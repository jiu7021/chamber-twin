"""Phase 2 (축소판) 그림: 순번 효과 프로파일과 31채널 전수 음성 결과.

이 두 그림이 Phase 3(물리 기반 시뮬레이터)의 근거다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_0_extract import etch_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGS = ROOT / "reports" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)

for f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic"):
    if f in {x.name for x in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130


def prof(d, y):
    x = d[["lot", "seq", y]].dropna().copy()
    x["c"] = x[y] - x.groupby("lot")[y].transform("mean")
    p = x.groupby("seq")["c"].agg(["mean", "sem"])
    p["mean"] -= p["mean"].iloc[0]
    return p


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_channels_31.csv").merge(
        etch_metrics(), on="exp_key", how="left")
    d = df[df.si_etch_mean.notna()]
    scan = pd.read_csv(RESULTS / "phase2_channel_scan.csv")

    # ---------- 그림 1: 순번 효과 ----------
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9))
    cmap = plt.get_cmap("tab10")
    for i, (lot, s) in enumerate(d.groupby("lot")):
        ax[0].plot(s["seq"], s["si_etch_mean"], "o-", ms=3.5, lw=1,
                   color=cmap(i % 10), alpha=0.8, label=f"Lot {lot}")
    ax[0].set_xlabel("로트 내 순번"); ax[0].set_ylabel("평균 Si 식각깊이 [um]")
    ax[0].set_title("식각깊이 — 로트별 원시값", fontsize=10)
    ax[0].legend(fontsize=6, ncol=2); ax[0].grid(alpha=0.25)

    for j, (y, lab, col) in enumerate((("si_etch_mean", "식각깊이 [um]", "C3"),
                                       ("si_etch_cv", "면내 변동계수 [-]", "C0"))):
        p = prof(d, y)
        a = ax[1] if j == 0 else ax[1].twinx()
        a.errorbar(p.index, p["mean"], yerr=p["sem"], marker="os"[j], ms=5.5,
                   lw=2, capsize=3, color=col, label=lab)
        a.set_ylabel(f"{lab} 편차", color=col)
        a.tick_params(axis="y", labelcolor=col)
    ax[1].set_xlabel("로트 내 순번"); ax[1].grid(alpha=0.25)
    ax[1].set_title("순번 효과 (로트 중심화, ±SEM)\n깊이 −2.72% / 균일도 −3.54% (10장)", fontsize=9.5)

    for y, lab, mk in (("si_etch_mean", "식각깊이 (선형)", "o"),
                       ("si_etch_cv", "변동계수 (포화형)", "s")):
        p = prof(d, y)
        ax[2].plot(p.index, p["mean"] / p["mean"].abs().max(), mk + "-", lw=2, ms=5.5, label=lab)
    ax[2].set_xlabel("로트 내 순번"); ax[2].set_ylabel("첫 장 대비 정규화")
    ax[2].set_title("형상 비교 — 3장까지 진행률\n깊이 10.1% vs 변동계수 56.1%", fontsize=9.5)
    ax[2].legend(fontsize=8); ax[2].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGS / "phase2_seq_effect.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- 그림 2: 31채널 전수 스캔 ----------
    s = scan.dropna(subset=["부분r_depth"]).sort_values("부분r_depth")
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 6.2))
    ypos = np.arange(len(s))
    sig = s["bonf_depth"] < 0.05
    ax[0].barh(ypos, s["부분r_depth"], color=np.where(sig, "C3", "0.72"), height=0.7)
    ax[0].set_yticks(ypos); ax[0].set_yticklabels(s["채널"], fontsize=7.5)
    ax[0].axvline(0, color="k", lw=0.8)
    ax[0].set_xlabel("부분상관 r (로트 + 순번 통제)")
    ax[0].set_title("si_etch_mean 과의 부분상관\n빨강 = Bonferroni 보정 후 p<0.05 (25개 중 2개)",
                    fontsize=10)
    ax[0].grid(alpha=0.25, axis="x"); ax[0].set_xlim(-0.7, 0.7)

    ax[1].barh(ypos, -np.log10(s["bonf_depth"].clip(lower=1e-6)),
               color=np.where(sig, "C3", "0.72"), height=0.7)
    ax[1].axvline(-np.log10(0.05), color="C0", ls="--", lw=1.4, label="보정 p = 0.05")
    ax[1].set_yticks(ypos); ax[1].set_yticklabels([])
    ax[1].set_xlabel("−log10 (Bonferroni 보정 p)")
    ax[1].set_title("유의성 — 대부분 보정 후 p = 1.0", fontsize=10)
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.25, axis="x")
    fig.suptitle("측정된 31개 설비 채널 중 순번 효과를 설명하는 변수가 없다 — Phase 3의 근거",
                 fontsize=11.5, y=1.00)
    fig.tight_layout()
    fig.savefig(FIGS / "phase2_channel_scan.png", bbox_inches="tight")
    plt.close(fig)

    print("저장:", *(str(p) for p in sorted(FIGS.glob("phase2_*.png"))), sep="\n  ")


if __name__ == "__main__":
    main()
