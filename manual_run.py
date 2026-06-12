import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

# Add src to path
sys.path.append(r"c:\Users\patri\OneDrive\BaSIM v2.0\BaSIM_v1.0_source")

from src.usg_model_builder import run_simulation

ts1_file = r"C:\Users\patri\OneDrive\External\Perth\Perth_1_Catchments_1% AEP, 3 hour burst, Storm 1.ts1"
config = {
  "basin": {
    "floor_elev_m": 5.0,
    "max_depth_m": 1.5,
    "length_floor_m": 20.0,
    "width_floor_m": 10.0,
    "side_slope_hv": 3.0
  },
  "aquifer": {
    "k_horizontal_mpd": 5.0,
    "k_vertical_mpd": 5.0,
    "sy": 0.2,
    "ss": 0.0001,
    "initial_head": -2.0,
    "aquifer_bottom": -20.0,
    "domain_size_m": 500.0
  },
  "infiltration": {
    "mode": "full",
    "bed_thickness_m": 0.5,
    "bed_k_mpd": 5.0,
    "side_k_mpd": 5.0,
    "side_k_separate": False
  },
  "output_dir": r"C:\Users\patri\OneDrive\BaSIM v2.0\output\manual_test"
}

res = run_simulation(ts1_file, config)
print("Run success:", res.get("success"))
if "error" in res:
    print("Error:", res["error"])
if "summary" in res:
    print("Summary:", res["summary"])
