const fs = require('fs'), path = require('path');
const { JSDOM } = require('jsdom');
const ROOT = require('path').join(__dirname, '..');
const bank = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/questions.json'), 'utf8'));

let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log('  ✓ ' + m)) : (fail++, console.log('  ✗ ' + m)); };

const dom = new JSDOM(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'), {
  runScripts: 'outside-only', url: 'https://example.github.io/net/', pretendToBeVisual: true,
});
const { window } = dom;
const doc = window.document;

// minimal shims jsdom lacks
window.fetch = () => Promise.resolve({ json: () => Promise.resolve(bank) });
window.alert = (m) => console.log('    [alert] ' + m);
window.URL.createObjectURL = () => 'blob:x';
window.URL.revokeObjectURL = () => {};
const store = {};
Object.defineProperty(window, 'localStorage', { value: {
  getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; }, clear: () => { for (const k in store) delete store[k]; },
}});

window.eval(fs.readFileSync(path.join(ROOT, 'js/app.js'), 'utf8'));

const $ = id => doc.getElementById(id);
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const key = k => doc.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true }));

setTimeout(() => {
  console.log('\n— load —');
  ok($('foot-count').textContent === String(bank.questions.length), `bank loaded (${bank.questions.length} questions)`);

  console.log('\n— start exam —');
  $('profile-input').value = 'testuser';
  $('profile-input').dispatchEvent(new window.Event('input', { bubbles: true }));
  click($('btn-start'));
  ok(!$('view-exam').hidden && $('view-home').hidden, 'exam view shown');
  ok($('grid').children.length === 40, 'navigator has 40 slots');
  ok($('q-total').textContent === '40', 'header says 40 questions');
  ok(/^(39|40):/.test($('timer-text').textContent), `timer running (${$('timer-text').textContent})`);
  ok($('btn-prev').disabled, 'Previous disabled on Q1');
  const opts1 = $('q-options').children.length;
  ok(opts1 >= 2, `Q1 rendered ${opts1} options`);

  console.log('\n— answering & navigation —');
  key('2');
  ok($('q-options').children[1].classList.contains('sel'), 'keyboard "2" selects option B');
  ok($('grid').children[0].classList.contains('answered'), 'navigator marks Q1 answered');
  ok($('answered-count').textContent === '1', 'answered counter = 1');
  key('ArrowRight');
  ok($('q-index').textContent === '2', 'arrow-right advances to Q2');
  click($('q-options').children[0].querySelector('input'));
  key('ArrowLeft');
  ok($('q-index').textContent === '1', 'arrow-left goes back to Q1');
  ok($('q-options').children[1].classList.contains('sel'), 'previous answer still selected after navigating back');
  click($('btn-clear'));
  ok(!$('q-options').children[1].classList.contains('sel'), 'Clear answer works');
  ok($('answered-count').textContent === '1', 'counter drops back after clearing');

  console.log('\n— flagging —');
  key('f');
  ok($('btn-flag').getAttribute('aria-pressed') === 'true', 'F key flags the question');
  ok($('flag-count').textContent === '1', 'flag count = 1');
  goto(7); function goto(n) { click($('grid').children[n - 1]); }
  key('f'); goto(19); key('f');
  ok($('flag-count').textContent === '3', 'three questions flagged');
  ok($('flag-list').children.length === 3, 'flag list shows 3 entries');
  ok(/^Q1/.test($('flag-list').children[0].textContent), 'flag list is ordered by question number');
  click($('flag-list').children[1].querySelector('button'));
  ok($('q-index').textContent === '7', 'clicking a flagged entry jumps to that question');
  key('f');
  ok($('flag-count').textContent === '2', 'unflagging removes it from the list');

  console.log('\n— persistence across reload —');
  const saved = JSON.parse(store['secaiplus:exam:testuser']);
  ok(saved && saved.items.length === 40, 'exam persisted to localStorage');
  ok(saved.items.filter(i => i.flagged).length === 2, 'flags persisted');

  console.log('\n— multi-answer question —');
  const multiIdx = saved.items.findIndex(it => bank.questions.find(q => q.id === it.id).type === 'multi');
  if (multiIdx >= 0) {
    goto(multiIdx + 1);
    ok(!$('q-type').hidden, 'multi-answer question shows "Select N answers" badge');
    ok($('q-options').querySelector('input').type === 'checkbox', 'multi question uses checkboxes');
    if (!$('btn-clear').disabled) click($('btn-clear'));   // this slot may already hold an answer
    key('1'); key('3');
    ok(JSON.parse(store['secaiplus:exam:testuser']).items[multiIdx].picked.length === 2, 'checkbox question keeps two choices');
    key('3');
    ok(JSON.parse(store['secaiplus:exam:testuser']).items[multiIdx].picked.length === 1, 'pressing the same key again unchecks it');
  } else { console.log('  (no multi-answer question in this draw — skipped)'); }

  console.log('\n— submit & grade —');
  // answer every question with the first option so grading has something to chew on
  for (let i = 1; i <= 40; i++) { goto(i); if (!$('btn-clear').disabled) continue; key('1'); }
  click($('btn-submit'));
  ok(!$('modal').hidden, 'submit opens confirmation modal');
  click($('modal-ok'));
  ok(!$('view-results').hidden, 'results view shown');
  const m = $('score-raw').textContent.match(/^(\d+) \/ 40$/);
  ok(!!m, `score rendered (${$('score-raw').textContent}, ${$('score-pct').textContent})`);
  ok($('review').children.length === 40, 'review lists all 40 questions');
  ok($('review').querySelectorAll('.tag.ok').length === Number(m[1]), 'review "correct" tags match the score');
  ok($('review').querySelectorAll('li.correct').length >= 40, 'every review item highlights its correct answer');

  console.log('\n— stats written —');
  const st = JSON.parse(store['secaiplus:stats:testuser']);
  ok(Object.keys(st).length === 40, '40 question stats recorded');
  const wrongCount = Object.values(st).filter(s => s.wrong === 1).length;
  ok(wrongCount === 40 - Number(m[1]), 'miss counts match the missed questions');
  ok(Object.values(st).every(s => s.seen === 1), 'each question seen once');
  ok(!store['secaiplus:exam:testuser'], 'in-progress exam cleared after submit');
  ok(JSON.parse(store['secaiplus:history:testuser']).length === 1, 'history entry written');

  console.log('\n— only-missed filter —');
  $('only-wrong').checked = true;
  $('only-wrong').dispatchEvent(new window.Event('change', { bubbles: true }));
  ok($('review').children.length === 40 - Number(m[1]) || $('review').textContent.includes('Nothing missed'),
     'filter shows only missed questions');

  console.log('\n— second exam is adaptive —');
  click($('btn-again'));
  const ex2 = JSON.parse(store['secaiplus:exam:testuser']);
  const repeats = ex2.items.filter(it => st[it.id]).length;
  const missedRepeats = ex2.items.filter(it => st[it.id] && st[it.id].wrong > 0).length;
  ok(ex2.items.length === 40, 'second exam drawn');
  ok(new Set(ex2.items.map(i => i.id)).size === 40, 'no duplicate questions within an exam');
  ok(missedRepeats > 0, `missed questions carried into exam 2 (${missedRepeats} of ${repeats} repeats)`);

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}, 60);
