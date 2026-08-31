#!/usr/bin/env python3
"""README 용 핵심 그림 2장.

  A. 실제 PLC(OpenPLC) 폐루프에서 누설 외란을 주입해 측정한 압력과 밸브 각도.
     시뮬레이션이 아니라 실제 PLC 가 제어하는 계통의 Modbus 측정값이다.
     실행하려면 트윈(:5020)과 OpenPLC 슬레이브(:5502)가 떠 있어야 한다.
  B. 공개 실측 데이터의 로트별 식각깊이 — 로트마다 리셋되는 톱니.

    python3 scripts/readme_figures.py [--skip-hil]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "img"

for f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Malgun Gothic"):
    if f in {x.name for x in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 140

INK, PAPER = "#1C1C1C", "#F9F9FA"
BLUE, AMBER, GREY = "#5B8FF9", "#F0A050", "#9AA3B0"


def s16(u: int) -> int:
    return u - 65536 if u > 32767 else u


def measure_hil(leak: float = 0.05, pre: float = 4.0, total: float = 26.0,
                dt: float = 0.1) -> pd.DataFrame:
    """실제 PLC 폐루프에 누설을 주입하고 응답을 기록한다. 끝나면 반드시 원복한다."""
    from plc.modbus_tcp import ModbusTcpClient
    tw = ModbusTcpClient("127.0.0.1", 5020, unit=1, timeout=5.0)
    plc = ModbusTcpClient("127.0.0.1", 5502, unit=1, timeout=5.0)
    rows, t_inj = [], None
    try:
        t0 = time.time()
        while True:
            t = time.time() - t0
            if t >= pre and t_inj is None:
                tw.write_register(16, int(round(leak * 1e6)))   # HR16 INJ_QLEAK
                t_inj = t
            hr = plc.read_holding_registers(120, 4)
            rows.append((t, hr[0] / 100, hr[1] / 100, s16(hr[3]) / 100))
            if t > total:
                break
            time.sleep(dt)
    finally:
        tw.write_register(16, 0)
        time.sleep(0.5)
        assert tw.read_holding_registers(16, 1)[0] == 0, "누설 주입 원복 실패"
        plc.write_coil(883, True); time.sleep(0.4); plc.write_coil(883, False)
        tw.close(); plc.close()
    df = pd.DataFrame(rows, columns=["t", "p", "th", "drift"])
    df["t"] -= t_inj
    return df


def fig_hil(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(2, 1, figsize=(8.4, 5.4), sharex=True,
                           gridspec_kw={"hspace": 0.16})
    fig.patch.set_facecolor(PAPER)
    for a in ax:
        a.set_facecolor(PAPER)
        a.axvline(0, color=GREY, lw=1, ls="--")
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        a.grid(alpha=0.18)

    ax[0].plot(df.t, df.p, color=BLUE, lw=2)
    ax[0].axhline(40.0, color=GREY, lw=1, ls=":")
    ax[0].set_ylabel("챔버 압력 [mTorr]", color=INK)
    ax[0].set_title("누설을 넣으면 — 압력은 원래대로 돌아온다", color=INK, loc="left")
    fin = df.p.iloc[-20:].mean()
    ax[0].annotate(f"최종 {fin:.2f} mTorr\n잔류편차 {(fin-40)/40*100:+.3f} %",
                   xy=(df.t.iloc[-1], fin), xytext=(-140, 26),
                   textcoords="offset points", color=BLUE, fontsize=10)

    ax[1].plot(df.t, df.th, color=AMBER, lw=2)
    ax[1].set_ylabel("밸브 각도 [deg]", color=INK)
    ax[1].set_xlabel("누설 주입 후 경과 시간 [s]", color=INK)
    ax[1].set_title("밸브 각도에는 흔적이 남는다", color=INK, loc="left")
    th0 = df.th[df.t < 0].mean(); th1 = df.th.iloc[-20:].mean()
    ax[1].axhline(th0, color=GREY, lw=1, ls=":")
    ax[1].annotate(f"{th0:.2f}° → {th1:.2f}°  ({(th1-th0)/th0*100:+.2f} %)",
                   xy=(df.t.iloc[-1], th1), xytext=(-170, -30),
                   textcoords="offset points", color=AMBER, fontsize=10)

    fig.suptitle("실제 PLC(OpenPLC) 폐루프 측정 — 시뮬레이션이 아님",
                 color=INK, fontsize=11, y=0.985)
    fig.tight_layout()
    fig.savefig(OUT / "hil_leak_response.png", facecolor=PAPER)
    print(f"저장: {OUT/'hil_leak_response.png'}  "
          f"(압력 잔류 {(fin-40)/40*100:+.3f} %, 밸브각 {(th1-th0)/th0*100:+.2f} %)")


def fig_sawtooth() -> None:
    raw = pd.read_csv(ROOT / "data" / "Si_Oxide_etch_89_points.csv")
    g = raw.groupby("experiment_key")["si_etch"].mean().reset_index()
    g["lot"] = g.experiment_key.str[:10]
    g["seq"] = g.experiment_key.str[-2:].astype(int)
    g = g.sort_values(["lot", "seq"]).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(9.2, 3.6))
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)
    x = 0
    for i, (lot, d) in enumerate(g.groupby("lot")):
        xs = np.arange(x, x + len(d))
        ax.plot(xs, d.si_etch.values, "o-", color=BLUE if i % 2 == 0 else AMBER,
                lw=1.8, ms=4)
        x += len(d) + 1.2
        if i:
            ax.axvline(xs[0] - 1.1, color=GREY, lw=0.8, ls=":")
    ax.set_xticks([])
    ax.set_xlabel("웨이퍼 (로트 10개, 좌→우 처리 순서)", color=INK)
    ax.set_ylabel("Si 식각깊이 [μm]", color=INK)
    ax.set_title("로트 안에서 얕아지고, 로트가 바뀌면 회복된다 — 톱니",
                 color=INK, loc="left")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(alpha=0.18)
    fig.tight_layout()
    fig.savefig(OUT / "etch_depth_sawtooth.png", facecolor=PAPER)
    print(f"저장: {OUT/'etch_depth_sawtooth.png'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-hil", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not a.skip_hil:
        fig_hil(measure_hil())
    fig_sawtooth()


if __name__ == "__main__":
    main()
