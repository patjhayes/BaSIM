import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pandas as pd
import numpy as np

model_dir = r"C:\Users\patri\Documents\BaSIM\model_output\usg_scenarios\Pipe_Outlet\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7"
df = pd.read_csv(model_dir + "\\usg_basin_lak_stage.csv")
times = df['time_days'].values
stages = df['stage_m'].values

from src.utils.outlet_hydraulics import _geom_stage_to_storage_fn
basin_cfg = {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0}
stg2vol, _ = _geom_stage_to_storage_fn(basin_cfg, 5.0)

t_sec = times * 86400.0
dt = np.diff(t_sec)
dt = np.where(dt == 0.0, 1e-3, dt)
storage_m3_arr = stg2vol(stages)
dS = np.diff(storage_m3_arr)
dSdt = np.concatenate([[dS[0] / dt[0]], dS / dt])

idx = np.argmax(dSdt)
print(f"Max dSdt at idx {idx}: {dSdt[idx]}")
print(f"Stage prev: {stages[idx-1]}, Stage curr: {stages[idx]}")
print(f"Storage prev: {storage_m3_arr[idx-1]}, Storage curr: {storage_m3_arr[idx]}")
if idx > 0:
    print(f"dt: {dt[idx-1]}")
