"""단위 환산 왕복 테스트: A -> 변환 -> 역변환 -> A."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from physics import units


def test_torr_roundtrip():
    x = 7.5
    assert math.isclose(units.pa_to_torr(units.torr_to_pa(x)), x, rel_tol=1e-12)


def test_mtorr_roundtrip():
    x = 12.3
    assert math.isclose(units.pa_to_mtorr(units.mtorr_to_pa(x)), x, rel_tol=1e-12)


def test_mbar_roundtrip():
    x = 3.14
    assert math.isclose(units.pa_to_mbar(units.mbar_to_pa(x)), x, rel_tol=1e-12)


def test_lps_roundtrip():
    x = 200.0
    assert math.isclose(units.m3s_to_lps(units.lps_to_m3s(x)), x, rel_tol=1e-12)


def test_sccm_roundtrip():
    x = 50.0
    assert math.isclose(units.pam3s_to_sccm(units.sccm_to_pam3s(x)), x, rel_tol=1e-12)


def test_known_values():
    # 1 Torr = 133.322 Pa (표준값)
    assert math.isclose(units.torr_to_pa(1.0), 133.322, rel_tol=1e-9)
    # 1 mbar = 100 Pa
    assert math.isclose(units.mbar_to_pa(1.0), 100.0, rel_tol=1e-9)
    # 1 L/s = 1e-3 m^3/s
    assert math.isclose(units.lps_to_m3s(1.0), 1e-3, rel_tol=1e-9)
    # 1 sccm = 1.69e-3 Pa*m^3/s
    assert math.isclose(units.sccm_to_pam3s(1.0), 1.69e-3, rel_tol=1e-9)
