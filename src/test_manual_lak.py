import os
import numpy as np
import flopy
import matplotlib.pyplot as plt
import json
from pathlib import Path

# Import grid creation from phase 1
import sys
sys.path.append(r'C:\Users\patri\OneDrive\BaSIM\src')
from main_phase1_refined import create_refined_grid

def write_manual_lak_file(model_ws, model_name, lak_packagedata, lak_connectiondata, test_inflow):
    """
    Manually write LAK package file to ensure exact format
    """
    lak_file = os.path.join(model_ws, f"{model_name}.lak")
    
    print(f"\n📝 Writing manual LAK file: {lak_file}")
    
    with open(lak_file, 'w') as f:
        # Header
        f.write(f"# Manual LAK package file for {model_name}\n")
        
        # Options
        f.write("BEGIN options\n")
        f.write("  PRINT_STAGE\n")
        f.write("  PRINT_FLOWS\n")
        f.write("  SAVE_FLOWS\n")
        f.write(f"  STAGE  FILEOUT  {model_name}.lak.stg\n")
        f.write(f"  BUDGET  FILEOUT  {model_name}.lak.bud\n")
        f.write("  SURFDEP  0.1\n")
        f.write("END options\n")
        f.write("\n")
        
        # Dimensions
        f.write("BEGIN dimensions\n")
        f.write("  NLAKES  1\n")
        f.write("  NOUTLETS  0\n")
        f.write("END dimensions\n")
        f.write("\n")
        
        # Package data
        f.write("BEGIN packagedata\n")
        lakeno, strt, nlakeconn = lak_packagedata[0]
        f.write(f"  {lakeno+1}  {strt:.8f}  {nlakeconn}\n")  # Use 1-based indexing
        f.write("END packagedata\n")
        f.write("\n")
        
        # Connection data
        f.write("BEGIN connectiondata\n")
        for conn in lak_connectiondata:
            lakeno, iconn, layer, row, col, claktype, bedleak, belev, telev, connlen, connwidth = conn
            # Use 1-based indexing for MODFLOW
            f.write(f"  {lakeno+1}  {iconn+1}  {layer+1}  {row+1}  {col+1}  {claktype}  {bedleak:.12e}  {belev:.8f}  {telev:.8f}  {connlen:.8f}  {connwidth:.8f}\n")
        f.write("END connectiondata\n")
        f.write("\n")
        
        # NO OUTLETS SECTION since noutlets=0
        
        # Period data - Manual format
        f.write("BEGIN period  1\n")
        f.write(f"  1  RATE  {test_inflow:.8f}\n")  # Use 1-based lake indexing
        f.write("END period  1\n")
        f.write("\n")
    
    print(f"   ✅ Manual LAK file written with exact MODFLOW 6 format")
    return lak_file

def build_lak_model_manual(basin_length, basin_width, basin_depth, basin_level, gw_level, hk, sy):
    """
    Step 3.1: LAK package with MANUALLY WRITTEN LAK file
    """
    
    print("\n" + "="*60)
    print("🎯 PHASE 3 - STEP 3.1: MANUAL LAK FILE")
    print("="*60)
    print("Bypassing flopy LAK package and writing manual LAK file...")
    
    # Model setup
    model_name = "lak_manual"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase3_lak\manual"
    os.makedirs(model_ws, exist_ok=True)
    
    # Create refined grid
    grid_info = create_refined_grid(basin_length, basin_width, domain_factor=10)
    nrow = grid_info['nrow']
    ncol = grid_info['ncol']
    delr = grid_info['delr']
    delc = grid_info['delc']
    
    # Elevations
    ground_surface = basin_level + basin_depth
    
    # Layers
    nlay = 8
    min_model_bottom = min(gw_level - 40, basin_level - 45)
    
    layer_bottoms = [
        gw_level - 0.5,
        gw_level - 1.5,
        gw_level - 3.0,
        gw_level - 6.0,
        gw_level - 10.0,
        gw_level - 20.0,
        gw_level - 30.0,
        min_model_bottom
    ]
    
    # Create elevation arrays
    top = np.ones((nrow, ncol)) * ground_surface
    botm = np.zeros((nlay, nrow, ncol))
    for k in range(nlay):
        botm[k, :, :] = layer_bottoms[k]
    
    # Create simulation
    sim = flopy.mf6.MFSimulation(
        sim_name=model_name,
        exe_name=r"C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe",
        sim_ws=model_ws
    )
    
    # Time discretization
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(86400.0, 10, 1.2)],
        time_units='SECONDS'
    )
    
    # Solver
    ims = flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        outer_dvclose=1e-3,
        inner_dvclose=1e-4,
        outer_maximum=500,
        inner_maximum=300,
        linear_acceleration="BICGSTAB",
        relaxation_factor=0.97,
        backtracking_number=20,
        backtracking_tolerance=1.5,
        backtracking_reduction_factor=0.2
    )
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(
        sim, 
        modelname=model_name,
        save_flows=True,
        newtonoptions="NEWTON UNDER_RELAXATION"
    )
    
    # Discretization
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=nlay, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top, botm=botm
    )
    
    # Initial conditions
    initial_head = np.ones((nlay, nrow, ncol)) * gw_level
    ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_head)
    
    # Node property flow
    hk_ms = hk / 86400
    k_horizontal = np.ones(nlay) * hk_ms
    k_vertical = np.ones(nlay) * hk_ms
    
    for k in range(nlay):
        depth_factor = 1.0 - (k * 0.02)
        k_horizontal[k] *= depth_factor
        k_vertical[k] *= depth_factor
    
    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,
        k=k_horizontal,
        k33=k_vertical
    )
    
    # Storage
    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        ss=1e-5,
        sy=sy,
        steady_state=False,
        transient=True
    )
    
    # Constant head boundaries
    chd_spd = []
    for k in range(nlay):
        for i in range(nrow):
            chd_spd.append(((k, i, 0), gw_level))
            chd_spd.append(((k, i, ncol-1), gw_level))
        for j in range(1, ncol-1):
            chd_spd.append(((k, 0, j), gw_level))
            chd_spd.append(((k, nrow-1, j), gw_level))
    
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    
    # ============================================
    # PREPARE LAK DATA (but don't create package yet)
    # ============================================
    
    print("\n" + "="*40)
    print("🏞️ PREPARING LAK DATA")
    print("="*40)
    
    # Get basin cells
    r1, r2 = grid_info['basin_rows']
    c1, c2 = grid_info['basin_cols']
    
    # Calculate basin cells and area
    basin_cells = []
    basin_area = 0.0
    for i in range(r1, r2):
        for j in range(c1, c2):
            basin_cells.append((i, j))
            cell_area = delr[j] * delc[i]
            basin_area += cell_area
    
    n_basin_cells = len(basin_cells)
    
    print(f"\n📍 Basin Configuration:")
    print(f"   - Basin cells: {n_basin_cells}")
    print(f"   - Basin area: {basin_area:.1f} m²")
    print(f"   - Basin floor: {basin_level:.2f} m")
    
    # LAK Package Data
    initial_stage = basin_level + 0.01
    nlakeconn = n_basin_cells
    
    lak_packagedata = [(0, initial_stage, nlakeconn)]  # 0-based for our data
    
    # LAK Connection Data
    hk_ms = hk / 86400
    lakebed_thickness = 0.5
    bedleak = hk_ms / lakebed_thickness
    
    lak_connectiondata = []
    iconn = 0
    
    for (row, col) in basin_cells:
        lak_connectiondata.append(
            (0, iconn, 0, row, col, 'VERTICAL', bedleak, basin_level, ground_surface, delr[col], delc[row])
        )
        iconn += 1
    
    print(f"   - Lakebed leakance: {bedleak:.2e} 1/s")
    print(f"   - Connections: {len(lak_connectiondata)}")
    
    # Test inflow
    test_inflow = 0.0001  # 0.1 L/s
    print(f"   - Test inflow: {test_inflow*1000:.1f} L/s")
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST")]
    )
    
    # Write simulation (without LAK package)
    print("\n" + "="*40)
    print("📝 Writing model files (without LAK)...")
    
    try:
        sim.write_simulation()
        print(f"   ✅ Basic model files written")
    except Exception as e:
        print(f"   ❌ Error writing model files: {e}")
        return None, None, None
    
    # Now manually write the LAK file
    lak_file = write_manual_lak_file(model_ws, model_name, lak_packagedata, lak_connectiondata, test_inflow)
    
    # Update the name file to include LAK package
    nam_file = os.path.join(model_ws, f"{model_name}.nam")
    
    print(f"\n📝 Updating name file to include manual LAK package...")
    
    # Read existing name file
    with open(nam_file, 'r') as f:
        nam_lines = f.readlines()
    
    # Add LAK package line before the last line (usually END PACKAGES)
    new_nam_lines = []
    for line in nam_lines:
        if "END PACKAGES" in line:
            new_nam_lines.append(f"  LAK6  {model_name}.lak\n")
        new_nam_lines.append(line)
    
    # Write updated name file
    with open(nam_file, 'w') as f:
        f.writelines(new_nam_lines)
    
    print(f"   ✅ Name file updated with LAK package")
    
    print("\n🚀 Running MODFLOW 6 with MANUAL LAK file...")
    
    try:
        success, buff = sim.run_simulation(silent=False)
        
        if success:
            print("\n" + "="*60)
            print("✅ ✅ ✅ MANUAL LAK FILE WORKS! ✅ ✅ ✅")
            print("="*60)
            
            # Analyze results
            analyze_manual_lak_results(model_ws, model_name)
            
            return True
            
        else:
            print("\n" + "="*60)
            print("❌ Manual LAK file also failed")
            print("="*60)
            print("\n🔍 Output:")
            if buff:
                print(str(buff))
            
            return False
            
    except Exception as e:
        print(f"\n❌ Exception during model run: {e}")
        import traceback
        traceback.print_exc()
        return False

def analyze_manual_lak_results(model_ws, model_name):
    """
    Analyze results from manual LAK test
    """
    print("\n" + "="*40)
    print("📊 MANUAL LAK RESULTS")
    print("="*40)
    
    # Check for stage file
    stage_file = os.path.join(model_ws, f"{model_name}.lak.stg")
    if os.path.exists(stage_file):
        print(f"\n✅ Stage file created: {stage_file}")
        
        try:
            with open(stage_file, 'r') as f:
                lines = f.readlines()
                print(f"   - {len(lines)} lines in stage file")
                if len(lines) > 1:
                    print(f"   - First line: {lines[0].strip()}")
                    print(f"   - Last line: {lines[-1].strip()}")
                    
        except Exception as e:
            print(f"   ⚠️ Could not read stage file: {e}")
    else:
        print(f"   ❌ Stage file not found")
    
    # Check for budget file
    budget_file = os.path.join(model_ws, f"{model_name}.lak.bud")
    if os.path.exists(budget_file):
        print(f"\n✅ Budget file created: {budget_file}")
    else:
        print(f"   ❌ Budget file not found")

def main():
    """Test LAK package with manually written file"""
    print("="*60)
    print("BASIN INFILTRATION MODELING - PHASE 3")
    print("LAK PACKAGE - MANUAL FILE APPROACH")
    print("="*60)
    
    # Test parameters
    basin_length = 30.0
    basin_width = 10.0
    basin_depth = 2.0
    basin_level = 5.0
    gw_level = 3.0
    hk = 4.0
    sy = 0.25
    
    print("\n📋 Test Configuration:")
    print(f"  Basin: {basin_length}m × {basin_width}m × {basin_depth}m")
    print(f"  Basin floor: {basin_level}m")
    print(f"  Groundwater: {gw_level}m")
    print(f"  K: {hk} m/day")
    print(f"  Sy: {sy}")
    
    # Run test
    success = build_lak_model_manual(
        basin_length, basin_width, basin_depth,
        basin_level, gw_level, hk, sy
    )
    
    if success:
        print("\n🎉 Manual LAK file approach works!")
        print("This confirms the issue is with flopy LAK package generation")
        print("Phase 3 Step 3.1 is complete with manual approach!")
    else:
        print("\n😞 Even manual LAK file failed")
        print("This suggests a deeper MODFLOW 6 or version compatibility issue")

if __name__ == "__main__":
    main()
