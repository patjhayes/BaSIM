"""Shared inputs and result assembly for GAH-3D analyses."""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field

from ..models.common import Catchment
from ..models.results import HydrographResult, SoakwellTimeSeries


class CatchmentInput(BaseModel):
    name: str = "Roof"
    area_ha: float = Field(0.05, gt=0)
    slope: float = Field(0.01, gt=0)
    paved_fraction: float = Field(0.90, ge=0, le=1)
    supplementary_fraction: float = Field(0.0, ge=0, le=1)
    grassed_fraction: float = Field(0.10, ge=0, le=1)
    soil_type: float = Field(2.0, ge=1, le=4)
    amc: float = Field(2.0, ge=1, le=4)
    paved_additional_time_minutes: float = Field(0.0, ge=0)
    supplementary_additional_time_minutes: float = Field(0.0, ge=0)
    grassed_additional_time_minutes: float = Field(0.0, ge=0)
    paved_flow_path_length_m: float = Field(15.0, ge=0)
    supplementary_flow_path_length_m: float = Field(10.0, ge=0)
    grassed_flow_path_length_m: float = Field(20.0, ge=0)
    paved_flow_path_slope_pct: float = Field(1.0, gt=0)
    supplementary_flow_path_slope_pct: float = Field(2.0, gt=0)
    grassed_flow_path_slope_pct: float = Field(2.0, gt=0)
    paved_n_star: float = Field(0.011, gt=0)
    supplementary_n_star: float = Field(0.013, gt=0)
    grassed_n_star: float = Field(0.25, gt=0)
    paved_depression_storage_mm: float = Field(1.0, ge=0)
    supplementary_depression_storage_mm: float = Field(1.0, ge=0)
    grassed_depression_storage_mm: float = Field(5.0, ge=0)

    def to_domain(self) -> Catchment:
        return Catchment(**self.model_dump())


def timeseries_to_dict(timeseries: SoakwellTimeSeries) -> dict:
    return {
        "timestep_minutes": timeseries.timestep_minutes,
        "time_minutes": timeseries.time_minutes,
        "cumulative_inflow_m3": [
            round(value, 4) for value in timeseries.cumulative_inflow_m3
        ],
        "storage_volume_m3": [
            round(value, 4) for value in timeseries.storage_volume_m3
        ],
        "depth_m": [round(value, 4) for value in timeseries.depth_m],
        "cumulative_infiltration_m3": [
            round(value, 4) for value in timeseries.cumulative_infiltration_m3
        ],
        "spill_flag": [bool(value) for value in timeseries.spill_flag],
        "cumulative_overflow_m3": [
            round(value, 4) for value in timeseries.cumulative_overflow_m3
        ],
        "mound_height_m": [
            round(value, 4) for value in timeseries.mound_height_m
        ],
        "infiltration_rate_m_per_day": [
            round(value, 4) for value in timeseries.infiltration_rate_m_per_day
        ],
        "structure_outflow_m3": [
            round(value, 4) for value in timeseries.structure_outflow_m3
        ],
        "cumulative_structure_outflow_m3": [
            round(value, 4)
            for value in timeseries.cumulative_structure_outflow_m3
        ],
        "selected_model": timeseries.selected_model,
        "model_selection_reason": timeseries.model_selection_reason,
    }


def summarise_timeseries(
    timeseries: SoakwellTimeSeries,
    storm_end_minutes: float,
    critical_duration_minutes: int,
    critical_pattern_rank: int,
    max_storage_capacity: float,
) -> dict:
    peak_depth = max(timeseries.depth_m) if timeseries.depth_m else 0.0
    max_storage = (
        max(timeseries.storage_volume_m3) if timeseries.storage_volume_m3 else 0.0
    )
    total_infiltration = (
        timeseries.cumulative_infiltration_m3[-1]
        if timeseries.cumulative_infiltration_m3
        else 0.0
    )
    spilled = any(timeseries.spill_flag) if timeseries.spill_flag else False
    total_overflow = max(0.0, max_storage - max_storage_capacity)
    peak_mound = max(timeseries.mound_height_m) if timeseries.mound_height_m else 0.0

    drain_end_minutes = storm_end_minutes
    for index in range(len(timeseries.time_minutes) - 1, -1, -1):
        if timeseries.depth_m[index] > 1e-6:
            drain_end_minutes = timeseries.time_minutes[index]
            if index + 1 < len(timeseries.time_minutes):
                drain_end_minutes = timeseries.time_minutes[index + 1]
            break

    return {
        "critical_duration_minutes": critical_duration_minutes,
        "critical_pattern_rank": critical_pattern_rank,
        "peak_depth_m": round(peak_depth, 4),
        "max_storage_m3": round(max_storage, 4),
        "total_infiltration_m3": round(total_infiltration, 4),
        "total_overflow_m3": round(total_overflow, 4),
        "drain_time_hours": round(
            max(0.0, drain_end_minutes - storm_end_minutes) / 60.0,
            2,
        ),
        "spilled": spilled,
        "peak_mound_height_m": round(peak_mound, 4),
    }


def _drain_time_minutes(
    timeseries: SoakwellTimeSeries,
    duration_minutes: int,
) -> float:
    drain_end = float(duration_minutes)
    for index in range(len(timeseries.time_minutes) - 1, -1, -1):
        if timeseries.depth_m[index] > 1e-6:
            drain_end = timeseries.time_minutes[index]
            if index + 1 < len(timeseries.time_minutes):
                drain_end = timeseries.time_minutes[index + 1]
            break
    return max(0.0, drain_end - duration_minutes)


def select_model_critical(
    routed_by_duration: Dict[
        int,
        list[tuple[float, HydrographResult, SoakwellTimeSeries]],
    ],
    pattern_rank: int,
    use_probability_neutral_rank: bool = True,
) -> tuple[
    Optional[HydrographResult],
    Optional[SoakwellTimeSeries],
    Optional[HydrographResult],
    Optional[SoakwellTimeSeries],
]:
    critical_depth_result = None
    critical_depth_timeseries = None
    max_depth = -1.0
    critical_drawdown_result = None
    critical_drawdown_timeseries = None
    max_drawdown = -1.0

    for routed in routed_by_duration.values():
        if not routed:
            continue

        ranked_by_depth = sorted(routed, key=lambda item: item[0], reverse=True)
        depth_index = (
            min(pattern_rank, len(ranked_by_depth)) - 1
            if use_probability_neutral_rank
            else 0
        )
        chosen_depth, chosen_result, chosen_timeseries = ranked_by_depth[depth_index]
        if chosen_depth > max_depth:
            max_depth = chosen_depth
            critical_depth_result = chosen_result
            critical_depth_timeseries = chosen_timeseries

        ranked_by_drawdown = sorted(
            routed,
            key=lambda item: _drain_time_minutes(
                item[2],
                item[1].duration_minutes,
            ),
            reverse=True,
        )
        drawdown_index = (
            min(pattern_rank, len(ranked_by_drawdown)) - 1
            if use_probability_neutral_rank
            else 0
        )
        _, drawdown_result, drawdown_timeseries = ranked_by_drawdown[drawdown_index]
        drawdown = _drain_time_minutes(
            drawdown_timeseries,
            drawdown_result.duration_minutes,
        )
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            critical_drawdown_result = drawdown_result
            critical_drawdown_timeseries = drawdown_timeseries

    return (
        critical_depth_result,
        critical_depth_timeseries,
        critical_drawdown_result,
        critical_drawdown_timeseries,
    )