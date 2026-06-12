import sys
import numpy as np
from src.hydrology.common import Catchment, Hyetograph
from src.hydrology.ilsax import simulate_catchment_runoff, summarise_hydrograph

catchment = Catchment(
    area_ha=1.0,
    paved_fraction=0.4,
    supplementary_fraction=0.1,
    grassed_fraction=0.5,
    paved_flow_path_length_m=50.0,
    paved_flow_path_slope_pct=1.0,
    grassed_flow_path_length_m=50.0,
    grassed_flow_path_slope_pct=1.0,
    soil_type=2.0,
    amc=3.0,
)

# 60 minute storm, 1 min timestep, constant 50 mm/hr intensity -> 0.833 mm/min
depths = [0.833] * 60
hyetograph = Hyetograph(timestep_minutes=1.0, depths_mm=depths)

q = simulate_catchment_runoff(catchment, hyetograph)

res = summarise_hydrograph("1% AEP", 60, 1, hyetograph, q)
print(f"Peak Q: {res.peak_discharge_cms:.3f} m3/s")
print(f"Volume: {res.runoff_volume_m3:.1f} m3")
print(f"Time to Peak: {res.time_to_peak_minutes:.1f} min")
