import sys
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path("src").resolve()))
from usg_model_builder import run_simulation

config3 = {
    "scenario_title": "Test3",
    "basin_geometry": {"length_floor": 20, "width_floor": 20, "max_depth": 2, "floor_elev": 5},
    "aquifer": {"k_horizontal_mpd": 1, "k_vertical_mpd": 100, "sy": 0.2, "ss": 1e-4, "initial_head": 1, "aquifer_bottom": -20},
    "infiltration": {"bed_thickness_m": 0.5, "bed_k_mpd": 10.0, "mode": "vertical"},
    "catchment": {"area_ha": 1, "paved_fraction": 1},
    "rainfall": {"timestep_minutes": 5, "depths_mm": [5, 10, 5]},
    "post_storm_days": 2,
    "post_storm_step_hours": 2
}

ok3, sum3, ts3, out3 = run_simulation("", config3)
print("Config3 (kv=100) Peak Stage:", sum3.get("peak_stage_m"))
