"""ILSAX Hydrological Model — time-area routing with Horton infiltration.

Implements the ILSAX model as described in the ILSAX Reference
(June 2018, Section 8.3.2) using the **detailed** overland-flow mode:

* Three surface types: **paved** (DCIA), **supplementary**
  (indirectly-connected impervious), **grassed** (pervious).
* Time-of-entry for each surface is computed from the kinematic wave
  equation (Eq. 8.3, Ragan & Duru 1972):
      t_overland = 6.94 · (L · n*)^0.6 / (I^0.4 · S^0.3)
  plus a user-specified additional (constant) time.
* Depression storage treated as an initial loss for each surface type.
* Horton infiltration model for grassed areas using Watson's
  non-iterative method (Equations 8.7 & 8.8, ILSAX Reference).
* Linear time-area convolution routing per surface type.
* Soil types A–D with antecedent moisture conditions (AMC) 1–4.
"""

from __future__ import annotations

import math
from typing import List, Sequence

import numpy as np

from ..models.common import Catchment, Hyetograph
from ..models.results import HydrographResult

# ── Horton infiltration parameters (Table 8.6, ILSAX Reference) ────────────
# Soil types: 1 = A, 2 = B, 3 = C, 4 = D

HORTON_F0: dict[int, float] = {1: 250.0, 2: 200.0, 3: 125.0, 4: 75.0}  # mm/h
HORTON_FC: dict[int, float] = {1: 25.0, 2: 13.0, 3: 6.0, 4: 3.0}        # mm/h
HORTON_K: float = 2.0  # h⁻¹ (same for all soil types)

# Initial infiltration rates by (soil_type, AMC)
HORTON_INIT_RATE: dict[tuple[int, int], float] = {
    (1, 1): 250.0, (1, 2): 162.3, (1, 3): 83.6, (1, 4): 33.1,
    (2, 1): 200.0, (2, 2): 130.1, (2, 3): 66.3, (2, 4): 30.7,
    (3, 1): 125.0, (3, 2): 78.0,  (3, 3): 33.7, (3, 4): 6.6,
    (4, 1): 75.0,  (4, 2): 40.9,  (4, 3): 7.4,  (4, 4): 3.0,
}


# ── Helper: interpolate Horton parameters ────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a * (1.0 - t) + b * t


def _interpolate_simple(table: dict[int, float], key: float) -> float:
    """Linearly interpolate a soil-type-keyed table for non-integer keys."""
    lo = max(1, min(4, int(math.floor(key))))
    hi = max(1, min(4, int(math.ceil(key))))
    if lo == hi:
        return table[lo]
    return _lerp(table[lo], table[hi], key - lo)


def _get_horton_params(
    soil_type: float,
    amc: float,
) -> tuple[float, float, float, float]:
    """Return (f0, fc, k, fd_initial) for the given soil type and AMC.

    ``fd_initial`` is the accumulated diminishing infiltration at the start,
    derived from the AMC starting infiltration rate.
    """
    f0 = _interpolate_simple(HORTON_F0, soil_type)
    fc = _interpolate_simple(HORTON_FC, soil_type)
    k = HORTON_K

    # Bilinear interpolation of the initial infiltration rate
    s_lo = max(1, min(4, int(math.floor(soil_type))))
    s_hi = max(1, min(4, int(math.ceil(soil_type))))
    a_lo = max(1, min(4, int(math.floor(amc))))
    a_hi = max(1, min(4, int(math.ceil(amc))))

    def _rate(s: int, a: int) -> float:
        return HORTON_INIT_RATE.get((s, a), fc)

    sf = soil_type - s_lo if s_lo != s_hi else 0.0
    af = amc - a_lo if a_lo != a_hi else 0.0

    f_init = (
        _rate(s_lo, a_lo) * (1 - sf) * (1 - af)
        + _rate(s_hi, a_lo) * sf * (1 - af)
        + _rate(s_lo, a_hi) * (1 - sf) * af
        + _rate(s_hi, a_hi) * sf * af
    )

    # Accumulated diminishing infiltration at the starting AMC:
    #   Fd_0 = (f0 − f_init) / k
    fd_initial = max(0.0, (f0 - f_init) / k)

    return f0, fc, k, fd_initial


# ── Watson's non-iterative Horton infiltration ──────────────────────────

def _horton_excess(
    depths_mm: List[float],
    dt_hr: float,
    f0: float,
    fc: float,
    k: float,
    fd_initial: float,
) -> List[float]:
    """Return excess rainfall depths (mm) after Horton infiltration.

    Uses Watson's non-iterative method (Kinematic Wave Eq)
    which splits the Horton capacity into diminishing and constant
    components to avoid iteration.
    """
    fd = fd_initial  # accumulated diminishing infiltration (mm)
    excess: list[float] = []
    e_neg_kdt = math.exp(-k * dt_hr)
    max_diminishing = (f0 - fc) / k  # total area under diminishing curve

    for depth in depths_mm:
        # Remaining capacity in diminishing component
        remaining_dim = max(0.0, max_diminishing - fd)

        # Infiltration capacity for this timestep (Eq. 8.7)
        delta_f_cap = (1.0 - e_neg_kdt) * remaining_dim + fc * dt_hr

        # Actual infiltration = min(supply, capacity)
        actual = min(depth, delta_f_cap)

        # Update diminishing component (Eq. 8.8)
        if delta_f_cap > 1e-12:
            dim_portion = max(0.0, delta_f_cap - fc * dt_hr)
            fd += actual * (dim_portion / delta_f_cap)

        excess.append(max(0.0, depth - actual))

    return excess


# ── Kinematic wave overland flow time (Ragan & Duru Eq) ──────────────────

def _kinematic_wave_time(
    flow_path_length_m: float,
    flow_path_slope_pct: float,
    n_star: float,
    mean_intensity_mm_per_hr: float,
) -> float:
    """Compute overland flow travel time (minutes) using the kinematic wave
    equation from Ragan & Duru (1972), as implemented in Ragan & Duru Eq:

        t = 6.94 · (L · n*)^0.6 / (I^0.4 · S^0.3)

    Parameters
    ----------
    flow_path_length_m : float
        Overland flow path length in metres.
    flow_path_slope_pct : float
        Longitudinal slope of the flow path in percent (e.g. 2.0 = 2%).
    n_star : float
        Retardance coefficient (surface roughness, similar to Manning's n).
    mean_intensity_mm_per_hr : float
        Mean rainfall intensity over the storm duration, in mm/hr.

    Returns
    -------
    float
        Overland flow travel time in minutes. Returns 0.0 if any input
        is zero or negative (indicating no overland flow).
    """
    if (
        flow_path_length_m <= 0.0
        or flow_path_slope_pct <= 0.0
        or n_star <= 0.0
        or mean_intensity_mm_per_hr <= 0.0
    ):
        return 0.0

    L = flow_path_length_m
    S = flow_path_slope_pct / 100.0  # convert percent to m/m
    I = mean_intensity_mm_per_hr

    return 6.94 * (L * n_star) ** 0.6 / (I ** 0.4 * S ** 0.3)


def _compute_time_of_entry(
    additional_time_min: float,
    flow_path_length_m: float,
    flow_path_slope_pct: float,
    n_star: float,
    mean_intensity_mm_per_hr: float,
) -> float:
    """Compute total time of entry for a surface type (minutes).

    total = additional_time + kinematic_wave_time
    """
    t_overland = _kinematic_wave_time(
        flow_path_length_m, flow_path_slope_pct, n_star, mean_intensity_mm_per_hr
    )
    return additional_time_min + t_overland


# ── Depression-storage initial-loss bucket ───────────────────────────────

def _apply_depression_storage(
    depths_mm: List[float],
    storage_mm: float,
) -> List[float]:
    """Subtract depression storage as an initial loss from a depth series."""
    remaining = storage_mm
    result: list[float] = []
    for d in depths_mm:
        if remaining > 0.0:
            absorbed = min(d, remaining)
            remaining -= absorbed
            result.append(d - absorbed)
        else:
            result.append(d)
    return result


# ── Linear time-area histogram ───────────────────────────────────────────

def _time_area_histogram(
    time_of_entry_min: float,
    dt_min: float,
) -> np.ndarray:
    """Build a linear time-area histogram (fractional areas summing to 1).

    A linear time-area relationship assumes contributing area grows
    uniformly from 0 at t = 0 to A at t = t_entry.  The histogram
    ``h[i]`` gives the fraction of total area whose travel time falls in
    the *i*-th time-step.
    """
    if time_of_entry_min <= 0.0 or dt_min <= 0.0:
        return np.array([1.0])

    n_full = int(time_of_entry_min / dt_min)
    remainder = time_of_entry_min - n_full * dt_min

    fracs: list[float] = []
    if n_full > 0:
        frac = dt_min / time_of_entry_min
        fracs = [frac] * n_full
    if remainder > 1e-9:
        fracs.append(remainder / time_of_entry_min)
    if not fracs:
        fracs = [1.0]

    return np.asarray(fracs, dtype=float)


# ── Time-area convolution ────────────────────────────────────────────────

def _convolve(
    excess_mm: List[float],
    hist: np.ndarray,
    area_ha: float,
    dt_hr: float,
) -> np.ndarray:
    """Convolve excess rainfall with a time-area histogram → discharge (m³/s).

    :math:`Q_n = \\frac{1}{360}\\sum_i h_i \\cdot I_{n-i} \\cdot A`

    where *I* is excess intensity (mm/h), *h* fractional area, *A* in ha.
    The factor 360 converts ha·mm/h → m³/s.
    """
    intensities = np.asarray(excess_mm, dtype=float) / dt_hr  # mm → mm/h
    raw = np.convolve(intensities, hist)  # fractional-area-weighted intensity
    return raw * area_ha / 360.0


# ── Public API ───────────────────────────────────────────────────────────

def simulate_catchment_runoff(
    catchment: Catchment,
    hyetograph: Hyetograph,
) -> Sequence[float]:
    """Compute catchment runoff discharge (m³/s) using the ILSAX model.

    Implements three-surface-type time-area routing with Horton
    infiltration as per ILSAX Reference.

    Time-of-entry for each surface type is computed from the kinematic
    wave equation (Eq. 8.3) using flow path length, slope and retardance
    coefficient n*, plus an additional constant time.
    """
    dt_min = hyetograph.timestep_minutes
    dt_hr = dt_min / 60.0
    rainfall = list(hyetograph.depths_mm)
    n_rain = len(rainfall)
    area = catchment.area_ha

    # Mean rainfall intensity for kinematic wave time calculation
    total_depth = sum(rainfall)
    storm_duration_hr = n_rain * dt_hr
    mean_intensity = total_depth / storm_duration_hr if storm_duration_hr > 0 else 0.0

    # ── Compute times of entry via kinematic wave equation ───────────
    paved_te = _compute_time_of_entry(
        catchment.paved_additional_time_minutes,
        catchment.paved_flow_path_length_m,
        catchment.paved_flow_path_slope_pct,
        catchment.paved_n_star,
        mean_intensity,
    )
    supp_te = _compute_time_of_entry(
        catchment.supplementary_additional_time_minutes,
        catchment.supplementary_flow_path_length_m,
        catchment.supplementary_flow_path_slope_pct,
        catchment.supplementary_n_star,
        mean_intensity,
    )
    grass_te = _compute_time_of_entry(
        catchment.grassed_additional_time_minutes,
        catchment.grassed_flow_path_length_m,
        catchment.grassed_flow_path_slope_pct,
        catchment.grassed_n_star,
        mean_intensity,
    )

    # ── 1. Paved area (directly-connected impervious) ────────────────
    paved_a = area * catchment.paved_fraction
    if paved_a > 1e-12:
        paved_excess = _apply_depression_storage(
            rainfall, catchment.paved_depression_storage_mm
        )
        paved_hist = _time_area_histogram(paved_te, dt_min)
        paved_q = _convolve(paved_excess, paved_hist, paved_a, dt_hr)
    else:
        paved_q = np.zeros(n_rain)

    # ── 2. Supplementary area (indirectly-connected impervious) ──────
    supp_a = area * catchment.supplementary_fraction
    if supp_a > 1e-12:
        supp_excess = _apply_depression_storage(
            rainfall, catchment.supplementary_depression_storage_mm
        )
        supp_hist = _time_area_histogram(supp_te, dt_min)
        supp_q = _convolve(supp_excess, supp_hist, supp_a, dt_hr)
    else:
        supp_q = np.zeros(n_rain)

    # ── 3. Grassed area (pervious, Horton infiltration) ──────────────
    grass_a = area * catchment.grassed_fraction
    if grass_a > 1e-12:
        f0, fc, k, fd0 = _get_horton_params(
            catchment.soil_type, catchment.amc
        )
        after_horton = _horton_excess(rainfall, dt_hr, f0, fc, k, fd0)
        grass_excess = _apply_depression_storage(
            after_horton, catchment.grassed_depression_storage_mm
        )
        grass_hist = _time_area_histogram(grass_te, dt_min)
        grass_q = _convolve(grass_excess, grass_hist, grass_a, dt_hr)
    else:
        grass_q = np.zeros(n_rain)

    # ── 4. Combine (supplementary added to grassed, then + paved) ────
    max_len = max(len(paved_q), len(supp_q), len(grass_q))

    def _pad(a: np.ndarray) -> np.ndarray:
        if len(a) < max_len:
            return np.pad(a, (0, max_len - len(a)))
        return a

    total_q = _pad(paved_q) + _pad(supp_q) + _pad(grass_q)
    return total_q.tolist()


def summarise_hydrograph(
    aep,
    duration_minutes: int,
    pattern_rank: int,
    hyetograph: Hyetograph,
    discharge_cms: Sequence[float],
) -> HydrographResult:
    """Derive peak, volume and time-to-peak from a computed hydrograph."""
    dt_min = hyetograph.timestep_minutes
    dt_sec = dt_min * 60.0
    volumes = [q * dt_sec for q in discharge_cms]
    runoff_volume_m3 = sum(volumes)
    peak_discharge = max(discharge_cms) if discharge_cms else 0.0
    if discharge_cms:
        peak_index = int(np.argmax(discharge_cms))
        time_to_peak = (peak_index + 1) * dt_min
    else:
        time_to_peak = 0.0
    return HydrographResult(
        aep=aep,
        duration_minutes=duration_minutes,
        pattern_rank=pattern_rank,
        discharge_cms=list(discharge_cms),
        timestep_minutes=dt_min,
        peak_discharge_cms=peak_discharge,
        runoff_volume_m3=runoff_volume_m3,
        time_to_peak_minutes=time_to_peak,
    )
