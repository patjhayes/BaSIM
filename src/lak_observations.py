"""
LAK Observations Package for Basin Infiltration Modeling
========================================================

This module provides comprehensive observation capabilities for the LAK (Lake) package
in MODFLOW 6, specifically designed for infiltration basin monitoring and analysis.

Key Features:
- Lake stage monitoring
- Volume calculations
- Infiltration rate tracking  
- Water balance analysis
- Observation data export
- Visualization tools

Author: Basin Infiltration Simulator (BaSIM)
Date: August 2025
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import json
from datetime import datetime, timedelta
from pathlib import Path
import flopy

class LAKObservationManager:
    """
    Manages LAK package observations for infiltration basin modeling
    """
    
    def __init__(self, model_ws, model_name, basin_info=None):
        """
        Initialize LAK observation manager
        
        Parameters:
        -----------
        model_ws : str
            Model workspace directory
        model_name : str
            Name of the model
        basin_info : dict, optional
            Basin configuration information
        """
        self.model_ws = Path(model_ws)
        self.model_name = model_name
        self.basin_info = basin_info or {}
        
        # Output directories
        self.obs_dir = self.model_ws / "observations"
        self.obs_dir.mkdir(exist_ok=True)
        
        # Observation data storage
        self.observations = {}
        self.observation_types = [
            'stage',       # Lake water level
            'volume',      # Lake volume
            'seepage',     # Infiltration rate
            'inflow',      # Inflow rate
            'storage',     # Change in storage
        ]
        
        print(f"🔍 LAK Observation Manager initialized for {model_name}")
        print(f"   📂 Observation directory: {self.obs_dir}")
    
    def create_lak_observations(self, gwf, lake_cells, observation_frequency='daily'):
        """
        Create LAK observation package for MODFLOW 6
        
        Parameters:
        -----------
        gwf : flopy.mf6.ModflowGwf
            Groundwater flow model
        lake_cells : list
            List of (row, col) tuples for lake cells
        observation_frequency : str
            Frequency of observations ('daily', 'hourly', 'all')
        
        Returns:
        --------
        obs : flopy.mf6.ModflowUtlobs
            MODFLOW 6 observation package
        """
        
        print(f"\n🔬 Creating LAK observation package...")
        print(f"   📊 Observation frequency: {observation_frequency}")
        print(f"   🏞️ Monitoring {len(lake_cells)} lake cells")
        
        # Define observation data for MODFLOW 6 LAK package
        obs_data = []
        
        # 1. Lake Stage Observations  
        obs_data.append([
            'stage_obs',           # observation name
            'lak',                 # package name (lowercase)
            'stage',               # observation type
            1                      # lake number (1-based for MF6)
        ])
        
        # 2. Lake Volume Observations
        obs_data.append([
            'volume_obs',
            'lak',
            'volume', 
            1
        ])
        
        # 3. Lake Budget Observations
        obs_data.append([
            'budget_obs',
            'lak',
            'lak',                 # total lake budget
            1
        ])
        
        # Create observation package
        obs_file = f"{self.model_name}_lak.obs"
        
        try:
            obs = flopy.mf6.ModflowUtlobs(
                gwf,
                filename=obs_file,
                print_input=True,
                continuous=obs_data,
                digits=10,
                pname='obs_lak'
            )
            
            print(f"   ✅ LAK observation package created: {obs_file}")
            print(f"   📈 Tracking: {len(obs_data)} observation types")
            
            return obs
            
        except Exception as e:
            print(f"   ❌ Error creating LAK observations: {e}")
            return None
    
    def setup_observation_schedule(self, start_time, end_time, frequency='daily'):
        """
        Set up observation time schedule
        
        Parameters:
        -----------
        start_time : datetime
            Start time for observations
        end_time : datetime
            End time for observations
        frequency : str
            Observation frequency
        
        Returns:
        --------
        times : list
            List of observation times
        """
        
        if frequency == 'daily':
            delta = timedelta(days=1)
        elif frequency == 'hourly':
            delta = timedelta(hours=1)
        elif frequency == 'all':
            delta = timedelta(seconds=1)  # Every time step
        else:
            delta = timedelta(days=1)
        
        times = []
        current_time = start_time
        
        while current_time <= end_time:
            times.append(current_time)
            current_time += delta
        
        print(f"📅 Observation schedule: {len(times)} points from {start_time} to {end_time}")
        return times
    
    def load_observation_results(self):
        """
        Load LAK observation results from MODFLOW output
        
        Returns:
        --------
        results : dict
            Dictionary containing observation results
        """
        
        print(f"\n📊 Loading LAK observation results...")
        
        results = {}
        
        # Look for observation output files
        obs_file = self.model_ws / f"{self.model_name}_lak.obs.csv"
        
        if obs_file.exists():
            try:
                # Load observation data
                obs_data = pd.read_csv(obs_file)
                
                print(f"   ✅ Loaded observations from {obs_file}")
                print(f"   📈 Data points: {len(obs_data)}")
                print(f"   🏷️ Columns: {list(obs_data.columns)}")
                
                # Parse observation data
                for col in obs_data.columns:
                    if col.lower() != 'time' and col.lower() != 'totim':
                        results[col] = obs_data[col].values
                
                # Store time data
                if 'time' in obs_data.columns:
                    results['time'] = obs_data['time'].values
                elif 'totim' in obs_data.columns:
                    results['totim'] = obs_data['totim'].values
                
                self.observations = results
                
            except Exception as e:
                print(f"   ⚠️ Error loading observation file: {e}")
        
        else:
            # Try to load from LAK stage/budget files
            self._load_from_lak_files()
        
        return results
    
    def _load_from_lak_files(self):
        """
        Load LAK data from stage and budget files
        """
        
        print(f"   🔍 Searching for LAK stage/budget files...")
        
        # Look for stage file
        stage_files = list(self.model_ws.glob("*.lak.stg")) + list(self.model_ws.glob("*.lak.stage"))
        
        if stage_files:
            stage_file = stage_files[0]
            print(f"   📈 Found stage file: {stage_file}")
            
            try:
                # Load stage data
                stage_data = np.genfromtxt(stage_file, names=True)
                
                if len(stage_data) > 0:
                    self.observations['time'] = stage_data['time'] if 'time' in stage_data.dtype.names else np.arange(len(stage_data))
                    self.observations['stage'] = stage_data['stage'] if 'stage' in stage_data.dtype.names else stage_data['STAGE']
                    
                    print(f"   ✅ Loaded {len(stage_data)} stage observations")
                
            except Exception as e:
                print(f"   ⚠️ Error loading stage file: {e}")
        
        # Look for budget file
        budget_files = list(self.model_ws.glob("*.lak.bud"))
        
        if budget_files:
            budget_file = budget_files[0]
            print(f"   💰 Found budget file: {budget_file}")
            
            try:
                # Load budget data using flopy
                lak_bud = flopy.utils.CellBudgetFile(str(budget_file))
                
                # Get available records
                records = lak_bud.get_unique_record_names()
                print(f"   📊 Budget records: {records}")
                
                # Store budget data
                for record in records:
                    try:
                        data = lak_bud.get_data(text=record)
                        if data:
                            self.observations[f"budget_{record.lower()}"] = data
                    except:
                        continue
                
            except Exception as e:
                print(f"   ⚠️ Error loading budget file: {e}")
    
    def calculate_infiltration_metrics(self):
        """
        Calculate infiltration-specific metrics from observations
        
        Returns:
        --------
        metrics : dict
            Dictionary of calculated metrics
        """
        
        print(f"\n💧 Calculating infiltration metrics...")
        
        metrics = {}
        
        if 'stage' in self.observations and 'time' in self.observations:
            stages = self.observations['stage']
            times = self.observations['time']
            
            # Basic stage statistics
            metrics['max_stage'] = np.max(stages)
            metrics['min_stage'] = np.min(stages)
            metrics['stage_range'] = metrics['max_stage'] - metrics['min_stage']
            metrics['avg_stage'] = np.mean(stages)
            
            # Water depth in basin
            if 'basin_level' in self.basin_info:
                basin_floor = self.basin_info['basin_level']
                water_depths = stages - basin_floor
                water_depths = np.maximum(water_depths, 0)  # No negative depths
                
                metrics['max_depth'] = np.max(water_depths)
                metrics['avg_depth'] = np.mean(water_depths)
                metrics['volume_stored'] = water_depths * self.basin_info.get('basin_area', 300.0)
            
            # Stage change rates
            if len(stages) > 1:
                stage_changes = np.diff(stages)
                time_intervals = np.diff(times)
                
                if len(time_intervals) > 0 and np.all(time_intervals > 0):
                    stage_rates = stage_changes / time_intervals
                    
                    metrics['max_filling_rate'] = np.max(stage_rates)
                    metrics['max_draining_rate'] = np.min(stage_rates)
                    metrics['avg_stage_change_rate'] = np.mean(np.abs(stage_rates))
            
            # Infiltration performance
            if 'basin_area' in self.basin_info:
                basin_area = self.basin_info['basin_area']
                
                # Estimate infiltration rate from stage decline
                if len(stages) > 1:
                    # Find periods of stage decline (infiltration)
                    declining_mask = np.diff(stages) < 0
                    
                    if np.any(declining_mask):
                        decline_rates = -stage_changes[declining_mask] / time_intervals[declining_mask]
                        infiltration_rates = decline_rates * basin_area  # m³/s
                        
                        metrics['avg_infiltration_rate'] = np.mean(infiltration_rates)
                        metrics['max_infiltration_rate'] = np.max(infiltration_rates)
                        metrics['infiltration_rate_l_per_s'] = metrics['avg_infiltration_rate'] * 1000
            
            print(f"   ✅ Calculated {len(metrics)} infiltration metrics")
            
        else:
            print(f"   ⚠️ Insufficient data for metric calculation")
        
        return metrics
    
    def create_observation_plots(self, save_plots=True):
        """
        Create comprehensive observation plots
        
        Parameters:
        -----------
        save_plots : bool
            Whether to save plots to files
        
        Returns:
        --------
        fig : matplotlib.figure.Figure
            The created figure
        """
        
        print(f"\n📊 Creating observation plots...")
        
        if not self.observations:
            print(f"   ⚠️ No observation data available for plotting")
            return None
        
        # Determine number of subplots needed
        plot_count = 0
        if 'stage' in self.observations:
            plot_count += 1
        if 'volume' in self.observations:
            plot_count += 1
        if any('budget' in key for key in self.observations.keys()):
            plot_count += 1
        
        if plot_count == 0:
            print(f"   ⚠️ No plottable data found")
            return None
        
        # Create figure
        fig, axes = plt.subplots(plot_count, 1, figsize=(12, 4*plot_count))
        if plot_count == 1:
            axes = [axes]
        
        plot_idx = 0
        
        # Get time data
        times = self.observations.get('time', self.observations.get('totim', np.arange(len(list(self.observations.values())[0]))))
        
        # Convert time to hours if needed
        if np.max(times) > 1000:  # Assume seconds
            times = times / 3600
            time_label = 'Time (hours)'
        else:
            time_label = 'Time'
        
        # Plot 1: Lake Stage
        if 'stage' in self.observations:
            ax = axes[plot_idx]
            stages = self.observations['stage']
            
            ax.plot(times, stages, 'b-', linewidth=2, label='Lake Stage')
            
            # Add reference lines if basin info available
            if 'basin_level' in self.basin_info:
                ax.axhline(y=self.basin_info['basin_level'], color='brown', 
                          linestyle='--', label='Basin Floor', alpha=0.7)
            
            if 'gw_level' in self.basin_info:
                ax.axhline(y=self.basin_info['gw_level'], color='blue', 
                          linestyle='--', label='Groundwater', alpha=0.7)
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Elevation (m)')
            ax.set_title('Lake Stage Evolution')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plot_idx += 1
        
        # Plot 2: Lake Volume
        if 'volume' in self.observations:
            ax = axes[plot_idx]
            volumes = self.observations['volume']
            
            ax.plot(times, volumes, 'g-', linewidth=2, label='Lake Volume')
            ax.set_xlabel(time_label)
            ax.set_ylabel('Volume (m³)')
            ax.set_title('Lake Volume Changes')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plot_idx += 1
        
        # Plot 3: Budget Components
        budget_keys = [key for key in self.observations.keys() if 'budget' in key]
        if budget_keys:
            ax = axes[plot_idx]
            
            for key in budget_keys:
                data = self.observations[key]
                if isinstance(data, (list, np.ndarray)) and len(data) == len(times):
                    ax.plot(times, data, linewidth=2, label=key.replace('budget_', '').title())
            
            ax.set_xlabel(time_label)
            ax.set_ylabel('Flow Rate (m³/s)')
            ax.set_title('Lake Water Balance Components')
            ax.legend()
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_plots:
            plot_file = self.obs_dir / f"{self.model_name}_observations.png"
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            print(f"   💾 Plots saved to: {plot_file}")
        
        plt.show()
        
        return fig
    
    def export_observations(self, format='csv'):
        """
        Export observation data to file
        
        Parameters:
        -----------
        format : str
            Export format ('csv', 'json', 'excel')
        """
        
        print(f"\n💾 Exporting observations to {format.upper()}...")
        
        if not self.observations:
            print(f"   ⚠️ No observation data to export")
            return
        
        if format.lower() == 'csv':
            # Create DataFrame
            df_data = {}
            
            # Ensure all arrays have the same length
            max_length = max(len(v) if isinstance(v, (list, np.ndarray)) else 1 
                           for v in self.observations.values())
            
            for key, value in self.observations.items():
                if isinstance(value, (list, np.ndarray)):
                    if len(value) == max_length:
                        df_data[key] = value
                    else:
                        # Pad or truncate to match
                        if len(value) < max_length:
                            padded = np.full(max_length, np.nan)
                            padded[:len(value)] = value
                            df_data[key] = padded
                        else:
                            df_data[key] = value[:max_length]
                else:
                    df_data[key] = [value] * max_length
            
            df = pd.DataFrame(df_data)
            
            export_file = self.obs_dir / f"{self.model_name}_observations.csv"
            df.to_csv(export_file, index=False)
            
            print(f"   ✅ CSV exported: {export_file}")
            print(f"   📊 Rows: {len(df)}, Columns: {len(df.columns)}")
        
        elif format.lower() == 'json':
            # Convert numpy arrays to lists for JSON serialization
            export_data = {}
            for key, value in self.observations.items():
                if isinstance(value, np.ndarray):
                    export_data[key] = value.tolist()
                else:
                    export_data[key] = value
            
            export_file = self.obs_dir / f"{self.model_name}_observations.json"
            with open(export_file, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"   ✅ JSON exported: {export_file}")
        
        elif format.lower() == 'excel':
            df_data = {}
            max_length = max(len(v) if isinstance(v, (list, np.ndarray)) else 1 
                           for v in self.observations.values())
            
            for key, value in self.observations.items():
                if isinstance(value, (list, np.ndarray)):
                    if len(value) == max_length:
                        df_data[key] = value
                else:
                    df_data[key] = [value] * max_length
            
            df = pd.DataFrame(df_data)
            
            export_file = self.obs_dir / f"{self.model_name}_observations.xlsx"
            df.to_excel(export_file, index=False)
            
            print(f"   ✅ Excel exported: {export_file}")
    
    def generate_summary_report(self):
        """
        Generate a comprehensive summary report
        
        Returns:
        --------
        report : dict
            Summary report data
        """
        
        print(f"\n📋 Generating LAK observation summary report...")
        
        # Calculate metrics
        metrics = self.calculate_infiltration_metrics()
        
        # Create report
        report = {
            'model_name': self.model_name,
            'model_workspace': str(self.model_ws),
            'generation_time': datetime.now().isoformat(),
            'observation_summary': {
                'total_observations': len(self.observations),
                'observation_types': list(self.observations.keys()),
                'data_points': len(self.observations.get('time', []))
            },
            'basin_configuration': self.basin_info,
            'infiltration_metrics': metrics,
            'recommendations': self._generate_recommendations(metrics)
        }
        
        # Save report
        report_file = self.obs_dir / f"{self.model_name}_summary_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"   ✅ Summary report saved: {report_file}")
        
        return report
    
    def _generate_recommendations(self, metrics):
        """
        Generate recommendations based on observation analysis
        """
        
        recommendations = []
        
        if metrics:
            # Check infiltration performance
            if 'avg_infiltration_rate' in metrics:
                rate = metrics['avg_infiltration_rate']
                if rate < 1e-6:  # Very slow infiltration
                    recommendations.append("Consider increasing lakebed permeability or checking for clogging")
                elif rate > 1e-3:  # Very fast infiltration
                    recommendations.append("Infiltration rate is very high - verify lakebed properties")
            
            # Check water depth management
            if 'max_depth' in metrics:
                depth = metrics['max_depth']
                if depth > 2.0:  # Deep water
                    recommendations.append("Consider basin design modifications to reduce maximum depth")
                elif depth < 0.1:  # Very shallow
                    recommendations.append("Basin may not be retaining sufficient water")
            
            # Check stage variations
            if 'stage_range' in metrics:
                range_val = metrics['stage_range']
                if range_val > 1.0:  # Large variations
                    recommendations.append("Large stage variations detected - review inflow management")
        
        return recommendations


def create_basin_parameters_file():
    """
    Create a template basin parameters configuration file
    """
    
    params = {
        "basin_geometry": {
            "length": 30.0,
            "width": 10.0,
            "depth": 2.0,
            "floor_elevation": 5.0,
            "area": 300.0
        },
        "hydrogeology": {
            "groundwater_level": 3.0,
            "hydraulic_conductivity": 4.0,
            "specific_yield": 0.25,
            "lakebed_thickness": 0.5
        },
        "model_setup": {
            "domain_factor": 10,
            "grid_refinement": "three_zone",
            "layers": 8,
            "time_units": "seconds"
        },
        "observation_settings": {
            "frequency": "daily",
            "output_formats": ["csv", "json"],
            "create_plots": true,
            "track_water_balance": true
        }
    }
    
    params_file = Path("C:/Users/patri/OneDrive/BaSIM/data/input/basin_parameters.json")
    params_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(params_file, 'w') as f:
        json.dump(params, f, indent=2)
    
    print(f"📄 Basin parameters template created: {params_file}")
    return params_file


if __name__ == "__main__":
    # Example usage
    print("="*60)
    print("LAK OBSERVATIONS MODULE - BASIN INFILTRATION MODELING")
    print("="*60)
    
    # Create parameter file
    create_basin_parameters_file()
    
    # Example initialization
    model_ws = "C:/Users/patri/OneDrive/BaSIM/model_output/phase3"
    model_name = "basin_infiltration_lak"
    
    basin_info = {
        'basin_level': 5.0,
        'gw_level': 3.0,
        'basin_area': 300.0
    }
    
    # Initialize observation manager
    obs_manager = LAKObservationManager(model_ws, model_name, basin_info)
    
    print("\n🎯 LAK Observation Manager ready for Phase 3 implementation!")
    print("\nNext steps:")
    print("1. Integrate with main_phase3_lak.py")
    print("2. Configure observation schedule")
    print("3. Run model with observations")
    print("4. Analyze results and generate reports")
