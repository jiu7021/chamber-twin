"""Phase 1 게이트 판정과 부수 분석.

게이트 (사용자 지정, Phase 0 단위 미확정을 반영한 대체안):
  모든 스텝·웨이퍼에 대해 x = Q/P_ss, y = 1/τ 로 원점통과 회귀.
  기준 (1) R² > 0.95  (2) 절편이 0의 95% 신뢰구간 안  (3) 기울기 역수 = 챔버 체적 V 보고
  산점도가 두 군집이면 긴 스텝/짧은 스텝을 분리해 각각 회귀하고 두 기울기 비교.

부수: 단위 판별 정합근거, 가스 종 판별, 컨디셔닝 후보 런, He 배면 추세.
단위 불가지론 — 어떤 환산도 하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physics.fit import regress_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

R2_MIN = 0.95
PATH_AGREE_TOL = 0.10  # 경로1·경로2 일치 허용오차 10%


def build_points(df: pd.DataFrame) -> pd.DataFrame:
    """웨이퍼×스텝종류 단위의 (x=Q/P_ss, y=1/τ) 표본을 만든다."""
    rows = []
    for tag in ("long", "short"):
        sub = pd.DataFrame({
            "group": df["group"], "date": df["date"], "wafer": df["wafer"],
            "exp_key": df["exp_key"], "has_89pt": df["has_89pt"], "step": tag,
            "Q": df[f"{tag}_Q_tot"], "P_ss": df[f"{tag}_P_ss"],
            "S_eff_p2": df[f"{tag}_S_eff_p2"], "tau_s": df[f"{tag}_tau_s"],
            "tau_r2": df[f"{tag}_tau_r2"],
        })
        sub["x"] = sub["Q"] / sub["P_ss"]      # = S_eff (경로 2), 단위 Q/P
        sub["y"] = 1.0 / sub["tau_s"]          # 단위 1/s
        sub["V_implied"] = sub["tau_s"] * sub["S_eff_p2"]
        rows.append(sub)
    return pd.concat(rows, ignore_index=True)


def report_reg(name: str, res) -> None:
    print(f"--- {name} (n={res.n}) ---")
    print(f"  원점통과 기울기 = {res.slope_origin:.6e} ± {res.slope_origin_se:.2e}"
          f"   → V = 1/기울기 = {res.V:,.1f}  [Q단위·s/P단위]")
    print(f"  비중심 R²(원점통과) = {res.r2_origin_uncentered:.4f}")
    print(f"  절편 포함 OLS: 기울기 = {res.slope_ols:.4e}, 절편 = {res.intercept:.4f} ± {res.intercept_se:.4f}")
    print(f"    절편 95% CI = [{res.intercept_ci[0]:.4f}, {res.intercept_ci[1]:.4f}]"
          f"  → 0 포함? {'예' if res.intercept_contains_zero else '아니오'}")
    print(f"    표준 R²(OLS) = {res.r2_ols:.4f}   → R²>{R2_MIN}? "
          f"{'통과' if res.r2_ols > R2_MIN else '실패'}")


def main() -> None:
    df = pd.read_parquet(RESULTS / "taskA_seff.parquet")
    pts = build_points(df)
    pts.to_csv(RESULTS / "taskA_gate_points.csv", index=False)

    print("=" * 78)
    print("Phase 1 게이트: x = Q/P_ss,  y = 1/τ,  원점통과 회귀 (기울기 역수 = V)")
    print("=" * 78)
    print()
    print("[군집 확인] 스텝종류별 x, y 분포")
    print(pts.groupby("step")[["x", "y", "tau_s", "P_ss", "Q", "V_implied"]]
          .agg(["mean", "std"]).round(4).to_string())
    print()

    res_all = regress_gate(pts["x"].values, pts["y"].values)
    report_reg("전체 (긴+짧은 스텝 통합, 192점)", res_all)
    print()

    res_by = {}
    for tag in ("long", "short"):
        s = pts[pts["step"] == tag]
        res_by[tag] = regress_gate(s["x"].values, s["y"].values)
        report_reg(f"{'긴' if tag=='long' else '짧은'} 스텝 단독", res_by[tag])
        print()

    print("[두 군집 기울기 비교] — 공통 V라면 두 기울기가 같아야 한다")
    sl, ss = res_by["long"].slope_origin, res_by["short"].slope_origin
    print(f"  긴 스텝  기울기 = {sl:.6e}  → V = {1/sl:,.1f}")
    print(f"  짧은 스텝 기울기 = {ss:.6e}  → V = {1/ss:,.1f}")
    print(f"  기울기 비 (짧은/긴) = {ss/sl:.3f}   (일치라면 1.000)")
    print(f"  V 불일치율 = {abs(1/ss - 1/sl)/(1/sl)*100:.1f}%   (허용 {PATH_AGREE_TOL*100:.0f}%)")
    print()

    print("[경로1 · 경로2 일치 검정] V = τ·S_eff 가 스텝종류에 무관해야 한다")
    vl = df["long_tau_s"] * df["long_S_eff_p2"]
    vs = df["short_tau_s"] * df["short_S_eff_p2"]
    print(f"  긴 스텝  V = {vl.mean():,.1f} ± {vl.std():,.1f}")
    print(f"  짧은 스텝 V = {vs.mean():,.1f} ± {vs.std():,.1f}")
    print(f"  불일치 = {abs(vl.mean()-vs.mean())/vs.mean()*100:.1f}%  "
          f"→ 10% 이내? {'통과' if abs(vl.mean()-vs.mean())/vs.mean() < PATH_AGREE_TOL else '실패'}")
    print()

    print("[τ 분포 단봉성 검정]")
    for tag in ("long", "short"):
        v = df[f"{tag}_tau_s"].dropna().values
        print(f"  {tag}: mean={v.mean():.4f}s std={v.std():.4f}s "
              f"skew={stats.skew(v):+.2f} kurt={stats.kurtosis(v):+.2f} "
              f"Shapiro p={stats.shapiro(v).pvalue:.3g}")
    both = np.concatenate([df["long_tau_s"].values, df["short_tau_s"].values])
    print(f"  통합 τ: 긴 {df.long_tau_s.mean():.3f}s vs 짧은 {df.short_tau_s.mean():.3f}s "
          f"→ t검정 p={stats.ttest_ind(df.long_tau_s, df.short_tau_s).pvalue:.3g} (분리 필요성)")
    print()

    print("=" * 78)
    print("부수 분석")
    print("=" * 78)
    print()
    print("[4] 단위 판별 — 압력 채널 크기 관계 (정합 근거, 확정 아님)")
    for ch in ("Pressure", "ForeLinePressure", "HeliumBPPressure"):
        c = f"mean_{ch}"
        print(f"  {ch:20s} 평균 {df[c].mean():10.4f}   CV {df[c].std()/df[c].mean()*100:7.4f}%")
    print(f"  HeliumBP/Chamber  = {(df.mean_HeliumBPPressure/df.mean_Pressure).median():8.1f}")
    print(f"  ForeLine /Chamber = {(df.mean_ForeLinePressure/df.mean_Pressure).median():8.1f}")
    print(f"  HeliumBP/ForeLine = {(df.mean_HeliumBPPressure/df.mean_ForeLinePressure).median():8.4f}")
    print()

    print("[5] 가스 종 판별 지표")
    print(f"  긴 스텝 : P_ss={df.long_P_ss.mean():.5f}  PlatenPwr(평탄부)={df.long_PlatenRFLoadPower.mean():6.2f}"
          f"  SourcePwr={df.long_SourceRFLoadPower.mean():7.1f}  지속={df.long_dur_med_s.mean():.3f}s")
    print(f"  짧은스텝: P_ss={df.short_P_ss.mean():.5f}  PlatenPwr(평탄부)={df.short_PlatenRFLoadPower.mean():6.2f}"
          f"  SourcePwr={df.short_SourceRFLoadPower.mean():7.1f}  지속={df.short_dur_med_s.mean():.3f}s")
    print("  → 압력 지표: 짧은 스텝이 높음 → 사용자 규칙상 짧은=SF6 후보")
    print("  → 지속시간 지표: 긴 4.45s≈레시피 SF6 4.5s, 짧은 1.48s≈C4F8 1.5s → 긴=SF6 후보")
    print("  → 두 지표 상충 → 미확정. 이하 '긴 스텝/짧은 스텝'으로 지칭.")
    print()

    print("[6] 89점 측정이 없는 8장 (컨디셔닝 런 후보) 의 S_eff")
    miss = df[~df["has_89pt"]].sort_values(["date", "wafer"])
    print(miss[["exp_key", "long_S_eff_p2", "short_S_eff_p2", "long_P_ss",
                "mean_ForeLinePressure"]].round(5).to_string(index=False))
    print(f"  측정 있는 88장 평균 long_S_eff = {df[df.has_89pt].long_S_eff_p2.mean():.2f} "
          f"± {df[df.has_89pt].long_S_eff_p2.std():.2f}")
    print(f"  측정 없는  8장 평균 long_S_eff = {miss.long_S_eff_p2.mean():.2f} "
          f"± {miss.long_S_eff_p2.std():.2f}")
    tt = stats.ttest_ind(df[df.has_89pt].long_S_eff_p2, miss.long_S_eff_p2)
    print(f"  t검정 p = {tt.pvalue:.3g}")
    print()

    print("[7] He 배면: 웨이퍼별 평균과 로트 내 순번 추세 (Phase 2용)")
    he = df[["date", "wafer", "exp_key", "mean_HeliumBPPressure", "mean_HeliumBPFlow",
             "std_HeliumBPPressure", "mean_ForeLinePressure", "long_S_eff_p2",
             "short_S_eff_p2", "has_89pt"]].copy()
    he.to_csv(RESULTS / "phase1_he_backside.csv", index=False)
    for col in ("mean_HeliumBPPressure", "mean_HeliumBPFlow", "mean_ForeLinePressure",
                "long_S_eff_p2"):
        # 로트(날짜)별 중심화 후 순번 회귀 = 로트 간 변동 흡수
        d = he.copy()
        d["centered"] = d[col] - d.groupby("date")[col].transform("mean")
        lr = stats.linregress(d["wafer"], d["centered"])
        print(f"  {col:24s} 순번기울기 = {lr.slope:+.6g} /장  "
              f"p = {lr.pvalue:.3g}  R² = {lr.rvalue**2:.4f}  "
              f"(전체 CV {d[col].std()/d[col].mean()*100:.3f}%)")
    print(f"\n  저장: {RESULTS/'phase1_he_backside.csv'}, {RESULTS/'taskA_gate_points.csv'}")


if __name__ == "__main__":
    main()
