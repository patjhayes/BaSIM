"""Synchronous GAH-3D basin design analysis."""

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
from ..hydraulics.routing import basin_storage_m3_at_depth, route_through_basin
from ..models.common import AEP, Coordinate, Project, ProjectSettings
from ..pipeline import DataRepository, run_full_pipeline


GAH3D_MODEL_KEY = "green_ampt_hantush"
GAH3D_MODEL_LABEL = "Green-Ampt/Hantush"
ProgressCallback = Callable[[dict[str, Any]], None]


class HydraulicStructureInput(BaseModel):
    type: str
    name: str = ""
    weir_crest_level_m_ahd: Optional[float] = None
    weir_length_m: Optional[float] = Field(None, gt=0)
    weir_lining: Optional[str] = "concrete"
    culvert_material: Optional[str] = None
    culvert_diameter_mm: Optional[int] = Field(None, gt=0)
    culvert_width_mm: Optional[int] = Field(None, gt=0)
    culvert_height_mm: Optional[int] = Field(None, gt=0)
    culvert_invert_level_m_ahd: Optional[float] = None
    culvert_length_m: Optional[float] = Field(10.0, gt=0)
    culvert_slope: Optional[float] = Field(0.0, ge=0)
    culvert_count: int = Field(1, ge=1)
    pit_inlet_level_m_ahd: Optional[float] = None
    pit_length_m: Optional[float] = Field(None, gt=0)
    pit_width_m: Optional[float] = Field(None, gt=0)
    pit_opening_ratio: Optional[float] = Field(0.5, gt=0, le=1)


class DesignRequest(BaseModel):
    latitude: float = Field(-31.95, ge=-44.0, le=-10.0)
    longitude: float = Field(115.86, ge=112.0, le=154.0)
    catchments: list[CatchmentInput] = Field(
        default_factory=lambda: [CatchmentInput()]
    )
    aep_percentages: list[float] = Field(default_factory=lambda: [10.0, 5.0])
    durations_minutes: list[int] = Field(default_factory=lambda: [30, 60])
    vertical_k_mm_per_hr: float = Field(50.0, gt=0)
    horizontal_k_mm_per_hr: Optional[float] = Field(None, gt=0)
    design_drain_time_hours: float = Field(24.0, gt=0)
    soil_moderation_factor: float = Field(0.5, gt=0)
    surface_level_m_ahd: float = 10.0
    design_gwl_m_ahd: float = 7.0
    base_aquifer_level_m_ahd: float = 0.0
    pattern_rank: int = Field(4, ge=1, le=10)
    design_aep_percent: Optional[float] = Field(None, gt=0)
    basin_base_length_m: Optional[float] = Field(None, gt=0)
    basin_base_width_m: Optional[float] = Field(None, gt=0)
    basin_side_slope_ratio: Optional[float] = Field(None, gt=0)
    basin_max_depth_m: Optional[float] = Field(None, gt=0)
    initial_moisture_deficit: Optional[float] = Field(None, gt=0, le=0.5)
    capillary_suction_head_m: Optional[float] = Field(None, ge=0)
    specific_yield: Optional[float] = Field(None, ge=0)
    basin_use_clogged_layer: bool = False
    basin_clogged_k_m_per_day: Optional[float] = Field(None, gt=0)
    basin_clogged_thickness_m: Optional[float] = Field(None, gt=0)
    basin_side_infil_enabled: bool = True
    use_live_data: bool = False
    hydraulic_structures: list[HydraulicStructureInput] = Field(default_factory=list)
    climate_scenario: Optional[str] = None
    climate_epoch: Optional[int] = Field(None, ge=2030, le=2100)


def _validate_request(request: DesignRequest) -> None:
    required_basin = {
        "basin_base_length_m": request.basin_base_length_m,
        "basin_base_width_m": request.basin_base_width_m,
        "basin_side_slope_ratio": request.basin_side_slope_ratio,
        "basin_max_depth_m": request.basin_max_depth_m,
    }
    missing = [name for name, value in required_basin.items() if value is None]
    if missing:
        raise ValueError(f"Missing basin inputs: {', '.join(missing)}")
    if request.basin_use_clogged_layer and (
        request.basin_clogged_k_m_per_day is None
        or request.basin_clogged_thickness_m is None
    ):
        raise ValueError(
            "When basin_use_clogged_layer is true, basin_clogged_k_m_per_day "
            "and basin_clogged_thickness_m are required."
        )
    if (
        request.climate_scenario
        and request.climate_scenario.lower() not in ("historical", "none")
        and request.climate_epoch is None
    ):
        raise ValueError("climate_epoch is required when climate_scenario is set.")


def _emit(progress: Optional[ProgressCallback], event: dict[str, Any]) -> None:
    if progress is not None:
        progress(event)


def run_design_analysis(
    payload: DesignRequest | dict[str, Any],
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    request = (
        payload if isinstance(payload, DesignRequest) else DesignRequest.model_validate(payload)
    )
    _validate_request(request)

    design_aep_percent = request.design_aep_percent or min(request.aep_percentages)
    design_aep = AEP.from_percent(design_aep_percent)
    aep_percentages = set(request.aep_percentages)
    aep_percentages.add(design_aep_percent)
    ae_ps = tuple(
        AEP.from_percent(value) for value in sorted(aep_percentages, reverse=True)
    )

    project = Project(
        coordinate=Coordinate(
            latitude=request.latitude,
            longitude=request.longitude,
        ),
        catchments=tuple(item.to_domain() for item in request.catchments),
        settings=ProjectSettings(
            ae_ps=ae_ps,
            durations_minutes=tuple(request.durations_minutes),
        ),
        additional_metadata={"project_name": "GAH-3D Basin Engine"},
    )
    report = run_full_pipeline(
        project=project,
        data_repo=DataRepository(use_live_data=request.use_live_data),
        aep_for_design=design_aep,
        pattern_rank=request.pattern_rank,
        climate_scenario=request.climate_scenario,
        climate_epoch=request.climate_epoch,
    )

    runoff_table = [
        {
            "aep": result.aep.to_label(),
            "duration_minutes": result.duration_minutes,
            "pattern_rank": result.pattern_rank,
            "peak_discharge_cms": round(result.peak_discharge_cms, 6),
            "runoff_volume_m3": round(result.runoff_volume_m3, 3),
            "time_to_peak_minutes": round(result.time_to_peak_minutes, 1),
        }
        for result in sorted(
            report.runoff_results.values(),
            key=lambda item: (item.aep.value, item.duration_minutes, item.pattern_rank),
        )
    ]

    patterns_to_route = [
        result
        for (result_aep, _), ensemble in report.ensembles.items()
        if result_aep == design_aep and ensemble.results
        for result in ensemble.results
    ]
    routed_by_duration = {}
    total_patterns = len(patterns_to_route)
    for index, hydrograph in enumerate(patterns_to_route):
        storm_label = (
            f"{design_aep.to_label()} {hydrograph.duration_minutes} min "
            f"- pattern {hydrograph.pattern_rank}"
        )
        _emit(
            progress,
            {
                "phase": "routing",
                "step": index,
                "total": total_patterns,
                "storm": storm_label,
            },
        )
        timeseries = route_through_basin(
            hydrograph=hydrograph,
            base_length_m=request.basin_base_length_m or 1.0,
            base_width_m=request.basin_base_width_m or 1.0,
            side_slope_ratio=request.basin_side_slope_ratio or 3.0,
            max_depth_m=request.basin_max_depth_m or 1.0,
            vertical_k_mm_per_hr=request.vertical_k_mm_per_hr,
            horizontal_k_mm_per_hr=request.horizontal_k_mm_per_hr,
            design_drain_time_hours=request.design_drain_time_hours,
            soil_moderation_factor=request.soil_moderation_factor,
            initial_moisture_deficit=request.initial_moisture_deficit or 0.2,
            capillary_suction_head_m=request.capillary_suction_head_m or 0.15,
            specific_yield=max(request.specific_yield or 0.25, 0.01),
            surface_level_m_ahd=request.surface_level_m_ahd,
            design_gwl_m_ahd=request.design_gwl_m_ahd,
            base_aquifer_level_m_ahd=request.base_aquifer_level_m_ahd,
            use_clogged_layer=request.basin_use_clogged_layer,
            clogged_k_m_per_day=request.basin_clogged_k_m_per_day,
            clogged_thickness_m=request.basin_clogged_thickness_m,
            basin_side_infil_enabled=request.basin_side_infil_enabled,
            hydraulic_structures=request.hydraulic_structures,
        )
        peak_depth = max(timeseries.depth_m) if timeseries.depth_m else 0.0
        routed_by_duration.setdefault(hydrograph.duration_minutes, []).append(
            (peak_depth, hydrograph, timeseries)
        )
        _emit(
            progress,
            {
                "phase": "routing",
                "step": index + 1,
                "total": total_patterns,
                "storm": storm_label,
                "done": True,
            },
        )

    hyetographs = [
        {
            "key": f"{aep.to_label()} {duration}min Rank {rank}",
            "timestep_minutes": hyetograph.timestep_minutes,
            "depths_mm": [round(depth, 4) for depth in hyetograph.depths_mm],
        }
        for (aep, duration, rank), hyetograph in sorted(
            report.hyetographs.items(),
            key=lambda item: (item[0][0].value, item[0][1], item[0][2]),
        )
    ]
    hydrographs = [
        {
            "key": f"{aep.to_label()} {duration}min Rank {rank}",
            "timestep_minutes": hydrograph.timestep_minutes,
            "discharge_cms": [
                round(discharge, 6) for discharge in hydrograph.discharge_cms
            ],
        }
        for (aep, duration, rank), hydrograph in sorted(
            report.runoff_results.items(),
            key=lambda item: (item[0][0].value, item[0][1], item[0][2]),
        )
    ]

    (
        depth_result,
        depth_timeseries,
        drawdown_result,
        drawdown_timeseries,
    ) = select_model_critical(routed_by_duration, request.pattern_rank)
    selected_model = GAH3D_MODEL_KEY
    selected_model_reason = "GAH-3D Basin Engine"
    model_runs = []
    max_capacity = basin_storage_m3_at_depth(
        base_length_m=request.basin_base_length_m or 1.0,
        base_width_m=request.basin_base_width_m or 1.0,
        side_slope_ratio=request.basin_side_slope_ratio or 0.0,
        depth_m=request.basin_max_depth_m or 0.0,
    )
    if (
        depth_result is not None
        and depth_timeseries is not None
        and drawdown_result is not None
        and drawdown_timeseries is not None
    ):
        selected_model = depth_timeseries.selected_model or GAH3D_MODEL_KEY
        selected_model_reason = (
            depth_timeseries.model_selection_reason or selected_model_reason
        )
        depth_summary = summarise_timeseries(
            depth_timeseries,
            len(depth_result.discharge_cms) * depth_result.timestep_minutes,
            depth_result.duration_minutes,
            depth_result.pattern_rank,
            max_capacity,
        )
        drawdown_summary = summarise_timeseries(
            drawdown_timeseries,
            len(drawdown_result.discharge_cms) * drawdown_result.timestep_minutes,
            drawdown_result.duration_minutes,
            drawdown_result.pattern_rank,
            max_capacity,
        )
        model_runs.append(
            {
                "model_key": GAH3D_MODEL_KEY,
                "label": GAH3D_MODEL_LABEL,
                "depth_summary": depth_summary,
                "drawdown_summary": drawdown_summary,
                "timeseries": timeseries_to_dict(depth_timeseries),
                "timeseries_drawdown": timeseries_to_dict(drawdown_timeseries),
            }
        )

    dashboard_times = {}
    dashboard_depths = {}
    dashboard_mound = {}
    dashboard_infiltration = {}
    dashboard_cumulative_infiltration = {}
    for duration, routed in routed_by_duration.items():
        if not routed:
            continue
        dashboard_times[duration] = routed[0][2].time_minutes
        dashboard_depths[duration] = {}
        dashboard_mound[duration] = {}
        dashboard_infiltration[duration] = {}
        dashboard_cumulative_infiltration[duration] = {}
        for _, hydrograph, timeseries in routed:
            rank = hydrograph.pattern_rank
            dashboard_depths[duration][rank] = timeseries.depth_m
            dashboard_mound[duration][rank] = timeseries.mound_height_m
            dashboard_infiltration[duration][rank] = (
                timeseries.infiltration_rate_m_per_day
            )
            dashboard_cumulative_infiltration[duration][rank] = (
                timeseries.cumulative_infiltration_m3
            )

    warnings = []
    basin_max_depth = request.basin_max_depth_m or 0.0
    spill_storms = []
    worst_peak = 0.0
    for duration, routed in routed_by_duration.items():
        for _, hydrograph, timeseries in routed:
            peak_depth = max(timeseries.depth_m) if timeseries.depth_m else 0.0
            worst_peak = max(worst_peak, peak_depth)
            if basin_max_depth > 0 and peak_depth > basin_max_depth + 1e-6:
                max_stored = (
                    max(timeseries.storage_volume_m3)
                    if timeseries.storage_volume_m3
                    else 0.0
                )
                spill_storms.append(
                    (
                        duration,
                        hydrograph.pattern_rank,
                        peak_depth,
                        max(0.0, max_stored - max_capacity),
                    )
                )
    if spill_storms:
        total_events = sum(len(routed) for routed in routed_by_duration.values())
        warnings.append(
            f"Basin overtops in {len(spill_storms)} of {total_events} design events; "
            f"peak depth {worst_peak:.2f} m exceeds max depth {basin_max_depth:.2f} m. "
            "Water is assumed to pool above the crest (see Help section 7.3). "
            "Overflow volume is reported per event."
        )
        for duration, rank, peak_depth, overflow_m3 in sorted(spill_storms):
            warnings.append(
                f"{design_aep.to_label()} {duration}min Rank {rank}: peak depth "
                f"{peak_depth:.2f} m > max {basin_max_depth:.2f} m "
                f"(overtops, ~{overflow_m3:.1f} m3 above crest)."
            )

    return {
        "project_name": report.project_name,
        "runoff_table": runoff_table,
        "basin_geometry": {
            "base_length_m": request.basin_base_length_m or 0.0,
            "base_width_m": request.basin_base_width_m or 0.0,
            "side_slope_ratio": request.basin_side_slope_ratio or 0.0,
            "max_depth_m": request.basin_max_depth_m or 0.0,
            "use_clogged_layer": request.basin_use_clogged_layer,
            "clogged_k_m_per_day": request.basin_clogged_k_m_per_day,
            "clogged_thickness_m": request.basin_clogged_thickness_m,
        },
        "selected_model": selected_model,
        "model_selection_reason": selected_model_reason,
        "model_runs": model_runs,
        "basin_routing_times": dashboard_times,
        "basin_routing_depths": dashboard_depths,
        "basin_routing_mound": dashboard_mound,
        "basin_routing_infil": dashboard_infiltration,
        "basin_routing_cum_infil": dashboard_cumulative_infiltration,
        "hyetographs": hyetographs,
        "hydrographs": hydrographs,
        "warnings": warnings,
        "climate_scenario_label": (
            f"{request.climate_scenario} ({request.climate_epoch})"
            if request.climate_scenario and request.climate_epoch is not None
            else "Historical"
        ),
        "climate_epoch": request.climate_epoch,
    }