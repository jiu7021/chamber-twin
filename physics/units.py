"""단위 환산 상수 및 함수 모음.

내부 계산은 SI 단일계(Pa, m^3, m^3/s, Pa*m^3/s, s, K)만 사용한다.
환산은 입출력 경계에서만 이 모듈을 통해 수행한다.
"""

# 1 Torr = 133.322 Pa (표준·규정: 정의값, 수은주 밀도 기반 물리 정의)
TORR_TO_PA = 133.322

# 1 mbar = 100 Pa (표준·규정: SI 정의, 1 bar = 100000 Pa)
MBAR_TO_PA = 100.0

# 1 L/s = 1e-3 m^3/s (표준·규정: SI 정의, 1 L = 1e-3 m^3)
LPS_TO_M3S = 1e-3

# 1 sccm(표준상태 cm^3/min)을 스루풋(Pa*m^3/s)으로 환산
# 유도: 1 cm^3/min @ 101325 Pa(표준대기압) = 1e-6 m^3 / 60 s = 1.667e-8 m^3/s
#       스루풋 Q = P * (dV/dt) = 101325 Pa * 1.667e-8 m^3/s = 1.69e-3 Pa*m^3/s
SCCM_TO_PAM3S = 1.69e-3


def torr_to_pa(value_torr: float) -> float:
    """Torr -> Pa 변환.

    Args:
        value_torr: 압력, 단위 Torr

    Returns:
        압력, 단위 Pa
    """
    return value_torr * TORR_TO_PA


def pa_to_torr(value_pa: float) -> float:
    """Pa -> Torr 변환.

    Args:
        value_pa: 압력, 단위 Pa

    Returns:
        압력, 단위 Torr
    """
    return value_pa / TORR_TO_PA


def mtorr_to_pa(value_mtorr: float) -> float:
    """mTorr -> Pa 변환.

    Args:
        value_mtorr: 압력, 단위 mTorr

    Returns:
        압력, 단위 Pa
    """
    return value_mtorr * 1e-3 * TORR_TO_PA


def pa_to_mtorr(value_pa: float) -> float:
    """Pa -> mTorr 변환.

    Args:
        value_pa: 압력, 단위 Pa

    Returns:
        압력, 단위 mTorr
    """
    return value_pa / TORR_TO_PA * 1e3


def mbar_to_pa(value_mbar: float) -> float:
    """mbar -> Pa 변환.

    Args:
        value_mbar: 압력, 단위 mbar

    Returns:
        압력, 단위 Pa
    """
    return value_mbar * MBAR_TO_PA


def pa_to_mbar(value_pa: float) -> float:
    """Pa -> mbar 변환.

    Args:
        value_pa: 압력, 단위 Pa

    Returns:
        압력, 단위 mbar
    """
    return value_pa / MBAR_TO_PA


def lps_to_m3s(value_lps: float) -> float:
    """L/s -> m^3/s 변환 (배기속도 등 체적유량).

    Args:
        value_lps: 체적유량, 단위 L/s

    Returns:
        체적유량, 단위 m^3/s
    """
    return value_lps * LPS_TO_M3S


def m3s_to_lps(value_m3s: float) -> float:
    """m^3/s -> L/s 변환 (배기속도 등 체적유량).

    Args:
        value_m3s: 체적유량, 단위 m^3/s

    Returns:
        체적유량, 단위 L/s
    """
    return value_m3s / LPS_TO_M3S


def sccm_to_pam3s(value_sccm: float) -> float:
    """sccm -> Pa*m^3/s 변환 (가스 유량을 스루풋으로).

    Args:
        value_sccm: 가스 유량, 단위 sccm (표준상태 cm^3/min)

    Returns:
        스루풋, 단위 Pa*m^3/s
    """
    return value_sccm * SCCM_TO_PAM3S


def pam3s_to_sccm(value_pam3s: float) -> float:
    """Pa*m^3/s -> sccm 변환.

    Args:
        value_pam3s: 스루풋, 단위 Pa*m^3/s

    Returns:
        가스 유량, 단위 sccm
    """
    return value_pam3s / SCCM_TO_PAM3S
