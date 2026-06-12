import os
import numpy as np
import flopy
import matplotlib.pyplot as plt

def build_basic_model(basin_length, basin_width, basin_depth, gw_clearance, hk, sy):
    """Phase 1: Basic steady-state groundwater model without LAK"""
    
    print("\n" + "="*50)
    print("PHASE 1: Building Basic Groundwater Model")
    print("="*50)
    
    # Model setup
    model_name = "basin_basic"  # Shortened to under 16 characters
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase1"
    os.makedirs(model_ws, exist_ok=True)
    
    # Simple grid
    nlay, nrow, ncol = 3, 30, 30
    delr = delc = 5.0  # 5m cells
    
    # Model domain elevations
    ground_surface = 10.0  # Ground surface elevation (m)
    
    # Calculate initial water table based on user input
    # Water table should be gw_clearance meters below ground surface
    initial_water_table = ground_surface - gw_clearance
    
    print(f"Ground surface elevation: {ground_surface} m")
    print(f"Initial water table: {initial_water_table} m")
    print(f"Clearance to groundwater: {gw_clearance} m")
    
    # Create layer elevations
    top = np.ones((nrow, ncol)) * ground_surface
    
    # Layer bottoms
    botm = np.zeros((nlay, nrow, ncol))
    botm[0] = ground_surface - 5     # Layer 1 bottom at 5m depth
    botm[1] = ground_surface - 15    # Layer 2 bottom at 15m depth
    botm[2] = ground_surface - 30    # Layer 3 bottom at 30m depth
    
    print(f"Grid: {nlay} layers, {nrow} rows, {ncol} columns")
    print(f"Cell size: {delr}m x {delc}m")
    
    # Create simulation
    sim = flopy.mf6.MFSimulation(
        sim_name=model_name,
        exe_name=r"C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe",
        sim_ws=model_ws
    )
    
    # Time discretization - steady state for now
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(1.0, 1, 1.0)]  # 1 day, 1 step, steady
    )
    
    # Solver
    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(sim, modelname=model_name, save_flows=True)
    
    # Discretization
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=nlay, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top, botm=botm
    )
    
    # Initial conditions - set water table at user-specified depth
    initial_head = np.ones((nlay, nrow, ncol)) * initial_water_table
    ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_head)
    
    # Node property flow - use user's hydraulic conductivity
    hk_ms = hk / 86400  # Convert m/day to m/s
    print(f"Hydraulic conductivity: {hk} m/day = {hk_ms:.2e} m/s")
    
    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,  # All layers convertible
        k=hk_ms,
        k33=hk_ms/10  # Vertical K is typically lower
    )
    
    # Storage - even though steady state, needed for future transient
    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        ss=1e-5,
        sy=sy,
        steady_state=True  # Steady for phase 1
    )
    
    # Constant head boundaries at edges
    print("Setting up constant head boundaries...")
    chd_spd = []
    for k in range(nlay):
        for i in range(nrow):
            chd_spd.append(((k, i, 0), initial_water_table))
            chd_spd.append(((k, i, ncol-1), initial_water_table))
        for j in range(1, ncol-1):
            chd_spd.append(((k, 0, j), initial_water_table))
            chd_spd.append(((k, nrow-1, j), initial_water_table))
    
    print(f"Created {len(chd_spd)} constant head cells")
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        budget_filerecord=f"{model_name}.bud",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "ALL"), ("BUDGET", "ALL")]
    )
    
    # Write and run
    print("\nWriting model files...")
    sim.write_simulation()
    
    print("Running MODFLOW 6...")
    success, buff = sim.run_simulation()
    
    if success:
        print("✅ Phase 1 model ran successfully!")
        
        # Plot results
        head_file = os.path.join(model_ws, f"{model_name}.hds")
        if os.path.exists(head_file):
            hds = flopy.utils.HeadFile(head_file)
            head = hds.get_data()
            
            # Simple plot
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
            
            # Plot layer 1 heads
            im1 = ax1.imshow(head[0], extent=(0, ncol*delr, 0, nrow*delc), cmap='viridis')
            plt.colorbar(im1, ax=ax1, label="Head (m)")
            ax1.set_title(f"Layer 1 Heads\nWater table at {initial_water_table:.1f} m")
            ax1.set_xlabel("Distance (m)")
            ax1.set_ylabel("Distance (m)")
            
            # Add contours
            X, Y = np.meshgrid(np.arange(ncol)*delr, np.arange(nrow)*delc)
            CS1 = ax1.contour(X, Y, head[0], colors='white', linewidths=0.5)
            ax1.clabel(CS1, inline=True, fontsize=8)
            
            # Mark future basin location (center of domain)
            basin_center_x = ncol * delr / 2
            basin_center_y = nrow * delc / 2
            basin_x_size = basin_length
            basin_y_size = basin_width
            
            # Draw basin outline
            basin_rect = plt.Rectangle(
                (basin_center_x - basin_x_size/2, basin_center_y - basin_y_size/2),
                basin_x_size, basin_y_size,
                fill=False, edgecolor='red', linewidth=2, linestyle='--'
            )
            ax1.add_patch(basin_rect)
            ax1.text(basin_center_x, basin_center_y, 'Future\nBasin', 
                    ha='center', va='center', color='red', fontweight='bold')
            
            # Plot cross-section through center
            center_row = nrow // 2
            x_coords = np.arange(ncol) * delr
            
            ax2.plot(x_coords, head[0, center_row, :], 'b-', linewidth=2, label='Layer 1')
            ax2.plot(x_coords, head[1, center_row, :], 'g-', linewidth=2, label='Layer 2')
            ax2.plot(x_coords, head[2, center_row, :], 'r-', linewidth=2, label='Layer 3')
            
            # Add ground surface and layer boundaries
            ax2.axhline(y=ground_surface, color='brown', linestyle='-', alpha=0.7, label='Ground Surface')
            ax2.axhline(y=ground_surface-5, color='gray', linestyle='--', alpha=0.5)
            ax2.axhline(y=ground_surface-15, color='gray', linestyle='--', alpha=0.5)
            ax2.axhline(y=ground_surface-30, color='gray', linestyle='--', alpha=0.5)
            
            # Mark basin location on cross-section
            basin_start_x = basin_center_x - basin_x_size/2
            basin_end_x = basin_center_x + basin_x_size/2
            ax2.axvspan(basin_start_x, basin_end_x, alpha=0.2, color='red', label='Basin Location')
            
            ax2.set_xlabel("Distance (m)")
            ax2.set_ylabel("Elevation (m)")
            ax2.set_title("Cross-Section Through Model Center")
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            plt.savefig(os.path.join(model_ws, "phase1_results.png"), dpi=150, bbox_inches='tight')
            plt.show()
            
            # Summary statistics
            print(f"\n📊 Phase 1 Results Summary:")
            print(f"   - Model domain: {ncol*delr:.0f}m x {nrow*delc:.0f}m")
            print(f"   - Head range: {head.min():.2f} to {head.max():.2f} m")
            print(f"   - Mean head: {head.mean():.2f} m")
            print(f"   - Basin location marked for future phases")
            
        return sim, gwf
    else:
        print("❌ Phase 1 model failed to run")
        print("Listing file contents:")
        lst_file = os.path.join(model_ws, "mfsim.lst")
        if os.path.exists(lst_file):
            with open(lst_file, 'r') as f:
                print(f.read())
        return None, None

def main():
    """Test Phase 1 basic model"""
    print("Basin Infiltration Modeling - Phase 1 Test")
    print("==========================================")
    
    try:
        # Get user input
        print("\nEnter basin parameters:")
        basin_length = float(input("Basin length (m) [5-100]: "))
        basin_width = float(input("Basin width (m) [5-100]: "))
        basin_depth = float(input("Basin depth (m) [0.5-5]: "))
        gw_clearance = float(input("Clearance to groundwater (m) [1-10]: "))
        hk = float(input("Hydraulic conductivity (m/day) [0.01-10]: "))
        sy = float(input("Specific yield [0.01-0.3]: "))
        
        # Validate inputs
        if not (5 <= basin_length <= 100):
            raise ValueError("Basin length must be between 5-100m")
        if not (5 <= basin_width <= 100):
            raise ValueError("Basin width must be between 5-100m")
        if not (0.5 <= basin_depth <= 5):
            raise ValueError("Basin depth must be between 0.5-5m")
        if not (1 <= gw_clearance <= 10):
            raise ValueError("Groundwater clearance must be between 1-10m")
        if not (0.01 <= hk <= 10):
            raise ValueError("Hydraulic conductivity must be between 0.01-10 m/day")
        if not (0.01 <= sy <= 0.3):
            raise ValueError("Specific yield must be between 0.01-0.3")
    
        print(f"\n📋 Phase 1 Parameters:")
        print(f"  Basin: {basin_length}m x {basin_width}m x {basin_depth}m deep")
        print(f"  Groundwater clearance: {gw_clearance}m")
        print(f"  Hydraulic conductivity: {hk} m/day")
        print(f"  Specific yield: {sy}")
        
        # Run Phase 1
        sim, gwf = build_basic_model(basin_length, basin_width, basin_depth, 
                                     gw_clearance, hk, sy)
        
        if sim is not None:
            print("\n🎉 Phase 1 Complete - Basic groundwater model working!")
            print(f"📁 Results saved to: {sim.sim_ws}")
            print("\n🚀 Ready for Phase 2: Transient capabilities")
        else:
            print("\n❌ Phase 1 Failed - Debug needed before proceeding")
            
    except ValueError as e:
        print(f"Input error: {e}")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
