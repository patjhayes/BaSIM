"""ARR Climate Change Factors for design rainfall adjustment.

Implements the rainfall scaling factors from Australian Rainfall and Runoff
(ARR) 2019, based on CMIP6 SSP scenarios and IPCC AR6 temperature
projections.  These factors are **nationally uniform** (same for all
Australian locations) and are applied as multiplicative adjustments to
the historical IFD design rainfall depths.

Reference:
    ARR Datahub — Climate Change Factors layer
    ARR Book 1, Chapter 6, Section 1 (Equation 1.6.1)
    IPCC AR6 Synthesis Report temperature projections re-baselined to the
    1961–1990 Australian baseline.

Usage:
    factor = get_climate_change_factor("SSP2-4.5", 2050, duration_minutes=60)
    adjusted_depth = historical_depth * factor

The factor tables below were sourced from the ARR Data Hub (version 2024_v1)
and are identical for all Australian coordinates.
"""

from __future__ import annotations

from typing import Optional

# ── Duration bins (column headers from ARR Data Hub) ─────────────────────
# Each bin maps to a maximum duration in minutes.
# The "<1 hour" bin covers all durations ≤ 60 min.
# The ">24 Hours" bin covers all durations ≥ 1440 min.
_DURATION_BINS_MINUTES = [60, 90, 120, 180, 270, 360, 540, 720, 1080, 1440]

EPOCHS = [2030, 2040, 2050, 2060, 2070, 2080, 2090, 2100]

SSP_SCENARIOS = ["SSP1-2.6", "SSP2-4.5", "SSP3-7.0", "SSP5-8.5"]

# ── Factor tables: SSP → epoch → list of 10 factors (one per duration bin) ─
# Index order matches _DURATION_BINS_MINUTES.
_FACTORS: dict[str, dict[int, list[float]]] = {
    "SSP1-2.6": {
        2030: [1.18, 1.17, 1.16, 1.14, 1.13, 1.12, 1.12, 1.11, 1.10, 1.10],
        2040: [1.21, 1.19, 1.18, 1.16, 1.15, 1.14, 1.13, 1.12, 1.11, 1.11],
        2050: [1.25, 1.23, 1.22, 1.20, 1.18, 1.17, 1.16, 1.15, 1.14, 1.13],
        2060: [1.26, 1.24, 1.22, 1.20, 1.19, 1.18, 1.16, 1.15, 1.14, 1.14],
        2070: [1.27, 1.25, 1.23, 1.21, 1.19, 1.18, 1.17, 1.16, 1.15, 1.14],
        2080: [1.27, 1.25, 1.23, 1.21, 1.19, 1.18, 1.17, 1.16, 1.15, 1.14],
        2090: [1.26, 1.24, 1.22, 1.20, 1.19, 1.18, 1.16, 1.15, 1.14, 1.14],
        2100: [1.25, 1.23, 1.21, 1.19, 1.18, 1.17, 1.15, 1.14, 1.13, 1.13],
    },
    "SSP2-4.5": {
        2030: [1.18, 1.17, 1.16, 1.14, 1.13, 1.12, 1.12, 1.11, 1.10, 1.10],
        2040: [1.23, 1.21, 1.20, 1.18, 1.16, 1.16, 1.15, 1.14, 1.13, 1.12],
        2050: [1.29, 1.27, 1.25, 1.23, 1.21, 1.20, 1.19, 1.18, 1.16, 1.16],
        2060: [1.34, 1.31, 1.29, 1.26, 1.24, 1.23, 1.21, 1.20, 1.18, 1.18],
        2070: [1.37, 1.34, 1.32, 1.29, 1.27, 1.25, 1.23, 1.22, 1.20, 1.19],
        2080: [1.40, 1.36, 1.34, 1.31, 1.28, 1.27, 1.25, 1.23, 1.22, 1.21],
        2090: [1.42, 1.38, 1.36, 1.32, 1.30, 1.28, 1.26, 1.24, 1.23, 1.22],
        2100: [1.44, 1.40, 1.38, 1.34, 1.31, 1.29, 1.27, 1.26, 1.24, 1.23],
    },
    "SSP3-7.0": {
        2030: [1.19, 1.18, 1.17, 1.15, 1.14, 1.13, 1.12, 1.11, 1.10, 1.10],
        2040: [1.25, 1.23, 1.22, 1.20, 1.18, 1.17, 1.16, 1.15, 1.14, 1.13],
        2050: [1.32, 1.29, 1.28, 1.25, 1.23, 1.22, 1.20, 1.19, 1.17, 1.17],
        2060: [1.39, 1.35, 1.33, 1.30, 1.27, 1.26, 1.24, 1.22, 1.21, 1.20],
        2070: [1.46, 1.41, 1.39, 1.35, 1.32, 1.30, 1.28, 1.26, 1.24, 1.23],
        2080: [1.55, 1.49, 1.46, 1.42, 1.38, 1.36, 1.33, 1.31, 1.28, 1.27],
        2090: [1.64, 1.57, 1.53, 1.48, 1.44, 1.41, 1.38, 1.35, 1.33, 1.31],
        2100: [1.73, 1.65, 1.60, 1.55, 1.50, 1.47, 1.43, 1.40, 1.37, 1.36],
    },
    "SSP5-8.5": {
        2030: [1.20, 1.18, 1.17, 1.16, 1.14, 1.13, 1.13, 1.12, 1.11, 1.11],
        2040: [1.26, 1.24, 1.22, 1.20, 1.18, 1.17, 1.16, 1.15, 1.14, 1.14],
        2050: [1.34, 1.31, 1.29, 1.26, 1.24, 1.23, 1.21, 1.20, 1.18, 1.18],
        2060: [1.42, 1.38, 1.35, 1.32, 1.29, 1.28, 1.26, 1.24, 1.22, 1.21],
        2070: [1.52, 1.47, 1.43, 1.40, 1.36, 1.34, 1.31, 1.29, 1.27, 1.26],
        2080: [1.63, 1.57, 1.52, 1.48, 1.43, 1.40, 1.37, 1.35, 1.33, 1.31],
        2090: [1.77, 1.69, 1.64, 1.58, 1.52, 1.49, 1.45, 1.42, 1.39, 1.37],
        2100: [1.86, 1.77, 1.71, 1.64, 1.58, 1.54, 1.50, 1.47, 1.43, 1.41],
    },
}


def _duration_bin_index(duration_minutes: int) -> int:
    """Return the index into _DURATION_BINS_MINUTES for a given duration.

    Durations ≤ 60 min map to index 0 ("<1 hour").
    Durations ≥ 1440 min map to index 9 (">24 Hours").
    Intermediate durations snap to the nearest bin.
    """
    for i, upper in enumerate(_DURATION_BINS_MINUTES):
        if duration_minutes <= upper:
            return i
    return len(_DURATION_BINS_MINUTES) - 1  # ≥ 24 hours


def get_climate_change_factor(
    ssp: str,
    epoch: int,
    duration_minutes: int,
) -> float:
    """Return the multiplicative climate change factor for rainfall.

    Parameters
    ----------
    ssp : str
        SSP scenario label, e.g. ``"SSP2-4.5"``.  Use ``"Historical"`` or
        ``None`` to skip adjustment (returns 1.0).
    epoch : int
        Planning horizon year, e.g. 2050.
    duration_minutes : int
        Storm duration in minutes.

    Returns
    -------
    float
        Multiplicative factor to apply to IFD design rainfall depth.
        Historical / unadjusted returns 1.0.
    """
    if ssp is None or ssp.lower() in ("historical", "none", ""):
        return 1.0

    ssp_upper = ssp.upper().replace("SSP", "SSP")
    # Normalise label
    for canonical in SSP_SCENARIOS:
        if canonical.upper() == ssp_upper:
            ssp = canonical
            break
    else:
        raise ValueError(
            f"Unknown SSP scenario '{ssp}'. "
            f"Valid options: {SSP_SCENARIOS + ['Historical']}"
        )

    epoch_table = _FACTORS.get(ssp)
    if epoch_table is None:
        raise ValueError(f"No factor table for SSP scenario '{ssp}'")

    if epoch in epoch_table:
        factors = epoch_table[epoch]
    else:
        # Interpolate between bracketing epochs
        sorted_epochs = sorted(epoch_table.keys())
        if epoch < sorted_epochs[0]:
            factors = epoch_table[sorted_epochs[0]]
        elif epoch > sorted_epochs[-1]:
            factors = epoch_table[sorted_epochs[-1]]
        else:
            lo = max(e for e in sorted_epochs if e <= epoch)
            hi = min(e for e in sorted_epochs if e >= epoch)
            if lo == hi:
                factors = epoch_table[lo]
            else:
                t = (epoch - lo) / (hi - lo)
                f_lo = epoch_table[lo]
                f_hi = epoch_table[hi]
                factors = [f_lo[j] + t * (f_hi[j] - f_lo[j]) for j in range(len(f_lo))]

    idx = _duration_bin_index(duration_minutes)
    return factors[idx]


def apply_climate_change_factors(
    design_rainfalls: list,
    ssp: Optional[str],
    epoch: Optional[int],
) -> list:
    """Apply climate change factors in-place to a list of DesignRainfall objects.

    If ssp is None/Historical, returns the list unchanged (factor = 1.0).
    """
    if ssp is None or ssp.lower() in ("historical", "none", ""):
        return design_rainfalls

    if epoch is None:
        return design_rainfalls

    for dr in design_rainfalls:
        factor = get_climate_change_factor(ssp, epoch, dr.duration_minutes)
        dr.depth_mm *= factor
        dr.intensity_mm_per_hr *= factor

    return design_rainfalls
