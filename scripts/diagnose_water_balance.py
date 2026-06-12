"""
Diagnose water balance calculation issues
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def diagnose_water_balance():
    """Diagnose the water balance calculation issues"""
    
    # Find a recent water balance CSV
    csv_files = list(Path(ROOT / "model_output").rglob("water_balance_timeseries.csv"))
    if not csv_files:
        print("No water balance CSV files found")
        return
    
    # Use most recent
    csv_file = max(csv_files, key=lambda p: p.stat().st_mtime)
    print(f"Analyzing: {csv_file}")
    print(f"File size: {csv_file.stat().st_size} bytes")
    
    # Load and inspect
    df = pd.read_csv(csv_file)
    print(f"\nShape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    
    # Check for issues
    print("\n=== DATA INTEGRITY CHECKS ===")
    
    # 1. Time values
    if 'time_days' in df.columns:
        t = df['time_days'].values
        print(f"\nTime range: {t.min():.3f} to {t.max():.3f} days")
        if t.min() < 0:
            print("❌ ERROR: Negative time values detected!")
            print(f"   First 5 time values: {t[:5]}")
        
        dt = np.diff(t)
        if np.any(dt <= 0):
            print("❌ ERROR: Non-monotonic time!")
            bad_idx = np.where(dt <= 0)[0]
            print(f"   Issues at indices: {bad_idx[:10]}")
    
    # 2. Physical constraints
    if 'storage_m3' in df.columns:
        storage = df['storage_m3'].values
        if np.any(storage < -1e-6):
            print(f"\n❌ ERROR: Negative storage detected!")
            print(f"   Min storage: {storage.min():.3f} m³")
            neg_idx = np.where(storage < 0)[0]
            print(f"   Negative at {len(neg_idx)} timesteps")
    
    # 3. Cumulative values
    if 'cum_inflow_m3' in df.columns and 'cum_infiltrated_m3' in df.columns:
        cum_in = df['cum_inflow_m3'].values
        cum_inf = df['cum_infiltrated_m3'].values
        
        # Check if they're identical (which would be wrong)
        if np.allclose(cum_in, cum_inf, rtol=1e-10):
            print(f"\n❌ ERROR: Cumulative inflow and infiltration are identical!")
            print(f"   This is physically impossible")
        
        # Check if infiltration exceeds inflow
        excess = cum_inf - cum_in
        if np.any(excess > 1e-6):
            print(f"\n❌ ERROR: Cumulative infiltration exceeds inflow!")
            print(f"   Max excess: {excess.max():.3f} m³")
    
    # 4. Check water balance
    if all(col in df.columns for col in ['cum_inflow_m3', 'storage_m3', 'cum_infiltrated_m3']):
        cum_in = df['cum_inflow_m3'].values
        storage = df['storage_m3'].values
        cum_inf = df['cum_infiltrated_m3'].values
        
        # Water balance: cum_infiltration should equal cum_inflow - storage (ignoring spill)
        expected_inf = cum_in - storage
        error = cum_inf - expected_inf
        
        print(f"\n=== WATER BALANCE CHECK ===")
        print(f"Max absolute error: {np.abs(error).max():.3f} m³")
        if np.abs(error).max() > 1.0:
            print("❌ Water balance error exceeds 1 m³")
            
    # 5. Show first and last rows
    print(f"\n=== FIRST 5 ROWS ===")
    print(df.head())
    
    print(f"\n=== LAST 5 ROWS ===")
    print(df.tail())
    
    # 6. Check for calculation method
    print(f"\n=== CHECKING CALCULATION SOURCE ===")
    # Look for the model output directory
    model_dir = csv_file.parent
    
    # Check if there's a LAK observation file
    lak_obs_files = list(model_dir.glob("*LAK*.csv"))
    if lak_obs_files:
        print(f"Found LAK observation files: {[f.name for f in lak_obs_files]}")
        # Load and check
        for lak_file in lak_obs_files[:1]:  # Just check first one
            lak_df = pd.read_csv(lak_file)
            print(f"\nLAK file shape: {lak_df.shape}")
            print(f"LAK columns: {list(lak_df.columns)}")
            if 'STORAGE' in lak_df.columns and 'time' in lak_df.columns:
                print(f"LAK storage range: {lak_df['STORAGE'].min():.1f} to {lak_df['STORAGE'].max():.1f}")
    
    # 7. Check configuration
    config_file = model_dir / "config.json"
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
        print(f"\n=== CONFIGURATION ===")
        print(f"Post-storm days: {config.get('post_storm_days', 'N/A')}")
        print(f"Post-storm step hours: {config.get('post_storm_step_hours', 'N/A')}")
        
    return csv_file

if __name__ == "__main__":
    diagnose_water_balance()