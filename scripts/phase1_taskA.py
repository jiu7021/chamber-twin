"""Phase 1 / Task A: 유효 배기속도 역산.

모델  V·dP/dt = Q_in(t) − S_eff·P(t),  τ = V/S_eff,  P_ss = Q_in/S_eff

경로 1 (과도응답)  스텝 상승 후 P(t)=P_inf+(P0−P_inf)exp(−t/τ) 피팅 → τ
경로 2 (정상상태)  스텝 평탄부에서 S_eff = Q_in/P_ss
게이트 (사용자 지정)  x=Q/P_ss, y=1/τ 원점통과 회귀. R²>0.95, 절편 CI가 0 포함. 기울기 역수 = V
진단 (추가)  적분형 ODE 선형회귀로 V와 구간별 S를 동시 추정 (미분 없이, 입력 램프 포함)

단위 불가지론: 압력·유량 단위는 미확정이므로 어떤 환산도 하지 않는다. 시간만 s.
따라서 S_eff의 단위는 [Q단위/P단위], V의 단위는 [Q단위·s/P단위]이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.dataio import list_groups, load_run  # noqa: E402
from physics.fit import fit_ode_integral, fit_tau  # noqa: E402
from physics.steps import (  # noqa: E402
    CHAMBER_GAS, LONG_BAND_S, SHORT_BAND_S, ensemble, find_steps,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

PRESSURE = "Pressure"          # 챔버 압력 채널 (단위 미확정)
LONG_GAS = "Gas5Flow"          # 긴 스텝 가스 (~4.45 s, 레벨 600) — 종 미확정
SHORT_GAS = "Gas4Flow"         # 짧은 스텝 가스 (~1.48 s, 레벨 300) — 종 미확정

# 피팅 창 파라미터 (전환 직후 밸브·MFC 응답 지연 제외). 민감도는 아래 SENS_* 로 확인.
LONG_EXCL_S, LONG_FITLEN_S = 0.4, 1.8
SHORT_EXCL_S, SHORT_FITLEN_S = 0.25, 1.1
SENS_LONG_EXCL = (0.3, 0.4, 0.5, 0.7)
SENS_SHORT_EXCL = (0.15, 0.25, 0.35, 0.45)

# 정상상태 평탄부 창 (스텝 상승 기준 상대시각 [s])
LONG_SS_WIN_S = (2.0, 4.2)
SHORT_SS_WIN_S = (0.9, 1.35)


def _plateau(ens: pd.DataFrame, win: tuple[float, float], col: str) -> tuple[float, float]:
    """평탄부 구간의 (중앙값, 상대드리프트) 반환. 드리프트=(끝−처음)/중앙값."""
    m = (ens["rel_t_s"] >= win[0]) & (ens["rel_t_s"] <= win[1])
    v = ens.loc[m, col].values
    if v.size == 0:
        return np.nan, np.nan
    med = float(np.median(v))
    drift = float((v[-1] - v[0]) / med) if med != 0 else np.nan
    return med, drift


def analyse_wafer(group: str) -> dict:
    """웨이퍼 1장에 대해 경로1·경로2·ODE 진단을 모두 수행한다."""
    r = load_run(group)
    df = r.df
    gases = [g for g in CHAMBER_GAS if g in df.columns]
    df = df.assign(Qtot=df[gases].sum(axis=1))

    long_steps = find_steps(df, LONG_GAS, LONG_BAND_S)
    short_steps = find_steps(df, SHORT_GAS, SHORT_BAND_S)

    cols = [PRESSURE, "Qtot", LONG_GAS, SHORT_GAS, "HeliumBPFlow",
            "HeliumBPPressure", "ForeLinePressure", "PlatenRFLoadPower",
            "PlatenDcBias", "SourceRFLoadPower"]
    cols = [c for c in cols if c in df.columns]

    out: dict = {
        "group": group, "date": r.date, "wafer": r.wafer, "exp_key": r.exp_key,
        "n_long_steps": int(long_steps.rise_s.size),
        "n_short_steps": int(short_steps.rise_s.size),
        "n_long_all": long_steps.n_all, "n_short_all": short_steps.n_all,
        "long_dur_med_s": float(np.median(long_steps.dur_s)) if long_steps.dur_s.size else np.nan,
        "short_dur_med_s": float(np.median(short_steps.dur_s)) if short_steps.dur_s.size else np.nan,
    }
    if long_steps.rise_s.size < 10 or short_steps.rise_s.size < 10:
        out["ok"] = False
        return out
    out["ok"] = True

    ens_L = ensemble(df, long_steps.rise_s, cols, k_lo=-3, k_hi=32)
    ens_S = ensemble(df, short_steps.rise_s, cols, k_lo=-3, k_hi=32)

    for tag, ens, ss_win, excl, fitlen, sens in (
        ("long", ens_L, LONG_SS_WIN_S, LONG_EXCL_S, LONG_FITLEN_S, SENS_LONG_EXCL),
        ("short", ens_S, SHORT_SS_WIN_S, SHORT_EXCL_S, SHORT_FITLEN_S, SENS_SHORT_EXCL),
    ):
        # --- 경로 2: 정상상태
        p_ss, p_drift = _plateau(ens, ss_win, PRESSURE)
        q_ss, _ = _plateau(ens, ss_win, "Qtot")
        q_gas, _ = _plateau(ens, ss_win, LONG_GAS if tag == "long" else SHORT_GAS)
        q_he, _ = _plateau(ens, ss_win, "HeliumBPFlow")
        out[f"{tag}_P_ss"] = p_ss
        out[f"{tag}_P_drift"] = p_drift
        out[f"{tag}_Q_tot"] = q_ss
        out[f"{tag}_Q_gasonly"] = q_gas
        out[f"{tag}_S_eff_p2"] = q_ss / p_ss if p_ss else np.nan          # 경로 2 주 산출
        out[f"{tag}_S_eff_p2_gasonly"] = q_gas / p_ss if p_ss else np.nan  # 민감도: 주가스만
        out[f"{tag}_S_eff_p2_withHe"] = (q_ss + q_he) / p_ss if p_ss else np.nan  # 민감도: He 포함
        out[f"{tag}_P_peak"] = float(ens[PRESSURE].max())

        # --- 경로 1: 과도응답
        t_rel = ens["rel_t_s"].values
        p = ens[PRESSURE].values
        f = fit_tau(t_rel, p, excl, fitlen)
        out[f"{tag}_tau_s"] = f.tau_s
        out[f"{tag}_tau_se_s"] = f.tau_se_s
        out[f"{tag}_tau_r2"] = f.r2
        out[f"{tag}_tau_pinf"] = f.p_inf
        out[f"{tag}_tau_n"] = f.n
        out[f"{tag}_tau_ok"] = f.ok
        for e in sens:  # 제외 구간 민감도
            out[f"{tag}_tau_excl{e:.2f}"] = fit_tau(t_rel, p, e, fitlen).tau_s

    # --- 진단: 적분형 ODE 회귀 (공통 V, 스텝별 S). 긴스텝 정렬 앙상블 한 주기 전체 사용
    ens = ens_L[ens_L["rel_t_s"] >= 0.0]
    t_s = ens["rel_t_s"].values
    p = ens[PRESSURE].values
    q = ens["Qtot"].values
    m_long = ens[LONG_GAS].values > ens[SHORT_GAS].values  # 긴 가스 우세 구간
    try:
        f2 = fit_ode_integral(t_s, p, q, masks=[m_long, ~m_long])
        out["ode_V"] = f2.V
        out["ode_S_long"] = float(f2.S[0])
        out["ode_S_short"] = float(f2.S[1])
        out["ode_tau_long_s"] = float(f2.tau_s[0])
        out["ode_tau_short_s"] = float(f2.tau_s[1])
        out["ode_r2"] = f2.r2
        f1 = fit_ode_integral(t_s, p, q)  # 단일 S 모델 (비교용)
        out["ode1_V"] = f1.V
        out["ode1_S"] = float(f1.S[0])
        out["ode1_r2"] = f1.r2
    except np.linalg.LinAlgError:
        out["ode_r2"] = np.nan

    # --- 부수 산출: 단위 판별용 압력 크기 관계 + Phase 2용 He 배면압력
    for ch in ("Pressure", "ForeLinePressure", "HeliumBPPressure", "HeliumBPFlow"):
        if ch in df.columns:
            bosch = df.loc[long_steps.rise_s[0]: long_steps.rise_s[-1], ch]
            out[f"mean_{ch}"] = float(bosch.mean())
            out[f"med_{ch}"] = float(bosch.median())
            out[f"std_{ch}"] = float(bosch.std())
    # --- 가스 종 판별용: 스텝별 평균 바이어스/파워
    for tag, ens_x, win in (("long", ens_L, LONG_SS_WIN_S), ("short", ens_S, SHORT_SS_WIN_S)):
        for ch in ("PlatenRFLoadPower", "PlatenDcBias", "SourceRFLoadPower"):
            if ch in ens_x.columns:
                out[f"{tag}_{ch}"] = _plateau(ens_x, win, ch)[0]
    return out


def main() -> None:
    rows = []
    for i, g in enumerate(list_groups(), 1):
        rows.append(analyse_wafer(g))
        if i % 16 == 0:
            print(f"  ... {i}/96 처리", flush=True)
    df = pd.DataFrame(rows)

    # 89점 측정 유무 표시 (측정 없는 8장 = 컨디셔닝 런 후보, 게이트 산출에는 포함)
    m89 = pd.read_csv(ROOT / "data" / "Si_Oxide_etch_89_points.csv")
    keys = set(m89["experiment_key"].unique())
    df["has_89pt"] = df["exp_key"].isin(keys)

    out = RESULTS / "taskA_seff.parquet"
    df.to_parquet(out, index=False)
    df.to_csv(RESULTS / "taskA_seff.csv", index=False)
    print(f"\n저장: {out}  ({len(df)}행)")
    return df


if __name__ == "__main__":
    main()
