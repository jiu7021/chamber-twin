"""배기 모델 파라미터 추정 루틴.

모델: V·dP/dt = Q_in(t) − S_eff·P(t)
      τ = V/S_eff,  정상상태 P_ss = Q_in/S_eff

단위 불가지론: 압력 P와 유량 Q의 단위는 미확정이므로 아래 함수들은 단위를 가정하지 않는다.
그 결과 V는 [Q단위 / P단위 × s]의 혼합 단위로 나온다. 시간만 s로 확정.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit


# ---------------------------------------------------------------- 경로 1: 과도응답


def exp_model(t: np.ndarray, p_inf: float, amp: float, tau: float) -> np.ndarray:
    """1차 지연 응답 P(t) = P_inf + amp·exp(−t/tau).

    Args:
        t: 스텝 시작 기준 상대시각, 단위 s
        p_inf: 종값 (P 원시 단위)
        amp: 초기 편차 P_0 − P_inf (P 원시 단위)
        tau: 시정수, 단위 s

    Returns:
        P(t) (P 원시 단위)
    """
    return p_inf + amp * np.exp(-t / tau)


@dataclass(frozen=True)
class TauFit:
    """지수 피팅 결과.

    Attributes:
        tau_s: 시정수, 단위 s
        tau_se_s: tau의 표준오차, 단위 s
        p_inf: 종값 (P 원시 단위)
        amp: 초기 편차 (P 원시 단위)
        r2: 결정계수
        n: 사용 점 개수
        ok: 수렴 여부
    """

    tau_s: float
    tau_se_s: float
    p_inf: float
    amp: float
    r2: float
    n: int
    ok: bool


def fit_tau(t_rel: np.ndarray, p: np.ndarray, excl_s: float, fitlen_s: float) -> TauFit:
    """스텝 응답에 1차 지연 모델을 피팅해 시정수를 구한다.

    Args:
        t_rel: 스텝 상승에지 기준 상대시각, 단위 s
        p: 압력 (원시 단위)
        excl_s: 전환 직후 제외 구간 길이, 단위 s (밸브·MFC 응답 지연 배제용)
        fitlen_s: 제외 구간 이후 사용할 창 길이, 단위 s

    Returns:
        TauFit
    """
    m = (t_rel >= excl_s) & (t_rel <= excl_s + fitlen_s)
    tt, pp = t_rel[m] - excl_s, p[m]
    if len(tt) < 4:
        return TauFit(np.nan, np.nan, np.nan, np.nan, np.nan, len(tt), False)
    span = float(np.ptp(pp))
    p0 = [float(pp[-1]), float(pp[0] - pp[-1]), 0.3]
    try:
        popt, pcov = curve_fit(
            exp_model, tt, pp, p0=p0, maxfev=20000,
            bounds=([pp.min() - span, -10 * span - 1e-9, 1e-3],
                    [pp.max() + span, 10 * span + 1e-9, 50.0]),
        )
    except (RuntimeError, ValueError):
        return TauFit(np.nan, np.nan, np.nan, np.nan, np.nan, len(tt), False)
    resid = pp - exp_model(tt, *popt)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((pp - pp.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    se = float(np.sqrt(np.diag(pcov))[2]) if np.all(np.isfinite(pcov)) else np.nan
    return TauFit(float(popt[2]), se, float(popt[0]), float(popt[1]), r2, len(tt), True)


# ------------------------------------------------- 적분형 ODE 회귀 (미분 없이 V, S 동시 추정)


@dataclass(frozen=True)
class OdeFit:
    """적분형 선형회귀로 얻은 배기 모델 파라미터.

    P(t) − P(t0) = a·∫Q dt − Σ_j b_j·∫P·1_j dt
      a = 1/V,  b_j = S_j/V = 1/τ_j

    Attributes:
        a: 1/V  (단위 P/(Q·s))
        b: 구간별 S_j/V = 1/τ_j, 단위 1/s
        V: 1/a (혼합 단위 Q·s/P)
        S: 구간별 S_j = b_j/a (단위 Q/P)
        tau_s: 구간별 τ_j = 1/b_j, 단위 s
        r2: 결정계수
        n: 사용 점 개수
    """

    a: float
    b: np.ndarray
    V: float
    S: np.ndarray
    tau_s: np.ndarray
    r2: float
    n: int


def fit_ode_integral(
    t_s: np.ndarray, p: np.ndarray, q: np.ndarray, masks: list[np.ndarray] | None = None
) -> OdeFit:
    """적분형으로 V·dP/dt = Q − S·P 를 선형 최소제곱 추정한다.

    미분 대신 누적적분을 쓰므로 압력 양자화 잡음에 훨씬 둔감하다.
    masks를 주면 구간별로 S를 다르게(공통 V) 추정한다.

    Args:
        t_s: 시각, 단위 s (등간격일 필요 없음)
        p: 압력 (원시 단위)
        q: 유입 유량 (원시 단위)
        masks: 구간 지시자 불리언 배열 목록. None이면 전체 단일 S.

    Returns:
        OdeFit
    """
    if masks is None:
        masks = [np.ones_like(t_s, dtype=bool)]

    def cumtrap(y: np.ndarray) -> np.ndarray:
        out = np.zeros_like(y, dtype=float)
        out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t_s))
        return out

    y = p - p[0]
    cols = [cumtrap(q)]
    for mk in masks:
        cols.append(-cumtrap(p * mk.astype(float)))
    X = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    a = float(coef[0])
    b = np.asarray(coef[1:], dtype=float)
    pred = X @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        V = 1.0 / a if a != 0 else np.nan
        S = b / a if a != 0 else np.full_like(b, np.nan)
        tau = 1.0 / b
    return OdeFit(a=a, b=b, V=float(V), S=S, tau_s=tau, r2=r2, n=len(t_s))


# ---------------------------------------------------------------- 원점통과 회귀 (Phase 1 게이트)


@dataclass(frozen=True)
class RegResult:
    """게이트용 회귀 결과.

    Attributes:
        slope_origin: 원점통과 회귀 기울기 (= 1/V)
        slope_origin_se: 그 표준오차
        V: 1/slope_origin (혼합 단위)
        r2_origin_uncentered: 원점통과 회귀의 비중심 결정계수
        slope_ols / intercept: 절편 포함 OLS 결과
        intercept_ci: 절편의 95% 신뢰구간
        intercept_contains_zero: 절편 CI가 0을 포함하는지
        r2_ols: 절편 포함 OLS의 표준 결정계수
        n: 표본 수
    """

    slope_origin: float
    slope_origin_se: float
    V: float
    r2_origin_uncentered: float
    slope_ols: float
    intercept: float
    intercept_se: float
    intercept_ci: tuple[float, float]
    intercept_contains_zero: bool
    r2_ols: float
    n: int


def regress_gate(x: np.ndarray, y: np.ndarray) -> RegResult:
    """x = Q/P_ss, y = 1/τ 에 대해 원점통과 회귀와 절편 포함 OLS를 모두 수행한다.

    모델 근거: 1/τ = S_eff/V = (Q/P_ss)/V 이므로 기울기의 역수가 챔버 체적 V.

    Args:
        x: Q/P_ss (단위 Q/P)
        y: 1/τ, 단위 1/s

    Returns:
        RegResult
    """
    from scipy import stats

    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)

    sxx = float(np.sum(x * x))
    slope0 = float(np.sum(x * y) / sxx)
    res0 = y - slope0 * x
    dof0 = max(n - 1, 1)
    s2 = float(np.sum(res0**2) / dof0)
    slope0_se = float(np.sqrt(s2 / sxx))
    r2_unc = 1.0 - float(np.sum(res0**2)) / float(np.sum(y * y))

    lr = stats.linregress(x, y)
    tcrit = float(stats.t.ppf(0.975, max(n - 2, 1)))
    lo = lr.intercept - tcrit * lr.intercept_stderr
    hi = lr.intercept + tcrit * lr.intercept_stderr

    return RegResult(
        slope_origin=slope0,
        slope_origin_se=slope0_se,
        V=1.0 / slope0 if slope0 != 0 else np.nan,
        r2_origin_uncentered=r2_unc,
        slope_ols=float(lr.slope),
        intercept=float(lr.intercept),
        intercept_se=float(lr.intercept_stderr),
        intercept_ci=(float(lo), float(hi)),
        intercept_contains_zero=bool(lo <= 0.0 <= hi),
        r2_ols=float(lr.rvalue**2),
        n=n,
    )
