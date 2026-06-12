import os
import numpy as np
import pandas as pd
from flopy.utils import HeadFile

p = r"c:\\Users\\patri\\OneDrive\\BaSIM\\model_output\\phase3\\step32"
hds_path = os.path.join(p, 'basin_step32.hds')
if not os.path.exists(hds_path):
    raise SystemExit(f"Missing HDS: {hds_path}")

hds = HeadFile(hds_path)
heads = hds.get_alldata()  # (nt, nlay, nrow, ncol)
nt, nlay, nrow, ncol = heads.shape
ci, cj = nrow // 2, ncol // 2
conn_layer_zero = 2  # LAK connects to layer 3 (1-based)

# sample a few times plus all daily marks if available
times = np.array(hds.get_times())

rows = []
for i, t in enumerate(times):
    if i in {0, 10, 35, 36, 50, nt-1} or abs(t - round(t)) < 1e-6:
        rows.append({
            'time_days': float(t),
            'head_conn_center': float(heads[i, conn_layer_zero, ci, cj])
        })

df = pd.DataFrame(rows).sort_values('time_days')
out_csv = os.path.join(p, 'debug_center_head_timeseries.csv')
df.to_csv(out_csv, index=False)
print(df.to_string(index=False))
print(f"\nSaved: {out_csv}")
