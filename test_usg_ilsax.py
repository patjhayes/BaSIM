import os
from pathlib import Path
from src.usg_model_builder import run_simulation

config = {
    "scenario_title": "ILSAX Integration Test",
    "output_dir": str(Path("C:/Users/patri/OneDrive/BaSIM v2.0/output/ilsax_test")),
    "basin_geometry": {
        "length_floor": 20.0,
        "width_floor": 20.0,
        "max_depth": 2.0,
        "side_slope_1_in": 3.0,
        "floor_elev": 5.0,
    },
    "aquifer": {
        "k_horizontal_mpd": 10.0,
        "k_vertical_mpd": 10.0,
        "sy": 0.2,
        "ss": 1e-4,
        "initial_head": 1.0,
        "aquifer_bottom": -20.0,
        "bed_k": 0.1,
        "bed_thickness": 0.1,
    },
    "catchment": {
        "name": "Test Catchment",
        "area_ha": 1.0,
        "paved_fraction": 0.4,
        "supplementary_fraction": 0.1,
        "grassed_fraction": 0.5,
        "paved_flow_path_length_m": 50.0,
        "grassed_flow_path_length_m": 50.0,
        "supplementary_flow_path_length_m": 50.0,
        "paved_flow_path_slope_pct": 1.0,
        "grassed_flow_path_slope_pct": 1.0,
        "supplementary_flow_path_slope_pct": 1.0,
        "soil_type": 2.0,
        "amc": 3.0,
        "slope": 1.0,
    },
    "rainfall": {
        "timestep_minutes": 5.0,
        "depths_mm": [2.5, 5.0, 10.0, 5.0, 2.5]
    },
    "infiltration": {
        "bed_k_mpd": 0.1,
        "bed_thickness_m": 0.5
    },
    "post_storm_days": 1.0,
    "post_storm_step_hours": 2.0,
}

ok, summary, outdir = run_simulation("", config)
print("Run OK:", ok)
print("Summary:", summary)
print("Output Dir:", outdir)
