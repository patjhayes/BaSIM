"""Framework-neutral routing of runoff hydrographs through a GAH-3D basin."""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from .gah_3d_engine import GAH3D_Basin
from .structures import build_structure, compute_structure_outflows
from ..models.results import HydrographResult, SoakwellTimeSeries


def basin_storage_m3_at_depth(
    base_length_m: float,
    base_width_m: float,
    side_slope_ratio: float,
    depth_m: float,
) -> float:
    depth = max(0.0, depth_m)
    return (
        base_length_m * base_width_m * depth
        + side_slope_ratio * (base_length_m + base_width_m) * depth * depth
        + (4.0 / 3.0)
        * side_slope_ratio
        * side_slope_ratio
        * depth
        * depth
        * depth
    )


def basin_depth_m_from_storage(
    storage_m3: float,
    base_length_m: float,
    base_width_m: float,
    side_slope_ratio: float,
    max_depth_m: float,
) -> float:
    if storage_m3 <= 0.0:
        return 0.0

    lower = 0.0
    upper = max(max_depth_m, 1.0)
    while basin_storage_m3_at_depth(
        base_length_m=base_length_m,
        base_width_m=base_width_m,
        side_slope_ratio=side_slope_ratio,
        depth_m=upper,
    ) < storage_m3:
        upper *= 2.0

    for _ in range(40):
        midpoint = 0.5 * (lower + upper)
        midpoint_volume = basin_storage_m3_at_depth(
            base_length_m=base_length_m,
            base_width_m=base_width_m,
            side_slope_ratio=side_slope_ratio,
            depth_m=midpoint,
        )
        if midpoint_volume < storage_m3:
            lower = midpoint
        else:
            upper = midpoint
    return 0.5 * (lower + upper)


def route_through_basin(
    hydrograph: HydrographResult,
    base_length_m: float,
    base_width_m: float,
    side_slope_ratio: float,
    max_depth_m: float,
    vertical_k_mm_per_hr: float,
    horizontal_k_mm_per_hr: Optional[float],
    design_drain_time_hours: float,
    soil_moderation_factor: float,
    initial_moisture_deficit: float,
    capillary_suction_head_m: float,
    specific_yield: float,
    surface_level_m_ahd: float,
    design_gwl_m_ahd: float,
    base_aquifer_level_m_ahd: float,
    use_clogged_layer: bool,
    clogged_k_m_per_day: Optional[float],
    clogged_thickness_m: Optional[float],
    basin_side_infil_enabled: bool = True,
    hydraulic_structures: Optional[Sequence[Any]] = None,
) -> SoakwellTimeSeries:
    dt_s = hydrograph.timestep_minutes * 60.0
    storm_steps = len(hydrograph.discharge_cms)
    max_drain_steps = int(
        math.ceil(10.0 * design_drain_time_hours * 3600.0 / dt_s)
    )
    total_steps = storm_steps + max_drain_steps

    max_storage_m3 = basin_storage_m3_at_depth(
        base_length_m=base_length_m,
        base_width_m=base_width_m,
        side_slope_ratio=side_slope_ratio,
        depth_m=max_depth_m,
    )

    vertical_k_m_per_s = vertical_k_mm_per_hr / 1000.0 / 3600.0
    adjusted_vertical_k_m_per_s = vertical_k_m_per_s * soil_moderation_factor
    horizontal_k = (
        horizontal_k_mm_per_hr
        if horizontal_k_mm_per_hr is not None
        else vertical_k_mm_per_hr * 5.0
    )
    horizontal_k_m_per_s = horizontal_k / 1000.0 / 3600.0
    adjusted_horizontal_k_m_per_s = horizontal_k_m_per_s * soil_moderation_factor
    clog_k_m_per_s = (
        ((clogged_k_m_per_day or 0.0) / 86400.0)
        if use_clogged_layer and clogged_k_m_per_day is not None
        else None
    )

    depth_to_groundwater_m = max(0.0, surface_level_m_ahd - design_gwl_m_ahd)
    aquifer_thickness_m = max(0.1, design_gwl_m_ahd - base_aquifer_level_m_ahd)
    engine = GAH3D_Basin(
        Ks=adjusted_vertical_k_m_per_s,
        psi=capillary_suction_head_m,
        Sy=specific_yield,
        b=aquifer_thickness_m,
        L=base_length_m,
        W=base_width_m,
        D_gw=depth_to_groundwater_m,
        Kh=adjusted_horizontal_k_m_per_s,
        k_cl=clog_k_m_per_s,
        l_cl=clogged_thickness_m if use_clogged_layer else None,
        slope=side_slope_ratio,
        enable_batters=basin_side_infil_enabled,
        theta_deficit=max(initial_moisture_deficit, 1e-3),
    )

    cumulative_inflow = 0.0
    cumulative_infiltration = 0.0
    cumulative_structure_outflow = 0.0
    stored = 0.0

    structures = []
    for structure_input in hydraulic_structures or []:
        payload = (
            structure_input.model_dump()
            if hasattr(structure_input, "model_dump")
            else dict(structure_input)
        )
        payload["_basin_invert_m_ahd"] = surface_level_m_ahd
        structures.append(build_structure(payload))

    time_minutes: list[float] = []
    cumulative_inflow_m3: list[float] = []
    storage_volume_m3: list[float] = []
    depth_m: list[float] = []
    cumulative_infiltration_m3: list[float] = []
    cumulative_overflow_m3: list[float] = []
    spill_flag: list[bool] = []
    mound_height_m: list[float] = []
    infiltration_rate_m_per_day: list[float] = []
    structure_outflow_m3: list[float] = []
    cumulative_structure_outflow_m3: list[float] = []

    for step in range(total_steps):
        elapsed_minutes = step * hydrograph.timestep_minutes
        inflow_rate = hydrograph.discharge_cms[step] if step < storm_steps else 0.0
        inflow_volume = inflow_rate * dt_s

        depth_before = basin_depth_m_from_storage(
            storage_m3=stored,
            base_length_m=base_length_m,
            base_width_m=base_width_m,
            side_slope_ratio=side_slope_ratio,
            max_depth_m=max_depth_m,
        )

        base_area = base_length_m * base_width_m
        available = stored + inflow_volume
        available_depth = available / base_area if base_area > 0 else 0.0
        infiltration_flux = engine.step(dt_s, depth_before, available_depth)
        infiltration_volume = infiltration_flux * base_area * dt_s
        stored = available - infiltration_volume

        structure_outflow_volume = 0.0
        if structures:
            depth_after_infiltration = basin_depth_m_from_storage(
                storage_m3=stored,
                base_length_m=base_length_m,
                base_width_m=base_width_m,
                side_slope_ratio=side_slope_ratio,
                max_depth_m=max_depth_m,
            )
            structure_outflow_volume, _ = compute_structure_outflows(
                structures=structures,
                water_depth_m=depth_after_infiltration,
                dt_s=dt_s,
                available_storage_m3=max(stored, 0.0),
            )
            stored -= structure_outflow_volume
        cumulative_structure_outflow += structure_outflow_volume

        is_spilling = stored > max_storage_m3
        cumulative_inflow += inflow_volume
        cumulative_infiltration += infiltration_volume
        depth_after = basin_depth_m_from_storage(
            storage_m3=stored,
            base_length_m=base_length_m,
            base_width_m=base_width_m,
            side_slope_ratio=side_slope_ratio,
            max_depth_m=max_depth_m,
        )

        time_minutes.append(round(elapsed_minutes, 2))
        cumulative_inflow_m3.append(round(cumulative_inflow, 6))
        storage_volume_m3.append(round(stored, 6))
        depth_m.append(round(depth_after, 4))
        cumulative_infiltration_m3.append(round(cumulative_infiltration, 6))
        cumulative_overflow_m3.append(0.0)
        spill_flag.append(is_spilling)
        mound_height_m.append(round(engine.H_m, 4))
        infiltration_rate_m_per_day.append(round(infiltration_flux * 86400, 4))
        structure_outflow_m3.append(round(structure_outflow_volume, 6))
        cumulative_structure_outflow_m3.append(
            round(cumulative_structure_outflow, 6)
        )

        if step >= storm_steps and stored < 1e-9:
            time_since_storm_end = elapsed_minutes - (
                storm_steps * hydrograph.timestep_minutes
            )
            if (
                engine.H_m < 0.01
                or time_since_storm_end > design_drain_time_hours * 60.0 * 2.0
            ):
                break

    reason = (
        f"GAH-3D routing with batters={side_slope_ratio}H:1V "
        f"and GWD={depth_to_groundwater_m}m."
    )
    if (
        use_clogged_layer
        and clogged_k_m_per_day is not None
        and clogged_thickness_m is not None
    ):
        reason += (
            f" Clogged-layer resistance active (Kc={clogged_k_m_per_day:.3f} m/day, "
            f"thickness={clogged_thickness_m:.3f} m)."
        )

    return SoakwellTimeSeries(
        timestep_minutes=hydrograph.timestep_minutes,
        time_minutes=time_minutes,
        cumulative_inflow_m3=cumulative_inflow_m3,
        storage_volume_m3=storage_volume_m3,
        depth_m=depth_m,
        cumulative_infiltration_m3=cumulative_infiltration_m3,
        spill_flag=spill_flag,
        cumulative_overflow_m3=cumulative_overflow_m3,
        mound_height_m=mound_height_m,
        infiltration_rate_m_per_day=infiltration_rate_m_per_day,
        structure_outflow_m3=structure_outflow_m3,
        cumulative_structure_outflow_m3=cumulative_structure_outflow_m3,
        selected_model="green_ampt_hantush",
        model_selection_reason=reason,
    )