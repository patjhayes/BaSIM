#!/usr/bin/env python3
"""Test script to verify MODFLOW data reading for timeseries plots."""

import pandas as pd
import numpy as np
from pathlib import Path

def test_modflow_output():
    """Test reading MODFLOW LAK output data directly."""
    # Look for existing MODFLOW output
    model_output = Path("model_output")
    obs_files = list(model_output.rglob("*_lak_allobs.csv"))
    
    if not obs_files:
        print("❌ No MODFLOW LAK observation files found")
        return False
    
    print(f"✅ Found {len(obs_files)} MODFLOW LAK observation files")
    
    # Test reading the most recent file
    obs_file = max(obs_files, key=lambda p: p.stat().st_mtime)
    print(f"📊 Testing: {obs_file}")
    
    try:
        df = pd.read_csv(obs_file)
        print(f"   Columns: {list(df.columns)}")
        print(f"   Shape: {df.shape}")
        
        # Check required columns
        required = ['time', 'LAK_EXT_INFLOW', 'LAK_STAGE']
        missing = [col for col in required if col not in df.columns]
        if missing:
            print(f"❌ Missing required columns: {missing}")
            return False
        
        # Basic data validation
        t_days = df['time'].astype(float).values
        inflow = df['LAK_EXT_INFLOW'].astype(float).values
        stage = df['LAK_STAGE'].astype(float).values
        
        print(f"   Time range: {t_days[0]:.3f} to {t_days[-1]:.3f} days")
        print(f"   Inflow range: {np.min(inflow):.6f} to {np.max(inflow):.3f} m³/s")
        print(f"   Stage range: {np.min(stage):.3f} to {np.max(stage):.3f} m")
        
        # Calculate cumulative inflow
        t_sec = t_days * 86400.0
        try:
            from scipy.integrate import cumulative_trapezoid
            cum_inflow = cumulative_trapezoid(inflow, t_sec, initial=0.0)
        except ImportError:
            dt = np.diff(t_sec)
            qm = 0.5 * (inflow[:-1] + inflow[1:])
            cum_inflow = np.concatenate([[0.0], np.cumsum(qm * dt)])
        
        print(f"   Cumulative inflow: 0 to {cum_inflow[-1]:.1f} m³")
        
        # Test LAKTAB reading
        laktab_files = list(obs_file.parent.glob("*.laktab"))
        if laktab_files:
            laktab_file = laktab_files[0]
            print(f"📈 Testing LAKTAB: {laktab_file.name}")
            
            stg_tab, vol_tab = [], []
            in_table = False
            with open(laktab_file, 'r', encoding='utf-8', errors='ignore') as tf:
                for line in tf:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    if s.upper().startswith('BEGIN TABLE'):
                        in_table = True; continue
                    if s.upper().startswith('END TABLE'):
                        break
                    if in_table:
                        parts = s.split()
                        if len(parts) >= 2:
                            try:
                                stg = float(parts[0]); vol = float(parts[1])
                                stg_tab.append(stg); vol_tab.append(max(0.0, vol))
                            except Exception:
                                pass
            
            if len(stg_tab) >= 2:
                storage = np.interp(stage, np.array(stg_tab), np.array(vol_tab))
                print(f"   LAKTAB entries: {len(stg_tab)}")
                print(f"   Storage range: {np.min(storage):.1f} to {np.max(storage):.1f} m³")
            else:
                print("   ❌ Could not parse LAKTAB")
        else:
            print("   ⚠️ No LAKTAB file found")
        
        print("✅ MODFLOW data reading successful!")
        return True
        
    except Exception as e:
        print(f"❌ Error reading MODFLOW data: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing MODFLOW output data reading...")
    success = test_modflow_output()
    if success:
        print("\n🎉 All tests passed! The timeseries will now use MODFLOW output data directly.")
    else:
        print("\n💥 Tests failed. Check MODFLOW output files.")
