#!/usr/bin/env python3
"""Convert the master question spreadsheet into data/questions.json for the adaptive exam app.

Columns: A question, B type, C-G options, H answer (option numbers, "1,4" for multi),
I time (unused), J exhibit images (paths inside the site such as images/q0027-1.png, one
per line), K answer explanation, L exhibit (a table or command output shown in a monospace
box). Text exhibit and images appear together after the question's "...the following:" line.
Columns M-O are the instructor's review notes and drafts; they are never published.
Q is option 6 (at the end so columns A-P never move). P is the question id. Students' progress is stored per id, so a question keeps its
progress when its wording is edited. A row with an empty P gets an id from a hash of
its text; clearing P deliberately resets a question's progress.

Re-run this whenever the spreadsheet changes:
    python3 tools/build_questions.py ["<a.xlsx>" "<b.xlsx>" ...] [out.json]
With no arguments it reads the paths listed in tools/sources.local.txt (gitignored). Question IDs are a hash
of the question text, so stats survive row reordering; when the same text appears
twice (in one file or across files) the first occurrence wins.
"""
import hashlib, json, os, re, sys, zipfile
from xml.etree import ElementTree as ET

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = {'m': M}

def cells(path):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
            shared.append(''.join(t.text or '' for t in si.iter(f'{{{M}}}t')))
    sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    for row in sheet.find('m:sheetData', NS):
        out = {}
        for c in row.findall('m:c', NS):
            col = ''.join(ch for ch in c.get('r') if ch.isalpha())
            inline, v = c.find('m:is', NS), c.find('m:v', NS)
            if inline is not None:
                val = ''.join(t.text or '' for t in inline.iter(f'{{{M}}}t'))
            elif v is None:
                continue
            elif c.get('t') == 's':
                val = shared[int(v.text)]
            else:
                val = v.text
            # an exhibit keeps its alignment; everything else is trimmed
            val = (val or '').strip('\n').rstrip() if col == 'L' else (val or '').strip()
            if val:
                out[col] = val
        yield out

def clean(s):
    return re.sub(r'\s+', ' ', s).strip()

# Line breaks were lost when the questions were exported to Excel, so bullets and the
# question stem run into the scenario text. Display-only: ids still hash clean(text).
STEM = r'(?:Which of the following|Which of these|Based on the information|Afterward,)'
MISSING_SPACE = r'\b(would|administrator|the|new|configured|an|this)(BEST|MOST|VPN|DHCP|AP|MTU|APIPA)\b'

def format_text(t):
    """Display text: line breaks typed in the cell are kept; lost ones are rebuilt; a bullet
    list gets a blank line above and below it."""
    t = re.sub(r'\s*[•✑]\s*', '\n• ', t)                           # bullets onto their own lines
    t = re.sub(MISSING_SPACE, r'\1 \2', t)                          # "wouldBEST" -> "would BEST"
    t = re.sub(r'(?<=[a-z)"’])\.(?=[A-Z][a-z])', '. ', t)            # "report.The" -> "report. The"
    t = re.sub(r'(?<=[a-z)]):(?=[A-Z])', ':\n', t)                  # "details:Switch" (glued) -> new line
    t = re.sub(r'(?<=[a-z])(?=(?:The|This|However|After|Now) )', '\n', t)  # "• SwitchThe connection"
    t = re.sub(r'(?<=[^\s\n])\s*(?=' + STEM + ')', '\n', t)           # stem glued to the scenario
    out = []
    for line in (l.strip() for l in t.split('\n')):
        if not line:
            continue
        in_list = bool(out) and out[-1].startswith('• ')
        if out and line.startswith('• ') != in_list:          # entering or leaving a bullet list
            out.append('')
        out.append(line)
    return '\n'.join(out)

STEM_RE = re.compile('^' + STEM)
ANNOUNCE_RE = re.compile(r'following|details:|settings:|specifications:|displaying|shown', re.I)

def lead_in_index(text):
    """Line index after which an exhibit belongs: the last "...following:" lead-in that has no
    content of its own, else the last line ending in ':', else just before the question stem
    (-1 means before the first line)."""
    lines = text.split('\n')
    lead_ins = [i for i, line in enumerate(lines)
                if line.endswith(':') and ANNOUNCE_RE.search(line)
                and (not (nxt := next((l for l in lines[i + 1:] if l), '')) or STEM_RE.match(nxt) or nxt.endswith(':'))]
    if lead_ins:                     # the last one: in the source PDFs the exhibit sits just before the stem
        return lead_ins[-1]
    colon = [i for i, l in enumerate(lines) if l.endswith(':')]
    if colon:
        return colon[-1]
    stems = [i for i, l in enumerate(lines) if STEM_RE.match(l)]
    if stems:                        # no lead-in: the exhibit IS the scenario, so it goes before the stem
        return stems[0] - 1          # -1 = before the first line
    return max(len(lines) - 2, -1)

TYPES = ('multiple choice', 'checkbox')

def unshift(r):
    """Repair a row whose cells slid one column left (type cell holds option 1).

    Seen in "Adaptive Quiz 1" row 329: B='5G', options in C-F, answer in G, time in H.
    Only applied when column B is not a known type AND the shifted reading is valid.
    """
    if r.get('B', '').lower() in TYPES or not r.get('B'):
        return None
    fixed = {'A': r['A'], 'B': 'Multiple Choice'}
    for a, b in zip('BCDEFGH', 'CDEFGHI'):
        if r.get(a):
            fixed[b] = r[a]
    opts = [c for c in 'CDEFG' if fixed.get(c)]
    ans = re.findall(r'\d+', fixed.get('H', ''))
    if len(ans) == 1 and 1 <= int(ans[0]) <= len(opts):
        return fixed
    return None

def read_rows(src):
    rows = list(cells(src))
    header, body = rows[0], rows[1:]
    assert header.get('A', '').lower().startswith('question'), f'unexpected header in {src}: {header}'
    return body

def main(srcs, dest):
    questions, seen_ids, skipped, repaired, missing_images = [], {}, [], [], []
    for src in srcs:
        name = re.sub(r'^Net\s+ExamTopics\s+', '', os.path.splitext(os.path.basename(src))[0])
        for i, r in enumerate(read_rows(src), start=2):
            if not r:                                   # blank row (formatting only)
                continue
            fixed = unshift(r)
            if fixed:
                repaired.append((name, i, r.get('B')))
                r = fixed

            raw = r.get('A', '')
            text = clean(raw)                           # single-line form: for the id hash and duplicates
            options = [clean(r[c]) for c in ('C', 'D', 'E', 'F', 'G', 'Q') if r.get(c)]   # Q = option 6
            raw_answer = r.get('H', '')
            answer = [int(n) - 1 for n in re.findall(r'\d+', raw_answer)]

            if not text or len(options) < 2 or not answer or any(a >= len(options) for a in answer):
                skipped.append((name, i, text[:60], 'answer=' + raw_answer))
                continue

            # First occurrence wins, so existing student stats keep pointing at the same wording/options.
            qid = r.get('P') or hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
            if qid in seen_ids:
                skipped.append((name, i, text[:60], 'DUPLICATE of %s row %d' % seen_ids[qid]))
                continue
            seen_ids[qid] = (name, i)

            q = {
                'id': qid,
                'source': name,
                'row': i,
                'text': format_text('\n'.join(clean(l) for l in raw.split('\n'))),
                'type': 'multi' if len(answer) > 1 or r.get('B', '').lower().startswith('checkbox') else 'single',
                'options': options,
                'answer': sorted(answer),
            }
            if r.get('K'):
                q['explanation'] = clean(r['K'])
            if r.get('L'):
                q['exhibit'] = r['L']
            images = [x.strip() for x in re.split(r'[\n;]', r.get('J', '')) if x.strip()]
            if images:
                q['images'] = images
                site = os.path.dirname(os.path.dirname(os.path.abspath(dest)))
                missing_images += [(name, i, x) for x in images if not os.path.exists(os.path.join(site, x))]
            if q.get('exhibit') or images:
                q['exhibit_after'] = lead_in_index(q['text'])
            questions.append(q)

    json.dump({'version': 1, 'count': len(questions), 'questions': questions},
              open(dest, 'w'), indent=1)
    print(f'wrote {len(questions)} questions -> {dest}')
    for src in srcs:
        print('  from', os.path.basename(src))
    print('  single:', sum(1 for q in questions if q['type'] == 'single'),
          ' multi:', sum(1 for q in questions if q['type'] == 'multi'),
          ' with explanation:', sum(1 for q in questions if 'explanation' in q),
          ' reformatted:', sum(1 for q in questions if '\n' in q['text']),
          ' with exhibit:', sum(1 for q in questions if 'exhibit' in q),
          ' with images:', sum(1 for q in questions if 'images' in q))
    for name, i, x in missing_images:
        print(f'  WARNING {name} row {i}: image {x} not found in the site folder')
    for name, i, b in repaired:
        print(f'  REPAIRED {name} row {i}: cells shifted one column left (type cell was {b!r})')
    if skipped:
        print(f'  SKIPPED {len(skipped)} rows:')
        for s in skipped:
            print('   %s row %s | %s | %s' % s)

# Default spreadsheet paths live in a gitignored file so no local paths end up in the repo.
# One path per line (several are merged in order), e.g.
#   /path/to/Net ExamTopics Master.xlsx
LOCAL_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources.local.txt')

if __name__ == '__main__':
    srcs = [a for a in sys.argv[1:] if a.endswith('.xlsx')]
    if not srcs and os.path.exists(LOCAL_SOURCES):
        srcs = [l.strip() for l in open(LOCAL_SOURCES) if l.strip() and not l.startswith('#')]
    if not srcs:
        sys.exit('usage: build_questions.py "/path/to/first.xlsx" ["/path/to/second.xlsx" ...] [out.json]\n'
                 '       (or list the paths in tools/sources.local.txt)')
    dests = [a for a in sys.argv[1:] if a.endswith('.json')]
    main(srcs, dests[0] if dests else 'data/questions.json')
