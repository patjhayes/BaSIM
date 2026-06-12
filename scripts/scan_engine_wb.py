"""
Scan engine for water balance calculation
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def scan_engine():
    """Find exact water balance calculation in engine"""
    
    engine_file = ROOT / "src" / "main_phase3_step32_time_varying.py"
    
    with open(engine_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    print("=== WATER BALANCE CALCULATION IN ENGINE ===\n")
    
    # Find lines with cumulative infiltration
    for i, line in enumerate(lines, 1):
        if 'cum_infiltrated' in line or 'cum_infil' in line:
            print(f"Line {i}: {line.rstrip()}")
            # Show context
            start = max(0, i-3)
            end = min(len(lines), i+3)
            for j in range(start, end):
                if j != i-1:
                    print(f"  {j+1}: {lines[j].rstrip()}")
            print()
    
    # Find DataFrame creation
    print("\n=== DATAFRAME CREATION ===\n")
    for i, line in enumerate(lines, 1):
        if 'DataFrame' in line and 'water_balance' in line.lower():
            print(f"Line {i}: {line.rstrip()}")
            # Show the dictionary being passed
            j = i
            while j < min(i+20, len(lines)):
                print(f"  {j}: {lines[j-1].rstrip()}")
                if '})' in lines[j-1]:
                    break
                j += 1
            print()
            break
    
    # Find effective infiltration calculation
    print("\n=== EFFECTIVE INFILTRATION RATE ===\n")
    for i, line in enumerate(lines, 1):
        if 'effective_infiltration' in line and '=' in line:
            print(f"Line {i}: {line.rstrip()}")
            # Show context
            for j in range(max(0, i-2), min(len(lines), i+3)):
                if j != i-1:
                    print(f"  {j+1}: {lines[j].rstrip()}")
            print()
            break

if __name__ == "__main__":
    scan_engine()