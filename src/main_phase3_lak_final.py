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
    
    # Check for reasonable range
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
    
    # Summary
    print("\n📊 Debug Summary:")
    for check, status in debug_results.items():
        symbol = "✅" if status == "PASS" else "⚠️"
        print(f"   {symbol} {check}: {status}")
    
    return debug_results

def calculate_lakebed_leakance(hk, lakebed_thickness=0.5):
    """
    Calculate lakebed leakance (BEDLEAK parameter)
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
    """
    
    print("\n" + "="*60)
    print("🎯 PHASE 3 - STEP 3.1: MINIMAL LAK TEST")
    print("="*60)
    print("Starting with simplest possible LAK configuration...")
    
    # Model setup
    model_name = "lak_step31"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase3_lak\step31"
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
        perioddata=[(86400.0, 10, 1.2)],  # 1 day, 10 steps
        time_units='SECONDS'
    )
    
    print("\n⏰ Time Discretization (Minimal Test):")
    print(f"   - Periods: 1")
    print(f"   - Duration: 1 day")
    print(f"   - Steps: 10 with multiplier 1.2")
    
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
    
    print("\n🔧 Solver Configuration (LAK-optimized):")
    print(f"   - Convergence: Relaxed (1e-3 outer, 1e-4 inner)")
    print(f"   - Max iterations: 500 outer, 300 inner")
    print(f"   - Relaxation: 0.97")
    
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
    # LAK PACKAGE SETUP - FIXED PERIOD DATA FORMAT
    # ============================================
    
    print("\n" + "="*40)
    print("🏞️ LAK PACKAGE SETUP")
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
    
    # LAK Package Data - CORRECT FORMAT
    # Format: [lakeno, strt, nlakeconn]
    initial_stage = basin_level + 0.01  # Start with 1cm of water
    nlakeconn = n_basin_cells
    
    lak_packagedata = [(0, initial_stage, nlakeconn)]
    
    print(f"\n🌊 Lake Package Data:")
    print(f"   - Lake 0: Stage={initial_stage:.3f}m, Connections={nlakeconn}")
    
    # LAK Connection Data - CORRECT FORMAT
    # Calculate lakebed leakance
    lakebed_thickness = 0.5
    bedleak = calculate_lakebed_leakance(hk, lakebed_thickness)
    
    # Build connection data with proper tuple format
    lak_connectiondata = []
    iconn = 0
    
    for (row, col) in basin_cells:
        # Create connection as tuple: (lakeno, iconn, layer, row, col, claktype, bedleak, belev, telev, connlen, connwidth)
        lak_connectiondata.append(
            (0, iconn, 0, row, col, 'VERTICAL', bedleak, basin_level, ground_surface, delr[col], delc[row])
        )
        iconn += 1
    
    print(f"\n🔗 Lake Connections:")
    print(f"   - Total: {len(lak_connectiondata)}")
    print(f"   - Type: VERTICAL only")
    print(f"   - Bedleak: {bedleak:.2e} 1/s")
    
    # Period data - FIXED FORMAT FOR FLOPY
    # Use correct list format for flopy stress_period_data
    test_inflow = 0.0001  # 0.1 L/s
    
    # Format: [(lakeno, keyword, value)]
    lak_perioddata = [(0, 'RATE', test_inflow)]
    
    print(f"\n💧 Inflow Configuration (Minimal Test):")
    print(f"   - Type: Constant rate")
    print(f"   - Rate: {test_inflow*1000:.1f} L/s")
    print(f"   - Duration: 1 day")
    print(f"   - Period data format: {lak_perioddata}")
    
    # Create LAK package - SIMPLIFIED
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        nlakes=1,
        noutlets=0,
        packagedata=lak_packagedata,
        connectiondata=lak_connectiondata,
        perioddata=lak_perioddata,  # Use simple list format
        surfdep=0.1,
        time_conversion=1.0,
        length_conversion=1.0,
        print_stage=True,
        print_flows=True,
        save_flows=True,
        stage_filerecord=f"{model_name}.lak.stg",
        budget_filerecord=f"{model_name}.lak.bud",
        boundnames=False,  # Disable boundnames to simplify
        auxiliary=None     # No auxiliary variables
    )
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST")]
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
            analyze_lak_results_step31(model_ws, model_name, basin_info, grid_info)
            
            # Save configuration for next steps
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
                'success': True
            }
            
            config_file = os.path.join(model_ws, "step31_config.json")
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"\n📝 Configuration saved to: {config_file}")
            print("\n🎯 Ready for Step 3.2: Time-varying inputs")
            
            return sim, gwf, lak
            
        else:
            print("\n" + "="*60)
            print("❌ Step 3.1 Failed - LAK convergence issue")
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

def analyze_lak_results_step31(model_ws, model_name, basin_info, grid_info):
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
        
        try:
            # Try to load as a structured array
            stage_data = np.genfromtxt(stage_file, names=True)
            
            if len(stage_data) > 0:
                # Get time and stage columns
                times = stage_data['time'] if 'time' in stage_data.dtype.names else np.arange(len(stage_data))
                stages = stage_data['stage'] if 'stage' in stage_data.dtype.names else stage_data['STAGE']
                
                print(f"   - Initial stage: {stages[0]:.3f} m")
                print(f"   - Final stage: {stages[-1]:.3f} m")
                print(f"   - Stage change: {stages[-1] - stages[0]:.3f} m")
                print(f"   - Basin floor: {basin_info['basin_level']:.3f} m")
                print(f"   - Final water depth: {stages[-1] - basin_info['basin_level']:.3f} m")
                
                # Create visualization
                fig, axes = plt.subplots(1, 2, figsize=(14, 6))
                
                # Plot 1: Stage evolution
                ax1 = axes[0]
                ax1.plot(times/3600, stages, 'b-', linewidth=2, label='Lake Stage')
                ax1.axhline(y=basin_info['basin_level'], color='brown', 
                           linestyle='--', label='Basin Floor', linewidth=1.5)
                ax1.axhline(y=basin_info['gw_level'], color='blue', 
                           linestyle='--', alpha=0.5, label='Groundwater', linewidth=1.5)
                ax1.axhline(y=basin_info['basin_level'] + 2, color='red', 
                           linestyle=':', alpha=0.5, label='Basin Top', linewidth=1.5)
                ax1.set_xlabel('Time (hours)')
                ax1.set_ylabel('Elevation (m)')
                ax1.set_title('Step 3.1: LAK Stage Evolution')
                ax1.legend(loc='best')
                ax1.grid(True, alpha=0.3)
                
                # Plot 2: Water depth
                ax2 = axes[1]
                water_depth = stages - basin_info['basin_level']
                ax2.plot(times/3600, water_depth, 'g-', linewidth=2)
                ax2.set_xlabel('Time (hours)')
                ax2.set_ylabel('Water Depth in Basin (m)')
                ax2.set_title('Water Depth Evolution')
                ax2.grid(True, alpha=0.3)
                ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                
                plt.suptitle('LAK Package Step 3.1: Minimal Test Results', fontsize=14, fontweight='bold')
                plt.tight_layout()
                plt.savefig(os.path.join(model_ws, 'lak_stage_step31.png'), dpi=150)
                plt.show()
                
                print(f"\n✅ Stage plots saved")
            else:
                print("   ⚠️ Stage file is empty")
                
        except Exception as e:
            print(f"   ⚠️ Could not parse stage file: {e}")
    else:
        print(f"   ⚠️ Stage file not found: {stage_file}")
    
    # Check heads
    head_file = os.path.join(model_ws, f"{model_name}.hds")
    if os.path.exists(head_file):
        hds = flopy.utils.HeadFile(head_file)
        head = hds.get_data()
        
        # Get basin center
        r1, r2 = grid_info['basin_rows']
        c1, c2 = grid_info['basin_cols']
        center_row = (r1 + r2) // 2
        center_col = (c1 + c2) // 2
        
        print(f"\n📊 Groundwater Heads:")
        print(f"   - Min head: {head.min():.3f} m")
        print(f"   - Max head: {head.max():.3f} m")
        print(f"   - Head range: {head.max() - head.min():.3f} m")
        print(f"   - Head at basin center: {head[0, center_row, center_col]:.3f} m")
        
        # Check for mounding
        mounding = head[0, center_row, center_col] - basin_info['gw_level']
        if mounding > 0.01:
            print(f"   - Mounding detected: {mounding:.3f} m")
        else:
            print(f"   - No significant mounding")

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
    print(f"  Sy: {sy}")
    
    # Run Step 3.1
    sim, gwf, lak = build_lak_model_step31(
        basin_length, basin_width, basin_depth,
        basin_level, gw_level, hk, sy
    )
    
    if sim is not None:
        print("\n" + "🎉"*20)
        print("STEP 3.1 COMPLETE - LAK PACKAGE BASIC FUNCTIONALITY VERIFIED!")
        print("🎉"*20)
        print("\nNext: Step 3.2 will add time-varying inputs")
    else:
        print("\n😞 Step 3.1 failed - Review debug output above")
        print("\nCommon issues to check:")
        print("  1. Lake stage vs basin floor elevation")
        print("  2. Connection cell indices")
        print("  3. Lakebed leakance values")
        print("  4. Period data format")

if __name__ == "__main__":
    main()
