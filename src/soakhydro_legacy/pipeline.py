from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple

from .climate_change import apply_climate_change_factors
from .config import default_project_settings
from .hydraulics.optimizer import SoakwellDesignParameters
from .hydrology.engine import design_rainfall_map, generate_hyetographs, run_hydrology
from .models.common import AEP, Project
from .models.results import SimulationReport
from .services.arr import ARRTemporalPatternClient
from .services.bom import BoMIFDClient
from .services.samples import load_json
from .utils.cache import SimpleCache
from .utils.paths import get_cache_dir

LOGGER = logging.getLogger(__name__)


class DataRepository:
    def __init__(self, use_live_data: bool = False, bom_local_json: Path | None = None) -> None:
        self.use_live_data = use_live_data
        cache_dir = get_cache_dir()
        self.arr_patterns_client = ARRTemporalPatternClient(cache=SimpleCache(cache_dir / "arr"))
        self.bom_client = BoMIFDClient(
            cache=SimpleCache(cache_dir / "bom"),
            local_dataset=bom_local_json,
        )

    def fetch_temporal_patterns(self, project: Project):
        if self.use_live_data:
            try:
                return self.arr_patterns_client.fetch_temporal_patterns(
                    project.coordinate,
                    project.settings.durations_minutes,
                    project.settings.ae_ps,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Live ARR temporal pattern fetch failed (%s); falling back to bundled samples",
                    exc,
                    exc_info=True,
                )
        sample = load_json("arr_temporal_patterns.json")
        all_patterns = self.arr_patterns_client._parse_payload(sample)
        # Filter to only the requested durations and AEPs
        dur_set = set(int(d) for d in project.settings.durations_minutes)
        aep_set = set(project.settings.ae_ps)
        return {
            (aep, dur): pats
            for (aep, dur), pats in all_patterns.items()
            if dur in dur_set and aep in aep_set
        }

    def fetch_design_rainfalls(self, project: Project):
        if self.use_live_data:
            try:
                bom_rain = self.bom_client.fetch_ifd(
                    project.coordinate,
                    project.settings.durations_minutes,
                    project.settings.ae_ps,
                )
                return bom_rain
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Live rainfall depth fetch failed (%s); falling back to bundled samples",
                    exc,
                    exc_info=True,
                )
        sample = load_json("bom_ifd.json")
        all_rainfalls = self.bom_client._parse_response(sample)
        # Filter to only the requested durations and AEPs
        dur_set = set(int(d) for d in project.settings.durations_minutes)
        aep_set = set(project.settings.ae_ps)
        return [r for r in all_rainfalls if r.duration_minutes in dur_set and r.aep in aep_set]


def run_full_pipeline(
    project: Project,
    soakwell_params: SoakwellDesignParameters,
    data_repo: DataRepository | None = None,
    aep_for_design: AEP = AEP.AEP_5,
    pattern_rank: int = 1,
    climate_scenario: str | None = None,
    climate_epoch: int | None = None,
    run_optimizer: bool = False,
) -> SimulationReport:
    project.validate()
    data_repo = data_repo or DataRepository(use_live_data=False)

    patterns = data_repo.fetch_temporal_patterns(project)
    design_rainfalls = data_repo.fetch_design_rainfalls(project)

    # Apply ARR climate change factors to design rainfall depths
    design_rainfalls = apply_climate_change_factors(
        design_rainfalls, climate_scenario, climate_epoch
    )

    rainfall_mapping = design_rainfall_map(design_rainfalls)
    hyetographs = generate_hyetographs(
        patterns,
        rainfall_mapping,
    )
    report = run_hydrology(project, hyetographs)

    return report


def create_sample_project() -> Project:
    from .models.common import Catchment, Coordinate, ProjectSettings

    settings = default_project_settings()
    settings = ProjectSettings(
        ae_ps=(AEP.AEP_10, AEP.AEP_5),
        durations_minutes=(30, 60),
    )
    project = Project(
        coordinate=Coordinate(latitude=-31.9505, longitude=115.8605),
        catchments=(
            Catchment(
                name="Roof",
                area_ha=0.05,
                slope=0.01,
                paved_fraction=0.95,
                supplementary_fraction=0.0,
                grassed_fraction=0.05,
                soil_type=2.0,
                amc=2.0,
                paved_additional_time_minutes=0.0,
                supplementary_additional_time_minutes=0.0,
                grassed_additional_time_minutes=0.0,
                paved_flow_path_length_m=15.0,
                supplementary_flow_path_length_m=10.0,
                grassed_flow_path_length_m=20.0,
                paved_flow_path_slope_pct=1.0,
                supplementary_flow_path_slope_pct=2.0,
                grassed_flow_path_slope_pct=2.0,
                paved_n_star=0.011,
                supplementary_n_star=0.013,
                grassed_n_star=0.25,
                paved_depression_storage_mm=1.0,
                supplementary_depression_storage_mm=1.0,
                grassed_depression_storage_mm=5.0,
            ),
            Catchment(
                name="Paved",
                area_ha=0.02,
                slope=0.015,
                paved_fraction=0.90,
                supplementary_fraction=0.0,
                grassed_fraction=0.10,
                soil_type=2.0,
                amc=2.0,
                paved_additional_time_minutes=0.0,
                supplementary_additional_time_minutes=0.0,
                grassed_additional_time_minutes=0.0,
                paved_flow_path_length_m=15.0,
                supplementary_flow_path_length_m=10.0,
                grassed_flow_path_length_m=20.0,
                paved_flow_path_slope_pct=1.0,
                supplementary_flow_path_slope_pct=2.0,
                grassed_flow_path_slope_pct=2.0,
                paved_n_star=0.011,
                supplementary_n_star=0.013,
                grassed_n_star=0.25,
                paved_depression_storage_mm=1.0,
                supplementary_depression_storage_mm=1.0,
                grassed_depression_storage_mm=5.0,
            ),
        ),
        settings=settings,
        additional_metadata={"project_name": "Sample Development"},
    )
    return project