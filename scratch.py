import sys
import json
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path("src").resolve()))
from usg_model_builder import run_simulation

config1 = {
    "scenario_title": "Test1",
    "basin_geometry": {"length_floor": 20, "width_floor": 20, "max_depth": 2, "floor_elev": 5},
    "aquifer": {"k_horizontal_mpd": 1, "k_vertical_mpd": 1, "sy": 0.2, "ss": 1e-4, "initial_head": 1, "aquifer_bottom": -20},
    "infiltration": {"bed_thickness_m": 0.5, "bed_k_mpd": 0.01, "mode": "vertical"},
    "catchment": {"area_ha": 1, "paved_fraction": 1},
    "rainfall": {"timestep_minutes": 5, "depths_mm": [5, 10, 5]},
    "post_storm_days": 2,
    "post_storm_step_hours": 2
}

config2 = dict(config1)
config2["infiltration"] = {"bed_thickness_m": 0.5, "bed_k_mpd": 10.0, "mode": "vertical"}

ok1, sum1, ts1, out1 = run_simulation("", config1)
print("Config1 (k=0.01) Peak Stage:", sum1.get("peak_stage_m"))

ok2, sum2, ts2, out2 = run_simulation("", config2)
print("Config2 (k=10.0) Peak Stage:", sum2.get("peak_stage_m"))
