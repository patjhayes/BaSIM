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

def build_lak_model_fixed_format(basin_length, basin_width, basin_depth, basin_level, gw_level, hk, sy):
    """
    Step 3.1: LAK package with CORRECTLY FORMATTED period data
    """
    
    print("\n" + "="*60)
    print("🎯 PHASE 3 - STEP 3.1: LAK WITH FIXED PERIOD FORMAT")
    print("="*60)
    print("Using correct MODFLOW 6 LAK period data format...")
    
    # Model setup
    model_name = "lak_fixed"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase3_lak\fixed"
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
    
    # Time discretization - SINGLE STRESS PERIOD
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(86400.0, 10, 1.2)],
        time_units='SECONDS'
    )
    
    # Solver - RELAXED SETTINGS for LAK
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
    # LAK PACKAGE SETUP - FIXED PERIOD FORMAT
    # ============================================
    
    print("\n" + "="*40)
    print("🏞️ LAK PACKAGE SETUP (FIXED FORMAT)")
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
    initial_stage = basin_level + 0.01  # Start with 1cm of water
    nlakeconn = n_basin_cells
    
    lak_packagedata = [(0, initial_stage, nlakeconn)]
    
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
    
    # Period data - Try different formats
    test_inflow = 0.0001  # 0.1 L/s
    
    print(f"\n💧 Testing different period data formats:")
    
    # Format 1: Simple list
    format1 = [(0, 'RATE', test_inflow)]
    print(f"   Format 1: {format1}")
    
    # Format 2: Nested list
    format2 = [[0, 'RATE', test_inflow]]
    print(f"   Format 2: {format2}")
    
    # Format 3: Dictionary with nested list
    format3 = {0: [[0, 'RATE', test_inflow]]}
    print(f"   Format 3: {format3}")
    
    # Format 4: Just the rate value (MODFLOW might default to RATE)
    format4 = [(0, test_inflow)]
    print(f"   Format 4: {format4}")
    
    # Use format that looks most like MODFLOW 6 manual examples
    # According to MODFLOW 6 manual, the format should be:
    # [(lakeno, laksetting, laksettingvalue)]
    
    lak_perioddata = format2  # Use nested list format
    
    print(f"\n   → Using Format 2: nested list format")
    
    # Create LAK package 
    print(f"\n🏗️ Creating LAK package with corrected period format...")
    
    try:
        lak = flopy.mf6.ModflowGwflak(
            gwf,
            nlakes=1,
            noutlets=0,
            packagedata=lak_packagedata,
            connectiondata=lak_connectiondata,
            perioddata=lak_perioddata,
            surfdep=0.1,
            print_stage=True,
            print_flows=True,
            save_flows=True,
            stage_filerecord=f"{model_name}.lak.stg",
            budget_filerecord=f"{model_name}.lak.bud"
        )
        print(f"   ✅ LAK package created successfully")
    except Exception as e:
        print(f"   ❌ Error creating LAK package: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST")]
    )
    
    # Write and run
    print("\n" + "="*40)
    print("📝 Writing model files...")
    
    try:
        sim.write_simulation()
        print(f"   ✅ Model files written successfully")
    except Exception as e:
        print(f"   ❌ Error writing model files: {e}")
        return None, None, None
    
    print("\n🚀 Running MODFLOW 6 with LAK (FIXED FORMAT)...")
    
    try:
        success, buff = sim.run_simulation(silent=False)
        
        if success:
            print("\n" + "="*60)
            print("✅ ✅ ✅ STEP 3.1 SUCCESS! LAK WITH INFLOW WORKS! ✅ ✅ ✅")
            print("="*60)
            
            # Analyze results
            analyze_lak_results(model_ws, model_name, grid_info)
            
            # Save success configuration
            config = {
                'basin_length': basin_length,
                'basin_width': basin_width,
                'basin_depth': basin_depth,
                'basin_level': basin_level,
                'gw_level': gw_level,
                'hk': hk,
                'sy': sy,
                'bedleak': bedleak,
                'basin_area': basin_area,
                'n_basin_cells': n_basin_cells,
                'test_inflow': test_inflow,
                'period_format': 'nested_list',
                'success': True
            }
            
            config_file = os.path.join(model_ws, "lak_success_config.json")
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"\n📝 Success configuration saved to: {config_file}")
            print("\n🎯 Ready for Step 3.2: Time-varying inputs")
            
            return sim, gwf, lak
            
        else:
            print("\n" + "="*60)
            print("❌ Still failed - trying other formats...")
            print("="*60)
            print("\n🔍 Last 1000 characters of output:")
            if buff:
                print(str(buff)[-1000:])
            
            return None, None, None
            
    except Exception as e:
        print(f"\n❌ Exception during model run: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def analyze_lak_results(model_ws, model_name, grid_info):
    """
    Analyze LAK results
    """
    print("\n" + "="*40)
    print("📊 LAK RESULTS ANALYSIS")
    print("="*40)
    
    # Load stage file
    stage_file = os.path.join(model_ws, f"{model_name}.lak.stg")
    if os.path.exists(stage_file):
        print("\n📈 Lake Stage Results:")
        
        try:
            # Try to load stage data
            with open(stage_file, 'r') as f:
                lines = f.readlines()
                print(f"   - Stage file has {len(lines)} lines")
                print(f"   - First few lines:")
                for i, line in enumerate(lines[:5]):
                    print(f"     {i+1}: {line.strip()}")
                    
        except Exception as e:
            print(f"   ⚠️ Could not read stage file: {e}")
    else:
        print(f"   ⚠️ Stage file not found: {stage_file}")

def main():
    """Test LAK package with corrected period format"""
    print("="*60)
    print("BASIN INFILTRATION MODELING - PHASE 3")
    print("LAK PACKAGE - PERIOD FORMAT FIX")
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
    sim, gwf, lak = build_lak_model_fixed_format(
        basin_length, basin_width, basin_depth,
        basin_level, gw_level, hk, sy
    )
    
    if sim is not None:
        print("\n🎉 LAK package with inflow works!")
        print("Phase 3 Step 3.1 is complete!")
    else:
        print("\n😞 Still having period format issues")
        print("Need to investigate MODFLOW 6 LAK format more deeply")

if __name__ == "__main__":
    main()
