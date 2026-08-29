"""Phase 2-0 / 4단계: 포어라인 압력 분해 그림.

(1) 96장 시간순 (로트 경계 표시)
(2) 로트 내 순번 겹쳐 그리기
(3) 식각깊이 대조 + 형상 비교
단위 불가지론 — 축 라벨에 단위를 쓰지 않고 '원시단위'로 표기한다.
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

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGS = ROOT / "reports" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)

for f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Malgun Gothic"):
    if f in {x.name for x in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130

Y = "ForeLinePressure_mean"


def main() -> None:
    df = pd.read_csv(RESULTS / "phase2_0_wafer_summary.csv").sort_values(["lot", "seq"])
    d88 = df[df.has_89pt]
    cmap = plt.get_cmap("tab10")

    # ---------- 그림 1: 시간순 96장 ----------
    fig, ax = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True)
    x = np.arange(1, len(df) + 1)
    ax[0].plot(x, df[Y].values, "-", color="0.65", lw=0.9, zorder=1)
    for i, (lot, s) in enumerate(df.groupby("lot")):
        idx = x[df["lot"].values == lot]
        ax[0].plot(idx, s[Y].values, "o", ms=4.5, color=cmap(i % 10),
                   label=f"Lot {lot} ({s.date.iloc[0][5:]}, {s.cond_type.iloc[0]})")
        ax[0].axvline(idx[0] - 0.5, color="0.8", lw=0.8, ls="--", zorder=0)
    ax[0].set_ylabel("포어라인 압력 [원시단위]")
    ax[0].set_title("포어라인 압력 — 96장 시간순 (점선 = 로트 경계)", fontsize=11)
    ax[0].legend(fontsize=6.5, ncol=5, loc="upper center")
    ax[0].grid(alpha=0.25)

    ax[1].plot(x[df.has_89pt.values], d88["si_etch_mean"].values, "s-",
               color="C3", ms=4, lw=0.9)
    for lot, s in df.groupby("lot"):
        ax[1].axvline(x[df["lot"].values == lot][0] - 0.5, color="0.8", lw=0.8, ls="--")
    ax[1].set_ylabel("평균 Si 식각깊이 [um]")
    ax[1].set_xlabel("처리 순서 (로트순 → 로트 내 순번). 절대 타임스탬프는 데이터에 없음")
    ax[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGS / "phase2_0_timeorder.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- 그림 2: 순번 겹쳐 그리기 ----------
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.0))
    for i, (lot, s) in enumerate(df.groupby("lot")):
        ax[0].plot(s["seq"], s[Y], "o-", ms=4, lw=1.1, color=cmap(i % 10), label=f"Lot {lot}")
        ax[1].plot(s["seq"], s[Y] - s[Y].mean(), "o-", ms=4, lw=1.1, color=cmap(i % 10))
    ax[0].set_xlabel("로트 내 순번"); ax[0].set_ylabel("포어라인 압력 [원시단위]")
    ax[0].set_title("원시값 — 로트별 겹쳐 그리기", fontsize=10)
    ax[0].legend(fontsize=6.5, ncol=2); ax[0].grid(alpha=0.25)

    prof = (df.assign(c=df[Y] - df.groupby("lot")[Y].transform("mean"))
              .groupby("seq")["c"].agg(["mean", "sem"]))
    ax[1].errorbar(prof.index, prof["mean"], yerr=prof["sem"], color="k", lw=2.2,
                   marker="o", ms=6, capsize=3, zorder=5, label="10개 로트 평균±SEM")
    ax[1].axhline(0, color="0.5", lw=0.8)
    ax[1].set_xlabel("로트 내 순번"); ax[1].set_ylabel("로트 평균 대비 편차 [원시단위]")
    ax[1].set_title("로트 중심화 — 톱니 리셋 확인", fontsize=10)
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.25)

    sh = pd.read_csv(RESULTS / "phase2_0_shape_profiles.csv", index_col=0)
    ax[2].plot(sh.index, sh["포어라인_정규화"], "o-", lw=2, ms=6, label="포어라인 압력")
    ax[2].plot(sh.index, sh["si_etch_정규화"], "s-", lw=2, ms=6, label="Si 식각깊이")
    ax[2].set_xlabel("로트 내 순번"); ax[2].set_ylabel("첫 장 대비 정규화 변화")
    ax[2].set_title("형상 비교 — 포화형 vs 선형", fontsize=10)
    ax[2].legend(fontsize=8); ax[2].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIGS / "phase2_0_byseq.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- 그림 3: 교란변수 (온도) ----------
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    for j, ch in enumerate(["Heater2Temp_mean", "Heater3Temp_mean", "Heater4Temp_mean"]):
        p = (df.assign(c=df[ch] - df.groupby("lot")[ch].transform("mean"))
               .groupby("seq")["c"].agg(["mean", "sem"]))
        pf = (df.assign(c=df[Y] - df.groupby("lot")[Y].transform("mean"))
                .groupby("seq")["c"].agg(["mean", "sem"]))
        a = ax[j]
        a.errorbar(p.index, p["mean"], yerr=p["sem"], color="C1", marker="o", ms=5, capsize=3)
        a.set_xlabel("로트 내 순번"); a.set_ylabel(f"{ch[:-5]} 편차", color="C1")
        a.tick_params(axis="y", labelcolor="C1"); a.grid(alpha=0.25)
        b = a.twinx()
        b.errorbar(pf.index, pf["mean"], yerr=pf["sem"], color="C0", marker="s", ms=5,
                   capsize=3, alpha=0.75)
        b.set_ylabel("포어라인 편차", color="C0"); b.tick_params(axis="y", labelcolor="C0")
        a.set_title(f"{ch[:-5]} vs 포어라인", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "phase2_0_temp_confound.png", bbox_inches="tight")
    plt.close(fig)

    print("저장:", *(str(p) for p in sorted(FIGS.glob("phase2_0_*.png"))), sep="\n  ")


if __name__ == "__main__":
    main()
