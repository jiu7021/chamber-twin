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
  if (!s.isProcessing) {
    for (let i = 0; i < arrows.length; i++) arrows[i].style.opacity = 0;
    $('valve-disc').style.transform = 'rotate(0deg)';
    $('svg-press').textContent = '0.0';
    $('svg-theta').textContent = '0.0°';
    $('svg-pump').textContent = `${(ch.pumpDerate * 100).toFixed(0)} % · 0 L/s`;
    $('leak-mark').classList.add('hidden');
    $('plasma').style.opacity = 0;
    return;
  }
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

// ---------------------------------------------------------------- FDC 알람 관제 콘솔 엔진 (CMP & P-T 스타일 헤리티지)
const fdcState = {
  filter: 'all',
  critCount: 0,
  warnCount: 0,
  autoCount: 0,
  pmAlarmActive: false,
  leakAlarmActive: false,
  lastPhase: '',
  feedLogs: [],
};

function initFdcConsole() {
  const consoleEl = $('fab-console');
  const launcherEl = $('fab-launcher');
  const btnMin = $('fab-min-btn');
  const btnClose = $('fab-close-btn');

  const openConsole = () => {
    if (consoleEl) consoleEl.classList.remove('is-closed');
    if (launcherEl) launcherEl.classList.add('is-hidden');
  };
  const closeConsole = () => {
    if (consoleEl) consoleEl.classList.add('is-closed');
    if (launcherEl) launcherEl.classList.remove('is-hidden');
  };

  if (btnMin) btnMin.addEventListener('click', closeConsole);
  if (btnClose) btnClose.addEventListener('click', closeConsole);
  if (launcherEl) launcherEl.addEventListener('click', openConsole);

  // HUD & 필터 탭 클릭 이벤트
  document.querySelectorAll('.fc-hud-box').forEach((box) => {
    box.addEventListener('click', () => {
      const filter = box.getAttribute('data-f');
      setFdcFilter(filter);
    });
  });

  document.querySelectorAll('.fc-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const filter = tab.getAttribute('data-f');
      setFdcFilter(filter);
    });
  });

  renderFdcHud();

  const params = new URLSearchParams(window.location.search);
  if (params.get('console') === 'open') {
    openConsole();
  }
}

function setFdcFilter(f) {
  fdcState.filter = f;
  document.querySelectorAll('.fc-tab').forEach((t) => {
    t.classList.toggle('on', t.getAttribute('data-f') === f);
  });
  renderFdcFeed();
}

function renderFdcHud() {
  const elCrit = $('fc-crit');
  const elWarn = $('fc-warn');
  const elAuto = $('fc-auto');
  const elCnt = $('fc-cnt');
  const elPulse = $('fc-pulse');
  const elLauncherDot = $('fab-launcher-dot');
  const elLauncherBadge = $('fab-badge');

  if (elCrit) elCrit.textContent = fdcState.critCount;
  if (elWarn) elWarn.textContent = fdcState.warnCount;
  if (elAuto) elAuto.textContent = fdcState.autoCount;
  const totalActive = fdcState.critCount + fdcState.warnCount;
  if (elCnt) elCnt.textContent = totalActive;

  if (elPulse) {
    if (fdcState.critCount > 0) {
      elPulse.className = 'fc-pulse crit';
    } else if (fdcState.warnCount > 0) {
      elPulse.className = 'fc-pulse warn';
    } else {
      elPulse.className = 'fc-pulse';
    }
  }

  if (elLauncherDot) {
    elLauncherDot.className = (fdcState.critCount > 0 || fdcState.warnCount > 0) ? 'fab-launcher-dot warn' : 'fab-launcher-dot';
  }
  if (elLauncherBadge) {
    if (fdcState.critCount > 0) {
      elLauncherBadge.textContent = `설비이상 (${fdcState.critCount})`;
      elLauncherBadge.style.color = '#ff453a';
    } else if (fdcState.warnCount > 0) {
      elLauncherBadge.textContent = `세정권고 (${fdcState.warnCount})`;
      elLauncherBadge.style.color = '#ff9f0a';
    } else {
      elLauncherBadge.textContent = `정상 (${fdcState.autoCount > 0 ? fdcState.autoCount : 0})`;
      elLauncherBadge.style.color = 'var(--neon-cyan)';
    }
  }
}

function addFdcFeedLog(type, tag, title, desc) {
  const timeStr = (ch && ch.t !== undefined ? ch.t.toFixed(1) : '0.0') + 's';
  fdcState.feedLogs.unshift({ type, tag, title, desc, time: timeStr });
  if (fdcState.feedLogs.length > 25) fdcState.feedLogs.pop();
  renderFdcFeed();
}

function renderFdcFeed() {
  const feedEl = $('console-feed');
  if (!feedEl) return;
  const filtered = fdcState.filter === 'all'
    ? fdcState.feedLogs
    : fdcState.feedLogs.filter((item) => item.type === fdcState.filter);

  if (filtered.length === 0) {
    feedEl.innerHTML = '<div class="fc-feed-empty">해당 분류의 수신 내역이 없습니다.</div>';
    return;
  }

  feedEl.innerHTML = filtered.map((item) => `
    <div class="fc-card ${item.type}">
      <div class="fc-card-top">
        <span class="fc-card-tag ${item.type}">${item.tag}</span>
        <span class="fc-card-time font-mono">${item.time}</span>
      </div>
      <div class="fc-card-title">${item.title}</div>
      ${item.desc ? `<div class="fc-card-desc">${item.desc}</div>` : ''}
    </div>
  `).join('');
}

function resetFdcPmAlarm() {
  if (fdcState.pmAlarmActive) {
    fdcState.pmAlarmActive = false;
    fdcState.warnCount = Math.max(0, fdcState.warnCount - 1);
    renderFdcHud();
    const pinnedEl = $('console-pinned');
    if (pinnedEl) {
      pinnedEl.innerHTML = '<div class="fc-pinned-empty">현재 긴급 세정 권고 없음 (챔버 내벽 정상)</div>';
    }
  }
  addFdcFeedLog('auto', '🧼 WAC CLEAN', '챔버 플라즈마 건식 세정 완료', '내벽 폴리머 오염도 0% 초기화 및 밸브 제어 마진 100% 복구');
}

function evaluateFdcAlarms(s, clogPct, deg) {
  // 1. 챔버 내벽 오염도 한계 도달 (WAC 세정 필요 알람)
  const pinnedEl = $('console-pinned');
  if (clogPct >= 75 && !fdcState.pmAlarmActive) {
    fdcState.pmAlarmActive = true;
    fdcState.warnCount++;
    renderFdcHud();

    if (pinnedEl) {
      pinnedEl.innerHTML = `
        <div class="fc-card warn" id="card-clog-pm">
          <div class="fc-card-top">
            <span class="fc-card-tag warn">🟡 PM REQUIRED</span>
            <span class="fc-card-time font-mono">${s.t.toFixed(1)}s</span>
          </div>
          <div class="fc-card-title">⚠️ 챔버 내벽 폴리머 증착 임계 (오염도 ${clogPct.toFixed(0)}%)</div>
          <div class="fc-card-desc">C₄F₈ 연속 가공으로 배기 단면적 축소 · 밸브 제어 마진 고갈 위험</div>
          <button type="button" class="fc-action-btn" id="btn-fc-clean">🧼 지금 챔버 세정(WAC) 실행</button>
        </div>
      `;
      const btnFcClean = $('btn-fc-clean');
      if (btnFcClean) {
        btnFcClean.addEventListener('click', () => {
          cleanLot(true);
        });
      }
    }
  } else if (clogPct < 75 && fdcState.pmAlarmActive) {
    fdcState.pmAlarmActive = false;
    fdcState.warnCount = Math.max(0, fdcState.warnCount - 1);
    renderFdcHud();
    if (pinnedEl) {
      pinnedEl.innerHTML = '<div class="fc-pinned-empty">현재 긴급 세정 권고 없음 (챔버 내벽 정상)</div>';
    }
  }

  // 2. 누설 감지 고장 인터락 알람
  const hasLeak = (ch.qLeak && ch.qLeak > 0) || (ch.q1 && ch.q1 > 0);
  if (hasLeak && !fdcState.leakAlarmActive) {
    fdcState.leakAlarmActive = true;
    fdcState.critCount++;
    renderFdcHud();
    const qVal = (ch.qLeak > 0 ? ch.qLeak : ch.q1).toFixed(3);
    addFdcFeedLog('crit', '🔴 VAC LEAK', `진공 누설 감지 (Q_leak=${qVal} Pa·m³/s)`, '챔버 밀폐 불량 또는 아웃가싱 과다 · 밸브 강제 개방 보상 중');
  } else if (!hasLeak && fdcState.leakAlarmActive) {
    fdcState.leakAlarmActive = false;
    fdcState.critCount = Math.max(0, fdcState.critCount - 1);
    renderFdcHud();
    addFdcFeedLog('auto', '🟢 LEAK CLEAR', '진공 누설 정상 복구', 'Q_leak = 0 Pa·m³/s · 베이스라인 회귀');
  }

  // 3. 가스 전환 시 실시간 APC 제어 스트림 로그 등록 (중복 방지: 위상 바뀔 때 1회)
  const currentPhase = s.boschMode ? s.boschPhase : 'steady';
  if (currentPhase !== fdcState.lastPhase) {
    fdcState.lastPhase = currentPhase;
    fdcState.autoCount++;
    renderFdcHud();

    if (s.boschMode) {
      const isPass = s.boschPhase === 'pass';
      const gasName = isPass ? 'C₄F₈ 보호막 단계' : 'SF₆ 식각 단계';
      const flowSccm = isPass ? '385.0 sccm' : '817.2 sccm';
      const desc = `공급 유량 ${flowSccm} 유입 · 40.0 mTorr 사수를 위해 스로틀 밸브 θ=${deg.toFixed(1)}° 즉각 보상`;
      addFdcFeedLog('auto', '⚡ APC CLOSED-LOOP', `${gasName} 밸브 연동 보정`, desc);
    } else {
      addFdcFeedLog('auto', '⚡ APC CLOSED-LOOP', '정속 Ar 정상상태 제어', `유량 592.2 sccm · 스로틀 밸브 θ=${deg.toFixed(1)}° 정격 안정화`);
    }
  }
}

// ---------------------------------------------------------------- 계기 갱신 (자동차 속도계 다이얼 & 가로 게이지 연동)
function updateGauges(s) {
  const needle = $('speedo-needle-group');
  const arcFill = $('speedo-arc-fill');
  const elFillP = $('bar-fill-press');
  const elFillS = $('bar-fill-seff');
  const elFillQ = $('bar-fill-q');
  const badgeP = $('g-press-status-badge');
  const tagAuto = $('speedo-live-tag');

  if (!s.isProcessing) {
    // 1. 디지털 수치 클램핑
    $('g-press').textContent = '0.00';
    const dEl = $('g-press-delta');
    dEl.textContent = '공정 대기 (IDLE) · 펌프 스탠바이';
    dEl.classList.remove('hot');

    $('g-theta').textContent = '0.00';
    $('g-open').textContent = '0.0';
    const tEl = $('g-theta-delta');
    tEl.textContent = '공정 대기 (IDLE)';
    tEl.classList.remove('hot');

    $('g-seff').textContent = '0.0';
    $('g-q').textContent = '0.0000';
    const elKn = $('g-kn'); if (elKn) elKn.textContent = '0.000';
    const elReg = $('g-regime'); if (elReg) elReg.textContent = '공정 대기';
    const elClog = $('g-clog'); if (elClog) elClog.textContent = '0.0%';
    const elClogBadge = $('g-clog-badge');
    if (elClogBadge) {
      elClogBadge.textContent = 'CLEAN';
      elClogBadge.className = 'h-meter-badge ok';
    }
    const elFillClog = $('bar-fill-clog');
    if (elFillClog) elFillClog.style.width = '0%';
    const elClogMargin = $('g-clog-margin');
    if (elClogMargin) elClogMargin.textContent = '100%';
    $('g-time').textContent = s.t.toFixed(1);

    // 2. 속도계 게이지 (IDLE: 바닥 0° 위치 휴지)
    if (needle) needle.setAttribute('transform', 'rotate(-120, 120, 80)');
    if (arcFill) arcFill.style.strokeDashoffset = '276.5';
    if (tagAuto) {
      tagAuto.textContent = 'STANDBY';
      tagAuto.style.borderColor = 'rgba(255,255,255,0.15)';
      tagAuto.style.color = 'var(--ink-40)';
    }

    // 3. 가로 막대그래프 (0% 고정)
    if (elFillP) elFillP.style.width = '0%';
    if (elFillS) elFillS.style.width = '0%';
    if (elFillQ) elFillQ.style.width = '0%';
    if (badgeP) {
      badgeP.textContent = 'STANDBY';
      badgeP.className = 'h-meter-badge standby';
    }
    return;
  }

  // ── 가동 중(RUNNING) 실시간 계측 및 애니메이션 ──
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
  const elKn = $('g-kn'); if (elKn) elKn.textContent = s.Kn < 0.01 ? s.Kn.toExponential(2) : s.Kn.toFixed(3);
  const elReg = $('g-regime'); if (elReg) elReg.textContent = s.regime.name;
  $('g-time').textContent = s.t.toFixed(1);

  // 1. 자동차 속도계 바늘 & 아크 회전
  // 스케일: 0° -> -120° 회전, 90° -> +120° 회전 (총 240° 스팬)
  const degClamped = Math.max(0, Math.min(90, deg));
  const rot = -120 + (degClamped / 90) * 240;
  if (needle) needle.setAttribute('transform', `rotate(${rot.toFixed(1)}, 120, 80)`);
  if (arcFill) {
    const arcPct = degClamped / 90;
    arcFill.style.strokeDashoffset = (276.5 * (1 - arcPct)).toFixed(1);
  }
  if (tagAuto) {
    tagAuto.textContent = ch.apcOn ? '● APC AUTO' : '⚠️ APC OFF';
    tagAuto.style.borderColor = ch.apcOn ? 'rgba(0, 240, 255, 0.4)' : 'rgba(255, 69, 58, 0.4)';
    tagAuto.style.color = ch.apcOn ? 'var(--neon-cyan)' : '#ff453a';
  }

  // 2. 가로 막대 1: 챔버 압력 (0~80 mTorr, 40 mTorr = 50%)
  const pPct = Math.max(0, Math.min(100, (mt / 80) * 100));
  if (elFillP) {
    elFillP.style.width = `${pPct.toFixed(1)}%`;
    if (Math.abs(mt - sp) <= 1.0) {
      elFillP.style.background = 'linear-gradient(90deg, #10b981 0%, #00f0ff 100%)';
    } else {
      elFillP.style.background = 'linear-gradient(90deg, #ff9f0a 0%, #ff453a 100%)';
    }
  }
  if (badgeP) {
    if (Math.abs(mt - sp) <= 0.8) {
      badgeP.textContent = 'STABLE (초안정)';
      badgeP.className = 'h-meter-badge ok';
    } else if (Math.abs(mt - sp) <= 2.5) {
      badgeP.textContent = 'COMPENSATING';
      badgeP.className = 'h-meter-badge warn';
    } else {
      badgeP.textContent = 'UNSTABLE';
      badgeP.className = 'h-meter-badge bad';
    }
  }

  // 3. 가로 막대 2: 유효 배기속도 (0~300 L/s)
  const seffLps = m3sToLps(s.sEff);
  const seffPct = Math.max(0, Math.min(100, (seffLps / 300) * 100));
  if (elFillS) elFillS.style.width = `${seffPct.toFixed(1)}%`;

  // 4. 가로 막대 3: 총 스루풋 Q (0~2.0 Pa·m³/s)
  const qPct = Math.max(0, Math.min(100, (s.Q / 2.0) * 100));
  if (elFillQ) elFillQ.style.width = `${qPct.toFixed(1)}%`;

  // 5. 가로 막대 4: 챔버 내벽 오염도 (Wall Clog) & 세정 마진
  const elClog = $('g-clog');
  const elClogBadge = $('g-clog-badge');
  const elFillClog = $('bar-fill-clog');
  const elClogMargin = $('g-clog-margin');

  // 오염도 계산: 10매 시퀀스에서 웨이퍼 진행도에 따라 오염 누적
  // 1매: 0%, 5매: 38%, 8매: 66%, 9매: 76% (주의), 10매: 88% (세정 필요)
  // C4F8 패시베이션 단계 시 폴리머 증착으로 일시 미세 상승(+3.5%)
  const waferIdx = (lotState && lotState.currentWafer) ? lotState.currentWafer : 1;
  const waferRatio = Math.max(0, Math.min(1, (waferIdx - 1) / 9));
  const passBonus = (s.boschMode && s.boschPhase === 'pass') ? 3.5 : 0.0;
  const clogPct = Math.max(0, Math.min(100, waferRatio * 85 + passBonus));
  const marginPct = Math.max(0, 100 - clogPct);

  if (elClog) elClog.textContent = `${clogPct.toFixed(1)}%`;
  if (elFillClog) elFillClog.style.width = `${clogPct.toFixed(1)}%`;
  if (elClogMargin) elClogMargin.textContent = `${marginPct.toFixed(0)}%`;

  if (elClogBadge) {
    if (clogPct < 60) {
      elClogBadge.textContent = 'CLEAN';
      elClogBadge.className = 'h-meter-badge ok';
    } else if (clogPct < 75) {
      elClogBadge.textContent = 'ACCUM';
      elClogBadge.className = 'h-meter-badge warn';
    } else {
      elClogBadge.textContent = 'WAC REQ';
      elClogBadge.className = 'h-meter-badge bad';
    }
  }

  // FDC 알람 엔진 평가 및 콘솔 실시간 연동
  evaluateFdcAlarms(s, clogPct, deg);
}

// ---------------------------------------------------------------- 3D / 2D 뷰포트 토글 모드
let currentViewMode = '3d';
const btn3d = $('btn-view-3d');
const btn2d = $('btn-view-2d');
const wrap3d = $('chamber-3d-wrap');
const svgChamber = $('chamber-svg');
const btnReset3d = $('btn-3d-reset');

function setViewMode(mode) {
  currentViewMode = mode;
  if (btn3d) btn3d.classList.toggle('on', mode === '3d');
  if (btn2d) btn2d.classList.toggle('on', mode === '2d');
  if (wrap3d) wrap3d.style.display = mode === '3d' ? 'flex' : 'none';
  if (svgChamber) svgChamber.style.display = mode === '2d' ? 'block' : 'none';
  if (window.Chamber3D) {
    window.Chamber3D.setActive(mode === '3d');
  }
}

if (btn3d) btn3d.addEventListener('click', () => setViewMode('3d'));
if (btn2d) btn2d.addEventListener('click', () => setViewMode('2d'));
if (btnReset3d && window.Chamber3D) {
  btnReset3d.addEventListener('click', () => window.Chamber3D.resetView());
}

// 3D 엔진 초기화
let has3D = false;
const urlParams = new URLSearchParams(window.location.search);
const initialMode = urlParams.get('view') === '2d' ? '2d' : '3d';
try {
  if (window.Chamber3D && window.Chamber3D.init('chamber-3d-wrap')) {
    has3D = true;
    setViewMode(initialMode);
  } else {
    setViewMode('2d');
  }
} catch (e) {
  console.warn('3D initialization failed:', e);
  setViewMode('2d');
}

// ---------------------------------------------------------------- 공정 모드 토글 (정속 정상상태 vs 보쉬 DRIE)
const btnSteady = $('btn-mode-steady');
const btnBosch = $('btn-mode-bosch');

function setProcessMode(isBosch) {
  ch.boschMode = isBosch;
  if (btnSteady) btnSteady.classList.toggle('on', !isBosch);
  if (btnBosch) btnBosch.classList.toggle('on', isBosch);
}

if (btnSteady) btnSteady.addEventListener('click', () => setProcessMode(false));
if (btnBosch) btnBosch.addEventListener('click', () => setProcessMode(true));

// 기본 공정 모드: 보쉬(Bosch DRIE) 고속 펄스 공정 기본 활성화!
setProcessMode(true);
if (urlParams.get('mode') === 'steady') {
  setProcessMode(false);
}
if (urlParams.get('gas') === 'c4f8') {
  ch.boschTimer = 4.8;
}

// ---------------------------------------------------------------- 10매 로트(Lot) 가상계측(VM) 관리자 (Zenodo 96매 실측 연동)
const lotState = {
  currentLot: 1,        // 1 ~ 10
  currentWafer: 1,      // 1 ~ 10
  history: [],          // W2W depth_pct for current lot
  autoTimer: null
};

const cvSaw = $('c-lot-sawtooth');
const cxSaw = cvSaw ? cvSaw.getContext('2d') : null;

function drawSawtooth() {
  if (!cvSaw || !cxSaw) return;
  const r = cvSaw.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  cvSaw.width = Math.max(r.width * d, 10);
  cvSaw.height = Math.max(r.height * d, 10);
  cxSaw.setTransform(d, 0, 0, d, 0, 0);
  const w = r.width, h = r.height;
  cxSaw.clearRect(0, 0, w, h);

  // Y 범위: 96.0% ~ 101.0%
  const lo = 96.0, hi = 101.0;
  const Y = (v) => h - 14 - ((v - lo) / (hi - lo)) * (h - 26);
  const X = (wf) => 18 + ((wf - 1) / 9) * (w - 36);

  // 100% 기준선 및 97.28%(-2.72%) 관리한계 점선
  cxSaw.strokeStyle = 'rgba(255, 255, 255, 0.12)';
  cxSaw.lineWidth = 1;
  cxSaw.setLineDash([3, 3]);
  const y100 = Y(100.0);
  cxSaw.beginPath(); cxSaw.moveTo(0, y100); cxSaw.lineTo(w, y100); cxSaw.stroke();

  const y97 = Y(97.28);
  cxSaw.strokeStyle = 'rgba(255, 69, 58, 0.35)';
  cxSaw.beginPath(); cxSaw.moveTo(0, y97); cxSaw.lineTo(w, y97); cxSaw.stroke();
  cxSaw.setLineDash([]);

  // 10매 실측 톱니 곡선
  if (lotState.history.length > 0) {
    cxSaw.strokeStyle = '#ff453a';
    cxSaw.lineWidth = 2.2;
    cxSaw.lineJoin = 'round';
    cxSaw.beginPath();
    lotState.history.forEach((val, i) => {
      const x = X(i + 1), y = Y(val);
      i === 0 ? cxSaw.moveTo(x, y) : cxSaw.lineTo(x, y);
    });
    cxSaw.stroke();

    // 데이터 포인트
    lotState.history.forEach((val, i) => {
      const x = X(i + 1), y = Y(val);
      const isCur = (i + 1 === lotState.currentWafer);
      cxSaw.fillStyle = isCur ? '#00f0ff' : '#ff453a';
      cxSaw.beginPath();
      cxSaw.arc(x, y, isCur ? 4.5 : 3.0, 0, Math.PI * 2);
      cxSaw.fill();
    });
  }

  // 100% 및 97.28% 라벨
  cxSaw.fillStyle = 'rgba(255, 255, 255, 0.4)';
  cxSaw.font = '9px monospace';
  cxSaw.fillText('100.0%', w - 38, y100 - 3);
  cxSaw.fillText('97.28%', w - 38, y97 + 10);
}

if (cvSaw) {
  new ResizeObserver(() => drawSawtooth()).observe(cvSaw);
}

function updateLotUI() {
  const dataset = window.LOT_DATASET || {};
  const lotKey = `lot_${lotState.currentLot}`;
  const lot = dataset[lotKey] || null;
  const maxWafers = lot ? lot.count : 10;
  const cur = Math.max(1, Math.min(lotState.currentWafer, maxWafers));
  lotState.currentWafer = cur;

  const wafer = (lot && lot.wafers) ? lot.wafers[cur - 1] : null;

  // 실측 드리프트 각도를 챔버 진공 물리 모델에 연동
  const driftDeg = wafer ? wafer.drift_deg : (cur - 1) * 0.085;
  ch.setWafer(cur, driftDeg);

  // 로트 선택 버튼 하이라이트 동기화
  const lotPills = document.querySelectorAll('#lot-pills .lot-pill');
  lotPills.forEach((p) => {
    const lNum = parseInt(p.getAttribute('data-lot'), 10);
    p.classList.toggle('active', lNum === lotState.currentLot);
    p.classList.toggle('completed', lNum < lotState.currentLot);
  });

  // 웨이퍼 알약 업데이트
  const pills = document.querySelectorAll('#wafer-pills .wf-pill');
  pills.forEach((p, idx) => {
    const wfNum = idx + 1;
    p.classList.toggle('active', wfNum === cur);
    p.classList.toggle('past', wfNum < cur);
  });

  // 로트 & 웨이퍼 타이틀 업데이트
  const lotTitle = $('lot-title-text');
  if (lotTitle) {
    const dateStr = lot ? lot.date : '2024-07-02';
    lotTitle.textContent = `로트 웨이퍼 순번 · LOT #${lotState.currentLot} (${dateStr})`;
  }
  const expKeyEl = $('lot-exp-key');
  if (expKeyEl) {
    const expKey = wafer ? wafer.exp_key : `EXP_${lotState.currentLot}_${cur}`;
    expKeyEl.textContent = `EXP: ${expKey}`;
  }
  const txt = $('lot-wafer-text');
  if (txt) txt.textContent = `WAFER #${cur} / ${maxWafers}`;

  // 실측 절대 식각 깊이 (µm) 및 백분율 (%)
  const depthUm = wafer ? wafer.depth_um : (44.289 - (cur - 1) * 0.134);
  const depthPct = wafer ? wafer.depth_pct : (100.0 - (cur - 1) * 0.3022);
  const drift = driftDeg;
  const oes = Math.max(88, 100.0 - (cur - 1) * 0.944);

  const elDepthUm = $('vm-depth-um');
  if (elDepthUm) elDepthUm.textContent = depthUm.toFixed(2);
  const elDepthPct = $('vm-depth-pct');
  if (elDepthPct) elDepthPct.textContent = `(${depthPct.toFixed(2)}%)`;

  const elSawVal = $('saw-depth-val');
  if (elSawVal) elSawVal.textContent = `${depthUm.toFixed(2)} µm (${depthPct.toFixed(2)}%)`;

  const elDepthDelta = $('vm-depth-delta');
  if (elDepthDelta) {
    const w1Depth = lot ? lot.w1_depth : 44.289;
    const diffUm = depthUm - w1Depth;
    const lossPct = (depthPct - 100.0).toFixed(2);
    if (cur === 1) {
      elDepthDelta.textContent = `기준 원점 (${w1Depth.toFixed(2)} µm, 신규 로트)`;
    } else {
      elDepthDelta.textContent = `누적 변위: ${diffUm.toFixed(2)} µm (${lossPct}%) · 실측값`;
    }
  }

  const elDrift = $('vm-drift');
  if (elDrift) elDrift.textContent = drift.toFixed(2);

  const elOes = $('vm-oes');
  if (elOes) elOes.textContent = oes.toFixed(1);

  const badge = $('badge-lot-status');
  if (badge) {
    if (cur === 1) {
      badge.textContent = `LOT #${lotState.currentLot} 개시 · 챔버 정상`;
      badge.className = 'badge ok';
    } else if (cur >= maxWafers) {
      badge.textContent = `⚠️ LOT #${lotState.currentLot} (${maxWafers}매) 완료 · 세정 주기 도달`;
      badge.className = 'badge bad';
    } else {
      badge.textContent = `LOT #${lotState.currentLot} 진행 중 (${cur}/${maxWafers}) · 오염 누적`;
      badge.className = 'badge warn';
    }
  }

  // history 동기화 (현재 로트 실측치 채우기)
  lotState.history = [];
  if (lot && lot.wafers) {
    for (let w = 0; w < cur; w++) {
      lotState.history.push(lot.wafers[w].depth_pct);
    }
  } else {
    for (let w = 1; w <= cur; w++) {
      lotState.history.push(100.0 - (w - 1) * 0.3022);
    }
  }
  drawSawtooth();
}

const btnTopRun = $('btn-top-lot-run');
const btnTopNext = $('btn-top-wafer-next');
const btnTopClean = $('btn-top-chamber-clean');
const btnWaferNext = $('btn-wafer-next');
const btnLotAuto = $('btn-lot-auto');
const btnChamberClean = $('btn-chamber-clean');

function startLotProcess() {
  ch.start();
  if (btnTopRun) {
    btnTopRun.innerHTML = '<span class="btn-icon">⏸️</span> 일시 정지';
    btnTopRun.classList.remove('pulse');
  }
  if (btnTopClean) btnTopClean.classList.remove('pulse');
  if (btnLotAuto) btnLotAuto.textContent = '⏸️ 일시 정지';
}

function pauseLotProcess() {
  ch.stop();
  if (lotState.autoTimer) {
    clearInterval(lotState.autoTimer);
    lotState.autoTimer = null;
  }
  if (btnTopRun) {
    btnTopRun.innerHTML = '<span class="btn-icon">⚡</span> 10매 연속 가공';
    if (lotState.currentWafer < 10) btnTopRun.classList.add('pulse');
  }
  if (btnLotAuto) btnLotAuto.textContent = '⚡ 10매 연속 가공';
}

function nextWafer() {
  const dataset = window.LOT_DATASET || {};
  const lotKey = `lot_${lotState.currentLot}`;
  const maxWafers = dataset[lotKey] ? dataset[lotKey].count : 10;

  startLotProcess();
  if (lotState.currentWafer < maxWafers) {
    lotState.currentWafer++;
    updateLotUI();
  } else {
    pauseLotProcess();
    const nextLotNum = (lotState.currentLot % 10) + 1;
    if (btnTopClean) {
      btnTopClean.innerHTML = `🧼 챔버 세정 &amp; 다음 로트 (LOT ${nextLotNum}) →`;
      btnTopClean.classList.add('pulse');
    }
    if (btnChamberClean) {
      btnChamberClean.textContent = `🧼 챔버 세정 & 다음 로트 (LOT ${nextLotNum}) →`;
    }
  }
}

function cleanLot(advance = true) {
  pauseLotProcess();
  ch.cleanChamber();
  resetFdcPmAlarm();
  if (advance && lotState.currentWafer >= 10) {
    lotState.currentLot = (lotState.currentLot % 10) + 1;
  }
  lotState.currentWafer = 1;
  updateLotUI();
  if (btnTopClean) {
    btnTopClean.innerHTML = '🧼 챔버 세정';
    btnTopClean.classList.remove('pulse');
  }
  if (btnChamberClean) {
    btnChamberClean.textContent = '🧼 챔버 세정 (Clean & Reset)';
  }
  if (btnTopRun) btnTopRun.classList.add('pulse');
}

function toggleAutoLot() {
  if (lotState.autoTimer) {
    pauseLotProcess();
  } else {
    const dataset = window.LOT_DATASET || {};
    const lotKey = `lot_${lotState.currentLot}`;
    const maxWafers = dataset[lotKey] ? dataset[lotKey].count : 10;

    if (lotState.currentWafer >= maxWafers) {
      cleanLot(true);
    }
    startLotProcess();
    lotState.autoTimer = setInterval(() => {
      const d = window.LOT_DATASET || {};
      const lk = `lot_${lotState.currentLot}`;
      const mw = d[lk] ? d[lk].count : 10;
      if (lotState.currentWafer < mw) {
        lotState.currentWafer++;
        updateLotUI();
      } else {
        pauseLotProcess();
        const nextLotNum = (lotState.currentLot % 10) + 1;
        if (btnTopClean) {
          btnTopClean.innerHTML = `🧼 챔버 세정 &amp; 다음 로트 (LOT ${nextLotNum}) →`;
          btnTopClean.classList.add('pulse');
        }
        if (btnChamberClean) {
          btnChamberClean.textContent = `🧼 챔버 세정 & 다음 로트 (LOT ${nextLotNum}) →`;
        }
      }
    }, 1500);
  }
}

if (btnTopRun) btnTopRun.addEventListener('click', toggleAutoLot);
if (btnTopNext) btnTopNext.addEventListener('click', nextWafer);
if (btnTopClean) btnTopClean.addEventListener('click', () => cleanLot(true));
if (btnWaferNext) btnWaferNext.addEventListener('click', nextWafer);
if (btnLotAuto) btnLotAuto.addEventListener('click', toggleAutoLot);
if (btnChamberClean) btnChamberClean.addEventListener('click', () => cleanLot(true));

// 실측 10개 로트 탭 버튼 이벤트 등록
document.querySelectorAll('#lot-pills .lot-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    const l = parseInt(pill.getAttribute('data-lot'), 10);
    if (!isNaN(l) && l >= 1 && l <= 10) {
      pauseLotProcess();
      lotState.currentLot = l;
      lotState.currentWafer = 1;
      ch.cleanChamber();
      updateLotUI();
    }
  });
});

// 초기 상태: 대기 (IDLE) 모드로 시작하여 사용자의 [⚡ 10매 연속 가공] 클릭 유도
ch.stop();
updateLotUI();

if (urlParams.get('run') === '1') { toggleAutoLot(); }
if (urlParams.get('lot')) {
  const targetLot = parseInt(urlParams.get('lot'), 10);
  if (!isNaN(targetLot) && targetLot >= 1 && targetLot <= 10) {
    lotState.currentLot = targetLot;
    updateLotUI();
  }
}
if (urlParams.get('wafer')) {
  const targetWafer = parseInt(urlParams.get('wafer'), 10);
  if (!isNaN(targetWafer) && targetWafer >= 1 && targetWafer <= 10) {
    lotState.currentWafer = targetWafer;
    updateLotUI();
  }
}

// ---------------------------------------------------------------- 3D HUD 계측 갱신
function update3dHud(s) {
  if (!s) return;
  if (!s.isProcessing) {
    const elPress = $('hud-3d-press');
    if (elPress) elPress.textContent = '0.00';
    const elRegime = $('hud-3d-regime');
    if (elRegime) elRegime.textContent = '공정 대기 (IDLE)';
    const elKn = $('hud-3d-kn');
    if (elKn) elKn.textContent = '0.000';
    const elTheta = $('hud-3d-theta');
    if (elTheta) elTheta.textContent = '0.0';
    const elOpen = $('hud-3d-open');
    if (elOpen) elOpen.textContent = '0.0';
    const elSeff = $('hud-3d-seff');
    if (elSeff) elSeff.textContent = '0.0';
    const elPumpPct = $('hud-3d-pump-pct');
    if (elPumpPct) elPumpPct.textContent = '100';
    const elMfcVal = $('hud-3d-mfc-val');
    if (elMfcVal) elMfcVal.textContent = '0.0';
    const elMfcSub = $('hud-3d-mfc-sub');
    if (elMfcSub) elMfcSub.textContent = '가스 공급 대기 (STANDBY)';
    const elMfcDot = $('hud-3d-mfc-dot');
    if (elMfcDot) { elMfcDot.className = 'hud-dot'; elMfcDot.style.background = '#64748b'; }
    const elPfore = $('hud-3d-pfore');
    if (elPfore) elPfore.textContent = '—';
    const elLeak = $('hud-3d-leak');
    if (elLeak) elLeak.classList.add('hidden');
    return;
  }

  const mt = paToMtorr(s.P);
  const elPress = $('hud-3d-press');
  if (elPress) elPress.textContent = mt.toFixed(2);

  const elRegime = $('hud-3d-regime');
  if (elRegime) {
    const rName = s.regime ? s.regime.name : '중간류';
    elRegime.textContent = s.boschMode ? `${rName} · 보쉬 DRIE` : rName;
  }

  const elKn = $('hud-3d-kn');
  if (elKn) elKn.textContent = s.Kn < 0.01 ? s.Kn.toExponential(2) : s.Kn.toFixed(3);

  // 스로틀 밸브 각도 & 개도율
  const deg = (s.theta * 180) / Math.PI;
  const elTheta = $('hud-3d-theta');
  if (elTheta) elTheta.textContent = deg.toFixed(1);
  const elOpen = $('hud-3d-open');
  if (elOpen) elOpen.textContent = s.openPct.toFixed(1);

  // TMP 배기속도 & 정격
  const elSeff = $('hud-3d-seff');
  if (elSeff) elSeff.textContent = m3sToLps(s.sEff).toFixed(1);
  const elPumpPct = $('hud-3d-pump-pct');
  if (elPumpPct) elPumpPct.textContent = (ch.pumpDerate * 100).toFixed(0);

  // 가스 유입 (MFC) - 보쉬 DRIE 모드 시 SF₆ vs C₄F₈ 실시간 전환
  const elMfcVal = $('hud-3d-mfc-val');
  const elMfcSub = $('hud-3d-mfc-sub');
  const elMfcDot = $('hud-3d-mfc-dot');
  if (ch.gateClosed) {
    if (elMfcVal) elMfcVal.textContent = '0.0';
    if (elMfcSub) elMfcSub.textContent = '가스 공급 차단 (CLOSED)';
    if (elMfcDot) { elMfcDot.className = 'hud-dot'; elMfcDot.style.background = '#ff453a'; }
  } else if (s.boschMode) {
    const isEtch = s.boschPhase === 'etch';
    const flow = isEtch ? ch.qEtch : ch.qPass;
    const sccm = (flow * 592.2).toFixed(1);
    if (elMfcVal) elMfcVal.textContent = sccm;
    if (elMfcSub) elMfcSub.textContent = isEtch ? `SF₆ 식각 가스 (${flow.toFixed(2)} Pa·m³/s)` : `C₄F₈ 보호 가스 (${flow.toFixed(2)} Pa·m³/s)`;
    if (elMfcDot) {
      elMfcDot.className = 'hud-dot';
      elMfcDot.style.background = isEtch ? '#00f0ff' : '#30d158';
    }
  } else {
    const qActual = ch.qMfc + ch.mfcOffset;
    const sccm = (qActual * 592.2).toFixed(1);
    if (elMfcVal) elMfcVal.textContent = sccm;
    if (elMfcSub) elMfcSub.textContent = `Ar ${qActual.toFixed(2)} Pa·m³/s (공급 중)`;
    if (elMfcDot) { elMfcDot.className = 'hud-dot green'; elMfcDot.style.background = ''; }
  }

  // 포어라인 백킹 압력 (2차 드라이 러핑펌프 흡입구)
  const elPfore = $('hud-3d-pfore');
  if (elPfore) {
    if (ch.gateClosed) {
      elPfore.textContent = '—';
    } else {
      const pf = Math.max(75, Math.min(160, 80 + s.Q * 25));
      elPfore.textContent = pf.toFixed(0);
    }
  }

  // 누설 고장 경보
  const elLeak = $('hud-3d-leak');
  const elLeakVal = $('hud-3d-leak-val');
  const hasLeak = (ch.qLeak && ch.qLeak > 0) || (ch.q1 && ch.q1 > 0);
  if (elLeak) {
    elLeak.classList.toggle('hidden', !hasLeak);
    if (hasLeak && elLeakVal) {
      const qVal = ch.qLeak > 0 ? ch.qLeak : ch.q1;
      elLeakVal.textContent = `${qVal.toFixed(3)} Pa·m³/s`;
    }
  }
}


function updateGasIndicator(s) {
  if (!s) return;
  const elInd = $('live-gas-indicator');
  const elBadge = $('gas-live-badge');
  const elTitle = $('gas-live-title');
  const elTimer = $('gas-live-timer');
  const elPill = $('hud-gas-pill');

  if (!s.isProcessing) {
    if (elInd) elInd.className = 'live-gas-indicator gas-steady';
    if (elBadge) elBadge.textContent = '⏸️ 공정 대기 (IDLE)';
    if (elTitle) elTitle.textContent = '상단 [⚡ 10매 연속 가공]을 클릭하여 에칭을 시작하세요';
    if (elTimer) elTimer.textContent = 'STANDBY';
    if (elPill) {
      elPill.textContent = 'READY';
      elPill.className = 'hud-gas-pill ar';
    }
    return;
  }

  if (s.boschMode) {
    const isPass = s.boschPhase === 'pass';
    const remain = (s.phaseRemain !== undefined ? s.phaseRemain : 0).toFixed(1);
    const flowSccm = isPass ? '385.0' : '817.2';
    const flowPa = isPass ? '0.65' : '1.38';

    if (isPass) {
      if (elInd) elInd.className = 'live-gas-indicator gas-c4f8';
      if (elBadge) elBadge.textContent = '🛡️ C₄F₈ 보호막 (PASSIVATION)';
      if (elTitle) elTitle.textContent = `${flowSccm} sccm (${flowPa} Pa·m³/s) · 측벽 폴리머 코팅`;
      if (elTimer) elTimer.textContent = `${remain}s`;
      if (elPill) {
        elPill.textContent = 'C₄F₈';
        elPill.className = 'hud-gas-pill c4f8';
      }
    } else {
      if (elInd) elInd.className = 'live-gas-indicator gas-sf6';
      if (elBadge) elBadge.textContent = '⚡ SF₆ 식각 (ETCH STEP)';
      if (elTitle) elTitle.textContent = `${flowSccm} sccm (${flowPa} Pa·m³/s) · Si 식각 플라즈마`;
      if (elTimer) elTimer.textContent = `${remain}s`;
      if (elPill) {
        elPill.textContent = 'SF₆';
        elPill.className = 'hud-gas-pill sf6';
      }
    }
  } else {
    if (elInd) elInd.className = 'live-gas-indicator gas-steady';
    const qActual = ch.qMfc + ch.mfcOffset;
    const sccm = (qActual * 592.2).toFixed(1);
    if (elBadge) elBadge.textContent = '⚖️ 정속 정상상태 (Ar)';
    if (elTitle) elTitle.textContent = `${sccm} sccm · 플라즈마 방전 안정화`;
    if (elTimer) elTimer.textContent = 'STEADY';
    if (elPill) {
      elPill.textContent = 'Ar';
      elPill.className = 'hud-gas-pill ar';
    }
  }
}

// ---------------------------------------------------------------- 메인 루프
let last = performance.now();
function frame(now) {
  const dtReal = Math.min((now - last) / 1000, 0.1); last = now;
  let s;
  for (let i = 0; i < SUBSTEPS; i++) s = ch.step(DT);
  if (rorState.active) rorTick(s);
  updateGauges(s);
  updateGasIndicator(s);
  if (currentViewMode === '2d') {
    animateSvg(s, dtReal);
  } else {
    update3dHud(s);
  }
  if (window.Chamber3D) {
    window.Chamber3D.update(s, dtReal);
  }
  const valPress = s.isProcessing ? paToMtorr(s.P) : 0;
  const valTheta = s.isProcessing ? (s.theta * 180) / Math.PI : 0;
  const valSeff = s.isProcessing ? m3sToLps(s.sEff) : 0;
  trPress.push(s.t, valPress);
  trTheta.push(s.t, valTheta);
  trSeff.push(s.t, valSeff);
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

const scenParam = urlParams.get('scen');
if (scenParam && scenarios[scenParam]) {
  const card = document.querySelector(`.scen-card[data-scen="${scenParam}"]`);
  if (card) {
    document.querySelectorAll('.scen-card').forEach((c) => c.classList.remove('on'));
    card.classList.add('on');
  }
  setTimeout(() => scenarios[scenParam](), 200);
}

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

initFdcConsole();
requestAnimationFrame(frame);
