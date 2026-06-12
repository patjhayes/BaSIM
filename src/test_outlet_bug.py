import numpy as np
import pandas as pd
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.outlet_hydraulics import apply_outlet_to_results, create_outlet_from_config

filepath = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"
header_line = 0
with open(filepath, 'r') as f:
    for i, line in enumerate(f):
        if line.startswith('Time (min)'):
            header_line = i
            break
df_in = pd.read_csv(filepath, skiprows=header_line)

times = (df_in.iloc[:, 0].values * 60) / 86400.0  # minutes to days
qin = df_in.iloc[:, 1].values # m3/s

basin_cfg = {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0}

out_cfg = {
    "enabled": True, "type": "pipe", "count": 1, "diameter_m": 0.3, "length_m": 10.0, "invert_mAHD": 5.5,
    "grade": 0.01, "mannings_n": 0.013, "entrance_type": "headwall"
}
out_structs = create_outlet_from_config(out_cfg)

res = apply_outlet_to_results(
    time_days=times,
    modflow_stage=np.ones_like(times) * 5.0, # Dummy modflow stage
    modflow_inflow=qin,
    modflow_infiltration={"stage_grid": [5.0, 6.0], "qinf_grid": [0.069, 0.069]}, # 0.069 m3/s infiltration
    outlet_structure=out_structs,
    basin_geometry=basin_cfg,
    floor_elev=5.0
)

print(f"Max Qin: {np.max(qin):.5f}")
print(f"Max Stage: {np.max(res['stage_with_outlet']):.5f}")
print(f"Max Storage: {np.max(res['storage_with_outlet']):.5f}")
print(f"Total Inflow m3: {np.sum(qin * np.diff(np.append([0], times)) * 86400):.5f}")
