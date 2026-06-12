"""
Trace the water balance error in detail
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def trace_error():
    """Trace where the water balance goes wrong"""
    
    # Load the problematic CSV
    csv_file = ROOT / "model_output/phase3/step32/scenarios/Scenario C/outputs/6EY_3h_TP6/water_balance_timeseries.csv"
    
    if not csv_file.exists():
        print(f"File not found: {csv_file}")
        return
        
    df = pd.read_csv(csv_file)
    
    print("=== WATER BALANCE ANALYSIS ===\n")
    
    # Extract columns
    t = df['time_days'].values
    inflow = df['inflow_m3s'].values
    storage = df['storage_m3'].values
    cum_inflow = df['cum_inflow_m3'].values
    cum_infiltrated = df['cum_infiltrated_m3'].values
    eff_infil_rate = df['effective_infiltration_m3s'].values
    
    # Calculate what cumulative infiltration SHOULD be
    # Method 1: From water balance
    cum_infil_expected = cum_inflow - storage
    
    # Method 2: Integrate the effective infiltration rate
    dt_days = np.diff(t, prepend=t[0])
    dt_seconds = dt_days * 86400
    cum_infil_integrated = np.cumsum(eff_infil_rate * dt_seconds)
    
    print(f"Total inflow: {cum_inflow[-1]:.1f} m³")
    print(f"Final storage: {storage[-1]:.1f} m³")
    print(f"Expected infiltration (inflow - storage): {cum_infil_expected[-1]:.1f} m³")
    print(f"Actual cum_infiltrated in file: {cum_infiltrated[-1]:.1f} m³")
    print(f"Integrated from rate: {cum_infil_integrated[-1]:.1f} m³")
    
    # Find where the error starts
    error = cum_infiltrated - cum_infil_expected
    
    print(f"\n=== ERROR PROGRESSION ===")
    print(f"Initial error: {error[0]:.3f} m³")
    print(f"Final error: {error[-1]:.3f} m³")
    
    # Find when error jumps
    derror = np.diff(error)
    large_jumps = np.where(np.abs(derror) > 10)[0]
    
    if len(large_jumps) > 0:
        print(f"\nLarge error jumps at indices: {large_jumps[:5]}")
        for idx in large_jumps[:3]:
            print(f"\n  At t={t[idx]:.3f} days:")
            print(f"    Inflow: {inflow[idx]:.3f} m³/s")
            print(f"    Storage: {storage[idx]:.1f} → {storage[idx+1]:.1f} m³")
            print(f"    Cum infiltrated: {cum_infiltrated[idx]:.1f} → {cum_infiltrated[idx+1]:.1f} m³")
            print(f"    Error jump: {derror[idx]:.1f} m³")
    
    # Check if cumulative values are properly cumulative
    print(f"\n=== CUMULATIVE VALUE CHECKS ===")
    
    # Check cum_inflow
    recalc_cum_inflow = np.zeros_like(cum_inflow)
    for i in range(len(t)):
        if i == 0:
            recalc_cum_inflow[i] = inflow[i] * t[i] * 86400
        else:
            dt = (t[i] - t[i-1]) * 86400  # seconds
            recalc_cum_inflow[i] = recalc_cum_inflow[i-1] + inflow[i] * dt
    
    inflow_error = cum_inflow - recalc_cum_inflow
    print(f"Cumulative inflow error: max={np.abs(inflow_error).max():.3f} m³")
    
    # Show the actual calculation being done
    print(f"\n=== WHAT'S IN THE FILE ===")
    print("First 10 rows with key columns:")
    print(df[['time_days', 'inflow_m3s', 'storage_m3', 'cum_inflow_m3', 'cum_infiltrated_m3']].head(10))
    
    # Check for the specific pattern in your screenshot
    print(f"\n=== CHECKING FOR IDENTICAL CUM_INFLOW AND CUM_INFILTRATED ===")
    identical = np.allclose(cum_inflow, cum_infiltrated, rtol=1e-6)
    print(f"Are they identical? {identical}")
    
    if not identical:
        diff = cum_infiltrated - cum_inflow
        print(f"Difference range: {diff.min():.3f} to {diff.max():.3f} m³")
        print(f"Mean difference: {diff.mean():.3f} m³")

if __name__ == "__main__":
    trace_error()