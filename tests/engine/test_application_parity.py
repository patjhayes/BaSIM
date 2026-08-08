from __future__ import annotations

import json
from pathlib import Path

from soakhydro.application.clogging import run_clogging_analysis
from soakhydro.application.design import run_design_analysis
from soakhydro.config import DEFAULT_DURATIONS_MIN


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gah_baseline"


def _fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_normalize(payload: dict) -> dict:
    return json.loads(json.dumps(payload))


def test_design_result_matches_pinned_gah_source() -> None:
    actual = run_design_analysis(_fixture("design_request.json"))

    assert _json_normalize(actual) == _fixture("design_result.json")


def test_clogging_result_matches_pinned_gah_source() -> None:
    actual = run_clogging_analysis(_fixture("clogging_request.json"))

    assert _json_normalize(actual) == _fixture("clogging_result.json")


def test_clogging_year_zero_matches_equivalent_clean_design() -> None:
    clogging_request = _fixture("clogging_request.json")
    clogging_result = run_clogging_analysis(clogging_request)
    design_request = {
        "latitude": clogging_request["latitude"],
        "longitude": clogging_request["longitude"],
        "catchments": clogging_request["catchments"],
        "aep_percentages": [clogging_request["design_aep_percent"]],
        "durations_minutes": list(DEFAULT_DURATIONS_MIN),
        "design_aep_percent": clogging_request["design_aep_percent"],
        "pattern_rank": clogging_request["critical_pattern_rank"],
        "vertical_k_mm_per_hr": clogging_request["vertical_k_mm_per_hr"],
        "horizontal_k_mm_per_hr": clogging_request["horizontal_k_mm_per_hr"],
        "design_drain_time_hours": 72.0,
        "soil_moderation_factor": clogging_request["soil_moderation_factor"],
        "surface_level_m_ahd": clogging_request["surface_level_m_ahd"],
        "design_gwl_m_ahd": clogging_request["design_gwl_m_ahd"],
        "base_aquifer_level_m_ahd": clogging_request["base_aquifer_level_m_ahd"],
        "basin_base_length_m": clogging_request["basin_base_length_m"],
        "basin_base_width_m": clogging_request["basin_base_width_m"],
        "basin_side_slope_ratio": clogging_request["basin_side_slope_ratio"],
        "basin_max_depth_m": clogging_request["basin_max_depth_m"],
        "initial_moisture_deficit": clogging_request["initial_moisture_deficit"],
        "capillary_suction_head_m": clogging_request["capillary_suction_head_m"],
        "specific_yield": clogging_request["specific_yield"],
        "basin_side_infil_enabled": clogging_request["basin_side_infil_enabled"],
        "use_live_data": False,
    }
    design_result = run_design_analysis(design_request)

    clean_year = clogging_result["timeline"][0]
    clean_design = design_result["model_runs"][0]
    assert clean_year["depth_summary"] == clean_design["depth_summary"]
    assert clean_year["drawdown_summary"] == clean_design["drawdown_summary"]