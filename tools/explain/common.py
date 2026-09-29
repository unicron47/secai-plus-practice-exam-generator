"""Shared helpers for the explanation pipeline (run.py, check.py)."""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from build_questions import ANNOUNCE_RE, STEM_RE, lead_in_index  # noqa: E402,F401  (one definition)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'work')          # gitignored: drafts, usage log, reports
LETTERS = 'ABCDEF'
MAX_WORDS = 60

def bank():
    return json.load(open(os.path.join(ROOT, 'data', 'questions.json')))['questions']

def letters(idx):
    return [LETTERS[i] for i in idx]

def words(s):
    return len(s.split())

def read(name, default=None):
    path = os.path.join(WORK, name)
    return json.load(open(path)) if os.path.exists(path) else ({} if default is None else default)

def write(name, obj):
    os.makedirs(WORK, exist_ok=True)
    json.dump(obj, open(os.path.join(WORK, name), 'w'), indent=1, ensure_ascii=False)

REFERS_RE = re.compile(
    r'following table|table (below|above)|\bthe table\b|chart above|\bexhibit\b|'
    r'(the|following) diagram|diagram (below|above)|shown (below|above)|'
    r'following (image|figure|topology|output|configuration|screenshot)', re.I)

def exhibit_reasons(text):
    """Rule-based: a lead-in ending in ':' with nothing after it, or a reference to a
    table/diagram/output. The model's needs_exhibit flag catches the rest."""
    reasons = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        nxt = next((l for l in lines[i + 1:] if l), '')           # skip blank spacer lines
        announces_data = ANNOUNCE_RE.search(line)   # not a fill-in-the-blank "an example of:"
        if line.endswith(':') and announces_data and (not nxt or STEM_RE.match(nxt) or nxt.endswith(':')):
            reasons.append('empty lead-in "%s"' % line[-40:])
    m = REFERS_RE.search(text)
    if m:
        reasons.append('refers to "%s"' % m.group(0))
    return reasons

def missing_exhibit(q):
    """Rule-based reasons a question looks like it lost its exhibit; none if it already has
    an image from the PDF or a text exhibit."""
    if q.get('images') or q.get('exhibit'):
        return []
    return exhibit_reasons(q['text'])

def with_exhibit(text, exhibit, after):
    lines = text.split('\n')
    return '\n'.join(lines[:after + 1] + ['[EXHIBIT]', exhibit, '[END EXHIBIT]'] + lines[after + 1:])
