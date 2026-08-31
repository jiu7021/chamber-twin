#!/usr/bin/env python3
"""Bosch 위상별 OES 분석.

섞어 평균한 Phase 6 분석과 같은 설계를 식각 위상과 패시베이션 위상에 따로 적용한다.
추가로 두 위상의 순번 기울기 부호가 갈리는 파장을 찾는다 — 섞어 평균하면 상쇄되어
안 보이던 것이다.

로트 더미가 모든 파장에 공통이므로 기울기는 로트별 중심화 후 벡터화해 한 번에 푼다.
흡수율 검정만 파장별 OLS 가 필요하다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parent.parent
ALPHA = 0.05
OFFSET = -1.21                                   # 분광기 파장 교정 오프셋 [nm]
F_LINES = (685.6, 690.2, 703.7, 712.8, 739.9)    # F I (문헌값)


def lot_center(v: np.ndarray, lot: np.ndarray) -> np.ndarray:
    out = np.array(v, dtype=float, copy=True)
    for L in np.unique(lot):
        k = lot == L
        out[k] -= out[k].mean(axis=0)
    return out


def slope_and_p(X: np.ndarray, seq: np.ndarray, lot: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """로트 고정효과 제거 후 순번 기울기와 그 p 값 (파장 전체 벡터화)."""
    s = lot_center(seq, lot)
    Y = lot_center(X, lot)
    denom = float(s @ s)
    b = (s @ Y) / denom
    resid = Y - np.outer(s, b)
    dof = len(s) - np.unique(lot).size - 1
    se = np.sqrt((resid**2).sum(axis=0) / dof / denom)
    from scipy import stats
    p = 2 * stats.t.sf(np.abs(b / se), dof)
    return b, p


def main() -> None:
    z = np.load(ROOT / "reports" / "oes_spectra_phase.npz", allow_pickle=True)
    wl, keys = z["wavelengths"], z["exp_key"]
    lot = np.array([k[:10] for k in keys])
    seq = np.array([int(k[-2:]) for k in keys], dtype=float)

    raw = pd.read_csv(ROOT / "data" / "Si_Oxide_etch_89_points.csv")
    dep = raw.groupby("experiment_key")["si_etch"].mean()
    M = pd.DataFrame({"exp_key": keys, "lot": lot, "seq": seq}).join(dep, on="exp_key")
    ok = M.si_etch.notna().values
    Mo = M.loc[ok].reset_index(drop=True)
    base = smf.ols("si_etch ~ C(lot) + seq", data=Mo).fit()
    b0 = base.params["seq"]
    bonf = ALPHA / wl.size
    print(f"기준 모델 seq 계수 {b0:+.6f} (p = {base.pvalues['seq']:.3e}), "
          f"Bonferroni 임계 p < {bonf:.3e}\n")

    out = {}
    for phase, key in (("식각", "mean_etch"), ("패시베이션", "mean_pass")):
        X = z[key]
        Xn = X / X.sum(axis=1, keepdims=True)
        for fam, mat in (("A 원시", X), ("B 정규화", Xn)):
            b, p = slope_and_p(mat[ok], seq[ok], lot[ok])
            out[(phase, fam)] = (b, p)
            print(f"[{phase} · {fam}] 유의 {int((p < bonf).sum())} / {wl.size}, "
                  f"최소 p = {p.min():.3e} @ {wl[int(np.argmin(p))]:.2f} nm")

    print("\n[F I 발광선의 위상별 순번 변화율 — 10장당 %]")
    print(f"{'F I 문헌':>10} {'식각':>10} {'패시베이션':>12} {'섞어평균 대비':>14}")
    for lit in F_LINES:
        j = int(np.argmin(np.abs(wl - (lit + OFFSET))))
        re_, rp = [], []
        for key in ("mean_etch", "mean_pass"):
            X = z[key]
            b, _ = slope_and_p(X[ok], seq[ok], lot[ok])
            (re_ if key == "mean_etch" else rp).append(b[j] / X[ok][:, j].mean() * 1000)
        print(f"{lit:10.1f} {re_[0]:+9.2f} % {rp[0]:+11.2f} %")

    print("\n[두 위상의 부호가 갈리는 파장 — 섞어 평균하면 상쇄된다]")
    be, pe = out[("식각", "B 정규화")]
    bp, pp = out[("패시베이션", "B 정규화")]
    both = (pe < bonf) & (pp < bonf)
    opp = both & (np.sign(be) != np.sign(bp))
    print(f"  두 위상 모두 유의: {int(both.sum())}개, 그중 부호 반대: {int(opp.sum())}개")
    if opp.sum():
        idx = np.where(opp)[0]
        o = idx[np.argsort(-np.abs(be[idx] - bp[idx]))][:10]
        print(f"  {'파장':>9} {'식각':>12} {'패시베이션':>13}")
        for j in o:
            print(f"  {wl[j]:9.2f} {be[j]:+12.3e} {bp[j]:+13.3e}")

    print("\n[식각깊이 순번계수 흡수율 — 위상별 최댓값]")
    for phase, key in (("식각", "mean_etch"), ("패시베이션", "mean_pass")):
        X = z[key][ok]
        best = (0.0, -1)
        for j in range(0, wl.size):
            d = Mo.copy(); d["v"] = X[:, j]
            if d["v"].std() < 1e-12:
                continue
            r = smf.ols("si_etch ~ C(lot) + seq + v", data=d).fit()
            a = (b0 - r.params["seq"]) / b0 * 100
            if abs(a) > abs(best[0]):
                best = (a, j)
        a, j = best
        d = Mo.copy(); d["v"] = X[:, j]
        r = smf.ols("si_etch ~ C(lot) + seq + v", data=d).fit()
        print(f"  {phase:6}: {a:+.2f} % @ {wl[j]:.2f} nm  "
              f"→ 투입 후 seq p = {r.pvalues['seq']:.3e}")


if __name__ == "__main__":
    main()
