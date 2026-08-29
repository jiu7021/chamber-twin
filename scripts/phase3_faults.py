"""Phase 3-4: 고장 주입과 진단.

게이트 지표는 "이상 탐지 정확도 %" 가 아니라 **주입 참값 대비 추정 오차**다.
  S_eff 추정 오차 ±X %, Q_leak 추정 오차 ±Y %, 고장 검출 지연 Z 초

고장 5종
  1 실누설          Q_leak = 상수          RoR 기울기 일정
  2 가상누설(아웃가싱) Q = q1·t^(−α)         RoR 기울기 감쇠
  3 TMP 성능저하     S_pump 점진 감소        정상상태 역산
  4 스로틀 밸브 마모   θ–C 곡선 변형          동일 압력 유지 각도 드리프트
  5 MFC 제로 드리프트  유량 offset           밸브각–압력에서 Q 역산 후 지령 대비

단위: 전부 SI. 시험대(testbed) 파라미터는 실제 장비값이 아니라 시뮬레이터 설정값이며,
게이트 지표(추정 오차 %)는 절대 스케일에 무관하다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.chamber import (  # noqa: E402
    APCController, ChamberConfig, ThrottleValve, outgassing_rate,
    series_pumping_speed, simulate,
)
from physics.diagnostics import estimate_ror  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# ---------------- 시험대 설정 (시뮬레이터 값. 실제 장비 스펙 아님)
V_M3 = 0.050              # (통상범위) 200 mm DRIE 챔버 30~80 L
S_PUMP = 1.500            # (통상범위) DRIE 용 TMP 1000~2000 L/s
C_MAX = 2.000             # 밸브 완전개방 컨덕턴스 [m³/s] (가정치, 시험대 설정)
P_SP = 5.33               # 압력 설정값 [Pa] (= 40 mTorr 등가)
Q_BASE = 1.000            # 기준 MFC 스루풋 [Pa·m³/s]
KP, KI = 0.30, 1.20       # APC 이득 (시험대 튜닝값)
T_END = 600.0             # 관측 구간 [s]
T_FAULT = 200.0           # 고장 주입 시각 [s]


# ---------------- 계측 모델 (실측 데이터셋 수준의 양자화·잡음)
# (물성치) 실측 Process_data.nc 의 압력 채널 양자화 눈금은 원시값 1e-4 / 평균 0.0424 = 0.236 %.
#          여기서는 0.25 % 상대 양자화로 둔다.
P_QUANT_REL = 0.0025
# (가정치) 압력 게이지 랜덤 잡음. 실측에서는 양자화에 가려 분리 불가 → 양자화 눈금의 40 % 로 가정.
P_NOISE_REL = 0.0010
# (가정치) 밸브 각도 보고 분해능. 실측 데이터에 채널 자체가 없어 확인 불가.
#          전스트로크(π/2)의 0.1 % 로 가정한다.
THETA_QUANT_RAD = 0.001 * np.pi / 2


def measure(x: np.ndarray, ref: float, quant_rel: float, noise_rel: float,
            rng: np.random.Generator) -> np.ndarray:
    """양자화 + 랜덤잡음을 적용한 계측값을 만든다.

    Args:
        x: 참값 배열
        ref: 계측 레인지 기준값 (양자화 눈금과 잡음 크기의 기준)
        quant_rel: 양자화 눈금 / ref
        noise_rel: 잡음 표준편차 / ref
        rng: 난수 생성기

    Returns:
        계측값 배열
    """
    step = quant_rel * ref
    y = x + rng.normal(0.0, noise_rel * ref, size=x.shape)
    return np.round(y / step) * step if step > 0 else y


def measure_theta(th: np.ndarray, scale: float, rng: np.random.Generator) -> np.ndarray:
    """밸브 각도 계측 (양자화만. 잡음은 양자화에 포함된 것으로 본다)."""
    step = THETA_QUANT_RAD * scale
    return np.round(th / step) * step if step > 0 else th


def base_cfg(c_max: float = C_MAX) -> ChamberConfig:
    return ChamberConfig(volume_m3=V_M3, pump_speed_m3s=S_PUMP,
                         valve=ThrottleValve(c_max_m3s=c_max),
                         apc=APCController(setpoint_pa=P_SP, kp=KP, ki=KI))


def theta_to_s_eff(theta: float, s_pump: float, c_max: float) -> float:
    """밸브 각도로부터 유효 배기속도를 계산한다 [m³/s]."""
    return series_pumping_speed(c_max * (1.0 - np.cos(np.clip(theta, 0, np.pi / 2))), s_pump)


def s_eff_to_theta(s_eff: float, s_pump: float, c_max: float) -> float:
    """유효 배기속도로부터 밸브 각도를 역산한다 [rad]."""
    if s_eff <= 0 or s_eff >= s_pump:
        return np.nan
    c = 1.0 / (1.0 / s_eff - 1.0 / s_pump)
    return float(np.arccos(np.clip(1.0 - c / c_max, -1.0, 1.0)))


def detection_delay(t: np.ndarray, sig: np.ndarray, t_fault: float, k: float = 5.0) -> float:
    """기준구간 잡음의 k배를 처음 넘는 시각까지의 지연 [s]. 못 넘으면 NaN."""
    base = (t >= t_fault * 0.5) & (t < t_fault)
    mu, sd = sig[base].mean(), sig[base].std()
    thr = k * max(sd, 1e-12)
    after = t >= t_fault
    over = np.flatnonzero(np.abs(sig[after] - mu) > thr)
    return float(t[after][over[0]] - t_fault) if over.size else np.nan


# ---------------------------------------------------------------- RoR 시퀀스


def rate_of_rise(q_leak: float, q1: float, alpha: float, t_ror: float = 300.0,
                 n: int = 3000, p0: float = 0.05,
                 rng: np.random.Generator | None = None,
                 noise_scale: float = 1.0) -> dict:
    """게이트 밸브를 닫고(S = 0) 압력 상승을 측정한다.

    V·dP/dt = Q_total 이므로 dP/dt 로부터 Q_total 을 산출한다.
    실누설(상수)과 아웃가싱(t^(−α))의 분리가 목적이다.

    Args:
        q_leak: 주입 실누설 [Pa·m³/s]
        q1: 주입 아웃가싱 계수 (t = 1 s 기준) [Pa·m³/s]
        alpha: 주입 아웃가싱 지수
        t_ror: RoR 측정 시간 [s]
        n: 샘플 수
        p0: 초기 압력 [Pa]

    Returns:
        측정 시계열과 추정 결과
    """
    cfg = ChamberConfig(volume_m3=V_M3, pump_speed_m3s=S_PUMP,
                        valve=ThrottleValve(c_max_m3s=C_MAX),
                        apc=None, theta_fixed_rad=0.0)      # 게이트 폐쇄
    og = (lambda t: outgassing_rate(t, q1, alpha)) if q1 > 0 else None
    sol = simulate(cfg, t_end_s=t_ror, p0_pa=p0, q_in=lambda t: 0.0,
                   q_leak_pa_m3s=q_leak, outgas=og, n_out=n)
    t, p_true = sol.t_s, sol.p_pa
    # 실측과 같은 5 Hz 로 다운샘플
    keep = np.arange(0, len(t), max(int(round(len(t) / (t[-1] * 5.0))), 1))
    t, p_true = t[keep], p_true[keep]
    if rng is not None and noise_scale > 0.0:
        p = measure(p_true, float(p_true.max()), P_QUANT_REL * noise_scale,
                    P_NOISE_REL * noise_scale, rng)
    else:
        p = p_true
    return {"t": t, "p": p, "p_true": p_true}


# ---------------------------------------------------------------- 고장 시나리오


def run_fault(name: str, **kw) -> dict:
    """고장을 주입하고 진단 지표를 산출한다."""
    t_eval_n = 3000
    q_in = kw.get("q_in", lambda t: Q_BASE)
    q_leak = kw.get("q_leak", 0.0)
    outgas = kw.get("outgas", None)
    pump_of_t = kw.get("pump_of_t", None)
    cmax_of_t = kw.get("cmax_of_t", None)

    cfg = base_cfg()
    sol = simulate(cfg, t_end_s=T_END, p0_pa=P_SP, q_in=q_in,
                   q_leak_pa_m3s=q_leak, outgas=outgas,
                   pump_speed_of_t=pump_of_t, c_max_of_t=cmax_of_t,
                   theta0_rad=s_eff_to_theta(Q_BASE / P_SP, S_PUMP, C_MAX),
                   n_out=t_eval_n)
    t, p_true, th_true = sol.t_s, sol.p_pa, sol.theta_rad
    rng = kw.get("rng")
    scale = kw.get("noise_scale", 1.0)
    if rng is None or scale == 0.0:
        p, th = p_true, th_true
    else:
        p = measure(p_true, P_SP, P_QUANT_REL * scale, P_NOISE_REL * scale, rng)
        th = measure_theta(th_true, scale, rng)
    last = t >= T_END - 50.0
    pre = (t >= T_FAULT * 0.5) & (t < T_FAULT)
    return {"name": name, "t": t, "p": p, "theta": th, "s_eff": sol.s_eff_m3s,
            "theta_pre": float(th[pre].mean()), "theta_post": float(th[last].mean()),
            "p_pre": float(p[pre].mean()), "p_post": float(p[last].mean()),
            "delay_theta": detection_delay(t, th, T_FAULT),
            "delay_p": detection_delay(t, p, T_FAULT)}


NOISE_SCALES = [0.0, 1.0, 3.0]      # 0 = 무잡음(자기일관성), 1 = 실측 수준, 3 = 3배
N_SEEDS = 20


def summarize(errs: list[float]) -> str:
    a = np.abs(np.array([e for e in errs if np.isfinite(e)]))
    return "—" if a.size == 0 else f"{a.mean():6.2f} ± {a.std():5.2f}"


def main() -> None:
    rows = []
    print("=" * 92)
    print("Phase 3-4 고장 주입과 진단 — 주입 참값 대비 추정 오차")
    print("=" * 92)
    print(f"\n시험대: V = {V_M3} m³, S_pump = {S_PUMP} m³/s, C_max = {C_MAX} m³/s, "
          f"P_sp = {P_SP} Pa, Q = {Q_BASE} Pa·m³/s")
    print(f"       고장 주입 {T_FAULT} s, 관측 {T_END} s, 계측 잡음 시드 {N_SEEDS} 개")
    print(f"\n계측 모델: 압력 상대양자화 {P_QUANT_REL*100:.2f} % (실측 데이터셋의 0.236 % 에 맞춤), "
          f"잡음 {P_NOISE_REL*100:.2f} %,")
    print(f"          밸브각 분해능 {THETA_QUANT_RAD*1e3:.3f} mrad (가정치), RoR 은 실측과 같은 5 Hz")
    print("\n잡음 배율 0 = 무잡음. 이 열은 성능이 아니라 추정기 대수(algebra)의 자기일관성 확인이다.")

    ror_cases = [("실누설만", 2.0e-3, 0.0, 1.0),
                 ("아웃가싱만 (금속 α=1)", 0.0, 5.0e-2, 1.0),
                 ("아웃가싱만 (폴리머 α=0.5)", 0.0, 5.0e-3, 0.5),
                 ("실누설 + 아웃가싱", 2.0e-3, 5.0e-2, 1.0),
                 ("실누설 + 폴리머", 1.0e-3, 5.0e-3, 0.5)]

    print("\n" + "-" * 92)
    print("[1·2] Rate-of-Rise — 실누설(상수)과 가상누설(아웃가싱) 분리")
    print("-" * 92)
    print(f"  {'시나리오':26s} {'잡음':>5s} {'Q_leak 오차%':>14s} {'q1 오차%':>14s} {'α 추정':>14s}")
    for nm, ql, q1, al in ror_cases:
        for sc in NOISE_SCALES:
            eq, e1, ea = [], [], []
            for sd in range(1 if sc == 0.0 else N_SEEDS):
                r = rate_of_rise(ql, q1, al, rng=np.random.default_rng(sd), noise_scale=sc)
                e = estimate_ror(list(zip(r["t"].tolist(), r["p"].tolist())), V_M3)
                if e is None:
                    continue
                if ql > 0:
                    eq.append((e.q_leak - ql) / ql * 100)
                if q1 > 0:
                    e1.append((e.q1 - q1) / q1 * 100)
                ea.append(e.alpha if e.outgas_accepted else float("nan"))
            a = np.array(ea, dtype=float)
            fin = a[np.isfinite(a)]
            a_txt = (f"{fin.mean():6.3f}±{fin.std():.3f}" if fin.size
                     else "     기각     ")          # 모델선택이 아웃가싱을 기각한 경우
            print(f"  {nm:26s} {sc:5.0f}x {summarize(eq):>14s} {summarize(e1):>14s} "
                  f"{a_txt:>14s}  (참값 {al})")
            rows.append({"고장": f"RoR/{nm}", "잡음배율": sc,
                         "오차%_Q_leak": np.mean(np.abs(eq)) if eq else np.nan,
                         "오차%_q1": np.mean(np.abs(e1)) if e1 else np.nan,
                         "추정_alpha": float(fin.mean()) if fin.size else np.nan,
                         "참값_alpha": al,
                         "아웃가싱_채택율": float(fin.size / max(len(a), 1))})

    # ---------- 3·4·5
    scenarios = []
    for frac in (0.95, 0.90, 0.80, 0.70):
        scenarios.append(("TMP저하", frac))
    for frac in (0.95, 0.90, 0.80, 0.70):
        scenarios.append(("밸브마모", frac))
    for off in (0.02, 0.05, 0.10, -0.05):
        scenarios.append(("MFC드리프트", off))

    print("\n" + "-" * 92)
    print("[3·4·5] 공정 중 진단 — 밸브 각도에서 미측정 변수 역산")
    print("-" * 92)
    print(f"  {'고장':16s} {'크기':>8s} {'잡음':>5s} {'추정 오차%':>16s} "
          f"{'검출지연 s':>16s} {'P 변화%':>10s}")
    for kind, amt in scenarios:
        for sc in NOISE_SCALES:
            errs, delays, dps = [], [], []
            for sd in range(1 if sc == 0.0 else N_SEEDS):
                rng = np.random.default_rng(1000 + sd)
                if kind == "TMP저하":
                    s_end = S_PUMP * amt
                    def pump(t, s_end=s_end):
                        k = 0.0 if t < T_FAULT else min((t - T_FAULT) / 100.0, 1.0)
                        return S_PUMP + (s_end - S_PUMP) * k
                    r = run_fault(kind, pump_of_t=pump, rng=rng, noise_scale=sc)
                    s_eff_req = Q_BASE / r["p_post"]
                    c_now = C_MAX * (1 - np.cos(r["theta_post"]))
                    est = 1.0 / max(1.0 / s_eff_req - 1.0 / c_now, 1e-12)
                    errs.append((est - s_end) / s_end * 100)
                elif kind == "밸브마모":
                    c_end = C_MAX * amt
                    def cmax(t, c_end=c_end):
                        k = 0.0 if t < T_FAULT else min((t - T_FAULT) / 100.0, 1.0)
                        return C_MAX + (c_end - C_MAX) * k
                    r = run_fault(kind, cmax_of_t=cmax, rng=rng, noise_scale=sc)
                    s_eff_req = Q_BASE / r["p_post"]
                    c_req = 1.0 / max(1.0 / s_eff_req - 1.0 / S_PUMP, 1e-12)
                    est = c_req / max(1 - np.cos(r["theta_post"]), 1e-12)
                    errs.append((est - c_end) / c_end * 100)
                else:
                    def q_in(t, off=amt):
                        return Q_BASE + (off if t >= T_FAULT else 0.0)
                    r = run_fault(kind, q_in=q_in, rng=rng, noise_scale=sc)
                    q_true = Q_BASE + amt
                    c_now = C_MAX * (1 - np.cos(r["theta_post"]))
                    est = series_pumping_speed(c_now, S_PUMP) * r["p_post"]
                    errs.append((est - q_true) / q_true * 100)
                delays.append(r["delay_theta"])
                dps.append((r["p_post"] / r["p_pre"] - 1) * 100)
            d = np.array([x for x in delays if np.isfinite(x)])
            lab = f"{amt:.0%}" if kind != "MFC드리프트" else f"{amt:+.2f}"
            print(f"  {kind:16s} {lab:>8s} {sc:5.0f}× {summarize(errs):>16s} "
                  f"{(f'{d.mean():6.2f} ± {d.std():5.2f}' if d.size else '미검출'):>16s} "
                  f"{np.mean(np.abs(dps)):10.4f}")
            rows.append({"고장": f"{kind} {lab}", "잡음배율": sc,
                         "추정오차%": float(np.mean(np.abs(errs))),
                         "검출지연_s": float(d.mean()) if d.size else np.nan,
                         "P변화%": float(np.mean(np.abs(dps)))})

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "phase3_fault_diagnosis.csv", index=False)

    print("\n" + "-" * 92)
    print("[검증] APC 하에서 압력 채널은 고장을 보지 못한다 (Phase 1 실측 재현)")
    print("-" * 92)
    pv = df["P변화%"].dropna()
    print(f"  전체 {len(pv)} 건의 정상상태 압력 변화: 중앙값 {pv.median():.5f} %, 최대 {pv.max():.5f} %")
    print("  → 압력만 보면 어떤 고장도 검출되지 않는다. 밸브 각도가 정보를 전부 담고 있다.")

    print("\n" + "=" * 92)
    print("게이트 지표 요약 (잡음 배율 1× = 실측 수준)")
    print("=" * 92)
    d1 = df[df["잡음배율"] == 1.0]
    for key, lab in (("오차%_Q_leak", "Q_leak"), ("오차%_q1", "q1(아웃가싱)"),
                     ("추정오차%", "S_pump/C_max/Q")):
        v = d1[key].dropna() if key in d1 else pd.Series(dtype=float)
        if len(v):
            print(f"  {lab:16s} 추정 오차  중앙값 {v.median():7.2f} %, 최대 {v.max():7.2f} %")
    dd = d1["검출지연_s"].dropna()
    if len(dd):
        print(f"  {'검출 지연':16s}            중앙값 {dd.median():7.2f} s,  최대 {dd.max():7.2f} s")
    print(f"\n저장: {RESULTS/'phase3_fault_diagnosis.csv'}")


if __name__ == "__main__":
    main()
