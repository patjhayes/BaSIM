import numpy as np
import pandas as pd
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.outlet_hydraulics import apply_outlet_to_results, create_outlet_from_config

df = pd.read_csv(r"C:\Users\patri\Documents\BaSIM\model_output\usg_scenarios\Pipe_Outlet\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7\usg_basin_lak_stage.csv")
times = df['time_days'].values
stages = df['stage_m'].values
n = len(times)

df_in = pd.read_csv(r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1", skiprows=6, names=['time', 'flow'])
flows_m3day = (df_in['flow'].values * 86400.0)

basin_cfg = {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0}

out_cfg = {
    "enabled": True, "type": "pipe", "count": 1, "diameter_m": 0.3, "length_m": 10.0, "invert_mAHD": 5.5,
    "grade": 0.01, "mannings_n": 0.013, "entrance_type": "headwall"
}
out_structs = create_outlet_from_config(out_cfg)

res_out = apply_outlet_to_results(
    time_days=times,
    modflow_stage=stages,
    modflow_inflow=flows_m3day / 86400.0,
    modflow_infiltration=None,
    outlet_structure=out_structs,
    basin_geometry=basin_cfg,
    floor_elev=5.0
)

print("time\tstg\tS\tQout\tQinf")
for i in range(10):
    print(f"{res_out['time_days'][i]:.5f}\t{res_out['stage_with_outlet'][i]:.5f}\t{res_out['storage_with_outlet'][i]:.5f}\t{res_out['outlet_discharge'][i]:.5f}\t{res_out['infiltration_m3s'][i]:.5f}")
