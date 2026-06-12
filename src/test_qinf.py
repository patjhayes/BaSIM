import os, sys, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pandas as pd
import numpy as np

times = pd.read_csv(r"C:\Users\patri\Documents\BaSIM\model_output\usg_scenarios\Pipe_Outlet\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7\usg_basin_lak_stage.csv")['time_days'].values
stages = pd.read_csv(r"C:\Users\patri\Documents\BaSIM\model_output\usg_scenarios\Pipe_Outlet\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7\usg_basin_lak_stage.csv")['stage_m'].values

from src.utils.outlet_hydraulics import _geom_stage_to_storage_fn
basin_cfg = {"length_floor": 50.0, "width_floor": 30.0, "max_depth": 2.0, "floor_elev": 5.0}
stg2vol, _ = _geom_stage_to_storage_fn(basin_cfg, 5.0)

t_sec = times * 86400.0
dt = np.diff(t_sec)
dt[dt == 0.0] = 1e-3
storage_m3_arr = stg2vol(stages)
dS = np.diff(storage_m3_arr)
dSdt = np.concatenate([[dS[0] / dt[0]], dS / dt])

df_in = pd.read_csv(r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1", skiprows=6, names=['time', 'flow'])
q_in_m3s = df_in['flow'].values
if len(q_in_m3s) > len(dSdt):
    q_in_m3s = q_in_m3s[1:]

qinf_ts = q_in_m3s - dSdt
qinf_ts = np.maximum(0.0, qinf_ts)

print(f"Qin[0:5]: {q_in_m3s[:5]}")
print(f"dSdt[0:5]: {dSdt[:5]}")
print(f"Qinf[0:5]: {qinf_ts[:5]}")
print(f"Stages[0:5]: {stages[:5]}")
