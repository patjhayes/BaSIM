import numpy as np
import pandas as pd
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.outlet_hydraulics import apply_outlet_to_results

df = pd.read_csv(r"C:\Users\patri\Documents\BaSIM\model_output\usg_scenarios\Pipe_Outlet\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7\usg_basin_lak_stage.csv")
times = df['time_days'].values
stages = df['stage_m'].values
n = len(times)

qin = np.zeros(n)
basin_cfg = {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0}

res = apply_outlet_to_results(
    time_days=times,
    modflow_stage=stages,
    modflow_inflow=qin,
    modflow_infiltration=None,
    outlet_structure=[],
    basin_geometry=basin_cfg,
    floor_elev=5.0
)

print("time\tstg\tS\tQout\tQinf")
for i in range(10):
    print(f"{res['time_days'][i]:.5f}\t{res['stage_with_outlet'][i]:.5f}\t{res['storage_with_outlet'][i]:.5f}\t{res['outlet_discharge'][i]:.5f}\t{res['infiltration_m3s'][i]:.5f}")
