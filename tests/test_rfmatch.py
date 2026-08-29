"""RF 정합망 역산의 왕복(round-trip) 검증.

Z_L 을 임의로 잡고 → 정합되는 소자값을 해석해로 구하고 → 역산이 원래 Z_L 을 회복하는지 확인.
모든 임피던스는 Z0 정규화 무차원.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics.rfmatch import (  # noqa: E402
    abcd_series, abcd_shunt, invert_load, match_quality, z_in, zl_L, zl_pi, zl_T,
)


def test_L_analytic_form():
    """L형 해석해 R = 1/(1+b²), X = b/(1+b²) − x_se 를 수치 역산이 재현하는가."""
    for b in (0.2, 0.8, 1.5, 3.0):
        for xs in (-1.2, 0.0, 0.7):
            z = zl_L(b, xs)
            assert z.real == pytest.approx(1.0 / (1 + b**2), rel=1e-10)
            assert z.imag == pytest.approx(b / (1 + b**2) - xs, rel=1e-10, abs=1e-12)


def test_L_roundtrip_matches_z0():
    """역산한 Z_L 을 순방향으로 넣으면 입력 임피던스가 정확히 Z0(=1)이어야 한다."""
    for b, xs in ((0.5, -0.9), (2.0, 0.3), (1.1, 1.4)):
        zl = zl_L(b, xs)
        M = abcd_shunt(1j * b) @ abcd_series(1j * xs)
        assert z_in(M, zl) == pytest.approx(1.0 + 0j, rel=1e-10, abs=1e-12)


def test_pi_roundtrip_matches_z0():
    for b1, xs, b2 in ((0.6, 1.3, 0.4), (1.2, 2.0, 0.9), (0.3, 0.8, 1.6)):
        zl = zl_pi(b1, xs, b2)
        M = abcd_shunt(1j * b1) @ abcd_series(1j * xs) @ abcd_shunt(1j * b2)
        assert z_in(M, zl) == pytest.approx(1.0 + 0j, rel=1e-10, abs=1e-12)


def test_T_roundtrip_matches_z0():
    for x1, bsh, x2 in ((-1.1, -0.7, -0.9), (-0.5, -1.5, -2.0), (-2.2, -0.4, -0.6)):
        zl = zl_T(x1, bsh, x2)
        M = abcd_series(1j * x1) @ abcd_shunt(1j * bsh) @ abcd_series(1j * x2)
        assert z_in(M, zl) == pytest.approx(1.0 + 0j, rel=1e-10, abs=1e-12)


def test_known_L_match_case():
    """고전 L형 매칭: R < Z0 을 Z0 로 올릴 때 Q = sqrt(Z0/R − 1) 관계 확인."""
    r_target = 0.1  # Z0 정규화 (= 5 Ω @ Z0=50)
    b = np.sqrt(1.0 / r_target - 1.0)  # R = 1/(1+b²) 로부터
    z = zl_L(b, 0.0)
    assert z.real == pytest.approx(r_target, rel=1e-12)
    # 순수 저항 부하를 정합하려면 직렬 리액턴스가 부하 리액턴스를 상쇄해야 한다
    xs_needed = z.imag
    z2 = zl_L(b, xs_needed)
    assert z2.imag == pytest.approx(0.0, abs=1e-12)


def test_invert_load_degenerate():
    """A − Z0·C = 0 인 축퇴 상황에서 NaN 을 반환하는가."""
    M = np.array([[1.0 + 0j, 0.5 + 0j], [1.0 + 0j, 1.0 + 0j]])
    z = invert_load(M)
    assert np.isnan(z.real)


def test_match_quality_perfect_and_known():
    q = match_quality(np.array([0.0]), np.array([100.0]))
    assert q.gamma_mag == pytest.approx(0.0)
    assert q.vswr == pytest.approx(1.0)
    # P_refl=4, P_load=96 → P_fwd=100, |Γ|=0.2, VSWR=1.5
    q2 = match_quality(np.array([4.0]), np.array([96.0]), other_is_delivered=True)
    assert q2.gamma_mag == pytest.approx(0.2, rel=1e-9)
    assert q2.vswr == pytest.approx(1.5, rel=1e-9)
