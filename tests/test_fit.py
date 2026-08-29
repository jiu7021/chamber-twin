"""추정 루틴의 해석해 대조 테스트.

합성 데이터는 V·dP/dt = Q − S·P 의 해석해로 생성한다.
단위는 임의(불가지론) — 시간만 s.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.fit import fit_ode_integral, fit_tau, regress_gate


def analytic_step(t, p0, q, s, v):
    """계단 입력에 대한 해석해: P(t) = Q/S + (P0 − Q/S)·exp(−t·S/V)."""
    p_inf = q / s
    return p_inf + (p0 - p_inf) * np.exp(-t * s / v)


def test_fit_tau_recovers_known_tau():
    v, s, q, p0 = 4000.0, 15000.0, 600.0, 0.0600
    tau = v / s  # 0.2667 s
    t = np.arange(0.0, 3.0, 0.02)
    p = analytic_step(t, p0, q, s, v)
    fit = fit_tau(t, p, excl_s=0.0, fitlen_s=3.0)
    assert fit.ok
    assert fit.tau_s == pytest.approx(tau, rel=1e-3)
    assert fit.p_inf == pytest.approx(q / s, rel=1e-3)


def test_fit_tau_excl_window_does_not_bias():
    """제외 구간을 바꿔도 순수 1차계에서는 tau가 동일해야 한다."""
    v, s, q, p0 = 4000.0, 15000.0, 600.0, 0.0600
    t = np.arange(0.0, 3.0, 0.02)
    p = analytic_step(t, p0, q, s, v)
    taus = [fit_tau(t, p, excl_s=e, fitlen_s=1.5).tau_s for e in (0.0, 0.2, 0.4)]
    assert np.allclose(taus, v / s, rtol=1e-3)


def test_ode_integral_single_region():
    v, s, q, p0 = 4000.0, 15000.0, 600.0, 0.0600
    t = np.arange(0.0, 3.0, 0.01)
    p = analytic_step(t, p0, q, s, v)
    qq = np.full_like(t, q)
    fit = fit_ode_integral(t, p, qq)
    assert fit.V == pytest.approx(v, rel=1e-3)
    assert fit.S[0] == pytest.approx(s, rel=1e-3)
    assert fit.tau_s[0] == pytest.approx(v / s, rel=1e-3)
    assert fit.r2 > 0.999


def test_ode_integral_two_regions_common_volume():
    """구간마다 S가 다르고 V는 공통인 경우를 분리 추정할 수 있어야 한다."""
    v, s_a, s_b = 4000.0, 15000.0, 6000.0
    q_a, q_b = 600.0, 300.0
    dt = 0.01
    t_a = np.arange(0.0, 4.5, dt)
    p_a = analytic_step(t_a, 0.050, q_a, s_a, v)
    t_b = np.arange(0.0, 1.5, dt)
    p_b = analytic_step(t_b, p_a[-1], q_b, s_b, v)
    t = np.concatenate([t_a, t_a[-1] + dt + t_b])
    p = np.concatenate([p_a, p_b])
    q = np.concatenate([np.full_like(t_a, q_a), np.full_like(t_b, q_b)])
    mask_a = np.concatenate([np.ones_like(t_a, bool), np.zeros_like(t_b, bool)])
    fit = fit_ode_integral(t, p, q, masks=[mask_a, ~mask_a])
    assert fit.V == pytest.approx(v, rel=2e-3)
    assert fit.S[0] == pytest.approx(s_a, rel=2e-3)
    assert fit.S[1] == pytest.approx(s_b, rel=2e-3)


def test_regress_gate_recovers_volume():
    """1/tau = (Q/P_ss)/V 관계를 만족하는 합성 표본에서 V를 회복해야 한다."""
    rng = np.random.default_rng(0)
    v = 4200.0
    x = rng.uniform(5000, 20000, 200)          # Q/P_ss
    y = x / v + rng.normal(0, 1e-3, x.size)    # 1/tau
    res = regress_gate(x, y)
    assert res.V == pytest.approx(v, rel=0.01)
    assert res.r2_ols > 0.95
    assert res.intercept_contains_zero


def test_regress_gate_flags_inconsistent_data():
    """1/tau가 Q/P_ss와 음의 관계면 게이트가 통과되지 않아야 한다."""
    x = np.array([15000.0, 6000.0] * 50)
    y = np.array([3.57, 4.55] * 50)
    res = regress_gate(x, y)
    assert res.slope_ols < 0
    assert not res.intercept_contains_zero
