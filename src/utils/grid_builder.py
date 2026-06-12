"""
Grid Builder Utilities for Basin Infiltration Modeling
======================================================

This module provides enhanced grid building capabilities for the BaSIM project,
including three-zone refinement, adaptive meshing, and grid optimization.

Author: Basin Infiltration Simulator (BaSIM)
Date: August 2025
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def create_adaptive_refined_grid(basin_length, basin_width, domain_factor=10, 
                                refinement_zones=3, min_cell_size=1.0, max_cell_size=20.0):
    """
    Create an adaptive refined grid with multiple refinement zones
    
    Parameters:
    -----------
    basin_length : float
        Length of the infiltration basin (m)
    basin_width : float
        Width of the infiltration basin (m)
    domain_factor : float
        Multiplier for domain size relative to basin
    refinement_zones : int
        Number of refinement zones (2, 3, or 4)
    min_cell_size : float
        Minimum cell size in basin area (m)
    max_cell_size : float
        Maximum cell size at domain boundaries (m)
    
    Returns:
    --------
    grid_info : dict
        Dictionary containing grid information
    """
    
    print(f"\n📐 Creating adaptive refined grid...")
    print(f"   🏞️ Basin: {basin_length}m × {basin_width}m")
    print(f"   🔍 Refinement zones: {refinement_zones}")
    print(f"   📏 Cell size range: {min_cell_size}m - {max_cell_size}m")
    
    # Calculate domain size. Domain spans symmetrically about basin center.
    # domain_factor multiplies the basin dimensions, so a factor of 12 means
    # boundaries are about 6 basin widths away from center in each direction.
    domain_length = basin_length * domain_factor
    domain_width = basin_width * domain_factor
    
    print(f"   🌐 Domain: {domain_length}m × {domain_width}m")
    
    # Define refinement zones
    if refinement_zones == 2:
        # Simple two-zone: fine basin, coarse outside
        zones = [
            {'name': 'basin', 'cell_size': min_cell_size, 'extent_factor': 1.2},
            {'name': 'far_field', 'cell_size': max_cell_size, 'extent_factor': domain_factor}
        ]
    
    elif refinement_zones == 3:
        # Three-zone: fine basin, medium transition, coarse far field
        zones = [
            {'name': 'basin', 'cell_size': min_cell_size, 'extent_factor': 2.0},
            {'name': 'transition', 'cell_size': min_cell_size * 2.5, 'extent_factor': 5.0},
            {'name': 'far_field', 'cell_size': max_cell_size, 'extent_factor': domain_factor}
        ]
    
    elif refinement_zones == 4:
        # Four-zone: finest basin, fine near, medium mid, coarse far
        zones = [
            {'name': 'basin_core', 'cell_size': min_cell_size, 'extent_factor': 2.0},
            {'name': 'basin_near', 'cell_size': min_cell_size * 1.5, 'extent_factor': 3.5},
            {'name': 'transition', 'cell_size': min_cell_size * 3.0, 'extent_factor': 6.0},
            {'name': 'far_field', 'cell_size': max_cell_size, 'extent_factor': domain_factor}
        ]
    
    else:
        raise ValueError("refinement_zones must be 2, 3, or 4")
    
    # Build grid arrays
    delr, delc, grid_zones = _build_variable_grid(
        domain_length, domain_width, basin_length, basin_width, zones
    )
    
    # Calculate grid dimensions
    nrow = len(delc)
    ncol = len(delr)
    
    # Find basin cell indices
    basin_rows, basin_cols = _find_basin_cells(
        delr, delc, domain_length, domain_width, basin_length, basin_width
    )
    
    # Calculate distances to boundaries (from basin center to nearest boundary)
    center_col = ncol // 2
    center_row = nrow // 2
    
    distance_to_boundary_x = min(
        sum(delr[:center_col]), 
        sum(delr[center_col:])
    )
    distance_to_boundary_y = min(
        sum(delc[:center_row]),
        sum(delc[center_row:])
    )
    
    grid_info = {
        'nrow': nrow,
        'ncol': ncol,
        'delr': delr,
        'delc': delc,
        'domain_length': domain_length,
        'domain_width': domain_width,
        'basin_rows': basin_rows,
        'basin_cols': basin_cols,
        'grid_zones': grid_zones,
        'refinement_zones': refinement_zones,
        'min_cell_size': min_cell_size,
        'max_cell_size': max_cell_size,
        'distance_to_boundary_x': distance_to_boundary_x,
        'distance_to_boundary_y': distance_to_boundary_y,
        'total_cells': nrow * ncol,
        'basin_cells': (basin_rows[1] - basin_rows[0]) * (basin_cols[1] - basin_cols[0])
    }
    
    print(f"   ✅ Grid created: {nrow} × {ncol} = {nrow*ncol:,} cells")
    print(f"   🎯 Basin cells: {grid_info['basin_cells']}")
    print(f"   📏 Distance to boundaries: {distance_to_boundary_x:.1f}m × {distance_to_boundary_y:.1f}m (from center)")
    
    return grid_info

def _build_variable_grid(domain_length, domain_width, basin_length, basin_width, zones):
    """
    Build variable spacing grid arrays with exact symmetry by constructing one half
    from the center to the boundary and mirroring it.
    """

    def _build_half(total_len, basin_dim, zones):
        half = []
        zone_names = []
        remaining = total_len / 2.0
        dist_from_center = 0.0
        while remaining > 1e-9:  # small epsilon to avoid infinite loop
            zone = _get_zone_for_distance(dist_from_center, basin_dim, zones)
            step = min(zone['cell_size'], remaining)
            half.append(step)
            zone_names.append(zone['name'])
            remaining -= step
            dist_from_center += step
            if len(half) > 100000:  # guard
                break
        # Adjust last to fit exactly
        if half:
            s = sum(half)
            if abs(s - total_len/2.0) > 1e-9:
                half[-1] += (total_len/2.0 - s)
        return half, zone_names

    # Columns (x direction)
    half_x, zones_x = _build_half(domain_length, basin_length, zones)
    delr = np.array(list(reversed(half_x)) + half_x)
    grid_zones_x = list(reversed(zones_x)) + zones_x

    # Rows (y direction)
    half_y, zones_y = _build_half(domain_width, basin_width, zones)
    delc = np.array(list(reversed(half_y)) + half_y)
    grid_zones_y = list(reversed(zones_y)) + zones_y

    grid_zones = {
        'x_zones': grid_zones_x,
        'y_zones': grid_zones_y
    }

    return delr, delc, grid_zones

def _get_zone_for_distance(distance, basin_dimension, zones):
    """
    Determine which refinement zone applies for a given distance from center
    """
    
    for zone in zones:
        zone_extent = basin_dimension * zone['extent_factor'] / 2
        if distance <= zone_extent:
            return zone
    
    # If beyond all zones, use the outermost zone
    return zones[-1]

def _find_basin_cells(delr, delc, domain_length, domain_width, basin_length, basin_width):
    """
    Find the row and column indices that contain the basin.
    Enforce symmetry by expanding from the domain center outward until the
    requested basin length/width is covered.
    """

    def _symmetric_span(cell_sizes, target_length):
        n = len(cell_sizes)
        if n == 0:
            return (0, 0)
        # Determine center indices
        if n % 2 == 1:
            left = right = n // 2
            total = float(cell_sizes[left])
        else:
            right = n // 2
            left = right - 1
            total = float(cell_sizes[left] + cell_sizes[right])
        # Expand alternately on both sides to maintain symmetry
        while total < target_length and (left > 0 or right < n - 1):
            grew = False
            if left > 0:
                left -= 1
                total += float(cell_sizes[left])
                grew = True
            if total >= target_length:
                break
            if right < n - 1:
                right += 1
                total += float(cell_sizes[right])
                grew = True
            if not grew:
                break
        return (left, right + 1)  # end-exclusive

    # Compute symmetric spans for columns and rows
    col_start, col_end = _symmetric_span(np.asarray(delr, dtype=float), float(basin_length))
    row_start, row_end = _symmetric_span(np.asarray(delc, dtype=float), float(basin_width))

    # Clamp to valid ranges
    col_start = max(0, min(col_start, len(delr)))
    col_end = max(col_start, min(col_end, len(delr)))
    row_start = max(0, min(row_start, len(delc)))
    row_end = max(row_start, min(row_end, len(delc)))

    return (row_start, row_end), (col_start, col_end)

def visualize_grid_refinement(grid_info, save_plot=True, plot_dir=None):
    """
    Create visualization of grid refinement pattern
    
    Parameters:
    -----------
    grid_info : dict
        Grid information from create_adaptive_refined_grid
    save_plot : bool
        Whether to save the plot
    plot_dir : str, optional
        Directory to save plots
    
    Returns:
    --------
    fig : matplotlib.figure.Figure
        The created figure
    """
    
    print(f"\n📊 Creating grid refinement visualization...")
    
    if plot_dir is None:
        plot_dir = Path("C:/Users/patri/OneDrive/BaSIM/model_output/phase3/observations")
    else:
        plot_dir = Path(plot_dir)
    
    plot_dir.mkdir(parents=True, exist_ok=True)
    
    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    
    # Plot 1: Grid cell sizes in X direction
    ax1 = axes[0, 0]
    x_centers = np.cumsum(grid_info['delr']) - grid_info['delr']/2
    ax1.bar(x_centers, grid_info['delr'], width=grid_info['delr'], alpha=0.7, edgecolor='black')
    ax1.set_xlabel('X Position (m)')
    ax1.set_ylabel('Cell Width (m)')
    ax1.set_title('Grid Refinement - X Direction')
    ax1.grid(True, alpha=0.3)
    
    # Add basin boundary lines
    basin_cols = grid_info['basin_cols']
    if basin_cols[0] < len(x_centers):
        ax1.axvline(x=x_centers[basin_cols[0]], color='red', linestyle='--', label='Basin Boundary')
    if basin_cols[1] <= len(x_centers):
        ax1.axvline(x=x_centers[basin_cols[1]-1], color='red', linestyle='--')
    ax1.legend()
    
    # Plot 2: Grid cell sizes in Y direction
    ax2 = axes[0, 1]
    y_centers = np.cumsum(grid_info['delc']) - grid_info['delc']/2
    ax2.bar(y_centers, grid_info['delc'], width=grid_info['delc'], alpha=0.7, edgecolor='black')
    ax2.set_xlabel('Y Position (m)')
    ax2.set_ylabel('Cell Height (m)')
    ax2.set_title('Grid Refinement - Y Direction')
    ax2.grid(True, alpha=0.3)
    
    # Add basin boundary lines
    basin_rows = grid_info['basin_rows']
    if basin_rows[0] < len(y_centers):
        ax2.axvline(x=y_centers[basin_rows[0]], color='red', linestyle='--', label='Basin Boundary')
    if basin_rows[1] <= len(y_centers):
        ax2.axvline(x=y_centers[basin_rows[1]-1], color='red', linestyle='--')
    ax2.legend()
    
    # Plot 3: 2D Grid overview
    ax3 = axes[1, 0]
    
    # Create grid lines
    x_lines = np.cumsum(np.concatenate([[0], grid_info['delr']]))
    y_lines = np.cumsum(np.concatenate([[0], grid_info['delc']]))
    
    # Plot vertical lines
    for x in x_lines[::max(1, len(x_lines)//20)]:  # Subsample for clarity
        ax3.axvline(x=x, color='gray', alpha=0.5, linewidth=0.5)
    
    # Plot horizontal lines
    for y in y_lines[::max(1, len(y_lines)//20)]:  # Subsample for clarity
        ax3.axhline(y=y, color='gray', alpha=0.5, linewidth=0.5)
    
    # Highlight basin area
    basin_x_min = x_lines[basin_cols[0]]
    basin_x_max = x_lines[basin_cols[1]]
    basin_y_min = y_lines[basin_rows[0]]
    basin_y_max = y_lines[basin_rows[1]]
    
    ax3.add_patch(plt.Rectangle(
        (basin_x_min, basin_y_min), 
        basin_x_max - basin_x_min, 
        basin_y_max - basin_y_min,
        fill=True, alpha=0.3, color='blue', label='Basin Area'
    ))
    
    ax3.set_xlabel('X Position (m)')
    ax3.set_ylabel('Y Position (m)')
    ax3.set_title('2D Grid Overview')
    ax3.legend()
    ax3.set_aspect('equal')
    
    # Plot 4: Grid statistics
    ax4 = axes[1, 1]
    
    # Calculate statistics
    total_cells = grid_info['total_cells']
    basin_cells = grid_info['basin_cells']
    min_cell = min(np.min(grid_info['delr']), np.min(grid_info['delc']))
    max_cell = max(np.max(grid_info['delr']), np.max(grid_info['delc']))
    avg_cell = (np.mean(grid_info['delr']) + np.mean(grid_info['delc'])) / 2
    
    stats_text = f"""Grid Statistics:
    
    Total Cells: {total_cells:,}
    Basin Cells: {basin_cells:,}
    
    Cell Size Range:
    Min: {min_cell:.1f}m
    Max: {max_cell:.1f}m
    Avg: {avg_cell:.1f}m
    
    Refinement Zones: {grid_info['refinement_zones']}
    
    Distance to Boundaries:
    X: {grid_info['distance_to_boundary_x']:.1f}m
    Y: {grid_info['distance_to_boundary_y']:.1f}m
    
    Domain Size:
    {grid_info['domain_length']:.1f}m × {grid_info['domain_width']:.1f}m
    """
    
    ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, 
             verticalalignment='top', fontsize=10, fontfamily='monospace')
    ax4.set_xlim(0, 1)
    ax4.set_ylim(0, 1)
    ax4.axis('off')
    ax4.set_title('Grid Statistics')
    
    plt.suptitle(f'Grid Refinement Analysis - {grid_info["refinement_zones"]} Zones', fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    if save_plot:
        plot_file = plot_dir / f"grid_refinement_{grid_info['refinement_zones']}_zones.png"
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"   💾 Grid plot saved: {plot_file}")
    
    plt.show()
    
    return fig

def optimize_grid_for_simulation(basin_info, target_cells=50000, min_refinement=2, max_refinement=4):
    """
    Optimize grid configuration for computational efficiency
    
    Parameters:
    -----------
    basin_info : dict
        Basin configuration parameters
    target_cells : int
        Target number of grid cells
    min_refinement : int
        Minimum number of refinement zones
    max_refinement : int
        Maximum number of refinement zones
    
    Returns:
    --------
    optimal_config : dict
        Optimal grid configuration
    """
    
    print(f"\n🎯 Optimizing grid configuration...")
    print(f"   🎪 Target cells: {target_cells:,}")
    print(f"   🔍 Refinement range: {min_refinement}-{max_refinement} zones")
    
    basin_length = basin_info.get('length', 30.0)
    basin_width = basin_info.get('width', 10.0)
    
    best_config = None
    best_score = float('inf')
    
    # Test different configurations
    for zones in range(min_refinement, max_refinement + 1):
        for min_size in [0.5, 1.0, 1.5, 2.0]:
            for max_size in [10.0, 15.0, 20.0, 25.0]:
                for domain_factor in [8, 10, 12]:
                    
                    try:
                        grid_info = create_adaptive_refined_grid(
                            basin_length, basin_width, domain_factor,
                            zones, min_size, max_size
                        )
                        
                        total_cells = grid_info['total_cells']
                        
                        # Calculate score (prefer close to target)
                        cell_score = abs(total_cells - target_cells) / target_cells
                        
                        # Penalize extreme values
                        size_ratio = max_size / min_size
                        if size_ratio > 50:  # Too extreme
                            cell_score += 0.5
                        
                        # Bonus for more refinement zones (better accuracy)
                        zone_bonus = -0.1 * zones
                        
                        total_score = cell_score + zone_bonus
                        
                        if total_score < best_score:
                            best_score = total_score
                            best_config = {
                                'grid_info': grid_info,
                                'zones': zones,
                                'min_cell_size': min_size,
                                'max_cell_size': max_size,
                                'domain_factor': domain_factor,
                                'total_cells': total_cells,
                                'score': total_score
                            }
                        
                        print(f"   🧪 Test: {zones}z, {min_size}-{max_size}m, ×{domain_factor} → {total_cells:,} cells (score: {total_score:.3f})")
                    
                    except Exception as e:
                        continue
    
    if best_config:
        print(f"\n   ✅ Optimal configuration found:")
        print(f"      🔍 Refinement zones: {best_config['zones']}")
        print(f"      📏 Cell size: {best_config['min_cell_size']}-{best_config['max_cell_size']}m")
        print(f"      🌐 Domain factor: {best_config['domain_factor']}")
        print(f"      🎪 Total cells: {best_config['total_cells']:,}")
        print(f"      📊 Score: {best_config['score']:.3f}")
    
    return best_config


if __name__ == "__main__":
    # Example usage
    print("="*60)
    print("GRID BUILDER UTILITIES - BASIN INFILTRATION MODELING")
    print("="*60)
    
    # Test with sample basin
    basin_info = {
        'length': 30.0,
        'width': 10.0,
        'depth': 2.0
    }
    
    # Create adaptive grid
    grid_info = create_adaptive_refined_grid(
        basin_info['length'], 
        basin_info['width'], 
        refinement_zones=3,
        min_cell_size=1.0,
        max_cell_size=15.0
    )
    
    # Visualize grid
    visualize_grid_refinement(grid_info)
    
    # Optimize grid
    optimal = optimize_grid_for_simulation(basin_info, target_cells=30000)
    
    print("\n🎯 Grid builder utilities ready!")
