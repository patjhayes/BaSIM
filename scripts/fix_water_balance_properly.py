"""
Fix the water balance calculation properly - infiltration must account for storage changes
"""
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def fix_water_balance():
    """Fix the water balance calculation to be physically correct"""
    
    engine_file = ROOT / "src" / "main_phase3_step32_time_varying.py"
    
    print("=== FIXING WATER BALANCE CALCULATION ===\n")
    print("Physical principle: Inflow = ΔStorage + Infiltration + Spill")
    print("Therefore: Cumulative Infiltration = Cumulative Inflow - Current Storage - Cumulative Spill")
    print("With no spill: Cumulative Infiltration = Cumulative Inflow - Current Storage\n")
    
    # Read the file
    with open(engine_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Backup
    backup_file = engine_file.with_suffix('.py.wb_backup')
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"✅ Backup saved to: {backup_file.name}")
    
    # Find and fix the calculation
    fixed_lines = []
    found_calc = False
    
    for i, line in enumerate(lines):
        # Find the cumulative infiltration calculation (around line 271)
        if 'cum_infil_m3 = np.maximum(0.0, cum_inflow_at_stage - storage_m3)' in line or \
           'cum_infil_m3 = cum_inflow_actual - storage_m3' in line:
            print(f"Found calculation at line {i+1}")
            found_calc = True
            
            indent = len(line) - len(line.lstrip())
            spaces = ' ' * indent
            
            # Replace with correct calculation
            new_lines = [
                f"{spaces}# WATER BALANCE: Inflow = ΔStorage + Infiltration + Spill\n",
                f"{spaces}# With no spill: Cumulative Infiltration = Cumulative Inflow - Current Storage\n",
                f"{spaces}# This is already correct, but we need to ensure cum_inflow is properly calculated\n",
                f"{spaces}\n",
                f"{spaces}# First, properly integrate the inflow to get cumulative inflow\n",
                f"{spaces}# cum_inflow_at_stage was interpolated, but we need the actual integral\n",
                f"{spaces}cum_inflow_proper = np.zeros_like(t_stage_sec)\n",
                f"{spaces}for j in range(len(t_stage_sec)):\n",
                f"{spaces}    t_current = t_stage_sec[j]\n",
                f"{spaces}    # Find all inflow data up to current time\n",
                f"{spaces}    mask = t_inflow_sec <= t_current\n",
                f"{spaces}    if np.any(mask):\n",
                f"{spaces}        t_subset = t_inflow_sec[mask]\n",
                f"{spaces}        q_subset = inflow_m3s[mask]\n",
                f"{spaces}        # Add the interpolated point at t_current if needed\n",
                f"{spaces}        if len(t_subset) > 0 and t_subset[-1] < t_current:\n",
                f"{spaces}            t_subset = np.append(t_subset, t_current)\n",
                f"{spaces}            q_at_current = np.interp(t_current, t_inflow_sec, inflow_m3s)\n",
                f"{spaces}            q_subset = np.append(q_subset, q_at_current)\n",
                f"{spaces}        # Integrate using trapezoidal rule\n",
                f"{spaces}        if len(t_subset) > 1:\n",
                f"{spaces}            cum_inflow_proper[j] = np.trapz(q_subset, t_subset)\n",
                f"{spaces}        else:\n",
                f"{spaces}            cum_inflow_proper[j] = 0.0\n",
                f"{spaces}\n",
                f"{spaces}# Now calculate infiltration correctly\n",
                f"{spaces}# Cumulative infiltration = Cumulative inflow - Current storage (assuming no spill)\n",
                f"{spaces}cum_infil_m3 = cum_inflow_proper - storage_m3\n",
                f"{spaces}\n",
                f"{spaces}# Apply physical constraints\n",
                f"{spaces}cum_infil_m3 = np.maximum(0.0, cum_infil_m3)  # Can't be negative\n",
            ]
            
            for new_line in new_lines:
                fixed_lines.append(new_line)
            
            # Skip the original line and the try/except blocks that follow
            continue
            
        # Skip the try/except blocks for accumulate and minimum (lines 272-279)
        elif i > 0 and found_calc and ('np.maximum.accumulate' in line or 
                                       'np.minimum(cum_infil_m3, cum_inflow' in line or
                                       (line.strip() in ['try:', 'except Exception:', 'pass'])):
            # Skip these lines as we're replacing the logic
            continue
            
        # Update the DataFrame creation to use proper cumulative inflow
        elif "'cum_inflow_m3': cum_inflow_at_stage" in line:
            print(f"Found DataFrame at line {i+1}")
            # Replace with properly calculated cumulative inflow
            fixed_line = line.replace('cum_inflow_at_stage', 'cum_inflow_proper')
            fixed_lines.append(fixed_line)
            
        else:
            fixed_lines.append(line)
    
    # Write the fixed file
    with open(engine_file, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)
    
    print("\n✅ Engine updated with correct water balance calculation")
    
    # Verify syntax
    try:
        with open(engine_file, 'r', encoding='utf-8') as f:
            code = f.read()
        compile(code, str(engine_file), 'exec')
        print("✅ Syntax check passed")
        return True
    except SyntaxError as e:
        print(f"\n❌ Syntax error: {e}")
        print(f"   at line {e.lineno}: {e.text}")
        # Restore backup
        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_content = f.read()
        with open(engine_file, 'w', encoding='utf-8') as f:
            f.write(backup_content)
        print("⚠️ Restored backup due to syntax error")
        return False

if __name__ == "__main__":
    if fix_water_balance():
        print("\n✅ SUCCESS! Water balance calculation fixed")
        print("\n📌 The fix ensures:")
        print("   • Cumulative inflow is properly integrated from the hydrograph")
        print("   • Cumulative infiltration = Cumulative inflow - Current storage")
        print("   • When storage drops, infiltration increases (physically correct)")
        print("\n🔄 Next steps:")
        print("   1. Run a new simulation from the GUI")
        print("   2. Check the Time Series tab:")
        print("      • Cumulative infiltration should increase as storage decreases")
        print("      • Final: Cum. Infiltration + Final Storage = Total Inflow")
        print("   3. Run verify_water_balance.py to confirm")
    else:
        print("\n❌ Fix failed - check errors above")