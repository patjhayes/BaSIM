"""
Fix the water balance calculation in the engine
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def fix_engine():
    """Fix the water balance calculation"""
    
    engine_file = ROOT / "src" / "main_phase3_step32_time_varying.py"
    
    print("=== FIXING WATER BALANCE CALCULATION ===\n")
    
    # Read the engine file
    with open(engine_file, 'r') as f:
        lines = f.readlines()
    
    # Find and fix the water balance calculation
    fixed_lines = []
    in_wb_section = False
    changes_made = []
    
    for i, line in enumerate(lines):
        # Look for the water balance DataFrame creation
        if 'water_balance_timeseries' in line and 'DataFrame' in line:
            in_wb_section = True
            print(f"Found water balance section at line {i+1}")
        
        # Fix the cumulative infiltration calculation
        if 'cum_infiltrated_m3' in line and '=' in line and 'cum_inflow' in line:
            # This is likely the problematic line
            original = line
            # Replace with correct calculation
            if 'np.maximum' not in line:
                indent = len(line) - len(line.lstrip())
                new_line = ' ' * indent + "# Cumulative infiltration = cumulative inflow - current storage\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "# But must be non-negative and non-decreasing\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "cum_infiltrated_m3 = np.maximum.accumulate(np.maximum(0, cum_inflow_m3 - storage_m3))\n"
                fixed_lines.append(new_line)
                changes_made.append((i+1, "Fixed cumulative infiltration calculation"))
                continue
        
        # Fix effective infiltration rate calculation if needed
        if 'effective_infiltration_m3s' in line and '=' in line:
            if 'gradient' not in line and 'diff' not in line:
                # Make sure it's calculated from the derivative of cumulative infiltration
                indent = len(line) - len(line.lstrip())
                new_line = ' ' * indent + "# Effective infiltration rate is the derivative of cumulative infiltration\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "dt_seconds = np.diff(time_days, prepend=time_days[0]) * 86400\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "dt_seconds[dt_seconds == 0] = 1  # Avoid division by zero\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "effective_infiltration_m3s = np.gradient(cum_infiltrated_m3) / dt_seconds\n"
                fixed_lines.append(new_line)
                new_line = ' ' * indent + "effective_infiltration_m3s = np.maximum(0, effective_infiltration_m3s)\n"
                fixed_lines.append(new_line)
                changes_made.append((i+1, "Fixed effective infiltration rate calculation"))
                continue
        
        fixed_lines.append(line)
    
    if changes_made:
        print(f"\nMaking {len(changes_made)} fixes:")
        for line_num, desc in changes_made:
            print(f"  Line {line_num}: {desc}")
        
        # Write the fixed file
        with open(engine_file, 'w') as f:
            f.writelines(fixed_lines)
        
        print("\n✅ Engine file updated successfully")
    else:
        print("No changes needed - checking current implementation...")
        
        # Show current implementation
        for i, line in enumerate(lines):
            if 'cum_infiltrated_m3' in line or 'effective_infiltration_m3s' in line:
                print(f"Line {i+1}: {line.rstrip()}")

if __name__ == "__main__":
    fix_engine()