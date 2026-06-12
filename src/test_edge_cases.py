import os
import json
import time
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.usg_model_builder import _run_usg_model
from src.nwt_model_builder import _run_nwt_model

ts1_path = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"

base_config = {
    "scenario_title": "Base Scenario",
    "basin_geometry": {
        "length_floor": 50.0,
        "width_floor": 30.0,
        "max_depth": 2.0,
        "floor_elev": 5.0
    },
    "aquifer": {
        "k_horizontal_mpd": 20.0,
        "k_vertical_mpd": 2.0,
        "sy": 0.05,
        "initial_head": 1.0 # 4m clearance
    },
    "infiltration": {
        "mode": "vertical",
        "bed_thickness_m": 0.5,
        "bed_k_mpd": 5.0
    }
}

import copy

scenarios = []

# Base Case
scenarios.append(("Base_Case", base_config))

# High Infiltration
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "High_Infiltration"
cfg["infiltration"]["bed_k_mpd"] = 15.0
scenarios.append(("High_Infiltration", cfg))

# Clogged Layer
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Clogged_Layer"
cfg["infiltration"]["bed_k_mpd"] = 0.5
scenarios.append(("Clogged_Layer", cfg))

# Shallow Groundwater (High Water Table)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Shallow_Groundwater"
cfg["aquifer"]["initial_head"] = 4.5 # 0.5m clearance
scenarios.append(("Shallow_Groundwater", cfg))

# Small Basin
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Small_Basin"
cfg["basin_geometry"]["length_floor"] = 20.0
cfg["basin_geometry"]["width_floor"] = 20.0
scenarios.append(("Small_Basin", cfg))

results = []

for name, config in scenarios:
    print(f"\nRunning Scenario: {name}")
    
    # Run NWT
    print("  Running NWT...")
    t0 = time.time()
    try:
        nwt_success, nwt_summary, _ = _run_nwt_model(ts1_path, config)
    except Exception as e:
        nwt_success = False
        nwt_summary = {"error": str(e)}
    t_nwt = time.time() - t0
        
    # Run USG
    print("  Running USG...")
    t0 = time.time()
    try:
        usg_success, usg_summary, _ = _run_usg_model(ts1_path, config)
    except Exception as e:
        usg_success = False
        usg_summary = {"error": str(e)}
    t_usg = time.time() - t0
    
    results.append({
        "Scenario": name,
        "NWT Success": nwt_success,
        "USG Success": usg_success,
        "NWT Stage (m)": nwt_summary.get("peak_stage_m", "N/A") if nwt_success else "FAIL",
        "USG Stage (m)": usg_summary.get("peak_stage_m", "N/A") if usg_success else "FAIL",
        "NWT Time (s)": round(t_nwt, 1),
        "USG Time (s)": round(t_usg, 1)
    })

# Write to markdown table
md = "# Edge Case Testing Results\n\n"
md += "| Scenario | NWT Peak Stage (m) | USG Peak Stage (m) | NWT Time (s) | USG Time (s) | NWT Success | USG Success |\n"
md += "|---|---|---|---|---|---|---|\n"
for r in results:
    if isinstance(r["NWT Stage (m)"], float):
        nwt_stage = f"{r['NWT Stage (m)']:.3f}"
    else:
        nwt_stage = r["NWT Stage (m)"]
        
    if isinstance(r["USG Stage (m)"], float):
        usg_stage = f"{r['USG Stage (m)']:.3f}"
    else:
        usg_stage = r["USG Stage (m)"]
        
    md += f"| {r['Scenario']} | {nwt_stage} | {usg_stage} | {r['NWT Time (s)']} | {r['USG Time (s)']} | {r['NWT Success']} | {r['USG Success']} |\n"

with open(r"C:\Users\patri\.gemini\antigravity\brain\d84dd9af-d7c1-4fa6-a402-43d228dc2671\edge_case_results.md", "w") as f:
    f.write(md)
    
print("Done. Results written to edge_case_results.md")
