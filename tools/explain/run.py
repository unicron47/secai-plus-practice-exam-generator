#!/usr/bin/env python3
"""Generate answer explanations (and replacement exhibits) through the Claude Message Batches API.

Run with the project venv:  tools/explain/.venv/bin/python tools/explain/run.py <stage> [...]

  pass1 --pilot 20 | --all | --ids a,b   blind answer + explanation (key NOT shown)   Sonnet 5, low
  pass2                                  adjudicate blind/key disagreements           Opus 5, high
  exhibit                                write replacement exhibits (key shown)       Opus 5, high
  verify                                 answer the repaired questions blind          Sonnet 5, medium
  explain --ids a,b                      explain an instructor-confirmed key          Opus 5, high
  audit                                  blind audit of every exhibit question        Fable 5.1, high
  then: python3 tools/explain/check.py

Add --direct for full-price immediate calls. Every stage prints an estimate first and refuses to submit above --max-usd (default $2).
Add --dry-run to see the estimate only. Batches cost 50% of standard prices. A submitted
batch id is saved in work/batches.json, so an interrupted run resumes instead of paying twice.

API key: $ANTHROPIC_API_KEY, else read from the file whose path is in tools/explain/key_path.local
(gitignored; keep the key itself outside the repo).
"""
import argparse, json, os, random, sys, time
from common import (HERE, LETTERS, ROOT, WORK, bank, exhibit_reasons, lead_in_index, letters, missing_exhibit, read,
                    with_exhibit, write)

MODELS = {'sonnet': 'claude-sonnet-5', 'opus': 'claude-opus-5', 'fable': 'claude-fable-5-1'}
PRICE = {'claude-sonnet-5': (2.00, 10.00), 'claude-opus-5': (5.00, 25.00),
         'claude-fable-5-1': (10.00, 50.00)}                              # $/1M in, out
BATCH_DISCOUNT = 0.5
KEY_PATH_FILE = os.path.join(HERE, 'key_path.local')           # gitignored: one line, the key file's path

def obj(props, required=None):
    return {'type': 'object', 'properties': props, 'required': required or list(props),
            'additionalProperties': False}

def items_schema(item):
    return obj({'items': {'type': 'array', 'items': item}})

S, B_, LET = {'type': 'string'}, {'type': 'boolean'}, {'type': 'string', 'enum': list(LETTERS)}
SCHEMAS = {
    'answer': items_schema(obj({'id': S, 'answer': {'type': 'array', 'items': LET}, 'explanation': S,
                                'needs_exhibit': B_, 'confidence': {'type': 'string', 'enum': ['high', 'medium', 'low']},
                                'note': S})),
    'adjudicate': items_schema(obj({'id': S, 'verdict': {'type': 'string', 'enum': ['key_correct', 'key_wrong', 'ambiguous']},
                                    'better_answer': {'type': 'array', 'items': LET}, 'explanation': S, 'note': S})),
    'explain': items_schema(obj({'id': S, 'explanation': S, 'concern': S})),
    'audit': items_schema(obj({'id': S, 'answer': {'type': 'array', 'items': LET},
                               'options': {'type': 'array', 'items': obj({'letter': LET, 'verdict': {
                                   'type': 'string', 'enum': ['correct', 'incorrect', 'also_defensible']}, 'reason': S})},
                               'sufficient': B_, 'unique': B_, 'issues': S, 'fix': S})),
    'exhibit': items_schema(obj({'id': S, 'exhibit_needed': B_, 'feasible': B_, 'exhibit': S, 'lead_in': S, 'explanation': S, 'note': S})),
}
# stage -> (system prompt, schema, model, effort, store, est. output tokens per question)
STAGES = {
    'pass1':   ('prompt.md',     'answer',     'sonnet', 'low',    'pass1.json',    200),
    'pass2':   ('adjudicate.md', 'adjudicate', 'opus',   'high',   'pass2.json',    900),
    'exhibit': ('exhibit.md',    'exhibit',    'opus',   'high',   'exhibits.json', 2500),
    'explain': ('explain.md',    'explain',    'opus',   'high',   'explain.json',  300),
    'audit':   ('audit.md',      'audit',      'fable',  'high',   'audit.json',    2000),
    'verify':  ('verify.md',     'answer',     'sonnet', 'medium', 'verify.json',   400),
}

def payload(q, text=None):
    p = {'id': q['id'], 'text': text or q['text'], 'select': len(q['answer']),
         'options': {LETTERS[i]: o for i, o in enumerate(q['options'])}}
    if q.get('images'):
        p['_images'] = q['images']            # sent as image blocks, not inside the JSON (see params)
    return p

def is_exhibit(q, r1=None):
    """A question that lost its exhibit (no image, no text exhibit) and needs one generated."""
    if q.get('images') or q.get('exhibit'):
        return False
    return bool(exhibit_reasons(q['text']) or (r1 or {}).get('needs_exhibit'))

MEDIA = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp'}

def content(chunk):
    """The questions as JSON, followed by each question's exhibit images (vision input)."""
    import base64
    items = [{k: v for k, v in it.items() if k != '_images'} for it in chunk]
    blocks = [{'type': 'text', 'text': json.dumps(items, ensure_ascii=False)}]
    for it in chunk:
        for n, path in enumerate(it.get('_images', []), 1):
            data = base64.standard_b64encode(open(os.path.join(ROOT, path), 'rb').read()).decode()
            blocks.append({'type': 'text', 'text': f"Exhibit image {n} for question {it['id']}:"})
            blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type':
                           MEDIA[os.path.splitext(path)[1].lower()], 'data': data}})
    return blocks if len(blocks) > 1 else blocks[0]['text']

def pilot_ids(n):
    """A deliberately awkward sample: suspected exhibits, multi-answer, bullets, then random."""
    rng = random.Random(22)
    B = bank()
    pick = rng.sample([q for q in B if missing_exhibit(q) or q.get('images')], 4)
    pick += rng.sample([q for q in B if q['type'] == 'multi'], 3)
    pick += rng.sample([q for q in B if '•' in q['text'] and q not in pick], 2)
    pick += rng.sample([q for q in B if q not in pick], n - len(pick))
    return [q['id'] for q in pick]

def select(stage, a, B):
    """-> list of request items for this stage (skipping ids already done)."""
    p1, done = read('pass1.json'), read(STAGES[stage][4])
    if stage == 'pass1':
        if a.pilot:
            ids = pilot_ids(a.pilot)
            write('pilot_ids.json', ids)
        elif a.ids:
            ids = a.ids.split(',')
        elif a.all:
            ids = list(B)
        else:
            sys.exit('pass1 needs --pilot N, --ids or --all')
        return [payload(B[i]) for i in ids if i not in done]
    if stage == 'pass2':      # exhibit questions are handled by the exhibit stage instead
        return [dict(payload(q), key=letters(q['answer']), reviewer_answer=r['answer'],
                     reviewer_explanation=r['explanation'], reviewer_note=r['note'])
                for i, r in p1.items() if (q := B.get(i)) and i not in done and not is_exhibit(q, r)
                and (sorted(r['answer']) != letters(q['answer']) or r['confidence'] == 'low')]
    if stage == 'exhibit':    # every suspected exhibit in the bank, not only those seen in pass 1
        return [dict(payload(q), key=letters(q['answer']),
                     lead_in=q['text'].split('\n')[lead_in_index(q['text'])])
                for i, q in B.items() if i not in done and is_exhibit(q, p1.get(i))]
    if stage == 'explain':    # instructor-confirmed key; explain it
        if not a.ids:
            sys.exit('explain needs --ids')
        return [dict(payload(q, with_exhibit(q['text'], q['exhibit'], q['exhibit_after']) if q.get('exhibit') else None),
                     key=letters(q['answer'])) for i in a.ids.split(',') if (q := B[i]) and i not in done]
    if stage == 'audit':      # every question that shows an exhibit, answered blind by a different model
        return [payload(q, with_exhibit(q['text'], q['exhibit'], q['exhibit_after']) if q.get('exhibit') else None)
                for i, q in B.items() if (q.get('exhibit') or q.get('images')) and i not in done]
    if stage == 'verify':     # the repaired question, answered blind
        ex = read('exhibits.json')
        out = []
        for i, e in ex.items():
            q = B.get(i)
            if q and i not in done and e['feasible'] and e['exhibit'].strip():
                out.append(payload(q, with_exhibit(q['text'], e['exhibit'], lead_in_index(q['text']))))
        return out

def estimate(stage, chunks):
    system, _, model, _, _, out_per_q = STAGES[stage]
    sys_tok = len(open(os.path.join(HERE, system)).read()) / 3.5 + 300     # + schema
    tin = sum(sys_tok + len(json.dumps(c)) / 3.5 + 1600 * sum(len(it.get('_images', [])) for it in c) for c in chunks)
    tout = sum(len(c) for c in chunks) * out_per_q
    pin, pout = PRICE[MODELS[model]]
    return tin, tout, (tin * pin + tout * pout) / 1e6 * BATCH_DISCOUNT

def client():
    import anthropic
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key and os.path.exists(KEY_PATH_FILE):
        key_file = os.path.expanduser(open(KEY_PATH_FILE).read().strip())
        key = open(key_file).read().strip() if os.path.exists(key_file) else None
    if not key:
        sys.exit('No API key: set ANTHROPIC_API_KEY, or put the key file\'s path in tools/explain/key_path.local')
    return anthropic.Anthropic(api_key=key)

def params(stage, chunk):
    system, schema, model, effort, _, _ = STAGES[stage]
    return dict(model=MODELS[model], max_tokens=16000,
                system=open(os.path.join(HERE, system)).read(),
                thinking={'type': 'adaptive'},
                output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': SCHEMAS[schema]}},
                messages=[{'role': 'user', 'content': content(chunk)}],
                # Fable 5.1: on a policy refusal the API re-runs the request on a fallback model (direct calls only)
                **({'betas': ['server-side-fallback-2026-06-01'], 'fallbacks': [{'model': 'claude-opus-4-8'}]}
                   if model == 'fable' else {}))

def submit(api, stage, chunks):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    reqs = [Request(custom_id=f'{stage}-{i:03d}', params=MessageCreateParamsNonStreaming(**params(stage, chunk)))
            for i, chunk in enumerate(chunks)]
    batch = api.messages.batches.create(requests=reqs)
    batches = read('batches.json')
    batches[stage] = {'id': batch.id, 'at': time.strftime('%Y-%m-%d %H:%M'), 'requests': len(reqs)}
    write('batches.json', batches)
    print(f'submitted batch {batch.id} ({len(reqs)} requests)')
    return batch.id

def save(stage, results, via):
    """results: [(tag, Message or None)]. Stores items, logs usage and cost per request."""
    _, _, model, effort, store, _ = STAGES[stage]
    done, (pin, pout) = read(store), PRICE[MODELS[model]]
    discount = BATCH_DISCOUNT if via == 'batch' else 1.0
    known = {q['id'] for q in bank()}
    tot_in = tot_out = n = failed = 0
    with open(os.path.join(WORK, 'usage.jsonl'), 'a') as log:
        for tag, msg in results:
            if msg is None:
                failed += 1
                continue
            u = msg.usage                           # billed even if the output is unusable
            tin = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
            cost = (tin * pin + u.output_tokens * pout) / 1e6 * discount
            items = []
            if msg.stop_reason in ('refusal', 'max_tokens'):
                failed += 1
                print(f'  {tag}: stopped ({msg.stop_reason}); re-run to retry', file=sys.stderr)
            else:
                items = json.loads(next(b.text for b in msg.content if b.type == 'text'))['items']
            for it in items:
                if it['id'] in known:
                    done[it['id']] = it
                else:                               # a mistyped id; that question is retried next run
                    print(f"  {tag}: unknown id {it['id']!r} dropped", file=sys.stderr)
            log.write(json.dumps({'tag': tag, 'n': len(items), 'model': MODELS[model], 'effort': effort,
                                  'input': tin, 'cache_write': 0, 'cache_read': 0, 'output': u.output_tokens,
                                  'cost_usd': round(cost, 5), 'api': via}) + '\n')
            tot_in, tot_out, n = tot_in + tin, tot_out + u.output_tokens, n + len(items)
    write(store, done)
    cost = (tot_in * pin + tot_out * pout) / 1e6 * discount
    print(f'{stage}: {n} questions saved, {failed} requests failed | {tot_in:,} in / {tot_out:,} out tokens | ${cost:.3f}')

def collect(api, stage, batch_id):
    while (b := api.messages.batches.retrieve(batch_id)).processing_status != 'ended':
        c = b.request_counts
        print(f'  {time.strftime("%H:%M:%S")} processing {c.processing}, done {c.succeeded}, errored {c.errored}', flush=True)
        time.sleep(30)
    results = []
    for r in api.messages.batches.results(batch_id):
        if r.result.type == 'succeeded':
            results.append((r.custom_id, r.result.message))
        else:
            print(f'  {r.custom_id}: {r.result.type} (re-run the stage to retry)', file=sys.stderr)
    save(stage, results, 'batch')
    batches = read('batches.json')
    batches.pop(stage, None)
    write('batches.json', batches)

def direct(api, stage, chunks, jobs=5):
    """Full-price Messages API calls, several at once; each response is streamed so long
    outputs cannot hit an HTTP timeout."""
    from concurrent.futures import ThreadPoolExecutor
    import anthropic
    def one(i_chunk):
        i, chunk = i_chunk
        tag = f'{stage}-{i:03d}'
        try:
            p = params(stage, chunk)
            client_ns = api.beta.messages if 'betas' in p else api.messages
            with client_ns.stream(**p) as s:
                msg = s.get_final_message()
            print(f'  {tag}: done by {msg.model} ({msg.usage.output_tokens:,} output tokens)', flush=True)
            return tag, msg
        except anthropic.APIStatusError as e:
            print(f'  {tag}: API error {e.status_code}: {e.message} (re-run to retry)', file=sys.stderr)
        except anthropic.APIConnectionError:
            print(f'  {tag}: connection error (re-run to retry)', file=sys.stderr)
        return tag, None
    with ThreadPoolExecutor(jobs) as ex:
        save(stage, list(ex.map(one, enumerate(chunks))), 'direct')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=list(STAGES))
    ap.add_argument('--pilot', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--ids', help='comma-separated question ids (required for explain; limits any stage)')
    ap.add_argument('--chunk', type=int, default=20, help='questions per request')
    ap.add_argument('--max-usd', type=float, default=2.0, help='refuse to submit above this estimate')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, help='only the first N questions (e.g. to measure cost)')
    ap.add_argument('--direct', action='store_true', help='full-price direct calls instead of a batch (faster, 2x cost)')
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    B = {q['id']: q for q in bank()}

    pending = read('batches.json').get(a.stage)
    if pending and not a.dry_run:                  # also collects a cancelled batch's finished requests
        print(f"resuming batch {pending['id']} submitted {pending['at']}")
        return collect(client(), a.stage, pending['id'])

    todo = select(a.stage, a, B)
    if a.ids and a.stage not in ('pass1', 'explain'):         # restrict any other stage to these ids
        wanted = set(a.ids.split(','))
        todo = [t for t in todo if t['id'] in wanted]
    if a.limit:
        todo = todo[:a.limit]
    chunk = min(a.chunk, 8) if a.stage == 'exhibit' else a.chunk      # exhibits need long outputs
    chunks = [todo[i:i + chunk] for i in range(0, len(todo), chunk)]
    tin, tout, usd = estimate(a.stage, chunks)
    if a.direct:
        usd /= BATCH_DISCOUNT
    print(f'{a.stage}: {len(todo)} questions in {len(chunks)} requests, '
          f'est. {tin:,.0f} in / {tout:,.0f} out tokens ≈ ${usd:.2f} ({"direct" if a.direct else "batch"} price)')
    if not todo or a.dry_run:
        return
    if usd > a.max_usd:
        sys.exit(f'estimate ${usd:.2f} is above --max-usd {a.max_usd}; raise it to proceed')
    api = client()
    if a.direct:
        direct(api, a.stage, chunks)
    else:
        collect(api, a.stage, submit(api, a.stage, chunks))

if __name__ == '__main__':
    main()
