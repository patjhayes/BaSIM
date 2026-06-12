import os
import numpy as np
import flopy
import matplotlib.pyplot as plt

# Import Phase 1 functions
from main_phase1_refined import create_refined_grid

def select_ts1_file():
    """Select a TS1 file from numbered list"""
    ts1_dir = r"C:\Users\patri\OneDrive\BaSIM\External\OUTPUT"
    
    if not os.path.exists(ts1_dir):
        print(f"❌ TS1 directory not found: {ts1_dir}")
        return None
    
    # Get all .ts1 files
    ts1_files = [f for f in os.listdir(ts1_dir) if f.endswith('.ts1')]
    
    if not ts1_files:
        print(f"❌ No TS1 files found in {ts1_dir}")
        return None
    
    print(f"\n📁 Available TS1 files ({len(ts1_files)} found):")
    for i, filename in enumerate(ts1_files, 1):
        print(f"  {i}. {filename}")
    
    while True:
        try:
            selection = int(input(f"\nSelect TS1 file (1-{len(ts1_files)}): "))
            if 1 <= selection <= len(ts1_files):
                return os.path.join(ts1_dir, ts1_files[selection - 1])
            else:
                print(f"Please enter a number between 1 and {len(ts1_files)}")
        except ValueError:
            print("Please enter a valid number")

def parse_ts1_file(filepath):
    """Parse TS1 file - TS1 format with time in minutes, flow data"""
    try:
        times = []
        flows = []
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        print(f"📖 Parsing TS1 file: {os.path.basename(filepath)}")
        print(f"   File contains {len(lines)} lines")
        
        # Find the data start line
        data_started = False
        for i, line in enumerate(lines):
            line = line.strip()
            
            if not line:
                continue
                
            # Look for header line or start parsing data
            if 'Time' in line and ('min' in line.lower() or 'Min' in line):
                data_started = True
                print(f"   Header found at line {i+1}: {line}")
                continue
                
            # Try to parse data lines
            if line and any(char.isdigit() for char in line):
                if ',' in line:
                    parts = line.split(',')
                else:
                    parts = line.split()
                    
                if len(parts) >= 2:
                    try:
                        time_min = float(parts[0])
                        time_sec = time_min * 60  # Convert to seconds
                        flow = float(parts[1])
                        
                        times.append(time_sec)
                        flows.append(flow)
                    except ValueError:
                        continue
        
        if not times:
            raise ValueError("No valid data found in TS1 file")
        
        # Convert to numpy array and sort by time
        ts_data = np.column_stack((times, flows))
        ts_data = ts_data[ts_data[:, 0].argsort()]  # Sort by time
        
        print(f"✅ TS1 parsed successfully:")
        print(f"   Data points: {len(ts_data)}")
        print(f"   Duration: {ts_data[-1,0]/3600:.1f} hours")
        print(f"   Flow range: {ts_data[:,1].min():.4f} to {ts_data[:,1].max():.4f} m³/s")
        print(f"   Peak flow: {ts_data[:,1].max():.4f} m³/s at {ts_data[np.argmax(ts_data[:,1]),0]/60:.1f} min")
        
        return ts_data
        
    except Exception as e:
        print(f"❌ Error parsing TS1 file: {e}")
        return None

def create_time_discretization(ts1_data, max_time_steps=100):
    """Create time discretization based on TS1 data"""
    
    times = ts1_data[:, 0]  # Time in seconds
    flows = ts1_data[:, 1]
    total_duration = times[-1]
    
    print(f"\n⏰ Creating time discretization:")
    print(f"   Total duration: {total_duration/3600:.1f} hours")
    print(f"   Target max time steps: {max_time_steps}")
    
    # Create adaptive time stepping
    # Smaller steps during high flow periods, larger during low flow
    
    stress_periods = []
    current_time = 0
    
    # Calculate time step based on flow variation
    dt_base = total_duration / max_time_steps  # Base time step
    
    while current_time < total_duration:
        # Find current flow rate by interpolation
        current_flow = np.interp(current_time, times, flows)
        max_flow = flows.max()
        
        # Adaptive time step: smaller during high flow
        flow_factor = (current_flow / max_flow) if max_flow > 0 else 0
        dt_factor = 0.5 + 0.5 * (1 - flow_factor)  # 0.5 to 1.0 multiplier
        dt = dt_base * dt_factor
        
        # Don't exceed remaining time
        dt = min(dt, total_duration - current_time)
        
        # Minimum time step
        dt = max(dt, 60)  # At least 1 minute
        
        stress_periods.append((dt, 1, 1.0))  # (length, nstp, tsmult)
        current_time += dt
        
        if len(stress_periods) >= max_time_steps:
            break
    
    print(f"   Created {len(stress_periods)} stress periods")
    print(f"   Time step range: {min([sp[0] for sp in stress_periods])/60:.1f} to {max([sp[0] for sp in stress_periods])/60:.1f} minutes")
    
    return stress_periods

def interpolate_ts1_to_stress_periods(ts1_data, stress_periods):
    """Create stress period data from TS1 file"""
    
    times = ts1_data[:, 0]
    flows = ts1_data[:, 1]
    
    # Calculate stress period times
    sp_times = []
    current_time = 0
    for sp_length, _, _ in stress_periods:
        sp_times.append(current_time + sp_length/2)  # Mid-point of stress period
        current_time += sp_length
    
    # Interpolate flows to stress period times
    sp_flows = np.interp(sp_times, times, flows)
    
    print(f"📊 Stress period flows:")
    print(f"   Average: {sp_flows.mean():.4f} m³/s")
    print(f"   Peak: {sp_flows.max():.4f} m³/s")
    print(f"   Total volume: {np.sum(sp_flows * [sp[0] for sp in stress_periods]):.1f} m³")
    
    return sp_flows

def build_transient_model(basin_length, basin_width, basin_depth, basin_level, gw_level, hk, sy, ts1_filepath):
    """
    Phase 2: Transient model with TS1 inflow - FIXED basin cells
    """
    
    print("\n" + "="*70)
    print("PHASE 2: TRANSIENT MODEL WITH TS1 INFLOW - FIXED")
    print("="*70)
    
    # Parse TS1 file
    ts1_data = parse_ts1_file(ts1_filepath)
    if ts1_data is None:
        return None, None, None
    
    # Create time discretization
    stress_periods = create_time_discretization(ts1_data, max_time_steps=50)
    sp_flows = interpolate_ts1_to_stress_periods(ts1_data, stress_periods)
    
    # Model setup
    model_name = "basin_transient"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase2"
    os.makedirs(model_ws, exist_ok=True)
    
    # Use same grid as Phase 1 - FIXED to use domain_factor=10
    grid_info = create_refined_grid(basin_length, basin_width, domain_factor=10)
    nrow = grid_info['nrow']
    ncol = grid_info['ncol']
    delr = grid_info['delr']
    delc = grid_info['delc']
    
    # Calculate elevations
    ground_surface = basin_level + basin_depth
    clearance = basin_level - gw_level
    
    print(f"\n📏 Model Configuration:")
    print(f"  Grid: {nrow} × {ncol} = {nrow*ncol} cells")
    print(f"  Domain: {grid_info['domain_length']:.0f}m × {grid_info['domain_width']:.0f}m")
    print(f"  Basin: {basin_length}m × {basin_width}m × {basin_depth}m")
    print(f"  Elevations: Ground {ground_surface}m, Basin {basin_level}m, GW {gw_level}m")
    
    # Enhanced vertical discretization
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
    
    # Time discretization - transient
    nper = len(stress_periods)
    perioddata = stress_periods
    
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=nper,
        perioddata=perioddata
    )
    
    print(f"\n⏰ Time Discretization:")
    print(f"   Stress periods: {nper}")
    print(f"   Total simulation time: {sum([sp[0] for sp in stress_periods])/3600:.1f} hours")
    
    # Enhanced solver for transient
    ims = flopy.mf6.ModflowIms(
        sim, 
        complexity="MODERATE",
        outer_dvclose=1e-6,
        inner_dvclose=1e-7,
        outer_maximum=200,
        inner_maximum=500
    )
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(sim, modelname=model_name, save_flows=True)
    
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
    
    # Depth-dependent K reduction
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
    
    # Storage - important for transient
    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        ss=1e-5,
        sy=sy,
        steady_state=False,  # TRANSIENT
        transient=True
    )
    
    print(f"\n💧 Hydraulic Properties:")
    print(f"   K: {hk:.2f} m/day (isotropic)")
    print(f"   Specific yield: {sy}")
    print(f"   Storage: Transient (unconfined)")
    
    # Boundary conditions
    chd_spd = {}
    for per in range(nper):
        chd_list = []
        for k in range(nlay):
            for i in range(nrow):
                chd_list.append(((k, i, 0), gw_level))
                chd_list.append(((k, i, ncol-1), gw_level))
            for j in range(1, ncol-1):
                chd_list.append(((k, 0, j), gw_level))
                chd_list.append(((k, nrow-1, j), gw_level))
        chd_spd[per] = chd_list
    
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    
    # RECHARGE package for basin inflow (better approach than wells)
    r1, r2 = grid_info['basin_rows']
    c1, c2 = grid_info['basin_cols']
    
    print(f"\n🎯 Basin Cell Check:")
    print(f"  Basin rows: {r1} to {r2} (span: {r2-r1})")
    print(f"  Basin cols: {c1} to {c2} (span: {c2-c1})")
    print(f"  Grid size: {nrow} rows × {ncol} cols")
    
    # Calculate basin area and cells
    basin_cells = []
    basin_area = 0.0
    
    # Ensure we have valid basin bounds
    if r1 >= r2 or c1 >= c2:
        print(f"❌ ERROR: Invalid basin bounds!")
        print(f"   Basin rows: {r1} to {r2}")
        print(f"   Basin cols: {c1} to {c2}")
        return None, None, None
    
    for i in range(r1, r2):
        for j in range(c1, c2):
            if 0 <= i < nrow and 0 <= j < ncol:  # Safety check
                basin_cells.append((i, j))
                cell_area = delr[j] * delc[i]
                basin_area += cell_area
    
    n_basin_cells = len(basin_cells)
    
    print(f"\n💧 Recharge Setup:")
    print(f"  Basin cells found: {n_basin_cells}")
    print(f"  Basin area: {basin_area:.1f} m²")
    
    if n_basin_cells == 0:
        print("❌ ERROR: No basin cells found!")
        return None, None, None
    
    # Create time-varying recharge
    rch_spd = {}
    for iper in range(nper):
        # Convert flow rate to recharge rate
        flow_rate = sp_flows[iper]  # m³/s
        recharge_rate = flow_rate / basin_area if basin_area > 0 else 0  # m/s
        
        # Create recharge array
        rch_array = np.zeros((nrow, ncol))
        for i, j in basin_cells:
            rch_array[i, j] = recharge_rate
        
        rch_spd[iper] = rch_array
    
    rch = flopy.mf6.ModflowGwfrcha(gwf, recharge=rch_spd)
    
    print(f"  Peak recharge rate: {max(sp_flows)/basin_area*86400:.2f} mm/day")
    
    # Output control - save heads for all periods
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.bud",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")]
    )
    
    # Write and run
    print("\n🔧 Writing model files...")
    sim.write_simulation()
    
    print("🚀 Running MODFLOW 6 (transient)...")
    success, buff = sim.run_simulation()
    
    if success:
        print("✅ Transient model completed successfully!")
        
        # Load and analyze results
        head_file = os.path.join(model_ws, f"{model_name}.hds")
        
        if os.path.exists(head_file):
            print("\n📊 Analyzing transient results...")
            
            hds = flopy.utils.HeadFile(head_file)
            times_out = hds.get_times()
            
            # Get head data for key times
            head_initial = hds.get_data(totim=times_out[0])
            head_peak = hds.get_data(totim=times_out[len(times_out)//2])  # Mid-simulation
            head_final = hds.get_data(totim=times_out[-1])
            
            # Create visualization
            visualize_transient_results(head_initial, head_peak, head_final, ts1_data, sp_flows, 
                                      stress_periods, grid_info, ground_surface, basin_level, 
                                      gw_level, model_ws, times_out)
            
            # Check for basin spilling
            basin_spill_check(hds, times_out, grid_info, basin_level, basin_depth, gw_level)
            
            print(f"\n🎯 Transient Results Summary:")
            print(f"   Simulation time: {times_out[-1]/3600:.1f} hours")
            print(f"   Head change: {head_final.max() - head_initial.max():.3f} m")
            print(f"   Peak mounding: {head_peak.max() - gw_level:.3f} m")
            print(f"   Final head range: {head_final.min():.3f} to {head_final.max():.3f} m")
            print(f"   Basin overflow: {'⚠️ YES' if head_peak.max() > basin_level else '✅ NO'}")
        
        return sim, gwf, grid_info
    else:
        print("❌ Transient model failed")
        return None, None, None

def visualize_transient_results(head_initial, head_peak, head_final, ts1_data, sp_flows, 
                               stress_periods, grid_info, ground_surface, basin_level, 
                               gw_level, model_ws, times):
    """Create comprehensive transient visualization"""
    
    fig = plt.figure(figsize=(18, 12))
    
    # Plot 1: TS1 hydrograph
    ax1 = plt.subplot(3, 3, 1)
    ts_times_hours = ts1_data[:, 0] / 3600
    ax1.plot(ts_times_hours, ts1_data[:, 1], 'b-', linewidth=2, label='TS1 Data')
    
    # Plot stress period flows
    sp_times = []
    current_time = 0
    for sp_length, _, _ in stress_periods:
        sp_times.append(current_time + sp_length/2)
        current_time += sp_length
    sp_times_hours = np.array(sp_times) / 3600
    
    ax1.plot(sp_times_hours, sp_flows, 'ro-', markersize=4, label='Model Input')
    ax1.set_xlabel('Time (hours)')
    ax1.set_ylabel('Flow (m³/s)')
    ax1.set_title('Inflow Hydrograph')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Initial heads
    ax2 = plt.subplot(3, 3, 2)
    im2 = ax2.imshow(head_initial[0], aspect='auto', cmap='viridis')
    plt.colorbar(im2, ax=ax2, label="Head (m)", shrink=0.7)
    ax2.set_title("Initial Heads (t=0)")
    
    # Plot 3: Peak heads
    ax3 = plt.subplot(3, 3, 3)
    im3 = ax3.imshow(head_peak[0], aspect='auto', cmap='viridis')
    plt.colorbar(im3, ax=ax3, label="Head (m)", shrink=0.7)
    ax3.set_title("Peak Flow Period")
    
    # Plot 4: Final heads
    ax4 = plt.subplot(3, 3, 4)
    im4 = ax4.imshow(head_final[0], aspect='auto', cmap='viridis')
    plt.colorbar(im4, ax=ax4, label="Head (m)", shrink=0.7)
    ax4.set_title("Final Heads")
    
    # Mark basin on head plots
    r1, r2 = grid_info['basin_rows']
    c1, c2 = grid_info['basin_cols']
    for ax in [ax2, ax3, ax4]:
        rect = plt.Rectangle((c1-0.5, r1-0.5), c2-c1, r2-r1, 
                           fill=False, edgecolor='red', linewidth=2)
        ax.add_patch(rect)
    
    # Plot 5: Head differences (peak - initial)
    ax5 = plt.subplot(3, 3, 5)
    head_diff = head_peak[0] - head_initial[0]
    im5 = ax5.imshow(head_diff, aspect='auto', cmap='RdYlBu', vmin=-0.1, vmax=head_diff.max())
    plt.colorbar(im5, ax=ax5, label="Head change (m)", shrink=0.7)
    ax5.set_title("Mounding (Peak - Initial)")
    rect5 = plt.Rectangle((c1-0.5, r1-0.5), c2-c1, r2-r1, 
                         fill=False, edgecolor='black', linewidth=2)
    ax5.add_patch(rect5)
    
    # Plot 6: Time series at basin center
    ax6 = plt.subplot(3, 3, 6)
    center_row = (r1 + r2) // 2
    center_col = (c1 + c2) // 2
    
    # Extract heads at basin center through time
    heads_center = []
    for time in times:
        head_data = flopy.utils.HeadFile(os.path.join(model_ws, "basin_transient.hds")).get_data(totim=time)
        heads_center.append(head_data[0, center_row, center_col])
    
    times_hours = np.array(times) / 3600
    ax6.plot(times_hours, heads_center, 'b-', linewidth=2)
    ax6.axhline(y=gw_level, color='blue', linestyle='--', label='Initial GW')
    ax6.axhline(y=basin_level, color='orange', linestyle='-', label='Basin Floor')
    ax6.set_xlabel('Time (hours)')
    ax6.set_ylabel('Head (m)')
    ax6.set_title('Head at Basin Center')
    ax6.legend()
    ax6.grid(True, alpha=0.3)
    
    # Plot 7: Cross-section (peak time)
    ax7 = plt.subplot(3, 3, 7)
    center_row = (r1 + r2) // 2
    
    # Calculate actual distances
    x_distances = np.zeros(grid_info['ncol'])
    for i in range(1, grid_info['ncol']):
        x_distances[i] = x_distances[i-1] + grid_info['delr'][i-1]
    
    for k in range(min(3, head_peak.shape[0])):
        ax7.plot(x_distances, head_peak[k][center_row, :], 
                label=f'Layer {k+1}', linewidth=1.5, alpha=0.7)
    
    # Reference lines
    ax7.axhline(y=ground_surface, color='brown', linestyle='-', linewidth=2, label='Ground')
    ax7.axhline(y=basin_level, color='orange', linestyle='-', linewidth=1.5, label='Basin')
    ax7.axhline(y=gw_level, color='blue', linestyle='--', linewidth=2, label='Initial GW')
    
    # Basin extent
    basin_x1 = x_distances[c1]
    basin_x2 = x_distances[c2]
    ax7.axvspan(basin_x1, basin_x2, alpha=0.2, color='red', label='Basin')
    
    ax7.set_xlabel('Distance (m)')
    ax7.set_ylabel('Head (m)')
    ax7.set_title('Cross-Section (Peak Flow)')
    ax7.legend(fontsize=8)
    ax7.grid(True, alpha=0.3)
    
    # Plot 8: Volume balance
    ax8 = plt.subplot(3, 3, 8)
    
    # Calculate cumulative inflow
    cumulative_inflow = []
    total_volume = 0
    for i, (sp_length, _, _) in enumerate(stress_periods):
        total_volume += sp_flows[i] * sp_length
        cumulative_inflow.append(total_volume)
    
    ax8.plot(sp_times_hours, cumulative_inflow, 'g-', linewidth=2)
    ax8.set_xlabel('Time (hours)')
    ax8.set_ylabel('Cumulative Volume (m³)')
    ax8.set_title('Cumulative Inflow')
    ax8.grid(True, alpha=0.3)
    
    # Plot 9: Model summary text
    ax9 = plt.subplot(3, 3, 9)
    ax9.axis('off')
    
    summary_text = f"""PHASE 2: Transient Results

Simulation Duration: {times[-1]/3600:.1f} hours
Total Inflow: {total_volume:.1f} m³
Peak Flow: {sp_flows.max():.4f} m³/s

Head Changes:
• Initial: {head_initial[0].mean():.3f} m
• Peak: {head_peak[0].max():.3f} m  
• Final: {head_final[0].mean():.3f} m
• Max mounding: {head_peak[0].max() - gw_level:.3f} m

Grid: {grid_info['nrow']} × {grid_info['ncol']} cells
Domain: {grid_info['domain_length']:.0f} × {grid_info['domain_width']:.0f} m
Stress Periods: {len(stress_periods)}

Basin: {(c2-c1)*(r2-r1)} cells
Distribution: Uniform wells in top layer

Status: ✅ Transient simulation complete
Ready for: Phase 3 (LAK Package)
"""
    
    ax9.text(0.05, 0.95, summary_text, transform=ax9.transAxes,
            fontsize=9, verticalalignment='top', fontfamily='monospace')
    
    plt.suptitle("Phase 2: Transient Model Results with TS1 Inflow", 
                fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(model_ws, "phase2_transient_results.png"), dpi=150)
    plt.show()

def basin_spill_check(hds, times_out, grid_info, basin_level, basin_depth, gw_level):
    """
    Check if basin spills and provide detailed warnings
    """
    # Basin location
    r1, r2 = grid_info['basin_rows']
    c1, c2 = grid_info['basin_cols']
    center_row = (r1 + r2) // 2
    center_col = (c1 + c2) // 2
    
    # Extract time series at basin center
    heads_time = []
    water_depths = []
    spill_times = []
    spill_depths = []
    
    basin_top_elevation = basin_level + basin_depth
    
    for i, time in enumerate(times_out):
        try:
            h = hds.get_data(totim=time)
            head_at_basin = h[0, center_row, center_col]
            heads_time.append(head_at_basin)
            
            # Calculate water depth in basin
            if head_at_basin > basin_level:
                water_depth = head_at_basin - basin_level
                water_depths.append(water_depth)
                
                # Check for spilling (water depth exceeds basin depth)
                if water_depth > basin_depth:
                    spill_times.append(time)
                    spill_depth = water_depth - basin_depth
                    spill_depths.append(spill_depth)
            else:
                water_depths.append(0)
        except:
            heads_time.append(gw_level)
            water_depths.append(0)
    
    # Check for spilling conditions
    max_water_depth = max(water_depths) if water_depths else 0
    is_spilling = max_water_depth > basin_depth
    
    # Print detailed warnings
    if is_spilling:
        print("\n" + "="*70)
        print("⚠️ ⚠️ ⚠️  WARNING: BASIN SPILLS! ⚠️ ⚠️ ⚠️")
        print("="*70)
        print(f"  Basin depth (design): {basin_depth:.2f} m")
        print(f"  Maximum water depth: {max_water_depth:.2f} m")
        print(f"  Overflow depth: {max_water_depth - basin_depth:.2f} m")
        print(f"  Basin top elevation: {basin_top_elevation:.2f} m")
        print(f"  Maximum head elevation: {max(heads_time):.2f} m")
        
        if spill_times:
            print(f"  First spill at: {spill_times[0]/60:.1f} minutes")
            print(f"  Last spill at: {spill_times[-1]/60:.1f} minutes")
            print(f"  Spill duration: {len(spill_times)} time steps")
            print(f"  Maximum overflow: {max(spill_depths):.2f} m")
        
        print("\n  🚨 RECOMMENDATIONS:")
        print(f"     1. Increase basin depth to ≥{max_water_depth*1.1:.1f} m")
        print(f"     2. Increase basin area to reduce water depth")
        print(f"     3. Consider overflow outlet design")
        print(f"     4. Use smaller/longer duration storms")
        print("="*70 + "\n")
    else:
        print(f"\n✅ Basin does NOT spill - maximum water depth: {max_water_depth:.2f} m")
        freeboard = basin_depth - max_water_depth
        print(f"   Freeboard remaining: {freeboard:.2f} m ({freeboard/basin_depth*100:.1f}% of depth)")

def main():
    """Phase 2: Transient modeling with TS1 inflow"""
    print("Basin Infiltration Modeling - Phase 2")
    print("Transient Simulation with TS1 Inflow")
    print("=" * 60)
    
    try:
        # Get basin parameters
        print("\nEnter basin parameters:")
        basin_length = float(input("Basin length (m) [5-100]: "))
        basin_width = float(input("Basin width (m) [5-100]: "))
        basin_depth = float(input("Basin depth (m) [0.5-5]: "))
        basin_level = float(input("Basin floor elevation (m): "))
        gw_level = float(input("Groundwater level (m): "))
        hk = float(input("Hydraulic conductivity (m/day) [0.01-10]: "))
        sy = float(input("Specific yield [0.01-0.3]: "))
        
        # Validation
        if gw_level >= basin_level:
            print(f"\n⚠️ ERROR: Groundwater level ({gw_level}m) must be below basin floor ({basin_level}m)")
            return
        
        # Select TS1 file
        ts1_filepath = select_ts1_file()
        if ts1_filepath is None:
            return
        
        print(f"\n📋 Phase 2 Configuration:")
        print(f"  Basin: {basin_length}m × {basin_width}m × {basin_depth}m")
        print(f"  Elevations: Basin at {basin_level}m, GW at {gw_level}m")
        print(f"  TS1 file: {os.path.basename(ts1_filepath)}")
        print(f"  Model type: TRANSIENT with time-varying inflow")
        
        # Run transient model
        sim, gwf, grid_info = build_transient_model(basin_length, basin_width, basin_depth, 
                                                   basin_level, gw_level, hk, sy, ts1_filepath)
        
        if sim is not None:
            print("\n🎉 Phase 2 Complete - Transient Model!")
            print(f"📁 Results: {sim.simulation_data.mfpath.get_sim_path()}")
            print("\n🚀 READY FOR PHASE 3: LAK Package Integration")
            print("   → Realistic basin representation with lake levels")
            print("   → Stage-discharge relationships")
            print("   → Enhanced infiltration modeling")
        else:
            print("\n❌ Phase 2 failed")
            
    except ValueError as e:
        print(f"Input error: {e}")
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
