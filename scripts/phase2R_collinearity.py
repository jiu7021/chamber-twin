"""Phase 2R / 1단계: RF 매칭 계통 채널의 공선성 검진.

목적
  (a) RF 관련 채널 전체의 상관행렬과 VIF
  (b) PlatenRFTuningCapacitor 단독 투입 시 순번 계수가 −145 % 로 반전된 원인 규명
      — 억제변수(suppressor)인지 공선성(collinearity)인지 판별
  (c) 주성분분석으로 RF 채널군의 실질 자유도 확인
  (d) 판정: 실질 자유도 1 → 종료, 2 이상 → 2단계

모든 분석은 로트 고정효과를 통제한 맥락에서 수행한다(하위 모형이 전부 C(lot)+seq 이므로).
단위 불가지론 — 채널은 원시 단위. 표준화(z-score)는 무차원이므로 단위 가정을 도입하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.outliers_influence import variance_inflation_factor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_0_extract import etch_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# 31개 공통 채널 중 RF 계통 (분산 0인 SourceRF2LoadPower, SourceRF2ReflectedPower,
# SourceRF2TuningCapacitor, SourceRFTuningCapacitor 는 제외)
RF_CH = [
    "PlatenRFTuningCapacitor", "PlatenRFLoadCapacitor", "PlatenRFPeakToPeak",
    "PlatenRFLoadPower", "PlatenRFReflectedPower", "PlatenDcBias",
    "SourceRFPeakToPeak", "SourceRFLoadPower", "SourceRFReflectedPower",
    "SourceRF2PeakToPeak", "moriInnerCurrent",
]


def center_by_lot(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """로트 평균을 제거한다 (모든 하위 모형이 C(lot)을 포함하므로)."""
    out = df[cols].copy()
    for c in cols:
        out[c] = df[c] - df.groupby("lot")[c].transform("mean")
    return out


def eff_dof(eigvals: np.ndarray) -> dict:
    """고유값 분포로부터 실질 자유도 지표들을 계산한다.

    Args:
        eigvals: 상관행렬 고유값 (내림차순)

    Returns:
        참여비(participation ratio), 엔트로피 기반 유효랭크, 90/95% 분산 도달 성분 수
    """
    lam = eigvals[eigvals > 1e-12]
    p = lam / lam.sum()
    return {
        "participation_ratio": float(lam.sum() ** 2 / np.sum(lam ** 2)),
        "effective_rank_entropy": float(np.exp(-np.sum(p * np.log(p)))),
        "n_pc_90": int(np.searchsorted(np.cumsum(p), 0.90) + 1),
        "n_pc_95": int(np.searchsorted(np.cumsum(p), 0.95) + 1),
        "pc1_var_frac": float(p[0]),
        "kaiser_n": int((lam > 1.0).sum()),
    }


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_channels_31.csv").merge(
        etch_metrics(), on="exp_key", how="left")
    d = df[df["si_etch_mean"].notna()].copy()
    rf = [c for c in RF_CH if c in d.columns and d[c].std() > 0]

    print("=" * 86)
    print("[1-a] RF 계통 채널 상관행렬 (로트 중심화 후, n = %d)" % len(d))
    print("=" * 86)
    CEN = center_by_lot(d, rf + ["si_etch_mean", "si_etch_cv"])
    CEN["seq"] = d["seq"].values - d.groupby("lot")["seq"].transform("mean").values
    corr = CEN[rf].corr()
    short = {c: c.replace("Platen", "P.").replace("Source", "S.")
              .replace("Capacitor", "Cap").replace("PeakToPeak", "Vpp")
              .replace("ReflectedPower", "Prefl").replace("LoadPower", "Pload")
              .replace("moriInnerCurrent", "moriI") for c in rf}
    cs = corr.rename(index=short, columns=short)
    print(cs.round(3).to_string())

    print("\n  |r| > 0.7 인 채널쌍:")
    hi = [(a, b, corr.loc[a, b]) for i, a in enumerate(rf) for b in rf[i + 1:]
          if abs(corr.loc[a, b]) > 0.7]
    for a, b, r in sorted(hi, key=lambda t: -abs(t[2])):
        print(f"    {short[a]:12s} ~ {short[b]:12s}  r = {r:+.4f}")
    if not hi:
        print("    없음")

    print("\n  각 RF 채널의 순번(seq)과의 상관 (로트 중심화):")
    for c in rf:
        r = np.corrcoef(CEN[c], CEN["seq"])[0, 1]
        print(f"    {c:26s} r(seq) = {r:+.4f}   R²(seq) = {r**2:.4f}")

    print("\n" + "=" * 86)
    print("[1-b] VIF — 회귀 설계행렬 맥락 (C(lot) + seq + RF채널 전체)")
    print("=" * 86)
    X = pd.get_dummies(d[["lot"]].astype(str), drop_first=True).astype(float)
    X["seq"] = d["seq"].values
    for c in rf:
        X[c] = d[c].values
    Xs = (X - X.mean()) / X.std().replace(0, 1)
    Xs.insert(0, "const", 1.0)
    vif = {}
    for i, c in enumerate(Xs.columns):
        if c == "const":
            continue
        vif[c] = variance_inflation_factor(Xs.values, i)
    vt = pd.Series(vif).sort_values(ascending=False)
    print("  (10 초과 = 심각한 공선성, 5~10 = 주의)")
    for k, v in vt.items():
        if k.startswith("lot_"):
            continue
        flag = "  ← 심각" if v > 10 else ("  ← 주의" if v > 5 else "")
        print(f"    {k:26s} VIF = {v:9.2f}{flag}")
    print(f"    (로트 더미 VIF 최대 = {max(v for k, v in vif.items() if k.startswith('lot_')):.2f})")

    print("\n" + "=" * 86)
    print("[1-c] 순번 계수 반전의 원인 — 억제변수 vs 공선성")
    print("=" * 86)
    for tgt in ("si_etch_cv", "si_etch_mean"):
        base = smf.ols(f"{tgt} ~ C(lot) + seq", data=d).fit()
        print(f"\n  대상: {tgt}")
        print(f"    기준모형  seq 계수 = {base.params['seq']:+.6g}  "
              f"SE = {base.bse['seq']:.6g}  t = {base.tvalues['seq']:+.2f}  "
              f"p = {base.pvalues['seq']:.3g}")
        for ch in ("PlatenRFTuningCapacitor", "PlatenRFLoadCapacitor",
                   "PlatenRFPeakToPeak", "moriInnerCurrent"):
            m = smf.ols(f"{tgt} ~ C(lot) + seq + {ch}", data=d).fit()
            # seq 의 VIF: seq 를 나머지 설명변수로 회귀한 R²
            aux = smf.ols(f"seq ~ C(lot) + {ch}", data=d).fit()
            vif_seq = 1.0 / (1.0 - aux.rsquared) if aux.rsquared < 1 else np.inf
            dchg = (m.params["seq"] - base.params["seq"]) / abs(base.params["seq"]) * 100
            se_ratio = m.bse["seq"] / base.bse["seq"]
            print(f"    +{ch:24s} seq = {m.params['seq']:+.6g} ({dchg:+7.1f}%)  "
                  f"SE = {m.bse['seq']:.6g} (×{se_ratio:.2f})  "
                  f"VIF(seq) = {vif_seq:6.2f}  p_seq = {m.pvalues['seq']:.3g}")

    print("\n  판별 근거:")
    aux = smf.ols("seq ~ C(lot) + PlatenRFTuningCapacitor", data=d).fit()
    print(f"    seq ~ C(lot) + PlatenRFTuningCapacitor 의 R² = {aux.rsquared:.4f}")
    print(f"    → seq 의 VIF = 1/(1−R²) = {1/(1-aux.rsquared):.2f}")
    aux2 = smf.ols("PlatenRFTuningCapacitor ~ C(lot) + seq", data=d).fit()
    print(f"    PlatenRFTuningCapacitor ~ C(lot) + seq 의 R² = {aux2.rsquared:.4f} "
          f"(seq p = {aux2.pvalues['seq']:.3g})")
    r_cv = np.corrcoef(CEN["PlatenRFTuningCapacitor"], CEN["si_etch_cv"])[0, 1]
    r_seq = np.corrcoef(CEN["PlatenRFTuningCapacitor"], CEN["seq"])[0, 1]
    print(f"    로트 중심화 상관:  채널~si_etch_cv r = {r_cv:+.4f},  채널~seq r = {r_seq:+.4f}")

    print("\n" + "=" * 86)
    print("[1-d] 주성분분석 — RF 채널군의 실질 자유도")
    print("=" * 86)
    Z = CEN[rf]
    Z = (Z - Z.mean()) / Z.std()
    R = np.corrcoef(Z.values, rowvar=False)
    w, V = np.linalg.eigh(R)
    idx = np.argsort(w)[::-1]
    w, V = w[idx], V[:, idx]
    frac = w / w.sum()
    print(f"  대상 채널 {len(rf)}개, 표본 {len(Z)}장 (로트 중심화 후 표준화)")
    print("\n   PC   고유값   분산비율   누적")
    for i in range(len(w)):
        print(f"   {i+1:2d}  {w[i]:8.4f}  {frac[i]*100:7.2f}%  {frac[:i+1].sum()*100:7.2f}%")
    e = eff_dof(w)
    print("\n  실질 자유도 지표:")
    print(f"    PC1 이 설명하는 분산      = {e['pc1_var_frac']*100:.2f} %")
    print(f"    90 % 분산 도달 성분 수    = {e['n_pc_90']}")
    print(f"    95 % 분산 도달 성분 수    = {e['n_pc_95']}")
    print(f"    Kaiser 기준 (고유값 > 1)  = {e['kaiser_n']}")
    print(f"    참여비 (participation ratio) = {e['participation_ratio']:.3f}")
    print(f"    엔트로피 기반 유효랭크       = {e['effective_rank_entropy']:.3f}")

    print("\n  PC1~PC3 적재량 (|적재| 내림차순):")
    for k in range(min(3, len(w))):
        ld = pd.Series(V[:, k], index=rf).reindex(
            pd.Series(V[:, k], index=rf).abs().sort_values(ascending=False).index)
        top = [f"{short[i]}={v:+.2f}" for i, v in ld.head(6).items()]
        print(f"    PC{k+1} ({frac[k]*100:5.1f}%): " + ", ".join(top))

    pcs = Z.values @ V
    print("\n  각 PC의 순번 상관 및 식각 결과 상관 (로트 중심화):")
    for k in range(min(4, len(w))):
        rs = np.corrcoef(pcs[:, k], CEN["seq"])[0, 1]
        rm = np.corrcoef(pcs[:, k], CEN["si_etch_mean"])[0, 1]
        rc = np.corrcoef(pcs[:, k], CEN["si_etch_cv"])[0, 1]
        print(f"    PC{k+1}: r(seq) = {rs:+.4f}   r(si_etch_mean) = {rm:+.4f}   "
              f"r(si_etch_cv) = {rc:+.4f}")

    out = pd.DataFrame(V, index=rf, columns=[f"PC{i+1}" for i in range(len(w))])
    out.loc["_eigenvalue"] = w
    out.loc["_var_frac"] = frac
    out.to_csv(RESULTS / "phase2R_pca_loadings.csv")
    corr.to_csv(RESULTS / "phase2R_rf_corr.csv")
    pd.Series(vif).to_csv(RESULTS / "phase2R_vif.csv", header=["VIF"])
    print(f"\n저장: {RESULTS/'phase2R_pca_loadings.csv'}, {RESULTS/'phase2R_rf_corr.csv'}, "
          f"{RESULTS/'phase2R_vif.csv'}")


if __name__ == "__main__":
    main()
