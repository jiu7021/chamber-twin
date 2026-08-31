#!/usr/bin/env python3
"""OES 분석 그림 — 로트 내 순번에 따른 스펙트럼 변화.

로트 고정효과를 뺀 순번 기울기를 파장마다 계산한다. 로트 더미가 모든 파장에
공통이므로 로트별 중심화 후 한 번에 벡터화해 푼다 (파장마다 OLS 를 돌릴 필요 없음).

    slope_j = (s·y_j) / (s·s),   s, y 는 각각 로트별 평균을 뺀 값
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

for f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Malgun Gothic"):
    if f in {x.name for x in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130

ROOT = Path(__file__).resolve().parent.parent


def lot_centered(v: np.ndarray, lot: np.ndarray) -> np.ndarray:
    """로트별 평균을 뺀다 (C(lot) 고정효과 제거와 동치)."""
    out = np.array(v, dtype=float, copy=True)
    for L in np.unique(lot):
        k = lot == L
        out[k] -= out[k].mean(axis=0)
    return out


def main() -> None:
    z = np.load(ROOT / "reports" / "oes_spectra.npz", allow_pickle=True)
    wl, keys, spec = z["wavelengths"], z["exp_key"], z["mean_spec"]
    lot = np.array([k[:10] for k in keys])
    seq = np.array([int(k[-2:]) for k in keys], dtype=float)

    s = lot_centered(seq, lot)
    denom = float(s @ s)
    slope_raw = (s @ lot_centered(spec, lot)) / denom
    norm = spec / spec.sum(axis=1, keepdims=True)
    slope_norm = (s @ lot_centered(norm, lot)) / denom

    fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    ax[0].plot(wl, spec.mean(axis=0), lw=0.7, color="0.25")
    ax[0].set_ylabel("평균 발광강도")
    ax[0].set_title("웨이퍼 96장 평균 OES 스펙트럼 (50~600 s 구간 평균)")

    ax[1].axhline(0, color="0.7", lw=0.8)
    ax[1].plot(wl, slope_raw, lw=0.7, color="#C0392B")
    ax[1].set_ylabel("순번 기울기\n(원시 강도)")
    ax[1].set_title("로트 내 순번 1장당 변화 — 원시 강도: F I 발광선이 급감한다")

    ax[2].axhline(0, color="0.7", lw=0.8)
    ax[2].plot(wl, slope_norm, lw=0.7, color="#1F6FB2")
    ax[2].set_ylabel("순번 기울기\n(총발광 정규화)")
    ax[2].set_xlabel("파장 [nm]")
    ax[2].set_title("총발광 정규화 후 — 공통 감광을 빼도 F I 감소는 남는다 (뷰포트 흐림만이 아니다)")
    # F I 발광선 표시. 이 분광기는 파장 교정이 -1.21 nm 어긋나 있다
    # (5개 선의 오프셋 평균 -1.21, 표준편차 0.04 nm).
    OFFSET = -1.21
    for lit in (685.6, 690.2, 703.7, 712.8, 739.9):
        for a in ax:
            a.axvline(lit + OFFSET, color="#F2A33C", lw=0.8, ls="--", alpha=0.7, zorder=0)
    ax[0].text(745, ax[0].get_ylim()[1]*0.75, "F I (원자 불소)", color="#B8781F", fontsize=9)

    for a in ax:
        a.grid(alpha=0.25)
    fig.tight_layout()
    out = ROOT / "reports" / "oes_sequence_slope.png"
    fig.savefig(out)
    print(f"저장: {out}")

    # 정규화 기울기 상위/하위 대역
    o = np.argsort(slope_norm)
    print("\n정규화 기준 가장 크게 감소한 파장 8개:")
    for j in o[:8]:
        print(f"  {wl[j]:8.2f} nm   {slope_norm[j]:+.3e}")
    print("정규화 기준 가장 크게 증가한 파장 8개:")
    for j in o[::-1][:8]:
        print(f"  {wl[j]:8.2f} nm   {slope_norm[j]:+.3e}")


if __name__ == "__main__":
    main()
