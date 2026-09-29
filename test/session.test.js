const fs = require('fs'), path = require('path');
const { JSDOM } = require('jsdom');
const ROOT = require('path').join(__dirname, '..');
const bank = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/questions.json'), 'utf8'));
let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log('  ✓ ' + m)) : (fail++, console.log('  ✗ ' + m)); };
const store = {};

function boot() {                       // simulates opening/reloading the page
  const dom = new JSDOM(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'),
    { runScripts: 'outside-only', url: 'https://x.github.io/n/', pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = () => Promise.resolve({ json: () => Promise.resolve(bank) });
  window.alert = m => console.log('    [alert] ' + m);
  window.URL.createObjectURL = () => 'blob:x'; window.URL.revokeObjectURL = () => {};
  Object.defineProperty(window, 'localStorage', { value: {
    getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; } } });
  window.eval(fs.readFileSync(path.join(ROOT, 'js/app.js'), 'utf8'));
  const doc = window.document;
  return { window, doc, $: id => doc.getElementById(id),
           click: el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })),
           key: k => doc.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true })) };
}
const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // ── session 1: start an exam, answer some, then "close the tab" ──
  let s = boot(); await wait(60);
  s.$('profile-input').value = 'alice';
  s.$('profile-input').dispatchEvent(new s.window.Event('input', { bubbles: true }));
  s.click(s.$('btn-start'));

  console.log('— single-answer behaviour —');
  s.key('1');
  ok(s.$('q-options').children[0].classList.contains('sel'), 'option A selected');
  s.key('3');
  ok(!s.$('q-options').children[0].classList.contains('sel') && s.$('q-options').children[2].classList.contains('sel'),
     'picking a second option replaces the first (radio, not checkbox)');
  ok(JSON.parse(store['secaiplus:exam:alice']).items[0].picked.length === 1, 'only one answer stored');

  s.click(s.$('grid').children[4]); s.key('2'); s.key('f');
  const before = JSON.parse(store['secaiplus:exam:alice']);
  const firstIds = before.items.map(i => i.id);

  console.log('\n— reload mid-exam —');
  s = boot(); await wait(60);
  ok(s.$('profile-input').value === 'alice', 'name remembered on reload');
  ok(!s.$('btn-resume').hidden, '"Resume exam in progress" button offered');
  s.click(s.$('btn-resume'));
  ok(!s.$('view-exam').hidden, 'exam resumed');
  const after = JSON.parse(store['secaiplus:exam:alice']);
  ok(JSON.stringify(after.items.map(i => i.id)) === JSON.stringify(firstIds), 'same 40 questions after reload');
  ok(after.items[0].picked.length === 1 && after.items[4].picked.length === 1, 'answers survived the reload');
  ok(after.items[4].flagged, 'flag survived the reload');
  ok(after.deadline === before.deadline, 'clock keeps counting from the original start (no reset exploit)');
  const t = s.$('timer-text').textContent;
  ok(/^(39|40):/.test(t), `resumed timer shows remaining time (${t})`);

  console.log('\n— time expiry auto-submits —');
  s = boot(); await wait(60);
  const ex = JSON.parse(store['secaiplus:exam:alice']);
  ex.deadline = Date.now() + 1200;                   // 1.2s left
  store['secaiplus:exam:alice'] = JSON.stringify(ex);
  s.click(s.$('btn-resume'));
  ok(!s.$('view-exam').hidden, 'exam running');
  await wait(2400);
  ok(!s.$('view-results').hidden, 'auto-submitted when the clock hit zero');
  ok(/time expired/.test(s.$('score-time').textContent), 'results say time expired');
  ok(!store['secaiplus:exam:alice'], 'expired exam cleared');
  const stats1 = JSON.parse(store['secaiplus:stats:alice']);
  ok(Object.keys(stats1).length === 40, 'unanswered questions still graded (as wrong)');
  ok(Object.values(stats1).filter(x => x.wrong).length >= 38, 'mostly-blank exam scored as misses');

  console.log('\n— expired exam is not resumable —');
  s = boot(); await wait(60);
  ok(s.$('btn-resume').hidden, 'no stale resume button after grading');
  ok(!s.$('stats-card').hidden, 'progress card now visible');
  ok(s.$('st-attempts').textContent === '1', 'one attempt recorded');
  ok(Number(s.$('st-weak').textContent) > 0, `weak list populated (${s.$('st-weak').textContent})`);

  console.log('\n— export / import moves progress to another machine —');
  let captured = null;
  s.window.Blob = class { constructor(parts) { captured = parts[0]; } };
  s.window.HTMLAnchorElement.prototype.click = function () {};
  s.click(s.$('btn-export'));
  ok(captured && JSON.parse(captured).app === 'secai-plus-practice-exam-generator', 'export produced a progress file');
  ok(Object.keys(JSON.parse(captured).stats).length === 40, 'export contains the stats');

  for (const k of Object.keys(store)) delete store[k];      // "new computer"
  s = boot(); await wait(60);
  ok(s.$('stats-card').hidden, 'fresh browser has no progress');
  s.window.FileReader = class {
    readAsText() { this.result = captured; this.onload(); }
  };
  s.$('file-import').dispatchEvent(Object.assign(new s.window.Event('change', { bubbles: true }), {}));
  // dispatch with a file present
  Object.defineProperty(s.$('file-import'), 'files', { value: [{ name: 'p.json' }], configurable: true });
  s.$('file-import').dispatchEvent(new s.window.Event('change', { bubbles: true }));
  ok(!s.$('stats-card').hidden, 'imported progress shows up');
  ok(s.$('st-attempts').textContent === '1', 'imported history intact');
  ok(Object.keys(JSON.parse(store['secaiplus:stats:alice'])).length === 40, 'imported stats persisted');

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
