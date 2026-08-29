"""챔버 디지털 트윈을 Modbus TCP 슬레이브로 노출한다.

Hardware-in-the-Loop 구성에서 이 프로세스가 **플랜트**를 맡는다.
제어(APC PI)는 OpenPLC 가 마스터로 붙어 수행하고, 여기서는 물리만 돈다.

    OpenPLC (마스터) ──Modbus TCP:5020──► 이 프로세스 (슬레이브, 챔버 물리)

레지스터 맵은 plc/modbus_map.md 가 규약이다. 이 파일은 그 규약의 구현이다.

실행:
    python plc/modbus_server.py --port 5020
    python plc/modbus_server.py --port 5020 --local-apc   # PLC 없이 단독 시험

단위: 내부는 SI 단일계. Modbus 경계에서만 mTorr / L/s 로 환산한다.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from physics.chamber import (
    APCController, ChamberConfig, ThrottleValve, outgassing_rate,
    series_pumping_speed,
)
from physics.diagnostics import classify, estimate_ror
from physics.units import m3s_to_lps, pa_to_mtorr, mtorr_to_pa

log = logging.getLogger("twin")

# ---------------------------------------------------------------- 스케일 (modbus_map.md §1)
S_P100, S_P10, S_DEG100, S_PCT100 = 100.0, 10.0, 100.0, 100.0
S_LPS10, S_Q1E4, S_KN1E4, S_Q1E6, S_K1E3 = 10.0, 1e4, 1e4, 1e6, 1e3

U16_MAX, INVALID_U16 = 65535, 65535


def u16(x: float) -> int:
    """실수를 부호 없는 16비트로 클리핑 변환한다."""
    if not math.isfinite(x):
        return INVALID_U16
    return int(min(max(round(x), 0), U16_MAX))


def i16(x: float) -> int:
    """실수를 부호 있는 16비트(2의 보수)로 변환한다."""
    if not math.isfinite(x):
        return 32767
    v = int(min(max(round(x), -32768), 32767))
    return v + 65536 if v < 0 else v


def from_i16(v: int) -> int:
    """레지스터값을 부호 있는 정수로 되돌린다."""
    return v - 65536 if v >= 32768 else v


def u32(x: float) -> tuple[int, int]:
    """U32 를 (하위워드, 상위워드) 로 분해한다 (LSW first)."""
    v = int(min(max(round(x), 0), 0xFFFFFFFF))
    return v & 0xFFFF, (v >> 16) & 0xFFFF


# ---------------------------------------------------------------- 플랜트


@dataclass
class Plant:
    """챔버 플랜트 + RoR 시퀀서 + 진단 추정기.

    Attributes:
        cfg: 챔버 구성 (SI)
        dt_s: 물리 적분 스텝 [s]
    """

    cfg: ChamberConfig
    dt_s: float = 0.01

    # 상태 (SI)
    t: float = 0.0
    p: float = 0.0
    theta: float = 0.0
    integral: float = 0.0

    # 지령 (PLC 가 쓴다)
    sp_pa: float = field(default_factory=lambda: mtorr_to_pa(40.0))
    q_mfc: float = 1.0
    cmd_theta: float | None = None      # None 이면 내부 APC 사용
    auto: bool = True
    gate_closed: bool = False
    process_run: bool = True

    # 고장 주입
    q_leak: float = 0.0
    q1: float = 0.0
    alpha: float = 1.0
    pump_derate: float = 1.0
    valve_wear: float = 1.0
    mfc_offset: float = 0.0
    t_outgas0: float = 0.0

    # RoR
    ror_run: bool = False
    ror_done: bool = False
    ror_t0: float = 0.0
    ror_dur: float = 60.0
    ror_samples: list = field(default_factory=list)
    est_qleak: float = float("nan")
    est_q1: float = float("nan")
    est_alpha: float = float("nan")

    # 알람 임계
    alm_p_hi: float = field(default_factory=lambda: mtorr_to_pa(44.0))
    alm_p_lo: float = field(default_factory=lambda: mtorr_to_pa(36.0))
    alm_valve_hi: float = math.radians(45.0)
    alm_qleak_hi: float = 5e-3

    theta_base: float = 0.0
    est_verdict: str = "정상"
    gauge_quant_rel: float = 0.0025      # 압력 게이지 상대 분해능 (실측 0.236 % 에 맞춤)

    def __post_init__(self) -> None:
        self.reset()

    # ---------------- 물리
    @property
    def s_pump(self) -> float:
        return self.cfg.pump_speed_m3s * self.pump_derate

    @property
    def c_max(self) -> float:
        return self.cfg.valve.c_max_m3s * self.valve_wear

    def reset(self) -> None:
        self.t = 0.0
        self.p = self.sp_pa
        s0 = self.q_mfc / self.sp_pa
        c = 1.0 / (1.0 / s0 - 1.0 / self.s_pump) if 0 < s0 < self.s_pump else self.c_max
        self.theta = float(np.arccos(np.clip(1.0 - c / self.c_max, -1.0, 1.0)))
        if not math.isfinite(self.theta):
            self.theta = math.pi / 4
        self.theta_base = self.theta
        self.integral = self.theta
        self.ror_run = self.ror_done = False
        self.ror_samples.clear()
        self.est_qleak = self.est_q1 = self.est_alpha = float("nan")
        self.est_verdict = "정상"

    def q_total(self) -> float:
        """총 유입 스루풋 [Pa·m³/s]. 게이트 폐쇄 중에는 MFC 를 차단한다(인터록)."""
        og = outgassing_rate(self.t - self.t_outgas0, self.q1, self.alpha) if self.q1 > 0 else 0.0
        mfc = 0.0 if (self.gate_closed or not self.process_run) else self.q_mfc + self.mfc_offset
        return mfc + self.q_leak + og

    def gauge(self, p_true: float) -> float:
        """압력 게이지 계측 모델 — 상대 양자화.

        실측 Process_data.nc 의 압력 채널 양자화 눈금은 원시값 1e-4 / 평균 0.0424 = 0.236 %.
        무잡음 신호를 그대로 쓰면 잔차가 기계정밀도까지 내려가 모델선택이 무의미해지므로,
        실제 계기와 같은 분해능을 반영한다.

        Args:
            p_true: 참 압력 [Pa]

        Returns:
            양자화된 계측 압력 [Pa]
        """
        step = self.gauge_quant_rel * max(p_true, 1e-9)
        return round(p_true / step) * step if step > 0 else p_true

    def s_eff(self) -> float:
        if self.gate_closed:
            return 0.0
        c = self.c_max * (1.0 - math.cos(min(max(self.theta, 0.0), math.pi / 2)))
        return series_pumping_speed(c, self.s_pump)

    def step(self) -> None:
        dt = self.dt_s
        apc = self.cfg.apc
        if self.gate_closed:
            pass
        elif self.auto and self.cmd_theta is None and apc is not None:
            # 내부 APC (단독 시험용)
            e = self.p - self.sp_pa
            raw = apc.kp * e + self.integral
            cmd = min(max(raw, 0.0), math.pi / 2)
            self.integral += (apc.ki * e + (1.0 / apc.tau_valve_s) * (cmd - raw)) * dt
            self.theta += ((cmd - self.theta) / apc.tau_valve_s) * dt
        elif self.cmd_theta is not None:
            # PLC 가 밸브 각도를 지령한다 (HIL 본 구성)
            tau = apc.tau_valve_s if apc else 0.05
            self.theta += ((self.cmd_theta - self.theta) / tau) * dt
        self.theta = min(max(self.theta, 0.0), math.pi / 2)

        q, s = self.q_total(), self.s_eff()
        if s > 1e-12:                                    # 지수적분기 (선형부 해석해)
            p_inf = q / s
            self.p = p_inf + (self.p - p_inf) * math.exp(-s * dt / self.cfg.volume_m3)
        else:
            self.p += q * dt / self.cfg.volume_m3
        self.p = max(self.p, 0.0)
        self.t += dt

        if self.ror_run:
            if not self.ror_samples or self.t - self.ror_samples[-1][0] >= 0.2:   # 5 Hz
                self.ror_samples.append((self.t, self.gauge(self.p)))
            if self.t - self.ror_t0 >= self.ror_dur:
                self.finish_ror()

    # ---------------- RoR
    def start_ror(self) -> None:
        self.ror_run, self.ror_done = True, False
        self.ror_t0 = self.t
        self.ror_samples = []
        self.gate_closed = True
        self.p = max(self.p * 0.02, mtorr_to_pa(0.4))
        # RoR 관례: 아웃가싱 시계는 챔버를 격리한 시점에서 다시 센다.
        # q(t) = q1·t^(−α) 의 t 원점을 격리 시점으로 두는 것이 표준 해석이다.
        self.t_outgas0 = self.t
        log.info("RoR 시퀀스 시작 (%.0f s)", self.ror_dur)

    def finish_ror(self) -> None:
        self.ror_run, self.ror_done = False, True
        self.gate_closed = False
        r = estimate_ror(self.ror_samples, self.cfg.volume_m3)
        if r:
            self.est_qleak, self.est_q1 = r.q_leak, r.q1
            self.est_alpha = r.alpha
            self.est_verdict = classify(r, self.alm_qleak_hi)
            log.info("RoR 완료 — Q_leak=%.3e  q1=%.3e  α=%s  판정 %s%s",
                     r.q_leak, r.q1, f"{r.alpha:.3f}" if math.isfinite(r.alpha) else "—",
                     self.est_verdict, "" if r.outgas_accepted else f"  (아웃가싱 기각: {r.reason})")

    # ---------------- 진단 (미측정 변수 역산)
    def estimate_health(self) -> tuple[float, float, bool]:
        """밸브각과 압력으로 TMP 성능비 / 밸브 C_max 비를 역산한다.

        정상상태 식이 하나뿐이라 둘을 동시에 결정할 수 없다.
        밸브각이 기준보다 열렸으면 펌프 저하를 의심해 TMP 를 역산하고, 아니면 밸브를 역산한다.

        Returns:
            (TMP 성능비, 밸브 C_max 비, assume_pump 플래그)
        """
        if self.p <= 0 or self.gate_closed:
            return float("nan"), float("nan"), True
        s_req = self.q_total() / self.p
        frac = 1.0 - math.cos(min(max(self.theta, 1e-6), math.pi / 2))
        assume_pump = self.theta >= self.theta_base
        if assume_pump:
            c_now = self.cfg.valve.c_max_m3s * frac
            inv = 1.0 / s_req - 1.0 / c_now
            sp = 1.0 / inv if inv > 1e-12 else float("nan")
            return sp / self.cfg.pump_speed_m3s, 1.0, True
        inv = 1.0 / s_req - 1.0 / self.cfg.pump_speed_m3s
        c_req = 1.0 / inv if inv > 1e-12 else float("nan")
        return 1.0, (c_req / frac) / self.cfg.valve.c_max_m3s, False

    def foreline_pa(self) -> float:
        """포어라인 압력 [Pa]. P_fore ≈ Q_통과 / S_러핑 (러핑 배기속도는 시험대 설정값)."""
        s_rough = 0.0576                       # m³/s (가정치) — Phase 1 단위 교차검증에서 추정한 규모
        return self.q_total() / s_rough


# ---------------------------------------------------------------- Modbus 브리지


class TwinBridge:
    """플랜트 상태를 Modbus 데이터스토어에 반영하고, 지령을 플랜트에 되먹인다."""

    def __init__(self, plant: Plant, store) -> None:
        self.p = plant
        self.s = store
        self._prev_coils = [False] * 8

    def read_commands(self) -> None:
        """Holding Register / Coil 을 읽어 플랜트에 반영한다."""
        hr = self.s.get_hr(0, 22)
        p = self.p
        if hr[0]:
            p.sp_pa = mtorr_to_pa(hr[0] / S_P100)
        p.q_mfc = hr[1] / S_Q1E4
        if hr[6]:
            p.alm_p_hi = mtorr_to_pa(hr[6] / S_P100)
        if hr[7]:
            p.alm_p_lo = mtorr_to_pa(hr[7] / S_P100)
        if hr[8]:
            p.alm_valve_hi = math.radians(hr[8] / S_DEG100)
        if hr[9]:
            p.alm_qleak_hi = hr[9] / S_Q1E6
        if hr[5]:
            p.ror_dur = float(hr[5])

        new_q1 = hr[17] / S_Q1E6
        if new_q1 > 0 and p.q1 == 0:
            p.t_outgas0 = p.t
        p.q_leak = hr[16] / S_Q1E6
        p.q1 = new_q1
        p.alpha = hr[18] / S_K1E3 if hr[18] else 1.0
        p.pump_derate = hr[19] / S_PCT100 / 100.0 if hr[19] else 1.0
        p.valve_wear = hr[20] / S_PCT100 / 100.0 if hr[20] else 1.0
        p.mfc_offset = from_i16(hr[21]) / S_Q1E6

        co = self.s.get_co(0, 6)
        p.auto = bool(co[0])
        p.process_run = bool(co[5])
        # 자동 모드에서 PLC 가 쓴 밸브 지령(HR2)을 따른다. 0 이면 내부 APC 로 폴백한다.
        p.cmd_theta = math.radians(hr[2] / S_DEG100) if (p.auto and hr[2] > 0) else None
        if not p.ror_run:
            p.gate_closed = bool(co[1])

        if co[2] and not self._prev_coils[2]:       # RoR 시작 (상승엣지)
            p.start_ror()
            self.s.set_co(2, [False])
            co = self.s.get_co(0, 6)
        if co[4] and not self._prev_coils[4]:       # 시뮬 리셋 (상승엣지)
            p.reset()
            self.s.set_co(4, [False])
            co = self.s.get_co(0, 6)
        self._prev_coils = list(co) + [False] * (8 - len(co))

    def write_measurements(self) -> None:
        """계측값과 상태·알람을 Input Register / Discrete Input 에 쓴다."""
        p = self.p
        s_eff = p.s_eff()
        health_pump, health_valve, assume_pump = p.estimate_health()
        rt_lo, rt_hi = u32(p.t * S_P10)

        ir = [
            u16(pa_to_mtorr(p.p) * S_P100),                     # IR0  챔버 압력
            u16(pa_to_mtorr(p.foreline_pa()) * S_P10),          # IR1  포어라인 압력
            u16(math.degrees(p.theta) * S_DEG100),              # IR2  밸브 각도
            u16((1 - math.cos(p.theta)) * 100 * S_PCT100),      # IR3  개방률
            u16(m3s_to_lps(s_eff) * S_LPS10),                   # IR4  S_eff
            u16(p.q_total() * S_Q1E4),                          # IR5  총 스루풋
            u16((p.q_mfc + p.mfc_offset) * S_Q1E4),             # IR6  MFC 실측
            u16(0.013 * S_KN1E4),                               # IR7  Knudsen 수
            1,                                                  # IR8  유동영역 (중간류)
            rt_lo, rt_hi,                                       # IR9~10 경과시간
            u16(p.est_qleak * S_Q1E6) if math.isfinite(p.est_qleak) else INVALID_U16,
            u16(p.est_q1 * S_Q1E6) if math.isfinite(p.est_q1) else INVALID_U16,
            u16(p.est_alpha * S_K1E3) if math.isfinite(p.est_alpha) else INVALID_U16,
            u16(health_pump * 100 * S_PCT100),                  # IR14 TMP 성능 추정
            u16(health_valve * 100 * S_PCT100),                 # IR15 밸브 성능 추정
        ]
        self.s.set_ir(0, ir)

        leak_alm = p.ror_done and p.est_verdict == "실누설"
        outgas_alm = p.ror_done and p.est_verdict == "아웃가싱 우세"
        self.s.set_di(0, [
            p.auto,                                             # DI0
            p.alm_p_lo <= p.p <= p.alm_p_hi,                    # DI1
            p.theta >= math.pi / 2 - 1e-3,                      # DI2
            p.theta <= 1e-3,                                    # DI3
            p.ror_run,                                          # DI4
            p.ror_done,                                         # DI5
            p.p > p.alm_p_hi,                                   # DI6
            p.p < p.alm_p_lo and not p.gate_closed,             # DI7
            p.theta > p.alm_valve_hi,                           # DI8
            bool(leak_alm and not outgas_alm),                  # DI9
            bool(outgas_alm),                                   # DI10
            p.gate_closed,                                      # DI11 인터록: 가스 차단
            assume_pump,                                        # DI12
            p.theta >= math.pi / 2 - 1e-3,                      # DI13 인터록: 밸브 포화
        ])


# ---------------------------------------------------------------- 실행


def build_plant(local_apc: bool) -> Plant:
    """시험대 설정으로 플랜트를 만든다 (plc/modbus_map.md 와 동일한 값)."""
    cfg = ChamberConfig(
        volume_m3=0.050,          # (통상범위) 200 mm DRIE 챔버 30~80 L
        pump_speed_m3s=1.500,     # (통상범위) DRIE 용 TMP 1000~2000 L/s
        valve=ThrottleValve(c_max_m3s=2.000),   # (가정치) 시험대 설정
        apc=APCController(setpoint_pa=mtorr_to_pa(40.0), kp=0.30, ki=1.20),
    )
    p = Plant(cfg=cfg)
    if not local_apc:
        p.auto = True
    return p


def default_holding() -> list[int]:
    """Holding Register 기본값 (modbus_map.md §3)."""
    hr = [0] * 22
    hr[0] = 4000        # 압력 설정값 40.00 mTorr
    hr[1] = 10000       # MFC 1.0 Pa·m³/s
    hr[2] = 0           # 밸브 지령 (PLC 가 쓴다. 0 이면 내부 APC)
    hr[3] = 300         # Kp
    hr[4] = 1200        # Ki
    hr[5] = 60          # RoR 시간
    hr[6] = 4400        # 압력 상한
    hr[7] = 3600        # 압력 하한
    hr[8] = 4500        # 밸브각 상한
    hr[9] = 5000        # 실누설 알람 임계
    hr[18] = 1000       # α = 1.0
    hr[19] = 10000      # TMP 100 %
    hr[20] = 10000      # 밸브 100 %
    return hr


def main() -> None:
    ap = argparse.ArgumentParser(description="챔버 디지털 트윈 Modbus TCP 슬레이브")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--dt", type=float, default=0.01, help="물리 적분 스텝 [s]")
    ap.add_argument("--period", type=float, default=0.2, help="Modbus 갱신 주기 [s] (실측 5 Hz)")
    ap.add_argument("--local-apc", action="store_true", help="PLC 없이 내부 APC 로 단독 시험")
    ap.add_argument("--headless-demo", type=float, default=0.0,
                    help="Modbus 없이 지정 시간만큼 물리만 돌리고 종료 (자체 시험용)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    plant = build_plant(args.local_apc)
    plant.dt_s = args.dt

    if args.headless_demo > 0:
        run_headless(plant, args.headless_demo)
        return

    from plc.modbus_tcp import DataStore, serve

    store = DataStore(n_co=16, n_di=32, n_hr=32, n_ir=32)
    store.set_hr(0, default_holding())
    store.set_co(0, [True, False, False, False, False, True])   # CMD_AUTO, CMD_PROCESS_RUN
    bridge = TwinBridge(plant, store)

    def loop() -> None:
        n = max(int(round(args.period / args.dt)), 1)
        nxt = time.perf_counter()
        while True:
            try:
                bridge.read_commands()
                for _ in range(n):
                    plant.step()
                bridge.write_measurements()
            except Exception:                       # 브리지 오류로 서버가 죽지 않게 한다
                log.exception("갱신 주기 처리 중 오류")
            nxt += args.period
            time.sleep(max(nxt - time.perf_counter(), 0.0))

    serve(args.host, args.port, store)
    threading.Thread(target=loop, daemon=True).start()
    log.info("Modbus TCP 슬레이브 시작 %s:%d  (갱신 %.0f ms, 물리 dt %.0f ms)",
             args.host, args.port, args.period * 1e3, args.dt * 1e3)
    log.info("레지스터 맵: plc/modbus_map.md")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("종료")


def run_headless(plant: Plant, seconds: float) -> None:
    """Modbus 없이 플랜트만 돌려 동작을 확인한다 (자체 시험)."""
    log.info("헤드리스 시험 %.0f s — 200 s 에 누설 0.10 Pa·m³/s 주입", seconds)
    base = None
    while plant.t < seconds:
        if plant.t >= 200.0 and plant.q_leak == 0.0:
            base = (plant.p, plant.theta)
            plant.q_leak = 0.10
        plant.step()
    hp, hv, ap_ = plant.estimate_health()
    print(f"\n  주입 직전 : P = {pa_to_mtorr(base[0]):8.4f} mTorr, θ = {math.degrees(base[1]):7.4f}°")
    print(f"  최종      : P = {pa_to_mtorr(plant.p):8.4f} mTorr, θ = {math.degrees(plant.theta):7.4f}°")
    print(f"  압력 변화 : {(plant.p / base[0] - 1) * 100:+.5f} %")
    print(f"  밸브 변화 : {(plant.theta / base[1] - 1) * 100:+.4f} %")
    print(f"  S_eff     : {m3s_to_lps(plant.s_eff()):.2f} L/s "
          f"(요구 {m3s_to_lps(plant.q_total() / plant.p):.2f} L/s)")
    print(f"  역산      : TMP {hp * 100:.2f} %, 밸브 {hv * 100:.2f} %, "
          f"{'펌프 역산' if ap_ else '밸브 역산'}")


if __name__ == "__main__":
    main()
