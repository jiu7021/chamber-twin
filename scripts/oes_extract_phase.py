#!/usr/bin/env python3
"""Bosch 두 위상을 나눠 웨이퍼별 평균 스펙트럼을 만든다.

Bosch 공정은 식각(SF6)과 패시베이션(C4F8)이 번갈아 돈다. 레시피 duty 는 4.5 s / 1.5 s
이고, OES 의 F I 발광선이 그 주기로 밝기가 2.5배 오르내리므로 **공정 데이터와 시간축을
맞출 필요 없이 OES 자체로 위상을 가를 수 있다**.

위상 판정은 F I 685.6 nm (측정 684.39 nm, 파장 교정 오프셋 -1.21 nm) 강도에
웨이퍼별 임계를 걸어서 한다. 임계는 (10 분위 + 90 분위)/2 로, 두 준위의 중간이다.
전이 프레임은 앞뒤 GUARD 개를 버려 섞임을 막는다.

출력: reports/oes_spectra_phase.npz
    wavelengths, exp_key, mean_etch, mean_pass, frac_etch, n_etch, n_pass
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "reports" / "oes_spectra_phase.npz"

T_LO, T_HI = 50.0, 600.0
CHUNK = 2000
WL_F1 = 684.39          # F I 685.6 nm - 1.21 nm 교정 오프셋
GUARD = 2               # 전이 앞뒤로 버릴 프레임 수 (23 Hz 에서 약 87 ms)


def main() -> None:
    dec = np.asarray(Dataset(DATA / "Dictionary_OES.nc")["data"][:], dtype=np.float64)
    days = sorted(DATA.glob("Day_*.nc"))
    if not days:
        sys.exit("Day_*.nc 가 없다.")

    keys, me, mp, fr, ne, npass, wl_ref = [], [], [], [], [], [], None
    for path in days:
        m = re.match(r"Day_(\d{4})_(\d{2})_(\d{2})\.nc", path.name)
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        ds = Dataset(path)
        for gname in sorted(ds.groups):
            g = ds.groups[gname]
            wafer = int(re.search(r"(\d+)$", gname).group(1))
            t = np.asarray(g["times"][:], dtype=np.float64)
            t = t - t[0]
            wl = np.asarray(g["wavelengths"][:], dtype=np.float64)
            if wl_ref is None:
                wl_ref = wl
            jF = int(np.argmin(np.abs(wl - WL_F1)))

            sel = np.where((t >= T_LO) & (t <= T_HI))[0]
            i0, i1 = sel[0], sel[-1] + 1

            # 1) 위상 판정용 F I 시계열
            f = dec[np.asarray(g["data"][i0:i1, jF])]
            thr = (np.percentile(f, 10) + np.percentile(f, 90)) / 2.0
            etch = f > thr
            # 전이 프레임 제거 — 앞뒤 GUARD 개 안에 상태 변화가 있으면 버린다
            ch = np.zeros_like(etch)
            ch[1:] = etch[1:] != etch[:-1]
            bad = np.zeros_like(etch)
            for k in range(-GUARD, GUARD + 1):
                bad |= np.roll(ch, k)
            use_e, use_p = etch & ~bad, (~etch) & ~bad

            # 2) 위상별 합산
            acc_e = np.zeros(wl.size); acc_p = np.zeros(wl.size)
            for a in range(i0, i1, CHUNK):
                b = min(a + CHUNK, i1)
                blk = dec[np.asarray(g["data"][a:b])]
                s = slice(a - i0, b - i0)
                acc_e += blk[use_e[s]].sum(axis=0)
                acc_p += blk[use_p[s]].sum(axis=0)

            keys.append(f"{date}_{wafer:02d}")
            me.append(acc_e / use_e.sum()); mp.append(acc_p / use_p.sum())
            ne.append(int(use_e.sum())); npass.append(int(use_p.sum()))
            fr.append(etch.mean())
            print(f"  {date}_{wafer:02d}  식각 {use_e.sum():5d} / 패시베이션 {use_p.sum():5d} "
                  f"프레임, duty {etch.mean()*100:4.1f} %  F I 비 {(acc_e/use_e.sum())[jF]/(acc_p/use_p.sum())[jF]:4.2f}")
        ds.close()

    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(OUT, wavelengths=wl_ref, exp_key=np.array(keys),
                        mean_etch=np.array(me), mean_pass=np.array(mp),
                        frac_etch=np.array(fr), n_etch=np.array(ne), n_pass=np.array(npass))
    print(f"\n저장: {OUT}  ({len(keys)} 웨이퍼)")
    print(f"식각 duty 평균 {np.mean(fr)*100:.1f} %  (레시피 4.5/6.0 = 75.0 % 기대)")


if __name__ == "__main__":
    main()
