"""Phase 2R / 2~3단계: 플라즈마 부하 임피던스 역산과 검정.

2단계
  - 토폴로지 후보(L형·T형·Π형)별 역산식을 ABCD 행렬로 유도
  - 각 경우 무엇이 결정되고 무엇이 미결정으로 남는지 명시
  - 절대값 불가 → 웨이퍼 1번 대비 상대 변화로 산출 (미지수는 소인)
  - 반사 전력으로 정합 품질 지표 산출

3단계
  - 역산 지표의 순번 추세 (기울기, CI, p, 형상)
  - 로트·순번 통제 후 si_etch_mean / si_etch_cv 부분상관
  - 다중비교 보정

원시 커패시터 값을 회귀에 직접 넣지 않는다. 인과 표현을 쓰지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.rfmatch import match_quality, zl_L, zl_pi, zl_T  # noqa: E402
from scripts.phase2_0_extract import etch_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

CT = "PlatenRFTuningCapacitor"
CL = "PlatenRFLoadCapacitor"

# 소인(sweep) 범위 — 미지 동작점. 플라즈마 부하 저항은 Z0 보다 훨씬 낮은 것이 통상.
# (통상범위: 용량결합 플라즈마 바이어스 부하 R ≈ 1~25 Ω @ Z0 = 50 Ω → r0 = 0.02~0.5)
R0_SWEEP = np.array([0.02, 0.05, 0.10, 0.20, 0.35, 0.50])
# 직렬 커패시터의 정규화 용량성 리액턴스 크기 s = 1/(ω·C_se·Z0). 미지 → 폭넓게 소인.
S_SWEEP = np.array([0.1, 0.3, 1.0, 3.0, 10.0])


def numeric_jacobian(topology: str, r0: float, extra: dict) -> np.ndarray:
    """토폴로지별로 [∂lnR/∂lnC1, ∂lnR/∂lnC2; ∂X/∂lnC1, ∂X/∂lnC2] 를 수치미분한다.

    Args:
        topology: 'L' | 'pi' | 'T'
        r0: 동작점의 정규화 부하 저항 R/Z0
        extra: 토폴로지별 부가 미지수

    Returns:
        2×2 야코비안 (행: lnR, X / 열: C1, C2). 모두 Z0 정규화 무차원.
    """
    h = 1e-6

    if topology == "L":
        b = np.sqrt(max(1.0 / r0 - 1.0, 1e-12))   # 병렬 서셉턴스 (R = 1/(1+b²))
        s = extra["s"]                             # 직렬 커패시터 리액턴스 크기
        x_se = extra.get("x_se", 0.0)

        def f(lc1: float, lc2: float) -> complex:
            # C1 = 병렬 커패시터 → b ∝ C1;  C2 = 직렬 커패시터 → x_se 에 −s/C2 로 기여
            return zl_L(b * np.exp(lc1), x_se - s * (np.exp(-lc2) - 1.0))

    elif topology == "pi":
        b1 = np.sqrt(max(1.0 / r0 - 1.0, 1e-12))
        b2, x_se = extra["b2"], extra["x_se"]

        def f(lc1: float, lc2: float) -> complex:
            return zl_pi(b1 * np.exp(lc1), x_se, b2 * np.exp(lc2))

    else:  # T형
        x1, b_sh, x2 = extra["x1"], extra["b_sh"], extra["x2"]

        def f(lc1: float, lc2: float) -> complex:
            # 직렬 커패시터: X = −1/(ωC) 이므로 C 가 커지면 |X| 감소
            return zl_T(x1 * np.exp(-lc1), b_sh, x2 * np.exp(-lc2))

    z0v = f(0.0, 0.0)
    d1 = (f(h, 0.0) - f(-h, 0.0)) / (2 * h)
    d2 = (f(0.0, h) - f(0.0, -h)) / (2 * h)
    return np.array([[d1.real / z0v.real, d2.real / z0v.real],
                     [d1.imag, d2.imag]])


def within_lot_slope(df: pd.DataFrame, y: str) -> dict:
    d = df[[y, "lot", "seq"]].dropna()
    if d[y].std() == 0:
        return {"slope": np.nan, "p": np.nan, "ci": (np.nan, np.nan), "R2": np.nan}
    m = smf.ols(f"{y} ~ C(lot) + seq", data=d).fit()
    ci = m.conf_int().loc["seq"]
    return {"slope": float(m.params["seq"]), "p": float(m.pvalues["seq"]),
            "ci": (float(ci[0]), float(ci[1])), "R2": float(m.rsquared)}


def partial_r(df: pd.DataFrame, a: str, b: str) -> tuple[float, float]:
    d = df[[a, b, "lot", "seq"]].dropna()
    if d[a].std() == 0:
        return np.nan, np.nan
    ra = smf.ols(f"{a} ~ C(lot) + seq", data=d).fit().resid
    rb = smf.ols(f"{b} ~ C(lot) + seq", data=d).fit().resid
    r, p = stats.pearsonr(ra, rb)
    return float(r), float(p)


def shape_aic(df: pd.DataFrame, y: str) -> str:
    out = {}
    for name, t in (("선형", "{y} ~ C(lot) + seq"),
                    ("2차", "{y} ~ C(lot) + seq + I(seq**2)"),
                    ("포화형", "{y} ~ C(lot) + np.log(seq)")):
        out[name] = smf.ols(t.format(y=y), data=df).fit().aic
    best = min(out, key=out.get)
    second = sorted(out.values())[1]
    return f"{best} (2위와 ΔAIC {second - out[best]:.2f})"


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_channels_31.csv").merge(
        etch_metrics(), on="exp_key", how="left")
    d = df[df["si_etch_mean"].notna()].reset_index(drop=True)

    print("=" * 86)
    print("[2-a] 토폴로지별 역산식 — ABCD 행렬 유도")
    print("=" * 86)
    print("""
  무손실 2포트 정합망 M = [[A,B],[C,D]] 에서  Z_in = (A·Z_L + B)/(C·Z_L + D).
  정합 상태 Z_in = Z0 를 대입하면 부하 임피던스가 유일하게 결정된다:

        Z_L = (Z0·D − B) / (A − Z0·C)          ... (★)

  구성요소:  직렬 Z → [[1,Z],[0,1]] ,  병렬 Y → [[1,0],[Y,1]]
  (이하 모든 임피던스는 Z0 로 정규화한 무차원량, Z0 = 1)
""")
    print("  L형  (병렬 C_sh → 직렬 [고정 L + 가변 C_se]):")
    print("      M = [[1,0],[jb,1]]·[[1,jx],[0,1]] = [[1, jx],[jb, 1+j²bx]]")
    print("      (★) 대입 → 해석해:")
    print("        R/Z0 = 1/(1 + b²)                    ← 병렬 커패시터만으로 결정")
    print("        X/Z0 = b/(1 + b²) − x_se             ← 두 소자 모두 관여")
    print("      b = ω·C_sh·Z0 ,  x_se = (ω·L − 1/(ω·C_se))/Z0")
    print()
    print("  Π형  (병렬 C1 → 직렬 고정 L → 병렬 C2):")
    print("      M = [[1,0],[jb1,1]]·[[1,jx],[0,1]]·[[1,0],[jb2,1]]")
    print("      (★) 로 Z_L 결정. R 이 두 커패시터 모두에 의존 → 분리 불가")
    print()
    print("  T형  (직렬 C1 → 병렬 고정 L → 직렬 C2):")
    print("      M = [[1,jx1],[0,1]]·[[1,0],[jb,1]]·[[1,jx2],[0,1]]")
    print("      (★) 로 Z_L 결정. R 이 두 커패시터 모두에 의존 → 분리 불가")

    print("\n" + "=" * 86)
    print("[2-b] 무엇이 결정되고 무엇이 미결정인가")
    print("=" * 86)
    print("""
  데이터에 없는 것 (가정 금지 → 미지수로 유지):
    ω  RF 주파수                         채널 없음
    Z0 발전기 임피던스                    관례 50 Ω, 데이터에 명시 없음
    고정 소자값 (L 또는 고정 C)           채널 없음
    커패시터 '위치(%) → 정전용량(F)' 변환  채널 없음, 통상 비선형
    정합망 토폴로지                       채널 없음
    두 채널 중 어느 것이 병렬/직렬인지      채널 없음 (Load/Tune 명명 관례는 벤더마다 다름)

  결과:
    절대 임피던스 (R[Ω], X[Ω])            → 결정 불가. 위 6개가 전부 필요하다.
    상대 변화 δlnR, δX (웨이퍼 1번 대비)   → 토폴로지·동작점 가정 하에 산출 가능 (아래)
""")

    print("=" * 86)
    print("[2-c] 선형화 타당성 — 커패시터 변위 크기")
    print("=" * 86)
    for c in (CT, CL):
        cen = d[c] - d.groupby("lot")[c].transform("mean")
        rng = (d[c].max() - d[c].min()) / d[c].mean() * 100
        print(f"  {c:26s} 평균 {d[c].mean():8.4f}  로트내 표준편차 {cen.std():.5f} "
              f"({cen.std()/d[c].mean()*100:.4f} %)  전범위 {rng:.3f} %")
    print("\n  변위가 0.5 % 수준이므로 어떤 매끄러운 역산식도 이 구간에서는 선형과 구별되지 않는다.")
    print("  → 역산은 (원시 커패시터 위치) 의 선형 재매개화가 된다. 이 사실을 3단계 해석에 반영한다.")

    print("\n" + "=" * 86)
    print("[2-d] 야코비안 구조 — 어느 커패시터가 R 을, 어느 것이 X 를 나르는가")
    print("=" * 86)
    print("  (행: lnR, X / 열: C1, C2. 값은 Z0 정규화 무차원 민감도)")
    rows = []
    for r0 in R0_SWEEP:
        J = numeric_jacobian("L", r0, {"s": 1.0})
        rows.append({"토폴로지": "L", "r0": r0, "dlnR/dlnC1": J[0, 0], "dlnR/dlnC2": J[0, 1],
                     "dX/dlnC1": J[1, 0], "dX/dlnC2": J[1, 1]})
    for r0 in (0.05, 0.2, 0.5):
        for b2 in (0.5, 2.0):
            J = numeric_jacobian("pi", r0, {"b2": b2, "x_se": 1.5})
            rows.append({"토폴로지": f"Π(b2={b2})", "r0": r0, "dlnR/dlnC1": J[0, 0],
                         "dlnR/dlnC2": J[0, 1], "dX/dlnC1": J[1, 0], "dX/dlnC2": J[1, 1]})
    for x1 in (-0.8, -2.0):
        for x2 in (-0.6, -1.8):
            J = numeric_jacobian("T", 0.0, {"x1": x1, "b_sh": -0.7, "x2": x2})
            rows.append({"토폴로지": f"T(x1={x1},x2={x2})", "r0": np.nan,
                         "dlnR/dlnC1": J[0, 0], "dlnR/dlnC2": J[0, 1],
                         "dX/dlnC1": J[1, 0], "dX/dlnC2": J[1, 1]})
    jt = pd.DataFrame(rows)
    print(jt.round(4).to_string(index=False))
    print("\n  핵심: L형에서만 ∂lnR/∂lnC2 = 0 (직렬 커패시터는 R 에 전혀 기여하지 않음).")
    print("        Π·T형에서는 두 커패시터가 모두 R 에 기여 → 개별 귀속 불가.")

    print("\n" + "=" * 86)
    print("[2-e] 상대 지표 산출 (웨이퍼 1번 대비) — L형 가정, 두 배정 모두")
    print("=" * 86)
    print("  δlnR = −2b²/(1+b²) · δln C_sh    (b = sqrt(1/r0 − 1), 동작점 r0 소인)")
    print("  δX   = b(1−b²)/(1+b²)² · δln C_sh − s · δln C_se   (s 소인)")
    print("  → δlnR 은 병렬 커패시터 하나의 상수배. δX 는 두 채널의 1-매개변수 선형족.\n")

    new_cols = {}
    for c in (CT, CL):
        ln = np.log(d[c])
        base = ln[d["seq"] == 1].groupby(d["lot"]).mean()
        new_cols[f"dln_{c}"] = (ln - d["lot"].map(base)).values

    idx_cols: dict[str, list[str]] = {}
    for assign, (c_sh, c_se) in {"A(Tune=병렬)": (CT, CL), "B(Load=병렬)": (CL, CT)}.items():
        tag = assign[0]
        for i, r0 in enumerate(R0_SWEEP):
            b = np.sqrt(1.0 / r0 - 1.0)
            name = f"dlnR_{tag}_r{i}"          # 컬럼명에 소수점을 쓰지 않는다 (patsy 수식 제약)
            new_cols[name] = -2 * b**2 / (1 + b**2) * new_cols[f"dln_{c_sh}"]
            idx_cols.setdefault(f"δlnR {assign}", []).append(name)
            for j, s in enumerate(S_SWEEP):
                nx = f"dX_{tag}_r{i}_s{j}"
                # X/Z0 = b/(1+b²) − x_se,  ∂x_se/∂lnC_se = +s  →  ∂X/∂lnC_se = −s
                # (수치 야코비안 dX/dlnC2 = −s 와 일치)
                new_cols[nx] = (b * (1 - b**2) / (1 + b**2) ** 2 * new_cols[f"dln_{c_sh}"]
                                - s * new_cols[f"dln_{c_se}"])
                idx_cols.setdefault(f"δX {assign}", []).append(nx)
    d = pd.concat([d, pd.DataFrame(new_cols, index=d.index)], axis=1)
    SWEEP_LABEL = {f"dlnR_{t}_r{i}": f"배정{t}, r0={r0:g}"
                   for t in "AB" for i, r0 in enumerate(R0_SWEEP)}
    SWEEP_LABEL.update({f"dX_{t}_r{i}_s{j}": f"배정{t}, r0={r0:g}, s={s:g}"
                        for t in "AB" for i, r0 in enumerate(R0_SWEEP)
                        for j, s in enumerate(S_SWEEP)})

    print("  δlnR 지표의 웨이퍼 1번 대비 누적 변화 (10번째 웨이퍼, 로트 평균):")
    for assign in ("A", "B"):
        for i, r0 in enumerate(R0_SWEEP):
            n = f"dlnR_{assign}_r{i}"
            v = d[d["seq"] == 10][n].mean()
            print(f"    배정{assign}, r0={r0:.2f}:  δlnR(10번째) = {v*100:+.4f} %")

    print("\n  δX 지표의 웨이퍼 1번 대비 누적 변화 (10번째 웨이퍼, 로트 평균, Z0 정규화):")
    for assign in ("A", "B"):
        for i, r0 in [(1, R0_SWEEP[1]), (3, R0_SWEEP[3])]:
            vals = [d[d["seq"] == 10][f"dX_{assign}_r{i}_s{j}"].mean()
                    for j in range(len(S_SWEEP))]
            rng = f"{min(vals):+.5f} ~ {max(vals):+.5f}"
            print(f"    배정{assign}, r0={r0:.2f}, s 소인 전체:  δX(10번째) = {rng}")

    print("\n" + "=" * 86)
    print("[2-f] 정합 품질 지표")
    print("=" * 86)
    for tag, pl, pr in (("Platen", "PlatenRFLoadPower", "PlatenRFReflectedPower"),
                        ("Source", "SourceRFLoadPower", "SourceRFReflectedPower")):
        for conv, lab in ((True, "LoadPower=전달전력"), (False, "LoadPower=순방향전력")):
            q = match_quality(d[pr].values, d[pl].values, other_is_delivered=conv)
            print(f"  {tag:7s} [{lab:18s}]  |Γ| = {q.gamma_mag:.4f}  "
                  f"VSWR = {q.vswr:.4f}  P_refl/P_fwd = {q.refl_frac:.5f}")
        g = np.sqrt(np.clip(d[pr] / (d[pl] + d[pr]), 0, 0.999999))
        d = d.assign(**{f"gamma_{tag}": g, f"vswr_{tag}": (1 + g) / (1 - g)})
    print("\n  두 해석 중 어느 쪽인지는 데이터에 없다. 이하 검정은 '전달전력' 해석으로 하되,")
    print("  |Γ| 는 단조변환이므로 상관계수·p값은 해석 선택에 무관하다.")

    print("\n" + "=" * 86)
    print("[3] 검정 — 순번 추세 및 식각 결과 부분상관 (다중비교 보정 포함)")
    print("=" * 86)
    fam = {**idx_cols,
           "정합품질 |Γ| Platen": ["gamma_Platen"], "정합품질 VSWR Platen": ["vswr_Platen"],
           "정합품질 |Γ| Source": ["gamma_Source"], "정합품질 VSWR Source": ["vswr_Source"]}
    m_tests = len(fam) * 2   # 지표군 × 목표 2개
    print(f"  검정 지표군 {len(fam)}개 × 목표 2개 = Bonferroni m = {m_tests}\n")

    out = []
    for name, cols in fam.items():
        st = [within_lot_slope(d, c) for c in cols]
        ps = [s["p"] for s in st]
        for tgt in ("si_etch_mean", "si_etch_cv"):
            rr = [partial_r(d, c, tgt) for c in cols]
            r_v = [x[0] for x in rr]
            p_v = [x[1] for x in rr]
            best = int(np.nanargmin(p_v))
            out.append({
                "지표군": name, "목표": tgt, "n_소인": len(cols),
                "순번p_최소": np.nanmin(ps), "순번p_최대": np.nanmax(ps),
                "부분r_범위": f"{np.nanmin(r_v):+.3f}~{np.nanmax(r_v):+.3f}",
                "부분p_최소": np.nanmin(p_v),
                "보정p_최소": min(np.nanmin(p_v) * m_tests, 1.0),
                "최적소인": cols[best],
                "최적소인_라벨": SWEEP_LABEL.get(cols[best], cols[best]),
            })
    res = pd.DataFrame(out)
    print(res.drop(columns=["최적소인"]).round(5).to_string(index=False))

    print("\n  형상 (대표 소인점):")
    for c in ("dlnR_A_r3", "dlnR_B_r3", "gamma_Platen", "vswr_Platen"):
        if c in d.columns:
            s = within_lot_slope(d, c)
            print(f"    {c:16s} 기울기 {s['slope']:+.6g}/장  "
                  f"95%CI[{s['ci'][0]:+.5g},{s['ci'][1]:+.5g}]  p={s['p']:.3g}  "
                  f"형상: {shape_aic(d, c)}")

    print(f"\n  보정 후 p<0.05 인 (지표군, 목표) 조합: "
          f"{(res['보정p_최소'] < 0.05).sum()} / {len(res)}")
    for _, r in res[res["보정p_최소"] < 0.05].iterrows():
        print(f"    {r['지표군']} → {r['목표']}: 부분r {r['부분r_범위']}, "
              f"보정p {r['보정p_최소']:.5f} (소인점 {SWEEP_LABEL.get(r['최적소인'], r['최적소인'])})")

    res.to_csv(RESULTS / "phase2R_impedance_tests.csv", index=False)
    jt.to_csv(RESULTS / "phase2R_jacobian.csv", index=False)
    keep = ["exp_key", "lot", "seq", "si_etch_mean", "si_etch_cv",
            f"dln_{CT}", f"dln_{CL}", "gamma_Platen", "vswr_Platen",
            "gamma_Source", "vswr_Source"] + sum(idx_cols.values(), [])
    d[keep].to_csv(RESULTS / "phase2R_impedance_indices.csv", index=False)
    print(f"\n저장: {RESULTS/'phase2R_impedance_tests.csv'}, {RESULTS/'phase2R_jacobian.csv'}, "
          f"{RESULTS/'phase2R_impedance_indices.csv'}")


if __name__ == "__main__":
    main()
