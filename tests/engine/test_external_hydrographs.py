from __future__ import annotations

import pytest

from soakhydro.application.clogging import run_clogging_analysis
from soakhydro.application.design import run_design_analysis
from soakhydro.external_hydrographs import (
    duration_from_filename,
    parse_csv_hydrograph,
    parse_ts1_hydrograph,
)


@pytest.mark.parametrize(
    ("filename", "expected_minutes"),
    [
        ("event_30m.csv", 30),
        ("event_0030M.csv", 30),
        ("model_24h.ts1", 1_440),
        ("model_00024H.ts1", 1_440),
    ],
)
def test_duration_from_filename_accepts_leading_zero_variants(filename, expected_minutes):
    assert duration_from_filename(filename) == expected_minutes


@pytest.mark.parametrize("filename", ["event.csv", "0m.csv", "30m_1h.csv"])
def test_duration_from_filename_rejects_missing_zero_or_ambiguous_values(filename):
    with pytest.raises(ValueError, match="exactly one positive duration"):
        duration_from_filename(filename)


def test_csv_hydrograph_normalises_hours_and_litres_per_second():
    hydrograph = parse_csv_hydrograph(
        "inflow_002h.csv",
        b"time,flow\n0,0\n0.5,1000\n1,0\n",
        time_column="time",
        flow_column="flow",
        time_unit="hours",
        flow_unit="L/s",
    )

    assert hydrograph["duration_minutes"] == 120
    assert hydrograph["timestep_minutes"] == 30
    assert hydrograph["discharge_cms"] == [0.0, 1.0, 0.0]
    assert hydrograph["volume_m3"] == 1800.0


def test_ts1_hydrograph_uses_declared_units():
    hydrograph = parse_ts1_hydrograph(
        "run_0030m.ts1",
        b"! TUFLOW export\nTime (min),Flow (L/s)\n0,0\n15,500\n30,0\n",
    )

    assert hydrograph["duration_minutes"] == 30
    assert hydrograph["timestep_minutes"] == 15
    assert hydrograph["discharge_cms"] == [0.0, 0.5, 0.0]


def test_parser_rejects_uneven_time_steps():
    with pytest.raises(ValueError, match="evenly spaced"):
        parse_csv_hydrograph(
            "run_30m.csv",
            b"time,flow\n0,0\n10,1\n25,0\n",
            time_column="time",
            flow_column="flow",
            time_unit="minutes",
            flow_unit="m3/s",
        )


def _external_hydrographs():
    return [
        {
            "filename": "small_0030m.csv",
            "duration_minutes": 30,
            "timestep_minutes": 15.0,
            "time_minutes": [0.0, 15.0, 30.0],
            "discharge_cms": [0.0, 0.1, 0.0],
            "source_format": "csv",
            "flow_column": "flow",
        },
        {
            "filename": "large_001h.csv",
            "duration_minutes": 60,
            "timestep_minutes": 30.0,
            "time_minutes": [0.0, 30.0, 60.0],
            "discharge_cms": [0.0, 0.3, 0.0],
            "source_format": "csv",
            "flow_column": "flow",
        },
    ]


def _basin_inputs():
    return {
        "basin_base_length_m": 8.0,
        "basin_base_width_m": 5.0,
        "basin_side_slope_ratio": 4.0,
        "basin_max_depth_m": 1.2,
        "vertical_k_mm_per_hr": 50.0,
        "horizontal_k_mm_per_hr": None,
        "design_drain_time_hours": 24.0,
        "soil_moderation_factor": 0.5,
        "initial_moisture_deficit": 0.2,
        "capillary_suction_head_m": 0.15,
        "specific_yield": 0.25,
        "surface_level_m_ahd": 10.0,
        "design_gwl_m_ahd": 7.0,
        "base_aquifer_level_m_ahd": 0.0,
        "basin_side_infil_enabled": True,
    }


def test_external_design_compares_every_uploaded_event():
    result = run_design_analysis(
        {**_basin_inputs(), "external_hydrographs": _external_hydrographs()}
    )

    assert result["climate_scenario_label"] == "External hydrographs"
    assert [row["source_filename"] for row in result["runoff_table"]] == [
        "small_0030m.csv",
        "large_001h.csv",
    ]
    assert result["model_runs"][0]["depth_summary"]["source_filename"] == "large_001h.csv"


def test_external_clogging_preserves_controlling_event_provenance():
    result = run_clogging_analysis(
        {
            **_basin_inputs(),
            "latitude": -31.95,
            "longitude": 115.86,
            "catchments": [],
            "design_aep_percent": 5.0,
            "critical_duration_minutes": 60,
            "critical_pattern_rank": 1,
            "clogging_years": 1,
            "final_k_cl_m_per_day": 0.1,
            "final_l_cl_m": 0.1,
            "external_hydrographs": _external_hydrographs(),
        }
    )

    assert len(result["timeline"]) == 2
    assert result["timeline"][0]["source_filename"] == "large_001h.csv"
