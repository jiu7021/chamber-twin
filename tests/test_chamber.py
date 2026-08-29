"""Phase 3-2: 물리 엔진 해석해 대조 검증.

구현(physics/chamber.py)보다 먼저 작성한 테스트다. 명세의 검증 항목:
  1. 정속 배기      t = (V/S_eff)·ln(P1/P2)          오차 1 % 이내
  2. 정상상태       유량 5단계 스윕에서 P = Q/S_eff   선형성 R² > 0.99
  3. 극한압력       P_ult = Q_total/S_eff
  4. 분자류 컨덕턴스 C[L/s] = 12.1·d³/l (공기 20 °C, d·l 단위 cm)
  5. 단위 환산 왕복  (tests/test_units.py 에 별도)

추가: 점성류 컨덕턴스, 영역 블렌딩 연속성, 아웃가싱 형태, APC 제어 루프.

단위: 전부 SI (Pa, m³, m³/s, Pa·m³/s, s, K).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.chamber import (  # noqa: E402
    APCController, ChamberConfig, ThrottleValve, conductance_molecular_tube,
    conductance_tube, conductance_viscous_tube, knudsen_number, mean_free_path,
    mean_thermal_speed, outgassing_rate, pump_down_time, series_pumping_speed,
    simulate,
)

# 공기 기준값 (물성치): 몰질량 0.028964 kg/mol, 20 °C = 293.15 K
M_AIR, T_ROOM = 0.028964, 293.15


# ---------------------------------------------------------------- 1. 정속 배기


def test_pumpdown_matches_analytic_within_1pct():
    """가스부하 없는 배기: P(t) = P0·exp(−S·t/V), t = (V/S)·ln(P1/P2)."""
    cfg = ChamberConfig(volume_m3=0.050, pump_speed_m3s=0.200,
                        valve=ThrottleValve(c_max_m3s=1e9), apc=None)
    p1, p2 = 1000.0, 10.0                      # Pa
    t_analytic = pump_down_time(cfg.volume_m3, 0.200, p1, p2)
    assert t_analytic == pytest.approx(0.050 / 0.200 * np.log(p1 / p2), rel=1e-12)

    sol = simulate(cfg, t_end_s=t_analytic * 1.5, p0_pa=p1,
                   q_in=lambda t: 0.0, q_leak_pa_m3s=0.0, outgas=None)
    # 수치해가 P2 에 도달하는 시각을 보간으로 찾는다
    idx = np.argmax(sol.p_pa <= p2)
    t_num = np.interp(np.log(p2), np.log(sol.p_pa[idx - 1:idx + 1][::-1]),
                      sol.t_s[idx - 1:idx + 1][::-1])
    assert abs(t_num - t_analytic) / t_analytic < 0.01


def test_pumpdown_decade_times_are_equal():
    """1차계이므로 10배 감압에 걸리는 시간은 압력 구간과 무관하게 일정해야 한다."""
    v, s = 0.050, 0.200
    t1 = pump_down_time(v, s, 1000.0, 100.0)
    t2 = pump_down_time(v, s, 100.0, 10.0)
    t3 = pump_down_time(v, s, 10.0, 1.0)
    assert t1 == pytest.approx(t2, rel=1e-12) == pytest.approx(t3, rel=1e-12)


# ---------------------------------------------------------------- 2. 정상상태 선형성


def test_steady_state_linear_in_flow():
    """유량 5단계 스윕에서 P_ss = Q/S_eff 선형성 R² > 0.99."""
    cfg = ChamberConfig(volume_m3=0.050, pump_speed_m3s=0.200,
                        valve=ThrottleValve(c_max_m3s=1e9), apc=None)
    q_levels = np.array([0.2, 0.4, 0.6, 0.8, 1.0])       # Pa·m³/s
    p_ss = []
    for q in q_levels:
        sol = simulate(cfg, t_end_s=20.0, p0_pa=1.0,
                       q_in=lambda t, q=q: q, q_leak_pa_m3s=0.0, outgas=None)
        p_ss.append(sol.p_pa[-1])
    p_ss = np.array(p_ss)

    slope, intercept = np.polyfit(q_levels, p_ss, 1)
    pred = slope * q_levels + intercept
    r2 = 1 - np.sum((p_ss - pred) ** 2) / np.sum((p_ss - p_ss.mean()) ** 2)
    assert r2 > 0.99
    # 기울기는 1/S_eff 여야 한다
    assert slope == pytest.approx(1.0 / 0.200, rel=1e-3)
    assert p_ss[-1] == pytest.approx(q_levels[-1] / 0.200, rel=1e-3)


# ---------------------------------------------------------------- 3. 극한압력


def test_ultimate_pressure_from_leak_and_outgassing():
    """P_ult = Q_total/S_eff (누설 + 아웃가싱이 상수인 경우)."""
    s = 0.150
    cfg = ChamberConfig(volume_m3=0.050, pump_speed_m3s=s,
                        valve=ThrottleValve(c_max_m3s=1e9), apc=None)
    q_leak = 3.0e-3                                       # Pa·m³/s
    sol = simulate(cfg, t_end_s=30.0, p0_pa=100.0, q_in=lambda t: 0.0,
                   q_leak_pa_m3s=q_leak, outgas=None)
    assert sol.p_pa[-1] == pytest.approx(q_leak / s, rel=1e-3)


def test_series_pumping_speed():
    """직렬 결합 1/S_eff = 1/C + 1/S_pump."""
    assert series_pumping_speed(1.0, 1.0) == pytest.approx(0.5)
    assert series_pumping_speed(1e12, 0.2) == pytest.approx(0.2, rel=1e-6)
    assert series_pumping_speed(0.0, 0.2) == pytest.approx(0.0)


# ---------------------------------------------------------------- 4. 분자류 컨덕턴스


def test_molecular_conductance_matches_12p1_rule():
    """공기 20 °C 장관(長管) 분자류: C[L/s] = 12.1·d³/l (d, l 단위 cm)."""
    for d_cm, l_cm in ((1.0, 1.0), (2.0, 10.0), (5.0, 100.0), (10.0, 50.0)):
        c_si = conductance_molecular_tube(d_cm * 1e-2, l_cm * 1e-2, M_AIR, T_ROOM)
        c_lps = c_si * 1e3                                # m³/s → L/s
        expected = 12.1 * d_cm ** 3 / l_cm
        assert c_lps == pytest.approx(expected, rel=0.01), f"d={d_cm} l={l_cm}"


def test_mean_thermal_speed_air():
    """공기 20 °C 평균 열속도 ≈ 463 m/s (표준 진공공학 값)."""
    assert mean_thermal_speed(M_AIR, T_ROOM) == pytest.approx(463.0, rel=0.01)


def test_molecular_conductance_scaling():
    """분자류는 d³/l 스케일링을 따르고 압력에 무관해야 한다."""
    c1 = conductance_molecular_tube(0.01, 0.10, M_AIR, T_ROOM)
    c2 = conductance_molecular_tube(0.02, 0.10, M_AIR, T_ROOM)
    assert c2 / c1 == pytest.approx(8.0, rel=1e-9)        # 2³
    c3 = conductance_molecular_tube(0.01, 0.20, M_AIR, T_ROOM)
    assert c1 / c3 == pytest.approx(2.0, rel=1e-9)


# ---------------------------------------------------------------- 점성류 · 영역 판별


def test_viscous_conductance_poiseuille_scaling():
    """점성류(Poiseuille): C ∝ d⁴·P̄/(η·l)."""
    c1 = conductance_viscous_tube(0.01, 0.10, 1000.0)
    c2 = conductance_viscous_tube(0.02, 0.10, 1000.0)
    assert c2 / c1 == pytest.approx(16.0, rel=1e-9)       # 2⁴
    c3 = conductance_viscous_tube(0.01, 0.10, 2000.0)
    assert c3 / c1 == pytest.approx(2.0, rel=1e-9)        # P̄ 비례


def test_knudsen_regime_boundaries():
    """Kn ≲ 0.01 점성류, 0.01~1 중간류, Kn ≳ 1 분자류."""
    d = 0.05                                              # m
    lam_hi = mean_free_path(1e-3, T_ROOM)                 # 저압 → 긴 평균자유행로
    lam_lo = mean_free_path(1e5, T_ROOM)                  # 대기압 → 짧음
    assert knudsen_number(lam_hi, d) > 1.0
    assert knudsen_number(lam_lo, d) < 0.01


def test_conductance_blend_is_continuous_and_bounded():
    """전 압력 구간에서 연속이고, 양 극한에서 각 영역 해에 수렴해야 한다."""
    d, l = 0.05, 0.50
    p = np.logspace(-4, 5, 400)                           # Pa
    c = np.array([conductance_tube(d, l, pp, M_AIR, T_ROOM) for pp in p])
    assert np.all(np.isfinite(c)) and np.all(c > 0)
    # 상대 변화가 인접 점 사이에서 급변하지 않는다 (연속성)
    rel_jump = np.abs(np.diff(np.log(c))) / np.abs(np.diff(np.log(p)))
    assert rel_jump.max() < 1.5
    # 저압 극한 → 분자류 해
    c_mol = conductance_molecular_tube(d, l, M_AIR, T_ROOM)
    assert c[0] == pytest.approx(c_mol, rel=0.05)
    # 고압에서는 점성류가 지배해 분자류 해보다 훨씬 커야 한다
    assert c[-1] > 10 * c_mol


def test_knudsen_minimum_exists_and_is_shallow():
    """중간류에서 컨덕턴스가 분자류 값 아래로 얕게 내려가는 Knudsen 최소가 나타나야 한다.

    이는 수치 오류가 아니라 실재하는 현상이다(Knudsen 1909). 단조 증가를 가정하면 안 된다.
    """
    d, l = 0.05, 0.50
    p = np.logspace(-4, 5, 400)
    c = np.array([conductance_tube(d, l, pp, M_AIR, T_ROOM) for pp in p])
    c_mol = conductance_molecular_tube(d, l, M_AIR, T_ROOM)
    i_min = int(np.argmin(c))
    assert 0 < i_min < len(c) - 1                      # 내부에 최소가 존재
    dip = 1.0 - c[i_min] / c_mol
    assert 0.0 < dip < 0.30                            # 얕다 (분자류 값의 30 % 이내)
    # 최소는 중간류 영역(Kn ~ 1 부근)에서 발생해야 한다
    kn_at_min = knudsen_number(mean_free_path(p[i_min], T_ROOM), d)
    assert 0.01 < kn_at_min < 100.0


# ---------------------------------------------------------------- 아웃가싱


def test_outgassing_power_law_shape():
    """q(t) = q1·t^(−α). α=1 금속, α=0.5 폴리머/엘라스토머."""
    q1 = 1e-5
    assert outgassing_rate(1.0, q1, 1.0) == pytest.approx(q1)
    assert outgassing_rate(10.0, q1, 1.0) == pytest.approx(q1 / 10.0)
    assert outgassing_rate(100.0, q1, 0.5) == pytest.approx(q1 / 10.0)
    # t → 0 에서 발산하지 않도록 하한이 걸려 있어야 한다
    assert np.isfinite(outgassing_rate(0.0, q1, 1.0))


def test_outgassing_decade_ratio_identifies_alpha():
    """10배 시간 경과 시 감소비가 10^(−α) → RoR 진단의 근거."""
    q1 = 1e-5
    for alpha in (0.5, 1.0):
        r = outgassing_rate(1000.0, q1, alpha) / outgassing_rate(100.0, q1, alpha)
        assert r == pytest.approx(10.0 ** (-alpha), rel=1e-9)


# ---------------------------------------------------------------- 스로틀 밸브


def test_valve_conductance_monotonic_and_bounded():
    """밸브 컨덕턴스는 각도에 대해 단조 증가하고 [0, c_max] 안에 있어야 한다."""
    v = ThrottleValve(c_max_m3s=0.5)
    th = np.linspace(0.0, np.pi / 2, 50)
    c = np.array([v.conductance(t) for t in th])
    assert np.all(np.diff(c) >= -1e-15)
    assert c[0] == pytest.approx(0.0, abs=1e-12)
    assert c[-1] == pytest.approx(0.5, rel=1e-9)
    assert np.all((c >= 0.0) & (c <= 0.5 + 1e-12))


def test_valve_open_area_geometry():
    """나비형 디스크의 개방 면적비 = 1 − cos θ (θ: 완전폐쇄 기준 회전각)."""
    v = ThrottleValve(c_max_m3s=1.0)
    assert v.open_fraction(0.0) == pytest.approx(0.0)
    assert v.open_fraction(np.pi / 3) == pytest.approx(1 - np.cos(np.pi / 3))
    assert v.open_fraction(np.pi / 2) == pytest.approx(1.0)


# ---------------------------------------------------------------- APC 제어 루프


def test_apc_holds_setpoint():
    """APC 가 있으면 정상상태 압력이 설정값에 수렴해야 한다 (실측이 요구한 기능)."""
    sp = 5.33                                             # Pa (= 40 mTorr 등가, 검증용 임의값)
    cfg = ChamberConfig(volume_m3=0.050, pump_speed_m3s=0.200,
                        valve=ThrottleValve(c_max_m3s=0.400),
                        apc=APCController(setpoint_pa=sp, kp=2.0, ki=8.0))
    sol = simulate(cfg, t_end_s=60.0, p0_pa=1.0, q_in=lambda t: 0.5,
                   q_leak_pa_m3s=0.0, outgas=None)
    assert sol.p_pa[-1] == pytest.approx(sp, rel=0.01)
    assert 0.0 < sol.theta_rad[-1] < np.pi / 2           # 밸브가 포화되지 않았다


def test_apc_absorbs_disturbance_into_valve_angle():
    """누설을 주입하면 압력은 설정값을 유지하고 밸브 각도가 움직인다.

    이것이 Phase 1 에서 실측으로 확인한 현상 — 상태 정보가 제어변수(압력)가 아니라
    조작변수(밸브 각도)로 이전되는 구조 — 의 재현이다.
    """
    sp = 5.33
    def run(q_leak):
        cfg = ChamberConfig(volume_m3=0.050, pump_speed_m3s=0.200,
                            valve=ThrottleValve(c_max_m3s=0.400),
                            apc=APCController(setpoint_pa=sp, kp=2.0, ki=8.0))
        return simulate(cfg, t_end_s=80.0, p0_pa=sp, q_in=lambda t: 0.5,
                        q_leak_pa_m3s=q_leak, outgas=None)

    a, b = run(0.0), run(0.10)
    assert a.p_pa[-1] == pytest.approx(sp, rel=0.01)
    assert b.p_pa[-1] == pytest.approx(sp, rel=0.01)      # 압력은 변하지 않는다
    assert b.theta_rad[-1] > a.theta_rad[-1] * 1.02       # 밸브는 더 열린다
    # 압력 변화율보다 밸브 각도 변화율이 훨씬 크다 (정보가 조작변수에 실린다)
    d_p = abs(b.p_pa[-1] - a.p_pa[-1]) / a.p_pa[-1]
    d_th = abs(b.theta_rad[-1] - a.theta_rad[-1]) / a.theta_rad[-1]
    assert d_th > 10 * d_p


def test_apc_off_lets_pressure_move():
    """APC 를 끄면 같은 누설이 압력을 움직인다 (대조군)."""
    cfg_kw = dict(volume_m3=0.050, pump_speed_m3s=0.200,
                  valve=ThrottleValve(c_max_m3s=0.400), apc=None)
    a = simulate(ChamberConfig(**cfg_kw), t_end_s=60.0, p0_pa=1.0,
                 q_in=lambda t: 0.5, q_leak_pa_m3s=0.0, outgas=None)
    b = simulate(ChamberConfig(**cfg_kw), t_end_s=60.0, p0_pa=1.0,
                 q_in=lambda t: 0.5, q_leak_pa_m3s=0.10, outgas=None)
    assert b.p_pa[-1] > a.p_pa[-1] * 1.1


# ---------------------------------------------------------------- 적분기 건전성


def test_solver_is_stiff_capable_not_explicit_euler():
    """압력이 여러 자릿수 변하는 stiff 문제에서 해가 발산하지 않아야 한다."""
    cfg = ChamberConfig(volume_m3=0.020, pump_speed_m3s=0.500,
                        valve=ThrottleValve(c_max_m3s=1e9), apc=None)
    sol = simulate(cfg, t_end_s=5.0, p0_pa=1.0e5, q_in=lambda t: 0.0,
                   q_leak_pa_m3s=1e-4, outgas=None)
    assert np.all(np.isfinite(sol.p_pa))
    assert np.all(sol.p_pa > 0)                           # 물리적으로 음압 금지
    assert sol.p_pa[-1] < 1.0                             # 5자릿수 이상 감압
