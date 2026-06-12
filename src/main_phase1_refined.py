import os
import numpy as np
import flopy
import matplotlib.pyplot as plt

def create_refined_grid(basin_length, basin_width, domain_factor=10):
    """
    Create refined grid with smaller cells near basin
    
    Parameters:
    -----------
    domain_factor : float
        Domain size multiplier (10 = domain is 10x basin size)
        Increased from 4 to 10 to minimize boundary effects
    """
    
    # Target cell sizes
    fine_cell_size = 2.0    # 2m cells in basin area
    medium_cell_size = 5.0  # 5m cells in transition zone
    coarse_cell_size = 10.0 # 10m cells far from basin (larger for efficiency)
    
    # Calculate domain size - much larger to avoid boundary effects
    domain_length = basin_length * domain_factor
    domain_width = basin_width * domain_factor
    
    # Three-zone grid design for efficiency
    # Zone 1: Fine cells for basin + immediate surroundings
    n_fine_length = int(basin_length / fine_cell_size) + 10  # +10 for good buffer
    n_fine_width = int(basin_width / fine_cell_size) + 10    # +10 for good buffer
    
    # Zone 2: Medium cells for transition zone
    transition_zone = 50  # 50m transition zone on each side
    n_medium_per_side_length = int(transition_zone / medium_cell_size)  # Per side
    n_medium_per_side_width = int(transition_zone / medium_cell_size)   # Per side
    
    # Zone 3: Coarse cells for far field
    fine_zone_size_length = n_fine_length * fine_cell_size
    fine_zone_size_width = n_fine_width * fine_cell_size
    medium_zone_size_length = n_medium_per_side_length * medium_cell_size * 2  # Both sides
    medium_zone_size_width = n_medium_per_side_width * medium_cell_size * 2    # Both sides
    
    remaining_length = domain_length - fine_zone_size_length - medium_zone_size_length
    remaining_width = domain_width - fine_zone_size_width - medium_zone_size_width
    
    n_coarse_per_side_length = max(1, int(remaining_length / coarse_cell_size / 2))
    n_coarse_per_side_width = max(1, int(remaining_width / coarse_cell_size / 2))
    
    # Build DELR array (column widths) - symmetric
    delr = []
    delr.extend([coarse_cell_size] * n_coarse_per_side_length)      # Left coarse
    delr.extend([medium_cell_size] * n_medium_per_side_length)      # Left medium
    delr.extend([fine_cell_size] * n_fine_length)                   # Center fine
    delr.extend([medium_cell_size] * n_medium_per_side_length)      # Right medium
    delr.extend([coarse_cell_size] * n_coarse_per_side_length)      # Right coarse
    
    # Build DELC array (row widths) - symmetric
    delc = []
    delc.extend([coarse_cell_size] * n_coarse_per_side_width)       # Top coarse
    delc.extend([medium_cell_size] * n_medium_per_side_width)       # Top medium
    delc.extend([fine_cell_size] * n_fine_width)                    # Center fine
    delc.extend([medium_cell_size] * n_medium_per_side_width)       # Bottom medium
    delc.extend([coarse_cell_size] * n_coarse_per_side_width)       # Bottom coarse
    
    ncol = len(delr)
    nrow = len(delc)
    
    # FIXED: Calculate basin location indices correctly
    # The basin should be centered in the fine zone
    # Start of fine zone in grid:
    fine_zone_start_col = n_coarse_per_side_length + n_medium_per_side_length
    fine_zone_start_row = n_coarse_per_side_width + n_medium_per_side_width
    
    # Basin cells needed
    n_basin_cells_length = max(1, int(basin_length / fine_cell_size))
    n_basin_cells_width = max(1, int(basin_width / fine_cell_size))
    
    # Center basin in fine zone
    buffer_cells_length = (n_fine_length - n_basin_cells_length) // 2
    buffer_cells_width = (n_fine_width - n_basin_cells_width) // 2
    
    basin_col_start = fine_zone_start_col + buffer_cells_length
    basin_col_end = basin_col_start + n_basin_cells_length
    basin_row_start = fine_zone_start_row + buffer_cells_width
    basin_row_end = basin_row_start + n_basin_cells_width
    
    # Calculate actual domain dimensions
    actual_domain_length = sum(delr)
    actual_domain_width = sum(delc)
    
    print(f"\n📐 Grid Design (3-zone refinement):")
    print(f"  Domain: {actual_domain_length:.0f}m × {actual_domain_width:.0f}m")
    print(f"  Distance to boundaries: >{(actual_domain_length - basin_length)/2:.0f}m")
    print(f"  Grid zones:")
    print(f"    - Fine (2m): {n_fine_length*fine_cell_size:.0f}m × {n_fine_width*fine_cell_size:.0f}m center zone")
    print(f"    - Medium (5m): {n_medium_per_side_length*medium_cell_size:.0f}m transition zones")
    print(f"    - Coarse (10m): Outer regions")
    print(f"  Basin location:")
    print(f"    - Columns: {basin_col_start} to {basin_col_end} ({n_basin_cells_length} cells)")
    print(f"    - Rows: {basin_row_start} to {basin_row_end} ({n_basin_cells_width} cells)")
    print(f"    - Total basin cells: {n_basin_cells_length * n_basin_cells_width}")
    
    return {
        'delr': np.array(delr),
        'delc': np.array(delc),
        'nrow': nrow,
        'ncol': ncol,
        'basin_rows': (basin_row_start, basin_row_end),
        'basin_cols': (basin_col_start, basin_col_end),
        'domain_length': actual_domain_length,
        'domain_width': actual_domain_width
    }

def build_refined_model(basin_length, basin_width, basin_depth, basin_level, gw_level, hk, sy):
    """
    Phase 1 Refined: Large domain to eliminate boundary effects
    
    Parameters:
    -----------
    basin_length : float : Basin length in meters
    basin_width : float : Basin width in meters
    basin_depth : float : Basin depth in meters
    basin_level : float : Elevation of basin floor (m AHD or similar datum)
    gw_level : float : Groundwater elevation (m AHD or similar datum)
    hk : float : Hydraulic conductivity (m/day)
    sy : float : Specific yield
    """
    
    print("\n" + "="*60)
    print("PHASE 1: Large Domain Model (No Boundary Effects)")
    print("="*60)
    
    # Model setup
    model_name = "basin_model"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output\phase1"
    os.makedirs(model_ws, exist_ok=True)
    
    # Create refined grid with larger domain
    grid_info = create_refined_grid(basin_length, basin_width, domain_factor=10)
    nrow = grid_info['nrow']
    ncol = grid_info['ncol']
    delr = grid_info['delr']
    delc = grid_info['delc']
    
    # Calculate ground surface from basin level and depth
    ground_surface = basin_level + basin_depth
    clearance = basin_level - gw_level
    
    print(f"\n📏 Elevation Summary:")
    print(f"  Ground surface: {ground_surface:.1f} m")
    print(f"  Basin floor: {basin_level:.1f} m")
    print(f"  Groundwater level: {gw_level:.1f} m")
    print(f"  Clearance (basin to GW): {clearance:.1f} m")
    
    # Validate elevations
    if gw_level >= basin_level:
        print(f"⚠️ WARNING: Groundwater ({gw_level:.1f}m) at or above basin floor ({basin_level:.1f}m)")
        print("  Basin may have standing water!")
    
    print(f"\n🔲 Grid Configuration:")
    print(f"  Total cells: {nrow} rows × {ncol} cols = {nrow*ncol} cells")
    print(f"  Basin location: rows {grid_info['basin_rows']}, cols {grid_info['basin_cols']}")
    print(f"  Basin spans: {grid_info['basin_cols'][1] - grid_info['basin_cols'][0]} × {grid_info['basin_rows'][1] - grid_info['basin_rows'][0]} cells")
    
    # Check boundary distance
    boundary_distance_x = (grid_info['domain_length'] - basin_length) / 2
    boundary_distance_y = (grid_info['domain_width'] - basin_width) / 2
    min_safe_distance = 50  # Minimum 50m from boundaries
    
    if min(boundary_distance_x, boundary_distance_y) < min_safe_distance:
        print(f"⚠️ WARNING: Boundaries may be too close ({min(boundary_distance_x, boundary_distance_y):.0f}m)")
    else:
        print(f"✅ Boundary distance adequate: >{min(boundary_distance_x, boundary_distance_y):.0f}m")
    
    # Enhanced vertical discretization based on real elevations
    nlay = 8  # More layers for better resolution
    
    # Layer design based on actual elevations
    min_model_bottom = min(gw_level - 40, basin_level - 45)  # Deeper model
    
    # Define layer bottoms with finer resolution near water table
    layer_bottoms = [
        gw_level - 0.5,           # Layer 1: 0.5m below groundwater
        gw_level - 1.5,           # Layer 2: 1.5m below groundwater
        gw_level - 3.0,           # Layer 3: 3m below groundwater
        gw_level - 6.0,           # Layer 4: 6m below groundwater
        gw_level - 10.0,          # Layer 5: 10m below groundwater
        gw_level - 20.0,          # Layer 6: 20m below groundwater
        gw_level - 30.0,          # Layer 7: 30m below groundwater
        min_model_bottom          # Layer 8: Model bottom
    ]
    
    print(f"\n📊 Layer Structure:")
    print(f"  Layers: {nlay} (refined near water table)")
    print(f"  Model top: {ground_surface:.1f} m")
    print(f"  Model bottom: {min_model_bottom:.1f} m")
    print(f"  Total thickness: {ground_surface - min_model_bottom:.1f} m")
    
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
    
    # Time discretization - steady state
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(1.0, 1, 1.0)]
    )
    
    # Enhanced solver for variable grid
    ims = flopy.mf6.ModflowIms(
        sim, 
        complexity="MODERATE",
        outer_dvclose=1e-6,
        inner_dvclose=1e-7
    )
    
    # Groundwater flow model
    gwf = flopy.mf6.ModflowGwf(sim, modelname=model_name, save_flows=True)
    
    # Discretization with variable grid
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=nlay, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top, botm=botm
    )
    
    # Initial conditions - use actual groundwater level
    initial_head = np.ones((nlay, nrow, ncol)) * gw_level
    ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_head)
    
    # Node property flow - CORRECTED 1:1 ANISOTROPY for sand
    hk_ms = hk / 86400  # Convert m/day to m/s
    
    # Layer-specific K values (slight decrease with depth)
    k_horizontal = np.ones(nlay) * hk_ms
    k_vertical = np.ones(nlay) * hk_ms  # 1:1 ratio for sandy infiltration basins
    
    # Slight decrease with depth (realistic)
    for k in range(nlay):
        depth_factor = 1.0 - (k * 0.03)  # 3% reduction per layer
        k_horizontal[k] *= depth_factor
        k_vertical[k] *= depth_factor
    
    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,  # All layers convertible
        k=k_horizontal,
        k33=k_vertical  # 1:1 anisotropy for sand
    )
    
    print(f"\n⚙️ Hydraulic Properties:")
    print(f"Anisotropy: 1:1 (isotropic for sand)")
    print(f"K range: {k_horizontal[-1]*86400:.2f} to {k_horizontal[0]*86400:.2f} m/day")
    
    # Storage
    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        ss=1e-5,
        sy=sy,
        steady_state=True
    )
    
    # Constant head boundaries at edges only
    chd_spd = []
    n_boundaries = 0
    for k in range(nlay):
        for i in range(nrow):
            chd_spd.append(((k, i, 0), gw_level))
            chd_spd.append(((k, i, ncol-1), gw_level))
            n_boundaries += 2
        for j in range(1, ncol-1):
            chd_spd.append(((k, 0, j), gw_level))
            chd_spd.append(((k, nrow-1, j), gw_level))
            n_boundaries += 2
    
    print(f"\n🔲 Boundary Conditions:")
    print(f"  Type: Constant head at {gw_level:.1f} m")
    print(f"  Location: Model edges only")
    print(f"  Total CHD cells: {n_boundaries}")
    print(f"  Distance from basin: >{min(boundary_distance_x, boundary_distance_y):.0f}m")
    
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    
    # Output control
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{model_name}.hds",
        saverecord=[("HEAD", "ALL")],
        printrecord=[("HEAD", "ALL")]
    )
    
    # Write and run
    print("\nWriting model files...")
    sim.write_simulation()
    
    print("Running MODFLOW 6...")
    success, buff = sim.run_simulation()
    
    if success:
        print("✅ Large domain model completed successfully!")
        
        # Enhanced visualization for large domain
        head_file = os.path.join(model_ws, f"{model_name}.hds")
        if os.path.exists(head_file):
            hds = flopy.utils.HeadFile(head_file)
            head = hds.get_data()
            
            # Create comprehensive visualization
            fig = plt.figure(figsize=(16, 10))
            
            # Plot 1: Full domain view
            ax1 = plt.subplot(2, 3, 1)
            im1 = ax1.imshow(head[0], aspect='auto', cmap='viridis')
            plt.colorbar(im1, ax=ax1, label="Head (m)", shrink=0.7)
            ax1.set_title("Full Domain - Layer 1")
            
            # Mark basin location
            r1, r2 = grid_info['basin_rows']
            c1, c2 = grid_info['basin_cols']
            rect = plt.Rectangle((c1-0.5, r1-0.5), c2-c1, r2-r1, 
                               fill=False, edgecolor='red', linewidth=2)
            ax1.add_patch(rect)
            ax1.text(c1, r1-2, 'Basin', color='red', fontweight='bold', fontsize=8)
            ax1.set_xlabel(f"Domain: {grid_info['domain_length']:.0f}m")
            ax1.set_ylabel(f"Domain: {grid_info['domain_width']:.0f}m")
            
            # Plot 2: Zoomed view of basin area
            ax2 = plt.subplot(2, 3, 2)
            # Extract basin area with buffer
            buffer = 10
            r1b, r2b = max(0, r1-buffer), min(nrow, r2+buffer)
            c1b, c2b = max(0, c1-buffer), min(ncol, c2+buffer)
            basin_area = head[0][r1b:r2b, c1b:c2b]
            im2 = ax2.imshow(basin_area, aspect='auto', cmap='viridis')
            plt.colorbar(im2, ax=ax2, label="Head (m)", shrink=0.7)
            ax2.set_title("Zoomed: Basin Area (2m cells)")
            
            # Mark exact basin
            rect2 = plt.Rectangle((buffer-0.5, buffer-0.5), c2-c1, r2-r1, 
                                fill=False, edgecolor='red', linewidth=2)
            ax2.add_patch(rect2)
            
            # Plot 3: Cross-section through basin
            ax3 = plt.subplot(2, 3, 3)
            center_row = (r1 + r2) // 2
            
            # Calculate actual distances
            x_distances = np.zeros(ncol)
            for i in range(1, ncol):
                x_distances[i] = x_distances[i-1] + delr[i-1]
            
            for k in range(min(3, nlay)):
                ax3.plot(x_distances, head[k][center_row, :], 
                        label=f'Layer {k+1}', linewidth=1.5, alpha=0.7)
            
            # Mark basin extent
            basin_x1 = x_distances[c1]
            basin_x2 = x_distances[c2]
            ax3.axvspan(basin_x1, basin_x2, alpha=0.2, color='red', label='Basin')
            ax3.set_title("Head Profile Through Basin")
            ax3.set_xlabel("Distance (m)")
            ax3.set_ylabel("Head (m)")
            ax3.legend(loc='best', fontsize=8)
            ax3.grid(True, alpha=0.3)
            
            # Plot 4: Grid spacing visualization
            ax4 = plt.subplot(2, 3, 4)
            # Create grid spacing matrix - show both X and Y refinement
            grid_spacing = np.zeros((nrow, ncol))
            for i in range(nrow):
                for j in range(ncol):
                    # Show cell area to capture refinement in both directions
                    grid_spacing[i, j] = delr[j] * delc[i]  # Cell area in m²
            
            im4 = ax4.imshow(grid_spacing, aspect='auto', cmap='coolwarm')
            plt.colorbar(im4, ax=ax4, label="Cell Area (m²)", shrink=0.7)
            ax4.set_title("Grid Refinement Map (Both Directions)")
            
            # Mark basin
            rect4 = plt.Rectangle((c1-0.5, r1-0.5), c2-c1, r2-r1, 
                               fill=False, edgecolor='black', linewidth=2)
            ax4.add_patch(rect4)
            ax4.text(c1, r1-2, 'Basin\n(4 m² cells)', color='black', fontweight='bold', fontsize=8)
            
            # Plot 5: Vertical profile at basin center
            ax5 = plt.subplot(2, 3, 5)
            center_col = (c1 + c2) // 2
            
            # Vertical head profile
            heads_vertical = [head[k][center_row, center_col] for k in range(nlay)]
            layer_centers = []
            for k in range(nlay):
                if k == 0:
                    layer_centers.append((ground_surface + layer_bottoms[k]) / 2)
                else:
                    layer_centers.append((layer_bottoms[k-1] + layer_bottoms[k]) / 2)
            
            ax5.plot(heads_vertical, layer_centers, 'bo-', linewidth=2, markersize=8)
            
            # Reference lines
            ax5.axvline(x=gw_level, color='blue', linestyle='--', linewidth=2, label='GW Level')
            ax5.axhline(y=ground_surface, color='brown', linestyle='-', linewidth=2, label='Ground')
            ax5.axhline(y=basin_level, color='orange', linestyle='-', linewidth=1.5, label='Basin Floor')
            
            # Show full profile
            y_top = ground_surface + 2
            y_bottom = min(layer_bottoms) - 2
            ax5.set_ylim(y_bottom, y_top)
            ax5.set_xlabel("Head (m)")
            ax5.set_ylabel("Elevation (m)")
            ax5.set_title("Vertical Profile at Basin Center")
            ax5.grid(True, alpha=0.3)
            ax5.legend(loc='best', fontsize=8)
            
            # Plot 6: Model info text
            ax6 = plt.subplot(2, 3, 6)
            ax6.axis('off')
            
            info_text = f"""Model Configuration Summary

Domain Size: {grid_info['domain_length']:.0f}m × {grid_info['domain_width']:.0f}m
Grid Cells: {nrow} × {ncol} = {nrow*ncol} cells
Layers: {nlay}

Basin Parameters:
  • Size: {basin_length}m × {basin_width}m × {basin_depth}m
  • Floor elevation: {basin_level:.1f}m
  • Ground surface: {ground_surface:.1f}m
  • GW level: {gw_level:.1f}m
  • Clearance: {clearance:.1f}m

Grid Refinement:
  • Fine (2m): Basin area
  • Medium (5m): Transition zone
  • Coarse (10m): Far field

Boundary Distance:
  • X-direction: {boundary_distance_x:.0f}m
  • Y-direction: {boundary_distance_y:.0f}m
  • Status: {"✅ No boundary effects expected" if min(boundary_distance_x, boundary_distance_y) > 50 else "⚠️ May have boundary effects"}

Hydraulic Properties:
  • K: {hk:.2f} m/day (isotropic)
  • Sy: {sy:.2f}
"""
            ax6.text(0.05, 0.95, info_text, transform=ax6.transAxes,
                    fontsize=9, verticalalignment='top', fontfamily='monospace')
            
            plt.suptitle("Phase 1: Large Domain Model - No Boundary Effects", 
                        fontsize=14, fontweight='bold')
            plt.tight_layout()
            plt.savefig(os.path.join(model_ws, "phase1_large_domain.png"), dpi=150)
            plt.show()
            
            print(f"\n📊 Model Results Summary:")
            print(f"  ✅ Head range: {head.min():.3f} to {head.max():.3f} m")
            print(f"  ✅ Convergence achieved")
            print(f"  ✅ No boundary effects expected (>{min(boundary_distance_x, boundary_distance_y):.0f}m clearance)")
            print(f"  ✅ Ready for Phase 2 (transient) and Phase 3 (LAK)")
        
        return sim, gwf, grid_info
    else:
        print("❌ Refined model failed")
        return None, None, None

def main():
    """Test Phase 1 with large domain"""
    print("Basin Infiltration Modeling - Phase 1")
    print("Large Domain Configuration (No Boundary Effects)")
    print("=" * 60)
    
    try:
        # Get user input - using real elevation inputs
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
        
        print(f"\n📋 Configuration Summary:")
        print(f"  Basin: {basin_length}m × {basin_width}m × {basin_depth}m")
        print(f"  Elevations: Basin at {basin_level}m, GW at {gw_level}m")
        print(f"  Domain: ~{basin_length*10}m × {basin_width*10}m (10× basin size)")
        
        # Run model with large domain
        sim, gwf, grid_info = build_refined_model(basin_length, basin_width, basin_depth, 
                                                 basin_level, gw_level, hk, sy)
        
        if sim is not None:
            print("\n🎉 Phase 1 Complete with Large Domain!")
            print(f"📁 Results: {sim.simulation_data.mfpath.get_sim_path()}")
            print("\n🚀 READY FOR PHASE 2: Adding transient capabilities")
            print("   → No boundary effects expected")
            print("   → Grid refinement optimal for infiltration modeling")
        else:
            print("\n❌ Model failed")
            
    except ValueError as e:
        print(f"Input error: {e}")
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
