"""
Visualization Utilities for Basin Infiltration Modeling
=======================================================

This module provides comprehensive visualization capabilities for the BaSIM project,
including 3D visualizations, time series analysis, and interactive plots.

Author: Basin Infiltration Simulator (BaSIM)
Date: August 2025
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from mpl_toolkits.mplot3d import Axes3D
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

# Try to import seaborn, but continue without it if not available
try:
    import os as _os
    # Make seaborn opt-in to avoid pulling heavy scipy at app startup.
    # Set BASIM_USE_SEABORN=1 to enable. Otherwise, stick to matplotlib only.
    if _os.getenv('BASIM_USE_SEABORN', '0').strip() in ('1', 'true', 'yes'):
        try:
            import seaborn as sns  # noqa: F401
            SEABORN_AVAILABLE = True
            try:
                plt.style.use('seaborn-v0_8')
            except OSError:
                try:
                    plt.style.use('seaborn')
                except OSError:
                    plt.style.use('default')
            try:
                sns.set_palette("husl")
            except Exception:
                pass
        except Exception:
            SEABORN_AVAILABLE = False
            plt.style.use('default')
    else:
        SEABORN_AVAILABLE = False
        plt.style.use('default')
except ImportError:
    SEABORN_AVAILABLE = False
    # Use matplotlib default style
    plt.style.use('default')
    print("   ⚠️ Seaborn not available, using matplotlib defaults")

class BasinVisualizationSuite:
    """
    Comprehensive visualization suite for basin infiltration modeling
    """
    
    def __init__(self, output_dir=None):
        """
        Initialize visualization suite
        
        Parameters:
        -----------
        output_dir : str, optional
            Directory to save plots
        """
        if output_dir is None:
            output_dir = "C:/Users/patri/OneDrive/BaSIM/model_output/phase3/observations"
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up color schemes
        self.colors = {
            'basin': '#2E86AB',
            'groundwater': '#A23B72', 
            'infiltration': '#F18F01',
            'stage': '#C73E1D',
            'volume': '#4CAF50',
            'grid': '#757575'
        }
        
        print(f"🎨 Visualization suite initialized")
        print(f"   📂 Output directory: {self.output_dir}")
    
    def plot_3d_basin_system(self, grid_info, basin_info, head_data=None, save_plot=True):
        """
        Create 3D visualization of basin system
        
        Parameters:
        -----------
        grid_info : dict
            Grid configuration information
        basin_info : dict
            Basin configuration information
        head_data : np.ndarray, optional
            3D head data for visualization
        save_plot : bool
            Whether to save the plot
        
        Returns:
        --------
        fig : matplotlib.figure.Figure
            The created figure
        """
        
        print(f"\n🏔️ Creating 3D basin system visualization...")
        
        fig = plt.figure(figsize=(16, 12))
        
        # Create 2x2 subplot layout with 3D plots
        ax1 = fig.add_subplot(221, projection='3d')
        ax2 = fig.add_subplot(222, projection='3d')
        ax3 = fig.add_subplot(223)
        ax4 = fig.add_subplot(224)
        
        # Extract grid information
        nrow, ncol = grid_info['nrow'], grid_info['ncol']
        delr, delc = grid_info['delr'], grid_info['delc']
        
        # Create coordinate arrays
        x = np.cumsum(np.concatenate([[0], delr]))
        y = np.cumsum(np.concatenate([[0], delc]))
        X, Y = np.meshgrid(x[:-1] + delr/2, y[:-1] + delc/2)
        
        # Get basin information
        basin_level = basin_info.get('basin_level', 5.0)
        gw_level = basin_info.get('gw_level', 3.0)
        basin_depth = basin_info.get('basin_depth', 2.0)
        
        # Create elevation surfaces
        ground_surface = np.ones_like(X) * (basin_level + basin_depth)
        basin_floor = np.ones_like(X) * basin_level
        gw_surface = np.ones_like(X) * gw_level
        
        # Identify basin cells
        basin_rows = grid_info['basin_rows']
        basin_cols = grid_info['basin_cols']
        
        # Create basin depression
        basin_mask = np.zeros_like(X, dtype=bool)
        basin_mask[basin_rows[0]:basin_rows[1], basin_cols[0]:basin_cols[1]] = True
        
        # Modify surface in basin area
        ground_surface[basin_mask] = basin_level
        
        # Plot 1: 3D Surface View
        ax1.plot_surface(X, Y, ground_surface, alpha=0.7, color=self.colors['basin'], label='Ground Surface')
        ax1.plot_surface(X, Y, gw_surface, alpha=0.4, color=self.colors['groundwater'], label='Groundwater')
        
        # Add basin outline
        basin_x = X[basin_mask]
        basin_y = Y[basin_mask]
        basin_z = ground_surface[basin_mask]
        ax1.scatter(basin_x, basin_y, basin_z, color=self.colors['infiltration'], s=20, alpha=0.6)
        
        ax1.set_xlabel('X (m)')
        ax1.set_ylabel('Y (m)')
        ax1.set_zlabel('Elevation (m)')
        ax1.set_title('3D Basin System Overview')
        
        # Plot 2: 3D Head Distribution (if available)
        if head_data is not None:
            # Use top layer heads
            head_surface = head_data[0, :, :] if head_data.ndim == 3 else head_data
            
            # Create head surface plot
            surf = ax2.plot_surface(X, Y, head_surface, cmap='viridis', alpha=0.8)
            
            # Add groundwater reference
            ax2.plot_surface(X, Y, gw_surface, alpha=0.3, color='blue')
            
            # Add colorbar
            fig.colorbar(surf, ax=ax2, shrink=0.5, aspect=10, label='Head (m)')
            
            ax2.set_xlabel('X (m)')
            ax2.set_ylabel('Y (m)')
            ax2.set_zlabel('Head (m)')
            ax2.set_title('3D Groundwater Head Distribution')
        else:
            # Plot grid structure instead
            self._plot_3d_grid_structure(ax2, X, Y, ground_surface, grid_info)
        
        # Plot 3: Plan view - Basin and Grid
        ax3.contourf(X, Y, ground_surface, levels=20, cmap='terrain', alpha=0.7)
        ax3.contour(X, Y, ground_surface, levels=10, colors='black', alpha=0.5, linewidths=0.5)
        
        # Highlight basin
        ax3.contour(X, Y, basin_mask.astype(float), levels=[0.5], colors='red', linewidths=3)
        ax3.fill(X[basin_mask], Y[basin_mask], alpha=0.3, color=self.colors['basin'])
        
        ax3.set_xlabel('X (m)')
        ax3.set_ylabel('Y (m)')
        ax3.set_title('Plan View - Basin Location')
        ax3.set_aspect('equal')
        
        # Plot 4: Cross-section view
        # Take a cross-section through basin center
        center_row = (basin_rows[0] + basin_rows[1]) // 2
        
        x_cross = x[:-1] + delr/2
        ground_cross = ground_surface[center_row, :]
        gw_cross = gw_surface[center_row, :]
        
        ax4.fill_between(x_cross, ground_cross, gw_cross, alpha=0.3, color=self.colors['basin'], label='Unsaturated Zone')
        ax4.fill_between(x_cross, gw_cross, gw_cross - 10, alpha=0.3, color=self.colors['groundwater'], label='Saturated Zone')
        ax4.plot(x_cross, ground_cross, 'k-', linewidth=2, label='Ground Surface')
        ax4.plot(x_cross, gw_cross, 'b--', linewidth=2, label='Groundwater Level')
        
        # Highlight basin section
        basin_x_cross = x_cross[basin_cols[0]:basin_cols[1]]
        basin_ground_cross = ground_cross[basin_cols[0]:basin_cols[1]]
        ax4.fill_between(basin_x_cross, basin_ground_cross, basin_ground_cross + 0.1, 
                        color=self.colors['infiltration'], alpha=0.7, label='Basin')
        
        ax4.set_xlabel('X (m)')
        ax4.set_ylabel('Elevation (m)')
        ax4.set_title('Cross-Section Through Basin Center')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        plt.suptitle('Basin Infiltration System - 3D Visualization', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save_plot:
            plot_file = self.output_dir / "basin_3d_system.png"
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            print(f"   💾 3D system plot saved: {plot_file}")
        
        plt.show()
        return fig
    
    def _plot_3d_grid_structure(self, ax, X, Y, Z, grid_info):
        """
        Plot 3D grid structure
        """
        # Subsample grid for clarity
        step = max(1, min(len(X)//20, len(X[0])//20))
        
        X_sub = X[::step, ::step]
        Y_sub = Y[::step, ::step]
        Z_sub = Z[::step, ::step]
        
        # Plot wireframe
        ax.plot_wireframe(X_sub, Y_sub, Z_sub, alpha=0.5, color=self.colors['grid'])
        
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_zlabel('Elevation (m)')
        ax.set_title('3D Grid Structure')
    
    def plot_time_series_analysis(self, observation_data, basin_info=None, save_plot=True):
        """
        Create comprehensive time series analysis plots
        
        Parameters:
        -----------
        observation_data : dict
            Dictionary containing time series data
        basin_info : dict, optional
            Basin configuration information
        save_plot : bool
            Whether to save the plot
        
        Returns:
        --------
        fig : matplotlib.figure.Figure
            The created figure
        """
        
        print(f"\n📈 Creating time series analysis...")
        
        # Determine number of available data types
        available_data = []
        if 'stage' in observation_data:
            available_data.append('stage')
        if 'volume' in observation_data:
            available_data.append('volume')
        if 'seepage' in observation_data or any('seepage' in key for key in observation_data.keys()):
            available_data.append('seepage')
        if any('budget' in key for key in observation_data.keys()):
            available_data.append('budget')
        
        n_plots = len(available_data)
        if n_plots == 0:
            print(f"   ⚠️ No time series data available")
            return None
        
        # Create figure
        fig, axes = plt.subplots(n_plots, 1, figsize=(14, 4*n_plots))
        if n_plots == 1:
            axes = [axes]
        
        # Get time data
        time_data = observation_data.get('time', observation_data.get('totim', None))
        if time_data is None:
            # Create dummy time data
            max_length = max(len(v) if isinstance(v, (list, np.ndarray)) else 1 
                           for v in observation_data.values())
            time_data = np.arange(max_length)
        
        # Convert time to hours if needed
        if np.max(time_data) > 1000:  # Assume seconds
            time_data = time_data / 3600
            time_label = 'Time (hours)'
        else:
            time_label = 'Time'
        
        plot_idx = 0
        
        # Plot 1: Stage evolution
        if 'stage' in available_data:
            ax = axes[plot_idx]
            stage_data = observation_data['stage']
            
            ax.plot(time_data, stage_data, color=self.colors['stage'], linewidth=2, label='Lake Stage')
            
            # Add reference lines
            if basin_info:
                if 'basin_level' in basin_info:
                    ax.axhline(y=basin_info['basin_level'], color='brown', 
                              linestyle='--', alpha=0.7, label='Basin Floor')
                if 'gw_level' in basin_info:
                    ax.axhline(y=basin_info['gw_level'], color='blue', 
                              linestyle='--', alpha=0.7, label='Groundwater Level')
                
                # Calculate and plot water depth
                if 'basin_level' in basin_info:
                    water_depth = np.maximum(stage_data - basin_info['basin_level'], 0)
                    ax_twin = ax.twinx()
                    ax_twin.fill_between(time_data, water_depth, alpha=0.3, 
                                       color=self.colors['basin'], label='Water Depth')
                    ax_twin.set_ylabel('Water Depth (m)', color=self.colors['basin'])
                    ax_twin.tick_params(axis='y', labelcolor=self.colors['basin'])
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Elevation (m)')
            ax.set_title('Lake Stage Evolution')
            ax.legend(loc='upper left')
            ax.grid(True, alpha=0.3)
            
            plot_idx += 1
        
        # Plot 2: Volume changes
        if 'volume' in available_data:
            ax = axes[plot_idx]
            volume_data = observation_data['volume']
            
            ax.plot(time_data, volume_data, color=self.colors['volume'], linewidth=2, label='Lake Volume')
            
            # Calculate volume change rate
            if len(volume_data) > 1:
                volume_changes = np.diff(volume_data)
                time_intervals = np.diff(time_data)
                change_rates = volume_changes / time_intervals
                
                ax_twin = ax.twinx()
                ax_twin.plot(time_data[1:], change_rates, color=self.colors['infiltration'], 
                           alpha=0.7, label='Volume Change Rate')
                ax_twin.set_ylabel('Volume Change Rate (m³/h)', color=self.colors['infiltration'])
                ax_twin.tick_params(axis='y', labelcolor=self.colors['infiltration'])
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Volume (m³)')
            ax.set_title('Lake Volume Changes')
            ax.legend(loc='upper left')
            ax.grid(True, alpha=0.3)
            
            plot_idx += 1
        
        # Plot 3: Seepage/Infiltration
        if 'seepage' in available_data:
            ax = axes[plot_idx]
            
            # Look for seepage data
            seepage_keys = [key for key in observation_data.keys() if 'seepage' in key.lower()]
            
            for key in seepage_keys:
                data = observation_data[key]
                if isinstance(data, (list, np.ndarray)) and len(data) == len(time_data):
                    ax.plot(time_data, data, linewidth=2, label=key.replace('_', ' ').title())
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Seepage Rate (m³/s)')
            ax.set_title('Infiltration/Seepage Rates')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plot_idx += 1
        
        # Plot 4: Budget components
        if 'budget' in available_data:
            ax = axes[plot_idx]
            
            budget_keys = [key for key in observation_data.keys() if 'budget' in key.lower()]
            
            for key in budget_keys:
                data = observation_data[key]
                if isinstance(data, (list, np.ndarray)) and len(data) == len(time_data):
                    ax.plot(time_data, data, linewidth=2, label=key.replace('budget_', '').replace('_', ' ').title())
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Flow Rate (m³/s)')
            ax.set_title('Water Balance Components')
            ax.legend()
            ax.grid(True, alpha=0.3)
        
        plt.suptitle('Basin Infiltration - Time Series Analysis', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save_plot:
            plot_file = self.output_dir / "time_series_analysis.png"
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            print(f"   💾 Time series plot saved: {plot_file}")
        
        plt.show()
        return fig
    
    def create_performance_dashboard(self, metrics, observation_data, save_plot=True):
        """
        Create a performance dashboard with key metrics
        
        Parameters:
        -----------
        metrics : dict
            Performance metrics
        observation_data : dict
            Observation data
        save_plot : bool
            Whether to save the plot
        
        Returns:
        --------
        fig : matplotlib.figure.Figure
            The created figure
        """
        
        print(f"\n📊 Creating performance dashboard...")
        
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        # Metric 1: Stage statistics
        ax = axes[0, 0]
        if 'stage' in observation_data:
            stage_data = observation_data['stage']
            
            # Create box plot
            ax.boxplot(stage_data, patch_artist=True, 
                      boxprops=dict(facecolor=self.colors['stage'], alpha=0.7))
            
            # Add statistics text
            stats_text = f"""Stage Statistics:
            Max: {np.max(stage_data):.2f}m
            Min: {np.min(stage_data):.2f}m
            Mean: {np.mean(stage_data):.2f}m
            Std: {np.std(stage_data):.2f}m"""
            
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, 
                   verticalalignment='top', fontsize=9, fontfamily='monospace',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        ax.set_ylabel('Stage (m)')
        ax.set_title('Stage Distribution')
        ax.grid(True, alpha=0.3)
        
        # Metric 2: Infiltration performance
        ax = axes[0, 1]
        if metrics and 'avg_infiltration_rate' in metrics:
            infilt_rate = metrics['avg_infiltration_rate'] * 1000  # Convert to L/s
            
            # Gauge-style plot
            theta = np.linspace(0, np.pi, 100)
            r = np.ones_like(theta)
            
            ax = plt.subplot(2, 3, 2, projection='polar')
            ax.plot(theta, r, 'k-', linewidth=3)
            ax.fill_between(theta, 0, r, alpha=0.1, color='gray')
            
            # Add infiltration rate indicator
            rate_angle = min(infilt_rate / 10.0 * np.pi, np.pi)  # Scale to 0-π
            ax.plot([rate_angle, rate_angle], [0, 1], color=self.colors['infiltration'], linewidth=5)
            
            ax.set_ylim(0, 1.2)
            ax.set_title(f'Infiltration Rate\n{infilt_rate:.1f} L/s', pad=20)
            ax.set_theta_zero_location('W')
            ax.set_theta_direction(1)
            ax.set_thetagrids([0, 45, 90, 135, 180], ['0', '2.5', '5', '7.5', '10+ L/s'])
        
        # Metric 3: Water depth evolution
        ax = axes[0, 2]
        if 'stage' in observation_data and metrics and 'basin_level' in metrics:
            time_data = observation_data.get('time', np.arange(len(observation_data['stage'])))
            if np.max(time_data) > 1000:
                time_data = time_data / 3600
            
            stage_data = observation_data['stage']
            water_depth = np.maximum(stage_data - metrics.get('basin_level', 5.0), 0)
            
            ax.fill_between(time_data, water_depth, alpha=0.5, color=self.colors['basin'])
            ax.plot(time_data, water_depth, color=self.colors['basin'], linewidth=2)
            
            ax.set_xlabel('Time (hours)')
            ax.set_ylabel('Water Depth (m)')
            ax.set_title('Water Depth Evolution')
            ax.grid(True, alpha=0.3)
        
        # Metric 4: Performance indicators
        ax = axes[1, 0]
        if metrics:
            # Create performance bars
            perf_metrics = {}
            if 'avg_infiltration_rate' in metrics:
                perf_metrics['Infiltration Rate'] = min(metrics['avg_infiltration_rate'] * 1000000, 100)  # μm/s, capped at 100
            if 'max_depth' in metrics:
                perf_metrics['Max Depth'] = min(metrics['max_depth'] * 50, 100)  # Scale to percentage
            if 'stage_range' in metrics:
                perf_metrics['Stage Variation'] = min(metrics['stage_range'] * 50, 100)  # Scale to percentage
            
            if perf_metrics:
                bars = ax.barh(list(perf_metrics.keys()), list(perf_metrics.values()), 
                              color=[self.colors['infiltration'], self.colors['volume'], self.colors['stage']])
                
                ax.set_xlim(0, 100)
                ax.set_xlabel('Performance Score')
                ax.set_title('Performance Indicators')
                
                # Add value labels
                for i, (bar, value) in enumerate(zip(bars, perf_metrics.values())):
                    ax.text(value + 2, i, f'{value:.1f}', va='center')
        
        # Metric 5: Volume efficiency
        ax = axes[1, 1]
        if 'volume' in observation_data:
            volume_data = observation_data['volume']
            
            # Calculate volume efficiency (storage vs. infiltration)
            if len(volume_data) > 1:
                total_inflow = max(volume_data) - min(volume_data)  # Approximate
                final_storage = volume_data[-1] - volume_data[0]
                infiltrated = total_inflow - final_storage
                
                if total_inflow > 0:
                    efficiency = (infiltrated / total_inflow) * 100
                    
                    # Pie chart
                    labels = ['Infiltrated', 'Stored']
                    sizes = [efficiency, 100 - efficiency]
                    colors = [self.colors['infiltration'], self.colors['volume']]
                    
                    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
                    ax.set_title('Volume Efficiency')
        
        # Metric 6: System summary
        ax = axes[1, 2]
        if metrics:
            summary_text = "System Performance Summary:\n\n"
            
            if 'avg_infiltration_rate' in metrics:
                rate_l_per_s = metrics['avg_infiltration_rate'] * 1000
                summary_text += f"Avg Infiltration: {rate_l_per_s:.2f} L/s\n"
            
            if 'max_depth' in metrics:
                summary_text += f"Max Water Depth: {metrics['max_depth']:.2f} m\n"
            
            if 'stage_range' in metrics:
                summary_text += f"Stage Variation: {metrics['stage_range']:.2f} m\n"
            
            if 'avg_stage' in metrics:
                summary_text += f"Avg Stage: {metrics['avg_stage']:.2f} m\n"
            
            # Add recommendations
            summary_text += "\nRecommendations:\n"
            if 'avg_infiltration_rate' in metrics:
                if metrics['avg_infiltration_rate'] < 1e-6:
                    summary_text += "• Consider improving lakebed permeability\n"
                elif metrics['avg_infiltration_rate'] > 1e-3:
                    summary_text += "• High infiltration - verify design\n"
                else:
                    summary_text += "• Infiltration rate is optimal\n"
            
            ax.text(0.05, 0.95, summary_text, transform=ax.transAxes, 
                   verticalalignment='top', fontsize=10, fontfamily='monospace',
                   bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.8))
        
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.set_title('Performance Summary')
        
        plt.suptitle('Basin Infiltration - Performance Dashboard', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save_plot:
            plot_file = self.output_dir / "performance_dashboard.png"
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            print(f"   💾 Dashboard saved: {plot_file}")
        
        plt.show()
        return fig
    
    def create_animation(self, time_series_data, basin_info, save_animation=True):
        """
        Create animated visualization of basin evolution
        
        Parameters:
        -----------
        time_series_data : dict
            Time series data for animation
        basin_info : dict
            Basin configuration
        save_animation : bool
            Whether to save animation as GIF
        
        Returns:
        --------
        ani : matplotlib.animation.FuncAnimation
            The created animation
        """
        
        print(f"\n🎬 Creating basin evolution animation...")
        
        if 'stage' not in time_series_data:
            print(f"   ⚠️ Stage data required for animation")
            return None
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        stage_data = time_series_data['stage']
        time_data = time_series_data.get('time', np.arange(len(stage_data)))
        
        if np.max(time_data) > 1000:
            time_data = time_data / 3600
            time_label = 'hours'
        else:
            time_label = 'time units'
        
        # Set up basin geometry for animation
        basin_length = basin_info.get('length', 30.0)
        basin_width = basin_info.get('width', 10.0)
        basin_level = basin_info.get('basin_level', 5.0)
        
        x = np.linspace(0, basin_length, 50)
        y = np.linspace(0, basin_width, 20)
        X, Y = np.meshgrid(x, y)
        
        def animate(frame):
            ax1.clear()
            ax2.clear()
            
            current_stage = stage_data[frame]
            current_time = time_data[frame]
            
            # Plot 1: 3D basin view
            ax1 = fig.add_subplot(121, projection='3d')
            
            # Basin floor
            Z_floor = np.ones_like(X) * basin_level
            ax1.plot_surface(X, Y, Z_floor, alpha=0.3, color='brown')
            
            # Water surface (if above basin floor)
            if current_stage > basin_level:
                Z_water = np.ones_like(X) * current_stage
                ax1.plot_surface(X, Y, Z_water, alpha=0.6, color='blue')
            
            ax1.set_xlabel('X (m)')
            ax1.set_ylabel('Y (m)')
            ax1.set_zlabel('Elevation (m)')
            ax1.set_title(f'Basin at t = {current_time:.1f} {time_label}')
            ax1.set_zlim(basin_level - 0.5, basin_level + 2)
            
            # Plot 2: Time series with current position
            ax2.plot(time_data[:frame+1], stage_data[:frame+1], 'b-', linewidth=2)
            ax2.plot(time_data[frame], stage_data[frame], 'ro', markersize=8)
            ax2.axhline(y=basin_level, color='brown', linestyle='--', alpha=0.7, label='Basin Floor')
            
            ax2.set_xlabel(f'Time ({time_label})')
            ax2.set_ylabel('Stage (m)')
            ax2.set_title('Stage Evolution')
            ax2.grid(True, alpha=0.3)
            ax2.legend()
            ax2.set_xlim(time_data[0], time_data[-1])
            ax2.set_ylim(min(stage_data) - 0.1, max(stage_data) + 0.1)
        
        # Create animation
        ani = animation.FuncAnimation(fig, animate, frames=len(stage_data), 
                                    interval=200, blit=False, repeat=True)
        
        if save_animation:
            ani_file = self.output_dir / "basin_evolution.gif"
            ani.save(str(ani_file), writer='pillow', fps=5)
            print(f"   💾 Animation saved: {ani_file}")
        
        plt.show()
        return ani


def create_comprehensive_report_plots(observation_data, metrics, basin_info, output_dir=None):
    """
    Create a comprehensive set of plots for reporting
    
    Parameters:
    -----------
    observation_data : dict
        Observation data
    metrics : dict
        Performance metrics
    basin_info : dict
        Basin configuration
    output_dir : str, optional
        Output directory for plots
    
    Returns:
    --------
    plot_files : list
        List of created plot files
    """
    
    print(f"\n📊 Creating comprehensive report plots...")
    
    if output_dir is None:
        output_dir = "C:/Users/patri/OneDrive/BaSIM/model_output/phase3/observations"
    
    viz = BasinVisualizationSuite(output_dir)
    plot_files = []
    
    # Create all visualization types
    try:
        # Time series analysis
        fig1 = viz.plot_time_series_analysis(observation_data, basin_info, save_plot=True)
        if fig1:
            plot_files.append(viz.output_dir / "time_series_analysis.png")
        
        # Performance dashboard
        fig2 = viz.create_performance_dashboard(metrics, observation_data, save_plot=True)
        if fig2:
            plot_files.append(viz.output_dir / "performance_dashboard.png")
        
        print(f"   ✅ Created {len(plot_files)} comprehensive plots")
        
    except Exception as e:
        print(f"   ⚠️ Error creating plots: {e}")
    
    return plot_files


if __name__ == "__main__":
    # Example usage
    print("="*60)
    print("VISUALIZATION UTILITIES - BASIN INFILTRATION MODELING")
    print("="*60)
    
    # Initialize visualization suite
    viz = BasinVisualizationSuite()
    
    # Create sample data for testing
    time_data = np.linspace(0, 24, 100)  # 24 hours
    stage_data = 5.0 + 0.5 * np.sin(2 * np.pi * time_data / 12) + 0.1 * np.random.randn(100)
    volume_data = (stage_data - 5.0) * 300  # Approximate volume
    
    observation_data = {
        'time': time_data,
        'stage': stage_data,
        'volume': volume_data
    }
    
    basin_info = {
        'basin_level': 5.0,
        'gw_level': 3.0,
        'length': 30.0,
        'width': 10.0
    }
    
    metrics = {
        'avg_infiltration_rate': 1e-5,
        'max_depth': 0.8,
        'stage_range': 1.2,
        'avg_stage': 5.3
    }
    
    # Create visualizations
    viz.plot_time_series_analysis(observation_data, basin_info)
    viz.create_performance_dashboard(metrics, observation_data)
    
    print("\n🎨 Visualization utilities ready!")
