"""
Performance profiles for grid sizing.

Provides helpers to compute min cell size from basin dimensions using
an adjustable divisor and a minimum floor, plus simple named modes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal
import math


Mode = Literal['fast', 'balanced', 'accurate']


@dataclass(frozen=True)
class PerfProfile:
    name: Mode
    divisor: float  # larger divisor → finer min cell
    min_floor_m: float  # absolute lower bound on min cell size


DEFAULT_PROFILES: dict[Mode, PerfProfile] = {
    'fast': PerfProfile('fast', divisor=15.0, min_floor_m=2.0),
    'balanced': PerfProfile('balanced', divisor=25.0, min_floor_m=2.0),
    'accurate': PerfProfile('accurate', divisor=40.0, min_floor_m=2.0),
}


def get_profile(mode: Optional[str]) -> PerfProfile:
    key = str(mode or 'balanced').strip().lower()
    if key not in DEFAULT_PROFILES:
        key = 'balanced'
    return DEFAULT_PROFILES[key]  # type: ignore[return-value]


def compute_min_cell_size_from_basin(
    basin_length_m: float,
    basin_width_m: float,
    divisor: Optional[float] = None,
    min_floor_m: Optional[float] = None,
    mode: Optional[str] = None,
) -> float:
    """
    min_cell = max(min_floor, diagonal / divisor)

    - diagonal = sqrt(L^2 + W^2)
    - divisor: higher values give finer resolution
    - min_floor_m: absolute lower bound
    - mode: optional preset that sets default divisor and floor
    """
    prof = get_profile(mode)
    use_div = float(divisor if divisor is not None else prof.divisor)
    use_floor = float(min_floor_m if min_floor_m is not None else prof.min_floor_m)
    diag = math.hypot(float(basin_length_m), float(basin_width_m))
    # Guard against pathological values
    use_div = max(1.0, use_div)
    use_floor = max(0.1, use_floor)
    return max(use_floor, diag / use_div)
