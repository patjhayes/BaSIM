import os, sys, time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.usg_model_builder import run_simulation

ts1 = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"
cfg = {
    "name": "Pipe_Only_Test",
    "basin": {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0, "side_slope_1_in": 3.0},
    "infiltration": {"bed_thickness_m": 0.5, "clogging_factor": 1.0, "bed_k_mpd": 5.0},
    "aquifer": {"k_horizontal_mpd": 5.0, "k_vertical_mpd": 5.0, "sy": 0.05, "ss": 1e-4, "initial_head": 1.0, "aquifer_bottom": -20.0},
    "outlet": {
        "enabled": True, "type": "pipe", "count": 1, "diameter_m": 0.3, "length_m": 10.0, "invert_mAHD": 5.0,
        "grade": 0.01, "mannings_n": 0.013, "entrance_type": "headwall"
    }
}

t0 = time.time()
print("Running Pipe_Outlet...")
run_simulation(ts1, cfg)
print(f"Pipe_Outlet finished in {time.time()-t0:.1f}s")
