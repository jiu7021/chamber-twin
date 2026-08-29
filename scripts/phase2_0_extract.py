"""Phase 2-0 / 1단계: 포어라인·온도·He 배면 채널의 웨이퍼별 요약 추출.

Phase 1 결론에 따라 진단 축을 챔버 압력(APC 서보로 정보 없음)에서
포어라인 압력(스로틀 밸브 하류, 비제어)으로 옮긴다.

단위 불가지론 — 압력·유량·온도 단위는 미확정이므로 환산하지 않는다. 시간만 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.dataio import list_groups, load_run  # noqa: E402
from physics.steps import (  # noqa: E402
    CHAMBER_GAS, LONG_BAND_S, SHORT_BAND_S, ensemble, find_steps,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

LONG_SS_WIN_S = (2.0, 4.2)
SHORT_SS_WIN_S = (0.9, 1.35)

TEMP_CH = ["Heater1Temp", "Heater2Temp", "Heater3Temp", "Heater4Temp"]
OTHER_CH = ["ForeLinePressure", "Pressure", "HeliumBPFlow", "HeliumBPPressure",
            "PlatenRFLoadPower", "SourceRFLoadPower", "SourceRFReflectedPower",
            "moriInnerCurrent", "PlatenRFTuningCapacitor", "PlatenRFLoadCapacitor",
            "SourceRFTuningCapacitor"]

# Lot_status.xlsx (표준·규정: 데이터셋 동봉 문서) — 날짜 -> (로트번호, 컨디셔닝 조건)
LOT_INFO = {
    "2024-07-02": (1, "3C"),      "2024-07-05": (2, "1C"),
    "2024-07-09": (3, "9C"),      "2024-07-11": (4, "3C-Si"),
    "2024-07-19": (5, "1C-Si"),   "2024-08-01": (6, "9C-Si"),
    "2024-08-05": (7, "3C-SiO2"), "2024-08-07": (8, "3C-SiO2"),
    "2024-08-21": (9, "3C"),      "2024-08-22": (10, "3C-SiO2"),
}


def summarize(group: str) -> dict:
    """웨이퍼 1장의 Bosch 구간 채널 요약."""
    r = load_run(group)
    df = r.df
    gases = [g for g in CHAMBER_GAS if g in df.columns]
    df = df.assign(Qtot=df[gases].sum(axis=1))

    L = find_steps(df, "Gas5Flow", LONG_BAND_S)
    S = find_steps(df, "Gas4Flow", SHORT_BAND_S)
    if L.rise_s.size < 10 or S.rise_s.size < 10:
        return {"group": group, "ok": False}

    t0, t1 = L.rise_s[0], L.rise_s[-1] + 4.4  # Bosch 정상 사이클 구간
    bosch = df.loc[t0:t1]

    out = {"group": group, "date": r.date, "seq": r.wafer, "exp_key": r.exp_key, "ok": True,
           "n_bosch_samples": len(bosch), "bosch_span_s": float(t1 - t0)}
    out["lot"], out["cond_type"] = LOT_INFO[r.date]

    for ch in TEMP_CH + OTHER_CH + ["Qtot"]:
        if ch in bosch.columns:
            out[f"{ch}_mean"] = float(bosch[ch].mean())
            out[f"{ch}_std"] = float(bosch[ch].std())

    # 스텝별 포어라인 평탄부 (듀티 혼합 없이 보기 위함)
    cols = ["ForeLinePressure", "Pressure", "Qtot"]
    eL = ensemble(df, L.rise_s, cols, k_lo=0, k_hi=25)
    eS = ensemble(df, S.rise_s, cols, k_lo=0, k_hi=10)
    for tag, e, win in (("long", eL, LONG_SS_WIN_S), ("short", eS, SHORT_SS_WIN_S)):
        m = (e["rel_t_s"] >= win[0]) & (e["rel_t_s"] <= win[1])
        for ch in cols:
            out[f"{tag}_{ch}"] = float(np.median(e.loc[m, ch].values)) if m.any() else np.nan
    return out


def etch_metrics() -> pd.DataFrame:
    """89점 측정에서 웨이퍼별 평균 식각 깊이와 면내 균일도를 산출한다.

    Returns:
        DataFrame — experiment_key별 si_etch/oxide_etch의 평균·표준편차·변동계수(=균일도),
        범위(max−min), 측정점 수. 모든 두께 값의 단위는 µm (Readme 2.3절 명시).
    """
    df = pd.read_csv(ROOT / "data" / "Si_Oxide_etch_89_points.csv")
    g = df.groupby("experiment_key")
    out = pd.DataFrame({
        "si_etch_mean": g["si_etch"].mean(),
        "si_etch_std": g["si_etch"].std(),
        "si_etch_range": g["si_etch"].max() - g["si_etch"].min(),
        "oxide_etch_mean": g["oxide_etch"].mean(),
        "oxide_etch_std": g["oxide_etch"].std(),
        "postox_mean": g["postox_thickness"].mean(),
        "n_points": g["si_etch"].size(),
        "n_nan_interp": g["postox_thickness_nan"].sum() if "postox_thickness_nan" in df else np.nan,
    })
    out["si_etch_cv"] = out["si_etch_std"] / out["si_etch_mean"]      # 면내 균일도 (작을수록 균일)
    out["oxide_etch_cv"] = out["oxide_etch_std"] / out["oxide_etch_mean"]
    return out.reset_index().rename(columns={"experiment_key": "exp_key"})


def main() -> None:
    rows = []
    for i, g in enumerate(list_groups(), 1):
        rows.append(summarize(g))
        if i % 24 == 0:
            print(f"  ... {i}/96", flush=True)
    df = pd.DataFrame(rows)

    df = df.merge(etch_metrics(), on="exp_key", how="left")
    df["has_89pt"] = df["si_etch_mean"].notna()
    # 캠페인 전체 처리 순서 (로트 순 -> 로트 내 순번). 절대 타임스탬프는 데이터에 없음.
    df = df.sort_values(["lot", "seq"]).reset_index(drop=True)
    df["global_idx"] = np.arange(1, len(df) + 1)

    out = RESULTS / "phase2_0_wafer_summary.csv"
    df.to_csv(out, index=False)
    print(f"\n저장: {out}  ({len(df)}행, {df.shape[1]}열)")
    print(f"89점 측정 있음: {df.has_89pt.sum()} / {len(df)}")


if __name__ == "__main__":
    main()
