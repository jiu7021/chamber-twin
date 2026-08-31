#!/usr/bin/env python3
"""OES 스펙트럼이 식각깊이의 로트 내 순번 효과를 설명하는가.

Phase 2 에서 기록된 31개 공정 채널을 전수 조사해 순번 효과를 설명하는 채널이
없음을 확인했다. OES 는 그때 범위에서 제외했던 유일한 데이터다.

설계는 결과를 보기 전에 고정한다.

  지표군 A : 파장별 원시 강도 I_j                (3648개)
  지표군 B : 총발광 정규화 강도 I_j / ΣI          (3648개)
             — 뷰포트 퇴적으로 투과율이 떨어지면 모든 파장이 같이 어두워진다.
               그건 플라즈마 화학 변화가 아니라 광학 손실이므로 비율로 상쇄한다.
  지표군 C : 전 스펙트럼 PCA 주성분              (누적 95 % 까지)

  검정 1 : 지표 ~ C(lot) + seq          → seq 계수의 p. Bonferroni 로 보정.
  검정 2 : depth ~ C(lot) + seq + 지표  → seq 계수 흡수율.
           흡수율 = (기준 seq 계수 − 지표 투입 후 seq 계수) / 기준 seq 계수 × 100 %

금지: 유의하게 나오는 파장을 골라 사후에 이야기를 만드는 것, 다중비교 보정 생략,
      인과 표현. 음성 결과는 음성으로 보고한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parent.parent
NPZ = ROOT / "reports" / "oes_spectra.npz"
DEPTH_CSV = ROOT / "data" / "Si_Oxide_etch_89_points.csv"
ALPHA = 0.05


def load() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    z = np.load(NPZ, allow_pickle=True)
    wl, keys, spec = z["wavelengths"], z["exp_key"], z["mean_spec"]

    # Phase 2 와 동일한 반응변수: 웨이퍼당 89점의 si_etch 평균과 면내 변동계수
    raw = pd.read_csv(DEPTH_CSV)
    g = raw.groupby("experiment_key")["si_etch"]
    dep = pd.DataFrame({"si_etch_mean": g.mean(), "si_etch_cv": g.std() / g.mean()})

    meta = pd.DataFrame({"exp_key": keys})
    meta["lot"] = meta.exp_key.str[:10]
    meta["seq"] = meta.exp_key.str[-2:].astype(int)
    meta = meta.join(dep, on="exp_key")
    return meta, spec, wl


def scan(meta: pd.DataFrame, mat: np.ndarray, wl: np.ndarray, name: str,
         y: str = "si_etch_mean") -> dict:
    """검정 1·2 를 지표 열 전체에 대해 수행한다."""
    ok = meta[y].notna().values
    m = meta.loc[ok].reset_index(drop=True)
    X = mat[ok]
    n_test = X.shape[1]
    bonf = ALPHA / n_test

    base = smf.ols(f"{y} ~ C(lot) + seq", data=m).fit()
    b0 = base.params["seq"]

    p_seq = np.full(n_test, np.nan)
    absorb = np.full(n_test, np.nan)
    for j in range(n_test):
        d = m.copy()
        d["v"] = X[:, j]
        if np.std(d["v"]) < 1e-12:
            continue
        r1 = smf.ols("v ~ C(lot) + seq", data=d).fit()
        p_seq[j] = r1.pvalues["seq"]
        r2 = smf.ols(f"{y} ~ C(lot) + seq + v", data=d).fit()
        absorb[j] = (b0 - r2.params["seq"]) / b0 * 100.0

    n_sig = int(np.nansum(p_seq < bonf))
    jbest = int(np.nanargmin(p_seq))
    jabs = int(np.nanargmax(np.abs(absorb)))
    print(f"\n[{name}]  지표 {n_test}개, Bonferroni 임계 p < {bonf:.3e}")
    print(f"  기준 모델 seq 계수 b0 = {b0:.6f}  (p = {base.pvalues['seq']:.3e})")
    print(f"  검정1 — 순번 의존성이 보정 후에도 유의한 지표: {n_sig} / {n_test}")
    print(f"          최소 p = {np.nanmin(p_seq):.3e} @ {wl[jbest]:.2f} nm"
          f"  ({'유의' if np.nanmin(p_seq) < bonf else '유의하지 않음'})")
    print(f"  검정2 — 최대 흡수율 = {absorb[jabs]:+.2f} % @ {wl[jabs]:.2f} nm")
    return {"p_seq": p_seq, "absorb": absorb, "b0": b0, "bonf": bonf, "n_sig": n_sig}


def main() -> None:
    meta, spec, wl = load()
    print(f"웨이퍼 {len(meta)}장, 그중 식각깊이 있는 것 {int(meta.si_etch_mean.notna().sum())}장")
    print(f"로트 {meta.lot.nunique()}개, 파장 {wl.size}개 ({wl.min():.1f}~{wl.max():.1f} nm)")

    res = {}
    res["A 원시강도"] = scan(meta, spec, wl, "A 원시 강도")

    tot = spec.sum(axis=1, keepdims=True)
    res["B 정규화"] = scan(meta, spec / tot, wl, "B 총발광 정규화 강도")

    # C: PCA (전역 중심화, 누적 95 %)
    Xc = spec - spec.mean(axis=0)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    var = S**2 / np.sum(S**2)
    k = int(np.searchsorted(np.cumsum(var), 0.95) + 1)
    pcs = U[:, :k] * S[:k]
    print(f"\nPCA: 누적 95 % 까지 주성분 {k}개 (설명분산 {np.cumsum(var)[k-1]*100:.1f} %)")
    res["C PCA"] = scan(meta, pcs, np.arange(1, k + 1, dtype=float), "C PCA 주성분")

    np.savez_compressed(ROOT / "reports" / "oes_scan.npz",
                        wavelengths=wl,
                        **{f"{k2.split()[0]}_{m2}": v[m2]
                           for k2, v in res.items() for m2 in ("p_seq", "absorb")})
    print("\n저장: reports/oes_scan.npz")


if __name__ == "__main__":
    main()
