// Loads the REAL weighting code out of js/app.js (everything up to "Exam lifecycle")
// and simulates a student who knows 70% of the bank.
const fs = require('fs');
const src = fs.readFileSync(require('path').join(__dirname,'../js/app.js'), 'utf8');
const core = src.slice(src.indexOf('const CONFIG'), src.indexOf('* Exam lifecycle')) + '*/';
let BANK, BY_ID;
const mod = eval(`(function(){ ${core}
  return {CONFIG, weightOf, isWeak, selectQuestions, setBank(b){BANK=b;BY_ID=new Map(b.map(q=>[q.id,q]));}, setStats(s){stats=s;}, getStats(){return stats;}};
})()`);

const bank = JSON.parse(fs.readFileSync(require('path').join(__dirname,'../data/questions.json'))).questions;
mod.setBank(bank);

// The student reliably knows 70% of questions; the other 30% they get right 25% of the time.
const knows = new Set(bank.filter(() => Math.random() < 0.70).map(q => q.id));
const stats = mod.getStats();
const stat = id => stats[id] || (stats[id] = {seen:0,right:0,wrong:0,streak:0});

console.log('attempt | drawn from miss-list | new(unseen) | already-mastered | score');
for (let a = 1; a <= 8; a++) {
  const ids = mod.selectQuestions();
  let fromMiss = 0, unseen = 0, mastered = 0, score = 0;
  for (const id of ids) {
    const s = stats[id];
    if (!s || !s.seen) unseen++;
    else if (s.wrong > 0 && s.streak < mod.CONFIG.MASTERY_STREAK) fromMiss++;
    else if (s.streak >= mod.CONFIG.MASTERY_STREAK) mastered++;
  }
  for (const id of ids) {
    const s = stat(id);
    s.seen++;
    const right = knows.has(id) || Math.random() < 0.25;
    if (right) { s.right++; s.streak++; score++; } else { s.wrong++; s.streak = 0; }
  }
  console.log(`   ${a}    |        ${String(fromMiss).padStart(2)} (${String(Math.round(fromMiss/ids.length*100)).padStart(3)}%)     |     ${String(unseen).padStart(2)}      |        ${String(mastered).padStart(2)}        |  ${score}/40`);
}
const outstanding = bank.filter(q => mod.isWeak(q.id)).length;
console.log('\nstill-weak questions after 8 attempts:', outstanding);
console.log('sample weights -> unseen:', mod.weightOf('zzz').toFixed(2),
  '| missed once:', (mod.CONFIG.MISS_WEIGHT[1]).toFixed(2),
  '| missed twice:', (mod.CONFIG.MISS_WEIGHT[2]).toFixed(2),
  '| right once after a miss:', (mod.CONFIG.MISS_WEIGHT[1]*mod.CONFIG.STREAK_DECAY).toFixed(2),
  '| right twice after a miss:', (mod.CONFIG.MISS_WEIGHT[1]*mod.CONFIG.STREAK_DECAY**2).toFixed(2));
