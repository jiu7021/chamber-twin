#!/usr/bin/env python3
"""역산 밸브각이 식각깊이의 로트 내 순번 효과를 설명하는가.

지금까지 하지 않은 검정이다. Phase 1 은 "압력으로 배기속도를 못 뽑는다"까지,
Phase 3~4 는 "트윈 안에서 밸브각이 해석해와 맞는다"까지였다.
**역산한 밸브각을 식각깊이와 직접 맞춰본 적은 없다.**

절차
  1. 웨이퍼 96장의 Bosch 정상 구간에서 챔버 압력 P 와 총유량 Q 의 평균을 뽑는다.
  2. 정상상태 진공식으로 밸브각을 역산한다.
       S_eff = Q / P,  1/S_eff = 1/C + 1/S_pump,  C(θ) = C_max (1 − cos θ)
       θ = arccos(1 − C / C_max)
  3. Phase 2 와 같은 설계로 검정한다.
       (a) θ  ~ C(lot) + seq                     → 밸브각 자체가 순번에 따라 변하는가
       (b) 깊이 ~ C(lot) + seq + θ               → 순번 계수 흡수율
       (c) 순번·로트를 통제한 θ 와 깊이의 편상관 → 순번의 대리변수가 아닌가

가정치와 민감도
  P 의 절대 단위가 데이터에 없다. 값 범위(평균 0.0405)와 DRIE 통상 운전압을 근거로
  Torr 로 본다. Q 는 sccm 으로 본다. S_pump 와 C_max 는 시뮬레이터 설정값이다.
  이 넷이 틀리면 θ 의 절대값은 바뀌지만 순번 기울기의 부호와 유의성은 바뀌지 않는지
  민감도로 확인한다.
"""
from __future__ import annotations

import sys
from math import acos, degrees
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from physics.dataio import list_groups, load_run          # noqa: E402
from physics.steps import find_steps                       # noqa: E402
from physics.units import TORR_TO_PA, SCCM_TO_PAM3S        # noqa: E402

CHAMBER_GAS = ["Gas1Flow", "Gas2Flow", "Gas4Flow", "Gas5Flow", "Gas7Flow"]
LONG_BAND_S, SHORT_BAND_S = (3.5, 6.0), (0.8, 2.5)
S_PUMP = 1.500      # (통상범위) DRIE 용 TMP 1000~2000 L/s
C_MAX = 2.000       # (가정치) 시험대 설정
CACHE = ROOT / "reports" / "phase7_valve.csv"


def theta_deg(P_pa: float, Q_pam3s: float, s_pump=S_PUMP, c_max=C_MAX) -> float:
    """정상상태 (P, Q) 에서 밸브각을 역산한다. 물리적으로 불가능하면 NaN."""
    if P_pa <= 0 or Q_pam3s <= 0:
        return np.nan
    s_eff = Q_pam3s / P_pa
    if s_eff >= s_pump:                       # 펌프 단독 한계를 넘음 — 가정 위반
        return np.nan
    c = 1.0 / (1.0 / s_eff - 1.0 / s_pump)
    x = 1.0 - c / c_max
    return degrees(acos(x)) if -1.0 <= x <= 1.0 else np.nan


def extract() -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_csv(CACHE)
    rows = []
    for g in list_groups():
        r = load_run(g)
        df = r.df
        gases = [c for c in CHAMBER_GAS if c in df.columns]
        df = df.assign(Qtot=df[gases].sum(axis=1))
        L = find_steps(df, "Gas5Flow", LONG_BAND_S)
        S = find_steps(df, "Gas4Flow", SHORT_BAND_S)
        if L.rise_s.size < 10 or S.rise_s.size < 10:
            print(f"  건너뜀(스텝 부족): {g}")
            continue
        b = df.loc[L.rise_s[0]: L.rise_s[-1] + 4.4]        # Bosch 정상 사이클 구간
        rows.append({"exp_key": r.exp_key, "lot": r.date, "seq": r.wafer,
                     "P_raw": float(b["Pressure"].mean()),
                     "Q_raw": float(b["Qtot"].mean())})
        print(f"  {r.exp_key}  P {rows[-1]['P_raw']:.5f}  Q {rows[-1]['Q_raw']:.2f}")
    d = pd.DataFrame(rows)
    CACHE.parent.mkdir(exist_ok=True)
    d.to_csv(CACHE, index=False)
    return d


def tests(m: pd.DataFrame, col: str, label: str) -> None:
    ok = m[col].notna() & m.si_etch.notna()
    d = m.loc[ok].reset_index(drop=True)
    if d[col].std() < 1e-12 or len(d) < 20:
        print(f"[{label}] 검정 불가 (n={len(d)}, std={d[col].std():.3e})")
        return
    base = smf.ols("si_etch ~ C(lot) + seq", data=d).fit()
    b0 = base.params["seq"]

    d = d.rename(columns={col: "v"})
    a = smf.ols("v ~ C(lot) + seq", data=d).fit()
    r = smf.ols("si_etch ~ C(lot) + seq + v", data=d).fit()
    rv = smf.ols("v ~ C(lot) + seq", data=d).fit().resid
    rd = smf.ols("si_etch ~ C(lot) + seq", data=d).fit().resid
    pr = np.corrcoef(rv, rd)[0, 1]
    dof = len(d) - d.lot.nunique() - 2
    t = pr * np.sqrt(dof / max(1 - pr**2, 1e-12))
    p_pr = 2 * stats.t.sf(abs(t), dof)

    print(f"\n[{label}]  n = {len(d)}")
    print(f"  값 범위 {d.v.min():.4f} ~ {d.v.max():.4f}, 로트내 변동 std {d.v.std():.5f}")
    print(f"  (a) 순번 의존성   기울기 {a.params['seq']:+.6f} /장,  p = {a.pvalues['seq']:.3e}"
          f"   10장 변화 {a.params['seq']*10/d.v.mean()*100:+.3f} %")
    print(f"  (b) 흡수율        {(b0 - r.params['seq']) / b0 * 100:+.2f} %"
          f"   (투입 후 seq p = {r.pvalues['seq']:.3e})")
    print(f"  (c) 편상관        r = {pr:+.4f},  p = {p_pr:.4f}"
          f"   → {'순번 너머의 정보 있음' if p_pr < 0.05 else '순번 너머의 정보 없음'}")


def main() -> None:
    d = extract()
    dep = pd.read_csv(ROOT / "data" / "Si_Oxide_etch_89_points.csv") \
            .groupby("experiment_key")["si_etch"].mean()
    m = d.join(dep, on="exp_key")
    m["P_pa"] = m.P_raw * TORR_TO_PA
    m["Q_si"] = m.Q_raw * SCCM_TO_PAM3S
    m["theta"] = [theta_deg(p, q) for p, q in zip(m.P_pa, m.Q_si)]
    m["S_eff_Lps"] = m.Q_si / m.P_pa * 1e3

    print(f"\n웨이퍼 {len(m)}장, 식각깊이 있는 것 {int(m.si_etch.notna().sum())}장, "
          f"로트 {m.lot.nunique()}개")
    print(f"역산 성공 {int(m.theta.notna().sum())}장 "
          f"(실패 {int(m.theta.isna().sum())}장 — S_eff ≥ S_pump 등 가정 위반)")
    if m.theta.notna().sum():
        print(f"  θ 범위 {m.theta.min():.3f} ~ {m.theta.max():.3f} deg, "
              f"S_eff {m.S_eff_Lps.min():.1f} ~ {m.S_eff_Lps.max():.1f} L/s")

    tests(m, "theta", "역산 밸브각 θ [deg]")
    tests(m, "S_eff_Lps", "유효 배기속도 S_eff [L/s] (참고)")
    tests(m, "P_raw", "챔버 압력 (참고)")
    tests(m, "Q_raw", "총유량 (참고)")

    print("\n[민감도] 가정치를 바꿔도 θ 의 순번 기울기 부호·유의성이 유지되는가")
    for sp, cm in [(1.0, 2.0), (1.5, 1.2), (1.5, 3.0), (2.0, 2.0), (1.5, 2.0)]:
        th = np.array([theta_deg(p, q, sp, cm) for p, q in zip(m.P_pa, m.Q_si)])
        mm = m.assign(v=th)
        ok = mm.v.notna() & mm.si_etch.notna()
        if ok.sum() < 20 or mm.loc[ok, "v"].std() < 1e-12:
            print(f"  S_pump {sp} / C_max {cm}: 역산 불가 {int((~mm.v.notna()).sum())}장")
            continue
        a = smf.ols("v ~ C(lot) + seq", data=mm.loc[ok]).fit()
        print(f"  S_pump {sp} / C_max {cm}:  θ평균 {mm.loc[ok,'v'].mean():6.2f}°"
              f"  기울기 {a.params['seq']:+.6f}  p = {a.pvalues['seq']:.3e}")


if __name__ == "__main__":
    main()
