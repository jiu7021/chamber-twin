"""Phase 2 (축소판) / Task B: 로트 내 순번 효과 특성화와 31개 채널 전수 음성 결과.

범위
  1) si_etch_mean, si_etch_cv 의 순번 효과 — 기울기, 신뢰구간, 형상(선형/포화)
  2) 31개 공통 채널 전수 — 순번 추세 + 순번 통제 후 si_etch 부분상관 + Bonferroni 보정
  3) 식각량 감소 / 균일도 개선 동시 발생 기록
  4) 포어라인 톱니 종결 요약

인과 주장 없음. 상관·추세로만 기술한다.
단위 불가지론 — 채널 값은 원시 단위. 식각 측정값만 µm (Readme 2.3절 명시).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.dataio import list_groups, load_run  # noqa: E402
from physics.steps import LONG_BAND_S, find_steps  # noqa: E402
from scripts.phase2_0_extract import LOT_INFO, etch_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# 31개 공통 채널 (Phase 0 확인). 첫날 10그룹에만 있는 13개는 전부 상수이므로 제외.
COMMON_31 = [
    "EpdIntensity", "ForeLinePressure", "Gas1Flow", "Gas2Flow", "Gas3Flow", "Gas4Flow",
    "Gas5Flow", "Gas7Flow", "Gas8Flow", "Heater1Temp", "Heater2Temp", "Heater3Temp",
    "Heater4Temp", "HeliumBPFlow", "HeliumBPPressure", "PlatenDcBias",
    "PlatenRFLoadCapacitor", "PlatenRFLoadPower", "PlatenRFPeakToPeak",
    "PlatenRFReflectedPower", "PlatenRFTuningCapacitor", "Pressure",
    "SourceRF2LoadPower", "SourceRF2PeakToPeak", "SourceRF2ReflectedPower",
    "SourceRF2TuningCapacitor", "SourceRFLoadPower", "SourceRFPeakToPeak",
    "SourceRFReflectedPower", "SourceRFTuningCapacitor", "moriInnerCurrent",
]

SHAPE_MODELS = {
    "선형   C(lot)+seq": "{y} ~ C(lot) + seq",
    "2차    C(lot)+seq+seq²": "{y} ~ C(lot) + seq + I(seq**2)",
    "포화형 C(lot)+log(seq)": "{y} ~ C(lot) + np.log(seq)",
    "로트만 C(lot)": "{y} ~ C(lot)",
}


def extract_channels() -> pd.DataFrame:
    """96장 각각의 Bosch 구간에서 31개 공통 채널 평균을 뽑는다."""
    rows = []
    for i, g in enumerate(list_groups(), 1):
        r = load_run(g)
        L = find_steps(r.df, "Gas5Flow", LONG_BAND_S)
        bosch = r.df.loc[L.rise_s[0]: L.rise_s[-1] + 4.4]
        row = {"group": g, "date": r.date, "seq": r.wafer, "exp_key": r.exp_key}
        row["lot"], row["cond_type"] = LOT_INFO[r.date]
        for ch in COMMON_31:
            row[ch] = float(bosch[ch].mean()) if ch in bosch.columns else np.nan
        rows.append(row)
        if i % 32 == 0:
            print(f"  ... {i}/96", flush=True)
    return pd.DataFrame(rows)


def seq_effect(df: pd.DataFrame, y: str) -> dict:
    """로트 고정효과를 통제한 순번 기울기와 95% 신뢰구간."""
    d = df[[y, "lot", "seq"]].dropna()
    if d[y].std() == 0 or len(d) < 12:
        return {"slope": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "p": np.nan,
                "R2": np.nan, "pct10": np.nan, "cv": 0.0}
    m = smf.ols(f"{y} ~ C(lot) + seq", data=d).fit()
    ci = m.conf_int().loc["seq"]
    mean = d[y].mean()
    return {"slope": float(m.params["seq"]), "ci_lo": float(ci[0]), "ci_hi": float(ci[1]),
            "p": float(m.pvalues["seq"]), "R2": float(m.rsquared),
            "pct10": 10 * float(m.params["seq"]) / mean * 100 if mean else np.nan,
            "cv": float(d[y].std() / mean * 100) if mean else np.nan}


def partial_r(df: pd.DataFrame, ch: str, tgt: str) -> tuple[float, float]:
    """로트 고정효과 + 순번을 통제한 ch와 tgt의 부분상관."""
    d = df[[ch, tgt, "lot", "seq"]].dropna()
    if d[ch].std() == 0 or len(d) < 12:
        return np.nan, np.nan
    ra = smf.ols(f"{ch} ~ C(lot) + seq", data=d).fit().resid
    rb = smf.ols(f"{tgt} ~ C(lot) + seq", data=d).fit().resid
    if ra.std() == 0:
        return np.nan, np.nan
    r, p = stats.pearsonr(ra, rb)
    return float(r), float(p)


def shape_table(df: pd.DataFrame, y: str) -> pd.DataFrame:
    """형상 모델 AIC 비교."""
    rows = []
    for name, tmpl in SHAPE_MODELS.items():
        m = smf.ols(tmpl.format(y=y), data=df).fit()
        rows.append({"모델": name, "AIC": m.aic, "R2_adj": m.rsquared_adj,
                     "resid_sd": float(np.sqrt(m.mse_resid))})
    out = pd.DataFrame(rows).sort_values("AIC").reset_index(drop=True)
    out["dAIC"] = out["AIC"] - out["AIC"].min()
    return out


def profile(df: pd.DataFrame, y: str) -> pd.DataFrame:
    """로트 중심화 후 순번별 평균 프로파일 (첫 장 기준, ±SEM)."""
    d = df[["lot", "seq", y]].dropna().copy()
    d["c"] = d[y] - d.groupby("lot")[y].transform("mean")
    p = d.groupby("seq")["c"].agg(["mean", "sem", "size"])
    p["mean"] -= p["mean"].iloc[0]
    p["norm"] = p["mean"] / p["mean"].abs().max()
    p["frac_by_seq3"] = np.nan
    return p


def main() -> None:
    ch_path = RESULTS / "phase2_channels_31.csv"
    if ch_path.exists():
        df = pd.read_csv(ch_path)
    else:
        df = extract_channels()
        df.to_csv(ch_path, index=False)
    df = df.merge(etch_metrics(), on="exp_key", how="left")
    d88 = df[df["si_etch_mean"].notna()].copy()

    print("=" * 84)
    print("[1] 로트 내 순번 효과 특성화 — si_etch_mean / si_etch_cv")
    print("=" * 84)
    for y, lab, unit in (("si_etch_mean", "평균 Si 식각깊이", "µm"),
                         ("si_etch_cv", "면내 균일도 (표준편차/평균)", "-")):
        e = seq_effect(d88, y)
        print(f"\n  {lab}  (평균 {d88[y].mean():.5g} {unit}, n = {d88[y].notna().sum()})")
        print(f"    순번 기울기 = {e['slope']:+.6g} {unit}/장")
        print(f"    95% 신뢰구간 = [{e['ci_lo']:+.6g}, {e['ci_hi']:+.6g}]")
        print(f"    p = {e['p']:.3g},  모델 R² = {e['R2']:.4f}")
        print(f"    10장 누적 변화 = {e['pct10']:+.2f} %  "
              f"(절대 {10*e['slope']:+.5g} {unit})")
        print("    형상 모델 AIC:")
        print(shape_table(d88, y).round(3).to_string(index=False).replace("\n", "\n      "))
        p = profile(d88, y)
        f3 = (p["mean"].iloc[0] - p["mean"].iloc[2]) / (p["mean"].iloc[0] - p["mean"].min())
        print(f"    첫 3장에서 진행된 비율 = {f3*100:.1f} %")
        print("    순번별 프로파일 (첫 장 대비, 로트 중심화):")
        print("      " + "  ".join(f"{s}:{v:+.4f}" for s, v in p["mean"].items()))

    print("\n" + "=" * 84)
    print("[2] 31개 공통 채널 전수 — 순번 추세 및 si_etch_mean 부분상관")
    print("=" * 84)
    rows = []
    for ch in COMMON_31:
        e = seq_effect(df, ch)
        r_m, p_m = partial_r(d88, ch, "si_etch_mean")
        r_c, p_c = partial_r(d88, ch, "si_etch_cv")
        rows.append({
            "채널": ch, "평균": df[ch].mean(), "CV_%": e["cv"],
            "순번기울기": e["slope"], "순번p": e["p"], "10장_%": e["pct10"],
            "부분r_depth": r_m, "부분p_depth": p_m,
            "부분r_cv": r_c, "부분p_cv": p_c,
        })
    tab = pd.DataFrame(rows)
    n_test = tab["부분p_depth"].notna().sum()
    for c in ("depth", "cv"):
        tab[f"bonf_{c}"] = (tab[f"부분p_{c}"] * n_test).clip(upper=1.0)
    tab = tab.sort_values("부분p_depth", na_position="last").reset_index(drop=True)
    tab.to_csv(RESULTS / "phase2_channel_scan.csv", index=False)

    show = tab.copy()
    for c in ["평균", "CV_%", "10장_%", "부분r_depth", "부분r_cv"]:
        show[c] = show[c].round(4)
    for c in ["순번기울기"]:
        show[c] = show[c].apply(lambda v: f"{v:+.4g}" if pd.notna(v) else "—")
    for c in ["순번p", "부분p_depth", "부분p_cv", "bonf_depth", "bonf_cv"]:
        show[c] = show[c].apply(lambda v: f"{v:.3g}" if pd.notna(v) else "—")
    print(show.to_string(index=False))

    print(f"\n  검정한 채널 수 (분산 0 제외) m = {n_test}")
    for c, lab in (("depth", "si_etch_mean"), ("cv", "si_etch_cv")):
        raw = (tab[f"부분p_{c}"] < 0.05).sum()
        bon = (tab[f"bonf_{c}"] < 0.05).sum()
        print(f"  {lab}: 보정 전 p<0.05 = {raw}개,  Bonferroni 보정 후 p<0.05 = {bon}개")
        if bon:
            print("    보정 통과 채널:")
            for _, r in tab[tab[f"bonf_{c}"] < 0.05].iterrows():
                print(f"      {r['채널']}  r={r[f'부분r_{c}']:+.4f}  "
                      f"보정p={r[f'bonf_{c}']:.4f}  (CV {r['CV_%']:.4f}%)")

    print(f"\n  분산 0 채널 (검정 제외): "
          f"{', '.join(tab[tab['부분p_depth'].isna()]['채널'].tolist())}")

    print("\n" + "=" * 84)
    print("[3] 식각량 감소 / 균일도 개선 동시 발생")
    print("=" * 84)
    d = d88.copy()
    for c in ("si_etch_mean", "si_etch_cv", "si_etch_std"):
        d[c + "_c"] = d[c] - d.groupby("lot")[c].transform("mean")
    r, p = stats.pearsonr(d["si_etch_mean_c"], d["si_etch_cv_c"])
    print(f"  로트 중심화 후 깊이 vs 균일도 상관: r = {r:+.4f}, p = {p:.3g}, n = {len(d)}")
    e_std = seq_effect(d88, "si_etch_std")
    print(f"  si_etch_std 순번 기울기 = {e_std['slope']:+.6g} µm/장, p = {e_std['p']:.3g}, "
          f"10장 {e_std['pct10']:+.2f} %")
    print(f"  → 깊이 {seq_effect(d88,'si_etch_mean')['pct10']:+.2f} %, "
          f"표준편차 {e_std['pct10']:+.2f} %, "
          f"변동계수 {seq_effect(d88,'si_etch_cv')['pct10']:+.2f} % (10장 기준)")

    print("\n" + "=" * 84)
    print("[4] 포어라인 톱니 — 종결 요약 (Phase 2-0 결과 인용, 추가 분석 없음)")
    print("=" * 84)
    e = seq_effect(df, "ForeLinePressure")
    r_m, p_m = partial_r(d88, "ForeLinePressure", "si_etch_mean")
    print(f"  순번 기울기 = {e['slope']:+.6g}/장, 95%CI [{e['ci_lo']:+.5g}, {e['ci_hi']:+.5g}], "
          f"p = {e['p']:.3g}, 10장 {e['pct10']:+.3f} %")
    print(f"  si_etch_mean 부분상관 (로트·순번 통제) r = {r_m:+.4f}, p = {p_m:.3g}")
    print("  기전: 클리닝 리셋 vs 당일 웜업 — 로트 = 날짜 완전 교락으로 판정 불가. 종료.")
    print(f"\n저장: {RESULTS/'phase2_channel_scan.csv'}, {ch_path}")


if __name__ == "__main__":
    main()
