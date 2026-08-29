"""Phase 2-0 / 2단계: 포어라인 압력 분해, AIC 모델 비교, 교란변수 검정, He 배면 분석.

판정 대상
  (a) 로트마다 리셋되는 톱니   → 챔버·배기계통 상태 기인
  (b) 로트와 무관한 단조 드리프트 → 열 또는 계측기 드리프트

단위 불가지론 — 환산하지 않는다. 시간만 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

TEMP_CH = ["Heater1Temp_mean", "Heater2Temp_mean", "Heater3Temp_mean", "Heater4Temp_mean"]

MODELS = {
    "M0 널             y ~ 1": "{y} ~ 1",
    "M1 단조드리프트    y ~ global_idx": "{y} ~ global_idx",
    "M2 로트평균만      y ~ C(lot)": "{y} ~ C(lot)",
    "M3 톱니(선형)      y ~ C(lot)+seq": "{y} ~ C(lot) + seq",
    "M4 톱니(포화형)    y ~ C(lot)+log(seq)": "{y} ~ C(lot) + np.log(seq)",
    "M5 톱니(2차)       y ~ C(lot)+seq+seq²": "{y} ~ C(lot) + seq + I(seq**2)",
    "M6 순번만          y ~ seq": "{y} ~ seq",
    "M7 드리프트+순번   y ~ global_idx+seq": "{y} ~ global_idx + seq",
}


def compare_models(df: pd.DataFrame, y: str) -> pd.DataFrame:
    """후보 모델들을 적합하고 AIC로 비교한다."""
    rows = []
    for name, tmpl in MODELS.items():
        m = smf.ols(tmpl.format(y=y), data=df).fit()
        rows.append({"model": name, "k": int(m.df_model) + 1, "AIC": m.aic,
                     "BIC": m.bic, "R2": m.rsquared, "R2_adj": m.rsquared_adj,
                     "resid_sd": float(np.sqrt(m.mse_resid))})
    out = pd.DataFrame(rows).sort_values("AIC").reset_index(drop=True)
    out["dAIC"] = out["AIC"] - out["AIC"].min()
    # Akaike 가중치
    w = np.exp(-0.5 * out["dAIC"])
    out["weight"] = w / w.sum()
    return out


def within_lot_slope(df: pd.DataFrame, y: str) -> dict:
    """로트 고정효과를 넣은 로트 내 순번 기울기와 통계량."""
    m = smf.ols(f"{y} ~ C(lot) + seq", data=df).fit()
    ci = m.conf_int().loc["seq"]
    return {"slope": float(m.params["seq"]), "se": float(m.bse["seq"]),
            "p": float(m.pvalues["seq"]), "ci_lo": float(ci[0]), "ci_hi": float(ci[1]),
            "R2": float(m.rsquared)}


def partial_corr(df: pd.DataFrame, a: str, b: str, controls: str) -> tuple[float, float, int]:
    """controls를 통제한 a와 b의 부분상관 (잔차 상관)."""
    d = df[[a, b]].join(df[[c for c in ["lot", "seq"] if c in df]]).dropna()
    ra = smf.ols(f"{a} ~ {controls}", data=d).fit().resid
    rb = smf.ols(f"{b} ~ {controls}", data=d).fit().resid
    r, p = stats.pearsonr(ra, rb)
    return float(r), float(p), len(d)


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_0_wafer_summary.csv")
    Y = "ForeLinePressure_mean"

    print("=" * 82)
    print("Phase 2-0  포어라인 압력 분해 — 톱니(로트 리셋) vs 단조 드리프트")
    print("=" * 82)

    print("\n[1] 로트별 순번 프로파일 (ForeLinePressure_mean)")
    piv = df.pivot_table(index="lot", columns="seq", values=Y)
    print(piv.round(2).to_string())
    print("\n  로트별 (첫장 − 끝장):")
    for lot, s in df.groupby("lot"):
        s = s.sort_values("seq")
        print(f"    Lot {lot:2d} ({s.date.iloc[0]}, {s.cond_type.iloc[0]:8s}) "
              f"n={len(s):2d}  첫 {s[Y].iloc[0]:7.3f} → 끝 {s[Y].iloc[-1]:7.3f}  "
              f"Δ = {s[Y].iloc[-1]-s[Y].iloc[0]:+.3f}")
    print(f"\n  로트 내 변동폭 평균 = {df.groupby('lot')[Y].apply(lambda s: s.max()-s.min()).mean():.3f}")
    print(f"  로트 간 평균의 변동폭 = {df.groupby('lot')[Y].mean().max()-df.groupby('lot')[Y].mean().min():.3f}")

    print("\n[2] AIC 모델 비교 — ForeLinePressure_mean")
    cmp = compare_models(df, Y)
    print(cmp.round(4).to_string(index=False))
    best = cmp.iloc[0]
    print(f"\n  최적 모델: {best['model']}   (Akaike 가중치 {best['weight']:.4f})")
    a_models = cmp[cmp["model"].str.contains("톱니")]["AIC"].min()
    b_models = cmp[cmp["model"].str.contains("단조드리프트")]["AIC"].min()
    print(f"  (a) 톱니 계열 최소 AIC = {a_models:.2f}")
    print(f"  (b) 단조드리프트 AIC   = {b_models:.2f}")
    print(f"  ΔAIC = {b_models - a_models:.2f}  →  "
          f"{'(a) 톱니 압도적 지지' if b_models-a_models > 10 else '판정 보류'}")

    print("\n[3] 로트 내 순번 기울기 (로트 고정효과 통제)")
    for ch in [Y, "long_ForeLinePressure", "short_ForeLinePressure",
               "HeliumBPFlow_mean", "HeliumBPPressure_mean", "Pressure_mean",
               "Qtot_mean"] + TEMP_CH:
        if ch not in df.columns:
            continue
        r = within_lot_slope(df, ch)
        mean = df[ch].mean()
        print(f"  {ch:26s} 기울기 {r['slope']:+.6g}/장  "
              f"95%CI[{r['ci_lo']:+.5g},{r['ci_hi']:+.5g}]  p={r['p']:.3g}  "
              f"R²={r['R2']:.3f}  (평균 대비 10장 {10*r['slope']/mean*100:+.3f}%)")

    print("\n[4] 교란변수 — 온도 채널과 포어라인의 관계")
    print("  온도 채널 기본 통계:")
    for ch in TEMP_CH:
        print(f"    {ch:22s} 평균 {df[ch].mean():9.4f}  표준편차 {df[ch].std():8.5f}  "
              f"CV {df[ch].std()/df[ch].mean()*100:7.4f}%")
    print(f"    {'ForeLinePressure_mean':22s} 평균 {df[Y].mean():9.4f}  표준편차 {df[Y].std():8.5f}  "
          f"CV {df[Y].std()/df[Y].mean()*100:7.4f}%")
    print("\n  상관 (원시 / 로트내 중심화 후):")
    for ch in TEMP_CH:
        r_raw, p_raw = stats.pearsonr(df[ch], df[Y])
        d = df.copy()
        for c in (ch, Y):
            d[c + "_c"] = d[c] - d.groupby("lot")[c].transform("mean")
        r_c, p_c = stats.pearsonr(d[ch + "_c"], d[Y + "_c"])
        print(f"    {ch:22s} 원시 r={r_raw:+.3f} (p={p_raw:.3g})   "
              f"로트내 r={r_c:+.3f} (p={p_c:.3g})")

    print("\n[5] He 배면 유량 — 열전달 축")
    for ch in ("HeliumBPFlow_mean", "HeliumBPPressure_mean"):
        c = compare_models(df, ch)
        print(f"  {ch}: 최적 = {c.iloc[0]['model']}  (dAIC 2위 {c.iloc[1]['dAIC']:.2f})")
    print("\n  He 유량 vs 식각 결과 상관 (88장, 89점 측정 보유):")
    d = df[df.has_89pt].copy()
    for tgt in ("si_etch_mean", "si_etch_cv", "si_etch_std", "si_etch_range",
                "oxide_etch_mean", "oxide_etch_cv"):
        if tgt not in d.columns:
            continue
        r_raw, p_raw = stats.pearsonr(d["HeliumBPFlow_mean"], d[tgt])
        r_p, p_p, n = partial_corr(d, "HeliumBPFlow_mean", tgt, "C(lot) + seq")
        print(f"    He유량 ~ {tgt:16s} 원시 r={r_raw:+.3f} (p={p_raw:.3g})   "
              f"부분상관(로트·순번 통제) r={r_p:+.3f} (p={p_p:.3g}, n={n})")

    print("\n  참고 — 포어라인 vs 식각 결과:")
    for tgt in ("si_etch_mean", "si_etch_cv"):
        r_raw, p_raw = stats.pearsonr(d[Y], d[tgt])
        r_p, p_p, n = partial_corr(d, Y, tgt, "C(lot) + seq")
        print(f"    포어라인 ~ {tgt:16s} 원시 r={r_raw:+.3f} (p={p_raw:.3g})   "
              f"부분상관 r={r_p:+.3f} (p={p_p:.3g}, n={n})")

    print("\n  참고 — 식각 결과 자체의 순번 추세:")
    for tgt in ("si_etch_mean", "si_etch_cv"):
        r = within_lot_slope(d, tgt)
        print(f"    {tgt:16s} 기울기 {r['slope']:+.6g}/장  p={r['p']:.3g}  "
              f"(평균 {d[tgt].mean():.5g}, 10장 {10*r['slope']/d[tgt].mean()*100:+.2f}%)")

    cmp.to_csv(RESULTS / "phase2_0_aic_foreline.csv", index=False)
    print(f"\n저장: {RESULTS/'phase2_0_aic_foreline.csv'}")


if __name__ == "__main__":
    main()
