"""
Direct fix for the water balance calculation
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def fix_water_balance():
    """Fix the water balance calculation directly"""
    
    engine_file = ROOT / "src" / "main_phase3_step32_time_varying.py"
    
    print("=== FIXING WATER BALANCE CALCULATION ===\n")
    
    # Read the file
    with open(engine_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Backup
    backup_file = engine_file.with_suffix('.py.before_wb_fix')
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"✅ Backup saved to: {backup_file.name}")
    
    # Find and fix the problematic lines
    fixed_lines = []
    changes = []
    
    for i, line in enumerate(lines):
        # Fix the cumulative inflow calculation
        if 'cum_inflow_at_stage = np.interp(t_stage_sec' in line:
            # This is interpolating inflow at stage times, but we need actual cumulative
            print(f"Found interpolation at line {i+1}")
            # Keep the line but mark for fixing
            fixed_lines.append(line)
            
        # Fix the main calculation around line 271
        elif 'cum_infil_m3 = np.maximum(0.0, cum_inflow_at_stage - storage_m3)' in line:
            print(f"Found main calculation at line {i+1}")
            indent = len(line) - len(line.lstrip())
            spaces = ' ' * indent
            
            # Replace with correct calculation
            # First we need to compute actual cumulative inflow
            new_lines = [
                f"{spaces}# Compute actual cumulative inflow at stage observation times\n",
                f"{spaces}# Integrate inflow over time properly\n",
                f"{spaces}cum_inflow_actual = np.zeros_like(t_stage_sec)\n",
                f"{spaces}for j, t in enumerate(t_stage_sec):\n",
                f"{spaces}    if j == 0:\n",
                f"{spaces}        # First point - integrate from 0 to t\n",
                f"{spaces}        mask = t_inflow_sec <= t\n",
                f"{spaces}        if np.any(mask):\n",
                f"{spaces}            t_use = t_inflow_sec[mask]\n",
                f"{spaces}            q_use = inflow_m3s[mask]\n",
                f"{spaces}            if len(t_use) > 1:\n",
                f"{spaces}                cum_inflow_actual[j] = np.trapz(q_use, t_use)\n",
                f"{spaces}            else:\n",
                f"{spaces}                cum_inflow_actual[j] = q_use[0] * t_use[0]\n",
                f"{spaces}    else:\n",
                f"{spaces}        # Subsequent points - add integral from previous t to current t\n",
                f"{spaces}        t_prev = t_stage_sec[j-1]\n",
                f"{spaces}        mask = (t_inflow_sec > t_prev) & (t_inflow_sec <= t)\n",
                f"{spaces}        t_segment = np.concatenate([[t_prev], t_inflow_sec[mask], [t]])\n",
                f"{spaces}        q_segment = np.concatenate([[np.interp(t_prev, t_inflow_sec, inflow_m3s)],\n",
                f"{spaces}                                     inflow_m3s[mask],\n",
                f"{spaces}                                     [np.interp(t, t_inflow_sec, inflow_m3s)]])\n",
                f"{spaces}        cum_inflow_actual[j] = cum_inflow_actual[j-1] + np.trapz(q_segment, t_segment)\n",
                f"{spaces}\n",
                f"{spaces}# Now calculate infiltration correctly\n",
                f"{spaces}cum_infil_m3 = cum_inflow_actual - storage_m3\n",
                f"{spaces}cum_infil_m3 = np.maximum(0.0, cum_infil_m3)  # Non-negative\n",
            ]
            
            for new_line in new_lines:
                fixed_lines.append(new_line)
            changes.append((i+1, "Fixed cumulative calculation"))
            
        # Update the DataFrame creation to use the corrected cumulative inflow
        elif "'cum_inflow_m3': cum_inflow_at_stage" in line:
            print(f"Found DataFrame at line {i+1}")
            # Replace with actual cumulative inflow
            fixed_line = line.replace('cum_inflow_at_stage', 'cum_inflow_actual')
            fixed_lines.append(fixed_line)
            changes.append((i+1, "Updated DataFrame to use corrected cumulative inflow"))
            
        else:
            fixed_lines.append(line)
    
    if changes:
        # Write the fixed file
        with open(engine_file, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
        
        print(f"\n✅ Applied {len(changes)} fixes:")
        for line_num, desc in changes:
            print(f"   Line {line_num}: {desc}")
        
        # Verify syntax
        try:
            with open(engine_file, 'r', encoding='utf-8') as f:
                compile(f.read(), str(engine_file), 'exec')
            print("\n✅ Syntax check passed")
            return True
        except SyntaxError as e:
            print(f"\n❌ Syntax error: {e}")
            # Restore backup
            with open(backup_file, 'r', encoding='utf-8') as f:
                content = f.read()
            with open(engine_file, 'w', encoding='utf-8') as f:
                f.write(content)
            print("⚠️ Restored backup")
            return False
    else:
        print("❌ Could not find lines to fix")
        return False

if __name__ == "__main__":
    if fix_water_balance():
        print("\n✅ Water balance fix applied successfully!")
        print("\n📌 Next steps:")
        print("1. Run a new simulation from the GUI")
        print("2. Check the Time Series tab - cumulative infiltration should now be correct")
        print("3. Run verify_water_balance.py to confirm")
    else:
        print("\n❌ Fix failed")