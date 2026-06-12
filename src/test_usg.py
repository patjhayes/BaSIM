import os
import json
from pathlib import Path

# Fix python path for local imports
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.usg_model_builder import _run_usg_model

ts1_path = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"

config = {
    "scenario_title": "Test_USG_UI",
    "basin_geometry": {
        "length_floor": 50.0,
        "width_floor": 50.0,
        "max_depth": 2.0,
        "floor_elev": 5.0
    },
    "aquifer": {
        "k_horizontal_mpd": 20.0,
        "k_vertical_mpd": 2.0,
        "sy": 0.05,
        "initial_head": 1.0 # Deep water table (4m clearance)
    },
    "infiltration": {
        "mode": "vertical",
        "bed_thickness_m": 0.5,
        "bed_k_mpd": 5.0
    }
}

success, summary, outdir = _run_usg_model(ts1_path, config)

print(f"Success: {success}")
print("Summary:")
print(json.dumps(summary, indent=2))
print(f"Output Directory: {outdir}")
