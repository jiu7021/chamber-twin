"""RoR 분리 추정기 검증 — 합성 해석해 대조.

RoR 구간에서는 배기가 끊기므로 V·dP/dt = Q_leak + q1·t^(−α) 이고, 적분하면
    P(t) = P(t₀) + (Q_leak/V)(t − t₀) + (q1/V)·∫t^(−α)dt
이 해석해로 표본을 만들어 추정기가 참값을 회복하는지, 그리고 아웃가싱이 없을 때
**없다고 판정**하는지를 확인한다.

단위: SI (Pa, m³, Pa·m³/s, s).
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.diagnostics import classify, estimate_ror


V = 0.050          # m³
DT = 0.2           # s (실측과 같은 5 Hz)
DUR = 60.0         # s


def make_samples(q_leak, q1, alpha, p0=0.1, quant_rel=0.0025, seed=None):
    """해석해로 RoR 표본을 만든다. 실측 수준 상대 양자화를 적용한다."""
    t = np.arange(0.0, DUR + DT, DT)
    tt = np.maximum(t, 1.0)
    integ = np.where(np.abs(alpha - 1.0) < 1e-9,
                     1.0 + np.log(tt), 1.0 + (tt ** (1 - alpha) - 1.0) / (1 - alpha))
    p = p0 + (q_leak * t + q1 * (integ - integ[0])) / V
    if quant_rel > 0:
        step = quant_rel * np.maximum(p, 1e-9)
        p = np.round(p / step) * step
    return list(zip(t.tolist(), p.tolist()))


def test_leak_only_rejects_outgassing():
    """실누설만 주입하면 아웃가싱 항을 기각해야 한다 (가장 중요한 오검출 방지)."""
    r = estimate_ror(make_samples(3.0e-2, 0.0, 1.0), V)
    assert r is not None
    assert not r.outgas_accepted, f"오검출: {r.reason or 'accepted'}"
    assert r.q1 == 0.0
    assert math.isnan(r.alpha)
    assert r.q_leak == pytest.approx(3.0e-2, rel=0.02)


def test_outgassing_metal_alpha1():
    r = estimate_ror(make_samples(0.0, 2.0e-2, 1.0), V)
    assert r.outgas_accepted
    assert r.alpha == pytest.approx(1.0, abs=0.05)
    assert r.q1 == pytest.approx(2.0e-2, rel=0.05)
    assert abs(r.q_leak) < 2.0e-3


def test_outgassing_polymer_alpha05():
    r = estimate_ror(make_samples(0.0, 8.0e-3, 0.5), V)
    assert r.outgas_accepted
    assert r.alpha == pytest.approx(0.5, abs=0.05)
    assert r.q1 == pytest.approx(8.0e-3, rel=0.05)


@pytest.mark.parametrize("q_leak,q1,alpha", [
    (1.5e-2, 2.0e-2, 1.0),
    (1.0e-2, 5.0e-3, 0.5),
    (5.0e-3, 3.0e-2, 1.0),
])
def test_mixed_separation(q_leak, q1, alpha):
    """두 기전이 섞여도 각각 분리 회복해야 한다."""
    r = estimate_ror(make_samples(q_leak, q1, alpha), V)
    assert r.outgas_accepted
    assert r.q_leak == pytest.approx(q_leak, rel=0.08)
    assert r.q1 == pytest.approx(q1, rel=0.08)
    assert r.alpha == pytest.approx(alpha, abs=0.06)


def test_early_samples_bias_alpha():
    """모델이 정의되지 않는 초기 구간을 넣으면 α 추정이 나빠진다.

    q(t) = q1·t^(−α) 는 t → 0 에서 발산하므로 t < t_min 표본은 반드시 버려야 한다.
    이 테스트는 그 설계 결정을 고정한다.
    """
    s = make_samples(0.0, 2.0e-2, 1.0)
    good = estimate_ror(s, V, t_min_s=1.0)
    early = estimate_ror(s, V, t_min_s=0.2)      # 모델이 성립하지 않는 구간까지 포함
    assert good.outgas_accepted
    assert good.alpha == pytest.approx(1.0, abs=0.05)
    assert early is not None
    err_good = abs(good.alpha - 1.0)
    err_early = float("inf") if not early.outgas_accepted else abs(early.alpha - 1.0)
    assert err_early > err_good, "초기 구간 포함이 추정을 나쁘게 만들지 않았다"


def test_t_min_must_be_positive():
    with pytest.raises(ValueError):
        estimate_ror(make_samples(0.0, 2.0e-2, 1.0), V, t_min_s=0.0)


def test_classify():
    leak = estimate_ror(make_samples(3.0e-2, 0.0, 1.0), V)
    assert classify(leak, 5e-3) == "실누설"
    og = estimate_ror(make_samples(0.0, 2.0e-2, 1.0), V)
    assert classify(og, 5e-3) == "아웃가싱 우세"
    clean = estimate_ror(make_samples(1.0e-4, 0.0, 1.0), V)
    assert classify(clean, 5e-3) == "정상"


def test_too_few_samples_returns_none():
    assert estimate_ror([(0.0, 1.0), (1.0, 2.0)], V) is None


def test_noise_robustness():
    """양자화가 3 배 거칠어져도 α 판별이 유지되는가."""
    r = estimate_ror(make_samples(1.0e-2, 2.0e-2, 1.0, quant_rel=0.0075), V)
    assert r.outgas_accepted
    assert r.alpha == pytest.approx(1.0, abs=0.10)
