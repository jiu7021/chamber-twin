"""Phase 3-1: 진공 챔버 물리 엔진.

지배식
    V·dP/dt = Q_mfc(t) + Q_leak + Q_outgas(t) − S_eff(P, θ)·P

    V        챔버 체적            [m³]
    P        챔버 압력            [Pa]
    Q_*      스루풋               [Pa·m³/s]
    S_eff    유효 배기속도         [m³/s]
    θ        스로틀 밸브 각도      [rad]  ← 실측에 없는 상태변수. 이 엔진이 복원 대상으로 삼는다.

APC(자동압력제어) 루프를 포함한다. Phase 1 실측에서 챔버 압력이 설정값에 서보 고정되고
(변동계수 0.027 %) 상태 정보가 밸브 각도로 이전되는 것을 확인했기 때문에, 이 루프 없이는
실측을 재현할 수 없다.

단위 규약: 내부 계산은 SI 단일계(Pa, m³, m³/s, Pa·m³/s, s, K)만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp

# ---------------------------------------------------------------- 물리 상수 · 물성치

# (표준·규정) 2019 SI 재정의 이후 정의값
BOLTZMANN = 1.380649e-23          # J/K
GAS_CONSTANT = 8.314462618        # J/(mol·K)

# (물성치) 건조 공기: 평균 몰질량, 20 °C 동점도, 유효 분자직경
M_AIR = 0.028964                  # kg/mol
ETA_AIR_293K = 1.813e-5           # Pa·s  (공기 20 °C 점성계수)
D_MOL_AIR = 3.66e-10              # m     (충돌단면 기준 유효 분자직경, 공기 λ≈68 nm @ 101325 Pa 재현)

# (통상범위) 아웃가싱 지수. 금속 α≈1, 폴리머·엘라스토머 α≈0.5.
# 출처: 사용자 제공 명세(Phase 3 사양). 진공공학 표준 문헌의 관용값과 일치하나
# 개별 문헌 인용은 미확인 — reports 에 검증 필요 항목으로 기록한다.
ALPHA_METAL = 1.0
ALPHA_POLYMER = 0.5

# (표준·규정) Knudsen 중간류 반경험식의 보정계수. Knudsen(1909).
# 진공공학 교재에 널리 재수록된 값이나 원문 대조는 미확인 — 검증 필요 항목.
KNUDSEN_Z_A = 2.507
KNUDSEN_Z_B = 3.095


# ---------------------------------------------------------------- 기체운동론


def mean_thermal_speed(molar_mass_kg_mol: float = M_AIR, temperature_k: float = 293.15) -> float:
    """평균 열속도 v̄ = √(8RT/πM).

    Args:
        molar_mass_kg_mol: 몰질량 [kg/mol]
        temperature_k: 온도 [K]

    Returns:
        평균 열속도 [m/s]  (공기 20 °C 에서 약 463 m/s)
    """
    return float(np.sqrt(8.0 * GAS_CONSTANT * temperature_k / (np.pi * molar_mass_kg_mol)))


def mean_free_path(pressure_pa: float, temperature_k: float = 293.15,
                   d_molecule_m: float = D_MOL_AIR) -> float:
    """평균자유행로 λ = k_B·T / (√2·π·d_m²·P).

    Args:
        pressure_pa: 압력 [Pa]
        temperature_k: 온도 [K]
        d_molecule_m: 유효 분자직경 [m]

    Returns:
        평균자유행로 [m]  (공기 20 °C, 101325 Pa 에서 약 6.8e-8 m)
    """
    p = max(float(pressure_pa), 1e-30)
    return float(BOLTZMANN * temperature_k / (np.sqrt(2.0) * np.pi * d_molecule_m ** 2 * p))


def knudsen_number(mean_free_path_m: float, characteristic_length_m: float) -> float:
    """Knudsen 수 Kn = λ/d.

    Kn ≲ 0.01 점성류, 0.01 ≲ Kn ≲ 1 중간류, Kn ≳ 1 분자류.

    Args:
        mean_free_path_m: 평균자유행로 [m]
        characteristic_length_m: 특성 길이(관 직경) [m]

    Returns:
        Knudsen 수 [무차원]
    """
    return float(mean_free_path_m / characteristic_length_m)


def flow_regime(kn: float) -> str:
    """Knudsen 수로 유동영역을 판별한다.

    Args:
        kn: Knudsen 수 [무차원]

    Returns:
        '점성류' | '중간류' | '분자류'
    """
    if kn <= 0.01:
        return "점성류"
    if kn >= 1.0:
        return "분자류"
    return "중간류"


# ---------------------------------------------------------------- 컨덕턴스


def conductance_molecular_tube(d_m: float, l_m: float,
                               molar_mass_kg_mol: float = M_AIR,
                               temperature_k: float = 293.15) -> float:
    """장관(長管) 분자류 컨덕턴스 C = (π/12)·v̄·d³/l.

    공기 20 °C 에서 d, l 을 cm 로 넣으면 C[L/s] = 12.1·d³/l 로 환원된다(대조 테스트 있음).

    Args:
        d_m: 관 내경 [m]
        l_m: 관 길이 [m]
        molar_mass_kg_mol: 몰질량 [kg/mol]
        temperature_k: 온도 [K]

    Returns:
        컨덕턴스 [m³/s]
    """
    vbar = mean_thermal_speed(molar_mass_kg_mol, temperature_k)
    return float(np.pi / 12.0 * vbar * d_m ** 3 / l_m)


def conductance_viscous_tube(d_m: float, l_m: float, p_avg_pa: float,
                             viscosity_pa_s: float = ETA_AIR_293K) -> float:
    """장관 점성류(Poiseuille) 컨덕턴스 C = π·d⁴·P̄ / (128·η·l).

    Args:
        d_m: 관 내경 [m]
        l_m: 관 길이 [m]
        p_avg_pa: 관 양단 평균 압력 [Pa]
        viscosity_pa_s: 점성계수 [Pa·s]

    Returns:
        컨덕턴스 [m³/s]
    """
    return float(np.pi * d_m ** 4 * p_avg_pa / (128.0 * viscosity_pa_s * l_m))


def conductance_tube(d_m: float, l_m: float, p_avg_pa: float,
                     molar_mass_kg_mol: float = M_AIR, temperature_k: float = 293.15,
                     viscosity_pa_s: float = ETA_AIR_293K) -> float:
    """전 영역 관 컨덕턴스 — Knudsen 반경험식으로 점성류·분자류를 연속 결합한다.

        C = C_viscous + Z·C_molecular
        Z = (1 + a·r/λ) / (1 + b·r/λ),  r = d/2,  a = 2.507, b = 3.095

    Z 는 λ → ∞ (분자류)에서 1, λ → 0 (점성류)에서 a/b ≈ 0.810 이 되어 두 극한을 매끄럽게 잇는다.
    중간류에서 C 가 분자류 값 아래로 얕게 내려가는 Knudsen 최소가 자연히 재현된다.

    Args:
        d_m: 관 내경 [m]
        l_m: 관 길이 [m]
        p_avg_pa: 평균 압력 [Pa]
        molar_mass_kg_mol: 몰질량 [kg/mol]
        temperature_k: 온도 [K]
        viscosity_pa_s: 점성계수 [Pa·s]

    Returns:
        컨덕턴스 [m³/s]
    """
    lam = mean_free_path(p_avg_pa, temperature_k)
    x = (d_m / 2.0) / lam
    z = (1.0 + KNUDSEN_Z_A * x) / (1.0 + KNUDSEN_Z_B * x)
    c_visc = conductance_viscous_tube(d_m, l_m, p_avg_pa, viscosity_pa_s)
    c_mol = conductance_molecular_tube(d_m, l_m, molar_mass_kg_mol, temperature_k)
    return float(c_visc + z * c_mol)


def series_pumping_speed(conductance_m3s: float, pump_speed_m3s: float) -> float:
    """직렬 결합 유효 배기속도: 1/S_eff = 1/C + 1/S_pump.

    Args:
        conductance_m3s: 배관·밸브 컨덕턴스 [m³/s]
        pump_speed_m3s: 펌프 배기속도 [m³/s]

    Returns:
        유효 배기속도 [m³/s]
    """
    if conductance_m3s <= 0.0 or pump_speed_m3s <= 0.0:
        return 0.0
    return float(1.0 / (1.0 / conductance_m3s + 1.0 / pump_speed_m3s))


# ---------------------------------------------------------------- 아웃가싱


def outgassing_rate(t_s: float, q1_pa_m3s: float, alpha: float,
                    t_min_s: float = 1.0) -> float:
    """멱함수 아웃가싱 q(t) = q1·t^(−α).

    q1 은 t = 1 s 기준 아웃가싱 스루풋이다. t < t_min 구간에서는 발산을 막기 위해
    t_min 값으로 고정한다(수치 안정용, 물리적 근거 아님).

    Args:
        t_s: 배기 시작 후 경과시간 [s]
        q1_pa_m3s: t = 1 s 에서의 아웃가싱 스루풋 [Pa·m³/s]
        alpha: 감쇠 지수 [무차원]. 금속 ≈ 1.0, 폴리머·엘라스토머 ≈ 0.5
        t_min_s: 하한 시각 [s]

    Returns:
        아웃가싱 스루풋 [Pa·m³/s]
    """
    t = max(float(t_s), t_min_s)
    return float(q1_pa_m3s * t ** (-alpha))


# ---------------------------------------------------------------- 스로틀 밸브


@dataclass(frozen=True)
class ThrottleValve:
    """나비형(butterfly) 스로틀 밸브.

    완전폐쇄(θ = 0)에서 완전개방(θ = π/2)까지 회전하는 원판을 가정한다.
    원판이 유로를 가리는 투영 면적이 A0·cos θ 이므로 개방 면적비는 1 − cos θ 다(기하 유도).
    분자류 오리피스 컨덕턴스는 면적에 비례하므로 C(θ) = C_max·(1 − cos θ) 로 둔다.

    Attributes:
        c_max_m3s: 완전개방 컨덕턴스 [m³/s]
        theta_min_rad: 최소 각도 [rad]
        theta_max_rad: 최대 각도 [rad]
    """

    c_max_m3s: float
    theta_min_rad: float = 0.0
    theta_max_rad: float = np.pi / 2

    def open_fraction(self, theta_rad: float) -> float:
        """개방 면적비 1 − cos θ [무차원, 0~1]."""
        th = float(np.clip(theta_rad, self.theta_min_rad, self.theta_max_rad))
        return float(1.0 - np.cos(th))

    def conductance(self, theta_rad: float) -> float:
        """각도 θ [rad] 에서의 컨덕턴스 [m³/s]."""
        return float(self.c_max_m3s * self.open_fraction(theta_rad))


# ---------------------------------------------------------------- APC 제어기


@dataclass(frozen=True)
class APCController:
    """압력 설정값을 유지하는 PI 제어기 (조작변수 = 스로틀 밸브 각도).

    오차 e = P − P_sp 가 양이면(압력이 높으면) 밸브를 더 열어 배기를 늘린다.

    밸브 각도는 지령값이 아니라 **상태변수**로 다룬다. 실제 스로틀 밸브 액추에이터는
    유한한 응답시간을 가지며, 이를 1차 지연으로 모델링하면 (a) 물리적으로 더 정확하고
    (b) 포화 클리핑이 우변의 미분 불연속을 만들지 않아 적분기가 안정된다.

    적분 와인드업은 지령이 포화되고 오차가 포화 방향일 때 적분기를 정지시켜 방지한다.

    Attributes:
        setpoint_pa: 압력 설정값 [Pa]
        kp: 비례이득 [rad/Pa]
        ki: 적분이득 [rad/(Pa·s)]
        tau_valve_s: 밸브 액추에이터 1차 지연 시정수 [s]
            (가정치) 기본 0.05 s. 실제 APC 밸브 응답은 통상 0.05~0.2 s 범위로 알려져 있으나
            본 데이터셋에는 밸브 채널 자체가 없어 확인 불가. 민감도 확인 대상.
    """

    setpoint_pa: float
    kp: float
    ki: float
    tau_valve_s: float = 0.05
    kaw: float | None = None

    def _kaw(self) -> float:
        """되계산 이득 [1/s]. 기본은 밸브 응답과 같은 속도(1/τ_valve)."""
        return float(1.0 / self.tau_valve_s) if self.kaw is None else float(self.kaw)

    def error(self, p_pa: float) -> float:
        """제어 오차 e = P − P_sp [Pa]."""
        return float(p_pa) - self.setpoint_pa

    def theta_raw(self, p_pa: float, integral: float) -> float:
        """포화 적용 전 PI 출력 [rad]."""
        return float(self.kp * self.error(p_pa) + integral)

    def theta_cmd(self, p_pa: float, integral: float, valve: ThrottleValve) -> float:
        """PI 지령 각도 (포화 적용) [rad]."""
        return float(np.clip(self.theta_raw(p_pa, integral),
                             valve.theta_min_rad, valve.theta_max_rad))

    def dintegral(self, p_pa: float, integral: float, valve: ThrottleValve) -> float:
        """적분항의 시간미분 [rad/s] — 되계산(back-calculation) 와인드업 방지.

            dI/dt = ki·e + kaw·(θ_cmd − θ_raw)

        비포화 구간에서는 θ_cmd = θ_raw 이므로 보정항이 0 이 되어 순수 PI 와 같다.
        포화 구간에서는 보정항이 적분을 되끌어온다. 클리핑이 연속함수이므로
        우변에 점프 불연속이 생기지 않는다 — 조건분기식 와인드업 방지를 쓰면
        dI/dt 에 계단 불연속이 생겨 stiff 적분기가 해당 지점에서 스텝을 반복 기각한다
        (실측: 0.5 s 적분에 우변 호출 760 만 회).
        """
        raw = self.theta_raw(p_pa, integral)
        sat = float(np.clip(raw, valve.theta_min_rad, valve.theta_max_rad))
        return float(self.ki * self.error(p_pa) + self._kaw() * (sat - raw))

    def dtheta(self, p_pa: float, integral: float, theta_rad: float,
               valve: ThrottleValve) -> float:
        """밸브 각도의 시간미분 [rad/s] — 액추에이터 1차 지연."""
        return float((self.theta_cmd(p_pa, integral, valve) - theta_rad) / self.tau_valve_s)


# ---------------------------------------------------------------- 챔버 구성 · 시뮬레이션


@dataclass(frozen=True)
class ChamberConfig:
    """챔버·배기계 구성.

    Attributes:
        volume_m3: 챔버 체적 [m³]
        pump_speed_m3s: 펌프 배기속도 [m³/s]
        valve: 스로틀 밸브
        apc: APC 제어기. None 이면 밸브를 theta_fixed_rad 에 고정한다
        theta_fixed_rad: APC 미사용 시 고정 각도 [rad]. 기본은 완전개방
        temperature_k: 기체 온도 [K]
    """

    volume_m3: float
    pump_speed_m3s: float
    valve: ThrottleValve
    apc: APCController | None = None
    theta_fixed_rad: float | None = None
    temperature_k: float = 293.15

    def theta_default(self) -> float:
        """APC 미사용 시 적용할 밸브 각도 [rad]."""
        if self.theta_fixed_rad is not None:
            return float(self.theta_fixed_rad)
        return float(self.valve.theta_max_rad)


@dataclass
class SimResult:
    """시뮬레이션 결과 (전부 SI).

    Attributes:
        t_s: 시각 [s]
        p_pa: 챔버 압력 [Pa]
        theta_rad: 스로틀 밸브 각도 [rad] — 실측에 없는 복원 대상 변수
        s_eff_m3s: 유효 배기속도 [m³/s]
        q_total_pa_m3s: 총 유입 스루풋 [Pa·m³/s]
    """

    t_s: np.ndarray
    p_pa: np.ndarray
    theta_rad: np.ndarray
    s_eff_m3s: np.ndarray
    q_total_pa_m3s: np.ndarray
    integral: np.ndarray = field(default_factory=lambda: np.empty(0))


def simulate(cfg: ChamberConfig, t_end_s: float, p0_pa: float,
             q_in: Callable[[float], float],
             q_leak_pa_m3s: float = 0.0,
             outgas: Callable[[float], float] | None = None,
             theta0_rad: float | None = None,
             pump_speed_of_t: Callable[[float], float] | None = None,
             c_max_of_t: Callable[[float], float] | None = None,
             n_out: int = 2000,
             rtol: float = 1e-8, atol: float = 1e-12) -> SimResult:
    """V·dP/dt = Q_mfc + Q_leak + Q_outgas − S_eff(P, θ)·P 를 적분한다.

    상태벡터는 [P, I, θ] 다. θ 는 실측에 없는 변수이며 이 엔진의 복원 대상이다.
    압력이 여러 자릿수 변하는 stiff 문제이므로 명시적 오일러를 쓰지 않고
    scipy.integrate.solve_ivp 의 LSODA(자동 stiff 전환)를 사용한다.

    Args:
        cfg: 챔버 구성
        t_end_s: 종료 시각 [s]
        p0_pa: 초기 압력 [Pa]
        q_in: MFC 스루풋 함수 t[s] → [Pa·m³/s]
        q_leak_pa_m3s: 실누설 스루풋 (상수) [Pa·m³/s]
        outgas: 아웃가싱 함수 t[s] → [Pa·m³/s]. None 이면 0
        theta0_rad: 초기 밸브 각도 [rad]. None 이면 APC 사용 시 완전개방의 절반,
            미사용 시 cfg.theta_default()
        pump_speed_of_t: 시변 펌프 배기속도 t[s] → [m³/s]. None 이면 cfg 값 고정.
            TMP 성능저하 고장 주입에 사용한다
        c_max_of_t: 시변 밸브 완전개방 컨덕턴스 t[s] → [m³/s]. None 이면 valve 값 고정.
            스로틀 밸브 마모(θ–C 곡선 변형) 고장 주입에 사용한다
        n_out: 출력 샘플 수
        rtol, atol: 적분기 허용오차

    Returns:
        SimResult
    """
    valve, apc = cfg.valve, cfg.apc

    def q_total(t: float) -> float:
        q = float(q_in(t)) + float(q_leak_pa_m3s)
        if outgas is not None:
            q += float(outgas(t))
        return q

    if apc is None:
        theta0 = cfg.theta_default() if theta0_rad is None else float(theta0_rad)
        i0 = 0.0
    else:
        theta0 = (0.5 * (valve.theta_min_rad + valve.theta_max_rad)
                  if theta0_rad is None else float(theta0_rad))
        i0 = theta0 - apc.kp * apc.error(p0_pa)   # t=0 에서 지령이 theta0 가 되도록

    def s_pump_at(t: float) -> float:
        return cfg.pump_speed_m3s if pump_speed_of_t is None else float(pump_speed_of_t(t))

    def c_at(t: float, theta: float) -> float:
        frac = valve.open_fraction(theta)
        cmax = valve.c_max_m3s if c_max_of_t is None else float(c_max_of_t(t))
        return cmax * frac

    def s_eff_of(t: float, theta: float) -> float:
        return series_pumping_speed(c_at(t, theta), s_pump_at(t))

    def rhs(t: float, y: np.ndarray) -> list[float]:
        p = max(float(y[0]), 0.0)
        integral, theta = float(y[1]), float(y[2])
        dp = (q_total(t) - s_eff_of(t, theta) * p) / cfg.volume_m3
        if apc is None:
            return [dp, 0.0, 0.0]
        return [dp, apc.dintegral(p, integral, valve), apc.dtheta(p, integral, theta, valve)]

    t_eval = np.linspace(0.0, t_end_s, n_out)
    sol = solve_ivp(rhs, (0.0, t_end_s), [float(p0_pa), i0, theta0], method="LSODA",
                    t_eval=t_eval, rtol=rtol, atol=[atol, 1e-9, 1e-9])
    if not sol.success:
        raise RuntimeError(f"적분 실패: {sol.message}")

    p = np.clip(sol.y[0], 0.0, None)
    integ, th = sol.y[1], np.clip(sol.y[2], valve.theta_min_rad, valve.theta_max_rad)
    se = np.array([s_eff_of(tt, thh) for tt, thh in zip(sol.t, th)])
    qt = np.array([q_total(tt) for tt in sol.t])
    return SimResult(t_s=sol.t, p_pa=p, theta_rad=th, s_eff_m3s=se,
                     q_total_pa_m3s=qt, integral=integ)


# ---------------------------------------------------------------- 해석해


def pump_down_time(volume_m3: float, s_eff_m3s: float,
                   p_start_pa: float, p_end_pa: float) -> float:
    """가스부하가 없는 정속 배기 시간 t = (V/S_eff)·ln(P1/P2).

    Args:
        volume_m3: 챔버 체적 [m³]
        s_eff_m3s: 유효 배기속도 [m³/s]
        p_start_pa: 시작 압력 [Pa]
        p_end_pa: 목표 압력 [Pa]

    Returns:
        소요 시간 [s]
    """
    return float(volume_m3 / s_eff_m3s * np.log(p_start_pa / p_end_pa))


def ultimate_pressure(q_total_pa_m3s: float, s_eff_m3s: float) -> float:
    """극한압력 P_ult = Q_total/S_eff.

    Args:
        q_total_pa_m3s: 총 가스부하 [Pa·m³/s]
        s_eff_m3s: 유효 배기속도 [m³/s]

    Returns:
        극한압력 [Pa]
    """
    return float(q_total_pa_m3s / s_eff_m3s)


# ------------------------------------------------- 단위 불가지론 배기속도 서보 (실측 대조용)


@dataclass(frozen=True)
class SpeedServo:
    """유효 배기속도 S 를 직접 조작변수로 삼는 APC 등가 모델.

    실측 대조에서는 스로틀 밸브의 기하(θ–C 곡선)도 단위계도 알 수 없다. 그러나 지배식
        V·dP/dt = Q(t) − S·P
    는 (V, Q, P, S) 가 서로 정합적인 단위계이기만 하면 형태가 보존된다. 따라서 밸브 각도를
    거치지 않고 S 를 직접 서보 변수로 두면 **단위를 가정하지 않고** APC 를 모델링할 수 있다.

    S = clip(S0 + kp·(P − P_sp) + I,  s_min, s_max)
    dI/dt = ki·(P − P_sp) + kaw·(clip − raw)      ← 되계산 와인드업 방지 (연속)

    Attributes:
        s0: 기준 배기속도 [Q단위/P단위]
        kp: 비례이득 [S단위/P단위]
        ki: 적분이득 [S단위/(P단위·s)]
        s_min, s_max: 배기속도 포화 한계 [Q단위/P단위]
        tau_s: 액추에이터 1차 지연 시정수 [s]
        kaw: 되계산 이득 [1/s]. None 이면 1/tau_s
    """

    s0: float
    kp: float
    ki: float
    s_min: float = 0.0
    s_max: float = np.inf
    tau_s: float = 0.05
    kaw: float | None = None

    def _kaw(self) -> float:
        return float(1.0 / self.tau_s) if self.kaw is None else float(self.kaw)

    def s_raw(self, p: float, integral: float, p_sp: float) -> float:
        """포화 전 지령 배기속도. 비례항은 오차 (p − p_sp) 에 작용한다."""
        return float(self.s0 + self.kp * (p - p_sp) + integral)

    def s_cmd(self, p: float, integral: float, p_sp: float) -> float:
        """포화 후 지령 배기속도."""
        return float(np.clip(self.s_raw(p, integral, p_sp), self.s_min, self.s_max))

    def dintegral(self, p: float, integral: float, p_sp: float) -> float:
        """적분항 시간미분 [S단위/s]."""
        raw = self.s_raw(p, integral, p_sp)
        sat = float(np.clip(raw, self.s_min, self.s_max))
        return float(self.ki * (p - p_sp) + self._kaw() * (sat - raw))

    def ds(self, p: float, integral: float, s: float, p_sp: float) -> float:
        """실제 배기속도의 시간미분 [S단위/s] — 액추에이터 1차 지연."""
        return float((self.s_cmd(p, integral, p_sp) - s) / self.tau_s)


def simulate_speed_servo(volume: float, q_of_t: Callable[[float], float],
                         t_eval: np.ndarray, p0: float,
                         servo: SpeedServo | None = None,
                         p_sp_of_t: Callable[[float], float] | None = None,
                         s_fixed: float | None = None,
                         rtol: float = 1e-8, atol: float = 1e-12) -> SimResult:
    """V·dP/dt = Q(t) − S·P 를 단위 불가지론으로 적분한다.

    servo 가 주어지면 S 를 PI 서보로 제어하고(APC 등가), s_fixed 가 주어지면 S 를 상수로 둔다.
    두 모드를 나란히 돌려 "APC 를 넣어야 실측이 재현되는가"를 검정하는 것이 목적이다.

    Args:
        volume: 챔버 체적 [Q단위·s/P단위]
        q_of_t: 유입 스루풋 함수 t[s] → [Q단위]
        t_eval: 출력 시각 배열 [s]
        p0: 초기 압력 [P단위]
        servo: 배기속도 서보. None 이면 s_fixed 필요
        p_sp_of_t: 압력 설정값 함수 t[s] → [P단위]. servo 사용 시 필요
        s_fixed: 고정 배기속도 [Q단위/P단위]
        rtol, atol: 적분기 허용오차

    Returns:
        SimResult (theta_rad 는 사용하지 않으므로 NaN 으로 채움)
    """
    if servo is None and s_fixed is None:
        raise ValueError("servo 또는 s_fixed 중 하나는 필요하다")

    def rhs(t: float, y: np.ndarray) -> list[float]:
        p = max(float(y[0]), 0.0)
        if servo is None:
            return [(q_of_t(t) - float(s_fixed) * p) / volume, 0.0, 0.0]
        integral, s = float(y[1]), float(y[2])
        p_sp = float(p_sp_of_t(t))
        return [(q_of_t(t) - s * p) / volume,
                servo.dintegral(p, integral, p_sp),
                servo.ds(p, integral, s, p_sp)]

    if servo is None:
        y0 = [float(p0), 0.0, 0.0]
    else:
        y0 = [float(p0), 0.0, servo.s0]

    sol = solve_ivp(rhs, (float(t_eval[0]), float(t_eval[-1])), y0, method="LSODA",
                    t_eval=t_eval, rtol=rtol, atol=[atol, 1e-9, 1e-9])
    if not sol.success:
        raise RuntimeError(f"적분 실패: {sol.message}")
    p = np.clip(sol.y[0], 0.0, None)
    s = np.full_like(p, float(s_fixed)) if servo is None else sol.y[2]
    return SimResult(t_s=sol.t, p_pa=p, theta_rad=np.full_like(p, np.nan),
                     s_eff_m3s=s, q_total_pa_m3s=np.array([q_of_t(tt) for tt in sol.t]),
                     integral=sol.y[1])
