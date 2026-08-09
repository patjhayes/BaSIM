"""Synchronous GAH-3D clogging degradation analysis."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import (
    CatchmentInput,
    select_model_critical,
    summarise_timeseries,
    timeseries_to_dict,
)
from ..config import DEFAULT_DURATIONS_MIN
from ..hydraulics.routing import basin_storage_m3_at_depth, route_through_basin
from ..models.common import AEP, Coordinate, Project, ProjectSettings
from ..pipeline import DataRepository, run_full_pipeline


ProgressCallback = Callable[[dict[str, Any]], None]


class CloggingRequest(BaseModel):
    project_name: Optional[str] = None
    scenario_name: Optional[str] = None
    latitude: float
    longitude: float
    catchments: list[CatchmentInput]
    design_aep_percent: float
    critical_duration_minutes: int
    critical_pattern_rank: int
    basin_base_length_m: float
    basin_base_width_m: float
    basin_side_slope_ratio: float
    basin_max_depth_m: float
    initial_moisture_deficit: float
    capillary_suction_head_m: float
    specific_yield: float
    vertical_k_mm_per_hr: float
    horizontal_k_mm_per_hr: Optional[float] = None
    soil_moderation_factor: float = Field(0.5, gt=0)
    surface_level_m_ahd: float = 10.0
    design_gwl_m_ahd: float = 7.0
    base_aquifer_level_m_ahd: float = 0.0
    basin_side_infil_enabled: bool = True
    clogging_years: int
    final_k_cl_m_per_day: float
    final_l_cl_m: float
    use_live_data: bool = False
    climate_scenario: Optional[str] = None
    climate_epoch: Optional[int] = None


def prepare_clogging_analysis(request: CloggingRequest) -> dict[str, Any]:
    design_aep = AEP.from_percent(request.design_aep_percent)
    project = Project(
        coordinate=Coordinate(
            latitude=request.latitude,
            longitude=request.longitude,
        ),
        catchments=tuple(item.to_domain() for item in request.catchments),
        settings=ProjectSettings(
            ae_ps=(design_aep,),
            durations_minutes=DEFAULT_DURATIONS_MIN,
        ),
        additional_metadata={
            "project_name": request.project_name or "Clogging Assessment"
        },
    )
    report = run_full_pipeline(
        project=project,
        data_repo=DataRepository(use_live_data=request.use_live_data),
        aep_for_design=design_aep,
        pattern_rank=request.critical_pattern_rank,
        climate_scenario=request.climate_scenario,
        climate_epoch=request.climate_epoch,
    )
    return {
        "design_aep": design_aep,
        "report": report,
        "initial_k": request.vertical_k_mm_per_hr / 1000.0 / 3600.0 * 86400.0,
        "initial_l": 0.001,
        "num_years": max(1, request.clogging_years),
        "max_capacity": basin_storage_m3_at_depth(
            base_length_m=request.basin_base_length_m,
            base_width_m=request.basin_base_width_m,
            side_slope_ratio=request.basin_side_slope_ratio,
            depth_m=request.basin_max_depth_m,
        ),
    }


def route_clogging_year(
    request: CloggingRequest,
    setup: dict[str, Any],
    year: int,
    fraction: float,
) -> dict[str, Any]:
    initial_k = setup["initial_k"]
    initial_l = setup["initial_l"]
    if initial_k > 0 and request.final_k_cl_m_per_day > 0:
        current_k = initial_k * (
            request.final_k_cl_m_per_day / initial_k
        ) ** fraction
    else:
        current_k = initial_k - (
            initial_k - request.final_k_cl_m_per_day
        ) * fraction
    current_l = initial_l + (request.final_l_cl_m - initial_l) * fraction

    routed_by_duration = {}
    for hydrograph_key, hydrograph in setup["report"].runoff_results.items():
        if hydrograph_key[0] != setup["design_aep"]:
            continue
        timeseries = route_through_basin(
            hydrograph=hydrograph,
            base_length_m=request.basin_base_length_m,
            base_width_m=request.basin_base_width_m,
            side_slope_ratio=request.basin_side_slope_ratio,
            max_depth_m=request.basin_max_depth_m,
            vertical_k_mm_per_hr=request.vertical_k_mm_per_hr,
            horizontal_k_mm_per_hr=request.horizontal_k_mm_per_hr,
            design_drain_time_hours=72.0,
            soil_moderation_factor=request.soil_moderation_factor,
            initial_moisture_deficit=request.initial_moisture_deficit,
            capillary_suction_head_m=request.capillary_suction_head_m,
            specific_yield=request.specific_yield,
            surface_level_m_ahd=request.surface_level_m_ahd,
            design_gwl_m_ahd=request.design_gwl_m_ahd,
            base_aquifer_level_m_ahd=request.base_aquifer_level_m_ahd,
            use_clogged_layer=fraction > 0.0,
            clogged_k_m_per_day=current_k,
            clogged_thickness_m=current_l,
            basin_side_infil_enabled=request.basin_side_infil_enabled,
            hydraulic_structures=None,
        )
        peak_depth = max(timeseries.depth_m) if timeseries.depth_m else 0.0
        routed_by_duration.setdefault(hydrograph.duration_minutes, []).append(
            (peak_depth, hydrograph, timeseries)
        )

    (
        depth_result,
        depth_timeseries,
        drawdown_result,
        drawdown_timeseries,
    ) = select_model_critical(routed_by_duration, request.critical_pattern_rank)

    peak_depth = 0.0
    drain_time_hours = 0.0
    spilled = False
    depth_summary = None
    drawdown_summary = None
    timeseries_result = None
    drawdown_timeseries_result = None
    if (
        depth_result is not None
        and depth_timeseries is not None
        and drawdown_result is not None
        and drawdown_timeseries is not None
    ):
        depth_summary = summarise_timeseries(
            depth_timeseries,
            len(depth_result.discharge_cms) * depth_result.timestep_minutes,
            depth_result.duration_minutes,
            depth_result.pattern_rank,
            setup["max_capacity"],
        )
        drawdown_summary = summarise_timeseries(
            drawdown_timeseries,
            len(drawdown_result.discharge_cms) * drawdown_result.timestep_minutes,
            drawdown_result.duration_minutes,
            drawdown_result.pattern_rank,
            setup["max_capacity"],
        )
        peak_depth = depth_summary["peak_depth_m"]
        drain_time_hours = drawdown_summary["drain_time_hours"]
        spilled = depth_summary["spilled"]
        timeseries_result = timeseries_to_dict(depth_timeseries)
        drawdown_timeseries_result = timeseries_to_dict(drawdown_timeseries)

    return {
        "year": year,
        "k_cl_m_per_day": current_k,
        "l_cl_m": current_l,
        "peak_depth_m": peak_depth,
        "drain_time_hours": drain_time_hours,
        "spilled": spilled,
        "depth_summary": depth_summary,
        "drawdown_summary": drawdown_summary,
        "timeseries": timeseries_result,
        "timeseries_drawdown": drawdown_timeseries_result,
    }


def run_clogging_analysis(
    payload: CloggingRequest | dict[str, Any],
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    request = (
        payload
        if isinstance(payload, CloggingRequest)
        else CloggingRequest.model_validate(payload)
    )
    if progress is not None:
        progress(
            {
                "phase": "setup",
                "message": "Fetching rainfall data and running hydrology",
            }
        )
    setup = prepare_clogging_analysis(request)
    total_steps = setup["num_years"] + 1
    timeline = []
    for year in range(total_steps):
        fraction = (
            1.0
            if setup["num_years"] == 0
            else year / float(setup["num_years"])
        )
        if progress is not None:
            progress(
                {
                    "phase": "routing",
                    "step": year,
                    "total": total_steps,
                    "year": year,
                }
            )
        year_result = route_clogging_year(request, setup, year, fraction)
        timeline.append(year_result)
        if progress is not None:
            progress(
                {
                    "phase": "routing",
                    "step": year + 1,
                    "total": total_steps,
                    "year": year,
                    "done": True,
                }
            )
    result = {"timeline": timeline}
    if request.project_name:
        result["project_name"] = request.project_name
    if request.scenario_name:
        result["scenario_name"] = request.scenario_name
    return result