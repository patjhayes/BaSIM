with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Insert the missing LAK completion print statements after line 148 (index 148)
new_lines = [
    '\n',
    '    print(f"   ✅ LAK file created: {os.path.basename(lak_file)}")\n',
    '    print(f"   🌊 Lake connections: {len(basin_cells)}")\n',
    '    print(f"   ⏰ Stress periods: {len(stress_periods)}")\n'
]

# Insert after line 148 
for i, new_line in enumerate(new_lines):
    lines.insert(149 + i, new_line)

with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Added missing LAK completion statements')
