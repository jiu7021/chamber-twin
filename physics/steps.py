"""Bosch 사이클 스텝 검출과 위상정렬 앙상블 생성.

단위 주의: 압력·유량은 원시 단위(미확정)로만 다룬다. 시간만 s로 확정.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DT_S = 0.2  # 샘플링 주기 (Phase 0 측정: dt 중앙값 0.2 s)

# 레시피 값 (표준·규정: Zenodo Readme.pdf 1절)
RECIPE_PERIOD_S = 6.0
RECIPE_LONG_S = 4.5
RECIPE_SHORT_S = 1.5
RECIPE_N_CYCLES = 100

# 스텝 채택 지속시간 밴드 (레시피 ±0.5 s / ±0.3 s). 프리필·점화·종료 스텝을 배제하기 위한 사전 기준.
LONG_BAND_S = (4.0, 5.0)
SHORT_BAND_S = (1.2, 1.8)

# 챔버로 유입되는 가스 채널 (HeliumBPFlow는 척 배면 회로이므로 기본 제외, 민감도에서만 포함)
CHAMBER_GAS = ["Gas1Flow", "Gas2Flow", "Gas3Flow", "Gas4Flow", "Gas5Flow", "Gas7Flow", "Gas8Flow"]


def detect_edges(x: np.ndarray, t: np.ndarray, thresh: float) -> tuple[np.ndarray, np.ndarray]:
    """임계값 상향/하향 교차 시점을 선형보간으로 서브샘플 추정한다.

    Args:
        x: 신호 (원시 단위)
        t: 시각, 단위 s
        thresh: 임계값 (x와 동일 단위)

    Returns:
        (상승 교차시각[s], 하강 교차시각[s])
    """
    above = x > thresh
    ris_idx = np.flatnonzero(~above[:-1] & above[1:])
    fal_idx = np.flatnonzero(above[:-1] & ~above[1:])

    def interp(idx: np.ndarray) -> np.ndarray:
        if idx.size == 0:
            return np.empty(0)
        x0, x1 = x[idx], x[idx + 1]
        t0, t1 = t[idx], t[idx + 1]
        d = x1 - x0
        frac = np.where(np.abs(d) > 0, (thresh - x0) / np.where(d == 0, 1.0, d), 0.0)
        return t0 + frac * (t1 - t0)

    return interp(ris_idx), interp(fal_idx)


@dataclass(frozen=True)
class StepSet:
    """한 종류 스텝(긴/짧은)의 검출 결과.

    Attributes:
        rise_s: 레시피 정합 스텝의 상승 시각 배열, 단위 s
        dur_s: 각 스텝의 지속시간, 단위 s
        n_all: 밴드 필터 이전 검출된 전체 스텝 수
    """

    rise_s: np.ndarray
    dur_s: np.ndarray
    n_all: int


def find_steps(df: pd.DataFrame, gas: str, band: tuple[float, float]) -> StepSet:
    """지정 가스 채널의 구형파 스텝을 검출하고 레시피 밴드로 거른다.

    Args:
        df: 웨이퍼 시계열 (인덱스 t[s])
        gas: 채널명 (예: 'Gas5Flow')
        band: 채택할 지속시간 범위 (s)

    Returns:
        StepSet
    """
    t = df.index.values
    x = df[gas].values
    thr = 0.5 * np.nanmax(x)
    ris, fal = detect_edges(x, t, thr)
    n = min(len(ris), len(fal))
    if n == 0:
        return StepSet(np.empty(0), np.empty(0), 0)
    # 상승 이후의 첫 하강과 짝짓기
    pairs = []
    for r in ris:
        after = fal[fal > r]
        if after.size:
            pairs.append((r, after[0] - r))
    if not pairs:
        return StepSet(np.empty(0), np.empty(0), 0)
    arr = np.array(pairs)
    keep = (arr[:, 1] >= band[0]) & (arr[:, 1] <= band[1])
    return StepSet(arr[keep, 0], arr[keep, 1], len(arr))


def ensemble(
    df: pd.DataFrame, rise_s: np.ndarray, cols: list[str], k_lo: int = -3, k_hi: int = 32
) -> pd.DataFrame:
    """스텝 상승에지에 위상정렬한 앙상블 평균 사이클을 만든다.

    각 스텝마다 상승에지 직후 첫 샘플을 k=0으로 두고 정수 오프셋 k별로 평균한다.
    (사이클 간 에지 위상 분산이 샘플 간격의 0.2배 수준이라 초해상 결합은 하지 않는다.)

    Args:
        df: 웨이퍼 시계열 (인덱스 t[s])
        rise_s: 스텝 상승 시각 배열, 단위 s
        cols: 평균할 채널 목록
        k_lo: 시작 오프셋 (음수 = 에지 이전)
        k_hi: 끝 오프셋 (배타)

    Returns:
        DataFrame — 인덱스 k, 컬럼: rel_t_s(에지 기준 평균 상대시각[s]), n,
        각 채널의 평균값(<col>) 및 평균의 표준오차(<col>_sem)
    """
    t = df.index.values
    vals = {c: df[c].values for c in cols}
    out_rows = []
    for k in range(k_lo, k_hi):
        rel, buf = [], {c: [] for c in cols}
        for e in rise_s:
            i = int(np.searchsorted(t, e)) + k
            if 0 <= i < len(t):
                rel.append(t[i] - e)
                for c in cols:
                    buf[c].append(vals[c][i])
        if not rel:
            continue
        row = {"k": k, "rel_t_s": float(np.mean(rel)), "n": len(rel)}
        for c in cols:
            a = np.asarray(buf[c], dtype=float)
            row[c] = float(a.mean())
            row[f"{c}_sem"] = float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else np.nan
        out_rows.append(row)
    return pd.DataFrame(out_rows).set_index("k")
