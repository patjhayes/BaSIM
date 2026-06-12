import sys
with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'bedleak_day = (float(lakebed_k) / float(lakebed_thickness)) * 86400.0' in line:
        new_lines.extend([
            '        if str(infiltration_mode).lower() == "full":\n',
            '            bedleak_day = 0.0\n',
            '        else:\n',
            '            bedleak_day = (float(lakebed_k) / float(lakebed_thickness)) * 86400.0\n'
        ])
    else:
        new_lines.append(line)

with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Updated bedleak_day logic.')
