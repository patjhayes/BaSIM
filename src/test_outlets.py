import os
import json
import time
import sys
import copy

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.usg_model_builder import run_simulation

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

scenarios = []

# 1. Base Case (No Outlet)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "No_Outlet"
scenarios.append(("No_Outlet", cfg))

# 2. Pipe Outlet (300mm pipe, set at invert 5.5m - half a meter up)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Pipe_Outlet"
cfg["outlet"] = {
    "enabled": True,
    "type": "pipe",
    "count": 1,
    "diameter_m": 0.3,
    "length_m": 10.0,
    "invert_mAHD": 5.5,
    "grade": 0.01,
    "mannings_n": 0.013,
    "entrance_type": "headwall"
}
scenarios.append(("Pipe_Outlet", cfg))

# 3. Weir Outlet (2m broad crested weir, set at 6.0m - 1m up)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Weir_Outlet"
cfg["outlet"] = {
    "enabled": True,
    "type": "weir",
    "crest_mAHD": 6.0,
    "crest_length_m": 2.0,
    "Cd": 1.6
}
scenarios.append(("Weir_Outlet", cfg))

# 4. Grated Inlet Outlet (set at 5.5m)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Grate_Outlet"
cfg["outlet"] = {
    "enabled": True,
    "type": "grate",
    "crest_mAHD": 5.5,
    "grate_area_m2": 1.0,
    "perimeter_m": 4.0,
    "grate_type": "generic"
}
scenarios.append(("Grate_Outlet", cfg))

# 5. Combined Outlet (Pipe + Weir)
cfg = copy.deepcopy(base_config)
cfg["scenario_title"] = "Combined_Outlet"
cfg["outlet"] = [
    {
        "enabled": True,
        "type": "pipe",
        "count": 1,
        "diameter_m": 0.3,
        "length_m": 10.0,
        "invert_mAHD": 5.5,
        "grade": 0.01,
        "mannings_n": 0.013,
        "entrance_type": "headwall"
    },
    {
        "enabled": True,
        "type": "weir",
        "crest_mAHD": 6.5, # Secondary overflow weir higher up
        "crest_length_m": 2.0,
        "Cd": 1.6
    }
]
scenarios.append(("Combined_Outlet", cfg))

results = []

for name, config in scenarios:
    print(f"\nRunning Scenario: {name}")
    t0 = time.time()
    
    config["name"] = name
    success, summary, _ = run_simulation(ts1_path, config)
        
    t_run = time.time() - t0
    
    results.append({
        "Scenario": name,
        "Success": success,
        "Time (s)": round(t_run, 1),
        "Stage (m)": summary.get("peak_stage_m", "FAIL") if success else "FAIL",
        "Stage w/Outlet (m)": summary.get("peak_stage_with_outlet_m", "N/A") if success and summary.get("outlet_enabled") else "N/A",
        "Peak Outflow (m3/s)": summary.get("peak_outlet_m3s", "N/A") if success and summary.get("outlet_enabled") else "N/A"
    })

# Write markdown report
out_path = r"C:\Users\patri\.gemini\antigravity\brain\d84dd9af-d7c1-4fa6-a402-43d228dc2671\outlet_test_results.md"
md = "# Outlet Testing Results\n\n"
md += "| Scenario | Success | Runtime (s) | Raw Stage (m) | Stage w/ Outlet (m) | Peak Outflow (m3/s) |\n"
md += "|---|---|---|---|---|---|\n"

for r in results:
    if isinstance(r['Stage (m)'], float) and r['Stage (m)'] > 10.0:
        s_raw = "Diverged (Overflow)"
    else:
        s_raw = f"{r['Stage (m)']:.3f}" if isinstance(r['Stage (m)'], float) else r['Stage (m)']
    
    s_out = f"{r['Stage w/Outlet (m)']:.3f}" if isinstance(r['Stage w/Outlet (m)'], float) else r['Stage w/Outlet (m)']
    q_out = f"{r['Peak Outflow (m3/s)']:.3f}" if isinstance(r['Peak Outflow (m3/s)'], float) else r['Peak Outflow (m3/s)']
    
    md += f"| {r['Scenario']} | {r['Success']} | {r['Time (s)']} | {s_raw} | {s_out} | {q_out} |\n"

with open(out_path, 'w') as f:
    f.write(md)
    
print("Done. Results written to outlet_test_results.md")
