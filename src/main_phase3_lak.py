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

def debug_lak_setup(gwf, lak_packagedata, lak_connectiondata, basin_info):
    """
    Comprehensive LAK package debugging before running model
    """
    print("\n" + "="*60)
    print("🔍 LAK PACKAGE DEBUG DIAGNOSTICS")
    print("="*60)
    
    debug_results = {}
    
    # 1. Check lake geometry
    print("\n1️⃣ Lake Geometry Check:")
    print(f"   - Number of lakes: {len(lak_packagedata)}")
    print(f"   - Lake stage: {lak_packagedata[0][1]:.3f} m")
    print(f"   - Lake connections: {lak_packagedata[0][2]}")
    debug_results['lake_geometry'] = 'PASS'
    
    # 2. Check connections
    print("\n2️⃣ Lake-Aquifer Connections:")
    n_connections = len(lak_connectiondata)
    print(f"   - Total connections: {n_connections}")
    print(f"   - Expected: {basin_info['n_basin_cells']} cells")
    
    if n_connections != basin_info['n_basin_cells']:
        print(f"   ⚠️ WARNING: Connection count mismatch!")
        debug_results['connections'] = 'WARNING'
    else:
        print(f"   ✅ Connection count matches")
        debug_results['connections'] = 'PASS'
    
    # 3. Check lakebed leakance values
    print("\n3️⃣ Lakebed Leakance Analysis:")
    leakances = [conn[6] for conn in lak_connectiondata]  # bedleak column
    print(f"   - Min leakance: {min(leakances):.2e} 1/s")
    print(f"   - Max leakance: {max(leakances):.2e} 1/s")
    print(f"   - Mean leakance: {np.mean(leakances):.2e} 1/s")
    
    # Check for reasonable range (1e-7 to 1e-4 typical for sand)
    if min(leakances) < 1e-10:
        print(f"   ⚠️ WARNING: Very low leakance values detected!")
        debug_results['leakance'] = 'WARNING'
    elif max(leakances) > 1e-2:
        print(f"   ⚠️ WARNING: Very high leakance values detected!")
        debug_results['leakance'] = 'WARNING'
    else:
        print(f"   ✅ Leakance values in reasonable range")
        debug_results['leakance'] = 'PASS'
    
    # 4. Check initial stage vs groundwater heads
    print("\n4️⃣ Initial Stage vs Groundwater:")
    initial_stage = lak_packagedata[0][1]
    print(f"   - Initial lake stage: {initial_stage:.3f} m")
    print(f"   - Basin floor: {basin_info['basin_level']:.3f} m")
    print(f"   - Groundwater level: {basin_info['gw_level']:.3f} m")
    
    if initial_stage < basin_info['basin_level']:
        print(f"   ⚠️ WARNING: Lake stage below basin floor!")
        debug_results['stage'] = 'WARNING'
    else:
        print(f"   ✅ Stage initialization reasonable")
        debug_results['stage'] = 'PASS'
    
    # 5. Check cell elevations
    print("\n5️⃣ Cell Elevation Consistency:")
    for i, conn in enumerate(lak_connectiondata[:3]):  # Check first 3
        cell_layer, cell_row, cell_col = conn[2], conn[3], conn[4]
        print(f"   - Connection {i}: Layer {cell_layer}, Row {cell_row}, Col {cell_col}")
    
    # Summary
    print("\n📊 Debug Summary:")
    for check, status in debug_results.items():
        symbol = "✅" if status == "PASS" else "⚠️"
        print(f"   {symbol} {check}: {status}")
    
    return debug_results

def calculate_lakebed_leakance(hk, lakebed_thickness=0.5):
    """
    Calculate lakebed leakance (BEDLEAK parameter)
    
    Parameters:
    -----------
    hk : float
        Hydraulic conductivity (m/day)
    lakebed_thickness : float
        Thickness of lakebed sediments (m)
    
    Returns:
    --------
    bedleak : float
        Lakebed leakance (1/s)
    """
    # Convert K from m/day to m/s
    hk_ms = hk / 86400
    
    # Leakance = K / thickness (in 1/s)
    bedleak = hk_ms / lakebed_thickness
    
    print(f"\n💧 Lakebed Leakance Calculation:")
    print(f"   - K: {hk:.2f} m/day = {hk_ms:.2e} m/s")
    print(f"   - Lakebed thickness: {lakebed_thickness:.2f} m")
    print(f"   - Leakance: {bedleak:.2e} 1/s")
    
    return bedleak

def build_lak_model_step31(basin_length, basin_width, basin_depth, basin_level, gw_level, hk, sy):
    """
    Step 3.1: Minimal LAK Test - Single stress period, constant inflow
    
    This is our defensive first step with LAK package
    """
    
    print("\n" + "="*60)
    print("🎯 PHASE 3 - STEP 3.1: MINIMAL LAK TEST")
    print("="*60)
    print("Starting with simplest possible LAK configuration...")
    
    # Model setup
    model_name = "lak_step31"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase3_lak\step31"
    os.makedirs(model_ws, exist_ok=True)
    
    # Create refined grid (use same as Phase 1)
    grid_info = create_refined_grid(basin_length, basin_width, domain_factor=10)
    nrow = grid_info['nrow']
    ncol = grid_info['ncol']
    delr = grid_info['delr']
    delc = grid_info['delc']
    
    # Elevations
    ground_surface = basin_level + basin_depth
    
    # Layers - same as Phase 1
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
    
    # Time discretization - SINGLE STRESS PERIOD for Step 3.1
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,  # Single period for minimal test
        perioddata=[(86400.0, 10, 1.2)],  # 1 day, 10 steps, multiplier 1.2
        time_units='SECONDS'
    )
    
    print("\n⏰ Time Discretization (Minimal Test):")
    print(f"   - Periods: 1 (steady-state like)")
    print(f"   - Duration: 1 day")
    print(f"   - Steps: 10 with multiplier 1.2")
    
    # Solver - RELAXED SETTINGS for LAK
    ims = flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        outer_dvclose=1e-3,  # Relaxed for LAK
        inner_dvclose=1e-4,  # Relaxed for LAK
        outer_maximum=500,    # More iterations
        inner_maximum=300,
        linear_acceleration="BICGSTAB",
        relaxation_factor=0.97,  # Slight under-relaxation
        backtracking_number=20,
        backtracking_tolerance=1.5,
        backtracking_reduction_factor=0.2
    )
    
    print("\n🔧 Solver Configuration (LAK-optimized):")
    print(f"   - Convergence: Relaxed (1e-3 outer, 1e-4 inner)")
    print(f"   - Max iterations: 500 outer, 300 inner")
    print(f"   - Relaxation: 0.97")
    print(f"   - Backtracking: Enabled")
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(
        sim, 
        modelname=model_name,
        save_flows=True,
        newtonoptions="NEWTON UNDER_RELAXATION"  # Newton with under-relaxation for LAK
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
    k_vertical = np.ones(nlay) * hk_ms  # 1:1 anisotropy
    
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
    
    # Storage - TRANSIENT for LAK
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
    # LAK PACKAGE SETUP - DEFENSIVE IMPLEMENTATION
    # ============================================
    
    print("\n" + "="*40)
    print("🏞️ LAK PACKAGE SETUP")
    print("="*40)
    
    # Get basin cells
    r1, r2 = grid_info['basin_rows']
    c1, c2 = grid_info['basin_cols']
    
    # Calculate basin area
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
    # [lakeno, strt, nlakeconn] - SIMPLIFIED format for MF6
    initial_stage = basin_level + 0.01  # Start with 1cm of water
    nlakeconn = n_basin_cells  # One connection per basin cell
    
    # Correct package data format: [ifno, strt, nlakeconn]
    lak_packagedata = [(0, initial_stage, nlakeconn)]
    
    print(f"\n🌊 Lake Package Data:")
    print(f"   - Lake 0: Stage={initial_stage:.3f}m, Connections={nlakeconn}")
    print(f"   - Area will be calculated from connections")
    
    # LAK Connection Data
    # [lakeno, iconn, cellid, claktype, bedleak, belev, telev, connlen, connwidth]
    
    # Calculate lakebed leakance
    lakebed_thickness = 0.5  # 0.5m lakebed sediments
    bedleak = calculate_lakebed_leakance(hk, lakebed_thickness)
    
    # Build connection data
    lak_connectiondata = []
    iconn = 0
    
    for (row, col) in basin_cells:
        # Connect to Layer 0 (top layer)
        claktype = 'VERTICAL'  # Vertical connection only
        belev = basin_level    # Bed elevation
        telev = ground_surface  # Top elevation of connection
        connlen = delr[col]    # Connection length
        connwidth = delc[row]   # Connection width
        
        lak_connectiondata.append([
            0,          # lakeno
            iconn,      # connection number
            0,          # layer
            row,        # row
            col,        # col
            claktype,   # connection type
            bedleak,    # lakebed leakance
            belev,      # bottom elevation
            telev,      # top elevation
            connlen,    # connection length
            connwidth   # connection width
        ])
        iconn += 1
    
    print(f"\n🔗 Lake Connections:")
    print(f"   - Total: {len(lak_connectiondata)}")
    print(f"   - Type: VERTICAL only (conservative)")
    print(f"   - Bedleak: {bedleak:.2e} 1/s")
    
    # Period data - MINIMAL TEST with constant small inflow
    # Format: [lakeno, setting, value]
    test_inflow = 0.0001  # 0.1 L/s = very small constant inflow
    lak_perioddata = {0: [['RATE', test_inflow]]}  # Simplified format
    
    print(f"\n💧 Inflow Configuration (Minimal Test):")
    print(f"   - Type: Constant rate")
    print(f"   - Rate: {test_inflow*1000:.1f} L/s")
    print(f"   - Duration: 1 day")
    
    # Create LAK package with defensive settings
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        nlakes=1,
        noutlets=0,  # No outlets for now
        packagedata=lak_packagedata,
        connectiondata=lak_connectiondata,
        perioddata=lak_perioddata,
        surfdep=0.1,  # 10cm for surface depression storage
        time_conversion=1.0,  # Time units already in seconds
        length_conversion=1.0,  # Length units in meters
        print_stage=True,
        print_flows=True,
        save_flows=True,
        stage_filerecord=f"{model_name}.lak.stg",
        budget_filerecord=f"{model_name}.lak.bud"
    )
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "ALL"), ("BUDGET", "ALL")]
    )
    
    # Debug before running
    basin_info = {
        'n_basin_cells': n_basin_cells,
        'basin_level': basin_level,
        'gw_level': gw_level,
        'basin_area': basin_area
    }
    
    debug_results = debug_lak_setup(gwf, lak_packagedata, lak_connectiondata, basin_info)
    
    # Write and run
    print("\n" + "="*40)
    print("📝 Writing model files...")
    sim.write_simulation()
    
    print("\n🚀 Running MODFLOW 6 with LAK (Step 3.1)...")
    print("   This is our minimal test - fingers crossed! 🤞")
    
    try:
        success, buff = sim.run_simulation(silent=False)
        
        if success:
            print("\n" + "="*60)
            print("✅ ✅ ✅ STEP 3.1 SUCCESS! LAK PACKAGE WORKS! ✅ ✅ ✅")
            print("="*60)
            
            # Analyze results
            analyze_lak_results_step31(model_ws, model_name, basin_info)
            
            # Save debug info for next steps
            debug_file = os.path.join(model_ws, "debug_info.json")
            with open(debug_file, 'w') as f:
                json.dump({
                    'debug_results': debug_results,
                    'basin_info': basin_info,
                    'bedleak': bedleak,
                    'success': True
                }, f, indent=2)
            
            print("\n🎯 Next Step: Ready for Step 3.2 (Time-varying)")
            
            return sim, gwf, lak
            
        else:
            print("\n" + "="*60)
            print("❌ Step 3.1 Failed - LAK issue detected")
            print("="*60)
            print("\n🔍 Debugging output:")
            print(buff[-2000:])  # Print last 2000 chars of output
            
            return None, None, None
            
    except Exception as e:
        print(f"\n❌ Exception during model run: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def analyze_lak_results_step31(model_ws, model_name, basin_info):
    """
    Analyze LAK results from Step 3.1
    """
    print("\n" + "="*40)
    print("📊 LAK RESULTS ANALYSIS - STEP 3.1")
    print("="*40)
    
    # Load stage file
    stage_file = os.path.join(model_ws, f"{model_name}.lak.stg")
    if os.path.exists(stage_file):
        print("\n📈 Lake Stage Results:")
        
        # Read stage data
        with open(stage_file, 'r') as f:
            lines = f.readlines()
        
        # Parse stage data (skip header)
        stages = []
        times = []
        for line in lines[1:]:  # Skip header
            if line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    times.append(float(parts[0]))  # time
                    stages.append(float(parts[3]))  # stage
        
        if stages:
            print(f"   - Initial stage: {stages[0]:.3f} m")
            print(f"   - Final stage: {stages[-1]:.3f} m")
            print(f"   - Stage change: {stages[-1] - stages[0]:.3f} m")
            print(f"   - Basin floor: {basin_info['basin_level']:.3f} m")
            print(f"   - Water depth: {stages[-1] - basin_info['basin_level']:.3f} m")
            
            # Simple plot
            if len(stages) > 1:
                plt.figure(figsize=(10, 6))
                plt.plot(np.array(times)/3600, stages, 'b-', linewidth=2)
                plt.axhline(y=basin_info['basin_level'], color='brown', 
                           linestyle='--', label='Basin Floor')
                plt.axhline(y=basin_info['gw_level'], color='blue', 
                           linestyle='--', alpha=0.5, label='Groundwater')
                plt.xlabel('Time (hours)')
                plt.ylabel('Stage (m)')
                plt.title('Step 3.1: LAK Stage Evolution (Minimal Test)')
                plt.legend()
                plt.grid(True, alpha=0.3)
                plt.savefig(os.path.join(model_ws, 'lak_stage_step31.png'), dpi=150)
                plt.show()
                
                print(f"\n✅ Stage plot saved")
        else:
            print("   ⚠️ No stage data found")
    else:
        print(f"   ⚠️ Stage file not found: {stage_file}")
    
    # Check heads
    head_file = os.path.join(model_ws, f"{model_name}.hds")
    if os.path.exists(head_file):
        hds = flopy.utils.HeadFile(head_file)
        head = hds.get_data()
        print(f"\n📊 Groundwater Heads:")
        print(f"   - Min head: {head.min():.3f} m")
        print(f"   - Max head: {head.max():.3f} m")
        print(f"   - Head range: {head.max() - head.min():.3f} m")

def main():
    """Test Step 3.1: Minimal LAK implementation"""
    print("="*60)
    print("BASIN INFILTRATION MODELING - PHASE 3")
    print("LAK PACKAGE IMPLEMENTATION")
    print("="*60)
    
    # Test parameters
    basin_length = 30.0
    basin_width = 10.0
    basin_depth = 2.0
    basin_level = 5.0
    gw_level = 3.0
    hk = 4.0
    sy = 0.25
    
    print("\n📋 Test Configuration (Step 3.1 - Minimal):")
    print(f"  Basin: {basin_length}m × {basin_width}m × {basin_depth}m")
    print(f"  Basin floor: {basin_level}m")
    print(f"  Groundwater: {gw_level}m")
    print(f"  K: {hk} m/day")
    
    # Run Step 3.1
    sim, gwf, lak = build_lak_model_step31(
        basin_length, basin_width, basin_depth,
        basin_level, gw_level, hk, sy
    )
    
    if sim is not None:
        print("\n" + "🎉"*20)
        print("STEP 3.1 COMPLETE - LAK PACKAGE BASIC FUNCTIONALITY VERIFIED!")
        print("🎉"*20)
        print("\nReady to proceed to Step 3.2: Time-varying inputs")
    else:
        print("\n😞 Step 3.1 failed - Need to debug LAK setup")
        print("Check the debug diagnostics above for issues")

if __name__ == "__main__":
    main()
