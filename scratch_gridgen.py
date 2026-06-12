import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from usg_model_builder import run_simulation

config = {
    "scenario_title": "Test1",
    "basin_geometry": {"length_floor": 20, "width_floor": 20, "max_depth": 2, "floor_elev": 5},
    "aquifer": {"k_horizontal_mpd": 1, "k_vertical_mpd": 1, "sy": 0.2, "ss": 1e-4, "initial_head": 1, "aquifer_bottom": -20},
    "infiltration": {"bed_thickness_m": 0.5, "bed_k_mpd": 0.01, "mode": "vertical"},
    "catchment": {"area_ha": 1, "paved_fraction": 1},
    "rainfall": {"timestep_minutes": 5, "depths_mm": [5, 10, 5]},
    "post_storm_days": 2,
    "post_storm_step_hours": 2,
    "run_name": "Gridgen Test",
    "sim_id": "test_123"
}

ok, sum, ts, out = run_simulation("", config)
print("Success:", ok)
if not ok:
    print("Error:", sum.get("error", "Unknown error"))
