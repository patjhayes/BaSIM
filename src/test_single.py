import os, sys, json, time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.usg_model_builder import run_simulation
ts1_path = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"
cfg = {
    "scenario_title": "Pipe_Outlet",
    "basin_geometry": {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0},
    "aquifer": {"k_horizontal_mpd": 20.0, "k_vertical_mpd": 2.0, "sy": 0.05, "initial_head": 1.0},
    "infiltration": {"mode": "vertical", "bed_thickness_m": 0.5, "bed_k_mpd": 5.0},
    "outlet": {
        "enabled": True, "type": "pipe", "count": 1, "diameter_m": 0.3, "length_m": 10.0, "invert_mAHD": 5.5,
        "grade": 0.01, "mannings_n": 0.013, "entrance_type": "headwall"
    }
}
print(f"Running Scenario: Pipe_Outlet")
t0 = time.time()
try:
    success, summary, _ = run_simulation(ts1_path, cfg)
except Exception as e:
    success = False
    summary = {"error": str(e)}
t_run = time.time() - t0
print(f"Success: {success}, Time: {t_run:.1f}s")
print(json.dumps(summary, indent=2))
