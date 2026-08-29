"""Phase 1 / Task A-1: Bosch 사이클 주기 확인과 스텝 검출.

절차
 1) 유량 신호의 자기상관 + FFT로 사이클 주기를 독립적으로 두 번 추정
 2) 임계값 교차로 긴 스텝(Gas5)·짧은 스텝(Gas4)의 상승/하강 에지 검출
 3) 검출된 사이클 수를 레시피 값(100 사이클)과 교차확인

단위 주의: 압력·유량은 원시 단위(미확정). 이 스크립트는 단위 변환을 하지 않는다.
시간만 초(s) 단위로 확정되어 있다(NetCDF times 속성: seconds since epoch).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physics.dataio import list_groups, load_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

# 레시피 값 (표준·규정: Readme.pdf 1절 — 1초 점화 후 100 사이클 × (SF6 4.5 s + C4F8 1.5 s))
RECIPE_N_CYCLES = 100
RECIPE_PERIOD_S = 6.0
RECIPE_LONG_S = 4.5
RECIPE_SHORT_S = 1.5

DT_S = 0.2  # 데이터에서 측정한 샘플링 주기 (Phase 0 확인: dt 중앙값 0.2 s = 5 Hz)


def detect_edges(x: np.ndarray, t: np.ndarray, thresh: float) -> tuple[np.ndarray, np.ndarray]:
    """임계값 상향/하향 교차 시점을 선형보간으로 서브샘플 추정한다.

    Args:
        x: 신호 (원시 단위)
        t: 시각, 단위 s
        thresh: 임계값 (x와 동일 단위)

    Returns:
        (rising_times_s, falling_times_s) — 각각 단위 s
    """
    above = x > thresh
    ris_idx = np.flatnonzero(~above[:-1] & above[1:])
    fal_idx = np.flatnonzero(above[:-1] & ~above[1:])

    def interp(idx: np.ndarray) -> np.ndarray:
        if idx.size == 0:
            return np.empty(0)
        x0, x1 = x[idx], x[idx + 1]
        t0, t1 = t[idx], t[idx + 1]
        frac = np.where(np.abs(x1 - x0) > 0, (thresh - x0) / (x1 - x0), 0.0)
        return t0 + frac * (t1 - t0)

    return interp(ris_idx), interp(fal_idx)


def period_autocorr(x: np.ndarray, dt: float, max_lag_s: float = 20.0) -> float:
    """자기상관 첫 주요 피크로 주기를 추정한다.

    Args:
        x: 신호
        dt: 샘플 간격, 단위 s
        max_lag_s: 탐색 최대 지연, 단위 s

    Returns:
        주기, 단위 s
    """
    xc = x - x.mean()
    n = len(xc)
    ac = np.correlate(xc, xc, mode="full")[n - 1 :]
    ac /= ac[0]
    max_lag = int(max_lag_s / dt)
    ac = ac[: max_lag + 1]
    # lag 0 근처의 자기 피크를 건너뛰기 위해 첫 음수 교차 이후에서 최대값 탐색
    neg = np.flatnonzero(ac < 0)
    if neg.size == 0:
        return float("nan")
    start = neg[0]
    k = start + int(np.argmax(ac[start:]))
    # 포물선 보간으로 서브샘플 피크 위치
    if 0 < k < len(ac) - 1:
        y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]
        denom = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        delta = 0.0
    return (k + delta) * dt


def period_fft(x: np.ndarray, dt: float) -> float:
    """FFT 최대 성분 주파수로 주기를 추정한다.

    Args:
        x: 신호
        dt: 샘플 간격, 단위 s

    Returns:
        주기, 단위 s
    """
    xc = x - x.mean()
    win = np.hanning(len(xc))
    sp = np.abs(np.fft.rfft(xc * win))
    fr = np.fft.rfftfreq(len(xc), dt)
    sp[0] = 0.0
    k = int(np.argmax(sp))
    if 0 < k < len(sp) - 1:  # 포물선 보간
        y0, y1, y2 = sp[k - 1], sp[k], sp[k + 1]
        denom = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        delta = 0.0
    f = (k + delta) * (fr[1] - fr[0])
    return 1.0 / f if f > 0 else float("nan")


def analyse_run(group: str) -> dict:
    """웨이퍼 1장의 사이클 구조를 분석한다."""
    r = load_run(group)
    t = r.df.index.values
    g_long = r.df["Gas5Flow"].values
    g_short = r.df["Gas4Flow"].values

    # 임계값: 각 신호 최대값의 50% (레벨 절대값에 의존하지 않도록 상대 임계)
    thr_long = 0.5 * np.nanmax(g_long)
    thr_short = 0.5 * np.nanmax(g_short)

    ris_l, fal_l = detect_edges(g_long, t, thr_long)
    ris_s, fal_s = detect_edges(g_short, t, thr_short)

    # Bosch 구간: 첫 긴-스텝 상승 ~ 마지막 긴-스텝 하강
    if ris_l.size < 2:
        return {"group": group, "ok": False, "reason": "긴 스텝 에지 부족"}
    bosch_t0, bosch_t1 = ris_l[0], fal_l[-1]
    in_bosch = (t >= bosch_t0 - 1.0) & (t <= bosch_t1 + 1.0)

    per_ac = period_autocorr(g_long[in_bosch], DT_S)
    per_fft = period_fft(g_long[in_bosch], DT_S)
    per_edge = float(np.median(np.diff(ris_l))) if ris_l.size > 1 else float("nan")

    dur_long = fal_l - ris_l[: len(fal_l)] if fal_l.size else np.empty(0)
    dur_short = fal_s - ris_s[: len(fal_s)] if fal_s.size else np.empty(0)

    return {
        "group": group,
        "date": r.date,
        "wafer": r.wafer,
        "exp_key": r.exp_key,
        "ok": True,
        "n_rise_long": int(ris_l.size),
        "n_fall_long": int(fal_l.size),
        "n_rise_short": int(ris_s.size),
        "n_fall_short": int(fal_s.size),
        "period_autocorr_s": per_ac,
        "period_fft_s": per_fft,
        "period_edge_median_s": per_edge,
        "period_edge_std_s": float(np.std(np.diff(ris_l))) if ris_l.size > 2 else np.nan,
        "dur_long_median_s": float(np.median(dur_long)) if dur_long.size else np.nan,
        "dur_short_median_s": float(np.median(dur_short)) if dur_short.size else np.nan,
        "flow_long_level": float(np.nanmax(g_long)),
        "flow_short_level": float(np.nanmax(g_short)),
        "bosch_t0_s": float(bosch_t0),
        "bosch_t1_s": float(bosch_t1),
        "run_duration_s": float(t[-1]),
    }


def main() -> None:
    rows = [analyse_run(g) for g in list_groups()]
    df = pd.DataFrame(rows)
    out = RESULTS / "phase1_cycles.csv"
    df.to_csv(out, index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    print(f"저장: {out}  (그룹 {len(df)}개)")
    print()
    cols = [
        "n_rise_long", "n_fall_long", "n_rise_short", "n_fall_short",
        "period_autocorr_s", "period_fft_s", "period_edge_median_s", "period_edge_std_s",
        "dur_long_median_s", "dur_short_median_s",
        "flow_long_level", "flow_short_level",
    ]
    print("=== 전체 96그룹 요약 ===")
    print(df[cols].describe().T.to_string())
    print()
    print(f"=== 레시피 대조 (기대: 사이클 {RECIPE_N_CYCLES}, 주기 {RECIPE_PERIOD_S} s, "
          f"긴 {RECIPE_LONG_S} s, 짧은 {RECIPE_SHORT_S} s) ===")
    print("긴 스텝 상승에지 개수 분포:")
    print(df["n_rise_long"].value_counts().sort_index().to_string())
    print("짧은 스텝 상승에지 개수 분포:")
    print(df["n_rise_short"].value_counts().sort_index().to_string())
    print()
    bad = df[df["n_rise_long"] != RECIPE_N_CYCLES]
    print(f"긴 스텝 검출수 != {RECIPE_N_CYCLES} 인 그룹 수: {len(bad)}")
    if len(bad):
        print(bad[["group", "n_rise_long", "n_rise_short", "run_duration_s"]].to_string(index=False))


if __name__ == "__main__":
    main()
