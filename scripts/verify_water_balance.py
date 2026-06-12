"""
Verify water balance after fix
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def verify_water_balance():
    """Verify the water balance is correct"""
    
    # Find most recent output
    csv_files = list(Path(ROOT / "model_output").rglob("water_balance_timeseries.csv"))
    if not csv_files:
        print("No water balance files found. Run a simulation first.")
        return False
        
    csv_file = max(csv_files, key=lambda p: p.stat().st_mtime)
    print(f"Checking: {csv_file.name}")
    print(f"From: {csv_file.parent.parent.name}/{csv_file.parent.name}")
    
    df = pd.read_csv(csv_file)
    
    # Extract data
    t = df['time_days'].values
    inflow = df['inflow_m3s'].values
    storage = df['storage_m3'].values
    cum_inflow = df['cum_inflow_m3'].values
    cum_infiltrated = df['cum_infiltrated_m3'].values
    
    print("\n=== WATER BALANCE VERIFICATION ===")
    
    # Check 1: No negative storage
    if np.any(storage < -1e-6):
        print(f"❌ FAIL: Negative storage detected (min={storage.min():.3f})")
        return False
    else:
        print(f"✅ PASS: Storage is non-negative")
    
    # Check 2: Cumulative infiltration <= cumulative inflow
    excess = cum_infiltrated - cum_inflow
    if np.any(excess > 1e-6):
        print(f"❌ FAIL: Infiltration exceeds inflow (max excess={excess.max():.3f} m³)")
        return False
    else:
        print(f"✅ PASS: Infiltration never exceeds inflow")
    
    # Check 3: Cumulative infiltration is monotonic
    d_cum_infil = np.diff(cum_infiltrated)
    if np.any(d_cum_infil < -1e-6):
        print(f"❌ FAIL: Cumulative infiltration decreases")
        return False
    else:
        print(f"✅ PASS: Cumulative infiltration is monotonic")
    
    # Check 4: Water balance closure
    # At any time: cum_inflow = storage + cum_infiltrated + cum_spilled
    # Assuming no spill for now
    balance_error = cum_inflow - (storage + cum_infiltrated)
    max_error = np.abs(balance_error).max()
    
    if max_error > 1.0:  # Allow 1 m³ tolerance
        print(f"❌ FAIL: Water balance error = {max_error:.3f} m³")
        print(f"   Final: Inflow={cum_inflow[-1]:.1f}, Storage={storage[-1]:.1f}, Infiltrated={cum_infiltrated[-1]:.1f}")
        print(f"   Error={balance_error[-1]:.1f} m³")
        return False
    else:
        print(f"✅ PASS: Water balance closes (max error={max_error:.3f} m³)")
    
    # Check 5: Time is positive and monotonic
    if t[0] < 0:
        print(f"❌ FAIL: Negative time values (starts at {t[0]:.3f})")
        return False
    else:
        print(f"✅ PASS: Time starts at {t[0]:.6f} days")
        
    if np.any(np.diff(t) <= 0):
        print(f"❌ FAIL: Time is not monotonic")
        return False
    else:
        print(f"✅ PASS: Time is monotonic")
    
    print("\n=== SUMMARY ===")
    print(f"Total inflow: {cum_inflow[-1]:.1f} m³")
    print(f"Final storage: {storage[-1]:.1f} m³")  
    print(f"Total infiltrated: {cum_infiltrated[-1]:.1f} m³")
    print(f"Balance check: {cum_inflow[-1]:.1f} = {storage[-1]:.1f} + {cum_infiltrated[-1]:.1f} = {storage[-1] + cum_infiltrated[-1]:.1f}")
    
    return True

if __name__ == "__main__":
    success = verify_water_balance()
    if success:
        print("\n✅ ALL CHECKS PASSED - Water balance is correct!")
    else:
        print("\n❌ WATER BALANCE ISSUES DETECTED - Please review")