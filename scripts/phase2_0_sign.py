"""Phase 2-0 / 3단계: 포어라인 압력 감소 방향의 기전 검토.

포어라인 압력이 로트 내에서 감소하는 것은 "배기 막힘"과 방향이 반대다.
후보 기전을 나열하고, 데이터로 구분 가능한 것과 불가능한 것을 분리한다.

단위 불가지론 — 다만 몰수지 자릿수 검토(4절)는 유량 단위를 sccm으로 가정해야만 가능하므로
해당 절에 한해 가정을 명시하고 조건부로 계산한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_0_analyse import MODELS, compare_models, within_lot_slope  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def shape_profile(df: pd.DataFrame, y: str) -> pd.Series:
    """로트 고정효과 제거 후 순번별 평균 프로파일 (첫 장 기준 정규화)."""
    d = df[["lot", "seq", y]].dropna().copy()
    d["c"] = d[y] - d.groupby("lot")[y].transform("mean")
    prof = d.groupby("seq")["c"].mean()
    return prof - prof.iloc[0]


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_0_wafer_summary.csv")
    d88 = df[df.has_89pt].copy()

    print("=" * 82)
    print("[A] 로트 내 형상 비교 — 포어라인 vs 식각깊이 (첫 장 대비, 로트효과 제거)")
    print("=" * 82)
    pf = shape_profile(df, "ForeLinePressure_mean")
    pe = shape_profile(d88, "si_etch_mean")
    ph = shape_profile(df, "HeliumBPFlow_mean")
    tab = pd.DataFrame({"포어라인Δ": pf, "si_etchΔ": pe, "He유량Δ": ph})
    tab["포어라인_정규화"] = tab["포어라인Δ"] / tab["포어라인Δ"].abs().max()
    tab["si_etch_정규화"] = tab["si_etchΔ"] / tab["si_etchΔ"].abs().max()
    print(tab.round(4).to_string())
    r, p = stats.pearsonr(tab["포어라인Δ"].values, tab["si_etchΔ"].values)
    print(f"\n  두 프로파일(순번 평균 10점)의 상관: r = {r:+.4f}, p = {p:.3g}")

    print("\n  형상 모델 AIC (식각깊이):")
    c = compare_models(d88, "si_etch_mean")
    print(c[["model", "AIC", "R2_adj", "dAIC", "weight"]].round(4).to_string(index=False))

    print("\n" + "=" * 82)
    print("[B] 몰수지 자릿수 검토 — 식각 생성물이 스루풋에 기여하는 크기")
    print("=" * 82)
    print("  가정 (전부 명시):")
    print("   (물성치) Si 밀도 2.329 g/cm³, Si 몰질량 28.085 g/mol")
    print("   (표준·규정) Readme 1절: 웨이퍼 200 mm, 노출 Si 면적 99.5% 초과")
    print("   (가정치) 식각 반응 Si + 4F → SiF4, 즉 Si 1몰당 기체 1몰 생성")
    print("   (가정치) 유량 단위 = sccm (0 °C 기준 22414 cm³/mol) — Phase 1에서 미확정")
    print("   (표준·규정) Bosch 총 공정시간 = 100 사이클 × 6.0 s = 600 s, 식각은 긴 스텝(74.2%)에서만")

    d_wafer_mm, exposed_frac = 200.0, 0.995
    area_cm2 = np.pi * (d_wafer_mm / 20.0) ** 2 * exposed_frac
    depth_um = d88["si_etch_mean"].mean()
    vol_cm3 = area_cm2 * depth_um * 1e-4
    mol_si = vol_cm3 * 2.329 / 28.085
    proc_s = 600.0
    mol_per_s = mol_si / proc_s
    sccm_equiv = mol_per_s / (1.0 / 22414.0 / 60.0)
    print(f"\n  노출 면적 = {area_cm2:.1f} cm²,  평균 식각깊이 = {depth_um:.2f} µm")
    print(f"  제거 Si 부피 = {vol_cm3:.4f} cm³  →  {mol_si*1e3:.2f} mmol")
    print(f"  SiF4 생성 몰유량 = {mol_per_s:.4e} mol/s  →  {sccm_equiv:.1f} sccm 등가")
    qtot = df["Qtot_mean"].mean()
    print(f"  측정 총 가스유량(사이클 평균) = {qtot:.1f} [원시단위]")
    print(f"  → 생성물이 총 스루풋에서 차지하는 비중 ≈ {sccm_equiv/(qtot+sccm_equiv)*100:.1f} %")

    sl = within_lot_slope(d88, "si_etch_mean")
    drop_pct = 10 * sl["slope"] / d88["si_etch_mean"].mean() * 100
    thr_change = sccm_equiv * (drop_pct / 100)
    print(f"\n  식각깊이 10장 변화 = {drop_pct:+.2f} %  →  생성물 유량 변화 = {thr_change:+.1f} sccm 등가")
    print(f"  이는 총 스루풋의 {thr_change/(qtot+sccm_equiv)*100:+.2f} % 에 해당")
    fl = within_lot_slope(df, "ForeLinePressure_mean")
    fl_pct = 10 * fl["slope"] / df["ForeLinePressure_mean"].mean() * 100
    print(f"  실측 포어라인 10장 변화  = {fl_pct:+.3f} %")
    print(f"  → 예측/실측 비 = {abs(thr_change/(qtot+sccm_equiv)*100)/abs(fl_pct):.2f} 배")

    print("\n" + "=" * 82)
    print("[C] 잔차 수준 연관 — 로트·순번을 통제하고도 남는 관계가 있는가")
    print("=" * 82)
    tgt = "si_etch_mean"
    cands = ["ForeLinePressure_mean", "long_ForeLinePressure", "short_ForeLinePressure",
             "HeliumBPFlow_mean", "HeliumBPPressure_mean", "Pressure_mean", "Qtot_mean",
             "Heater2Temp_mean", "Heater3Temp_mean", "Heater4Temp_mean",
             "SourceRFReflectedPower_mean", "PlatenRFLoadPower_mean", "moriInnerCurrent_mean"]
    rt = smf.ols(f"{tgt} ~ C(lot) + seq", data=d88).fit().resid
    rows = []
    for c in cands:
        if c not in d88.columns:
            continue
        rc = smf.ols(f"{c} ~ C(lot) + seq", data=d88).fit().resid
        r, p = stats.pearsonr(rc, rt)
        rows.append({"channel": c, "r_partial": r, "p": p})
    res = pd.DataFrame(rows).sort_values("p")
    res["p_bonferroni"] = (res["p"] * len(res)).clip(upper=1.0)
    print(f"  대상: {tgt} 잔차 (로트 고정효과 + 순번 통제, n={len(rt)})")
    print(res.round(4).to_string(index=False))
    print(f"\n  Bonferroni 보정(m={len(res)}) 후 p<0.05 인 채널: "
          f"{(res['p_bonferroni'] < 0.05).sum()}개")

    res.to_csv(RESULTS / "phase2_0_residual_scan.csv", index=False)
    tab.to_csv(RESULTS / "phase2_0_shape_profiles.csv")
    print(f"\n저장: {RESULTS/'phase2_0_residual_scan.csv'}, {RESULTS/'phase2_0_shape_profiles.csv'}")


if __name__ == "__main__":
    main()
