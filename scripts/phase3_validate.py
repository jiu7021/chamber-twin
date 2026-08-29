"""Phase 3-3: 실측 대조.

목적은 압력 시계열을 예쁘게 만드는 것이 아니라 **잔차를 산출하는 것**이다.
잔차가 백색잡음이 아니라 사이클과 상관된 구조를 보이면 모델에 빠진 물리가 있다는 뜻이다.

두 모델을 나란히 적합해 비교한다.
  모델 A  고정 S      V·dP/dt = Q(t) − S·P                   (Phase 1 이 실패했던 모델)
  모델 B  APC 서보    V·dP/dt = Q(t) − S(t)·P, S 는 PI 서보    (Phase 1 이 요구한 모델)

단위 불가지론: 지배식은 (V, Q, P, S) 가 정합적이면 형태가 보존되므로 원시 단위로 적합한다.
따라서 V 는 [Q단위·s/P단위], S 는 [Q단위/P단위] 의 혼합 단위로 나온다. 시간만 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.chamber import SpeedServo, simulate_speed_servo  # noqa: E402
from physics.dataio import list_groups, load_run  # noqa: E402
from physics.steps import (  # noqa: E402
    CHAMBER_GAS, LONG_BAND_S, SHORT_BAND_S, ensemble, find_steps,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

LONG_SS_WIN = (2.0, 4.2)      # 긴 스텝 평탄부 (상대시각 s)
SHORT_SS_WIN = (5.3, 5.9)     # 짧은 스텝 평탄부 (상대시각 s)


def build_cycle(group: str) -> dict | None:
    """웨이퍼 1장의 한 주기 앙상블 평균 사이클을 만든다 (긴 스텝 상승 정렬)."""
    r = load_run(group)
    df = r.df
    gases = [g for g in CHAMBER_GAS if g in df.columns]
    df = df.assign(Qtot=df[gases].sum(axis=1))
    L = find_steps(df, "Gas5Flow", LONG_BAND_S)
    S = find_steps(df, "Gas4Flow", SHORT_BAND_S)
    if L.rise_s.size < 10 or S.rise_s.size < 10:
        return None
    e = ensemble(df, L.rise_s, ["Pressure", "Qtot", "Gas5Flow", "Gas4Flow"], k_lo=0, k_hi=30)
    t = e["rel_t_s"].values
    p = e["Pressure"].values
    q = e["Qtot"].values
    long_on = e["Gas5Flow"].values > e["Gas4Flow"].values   # 긴 가스 우세 구간
    p_long = float(np.median(p[(t >= LONG_SS_WIN[0]) & (t <= LONG_SS_WIN[1])]))
    p_short = float(np.median(p[(t >= SHORT_SS_WIN[0]) & (t <= SHORT_SS_WIN[1])]))
    return {"group": group, "date": r.date, "seq": r.wafer, "exp_key": r.exp_key,
            "t": t, "p": p, "q": q, "long_on": long_on,
            "p_sp_long": p_long, "p_sp_short": p_short}


def make_interp(t: np.ndarray, y: np.ndarray):
    """구간선형 보간 함수 (적분기가 임의 시각을 요청하므로 필요)."""
    return lambda tt: float(np.interp(tt, t, y))


def fit_fixed_s(c: dict) -> dict:
    """모델 A: 고정 S. 자유변수 (V, S)."""
    t, p, q = c["t"], c["p"], c["q"]
    q_f = make_interp(t, q)

    def resid(theta):
        v, s = np.exp(theta)
        try:
            sim = simulate_speed_servo(v, q_f, t, p[0], s_fixed=s)
        except RuntimeError:
            return np.full_like(p, 1e3)
        return sim.p_pa - p

    x0 = np.log([np.median(q) / np.median(p) * 0.3, np.median(q) / np.median(p)])
    out = least_squares(resid, x0, method="lm", max_nfev=400)
    v, s = np.exp(out.x)
    pred = simulate_speed_servo(v, q_f, t, p[0], s_fixed=s).p_pa
    return {"V": v, "S": s, "pred": pred}


def fit_apc(c: dict) -> dict:
    """모델 B: APC 배기속도 서보. 자유변수 (V, s0, kp, ki)."""
    t, p, q = c["t"], c["p"], c["q"]
    q_f = make_interp(t, q)
    # 압력 설정값: 스텝별 실측 평탄부 값 (데이터에서 취한 값, 가정 아님)
    sp = np.where(c["long_on"], c["p_sp_long"], c["p_sp_short"])
    sp_f = make_interp(t, sp)
    s_guess = float(np.median(q) / np.median(p))

    def resid(theta):
        v, s0, kp, ki = np.exp(theta)
        servo = SpeedServo(s0=s0, kp=kp, ki=ki, s_min=0.0, s_max=50.0 * s_guess, tau_s=0.05)
        try:
            sim = simulate_speed_servo(v, q_f, t, p[0], servo=servo, p_sp_of_t=sp_f)
        except RuntimeError:
            return np.full_like(p, 1e3)
        return sim.p_pa - p

    x0 = np.log([s_guess * 0.3, s_guess, s_guess * 10.0, s_guess * 200.0])
    out = least_squares(resid, x0, method="lm", max_nfev=600)
    v, s0, kp, ki = np.exp(out.x)
    servo = SpeedServo(s0=s0, kp=kp, ki=ki, s_min=0.0, s_max=50.0 * s_guess, tau_s=0.05)
    sim = simulate_speed_servo(v, q_f, t, p[0], servo=servo, p_sp_of_t=sp_f)
    return {"V": v, "s0": s0, "kp": kp, "ki": ki, "pred": sim.p_pa, "s_traj": sim.s_eff_m3s}


def metrics(p: np.ndarray, pred: np.ndarray, t: np.ndarray, long_on: np.ndarray) -> dict:
    """RMSE, MAPE, 잔차 구조 지표."""
    r = pred - p
    rmse = float(np.sqrt(np.mean(r ** 2)))
    mape = float(np.mean(np.abs(r / p)) * 100)
    # 잔차 자기상관 (lag 1) — 백색잡음이면 0 근처
    r_c = r - r.mean()
    ac1 = float(np.sum(r_c[:-1] * r_c[1:]) / np.sum(r_c ** 2)) if np.sum(r_c ** 2) > 0 else np.nan
    # 전환 구간 vs 평탄 구간 잔차 크기 비 (구조 유무 지표)
    trans = np.zeros_like(t, dtype=bool)
    sw = np.flatnonzero(np.diff(long_on.astype(int)) != 0)
    for i in sw:
        trans[max(i - 1, 0): min(i + 4, len(t))] = True
    rms_tr = float(np.sqrt(np.mean(r[trans] ** 2))) if trans.any() else np.nan
    rms_pl = float(np.sqrt(np.mean(r[~trans] ** 2))) if (~trans).any() else np.nan
    return {"rmse": rmse, "mape": mape, "resid_ac1": ac1,
            "rms_transition": rms_tr, "rms_plateau": rms_pl,
            "ratio_tr_pl": rms_tr / rms_pl if rms_pl else np.nan,
            "resid_max_abs": float(np.max(np.abs(r)))}


def main() -> None:
    rows, resid_store = [], {}
    groups = list_groups()
    for i, g in enumerate(groups, 1):
        c = build_cycle(g)
        if c is None:
            continue
        a = fit_fixed_s(c)
        b = fit_apc(c)
        ma = metrics(c["p"], a["pred"], c["t"], c["long_on"])
        mb = metrics(c["p"], b["pred"], c["t"], c["long_on"])
        p_span = float(c["p"].max() - c["p"].min())
        rows.append({
            "group": g, "date": c["date"], "seq": c["seq"], "exp_key": c["exp_key"],
            "p_span": p_span,
            "A_V": a["V"], "A_S": a["S"], "A_rmse": ma["rmse"], "A_mape": ma["mape"],
            "A_ac1": ma["resid_ac1"], "A_ratio": ma["ratio_tr_pl"],
            "A_rmse_frac": ma["rmse"] / p_span,
            "B_V": b["V"], "B_s0": b["s0"], "B_kp": b["kp"], "B_ki": b["ki"],
            "B_rmse": mb["rmse"], "B_mape": mb["mape"], "B_ac1": mb["resid_ac1"],
            "B_ratio": mb["ratio_tr_pl"], "B_rmse_frac": mb["rmse"] / p_span,
            "B_S_min": float(np.min(b["s_traj"])), "B_S_max": float(np.max(b["s_traj"])),
        })
        if g == "Day_2024_07_05_Wafer_02":
            resid_store = {"t": c["t"], "p": c["p"], "q": c["q"],
                           "predA": a["pred"], "predB": b["pred"],
                           "s_traj": b["s_traj"], "long_on": c["long_on"]}
        if i % 24 == 0:
            print(f"  ... {i}/{len(groups)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "phase3_validation.csv", index=False)
    pd.DataFrame(resid_store).to_csv(RESULTS / "phase3_example_cycle.csv", index=False)

    pd.set_option("display.width", 200)
    print("\n" + "=" * 84)
    print("Phase 3-3 실측 대조 — 모델 A(고정 S) vs 모델 B(APC 서보), n = %d" % len(df))
    print("=" * 84)
    print(f"\n측정 압력의 사이클 내 변동폭 (P_max − P_min): 평균 {df.p_span.mean():.5f} [P단위]\n")
    tbl = pd.DataFrame({
        "모델 A (고정 S)": [df.A_rmse.mean(), df.A_rmse_frac.mean() * 100, df.A_mape.mean(),
                          df.A_ac1.mean(), df.A_ratio.mean()],
        "모델 B (APC 서보)": [df.B_rmse.mean(), df.B_rmse_frac.mean() * 100, df.B_mape.mean(),
                           df.B_ac1.mean(), df.B_ratio.mean()],
    }, index=["RMSE [P단위]", "RMSE / 변동폭 [%]", "MAPE [%]",
              "잔차 lag-1 자기상관", "전환/평탄 잔차비"])
    print(tbl.round(5).to_string())
    print(f"\n모델 B 가 개선한 비율: RMSE {(1 - df.B_rmse.mean()/df.A_rmse.mean())*100:.1f} %")
    print(f"모델 B 가 더 나은 웨이퍼: {(df.B_rmse < df.A_rmse).sum()} / {len(df)}")

    print("\n적합된 파라미터 (원시 혼합 단위):")
    print(df[["A_V", "A_S", "B_V", "B_s0", "B_S_min", "B_S_max"]].describe().T
          .loc[:, ["mean", "std", "min", "max"]].round(2).to_string())
    print(f"\n  모델 B 의 S 궤적 변동폭 (S_max/S_min) 평균 = "
          f"{(df.B_S_max / df.B_S_min.clip(lower=1e-9)).median():.2f} 배")
    print("  → 서보가 한 주기 안에서 배기속도를 얼마나 움직여야 실측을 재현하는가")

    print("\n" + "=" * 84)
    print("잔차 구조 — 백색잡음인가")
    print("=" * 84)
    for tag in ("A", "B"):
        ac = df[f"{tag}_ac1"]
        ratio = df[f"{tag}_ratio"]
        print(f"  모델 {tag}: lag-1 자기상관 {ac.mean():+.4f} ± {ac.std():.4f} "
              f"(백색잡음이면 0),  전환/평탄 잔차비 {ratio.mean():.2f} ± {ratio.std():.2f} "
              f"(구조 없으면 1)")

    print("\n" + "=" * 84)
    print("적합 품질과 순번·로트의 관계")
    print("=" * 84)
    import statsmodels.formula.api as smf
    for tag in ("A", "B"):
        m = smf.ols(f"{tag}_rmse ~ C(date) + seq", data=df).fit()
        print(f"  모델 {tag} RMSE ~ C(lot)+seq : 순번 기울기 {m.params['seq']:+.3e}/장, "
              f"p = {m.pvalues['seq']:.3g},  로트 효과 R² = {m.rsquared:.3f}")

    print(f"\n저장: {RESULTS/'phase3_validation.csv'}, {RESULTS/'phase3_example_cycle.csv'}")


if __name__ == "__main__":
    main()
