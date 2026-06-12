import pandas as pd

p = r"C:\Users\patri\Documents\BaSIM\model_output\phase3\step32\scenarios\CATCHA_01\inputs\1h_TP1\hydrograph.csv"
df = pd.read_csv(p)
total_m3 = (df["flow_m3s"].sum() * 60.0)
total_m3