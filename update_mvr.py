import sys
import re

with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Update create_mvr_package definition
old_def = '''def create_mvr_package(
    basin_cells,
    stress_periods,
    model_dir,
    model_name,
    delr,
    delc,
    lak_pname="basin_lak",
    uzf_pname="basin_uzf",
):'''
new_def = '''def create_mvr_package(
    basin_cells,
    stress_periods,
    model_dir,
    model_name,
    delr,
    delc,
    vks=50.0,
    lak_pname="basin_lak",
    uzf_pname="basin_uzf",
):'''
text = text.replace(old_def, new_def)

# Update the forward MVR loop to use RATE
old_forward = '''            # Forward: LAK -> UZF
            for idx in range(len(basin_cells)):
                uzf_id = idx + 1
                f.write(f"  {lak_pname}  1  {uzf_pname}  {uzf_id}  FACTOR  {fractions[idx]:.8f}\\n")'''

new_forward = '''            # Forward: LAK -> UZF
            for idx in range(len(basin_cells)):
                uzf_id = idx + 1
                cell_rate = areas[idx] * vks
                f.write(f"  {lak_pname}  1  {uzf_pname}  {uzf_id}  RATE  {cell_rate:.8f}\\n")'''
text = text.replace(old_forward, new_forward)

# Update the call in run_phase3_step32_model
old_call1 = '''        mvr_file = create_mvr_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            delr,
            delc,
        )'''
new_call1 = '''        mvr_file = create_mvr_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            delr,
            delc,
            vks=k_vertical,
        )'''
text = text.replace(old_call1, new_call1)

# Update the call in run_phase3_step32_with_config
old_call2 = '''        mvr_file = create_mvr_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            delr,
            delc,
        )'''
new_call2 = '''        mvr_file = create_mvr_package(
            basin_cells,
            stress_periods,
            str(MODEL_DIR),
            MODEL_NAME,
            delr,
            delc,
            vks=bed_k_mpd,
        )'''
text = text.replace(old_call2, new_call2)

with open(r'C:\Users\patri\OneDrive\BaSIM\src\main_phase3_step32_time_varying.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Updated MVR to use RATE with vks!')
