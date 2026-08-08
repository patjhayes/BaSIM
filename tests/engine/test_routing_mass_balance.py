"""Mass-balance test for basin routing.

Verifies the fundamental conservation law at every timestep:

    cumulative_inflow  ≈  storage  +  cumulative_infiltration  +  cumulative_overflow

Also covers the pooling/overtopping case: when the basin overtops the depth
exceeds the design max depth and a spilling event is flagged, but mass is
still conserved (the overflow volume accounts for water above the crest).
"""

from __future__ import annotations

import math

from soakhydro.models.common import AEP
from soakhydro.models.results import HydrographResult
from soakhydro.hydraulics.routing import route_through_basin


def _synthetic_hydrograph(
    peak_cms: float = 0.5,
    n_steps: int = 60,
    timestep_minutes: float = 5.0,
    duration_minutes: int = 60,
    pattern_rank: int = 4,
) -> HydrographResult:
    """A triangular hydrograph peaking at step n_steps//2."""
    half = n_steps // 2
    discharge = []
    for i in range(n_steps):
        if i <= half:
            q = peak_cms * (i / max(half, 1))
        else:
            q = peak_cms * (1.0 - (i - half) / max(n_steps - half, 1))
        discharge.append(max(0.0, q))
    return HydrographResult(
        aep=AEP.AEP_5,
        duration_minutes=duration_minutes,
        pattern_rank=pattern_rank,
        discharge_cms=discharge,
        timestep_minutes=timestep_minutes,
        peak_discharge_cms=max(discharge),
        runoff_volume_m3=sum(q * timestep_minutes * 60.0 for q in discharge),
        time_to_peak_minutes=(half + 1) * timestep_minutes,
    )


def _route(
    hydrograph: HydrographResult,
    basin_max_depth_m: float = 1.0,
    base_length_m: float = 8.0,
    base_width_m: float = 5.0,
    **kw,
):
    return route_through_basin(
        hydrograph=hydrograph,
        base_length_m=base_length_m,
        base_width_m=base_width_m,
        side_slope_ratio=4.0,
        max_depth_m=basin_max_depth_m,
        vertical_k_mm_per_hr=50.0,
        horizontal_k_mm_per_hr=None,
        design_drain_time_hours=24.0,
        soil_moderation_factor=0.5,
        initial_moisture_deficit=0.2,
        capillary_suction_head_m=0.15,
        specific_yield=0.25,
        surface_level_m_ahd=10.0,
        design_gwl_m_ahd=7.0,
        base_aquifer_level_m_ahd=0.0,
        use_clogged_layer=False,
        clogged_k_m_per_day=None,
        clogged_thickness_m=None,
        basin_side_infil_enabled=True,
        **kw,
    )


def test_mass_balance_holds_at_every_timestep():
    """inflow ≈ storage + infiltration + overflow (tolerance for rounding)."""
    hydro = _synthetic_hydrograph()
    ts = _route(hydro)
    assert len(ts.time_minutes) > 0
    for i in range(len(ts.time_minutes)):
        inflow = ts.cumulative_inflow_m3[i]
        storage = ts.storage_volume_m3[i]
        infil = ts.cumulative_infiltration_m3[i]
        overflow = ts.cumulative_overflow_m3[i]
        balance = storage + infil + overflow
        assert abs(inflow - balance) < 1e-3, (
            f"Timestep {i}: inflow {inflow:.4f} != storage+infil+overflow {balance:.4f}"
        )


def test_pooling_case_flags_overtopping_and_conerves_mass():
    """A deliberately undersized basin (tiny max depth) overtops: peak depth
    exceeds the max depth, spill_flag is True, but mass is still conserved."""
    hydro = _synthetic_hydrograph(peak_cms=2.0, n_steps=60)
    ts = _route(hydro, basin_max_depth_m=0.2, base_length_m=2.0, base_width_m=1.0)
    peak_depth = max(ts.depth_m)
    assert peak_depth > 0.2, "Expected overtopping (peak depth > max depth)"
    assert any(ts.spill_flag), "Expected spill_flag to be True for an overtopping basin"
    # Mass balance still holds
    for i in range(len(ts.time_minutes)):
        inflow = ts.cumulative_inflow_m3[i]
        storage = ts.storage_volume_m3[i]
        infil = ts.cumulative_infiltration_m3[i]
        overflow = ts.cumulative_overflow_m3[i]
        assert abs(inflow - (storage + infil + overflow)) < 1e-3


def test_drains_to_near_zero_after_storm():
    """After the storm the basin should drain toward empty (storage -> 0).

    The v1.2.0 engine uses the phase 4 back-calculation throttle (alpha=0,
    peak-preserving) which is deliberately conservative on the recession: the
    mound is pinned at the basin invert and infiltration is damped to the
    lateral-drainage rate. So the basin drains more slowly than under the old
    logistic-blend throttle. We verify the basin has drained substantially
    below its peak (the conservative recession holds water longer, but the
    basin still drains to near-empty given enough time).
    """
    hydro = _synthetic_hydrograph(peak_cms=0.05, n_steps=20)
    ts = _route(hydro)
    peak_storage = max(ts.storage_volume_m3)
    final_storage = ts.storage_volume_m3[-1]
    assert final_storage < peak_storage, "Basin did not drain at all"
    assert final_storage < 0.5, f"Basin did not drain: final storage {final_storage:.3f} m3"


def test_mound_height_bounded_by_depth_to_groundwater():
    """The groundwater mound cannot rise above the ground surface (D_gw)."""
    hydro = _synthetic_hydrograph(peak_cms=1.0, n_steps=60)
    ts = _route(hydro)
    # D_gw = surface_level (10) - design_gwl (7) = 3.0 m
    assert all(0.0 <= h <= 3.0 + 1e-6 for h in ts.mound_height_m)
