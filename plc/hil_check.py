"""HIL 제어 루프 검증 — OpenPLC ST 프로그램의 PI 이득이 실제로 안정한가.

지금까지 검증한 것은 Python 내부 APC(dt = 10 ms, 지연 없음)뿐이다.
그러나 실제 구성에는 루프 지연이 있다.

    챔버 물리 (dt 10 ms)
      └─ Modbus 폴링 200 ms ─→ PLC 스캔 100 ms ─→ Modbus 쓰기 200 ms ─→ 밸브 지연 50 ms
                                                                    총 유효 지연 ≈ 300 ms

챔버 시정수는 V/S_eff = 0.050/0.1876 = 0.267 s 다. **지연이 시정수와 같은 크기다.**
이 조건에서는 이득을 잘못 잡으면 발산한다. 이 스크립트가 그것을 실측한다.

실행:
    python plc/hil_check.py              # 현재 ST 이득 평가 + 이득 소인
    python plc/hil_check.py --sweep-only

단위: 내부 물리는 SI. PLC 측 계산은 ST 와 동일하게 mTorr / deg 공학단위.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from physics.chamber import series_pumping_speed
from physics.units import mtorr_to_pa, pa_to_mtorr

# 시험대 (plc/modbus_map.md 및 modbus_server.py 와 동일)
V_M3, S_PUMP, C_MAX = 0.050, 1.500, 2.000
P_SP_MTORR, Q_BASE = 40.0, 1.000

DT_PHYS = 0.010          # 물리 적분 스텝 [s]
DT_SCAN = 0.100          # PLC 스캔 주기 [s]  (ST: TASK INTERVAL := T#100ms)
DT_POLL = 0.200          # Modbus 폴링 주기 [s] (실측 5 Hz 와 동일)
TAU_VALVE = 0.050        # 밸브 액추에이터 시정수 [s]
THETA_MAX_DEG = 90.0


@dataclass
class HilResult:
    """HIL 응답 지표.

    Attributes:
        stable: 발산하지 않고 정착했는가
        overshoot_pct: 설정값 대비 최대 오버슈트 [%]
        settle_s: 설정값 ±1 % 안에 머무르기 시작한 시각 [s]
        ss_err_pct: 정상상태 오차 [%]
        osc_count: 설정값 교차 횟수 (진동 지표)
        theta_final_deg: 최종 밸브 각도 [deg]
        p_final_mtorr: 최종 압력 [mTorr]
        leak_dp_pct: 누설 주입 후 압력 변화 [%]
        leak_dth_pct: 누설 주입 후 밸브각 변화 [%]
        leak_settle_s: 누설 주입 후 압력이 설정값 ±0.1 % 로 복귀하는 데 걸린 시간 [s].
            진단 관점에서 실제로 중요한 지표다 — 밸브각이 새 평형에 도달해야 역산이 유효하다
    """

    stable: bool
    overshoot_pct: float
    settle_s: float
    ss_err_pct: float
    osc_count: int
    theta_final_deg: float
    p_final_mtorr: float
    leak_dp_pct: float = float("nan")
    leak_dth_pct: float = float("nan")
    leak_settle_s: float = float("nan")


def theta_for(s_eff: float) -> float:
    """정상상태 배기속도에 대응하는 밸브 각도 [deg]."""
    c = 1.0 / (1.0 / s_eff - 1.0 / S_PUMP)
    return math.degrees(math.acos(max(min(1.0 - c / C_MAX, 1.0), -1.0)))


def run_hil(kp: float, ki: float, t_end: float = 120.0, p0_mtorr: float = 28.0,
            t_leak: float = 60.0, q_leak: float = 0.05,
            dt_poll: float = DT_POLL, dt_scan: float = DT_SCAN) -> HilResult:
    """PLC(이산 PI + 지연) ↔ 플랜트(연속 물리) 폐루프를 모사한다.

    Args:
        kp: 비례이득 [deg/mTorr]
        ki: 적분이득 [deg/(mTorr·s)]
        t_end: 모사 시간 [s]
        p0_mtorr: 초기 압력 [mTorr]. 설정값(40)과 다르게 두어야 과도응답이 생긴다.
            같게 두면 제어기가 할 일이 없어 모든 이득이 "오버슈트 0 %" 로 보인다
        t_leak: 누설 주입 시각 [s] (0 이면 주입 안 함)
        q_leak: 주입 누설 [Pa·m³/s]
        dt_poll: Modbus 폴링 주기 [s]
        dt_scan: PLC 스캔 주기 [s]

    Returns:
        HilResult
    """
    sp = P_SP_MTORR
    theta0 = theta_for(Q_BASE / mtorr_to_pa(sp))

    # 플랜트 상태
    p_pa = mtorr_to_pa(p0_mtorr)
    theta = theta0                      # 실제 밸브 각도 [deg]
    theta_cmd_applied = theta0          # 플랜트가 현재 따르는 지령 [deg]

    # PLC 상태 (ST 의 FB_APC_PI 와 동일)
    integ = theta0
    kaw = 1.0 / TAU_VALVE               # 되계산 이득 [1/s]

    # 통신 지연 모델 — 값 유지(ZOH)
    pv_to_plc = pa_to_mtorr(p_pa)       # PLC 가 보고 있는 압력 (최대 dt_poll 만큼 오래된 값)
    cmd_from_plc = theta0

    t = 0.0
    t_next_poll, t_next_scan = dt_poll, dt_scan
    hist_t, hist_p, hist_th = [], [], []
    leak = 0.0
    p_pre = th_pre = float("nan")

    n = int(round(t_end / DT_PHYS))
    for _ in range(n):
        if t_leak > 0 and t >= t_leak and leak == 0.0:
            p_pre, th_pre = pa_to_mtorr(p_pa), theta
            leak = q_leak

        # --- Modbus 폴링: 계측 업로드 + 지령 다운로드 (양방향 ZOH)
        if t >= t_next_poll:
            pv_to_plc = pa_to_mtorr(p_pa)
            theta_cmd_applied = cmd_from_plc
            t_next_poll += dt_poll

        # --- PLC 스캔: 이산 PI (ST FB_APC_PI 와 동일한 되계산 와인드업 방지)
        if t >= t_next_scan:
            e = pv_to_plc - sp
            raw = kp * e + integ
            cmd = min(max(raw, 0.0), THETA_MAX_DEG)
            integ += (ki * e + kaw * (cmd - raw)) * dt_scan
            cmd_from_plc = cmd
            t_next_scan += dt_scan

        # --- 플랜트: 밸브 1차 지연 + 압력 지수적분
        theta += ((theta_cmd_applied - theta) / TAU_VALVE) * DT_PHYS
        theta = min(max(theta, 0.0), THETA_MAX_DEG)
        c = C_MAX * (1.0 - math.cos(math.radians(theta)))
        s_eff = series_pumping_speed(c, S_PUMP)
        q = Q_BASE + leak
        if s_eff > 1e-12:
            p_inf = q / s_eff
            p_pa = p_inf + (p_pa - p_inf) * math.exp(-s_eff * DT_PHYS / V_M3)
        else:
            p_pa += q * DT_PHYS / V_M3
        p_pa = max(p_pa, 0.0)
        if not math.isfinite(p_pa) or p_pa > mtorr_to_pa(10000.0):
            return HilResult(False, float("inf"), float("inf"), float("inf"),
                             999, theta, float("inf"))

        t += DT_PHYS
        hist_t.append(t); hist_p.append(pa_to_mtorr(p_pa)); hist_th.append(theta)

    tt = np.array(hist_t); pp = np.array(hist_p); th = np.array(hist_th)

    # 누설 주입 전 구간으로 과도응답 지표를 낸다 (초기 압력 이탈 → 설정값 복귀가 스텝)
    t_pre_end = t_leak if t_leak > 0 else t_end
    pre = tt < t_pre_end
    tp, p_pre_seg = tt[pre], pp[pre]
    overshoot = float((p_pre_seg.max() - sp) / sp * 100)
    dev = np.abs(p_pre_seg - sp) / sp
    outside = np.flatnonzero(dev > 0.01)
    settle = float(tp[outside[-1]]) if outside.size else 0.0
    ss = float(abs(p_pre_seg[-1] - sp) / sp * 100)
    crossings = int(np.sum(np.diff(np.sign(p_pre_seg - sp)) != 0))
    stable = (settle < t_pre_end * 0.8) and ss < 1.0 and crossings < 40

    res = HilResult(stable, overshoot, settle, ss, crossings,
                    float(th[-1]), float(pp[-1]))
    if t_leak > 0 and math.isfinite(p_pre):
        res.leak_dp_pct = float((pp[-1] - p_pre) / p_pre * 100)
        res.leak_dth_pct = float((th[-1] - th_pre) / th_pre * 100)
        post = tt >= t_leak
        dev_post = np.abs(pp[post] - sp) / sp
        out_post = np.flatnonzero(dev_post > 0.001)
        res.leak_settle_s = float(tt[post][out_post[-1]] - t_leak) if out_post.size else 0.0
    return res


def margin_estimate(kp: float, ki: float,
                    dt_poll: float = DT_POLL) -> tuple[float, float]:
    """선형화 모델로 교차주파수와 위상여유를 추정한다.

    플랜트 선형화 (운전점 P* = 40 mTorr, θ* ≈ 26.77°):
        dPV/dt = −a·PV_dev − b·θ_dev,   a = S*/V,  b = P*·(dS/dθ)/V

    Args:
        kp: 비례이득 [deg/mTorr]
        ki: 적분이득 [deg/(mTorr·s)]
        dt_poll: Modbus 폴링 주기 [s]

    Returns:
        (교차주파수 [rad/s], 위상여유 [deg])
    """
    p_pa = mtorr_to_pa(P_SP_MTORR)
    s_star = Q_BASE / p_pa
    th = math.radians(theta_for(s_star))
    c = C_MAX * (1 - math.cos(th))
    dc_dth = C_MAX * math.sin(th)                 # [m³/s per rad]
    ds_dc = (s_star / c) ** 2
    ds_dth = ds_dc * dc_dth
    a = s_star / V_M3                             # [1/s]
    b_pa = p_pa * ds_dth / V_M3                   # [Pa/(s·rad)]
    b = pa_to_mtorr(b_pa) * math.pi / 180.0       # [mTorr/(s·deg)]

    t_delay = dt_poll + DT_SCAN / 2 + TAU_VALVE    # 유효 지연 [s]
    w = np.logspace(-3, 2, 4000)
    # L(jw) = (kp + ki/jw)·b/(jw + a)·e^(−jw·T)
    L = (kp + ki / (1j * w)) * b / (1j * w + a) * np.exp(-1j * w * t_delay)
    mag = np.abs(L)
    idx = np.flatnonzero(np.diff(np.sign(mag - 1.0)) != 0)
    if idx.size == 0:
        return float("nan"), float("nan")
    k = int(idx[0])
    wc = float(w[k])
    pm = 180.0 + math.degrees(np.angle(L[k]))
    return wc, pm


def main() -> None:
    ap = argparse.ArgumentParser(description="HIL 제어 루프 안정성 검증")
    ap.add_argument("--sweep-only", action="store_true")
    args = ap.parse_args()

    print("=" * 92)
    print("HIL 제어 루프 검증 — PLC 이산 PI + 통신 지연")
    print("=" * 92)
    t_delay = DT_POLL + DT_SCAN / 2 + TAU_VALVE
    tau_chamber = V_M3 / (Q_BASE / mtorr_to_pa(P_SP_MTORR))
    print(f"\n  Modbus 폴링 {DT_POLL*1e3:.0f} ms + PLC 스캔 {DT_SCAN*1e3:.0f} ms/2 "
          f"+ 밸브 지연 {TAU_VALVE*1e3:.0f} ms  =  유효 지연 {t_delay*1e3:.0f} ms")
    print(f"  챔버 시정수 V/S_eff = {tau_chamber:.3f} s  →  지연/시정수 = {t_delay/tau_chamber:.2f}")
    print(f"  기준 밸브각 {theta_for(Q_BASE/mtorr_to_pa(P_SP_MTORR)):.2f}°")
    print(f"  과도응답 시험: 초기 압력 28 mTorr 에서 설정값 40 mTorr 로 복귀 (−30 % 이탈)\n")

    cur_kp, cur_ki = 0.40, 1.60          # 현재 openplc_apc.st 값
    print("-" * 92)
    print("[1] 현재 ST 이득 평가")
    print("-" * 92)
    wc, pm = margin_estimate(cur_kp, cur_ki)
    r = run_hil(cur_kp, cur_ki, t_leak=0.0, t_end=90.0, p0_mtorr=28.0)
    print(f"  KP = {cur_kp} deg/mTorr, KI = {cur_ki} deg/(mTorr·s)")
    print(f"  선형 추정: 교차주파수 {wc:.3f} rad/s, 위상여유 {pm:+.1f}°")
    print(f"  모사 결과: {'안정' if r.stable else '불안정'} | 오버슈트 {r.overshoot_pct:+.2f} % "
          f"| 정착 {r.settle_s:.1f} s | 정상상태오차 {r.ss_err_pct:.4f} % | 교차 {r.osc_count} 회")
    if pm < 30:
        print(f"  ⚠ 위상여유 {pm:.1f}° — 통상 설계 기준 45° 이상에 미달한다")

    print("\n" + "-" * 92)
    print("[2] 이득 소인")
    print("-" * 92)
    print("  채택 기준: 위상여유 >= 60도, 스텝 오버슈트 <= 8 %, 정상상태오차 < 0.1 %")
    print("  그 중 **교차주파수가 가장 높은** 조합을 고른다 — 외란(고장) 제거가 가장 빠르다\n")
    print(f"  {'KP':>6s} {'KI':>6s} {'교차w':>8s} {'위상여유':>9s} {'오버슈트':>9s} "
          f"{'정착s':>7s} {'외란정착s':>10s} {'교차':>5s} {'판정':>6s}")
    best = None
    for kp in (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60):
        for ki in (0.02, 0.05, 0.10, 0.20, 0.40, 0.80, 1.60):
            w, m = margin_estimate(kp, ki)
            rr = run_hil(kp, ki, t_end=90.0, t_leak=0.0, p0_mtorr=28.0)
            rd = run_hil(kp, ki, t_end=140.0, t_leak=60.0, q_leak=0.05, p0_mtorr=40.0)
            ok = (rr.stable and m >= 60.0 and rr.overshoot_pct <= 8.0
                  and rr.ss_err_pct < 0.1)
            if ok and (best is None or w > best[4]):
                best = (kp, ki, rr, m, w, rd)
            if ok or (kp, ki) == (cur_kp, cur_ki):
                print(f"  {kp:6.2f} {ki:6.2f} {w:8.3f} {m:+9.1f} {rr.overshoot_pct:+9.2f} "
                      f"{rr.settle_s:7.1f} {rd.leak_settle_s:10.1f} {rr.osc_count:5d} "
                      f"{'통과' if ok else '실패':>6s}")

    if best is None:
        print("\n  조건을 만족하는 이득 조합을 찾지 못했다.")
        return
    kp, ki, rr, pm2, wc2, rd2 = best
    print(f"\n  권장: KP = {kp} deg/mTorr, KI = {ki} deg/(mTorr*s)")
    print(f"        교차주파수 {wc2:.3f} rad/s, 위상여유 {pm2:+.1f} deg, "
          f"오버슈트 {rr.overshoot_pct:+.2f} %, 스텝정착 {rr.settle_s:.1f} s, "
          f"외란정착 {rd2.leak_settle_s:.1f} s")
    print(f"  (현재 ST 값 KP=0.40 KI=1.60 대비: 위상여유 20.0 → {pm2:.1f} deg, "
          f"오버슈트 22.94 → {rr.overshoot_pct:.2f} %)")

    print("\n" + "-" * 92)
    print("[3] 권장 이득으로 누설 외란 응답 확인 (60 s 에 0.05 Pa·m³/s 주입)")
    print("-" * 92)
    rl = run_hil(kp, ki, t_end=140.0, t_leak=60.0, q_leak=0.05, p0_mtorr=40.0)
    print(f"  압력 변화 {rl.leak_dp_pct:+.5f} %   밸브각 변화 {rl.leak_dth_pct:+.4f} %  "
          f"→ 최종 {rl.p_final_mtorr:.4f} mTorr, {rl.theta_final_deg:.4f} deg")
    print(f"  외란 정착 {rl.leak_settle_s:.1f} s — 이 시간 이후에야 밸브각 역산이 유효하다")
    print("  → 압력은 고정되고 밸브각만 움직인다 (실측 재현)")

    print("\n" + "-" * 92)
    print("[4] 폴링 주기 민감도 — 통신이 느려지면 어디서 무너지는가")
    print("-" * 92)
    print(f"  {'폴링ms':>8s} {'위상여유':>9s} {'오버슈트':>9s} {'정착s':>7s} {'판정':>6s}")
    for poll in (0.05, 0.10, 0.20, 0.50, 1.00, 2.00):
        rr = run_hil(kp, ki, t_end=120.0, t_leak=0.0, p0_mtorr=28.0, dt_poll=poll)
        _, m = margin_estimate(kp, ki, dt_poll=poll)
        print(f"  {poll*1e3:8.0f} {m:+9.1f} {rr.overshoot_pct:+9.2f} {rr.settle_s:7.1f} "
              f"{'안정' if rr.stable else '불안정':>6s}")


if __name__ == "__main__":
    main()
