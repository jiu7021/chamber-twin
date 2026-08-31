// UI · 애니메이션 · RoR 진단
import { Chamber, selftest, paToMtorr, mtorrToPa, m3sToLps } from './chamber.js';

const $ = (id) => document.getElementById(id);
const DT = 0.01;          // 물리 적분 스텝 [s]
const SUBSTEPS = 4;       // 프레임당 적분 횟수 → 실시간 배속 ≈ 4·0.01/0.0167 ≈ 2.4×
const HIST_S = 60;        // 차트 표시 구간 [s]

const ch = new Chamber();
let baseTheta = ch.theta;

// ---------------------------------------------------------------- 롤링 차트
class Trace {
  constructor(canvas, color, fmt) {
    this.cv = canvas; this.cx = canvas.getContext('2d');
    this.color = color; this.fmt = fmt || ((v) => v.toFixed(2));
    this.pts = []; this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas);
  }
  resize() {
    const r = this.cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    this.cv.width = Math.max(r.width * d, 10); this.cv.height = Math.max(r.height * d, 10);
    this.cx.setTransform(d, 0, 0, d, 0, 0); this.w = r.width; this.h = r.height;
  }
  push(t, v) {
    this.pts.push([t, v]);
    while (this.pts.length && this.pts[0][0] < t - HIST_S) this.pts.shift();
  }
  draw(marks) {
    const { cx, w, h } = this; cx.clearRect(0, 0, w, h);
    const cv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    if (this.pts.length < 2) return;
    const t1 = this.pts[this.pts.length - 1][0], t0 = t1 - HIST_S;
    let lo = Infinity, hi = -Infinity;
    for (const [, v] of this.pts) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const pad = (hi - lo) * 0.18 || Math.abs(hi) * 0.02 || 1;
    lo -= pad; hi += pad;
    const X = (t) => ((t - t0) / HIST_S) * w;
    const Y = (v) => h - 22 - ((v - lo) / (hi - lo)) * (h - 34);
    // 격자
    cx.strokeStyle = cv('--c-grid'); cx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = 12 + (i / 3) * (h - 34);
      cx.beginPath(); cx.moveTo(0, y); cx.lineTo(w, y); cx.stroke();
    }
    // 고장 주입 표시
    for (const m of marks || []) {
      if (m < t0) continue;
      cx.strokeStyle = cv('--c-mark'); cx.setLineDash([3, 3]);
      cx.beginPath(); cx.moveTo(X(m), 8); cx.lineTo(X(m), h - 18); cx.stroke();
      cx.setLineDash([]);
    }
    // 곡선
    cx.strokeStyle = cv(this.color); cx.lineWidth = 1.9; cx.lineJoin = 'round';
    cx.beginPath();
    this.pts.forEach(([t, v], i) => (i ? cx.lineTo(X(t), Y(v)) : cx.moveTo(X(t), Y(v))));
    cx.stroke();
    // 축 라벨
    cx.fillStyle = cv('--c-axis'); cx.font = '10px Inter, sans-serif';
    cx.fillText(this.fmt(hi), 4, 10); cx.fillText(this.fmt(lo), 4, h - 5);
    // 현재값은 캔버스가 아니라 헤더 요소에 쓴다 — 라벨과 겹치지 않게
    if (this.nowEl) this.nowEl.textContent = this.fmt(this.pts[this.pts.length - 1][1]);
  }
}

const trPress = new Trace($('c-press'), '--c-press', (v) => v.toFixed(2));
const trTheta = new Trace($('c-theta'), '--c-theta', (v) => v.toFixed(2));
const trSeff = new Trace($('c-seff'), '--c-seff', (v) => v.toFixed(1));
trPress.nowEl = $('n-press'); trTheta.nowEl = $('n-theta'); trSeff.nowEl = $('n-seff');
const faultMarks = [];

// ---------------------------------------------------------------- 도식 애니메이션
(function buildSvgDecor() {
  const ar = $('flow-arrows');
  for (let i = 0; i < 4; i++) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    p.setAttribute('points', '0,-3.4 7,0 0,3.4'); p.setAttribute('class', 'arrow');
    ar.appendChild(p);
  }
  const bl = $('tmp-blades');
  for (let i = 0; i < 6; i++) {
    const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    l.setAttribute('class', 'blade');
    l.setAttribute('x1', 210); l.setAttribute('y1', 248);
    l.setAttribute('x2', 210 + 12 * Math.cos((i * Math.PI) / 3));
    l.setAttribute('y2', 248 + 12 * Math.sin((i * Math.PI) / 3));
    bl.appendChild(l);
  }
})();

let flowPhase = 0, bladePhase = 0;
function animateSvg(s, dtReal) {
  const arrows = $('flow-arrows').children;
  const speed = 26 + 52 * Math.min(s.Q / 2.0, 1);
  flowPhase = (flowPhase + speed * dtReal) % 25;
  for (let i = 0; i < arrows.length; i++) {
    const x = 24 + ((flowPhase + i * 25) % 100);
    arrows[i].setAttribute('transform', `translate(${x},52)`);
    arrows[i].style.opacity = ch.gateClosed ? 0.12 : 0.85;
  }
  bladePhase += (s.sEff / ch.sPump0) * 620 * dtReal;
  $('tmp-blades').setAttribute('transform', `rotate(${bladePhase} 210 248)`);
  // 밸브 원판: 각도 0(폐쇄)에서 수평, π/2(개방)에서 수직으로 보이게 회전
  $('valve-disc').style.transform = `rotate(${(s.theta * 180) / Math.PI}deg)`;
  $('svg-press').textContent = paToMtorr(s.P).toFixed(1);
  $('svg-theta').textContent = `${((s.theta * 180) / Math.PI).toFixed(1)}°`;
  $('svg-pump').textContent = `${(ch.pumpDerate * 100).toFixed(0)} % · ${m3sToLps(ch.sPump).toFixed(0)} L/s`;
  $('leak-mark').classList.toggle('hidden', ch.qLeak <= 0 && ch.q1 <= 0);
  $('plasma').style.opacity = ch.gateClosed ? 0.25 : 1;
}

// ---------------------------------------------------------------- 계기 갱신
function updateGauges(s) {
  const mt = paToMtorr(s.P), sp = paToMtorr(ch.pSp);
  $('g-press').textContent = mt.toFixed(2);
  const dP = ((s.P - ch.pSp) / ch.pSp) * 100;
  const dEl = $('g-press-delta');
  dEl.textContent = `설정값 ${sp.toFixed(1)} mTorr 대비 ${dP >= 0 ? '+' : ''}${dP.toFixed(3)} %`;
  dEl.classList.toggle('hot', Math.abs(dP) > 1);

  const deg = (s.theta * 180) / Math.PI;
  $('g-theta').textContent = deg.toFixed(2);
  $('g-open').textContent = s.openPct.toFixed(1);
  const dTh = ((s.theta - baseTheta) / baseTheta) * 100;
  const tEl = $('g-theta-delta');
  tEl.textContent = `기준 대비 ${dTh >= 0 ? '+' : ''}${dTh.toFixed(2)} %`;
  tEl.classList.toggle('hot', Math.abs(dTh) > 1);

  $('g-seff').textContent = m3sToLps(s.sEff).toFixed(1);
  $('g-q').textContent = s.Q.toFixed(4);
  $('g-kn').textContent = s.Kn < 0.01 ? s.Kn.toExponential(2) : s.Kn.toFixed(3);
  $('g-regime').textContent = s.regime.name;
  $('g-time').textContent = s.t.toFixed(1);
}

// ---------------------------------------------------------------- 메인 루프
let last = performance.now();
function frame(now) {
  const dtReal = Math.min((now - last) / 1000, 0.1); last = now;
  let s;
  for (let i = 0; i < SUBSTEPS; i++) s = ch.step(DT);
  if (rorState.active) rorTick(s);
  updateGauges(s); animateSvg(s, dtReal);
  trPress.push(s.t, paToMtorr(s.P)); trTheta.push(s.t, (s.theta * 180) / Math.PI);
  trSeff.push(s.t, m3sToLps(s.sEff));
  trPress.draw(faultMarks); trTheta.draw(faultMarks); trSeff.draw(faultMarks);
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------- 컨트롤 바인딩
function bind(id, out, fmt, apply) {
  const el = $(id), o = $(out);
  const run = () => { const v = parseFloat(el.value); o.textContent = fmt(v); apply(v); };
  el.addEventListener('input', run); run();
}
const markFault = () => { faultMarks.push(ch.t); if (faultMarks.length > 12) faultMarks.shift(); };

bind('i-q', 'o-q', (v) => v.toFixed(3), (v) => { ch.qMfc = v; });
bind('i-sp', 'o-sp', (v) => v.toFixed(1), (v) => { ch.pSp = mtorrToPa(v); });
bind('i-leak', 'o-leak', (v) => v.toFixed(3), (v) => { if (v !== ch.qLeak) markFault(); ch.qLeak = v; });
bind('i-og', 'o-og', (v) => v.toFixed(3), (v) => {
  if (v > 0 && ch.q1 === 0) { ch.tOutgasStart = ch.t; markFault(); } ch.q1 = v;
});
bind('i-al', 'o-al', (v) => v.toFixed(2), (v) => { ch.alpha = v; });
bind('i-pump', 'o-pump', (v) => v.toFixed(0), (v) => {
  if (v / 100 !== ch.pumpDerate) markFault(); ch.pumpDerate = v / 100;
});
bind('i-wear', 'o-wear', (v) => v.toFixed(0), (v) => {
  if (v / 100 !== ch.valveWear) markFault(); ch.valveWear = v / 100;
});
bind('i-mfc', 'o-mfc', (v) => v.toFixed(2), (v) => { if (v !== ch.mfcOffset) markFault(); ch.mfcOffset = v; });

$('i-apc').addEventListener('change', (e) => {
  ch.apcOn = e.target.checked; markFault();
  $('apc-note').innerHTML = ch.apcOn
    ? '켜짐 — 밸브가 압력을 설정값에 붙든다. 고장은 압력이 아니라 <b>밸브 각도</b>에 나타난다.'
    : '꺼짐 — 밸브가 <b>지금 각도에 그대로 고정</b>된다. 이제 고장이 <b>압력</b>에 나타난다.'
      + '<br>이미 고장을 보상한 뒤에 끄면 압력이 안 움직인다. 기준 상태에서 끈 뒤 고장을 넣어야 '
      + '대조가 보인다 — 아래 시나리오 2번이 그 순서다.';
});

const setSlider = (id, v) => { const el = $(id); el.value = v; el.dispatchEvent(new Event('input')); };
function clearFaults() {
  ['i-leak', 'i-og', 'i-mfc'].forEach((i) => setSlider(i, 0));
  ['i-pump', 'i-wear'].forEach((i) => setSlider(i, 100));
  setSlider('i-al', 1.0);
}
$('b-clearfault').addEventListener('click', clearFaults);
$('b-reset').addEventListener('click', () => {
  clearFaults(); setSlider('i-q', 1.0); setSlider('i-sp', 40);
  $('i-apc').checked = true; $('i-apc').dispatchEvent(new Event('change'));
  ch.reset(); baseTheta = ch.theta; faultMarks.length = 0;
  [trPress, trTheta, trSeff].forEach((t) => (t.pts.length = 0));
  document.querySelectorAll('.scen-card').forEach((c) => c.classList.remove('on'));
});

// ---------------------------------------------------------------- 시나리오
// 시나리오는 **반드시 기준 운전점에서 출발**해야 대조가 성립한다.
// 이전 시나리오에서 밸브가 이미 고장을 보상한 각도에 있으면, APC 를 꺼도 그 각도에 얼어붙어
// 압력이 움직이지 않는다 — 물리적으로는 맞지만 보여주려는 대조가 사라진다.
const setApc = (on) => { $('i-apc').checked = on; $('i-apc').dispatchEvent(new Event('change')); };

const scenarios = {
  // APC 켠 채로 누설 → 압력 불변, 밸브만 이동
  leak: () => { clearFaults(); ch.softReset(); setApc(true); setSlider('i-leak', 0.12); },
  // APC 를 **먼저** 끄고(밸브가 기준각에 고정됨) 누설 → 이번엔 압력이 오른다
  apcoff: () => { clearFaults(); ch.softReset(); setApc(false); setSlider('i-leak', 0.12); },
  pump: () => { clearFaults(); ch.softReset(); setApc(true); setSlider('i-pump', 70); },
  ror: () => { clearFaults(); ch.softReset(); setApc(true);
               setSlider('i-leak', 0.05); setSlider('i-og', 0.08); setSlider('i-al', 1.0);
               setTimeout(() => $('b-ror').click(), 400); },
};
document.querySelectorAll('.scen-card').forEach((card) => {
  card.addEventListener('click', () => {
    document.querySelectorAll('.scen-card').forEach((c) => c.classList.remove('on'));
    card.classList.add('on'); scenarios[card.dataset.scen]();
  });
});

// ---------------------------------------------------------------- RoR 진단
// 게이트 폐쇄 후 V·dP/dt = Q_total. 적분형으로 적합해 실누설과 아웃가싱을 분리한다.
//   P(t) − P(t0) = (Q_leak/V)·(t − t0) + (q1/V)·∫ t^(−α) dt      α 는 소인해서 선택
const rorState = { active: false, t0: 0, dur: 60, samples: [] };
const rorCv = $('c-ror'), rorCx = rorCv.getContext('2d');

function estimateRoR(samples, V) {
  // physics/diagnostics.py 와 동일한 알고리즘 (단일 규약)
  //   M1  P−P₀ = (Q_leak/V)(t−t₀)                    실누설만
  //   M2  M1 + (q1/V)·∫t^(−α)dt                       아웃가싱 포함
  // t < T_MIN 표본은 **버린다**. 클램핑하면 설계행렬 0 행이 되는데 압력은 실제로
  // 상승하므로 모순 데이터가 되어 α 추정이 크게 치우친다.
  const T_MIN = 1.0, A_LO = 0.2, A_HI = 1.6, A_N = 141;
  const t0 = samples[0][0];
  const rows = samples.map(([t, p]) => [t - t0, p]).filter(([t]) => t >= T_MIN);
  if (rows.length < 20) return null;
  const tt = rows.map((r) => r[0]);
  const y = rows.map((r) => r[1] - rows[0][1]);
  const n = y.length;
  const basisOf = (a) => tt.map((t) => (Math.abs(a - 1) < 1e-9
    ? Math.log(t / tt[0]) : (Math.pow(t, 1 - a) - Math.pow(tt[0], 1 - a)) / (1 - a)));
  const x1 = tt.map((t) => t - tt[0]);
  const aic = (sse, k) => n * Math.log(Math.max(sse, 1e-300) / n) + 2 * k;

  // M1 — 원점통과 1변수
  let s11 = 0, b1 = 0;
  for (let i = 0; i < n; i++) { s11 += x1[i] * x1[i]; b1 += x1[i] * y[i]; }
  const c1 = s11 > 0 ? b1 / s11 : 0;
  let sse1 = 0;
  for (let i = 0; i < n; i++) { const r = y[i] - c1 * x1[i]; sse1 += r * r; }

  // M2 — α 격자 소인
  let best = null;
  for (let k = 0; k < A_N; k++) {
    const a = A_LO + ((A_HI - A_LO) * k) / (A_N - 1);
    const bs = basisOf(a);
    let m11 = 0, m12 = 0, m22 = 0, r1 = 0, r2 = 0;
    for (let i = 0; i < n; i++) {
      m11 += x1[i] * x1[i]; m12 += x1[i] * bs[i]; m22 += bs[i] * bs[i];
      r1 += x1[i] * y[i]; r2 += bs[i] * y[i];
    }
    const det = m11 * m22 - m12 * m12; if (Math.abs(det) < 1e-30) continue;
    const ca = (r1 * m22 - r2 * m12) / det, cb = (r2 * m11 - r1 * m12) / det;
    let sse = 0;
    for (let i = 0; i < n; i++) { const r = y[i] - (ca * x1[i] + cb * bs[i]); sse += r * r; }
    if (!best || sse < best.sse) best = { sse, a, ca, cb, bs };
  }
  if (!best) return { qLeak: c1 * V, q1: 0, alpha: NaN, accepted: false, reason: '적합 실패' };

  // 식별성 검사 — 셋 다 통과해야 아웃가싱 항을 채택한다
  const dAic = aic(sse1, 1) - aic(best.sse, 3);
  const contrib = Math.abs(best.cb * best.bs[n - 1]) / Math.max(Math.abs(y[n - 1]), 1e-30);
  const span = (A_HI - A_LO) / (A_N - 1);
  const railed = best.a <= A_LO + span * 0.6 || best.a >= A_HI - span * 0.6;
  let reason = '';
  if (best.cb <= 0) reason = '아웃가싱 계수 음수';
  else if (dAic < 10) reason = `AIC 개선 부족 (ΔAIC ${dAic.toFixed(1)})`;
  else if (railed) reason = `α 가 소인 경계 (${best.a.toFixed(2)}) — 기저 축퇴`;
  else if (contrib < 0.05) reason = `기여도 부족 (${(contrib * 100).toFixed(1)} %)`;

  if (reason) return { qLeak: c1 * V, q1: 0, alpha: NaN, accepted: false, reason };
  return { qLeak: best.ca * V, q1: best.cb * V, alpha: best.a, accepted: true, reason: '' };
}

function drawRoR() {
  const r = rorCv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  rorCv.width = r.width * d; rorCv.height = r.height * d;
  rorCx.setTransform(d, 0, 0, d, 0, 0);
  const w = r.width, h = r.height; rorCx.clearRect(0, 0, w, h);
  const S = rorState.samples; if (S.length < 2) return;
  const t0 = S[0][0], t1 = Math.max(S[S.length - 1][0], t0 + 1);
  let lo = Infinity, hi = -Infinity;
  for (const [, p] of S) { const v = paToMtorr(p); if (v < lo) lo = v; if (v > hi) hi = v; }
  if (hi - lo < 1e-9) hi = lo + 1;
  rorCx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--c-ror').trim(); rorCx.lineWidth = 1.9; rorCx.beginPath();
  S.forEach(([t, p], i) => {
    const x = ((t - t0) / (t1 - t0)) * w, y = h - 12 - ((paToMtorr(p) - lo) / (hi - lo)) * (h - 22);
    i ? rorCx.lineTo(x, y) : rorCx.moveTo(x, y);
  });
  rorCx.stroke();
  rorCx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--c-axis').trim(); rorCx.font = '10px Inter, sans-serif';
  rorCx.fillText('P [mTorr] 상승곡선', 6, 12);
}

function rorTick(s) {
  const el = rorState.samples;
  if (!el.length || s.t - el[el.length - 1][0] >= 0.2) el.push([s.t, s.P]);  // 실측과 같은 5 Hz
  const el2 = s.t - rorState.t0;
  $('ror-status').textContent = `측정 중… ${el2.toFixed(1)} / ${rorState.dur} s  (게이트 폐쇄)`;
  drawRoR();
  if (el2 >= rorState.dur) {
    rorState.active = false; ch.gateClosed = false;
    $('b-ror').disabled = false;
    $('ror-status').className = 'ror-status done';
    const e = estimateRoR(rorState.samples, ch.V);
    if (e) {
      $('r-ql').textContent = e.qLeak.toExponential(3);
      $('r-q1').textContent = e.accepted ? e.q1.toExponential(3) : '0 (기각)';
      $('r-al').textContent = e.accepted ? e.alpha.toFixed(3) : '—';
      let verdict;
      if (e.accepted && e.q1 > 0.5 * Math.abs(e.qLeak)) {
        verdict = e.alpha > 0.75 ? '아웃가싱 우세 (금속형 α≈1)' : '아웃가싱 우세 (폴리머형 α≈0.5)';
      } else if (e.qLeak > 5e-3) {
        verdict = '실누설 우세 (기울기 일정)';
      } else {
        verdict = '정상 — 유의한 가스부하 없음';
      }
      $('ror-status').textContent = `완료 — ${verdict}`
        + (e.accepted ? '' : `  ·  아웃가싱 기각: ${e.reason}`);
    }
  }
}

$('b-ror').addEventListener('click', () => {
  if (rorState.active) return;
  rorState.active = true; rorState.t0 = ch.t; rorState.samples = [];
  ch.gateClosed = true; ch.P = Math.max(ch.P * 0.02, mtorrToPa(0.4));  // 배기 후 시작
  // RoR 관례: 아웃가싱 시계는 챔버를 격리한 시점에서 다시 센다.
  // q(t) = q1·t^(−α) 의 t 원점을 격리 시점으로 두는 것이 표준 해석이며,
  // 추정기도 RoR 시작을 원점으로 보므로 이걸 맞춰야 α 추정이 정확해진다.
  ch.tOutgasStart = ch.t;
  $('b-ror').disabled = true;
  $('ror-status').className = 'ror-status run';
  $('r-qlt').textContent = ch.qLeak.toExponential(3);
  $('r-q1t').textContent = ch.q1.toExponential(3);
  $('r-alt').textContent = ch.alpha.toFixed(2);
  markFault();
});

// ---------------------------------------------------------------- 자기검증 표시
(function runSelftest() {
  const res = selftest();
  const box = $('selftest');
  box.innerHTML = res.map((r) => `
    <div class="st-item">
      <span class="st-dot ${r.ok ? 'ok' : 'no'}"></span>
      <span><span class="st-name">${r.name}</span><br><span class="st-detail">${r.detail}</span></span>
    </div>`).join('');
  const nOk = res.filter((r) => r.ok).length;
  const b = $('selftest-badge');
  b.textContent = `엔진 검증 ${nOk}/${res.length} 통과`;
  if (nOk !== res.length) b.classList.add('bad');
})();

requestAnimationFrame(frame);
