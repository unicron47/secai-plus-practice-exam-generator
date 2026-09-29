#!/usr/bin/env python3
"""Validate generated explanations and exhibits, write the review report, and track spend.

  python3 tools/explain/check.py        # work/report.md + work/review.csv

Results reach students only through the master spreadsheet: export_master.py writes ready
explanations into column K and drafts into columns M-O for the instructor to approve.
"""
import csv, json, os, re
from collections import Counter
from common import MAX_WORDS, ROOT, WORK, bank, lead_in_index, letters, missing_exhibit, read, words

LETTER_REF = re.compile(r'\b(option|answer|choice)\s+[A-F]\b|\([A-F]\)|\b[A-F]\s+and\s+[A-F]\b')
META = re.compile(r'answer key|this question|the question writer|\b(this|stock|exam|known|recognized) item\b|'
                  r'well-known|accepted (answer|best)|documented answer|official exam', re.I)
STOP = {'the', 'and', 'for', 'use', 'set', 'with', 'from', 'that', 'this', 'are', 'was', 'not',
        'configure', 'implement', 'install', 'enable', 'an', 'a', 'to', 'of', 'on', 'in', 'is'}
ORDER = ['KEY WRONG?', 'AMBIGUOUS', 'NEW EXHIBIT', 'EXHIBIT: drop', 'EXHIBIT: pending', 'review', 'ready']

def stem(t):
    return t[:-1] if len(t) > 3 and t.endswith('s') else t

def spelled_out(acronym, expl):
    """True if the explanation expands the acronym: "IaaS" <- "Infrastructure as a Service"."""
    initials = ''.join(w[0] for w in re.findall(r'[A-Za-z]+', expl)).lower()
    return len(acronym) >= 2 and acronym in initials

def names_answer(expl, q):
    """Soft check: the explanation mentions each correct option (full text, acronym expansion,
    or enough of its words: half, or 40% for long paraphrasable options)."""
    e = expl.lower()
    squashed = re.sub(r'[\-/]', '', e)                         # "SD-WAN" matches "SDWAN"
    for i in q['answer']:
        opt = q['options'][i].lower()
        initials = ''.join(w[0] for w in re.findall(r'[a-z]+', opt))
        if len(initials) >= 3 and re.search(r'\b' + initials + r'\b', e):   # "NAT" for the spelled-out option
            continue
        toks = [stem(t.strip('.-/')) for t in re.findall(r'[a-z0-9.\-/]+', opt)]
        toks = [t for t in toks if len(t) > 1 and t not in STOP]
        if opt.strip('.') in e or re.sub(r'[\-/]', '', opt.strip('.')) in squashed or any(spelled_out(stem(t), expl) for t in toks if len(toks) <= 2):
            continue
        need = 0.4 if len(toks) >= 5 else 0.5
        if not toks or sum(t in e for t in toks) / len(toks) < need:
            return False
    return True

def lint(expl, q):
    problems = []
    n = words(expl)
    if n > MAX_WORDS:
        problems.append(f'too long ({n} words)')
    if n < 12:
        problems.append(f'too thin ({n} words)')
    if LETTER_REF.search(expl):
        problems.append('refers to an option by letter')
    if META.search(expl):
        problems.append('mentions the key/question')
    if not names_answer(expl, q):
        problems.append('does not name the correct answer')
    return problems

def exhibit_lines(exhibit):
    lines = exhibit.split('\n')
    bad = [l for l in lines if len(l) > 76]
    return [f'exhibit has {len(lines)} lines'] * (len(lines) > 16) + [f'{len(bad)} exhibit lines over 76 chars'] * bool(bad)

def assess(q, r1, r2, e, v):
    """-> (status, explanation, exhibit, reasons)"""
    key = letters(q['answer'])
    reasons = ['rule: ' + x for x in missing_exhibit(q)]
    has_exhibit = bool(q.get('images') or q.get('exhibit'))
    if r1 and r1['needs_exhibit'] and not has_exhibit:
        reasons.append('model: needs missing exhibit')

    if reasons and not (e and not e['exhibit_needed']):          # ── an exhibit question
        if not e:
            return 'EXHIBIT: pending', '', '', reasons
        if not e['feasible']:
            return 'EXHIBIT: drop', '', '', reasons + [f"generator: infeasible — {e['note']}"]
        if not v:
            return 'EXHIBIT: pending', '', e['exhibit'], reasons + ['not verified yet']
        if sorted(v['answer']) != key:
            return 'EXHIBIT: drop', '', e['exhibit'], reasons + [
                f"blind check answered {','.join(v['answer'])} ≠ key {','.join(key)} — {v['explanation']}"]
        if v['needs_exhibit']:
            return 'EXHIBIT: drop', '', e['exhibit'], reasons + [f"blind check still finds information missing — {v['note']}"]
        expl = e['explanation'] if not lint(e['explanation'], q) else v['explanation']
        return 'NEW EXHIBIT', expl, e['exhibit'], reasons + lint(expl, q) + exhibit_lines(e['exhibit'])

    if e and not e['exhibit_needed']:
        reasons.append('generator: no exhibit needed')
    if r1 and r1['needs_exhibit'] and has_exhibit:     # has an exhibit, yet the model says data is missing
        reasons.append('model: information still missing despite the exhibit')
    if not r1:
        return 'EXHIBIT: pending', '', '', reasons + ['no pass 1 result yet']
    expl = ''
    agrees = sorted(r1['answer']) == key
    if not agrees:
        reasons.append(f"blind answer {','.join(r1['answer'])} ≠ key {','.join(key)}")
    if r1['confidence'] != 'high':
        reasons.append(f"confidence {r1['confidence']}")
    if r2:
        reasons.append(f"adjudicated: {r2['verdict']}" +
                       (f" (better: {','.join(r2['better_answer'])})" if r2['verdict'] == 'key_wrong' else ''))
        if r2['verdict'] == 'key_correct':
            expl = r2['explanation']
    elif agrees:
        expl = r1['explanation']
    if expl:
        reasons += lint(expl, q)
    if r2 and r2['verdict'] == 'key_wrong':
        return 'KEY WRONG?', expl, '', reasons
    if (r2 and r2['verdict'] == 'ambiguous') or not expl:
        return 'AMBIGUOUS', expl, '', reasons
    return ('review' if reasons else 'ready'), expl, '', reasons

def usage_summary(p1, B):
    path = os.path.join(WORK, 'usage.jsonl')
    rows = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
    table = ['| stage | via | calls | questions | input tokens | output tokens | per question in / out | cost |',
             '|---|---|---:|---:|---:|---:|---|---:|']
    agg = {}
    for stage in ('pass1', 'pass2', 'exhibit', 'verify'):
        for via in ('cli', 'batch', 'direct'):
            rs = [r for r in rows if r['tag'].startswith(stage) and r.get('api', 'cli') == via]
            if not rs:
                continue
            n = sum(r['n'] for r in rs)
            tin = sum(r['input'] + r['cache_write'] + r['cache_read'] for r in rs)
            tout = sum(r['output'] for r in rs)
            cost = sum(r['cost_usd'] or 0 for r in rs)
            agg[stage] = (n, tin, tout, cost)
            label = {'cli': 'subscription (API-equivalent)', 'batch': 'API batch', 'direct': 'API direct'}[via]
            table.append(f'| {stage} | {label} | {len(rs)} | {n} | {tin:,} | {tout:,} | '
                         f'{tin // max(n, 1)} / {tout // max(n, 1)} | ${cost:.3f} |')
    spent = sum(r['cost_usd'] or 0 for r in rows if r.get('api') in ('batch', 'direct'))
    table += ['', f'**API credit spent so far: ${spent:.2f}**']
    return table

def main():
    B = {q['id']: q for q in bank()}
    p1, p2, ex, ver = read('pass1.json'), read('pass2.json'), read('exhibits.json'), read('verify.json')

    rows = []
    for qid in sorted(set(p1) | set(ex)):
        if qid in B:
            q = B[qid]
            status, expl, exhibit, reasons = assess(q, p1.get(qid), p2.get(qid), ex.get(qid), ver.get(qid))
            rows.append((q, p1.get(qid), p2.get(qid), status, expl, exhibit, reasons))
    rows.sort(key=lambda x: (ORDER.index(x[3]), x[0]['source'], x[0]['row']))

    with open(os.path.join(WORK, 'review.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['status', 'source', 'row', 'id', 'reasons', 'question', 'exhibit (generated)', 'options',
                    'key', 'model answer', 'explanation', 'words', 'instructor note'])
        for q, r1, r2, status, expl, exhibit, reasons in rows:
            note = (r2 or {}).get('note') or (ex.get(q['id']) or {}).get('note') or (r1 or {}).get('note', '')
            w.writerow([status, q['source'], q['row'], q['id'], '; '.join(reasons), q['text'], exhibit,
                        ' | '.join(f'{chr(65 + i)}. {o}' for i, o in enumerate(q['options'])),
                        ','.join(letters(q['answer'])), ','.join((r1 or {}).get('answer', [])), expl,
                        words(expl), note])

    counts = Counter(r[3] for r in rows)
    lengths = [words(r[4]) for r in rows if r[4]]
    rep = [f'# Explanation run — {len(rows)} of {len(B)} questions processed', '',
           '| status | count |', '|---|---:|'] + [f'| {k} | {counts[k]} |' for k in ORDER if counts[k]]
    rep += ['', f'Explanation length: min {min(lengths, default=0)}, max {max(lengths, default=0)}, '
                f'mean {sum(lengths) / max(len(lengths), 1):.0f} words (limit {MAX_WORDS}).', '',
            '## Token use and cost', ''] + usage_summary(p1, B)
    rep += ['', '## Needs the instructor', '']
    for q, r1, r2, status, expl, exhibit, reasons in rows:
        if status == 'ready':
            continue
        rep += [f"### {status} — {q['source']} row {q['row']} (`{q['id']}`)", '']
        lines = q['text'].split('\n')
        cut = lead_in_index(q['text']) + 1 if exhibit else len(lines)
        rep += ['> ' + l for l in lines[:cut]]
        if exhibit:
            rep += ['', '```', exhibit, '```', '']
            rep += ['> ' + l for l in lines[cut:]]
        rep += ['']
        rep += [f"- {chr(65 + i)}. {o}{'  **← key**' if i in q['answer'] else ''}" for i, o in enumerate(q['options'])]
        rep += ['', f"- **Flags:** {'; '.join(reasons) or '—'}"]
        if r1:
            rep += [f"- **Pass 1 (blind):** {','.join(r1['answer'])} — {r1['explanation']}" +
                    (f" _({r1['note']})_" if r1['note'] else '')]
        if r2:
            rep += [f"- **Adjudication:** {r2['verdict']} — {r2['note']}"]
        if q['id'] in ex and ex[q['id']]['note']:
            rep += [f"- **Exhibit generator:** {ex[q['id']]['note']}"]
        if expl:
            rep += [f'- **Draft explanation ({words(expl)} words):** {expl}']
        rep += ['']
    rep += ['## Ready', '']
    for q, r1, r2, status, expl, exhibit, reasons in rows:
        if status == 'ready':
            rep += [f"- **{q['source']} row {q['row']}**: {q['text'].splitlines()[-1][:90]}  ",
                    f"  → *{expl}* ({words(expl)} words)"]
    open(os.path.join(WORK, 'report.md'), 'w').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:rep.index('## Needs the instructor')]))
    print(f'\nwrote {WORK}/report.md and review.csv')

if __name__ == '__main__':
    main()
