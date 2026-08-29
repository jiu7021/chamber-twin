"""Phase 3 그림: 실측 대조 사이클과 복원된 배기속도 궤적."""
from __future__ import annotations
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np, pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]
FIGS = ROOT / "reports" / "figs"; FIGS.mkdir(parents=True, exist_ok=True)
for f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic"):
    if f in {x.name for x in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = f; break
plt.rcParams["axes.unicode_minus"] = False; plt.rcParams["figure.dpi"] = 130

c = pd.read_csv(ROOT / "results" / "phase3_example_cycle.csv")
v = pd.read_csv(ROOT / "results" / "phase3_validation.csv")

fig, ax = plt.subplots(1, 3, figsize=(13.5, 4.0))
ax[0].plot(c.t, c.p, "ko-", ms=4, lw=1.6, label="실측 (앙상블 98주기)")
ax[0].plot(c.t, c.predA, "--", lw=1.8, color="C3", label="모델 A 고정 S")
ax[0].plot(c.t, c.predB, "-", lw=1.8, color="C0", label="모델 B APC 서보")
ax[0].set_xlabel("사이클 내 상대시각 [s]"); ax[0].set_ylabel("챔버 압력 [원시단위]")
ax[0].set_title("실측 대조 — Day_2024_07_05_Wafer_02", fontsize=10)
ax[0].legend(fontsize=8); ax[0].grid(alpha=0.25)

ax[1].axhline(0, color="0.5", lw=0.8)
ax[1].plot(c.t, c.predA - c.p, "--o", ms=3.5, lw=1.4, color="C3", label="모델 A 잔차")
ax[1].plot(c.t, c.predB - c.p, "-s", ms=3.5, lw=1.4, color="C0", label="모델 B 잔차")
ax[1].set_xlabel("사이클 내 상대시각 [s]"); ax[1].set_ylabel("잔차 (모델 − 실측)")
ax[1].set_title("잔차 — 이것이 산출물이다\n모델 A 자기상관 +0.83 / 모델 B +0.22", fontsize=9.5)
ax[1].legend(fontsize=8); ax[1].grid(alpha=0.25)

ax[2].plot(c.t, c.s_traj, "-", lw=2, color="C2")
ax[2].fill_between(c.t, 0, c.s_traj, alpha=0.15, color="C2")
ax[2].set_xlabel("사이클 내 상대시각 [s]"); ax[2].set_ylabel("복원된 S_eff [원시단위]")
ax[2].set_title("실측에 없는 변수의 복원\n한 주기에 배기속도가 %.1f배 움직인다"
                % (v.B_S_max / v.B_S_min.clip(lower=1e-9)).median(), fontsize=9.5)
ax[2].grid(alpha=0.25)
fig.tight_layout(); fig.savefig(FIGS / "phase3_validation.png", bbox_inches="tight")
print("저장:", FIGS / "phase3_validation.png")
