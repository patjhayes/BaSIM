"""ARR Climate Change Factors for design rainfall adjustment.

Implements the rainfall scaling factors from Australian Rainfall and Runoff
(ARR) 2019, based on CMIP6 SSP scenarios and IPCC AR6 temperature
projections.

The live path fetches the ARR Data Hub's "Climate Change Adjusted IFD
Datasets" layer (per-duration, per-AEP adjusted depths for 2030/2050/2090)
and derives an exact factor as adjusted_depth / current_baseline_depth for
every (duration, AEP) pair actually being designed for, interpolating
linearly between the two bracketing epochs. If the live fetch is
unavailable, this falls back to a frozen, nationally-uniform ARR Data Hub
(2024_v1) snapshot expressed as 10 duration bins.

Usage:
    design_rainfalls = apply_climate_change_factors(
        design_rainfalls, "SSP2-4.5", 2050, arr_client=arr_client, coordinate=coordinate,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models.common import Coordinate
    from .services.arr import ARRDataHubClient

LOGGER = logging.getLogger(__name__)

# ── Duration bins (column headers from ARR Data Hub) ─────────────────────
# Each bin maps to a maximum duration in minutes.
# The "<1 hour" bin covers all durations ≤ 60 min.
# The ">24 Hours" bin covers all durations ≥ 1440 min.
_DURATION_BINS_MINUTES = [60, 90, 120, 180, 270, 360, 540, 720, 1080, 1440]

EPOCHS = [2030, 2040, 2050, 2060, 2070, 2080, 2090, 2100]

SSP_SCENARIOS = ["SSP1-2.6", "SSP2-4.5", "SSP3-7.0", "SSP5-8.5"]

# ── Factor tables: SSP → epoch → list of 10 factors (one per duration bin) ─
# Index order matches _DURATION_BINS_MINUTES. Used only as an offline
# fallback when the live ARR Data Hub fetch is unavailable.
_FALLBACK_FACTORS: dict[str, dict[int, list[float]]] = {
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
    """Return the offline-fallback multiplicative climate change factor.

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

    epoch_table = _FALLBACK_FACTORS.get(ssp)
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


def _interpolate_epoch(values_by_epoch: dict[int, float], epoch: int) -> Optional[float]:
    """Linearly interpolate/clamp a value across the epochs the Data Hub provides."""
    if not values_by_epoch:
        return None
    if epoch in values_by_epoch:
        return values_by_epoch[epoch]
    sorted_epochs = sorted(values_by_epoch)
    if epoch < sorted_epochs[0]:
        return values_by_epoch[sorted_epochs[0]]
    if epoch > sorted_epochs[-1]:
        return values_by_epoch[sorted_epochs[-1]]
    lo = max(e for e in sorted_epochs if e <= epoch)
    hi = min(e for e in sorted_epochs if e >= epoch)
    if lo == hi:
        return values_by_epoch[lo]
    t = (epoch - lo) / (hi - lo)
    return values_by_epoch[lo] + t * (values_by_epoch[hi] - values_by_epoch[lo])


def _fetch_live_factors(
    design_rainfalls: list,
    ssp: str,
    epoch: int,
    arr_client: "ARRDataHubClient",
    coordinate: "Coordinate",
) -> Optional[dict[tuple, float]]:
    """Return {(duration_minutes, aep): factor} from a live ARR Data Hub fetch, or None on failure."""
    durations = sorted({dr.duration_minutes for dr in design_rainfalls})
    ae_ps = sorted({dr.aep for dr in design_rainfalls}, key=lambda a: a.value)
    try:
        adjusted_by_epoch_ssp = arr_client.fetch_climate_adjusted_ifds(coordinate, durations, ae_ps)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Live ARR climate-change-adjusted IFD fetch failed (%s); falling back to the "
            "bundled national CCF snapshot",
            exc,
            exc_info=True,
        )
        return None

    # Group the adjusted depths available for this SSP by epoch, per (duration, aep) key.
    by_key_by_epoch: dict[tuple, dict[int, float]] = {}
    for (table_ssp, table_epoch), rainfalls in adjusted_by_epoch_ssp.items():
        if table_ssp != ssp:
            continue
        for dr in rainfalls:
            by_key_by_epoch.setdefault((dr.duration_minutes, dr.aep), {})[table_epoch] = dr.depth_mm

    if not by_key_by_epoch:
        LOGGER.warning("No ARR CC-adjusted IFD data found for SSP '%s'; using fallback CCF table", ssp)
        return None

    factors: dict[tuple, float] = {}
    for dr in design_rainfalls:
        key = (dr.duration_minutes, dr.aep)
        adjusted_depth = _interpolate_epoch(by_key_by_epoch.get(key, {}), epoch)
        if adjusted_depth is None or dr.depth_mm <= 0:
            continue
        factors[key] = adjusted_depth / dr.depth_mm
    return factors or None


def apply_climate_change_factors(
    design_rainfalls: list,
    ssp: Optional[str],
    epoch: Optional[int],
    arr_client: Optional["ARRDataHubClient"] = None,
    coordinate: Optional["Coordinate"] = None,
) -> list:
    """Apply climate change factors to a list of DesignRainfall objects.

    Returns a **new** list of DesignRainfall objects with scaled depths and
    intensities. The input objects are not mutated. If ssp is
    None/Historical, returns the list unchanged (factor = 1.0).

    When ``arr_client`` and ``coordinate`` are supplied, factors are derived
    from a live ARR Data Hub fetch of the exact (duration, AEP) adjusted
    depths; otherwise (or if that fetch fails) the bundled national CCF
    snapshot (``get_climate_change_factor``) is used.
    """
    if ssp is None or ssp.lower() in ("historical", "none", ""):
        return design_rainfalls

    if epoch is None:
        return design_rainfalls

    from dataclasses import replace

    live_factors = None
    if arr_client is not None and coordinate is not None:
        live_factors = _fetch_live_factors(design_rainfalls, ssp, epoch, arr_client, coordinate)

    adjusted = []
    for dr in design_rainfalls:
        if live_factors is not None and (dr.duration_minutes, dr.aep) in live_factors:
            factor = live_factors[(dr.duration_minutes, dr.aep)]
        else:
            factor = get_climate_change_factor(ssp, epoch, dr.duration_minutes)
        adjusted.append(
            replace(
                dr,
                depth_mm=dr.depth_mm * factor,
                intensity_mm_per_hr=dr.intensity_mm_per_hr * factor,
            )
        )
    return adjusted
