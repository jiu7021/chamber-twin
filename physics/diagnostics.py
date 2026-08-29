"""진공 진단 추정기 — Rate-of-Rise 분리 추정.

RoR(Rate-of-Rise)은 게이트 밸브를 닫아 배기를 끊고 압력 상승을 측정하는 시험이다.
배기가 없으므로 지배식이 V·dP/dt = Q_total 로 단순해지고, 상승 곡선의 **모양**에서
실누설(상수)과 가상누설(아웃가싱, 시간에 따라 감쇠)을 분리할 수 있다.

모델
    M1  P(t) − P(t₀) = (Q_leak/V)·(t − t₀)                        실누설만 (파라미터 1)
    M2  M1 + (q1/V)·∫t^(−α)dt                                     아웃가싱 포함 (파라미터 3)

단위: 전부 SI (Pa, m³, Pa·m³/s, s).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

T_MIN_S = 1.0            # 아웃가싱 모델 q = q1·t^(−α) 가 정의되는 하한 시각
ALPHA_LO, ALPHA_HI = 0.2, 1.6
ALPHA_N = 141


@dataclass(frozen=True)
class RoRResult:
    """RoR 분리 추정 결과.

    Attributes:
        q_leak: 실누설 스루풋 [Pa·m³/s]
        q1: 아웃가싱 계수 (t = 1 s 기준) [Pa·m³/s]. 아웃가싱이 기각되면 0.0
        alpha: 아웃가싱 지수 [무차원]. 기각되면 nan
        outgas_accepted: 아웃가싱 항 채택 여부
        reason: 기각 사유 (채택 시 빈 문자열)
        d_aic: AIC(M1) − AIC(M2). 클수록 M2 가 우월
        contribution: 아웃가싱 항이 전체 압력 상승에서 차지하는 비율
        n: 사용한 표본 수
    """

    q_leak: float
    q1: float
    alpha: float
    outgas_accepted: bool
    reason: str
    d_aic: float
    contribution: float
    n: int


def _basis(tt: np.ndarray, alpha: float) -> np.ndarray:
    """∫t^(−α)dt 를 tt[0] 기준으로 적분한 기저 (α = 1 은 로그)."""
    if abs(alpha - 1.0) < 1e-9:
        return np.log(tt / tt[0])
    return (tt ** (1 - alpha) - tt[0] ** (1 - alpha)) / (1 - alpha)


def estimate_ror(samples: list[tuple[float, float]], volume_m3: float,
                 daic_accept: float = 10.0, contrib_min: float = 0.05,
                 t_min_s: float = T_MIN_S) -> RoRResult | None:
    """RoR 곡선에서 (Q_leak, q1, α) 를 분리 추정한다.

    미분 잡음을 피하기 위해 dP/dt 가 아니라 **적분형(압력 자체)** 으로 적합한다.
    α 는 격자 소인하며 2변수 선형 최소제곱을 반복해 잔차가 최소인 값을 고른다.

    **모델 선택이 반드시 필요하다.** 누설만 있을 때 M2 를 무조건 적합하면
    t^(−α) 기저가 직선을 흉내내며 존재하지 않는 아웃가싱을 만들어낸다.
    아래 세 조건을 모두 통과할 때만 아웃가싱 항을 채택한다.
      (a) AIC 개선 ΔAIC ≥ daic_accept
      (b) α 가 소인 경계에 붙지 않을 것 — 붙으면 기저가 축퇴했다는 신호다
      (c) 아웃가싱 항이 전체 압력 상승의 contrib_min 이상을 설명할 것

    Args:
        samples: [(t[s], P[Pa]), …] — RoR 시작을 원점으로 하는 시각
        volume_m3: 챔버 체적 [m³]
        daic_accept: M2 채택에 요구하는 ΔAIC (기본 10 = 관례상 "강한 증거")
        contrib_min: 아웃가싱 항의 최소 기여 비율
        t_min_s: 이 시각 미만 표본은 버린다. 반드시 > 0 이어야 한다
            (모델 q = q1·t^(−α) 가 t → 0 에서 발산하므로 t = 0 표본은 기저가 정의되지 않는다)

    Returns:
        RoRResult. 표본이 부족하면 None.

    Raises:
        ValueError: t_min_s <= 0 인 경우

    Note:
        t < t_min_s 구간은 **버린다**(클램핑하지 않는다). 클램핑하면 해당 표본이
        설계행렬에서 전부 0 행이 되는데 압력은 실제로 상승하므로 모순 데이터가 되어
        α 추정이 크게 치우친다.
    """
    if t_min_s <= 0:
        raise ValueError("t_min_s 는 0 보다 커야 한다 (t^(−α) 기저가 t = 0 에서 발산)")
    if len(samples) < 20:
        return None
    t = np.asarray([s[0] for s in samples], dtype=float)
    p = np.asarray([s[1] for s in samples], dtype=float)
    t = t - t[0]
    keep = t >= t_min_s
    if int(keep.sum()) < 20:
        return None
    tt, pp = t[keep], p[keep]
    y = pp - pp[0]
    n = len(y)

    def aic(sse: float, k: int) -> float:
        return n * math.log(max(sse, 1e-300) / n) + 2 * k

    # M1 — 실누설만 (원점 통과 1변수)
    x1 = (tt - tt[0]).reshape(-1, 1)
    c1, *_ = np.linalg.lstsq(x1, y, rcond=None)
    sse1 = float(np.sum((y - x1 @ c1) ** 2))
    aic1 = aic(sse1, 1)

    # M2 — 아웃가싱 포함, α 격자 소인
    best = None
    for a in np.linspace(ALPHA_LO, ALPHA_HI, ALPHA_N):
        X = np.column_stack([tt - tt[0], _basis(tt, a)])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        sse = float(np.sum((y - X @ coef) ** 2))
        if best is None or sse < best[0]:
            best = (sse, float(a), coef)
    sse2, a2, coef2 = best
    d_aic = aic1 - aic(sse2, 3)

    b2 = _basis(tt, a2)
    contrib = float(abs(coef2[1] * b2[-1]) / max(abs(y[-1]), 1e-30))
    span = (ALPHA_HI - ALPHA_LO) / (ALPHA_N - 1)
    railed = a2 <= ALPHA_LO + span * 0.6 or a2 >= ALPHA_HI - span * 0.6

    reason = ""
    if coef2[1] <= 0:
        reason = "아웃가싱 계수가 음수"
    elif d_aic < daic_accept:
        reason = f"AIC 개선 부족 (ΔAIC {d_aic:.1f} < {daic_accept:.0f})"
    elif railed:
        reason = f"α 가 소인 경계에 붙음 ({a2:.3f}) — 기저 축퇴"
    elif contrib < contrib_min:
        reason = f"기여도 부족 ({contrib * 100:.1f} % < {contrib_min * 100:.0f} %)"

    if reason:
        return RoRResult(q_leak=float(c1[0] * volume_m3), q1=0.0, alpha=float("nan"),
                         outgas_accepted=False, reason=reason, d_aic=d_aic,
                         contribution=contrib, n=n)
    return RoRResult(q_leak=float(coef2[0] * volume_m3), q1=float(coef2[1] * volume_m3),
                     alpha=a2, outgas_accepted=True, reason="", d_aic=d_aic,
                     contribution=contrib, n=n)


def classify(res: RoRResult, leak_threshold: float) -> str:
    """RoR 결과를 알람 문구로 분류한다.

    Args:
        res: 추정 결과
        leak_threshold: 실누설 알람 임계 [Pa·m³/s]

    Returns:
        '아웃가싱 우세' | '실누설' | '정상'
    """
    if res.outgas_accepted and res.q1 > 0.5 * abs(res.q_leak):
        return "아웃가싱 우세"
    if res.q_leak > leak_threshold:
        return "실누설"
    return "정상"


# ---------------------------------------------------------------- 다중 운전점 진단


@dataclass(frozen=True)
class MultiPointResult:
    """다중 운전점 배기계 식별 결과.

    Attributes:
        c_max: 밸브 완전개방 컨덕턴스 [m³/s]
        s_pump: 펌프 배기속도 [m³/s]
        r2: 적합 결정계수
        cond: 설계행렬 조건수 (클수록 운전점이 서로 비슷해 분리가 나쁘다)
        n: 사용한 운전점 수
    """

    c_max: float
    s_pump: float
    r2: float
    cond: float
    n: int


def estimate_multipoint(points: list[tuple[float, float, float]]) -> MultiPointResult | None:
    """서로 다른 운전점에서 밸브 완전개방 컨덕턴스와 펌프 배기속도를 **분리** 추정한다.

    단일 운전점에서는 정상상태 식이 하나뿐이라 (C_max, S_pump) 를 동시에 결정할 수 없다.

        1/S_eff = 1/[C_max·(1 − cos θ)] + 1/S_pump = P/Q          … 식 1개, 미지수 2개 → 부정

    그러나 유량 Q 를 바꾸면 밸브각 θ 가 따라 움직이고 f = 1 − cos θ 도 바뀐다.
    식을 미지수에 대해 정리하면 **선형**이다.

        P/Q = x·(1/f) + y,      x = 1/C_max,  y = 1/S_pump

    즉 운전점마다 독립적인 방정식이 하나씩 생기므로, 2개 이상이면 최소제곱으로 둘 다 풀린다.

    물리적 직관: 밸브를 많이 닫으면 **밸브가 병목**이 되고 많이 열면 **펌프가 병목**이 된다.
    여러 개도에서 재면 둘의 기여를 나눌 수 있다.

    Args:
        points: [(Q [Pa·m³/s], P [Pa], θ [rad]), …] — 각각 정상상태에 도달한 뒤의 값

    Returns:
        MultiPointResult. 운전점이 2개 미만이거나 축퇴하면 None.

    Note:
        운전점들의 θ 가 서로 비슷하면 1/f 열의 변화가 작아 설계행렬이 축퇴한다.
        반환되는 `cond` 로 그 상태를 감시할 것 — 통상 1e3 을 넘으면 신뢰하지 않는다.
    """
    if len(points) < 2:
        return None
    rows, rhs = [], []
    for q, p, th in points:
        if q <= 0 or p <= 0:
            continue
        f = 1.0 - math.cos(min(max(th, 1e-9), math.pi / 2))
        if f <= 1e-12:
            continue
        rows.append([1.0 / f, 1.0])
        rhs.append(p / q)
    if len(rows) < 2:
        return None
    A = np.asarray(rows, dtype=float)
    b = np.asarray(rhs, dtype=float)
    cond = float(np.linalg.cond(A))
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    x, y = float(coef[0]), float(coef[1])
    if x <= 0 or y <= 0:
        return None
    pred = A @ coef
    ss_res = float(np.sum((b - pred) ** 2))
    ss_tot = float(np.sum((b - b.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return MultiPointResult(c_max=1.0 / x, s_pump=1.0 / y, r2=r2, cond=cond, n=len(rows))
