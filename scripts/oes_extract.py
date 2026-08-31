#!/usr/bin/env python3
"""OES 스펙트럼에서 웨이퍼별 평균 스펙트럼을 추출한다.

Day_YYYY_MM_DD.nc 는 웨이퍼 그룹마다 (시간 × 파장) uint16 인덱스 행렬을 담고,
실제 강도는 Dictionary_OES.nc 의 코드북으로 복원한다 (`dec[encoded]`).
Process_data.nc 와 동일한 인코딩 방식이다.

평균 구간은 50~600 s 로 고정한다. 앞뒤는 점화·소화 램프이고, 그 사이는
Bosch 사이클 두 위상이 고정 duty 로 반복되므로 전 구간 평균이면 웨이퍼 간
위상 혼합비가 동일하다.

출력: reports/oes_spectra.npz
    wavelengths (3648,)  exp_key (N,)  mean_spec (N, 3648)  total (N,)  n_frames (N,)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "reports" / "oes_spectra.npz"

T_LO, T_HI = 50.0, 600.0     # 평균 구간 [s] — 램프 제외
CHUNK = 2000                 # 시간축 청크 (메모리 억제)


def main() -> None:
    dec = np.asarray(Dataset(DATA / "Dictionary_OES.nc")["data"][:], dtype=np.float64)
    days = sorted(DATA.glob("Day_*.nc"))
    if not days:
        sys.exit("Day_*.nc 가 없다. ./scripts/download.sh --oes 를 먼저 실행할 것")

    keys, specs, totals, nframes, wl_ref = [], [], [], [], None
    for path in days:
        m = re.match(r"Day_(\d{4})_(\d{2})_(\d{2})\.nc", path.name)
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        try:
            ds = Dataset(path)
        except OSError:
            # 다운로드가 끝나지 않은 파일. 완료 후 다시 실행할 것.
            print(f"  건너뜀(열 수 없음, 다운로드 미완료 추정): {path.name}")
            continue
        for gname in sorted(ds.groups):
            g = ds.groups[gname]
            wafer = int(re.search(r"(\d+)$", gname).group(1))
            t = np.asarray(g["times"][:], dtype=np.float64)
            t = t - t[0]
            wl = np.asarray(g["wavelengths"][:], dtype=np.float64)
            if wl_ref is None:
                wl_ref = wl
            elif not np.allclose(wl, wl_ref):
                sys.exit(f"파장축 불일치: {path.name}/{gname}")

            sel = np.where((t >= T_LO) & (t <= T_HI))[0]
            if sel.size == 0:
                print(f"  건너뜀(구간 없음): {date} {gname}")
                continue
            i0, i1 = sel[0], sel[-1] + 1

            acc = np.zeros(wl.size, dtype=np.float64)
            n = 0
            for a in range(i0, i1, CHUNK):
                b = min(a + CHUNK, i1)
                acc += dec[np.asarray(g["data"][a:b])].sum(axis=0)
                n += b - a
            mean_spec = acc / n

            keys.append(f"{date}_{wafer:02d}")
            specs.append(mean_spec)
            totals.append(mean_spec.sum())
            nframes.append(n)
            print(f"  {date}_{wafer:02d}  프레임 {n:6d}  총발광 {mean_spec.sum():10.0f}")
        ds.close()

    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(
        OUT, wavelengths=wl_ref, exp_key=np.array(keys),
        mean_spec=np.array(specs), total=np.array(totals), n_frames=np.array(nframes))
    print(f"\n저장: {OUT}  ({len(keys)} 웨이퍼 × {wl_ref.size} 파장)")


if __name__ == "__main__":
    main()
