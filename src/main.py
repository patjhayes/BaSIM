import os
import sys
import numpy as np
import flopy
import matplotlib.pyplot as plt
import re

def select_ts1_file():
    """Select a TS1 file from numbered list"""
    ts1_dir = r"C:\Users\patri\OneDrive\BaSIM\External\OUTPUT"
    
    if not os.path.exists(ts1_dir):
        print(f"Error: TS1 directory not found: {ts1_dir}")
        return None
    
    # Get all .ts1 files
    ts1_files = [f for f in os.listdir(ts1_dir) if f.endswith('.ts1')]
    
    if not ts1_files:
        print("No TS1 files found in the directory.")
        return None
    
    print(f"\nAvailable TS1 files in {ts1_dir}:")
    for i, filename in enumerate(ts1_files, 1):
        print(f"{i:2d}. {filename}")
    
    while True:
        try:
            choice = int(input(f"\nEnter the number of the TS1 file to use (1-{len(ts1_files)}): "))
            if 1 <= choice <= len(ts1_files):
                selected_file = os.path.join(ts1_dir, ts1_files[choice-1])
                print(f"\nParsing {ts1_files[choice-1]}...")
                return selected_file
            else:
                print(f"Please enter a number between 1 and {len(ts1_files)}")
        except ValueError:
            print("Please enter a valid number")

def parse_ts1_file(filepath):
    """Parse TS1 file - TS1 format with time in minutes, flow data"""
    try:
        print(f"Reading file: {filepath}")
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        # Remove any empty lines and strip whitespace
        lines = [line.strip() for line in lines if line.strip()]
        
        if not lines:
            raise ValueError("File is empty or contains no valid data")
        
        time_data = []
        flow_data = []
        
        # Skip header lines and parse data
        for i, line in enumerate(lines):
            # Skip comment lines or headers
            if line.startswith('#') or line.startswith('!') or not line:
                continue
                
            # Try to parse as data
            try:
                parts = re.split(r'[,\s]+', line)
                if len(parts) >= 2:
                    time_val = float(parts[0])  # Time in minutes
                    flow_val = float(parts[1])  # Flow in m³/s or L/s
                    
                    # Convert minutes to days for MODFLOW
                    time_days = time_val / (24 * 60)
                    
                    # Ensure flow is in m³/s (assume input is already correct units)
                    flow_m3s = flow_val
                    
                    time_data.append(time_days)
                    flow_data.append(flow_m3s)
                    
            except (ValueError, IndexError) as e:
                print(f"Skipping line {i+1}: {line} (Error: {e})")
                continue
        
        if not time_data:
            raise ValueError("No valid time-flow data found in file")
        
        # Convert to numpy arrays and sort by time
        time_array = np.array(time_data)
        flow_array = np.array(flow_data)
        
        # Sort by time
        sort_indices = np.argsort(time_array)
        time_array = time_array[sort_indices]
        flow_array = flow_array[sort_indices]
        
        # Combine into time series format for MODFLOW
        ts_data = np.column_stack((time_array, flow_array))
        
        print(f"Successfully parsed {len(ts_data)} data points")
        print(f"Found {len(time_data)} time steps")
        print(f"Duration: {max(time_data) * 24:.2f} hours")
        print(f"Peak flow: {max(flow_data):.3f} m³/s")
        
        return ts_data
        
    except Exception as e:
        print(f"Error parsing TS1 file: {e}")
        print("Please check that the file exists and contains valid time-flow data.")
        return None

def build_model(basin_length, basin_width, basin_depth, gw_clearance, hk, sy, ts1_data):
    """Build and run the MODFLOW 6 model with LAK package"""
    
    # Model setup
    model_name = "basin_model"
    model_ws = r"C:\Users\patri\OneDrive\BaSIM\model_output"
    
    # Ensure output directory exists
    os.makedirs(model_ws, exist_ok=True)
    
    # Convert hydraulic conductivity from m/day to m/s for MODFLOW
    hk_ms = hk / 86400  # Convert m/day to m/s
    
    # Define model domain - adaptive sizing based on basin
    buffer_factor = 5  # Buffer around basin
    domain_length = basin_length * buffer_factor
    domain_width = basin_width * buffer_factor
    
    # Grid discretization - finer near basin
    delr = min(5.0, basin_width / 5)  # 5m max, or basin_width/5 if smaller
    delc = min(5.0, basin_length / 5)  # 5m max, or basin_length/5 if smaller
    
    nrow = int(domain_width / delc)
    ncol = int(domain_length / delr)
    nlay = 3
    
    # Ensure minimum grid size
    nrow = max(nrow, 20)
    ncol = max(ncol, 20)
    
    print(f"Grid dimensions: {nlay} layers, {nrow} rows, {ncol} columns")
    print(f"Cell size: {delr}m x {delc}m")
    
    # Model layers
    top = np.ones((nrow, ncol)) * 10.0  # Ground surface at 10m
    botm = np.ones((nlay, nrow, ncol))
    botm[0] = top - 5.0  # Layer 1: 0-5m depth
    botm[1] = top - 15.0  # Layer 2: 5-15m depth  
    botm[2] = top - 30.0  # Layer 3: 15-30m depth
    
    print(f"Top array shape: {top.shape}")
    print(f"Botm array shape: {botm.shape}")
    
    # Lake bottom elevation
    lake_bottom = top[0, 0] - basin_depth
    
    # Time discretization based on TS1 data
    total_time = float(ts1_data[-1, 0])  # Last time point in days
    nper = len(ts1_data) - 1  # Number of stress periods
    
    # Create period data
    perlen = []
    for i in range(nper):
        if i == 0:
            perlen.append(ts1_data[1, 0] - ts1_data[0, 0])
        else:
            perlen.append(ts1_data[i+1, 0] - ts1_data[i, 0])
    
    nstp = [1] * nper  # One time step per period
    tsmult = [1.0] * nper
    
    # Create simulation
    sim = flopy.mf6.MFSimulation(
        sim_name=model_name, 
        version="mf6", 
        exe_name=r"C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe",
        sim_ws=model_ws
    )
    
    # Create TDIS package
    tdis = flopy.mf6.ModflowTdis(
        sim, 
        nper=nper, 
        perioddata=list(zip(perlen, nstp, tsmult))
    )
    
    # Create IMS package
    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    
    # Create GWF model
    gwf = flopy.mf6.ModflowGwf(sim, modelname=model_name, save_flows=True)
    
    # Create DIS package
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=nlay, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top,
        botm=botm
    )
    
    # Create IC package - initial water table
    initial_head = np.ones((nlay, nrow, ncol)) * (top - gw_clearance - 2)  # Water table 2m below clearance
    ic = flopy.mf6.ModflowGwfic(gwf, strt=initial_head)
    
    # Create NPF package
    npf = flopy.mf6.ModflowGwfnpf(
        gwf, 
        icelltype=1,  # All layers convertible
        k=hk_ms,      # Horizontal hydraulic conductivity
        k33=hk_ms/10  # Vertical hydraulic conductivity (typically lower)
    )
    
    # Create STO package
    sto = flopy.mf6.ModflowGwfsto(
        gwf, 
        iconvert=1,
        ss=1e-5, 
        sy=sy, 
        transient={0: True}
    )
    
    # Create constant head boundaries only on outer edges
    chd_spd = []
    head_value = initial_head[0, 0, 0]  # Use the initial head value
    for layer in range(nlay):
        for row in range(nrow):
            chd_spd.append(((layer, row, 0), head_value))
            chd_spd.append(((layer, row, ncol-1), head_value))
        for col in range(1, ncol-1):  # Avoid duplicates at corners
            chd_spd.append(((layer, 0, col), head_value))
            chd_spd.append(((layer, nrow-1, col), head_value))
    
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)
    
    # Calculate basin location (centered)
    basin_center_row = nrow // 2
    basin_center_col = ncol // 2
    basin_rows = int(basin_length / delr)
    basin_cols = int(basin_width / delc)
    
    row_start = max(1, basin_center_row - basin_rows // 2)
    row_end = min(nrow - 1, row_start + basin_rows)
    col_start = max(1, basin_center_col - basin_cols // 2)
    col_end = min(ncol - 1, col_start + basin_cols)
    
    # Create LAK package - simplified approach
    nlakes = 1
    lake_id = 0  # Lake IDs start from 0 in flopy
    strt = lake_bottom  # Start with empty lake
    
    # Single lake connection at center of basin
    center_row = (row_start + row_end) // 2
    center_col = (col_start + col_end) // 2
    
    # Lake package data - (lakeno, strt, nlakeconn)
    packagedata = [(lake_id, strt, 1)]
    
    # Single lake connection - (lakeno, iconn, cellid, claktype, bedleak, belev, telev, connlen, connwidth)
    top_elev = float(top[center_row, center_col])
    connectiondata = [(lake_id, 0, (0, center_row, center_col), 'VERTICAL', 
                      'NONE', lake_bottom, top_elev, 1.0, 1.0)]
    
    print(f"Created lake connection at row {center_row}, col {center_col}")
    
    # Time series data for inflow
    ts_data = ts1_data.tolist()  # Convert numpy array to list for flopy
    
    # Write time series file separately with correct format
    ts_file = os.path.join(model_ws, 'inflow.ts')
    with open(ts_file, 'w') as f:
        f.write("BEGIN ATTRIBUTES\n")
        f.write("  NAMES inflow_rate\n")
        f.write("  METHODS LINEAR\n")
        f.write("END ATTRIBUTES\n")
        f.write("\n")
        f.write("BEGIN TIMESERIES\n")
        # Ensure time series starts at exactly 0.0
        first_time = ts_data[0, 0]
        for time, flow in ts_data:
            adjusted_time = time - first_time  # Start from 0.0
            f.write(f"  {adjusted_time:.6f}  {flow:.6f}\n")
        f.write("END TIMESERIES\n")
    
    # Create LAK package
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        print_stage=True,
        print_flows=True,
        stage_filerecord=f'{model_name}.lak.stage',
        budget_filerecord=f'{model_name}.lak.bud',
        nlakes=nlakes,
        packagedata=packagedata,
        connectiondata=connectiondata,
        perioddata={0: [(lake_id, 'INFLOW', 'inflow_rate')]},
        ts_filerecord='inflow.ts'
    )
    
    # Create OC package
    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{model_name}.bud",
        head_filerecord=f"{model_name}.hds",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "FIRST"), ("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    
    # Write and run the model
    sim.write_simulation()
    
    print("Running simulation...")
    success, buff = sim.run_simulation()
    
    if not success:
        print("Model run failed! Check the following:")
        print("1. Verify MODFLOW 6 executable path is correct")
        print("2. Check model_output folder for error messages")
        return None
    
    print("Model run completed successfully!")
    return sim, gwf

def plot_results(sim, gwf):
    """Plot model results"""
    try:
        # Get output file paths
        model_ws = sim.sim_ws
        
        # Load head data
        head_file = os.path.join(model_ws, "basin_model.hds")
        if os.path.exists(head_file):
            hds = flopy.utils.HeadFile(head_file)
            head = hds.get_data()
            
            # Plot head contours for top layer
            fig, ax = plt.subplots(figsize=(10, 8))
            modelmap = flopy.plot.PlotMapView(model=gwf, ax=ax)
            quadmesh = modelmap.plot_array(head[0], alpha=0.5)
            contours = modelmap.contour_array(head[0], levels=10, colors='black', linewidths=0.5)
            ax.clabel(contours, inline=True, fontsize=8)
            plt.colorbar(quadmesh, ax=ax, label="Head (m)")
            plt.title("Groundwater Head Distribution")
            plt.tight_layout()
            plt.show()
        
        # Load and plot lake stage data
        lake_stage_file = os.path.join(model_ws, "basin_model.lak.stage")
        if os.path.exists(lake_stage_file):
            stage_data = np.loadtxt(lake_stage_file, skiprows=1)
            if stage_data.ndim == 1:
                stage_data = stage_data.reshape(1, -1)
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(stage_data[:, 0], stage_data[:, 1], 'b-', linewidth=2, label='Lake Stage')
            ax.set_xlabel('Time (days)')
            ax.set_ylabel('Stage (m)')
            ax.set_title('Basin Water Level Over Time')
            ax.grid(True, alpha=0.3)
            ax.legend()
            plt.tight_layout()
            plt.show()
        
        print("Results plotted successfully!")
        
    except Exception as e:
        print(f"Error plotting results: {e}")
        print("Model completed but visualization failed.")

def main():
    """Main function to run the basin modeling tool"""
    print("Basin Infiltration Modeling Tool")
    print("================================")
    
    try:
        # Get basin parameters from user
        print("\nBasin length (m) [5-100]: ", end="")
        basin_length = float(input())
        
        print("Basin width (m) [5-100]: ", end="")
        basin_width = float(input())
        
        print("Basin depth (m) [0.5-5]: ", end="")
        basin_depth = float(input())
        
        print("Clearance to groundwater (m) [1-10]: ", end="")
        gw_clearance = float(input())
        
        print("Hydraulic conductivity (m/day) [0.01-10]: ", end="")
        hk = float(input())
        
        print("Specific yield [0.01-0.3]: ", end="")
        sy = float(input())
        
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
        
        # Select and parse TS1 file
        print("\nSelect TS1 file for basin inflow...")
        ts1_file = select_ts1_file()
        
        if ts1_file is None:
            print("No TS1 file selected. Exiting.")
            return
        
        ts1_data = parse_ts1_file(ts1_file)
        if ts1_data is None:
            print("Failed to parse TS1 file. Exiting.")
            return
        
        # Build and run model
        print("\nBuilding and running model...")
        result = build_model(basin_length, basin_width, basin_depth, 
                           gw_clearance, hk, sy, ts1_data)
        
        if result is None:
            print("Model run failed!")
            return
        
        sim, gwf = result
        
        # Plot results
        print("\nGenerating plots...")
        plot_results(sim, gwf)
        
        print("\nBasin modeling completed successfully!")
        print(f"Results saved to: {sim.sim_ws}")
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")
        print("Please check your inputs and try again.")

if __name__ == "__main__":
    main()
