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

filepath = r"C:\Users\patri\OneDrive\BaSIM v2.0\CATCH_A_Catchments_1% AEP, 2 hour burst, Storm 7.ts1"
header_line = 0
with open(filepath, 'r') as f:
    for i, line in enumerate(f):
        if line.startswith('Time (min)'):
            header_line = i
            break
df_ts = pd.read_csv(filepath, skiprows=header_line)
flow_m3s = df_ts.iloc[:, 1].values

q_in_m3s = flow_m3s
if len(q_in_m3s) != len(dSdt):
    q_in_m3s = np.resize(q_in_m3s, len(dSdt))

qinf_ts = q_in_m3s - dSdt

order = np.argsort(stages)
stg_sorted = stages[order]
qinf_sorted = qinf_ts[order]
win = max(3, min(51, (len(qinf_sorted) // 20) * 2 + 1))
kernel = np.ones(win, dtype=float) / float(win)
qinf_smooth = np.convolve(qinf_sorted, kernel, mode='same')

print(f"qinf_sorted first 10: {qinf_sorted[:10]}")
print(f"qinf_smooth first 10: {qinf_smooth[:10]}")
