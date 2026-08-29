"""Process_data.nc 로더.

Zenodo DOI 10.5281/zenodo.17122442 데이터셋의 16비트 딕셔너리 인코딩을 해제해
웨이퍼별 시계열을 pandas DataFrame으로 반환한다.

단위 주의: 이 데이터셋의 압력·유량 채널에는 단위 메타데이터가 없다.
본 모듈은 단위 변환을 일절 수행하지 않고 원시(raw) 값을 그대로 반환한다.
단위 확정 전까지 모든 하위 분석은 단위 불가지론으로 작성한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PROCESS_NC = DATA_DIR / "Process_data.nc"
DICT_NC = DATA_DIR / "Dictionary_process.nc"

GROUP_RE = re.compile(r"Day_(\d{4})_(\d{2})_(\d{2})_Wafer_(\d+)")


@dataclass(frozen=True)
class WaferRun:
    """웨이퍼 1장의 공정 시계열.

    Attributes:
        group: NetCDF 그룹명 (예: 'Day_2024_07_05_Wafer_02')
        date: 'YYYY-MM-DD' 문자열
        wafer: 로트 내 웨이퍼 순번 (1~10)
        exp_key: 'YYYY-MM-DD_WW' — 측정 CSV의 experiment_key와 매칭되는 키
        t: 시각 배열, 단위 s (런 시작 기준 상대시간)
        df: 채널 시계열, 인덱스는 t(단위 s), 값은 원시 단위(미확정)
    """

    group: str
    date: str
    wafer: int
    exp_key: str
    t: np.ndarray
    df: pd.DataFrame


@lru_cache(maxsize=1)
def _decoder() -> np.ndarray:
    """딕셔너리 룩업테이블(float32) 반환. 단위 없음(채널별 원시값)."""
    with Dataset(DICT_NC, "r") as ds:
        return np.asarray(ds["data"][:], dtype=np.float64)


@lru_cache(maxsize=1)
def list_groups() -> tuple[str, ...]:
    """Process_data.nc의 전체 그룹명(웨이퍼 96개)을 정렬해 반환."""
    with Dataset(PROCESS_NC, "r") as ds:
        return tuple(sorted(ds.groups.keys()))


def parse_group(group: str) -> tuple[str, int, str]:
    """그룹명 -> (date 'YYYY-MM-DD', wafer 순번, exp_key 'YYYY-MM-DD_WW')."""
    m = GROUP_RE.match(group)
    if m is None:
        raise ValueError(f"그룹명 형식 불일치: {group}")
    y, mo, d, w = m.group(1), m.group(2), m.group(3), int(m.group(4))
    date = f"{y}-{mo}-{d}"
    return date, w, f"{date}_{w:02d}"


def load_run(group: str) -> WaferRun:
    """웨이퍼 1장의 시계열을 로드한다.

    Args:
        group: NetCDF 그룹명

    Returns:
        WaferRun. df의 인덱스는 런 시작 기준 상대시간(단위 s),
        컬럼은 'Stat3_Etch_MV_' 접두사를 제거한 채널명, 값은 원시 단위(미확정).
    """
    dec = _decoder()
    with Dataset(PROCESS_NC, "r") as ds:
        g = ds.groups[group]
        feats = [str(x).replace("Stat3_Etch_MV_", "") for x in g["feature"][:]]
        encoded = np.asarray(g["data"][:])
        times = np.asarray(g["times"][:], dtype=np.float64)
    data = dec[encoded]
    t = times - times[0]  # 단위 s
    df = pd.DataFrame(data, index=pd.Index(t, name="t_s"), columns=feats)
    date, wafer, exp_key = parse_group(group)
    return WaferRun(group=group, date=date, wafer=wafer, exp_key=exp_key, t=t, df=df)


COMMON_31 = None  # load_common_features()로 채워짐


def common_features() -> list[str]:
    """전체 96그룹에 공통으로 존재하는 채널명(접두사 제거) 목록을 반환."""
    global COMMON_31
    if COMMON_31 is None:
        sets = []
        with Dataset(PROCESS_NC, "r") as ds:
            for gname in ds.groups:
                feats = {
                    str(x).replace("Stat3_Etch_MV_", "")
                    for x in ds.groups[gname]["feature"][:]
                }
                sets.append(feats)
        COMMON_31 = sorted(set.intersection(*sets))
    return list(COMMON_31)
