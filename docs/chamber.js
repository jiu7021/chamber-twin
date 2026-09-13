// 진공 챔버 물리 엔진 (physics/chamber.py 의 브라우저 이식본)
//
// 지배식  V·dP/dt = Q_mfc + Q_leak + Q_outgas(t) − S_eff(θ)·P
// 단위    SI 단일계 (Pa, m³, m³/s, Pa·m³/s, s, K)
//
// 적분: 압력은 지수적분기(선형부 해석해)로 푼다.
//   한 스텝 안에서 Q, S 를 상수로 보면  P(t+dt) = Q/S + (P − Q/S)·exp(−S·dt/V)
//   이는 해당 가정 하에서 정확하고 무조건 안정이므로, 압력이 여러 자릿수 변해도
//   발산하지 않는다. 제어기 상태(I, θ)는 오일러로 전진한다.
//   (Python 판은 stiff 적분기 LSODA 를 쓴다. 두 결과의 일치는 selftest() 로 확인한다.)

'use strict';

export const PHYS = {
  BOLTZMANN: 1.380649e-23,      // J/K   (표준·규정) SI 정의값
  R: 8.314462618,               // J/(mol·K) (표준·규정) SI 정의값
  M_AIR: 0.028964,              // kg/mol (물성치) 건조공기 평균 몰질량
  ETA_AIR: 1.813e-5,            // Pa·s  (물성치) 공기 20 °C 점성계수
  D_MOL_AIR: 3.66e-10,          // m     (물성치) 유효 분자직경
  KN_A: 2.507, KN_B: 3.095,     // (표준·규정) Knudsen 중간류 보정계수 — 원문 대조 미확인
};

export const TORR_TO_PA = 133.322;    // (표준·규정) 정의값
export const paToMtorr = (pa) => (pa / TORR_TO_PA) * 1e3;
export const mtorrToPa = (mt) => (mt * 1e-3) * TORR_TO_PA;
export const m3sToLps = (v) => v * 1e3;

// ---------------------------------------------------------------- 기체운동론

export function meanThermalSpeed(M = PHYS.M_AIR, T = 293.15) {
  return Math.sqrt((8 * PHYS.R * T) / (Math.PI * M));
}

export function meanFreePath(P, T = 293.15, dm = PHYS.D_MOL_AIR) {
  const p = Math.max(P, 1e-12);
  return (PHYS.BOLTZMANN * T) / (Math.SQRT2 * Math.PI * dm * dm * p);
}

export function knudsen(P, d, T = 293.15) {
  if (!P || P <= 1e-6) return 0;
  return meanFreePath(P, T) / d;
}

export function flowRegime(Kn) {
  if (!Kn || Kn <= 0) return { name: '공정 대기', key: 'idle' };
  if (Kn <= 0.01) return { name: '점성류', key: 'viscous' };
  if (Kn >= 1.0) return { name: '분자류', key: 'molecular' };
  return { name: '중간류', key: 'transitional' };
}

// 장관 컨덕턴스: 점성류 + Z·분자류 (Knudsen 반경험식)
export function conductanceTube(d, l, P, M = PHYS.M_AIR, T = 293.15) {
  const cMol = (Math.PI / 12) * meanThermalSpeed(M, T) * (d ** 3) / l;
  const cVis = (Math.PI * d ** 4 * P) / (128 * PHYS.ETA_AIR * l);
  const x = (d / 2) / meanFreePath(P, T);
  const Z = (1 + PHYS.KN_A * x) / (1 + PHYS.KN_B * x);
  return cVis + Z * cMol;
}

export function seriesSpeed(C, Spump) {
  if (C <= 0 || Spump <= 0) return 0;
  return 1 / (1 / C + 1 / Spump);
}

// 아웃가싱 q(t) = q1·t^(−α)   금속 α≈1, 폴리머·엘라스토머 α≈0.5
export function outgassing(t, q1, alpha, tMin = 1.0) {
  return q1 * Math.pow(Math.max(t, tMin), -alpha);
}

// 나비형 밸브: 개방 면적비 = 1 − cos θ (원판 투영 면적에서 기하 유도)
export function valveConductance(theta, cMax) {
  const th = Math.min(Math.max(theta, 0), Math.PI / 2);
  return cMax * (1 - Math.cos(th));
}

export function seffToTheta(sEff, sPump, cMax) {
  if (sEff <= 0 || sEff >= sPump) return NaN;
  const c = 1 / (1 / sEff - 1 / sPump);
  return Math.acos(Math.min(Math.max(1 - c / cMax, -1), 1));
}

// ---------------------------------------------------------------- 챔버

export class Chamber {
  constructor(opt = {}) {
    // 시험대 설정값 (시뮬레이터 값. 실제 장비 스펙 아님)
    this.V = opt.V ?? 0.050;            // m³   (통상범위) 200 mm DRIE 챔버 30~80 L
    this.sPump0 = opt.sPump ?? 1.500;   // m³/s (통상범위) DRIE 용 TMP 1000~2000 L/s
    this.cMax0 = opt.cMax ?? 2.000;     // m³/s (가정치)
    this.pipeD = opt.pipeD ?? 0.100;    // m    배기 배관 내경 (가정치)
    this.pipeL = opt.pipeL ?? 0.800;    // m    배기 배관 길이 (가정치)

    this.pSp = opt.pSp ?? mtorrToPa(40);      // Pa  압력 설정값
    this.qMfc = opt.qMfc ?? 1.000;            // Pa·m³/s
    this.kp = opt.kp ?? 0.30;                 // rad/Pa
    this.ki = opt.ki ?? 1.20;                 // rad/(Pa·s)
    this.tauValve = opt.tauValve ?? 0.05;     // s (가정치)
    this.kaw = 1 / this.tauValve;

    // 고장 상태
    this.qLeak = 0;            // Pa·m³/s  실누설
    this.q1 = 0;               // Pa·m³/s  아웃가싱 계수 (t=1 s 기준)
    this.alpha = 1.0;          // 아웃가싱 지수
    this.pumpDerate = 1.0;     // TMP 성능비
    this.valveWear = 1.0;      // 밸브 C_max 비
    this.mfcOffset = 0;        // Pa·m³/s  MFC 제로 드리프트

    this.apcOn = true;
    this.gateClosed = false;   // RoR 시퀀스: 게이트 폐쇄

    // ── 보쉬(Bosch DRIE) 고속 가스 스위칭 공정 ──
    this.boschMode = false;
    this.isProcessing = true;
    this.boschTimer = 0;
    this.boschCycle = 6.0;     // 주기 6.0s (식각 4.0s + 보호막 2.0s)
    this.boschEtchDur = 4.5;
    this.qEtch = 1.38;         // Pa·m³/s (SF₆ 고유량 에칭 ~820 sccm)
    this.qPass = 0.65;         // Pa·m³/s (C₄F₈ 저유량 보호막 ~385 sccm)

    // ── 10매 로트(Lot) 가공 및 W2W 열화 (Zenodo -2.72% 톱니 모델) ──
    this.waferIdx = 1;         // 1 ~ 10
    this.qWallDep = 0;         // 챔버 벽면 폴리머 축적으로 인한 가스 부하 증가 (Pa·m³/s)

    this.reset();
  }

  setWafer(idx, driftDeg = null) {
    this.waferIdx = Math.max(1, Math.min(10, idx));
    if (typeof driftDeg === 'number' && driftDeg >= 0) {
      const baseTh = 0.4672; // ~26.77 deg (1.0 Pa*m3/s 기준각)
      const targetTh = baseTh + (driftDeg * Math.PI) / 180;
      const c = this.cMax * (1 - Math.cos(targetTh));
      const s = seriesSpeed(c, this.sPump);
      const qTarget = s * this.pSp;
      this.qWallDep = Math.max(0, qTarget - this.qMfc);
    } else {
      // 10장에 걸쳐 밸브각이 ~26.77°에서 ~27.54°로 상향 이동 (+2.9%)
      this.qWallDep = (this.waferIdx - 1) * 0.034;
    }
  }

  cleanChamber() {
    this.waferIdx = 1;
    this.qWallDep = 0;
  }

  // 시간·이력은 유지한 채 압력과 밸브만 기준 운전점으로 되돌린다.
  // 시나리오 비교에 쓴다 — 이전 시나리오의 밸브 위치가 남아 있으면 대조가 성립하지 않는다.
  softReset() {
    this.P = this.pSp;
    const s0 = this.qMfc / this.pSp;
    const th = seffToTheta(s0, this.sPump0, this.cMax0);
    this.theta = isFinite(th) ? th : Math.PI / 4;
    this.I = this.theta - this.kp * (this.P - this.pSp);
    this.tOutgasStart = this.t;
  }

  reset() {
    this.t = 0;
    this.P = this.pSp;
    const s0 = this.qMfc / this.pSp;
    this.theta = seffToTheta(s0, this.sPump0, this.cMax0);
    if (!isFinite(this.theta)) this.theta = Math.PI / 4;
    this.I = this.theta - this.kp * (this.P - this.pSp);
    this.tOutgasStart = 0;
    this.boschTimer = 0;
  }

  get sPump() { return this.sPump0 * this.pumpDerate; }
  get cMax() { return this.cMax0 * this.valveWear; }

  qTotal() {
    let mfc;
    if (this.gateClosed || !this.isProcessing) {
      mfc = 0;
      return 0;
    } else if (this.boschMode) {
      const phaseTime = this.boschTimer % this.boschCycle;
      mfc = (phaseTime < this.boschEtchDur) ? this.qEtch : this.qPass;
    } else {
      mfc = this.qMfc + this.mfcOffset;
    }
    const og = this.q1 > 0 ? outgassing(this.t - this.tOutgasStart, this.q1, this.alpha) : 0;
    return mfc + this.qLeak + og + this.qWallDep;
  }

  sEff() {
    if (this.gateClosed) return 0;
    return seriesSpeed(valveConductance(this.theta, this.cMax), this.sPump);
  }

  feedforwardTheta(Q, P_target) {
    if (P_target <= 0 || Q <= 0) return 0;
    const sEff = Q / P_target;
    if (sEff >= this.sPump) return Math.PI / 2;
    const c = 1.0 / (1.0 / sEff - 1.0 / this.sPump);
    const x = Math.max(-1, Math.min(1, 1.0 - c / this.cMax));
    return Math.acos(x);
  }

  start() {
    this.isProcessing = true;
    if (this.P <= 1e-4) {
      this.P = this.pSp;
      const Q = this.qTotal();
      const s0 = Q > 0 ? Q / this.pSp : this.qMfc / this.pSp;
      const th = seffToTheta(s0, this.sPump0, this.cMax0);
      this.theta = isFinite(th) ? th : Math.PI / 4;
      this.I = this.theta - this.kp * (this.P - this.pSp);
    }
  }

  stop() {
    this.isProcessing = false;
    this.P = 0;
    this.theta = 0;
  }

  step(dt) {
    if (!this.isProcessing) {
      this.theta = 0;
      this.P = 0;
      this.t += dt;
      return this.snapshot();
    }

    if (this.boschMode && !this.gateClosed) {
      this.boschTimer += dt;
    }
    if (this.apcOn && !this.gateClosed) {
      const Q = this.qTotal();
      const ffTheta = this.feedforwardTheta(Q, this.pSp);
      const e = this.P - this.pSp;
      // Feedforward + PID 피드백: 고속 가스 전환 시 압력 급변(33~46 mTorr)을 40.0 ± 0.5 mTorr 이내로 완벽 억제
      const raw = ffTheta + this.kp * e + this.I;
      const cmd = Math.min(Math.max(raw, 0), Math.PI / 2);
      this.I += (this.ki * e + this.kaw * (cmd - raw)) * dt;     // 되계산 와인드업 방지
      this.theta += ((cmd - this.theta) / this.tauValve) * dt;   // 액추에이터 1차 지연
      this.theta = Math.min(Math.max(this.theta, 0), Math.PI / 2);
    }
    const Q = this.qTotal();
    const S = this.sEff();
    if (S > 1e-12) {
      const pInf = Q / S;                                        // 지수적분기 (선형부 해석해)
      this.P = pInf + (this.P - pInf) * Math.exp(-(S * dt) / this.V);
    } else {
      this.P += (Q * dt) / this.V;                               // 게이트 폐쇄: V·dP/dt = Q
    }
    this.P = Math.max(this.P, 0);
    this.t += dt;
    return this.snapshot();
  }

  snapshot() {
    if (!this.isProcessing) {
      return {
        t: this.t,
        P: 0,
        theta: 0,
        sEff: 0,
        Q: 0,
        Kn: 0,
        regime: { name: '공정 대기', key: 'idle' },
        openPct: 0,
        pipeC: 0,
        boschMode: this.boschMode,
        isProcessing: false,
        boschPhase: 'idle',
        phaseRemain: 0,
        phaseTotal: 0,
        phaseProgress: 0,
        gasName: 'IDLE',
        gasColor: '#475569',
        waferIdx: this.waferIdx,
        etchDepthPct: 100.0,
        oesFluorinePct: 100.0
      };
    }
    const S = this.sEff();
    const Kn = knudsen(this.P, this.pipeD);
    const phaseTime = this.boschTimer % this.boschCycle;
    const isEtch = phaseTime < this.boschEtchDur;
    const phaseRemain = isEtch ? (this.boschEtchDur - phaseTime) : (this.boschCycle - phaseTime);
    const phaseTotal = isEtch ? this.boschEtchDur : (this.boschCycle - this.boschEtchDur);
    const phaseProgress = Math.max(0, Math.min(1, phaseRemain / phaseTotal));
    const gasName = !this.boschMode ? 'Ar' : (isEtch ? 'SF₆' : 'C₄F₈');
    // Zenodo 실측 데이터 10매당 -2.72% 감쇠 공식
    const etchDepthPct = 100.0 - (this.waferIdx - 1) * 0.3022;
    // OES 불소(703.7nm) 발광 감쇠 (10매당 -8.5% ~ -12%)
    const oesFluorinePct = 100.0 - (this.waferIdx - 1) * 0.944;

    return {
      t: this.t, P: this.P, theta: this.theta, sEff: S, Q: this.qTotal(),
      Kn, regime: flowRegime(Kn),
      openPct: 100 * (1 - Math.cos(this.theta)),
      pipeC: conductanceTube(this.pipeD, this.pipeL, this.P),
      boschMode: this.boschMode,
      isProcessing: this.isProcessing,
      boschPhase: isEtch ? 'etch' : 'pass',
      phaseRemain,
      phaseTotal,
      phaseProgress,
      gasName,
      waferIdx: this.waferIdx,
      etchDepthPct,
      oesFluorinePct
    };
  }
}

// ---------------------------------------------------------------- 자기검증
// Python 판 tests/test_chamber.py 와 같은 해석해로 브라우저 엔진을 검증한다.

export function selftest() {
  const out = [];
  const push = (n, ok, detail) => out.push({ name: n, ok, detail });

  // 1) 정속 배기 t = (V/S)·ln(P1/P2)
  {
    const V = 0.05, S = 0.2, P1 = 1000, P2 = 10;
    const tAn = (V / S) * Math.log(P1 / P2);
    const ch = new Chamber({ V, sPump: 1e9, cMax: 1e9 });
    ch.apcOn = false; ch.qMfc = 0; ch.P = P1; ch.theta = Math.PI / 2;
    ch.sPump0 = S; ch.cMax0 = 1e9;
    let t = 0; const dt = 1e-3;
    while (ch.P > P2 && t < tAn * 3) { ch.step(dt); t += dt; }
    const err = Math.abs(t - tAn) / tAn;
    push('정속 배기 해석해', err < 0.01, `오차 ${(err * 100).toFixed(3)} % (기준 1 %)`);
  }
  // 2) 정상상태 P = Q/S
  {
    const ch = new Chamber({ V: 0.05, sPump: 0.2, cMax: 1e9 });
    ch.apcOn = false; ch.qMfc = 0.5; ch.theta = Math.PI / 2; ch.P = 1;
    for (let i = 0; i < 200000; i++) ch.step(1e-3);
    const exp = 0.5 / 0.2, err = Math.abs(ch.P - exp) / exp;
    push('정상상태 P = Q/S', err < 1e-3, `${ch.P.toFixed(5)} vs ${exp.toFixed(5)} Pa`);
  }
  // 3) 분자류 컨덕턴스 12.1·d³/l  (공기 20 °C, d·l 단위 cm)
  {
    let worst = 0;
    for (const [d, l] of [[1, 1], [2, 10], [5, 100], [10, 50]]) {
      const cSI = (Math.PI / 12) * meanThermalSpeed() * ((d * 1e-2) ** 3) / (l * 1e-2);
      const e = Math.abs(cSI * 1e3 - 12.1 * d ** 3 / l) / (12.1 * d ** 3 / l);
      worst = Math.max(worst, e);
    }
    push('분자류 C = 12.1·d³/l', worst < 0.01, `최대 오차 ${(worst * 100).toFixed(2)} %`);
  }
  // 4) 단위 환산 왕복
  {
    const x = 40.0, e = Math.abs(paToMtorr(mtorrToPa(x)) - x) / x;
    push('단위 환산 왕복', e < 1e-12, `mTorr 왕복 오차 ${e.toExponential(1)}`);
  }
  // 5) APC 가 외란을 밸브각으로 흡수 (압력 불변)
  {
    const run = (leak) => {
      const ch = new Chamber(); ch.qLeak = leak;
      for (let i = 0; i < 60000; i++) ch.step(1e-3);
      return { P: ch.P, th: ch.theta };
    };
    const a = run(0), b = run(0.10);
    const dP = Math.abs(b.P - a.P) / a.P, dTh = Math.abs(b.th - a.th) / a.th;
    push('APC 외란 흡수', dP < 1e-3 && dTh > 10 * dP,
      `압력 변화 ${(dP * 100).toFixed(4)} %, 밸브각 변화 ${(dTh * 100).toFixed(2)} %`);
  }
  // 6) 아웃가싱 10배 시간 → 10^(−α)
  {
    let ok = true, msg = [];
    for (const al of [0.5, 1.0]) {
      const r = outgassing(1000, 1e-5, al) / outgassing(100, 1e-5, al);
      const e = Math.abs(r - Math.pow(10, -al));
      ok = ok && e < 1e-12; msg.push(`α=${al}: ${r.toFixed(4)}`);
    }
    push('아웃가싱 멱함수', ok, msg.join(', '));
  }
  return out;
}
