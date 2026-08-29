"""RF 정합망(matching network)에서 플라즈마 부하 임피던스를 역산한다.

원리
  무손실 2포트 정합망의 ABCD 행렬을 M = [[A, B], [C, D]] 라 하면
      Z_in = (A·Z_L + B) / (C·Z_L + D)
  정합 상태에서는 Z_in = Z0 (발전기 임피던스) 이므로
      A·Z_L + B = Z0·(C·Z_L + D)
      → **Z_L = (Z0·D − B) / (A − Z0·C)**
  즉 토폴로지와 소자값을 알면 두 커패시터 위치로부터 Z_L = R + jX 가 유일하게 결정된다.

구성 요소 ABCD
  직렬 임피던스 Z : [[1, Z], [0, 1]]
  병렬 어드미턴스 Y: [[1, 0], [Y, 1]]

이 데이터셋에서 미지인 것 (가정 금지 대상)
  - RF 주파수 ω               : 채널 없음
  - 발전기 임피던스 Z0         : 관례상 50 Ω 이나 데이터에 없음
  - 고정 소자값 (인덕터 등)     : 채널 없음
  - 커패시터 "위치(%) → 정전용량(F)" 변환 : 채널 없음, 통상 비선형
  따라서 절대 임피던스는 산출 불가능하다. 본 모듈은 무차원 정규화 형태로 계산하고,
  상위 스크립트가 미지수를 소인(sweep)해 부호·상대변화의 강건성을 확인한다.

단위: 임피던스는 Z0 로 정규화된 무차원량. 정규화하지 않은 값을 쓸 때는 Ω 로 명시한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------- ABCD 기본 요소


def abcd_series(z: complex) -> np.ndarray:
    """직렬 임피던스 z 의 ABCD 행렬 (z 는 Z0 정규화 무차원)."""
    return np.array([[1.0 + 0j, z], [0j, 1.0 + 0j]])


def abcd_shunt(y: complex) -> np.ndarray:
    """병렬 어드미턴스 y 의 ABCD 행렬 (y 는 1/Z0 정규화 무차원)."""
    return np.array([[1.0 + 0j, 0j], [y, 1.0 + 0j]])


def invert_load(M: np.ndarray) -> complex:
    """정합 조건 Z_in = Z0 에서 부하 임피던스를 역산한다.

    Args:
        M: 정합망 ABCD 행렬 (Z0 정규화)

    Returns:
        Z_L / Z0  (무차원 복소 임피던스)
    """
    A, B, C, D = M[0, 0], M[0, 1], M[1, 0], M[1, 1]
    denom = A - C  # Z0 정규화계에서는 Z0 = 1
    if abs(denom) < 1e-15:
        return complex(np.nan, np.nan)
    return (D - B) / denom


# ---------------------------------------------------------------- 토폴로지 3종
# 규약: 발전기 → (정합망) → 부하. 두 가변 커패시터를 c1, c2 로 둔다.
# 모든 리액턴스·서셉턴스는 Z0 정규화 무차원.


def zl_L(b_sh: float, x_se: float) -> complex:
    """L형: 발전기측 병렬 커패시터 → 직렬 가지(고정 L + 가변 C).

    Args:
        b_sh: 병렬 커패시터 서셉턴스 ω·C_sh·Z0 (무차원, > 0)
        x_se: 직렬 가지 리액턴스 (ω·L − 1/(ω·C_se))/Z0 (무차원, 부호 자유)

    Returns:
        Z_L/Z0

    해석해 (직접 유도 가능):
        R/Z0 = 1/(1 + b_sh²),  X/Z0 = b_sh/(1 + b_sh²) − x_se
    """
    M = abcd_shunt(1j * b_sh) @ abcd_series(1j * x_se)
    return invert_load(M)


def zl_pi(b1: float, x_se: float, b2: float) -> complex:
    """Π형: 병렬 C1 → 직렬 L(고정) → 병렬 C2 → 부하.

    Args:
        b1: 발전기측 병렬 서셉턴스 (무차원)
        x_se: 직렬 고정 인덕터 리액턴스 (무차원, > 0)
        b2: 부하측 병렬 서셉턴스 (무차원)

    Returns:
        Z_L/Z0
    """
    M = abcd_shunt(1j * b1) @ abcd_series(1j * x_se) @ abcd_shunt(1j * b2)
    return invert_load(M)


def zl_T(x1: float, b_sh: float, x2: float) -> complex:
    """T형: 직렬 C1 → 병렬 L(고정) → 직렬 C2 → 부하.

    Args:
        x1: 발전기측 직렬 리액턴스 (무차원, 커패시터면 < 0)
        b_sh: 병렬 고정 인덕터 서셉턴스 (무차원, 인덕터면 < 0)
        x2: 부하측 직렬 리액턴스 (무차원)

    Returns:
        Z_L/Z0
    """
    M = abcd_series(1j * x1) @ abcd_shunt(1j * b_sh) @ abcd_series(1j * x2)
    return invert_load(M)


# ---------------------------------------------------------------- 순방향 확인용


def z_in(M: np.ndarray, zl: complex) -> complex:
    """부하 zl (Z0 정규화) 을 정합망 M 으로 본 입력 임피던스 (Z0 정규화)."""
    A, B, C, D = M[0, 0], M[0, 1], M[1, 0], M[1, 1]
    return (A * zl + B) / (C * zl + D)


# ---------------------------------------------------------------- 정합 품질 지표


@dataclass(frozen=True)
class MatchQuality:
    """반사 지표.

    Attributes:
        gamma_mag: 반사계수 크기 |Γ| (무차원, 0 = 완전정합)
        vswr: 정재파비 (무차원, 1 = 완전정합)
        refl_frac: 반사 전력 비율 P_refl/P_fwd (무차원)
    """

    gamma_mag: float
    vswr: float
    refl_frac: float


def match_quality(p_refl: np.ndarray, p_other: np.ndarray,
                  other_is_delivered: bool = True) -> MatchQuality:
    """반사 전력으로부터 |Γ| 와 VSWR 을 산출한다.

    Args:
        p_refl: 반사 전력 (원시 단위)
        p_other: 'LoadPower' 채널 값 (원시 단위)
        other_is_delivered: True 면 LoadPower = 전달전력 (P_fwd = P_load + P_refl),
            False 면 LoadPower = 순방향전력 (P_fwd = P_load)

    Returns:
        MatchQuality (배열 평균 기준)

    주의: 두 해석 중 어느 쪽인지는 데이터에 명시되어 있지 않다. 상위 스크립트에서 둘 다 산출한다.
    """
    p_fwd = p_other + p_refl if other_is_delivered else p_other
    frac = np.clip(np.asarray(p_refl, float) / np.maximum(np.asarray(p_fwd, float), 1e-12),
                   0.0, 0.999999)
    g = np.sqrt(frac)
    return MatchQuality(gamma_mag=float(np.mean(g)),
                        vswr=float(np.mean((1 + g) / (1 - g))),
                        refl_frac=float(np.mean(frac)))
