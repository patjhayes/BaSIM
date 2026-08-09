"""HTTP request and response contracts for GAH-3D analysis jobs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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


class DesignAnalysisRequest(BaseModel):
    project_code: Optional[str] = None
    project_name: Optional[str] = Field(None, min_length=1, max_length=120)
    scenario_name: Optional[str] = Field(None, min_length=1, max_length=120)
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
    basin_base_length_m: float = Field(gt=0)
    basin_base_width_m: float = Field(gt=0)
    basin_side_slope_ratio: float = Field(gt=0)
    basin_max_depth_m: float = Field(gt=0)
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


class CloggingAnalysisRequest(BaseModel):
    project_code: Optional[str] = None
    project_name: Optional[str] = Field(None, min_length=1, max_length=120)
    scenario_name: Optional[str] = Field(None, min_length=1, max_length=120)
    latitude: float = Field(ge=-44.0, le=-10.0)
    longitude: float = Field(ge=112.0, le=154.0)
    catchments: list[CatchmentInput]
    design_aep_percent: float = Field(gt=0)
    critical_duration_minutes: int = Field(gt=0)
    critical_pattern_rank: int = Field(ge=1, le=10)
    basin_base_length_m: float = Field(gt=0)
    basin_base_width_m: float = Field(gt=0)
    basin_side_slope_ratio: float = Field(gt=0)
    basin_max_depth_m: float = Field(gt=0)
    initial_moisture_deficit: float = Field(gt=0, le=0.5)
    capillary_suction_head_m: float = Field(ge=0)
    specific_yield: float = Field(gt=0)
    vertical_k_mm_per_hr: float = Field(gt=0)
    horizontal_k_mm_per_hr: Optional[float] = Field(None, gt=0)
    soil_moderation_factor: float = Field(0.5, gt=0)
    surface_level_m_ahd: float = 10.0
    design_gwl_m_ahd: float = 7.0
    base_aquifer_level_m_ahd: float = 0.0
    basin_side_infil_enabled: bool = True
    clogging_years: int = Field(ge=1)
    final_k_cl_m_per_day: float = Field(gt=0)
    final_l_cl_m: float = Field(gt=0)
    use_live_data: bool = False
    climate_scenario: Optional[str] = None
    climate_epoch: Optional[int] = Field(None, ge=2030, le=2100)


class JobSubmissionResponse(BaseModel):
    job_id: str
    status: str
    cost: int