import pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path

# Load data from the scratch runs
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
config2["scenario_title"] = "Test2"
config2["infiltration"] = {"bed_thickness_m": 0.5, "bed_k_mpd": 10.0, "mode": "vertical"}

# Since we already ran these, let's just use run_simulation again (it's fast)
ok1, sum1, ts1, out1 = run_simulation("", config1)
ok2, sum2, ts2, out2 = run_simulation("", config2)

plt.figure(figsize=(10, 6))
plt.plot(ts1["time_days"], ts1["stage_m"], label="k = 0.01 m/day (Low Permeability)", linewidth=2)
plt.plot(ts2["time_days"], ts2["stage_m"], label="k = 10.0 m/day (High Permeability)", linewidth=2, linestyle='--')
plt.axhline(5.0, color='gray', linestyle=':', label="Basin Floor (5.0m)")
plt.xlabel("Time (Days)")
plt.ylabel("Stage (m AHD)")
plt.title("Basin Stage over Time: Peak Stage vs. Drain Time")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig("c:/Users/patri/.gemini/antigravity-ide/brain/9eca51f1-ae74-4997-81b7-a73bbab1f67a/stage_comparison.png")
