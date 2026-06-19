"""
BaSIM v2.0 - MODFLOW-USG Backend Integration
Compliance Verification Mode: MODFLOW-USG + Gridgen
"""

import os
import sys
import numpy as np
import pandas as pd
from pathlib import Path
import json
import traceback
import tempfile
import shutil

import flopy
from flopy.utils.gridgen import Gridgen
from shapely.geometry import Polygon, LineString

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64

try:
    from src.utils.mf6_locator import find_mfusg_exe, find_gridgen_exe
except ImportError:
    from utils.mf6_locator import find_mfusg_exe, find_gridgen_exe

from src.utils.outlet_hydraulics import create_outlet_from_config, apply_outlet_to_results, _geom_stage_to_storage_fn

def run_simulation(ts1_path: str, config: dict):
    """
    Main entry point for BaSIM v2.0 simulation.
    Builds and runs the MODFLOW-USG Compliance Mode simulation.
    
    Args:
        ts1_path (str): Path to the .ts1 hydrograph file.
        config (dict): The basin and aquifer parameters from the UI.
    """
    # 1. Parse Config
    scenario_title = config.get("scenario_title", "Scenario 1")
    basin_cfg = config.get("basin_geometry", {})
    aquifer = config.get("aquifer", {})
    
    basin_length = float(basin_cfg.get("length_floor", 50.0))
    basin_width = float(basin_cfg.get("width_floor", 50.0))
    max_depth = float(basin_cfg.get("max_depth", 2.0))
    floor_elev = float(basin_cfg.get("floor_elev", 5.0))
    
    k_horiz = float(aquifer.get("k_horizontal_mpd", 20.0))
    k_vert = float(aquifer.get("k_vertical_mpd", k_horiz))
    sy = float(aquifer.get("sy", 0.05))
    ss = float(aquifer.get("ss", 1e-4))
    initial_head = float(aquifer.get("initial_head", 1.0))
    aq_bottom = float(aquifer.get("aquifer_bottom", -20.0))
    
    # 2. Setup Output Directory
    if config.get("output_dir"):
        base_out = Path(config["output_dir"])
    else:
        base_out = Path.home() / '.basim_workspace' / 'model_output' / 'usg_scenarios'
    
    base_out.mkdir(parents=True, exist_ok=True)
    ts1_name = Path(ts1_path).stem if ts1_path else config.get("run_name", "synthetic")
    import re
    ts1_name = re.sub(r'[^A-Za-z0-9_\-\.]', '_', ts1_name)
    sim_id = config.get("sim_id")
    if sim_id:
        ts1_name = f"{ts1_name}_{sim_id[:8]}"
    model_dir = base_out / scenario_title / ts1_name
    model_dir.mkdir(parents=True, exist_ok=True)

    # 3. Parse Hydrograph (.ts1) or generate via ILSAX
    catchment_cfg = config.get("catchment", {})
    rainfall_cfg = config.get("rainfall", {})
    
    if not ts1_path and catchment_cfg and rainfall_cfg:
        from src.hydrology.common import Catchment, Hyetograph
        from src.hydrology.ilsax import simulate_catchment_runoff
        
        c = Catchment(
            name=catchment_cfg.get("name", "Catchment 1"),
            area_ha=float(catchment_cfg.get("area_ha", 1.0)),
            slope=float(catchment_cfg.get("slope", 1.0)),
            paved_fraction=float(catchment_cfg.get("paved_fraction", 0.0)),
            supplementary_fraction=float(catchment_cfg.get("supplementary_fraction", 0.0)),
            grassed_fraction=float(catchment_cfg.get("grassed_fraction", 0.0)),
            soil_type=float(catchment_cfg.get("soil_type", 2.0)),
            amc=float(catchment_cfg.get("amc", 3.0))
        )
        # Override optional path parameters if provided
        for key in ["paved_additional_time_minutes", "supplementary_additional_time_minutes", "grassed_additional_time_minutes",
                    "paved_flow_path_length_m", "supplementary_flow_path_length_m", "grassed_flow_path_length_m",
                    "paved_flow_path_slope_pct", "supplementary_flow_path_slope_pct", "grassed_flow_path_slope_pct",
                    "paved_n_star", "supplementary_n_star", "grassed_n_star",
                    "paved_depression_storage_mm", "supplementary_depression_storage_mm", "grassed_depression_storage_mm"]:
            if key in catchment_cfg:
                setattr(c, key, float(catchment_cfg[key]))
                
        timestep_min = float(rainfall_cfg.get("timestep_minutes", 5.0))
        depths = rainfall_cfg.get("depths_mm", [])
        hyeto = Hyetograph(timestep_minutes=timestep_min, depths_mm=depths)
        
        flows_m3s = simulate_catchment_runoff(c, hyeto)
        flows_m3s = np.array(flows_m3s)
        times_min = np.arange(1, len(flows_m3s) + 1) * timestep_min
        times_days = times_min / (24.0 * 60.0)
    else:
        def parse_ts1_file(filepath):
            header_line = 0
            with open(filepath, 'r') as f:
                for i, line in enumerate(f):
                    if line.startswith('Time (min)'):
                        header_line = i
                        break
            df = pd.read_csv(filepath, skiprows=header_line)
            time_min = df.iloc[:, 0].values
            flow_m3s = df.iloc[:, 1].values
            time_days = time_min / (24.0 * 60.0)
            return np.column_stack((time_days, flow_m3s))

        ts1_data = parse_ts1_file(ts1_path)
        times_days = ts1_data[:, 0]
        flows_m3s = ts1_data[:, 1]
    
    perlen = np.diff(times_days)
    perlen = np.append(perlen, perlen[-1] if len(perlen) > 0 else 1.0)
    
    post_days = float(config.get("post_storm_days", 2.0))
    post_step_h = float(config.get("post_storm_step_hours", 2.0))
    post_step_days = post_step_h / 24.0
    
    if post_days > 0 and post_step_days > 0:
        post_steps = max(1, int(np.ceil(post_days / post_step_days)))
        post_perlen = np.ones(post_steps) * post_step_days
        post_flows = np.zeros(post_steps)
        perlen = np.concatenate([perlen, post_perlen])
        flows_m3s = np.concatenate([flows_m3s, post_flows])
        
    nper = len(perlen)
    if len(flows_m3s) > 1:
        flows_m3day = ((flows_m3s[:-1] + flows_m3s[1:]) / 2.0) * 86400.0
        flows_m3day = np.append(flows_m3day, flows_m3s[-1] * 86400.0)
    else:
        flows_m3day = flows_m3s * 86400.0

    # Ensure length match
    if len(flows_m3day) > nper:
        flows_m3day = flows_m3day[:nper]
    elif len(flows_m3day) < nper:
        flows_m3day = np.pad(flows_m3day, (0, nper - len(flows_m3day)), 'edge')

    # 4. Gridgen setup
    model_name = "usg_basin"
    mfusg_exe = find_mfusg_exe()
    gridgen_exe = find_gridgen_exe()
    
    workspace = model_dir / "gridgen_ws"
    workspace.mkdir(parents=True, exist_ok=True)
    
    bed_thick = float(config["infiltration"].get("bed_thickness_m", 0.5))
    if bed_thick < 0.01:
        bed_thick = 0.5
    bed_k_raw = float(config["infiltration"]["bed_k_mpd"])
    if config["infiltration"].get("side_k_separate", False):
        side_k_raw = float(config["infiltration"].get("side_k_mpd", bed_k_raw))
    else:
        side_k_raw = bed_k_raw
        
    h_threshold_pct = float(config["infiltration"].get("h_threshold_pct", 1.0))
    h_threshold = max(0.05, max_depth * h_threshold_pct)
    
    # Estimate capillary suction head based on native aquifer K
    if k_horiz > 10.0:
        psi = 0.05  # Sand / Gravel
    elif k_horiz > 1.0:
        psi = 0.06  # Loamy Sand
    else:
        psi = 0.11  # Finer soils
        
    # Translate to MODFLOW's Effective K for upstream-weighting seepage
    bed_k = 0.5 * bed_k_raw * (1.0 + (bed_thick + psi) / h_threshold)
    side_k = 0.5 * side_k_raw * (1.0 + (bed_thick + psi) / h_threshold)
    
    mode = config["infiltration"].get("mode", "full")
    
    try:
        custom_coords = config.get("basin_geometry", {}).get("custom_polygon_coords")
        if custom_coords and len(custom_coords) >= 3:
            pts = np.array(custom_coords)
            min_x, max_x = np.min(pts[:, 0]), np.max(pts[:, 0])
            min_y, max_y = np.min(pts[:, 1]), np.max(pts[:, 1])
            basin_length = max_x - min_x
            basin_width = max_y - min_y
            
        # Use a coarse base grid and rely on Gridgen for nested refinement.
        # This keeps the total node count small for faster runtimes,
        # while still providing smooth contours via nested refinement buffers.
        max_dim = max(basin_length, basin_width)
        Lx = max_dim * 10
        Ly = max_dim * 10
        
        ncol = 25
        nrow = 25
        delr = Lx / ncol
        delc = Ly / nrow
        
        top_elev = floor_elev + max_depth
        clogged_bottom = floor_elev - bed_thick
        
        # Sub-layer the aquifer to prevent vertical throttling artifacts.
        # Instead of 1.0m uniform layers (which creates 100+ layers for deep aquifers),
        # use a maximum of 5 geometrically expanding layers to dramatically reduce node count.
        aq_thickness = clogged_bottom - aq_bottom
        n_aq_layers = min(5, max(1, int(np.ceil(aq_thickness / 2.0))))
        
        botm = [floor_elev, clogged_bottom]
        
        if n_aq_layers == 1:
            botm.append(aq_bottom)
        else:
            r = 1.5
            a = aq_thickness * (1 - r) / (1 - r**n_aq_layers)
            current_z = clogged_bottom
            for i in range(n_aq_layers):
                layer_thick = a * (r**i)
                current_z -= layer_thick
                botm.append(current_z)
                
        nlay = len(botm)
        
        sim_base = flopy.modflow.Modflow(modelname="base", model_ws=str(workspace))
        dis_base = flopy.modflow.ModflowDis(sim_base, nlay=nlay, nrow=nrow, ncol=ncol, delr=delr, delc=delc, top=top_elev, botm=botm)
        
        # Basin polygon
        x0, y0 = (Lx - basin_length) / 2, (Ly - basin_width) / 2
        eps = 0.001123
        custom_coords = config.get("basin_geometry", {}).get("custom_polygon_coords")
        
        if custom_coords and len(custom_coords) >= 3:
            # Re-center custom polygon to middle of domain
            pts = np.array(custom_coords)
            c_x = np.mean(pts[:, 0])
            c_y = np.mean(pts[:, 1])
            dx = (Lx / 2) - c_x
            dy = (Ly / 2) - c_y
            centered_pts = [(x + dx, y + dy) for x, y in custom_coords]
            basin_poly = Polygon(centered_pts)
        else:
            basin_poly = Polygon([
                (x0 + eps, y0 + eps), (x0 + basin_length - eps, y0 + eps), 
                (x0 + basin_length - eps, y0 + basin_width - eps), (x0 + eps, y0 + basin_width - eps)
            ])
            
        # Outer buffer (coarse transition)
        outer_buffer_dist = max_dim * 2
        outer_buffer_poly = Polygon([
            (x0 - outer_buffer_dist, y0 - outer_buffer_dist), 
            (x0 + basin_length + outer_buffer_dist, y0 - outer_buffer_dist), 
            (x0 + basin_length + outer_buffer_dist, y0 + basin_width + outer_buffer_dist), 
            (x0 - outer_buffer_dist, y0 + basin_width + outer_buffer_dist)
        ])
        
        # Inner buffer (smoother transition closer to basin)
        inner_buffer_dist = max_dim * 0.75
        inner_buffer_poly = Polygon([
            (x0 - inner_buffer_dist, y0 - inner_buffer_dist), 
            (x0 + basin_length + inner_buffer_dist, y0 - inner_buffer_dist), 
            (x0 + basin_length + inner_buffer_dist, y0 + basin_width + inner_buffer_dist), 
            (x0 - inner_buffer_dist, y0 + basin_width + inner_buffer_dist)
        ])
        
        g = Gridgen(dis_base, model_ws=str(workspace), exe_name=gridgen_exe)
        
        # We always want the basin cells to be roughly 1m to 2.5m.
        # Base cell size is (Lx / 25) = (max_dim * 10) / 25 = max_dim * 0.4.
        # For max_dim=20, base=8m.
        # For max_dim=50, base=20m.
        # We use levels 1, 2, and 3 to step it down.
        g.add_refinement_features([outer_buffer_poly], featuretype="polygon", level=1, layers=list(range(nlay)))
        g.add_refinement_features([inner_buffer_poly], featuretype="polygon", level=2, layers=list(range(nlay)))
        
        basin_level = 3
        if delr > 15.0:
            basin_level = 4  # Need deeper refinement if base cells are huge (e.g. max_dim > 40)
            
        g.add_refinement_features([basin_poly], featuretype="polygon", level=basin_level, layers=list(range(nlay)))
        import time
        max_build_retries = 5
        for attempt in range(max_build_retries):
            try:
                g.build(verbose=False)
                break
            except Exception as e:
                err_str = str(e)
                if attempt < max_build_retries - 1 and ("Shapefile does not exist" in err_str or "Permission" in err_str or "Access is denied" in err_str):
                    time.sleep(1.0)
                    continue
                with open(model_dir / "failed_config.json", "w") as f:
                    json.dump(config, f, indent=2)
                if "returned non-zero exit status 1" in err_str:
                    sum["gridgen_error"] = "Gridgen executable crashed. See command output for details."
                raise
        
        # Windows Defender / Anti-virus often locks the newly created .dat files. 
        # Adding a short delay helps prevent "Cannot open file" errors in subsequent intersections.
        time.sleep(1.5)
        
        gridprops = g.get_gridprops_disu5()
        
        # Add perlen, nstp, tsmult to gridprops for DISU
        gridprops["perlen"] = perlen
        gridprops["nstp"] = [1] * nper
        gridprops["tsmult"] = [1.0] * nper
        gridprops["steady"] = [False] * nper
        gridprops["nper"] = nper
        gridprops["itmuni"] = 4 # days
        gridprops["lenuni"] = 2 # meters
        
        sim = flopy.mfusg.MfUsg(modelname=model_name, model_ws=str(model_dir), exe_name=mfusg_exe, structured=False)
        
        disu = flopy.mfusg.MfUsgDisU(sim, **gridprops)
        
        def safe_intersect(poly, ptype, layer):
            import time
            for attempt in range(5):
                try:
                    return g.intersect(poly, ptype, layer)
                except Exception as e:
                    # Windows file locking often causes gridgen.exe to fail randomly with "Cannot open file:quadtreegrid.bot14.dat"
                    # Flopy loses the stderr output, so we just catch all exceptions and retry
                    if attempt < 4:
                        time.sleep(1.0)
                        continue
                    raise

        # Find nodes inside the basin to apply recharge
        intersect_L0 = safe_intersect([basin_poly], "polygon", 0)
        basin_nodes_L0 = intersect_L0['nodenumber']
        
        intersect_L1 = safe_intersect([basin_poly], "polygon", 1)
        basin_nodes_L1 = intersect_L1['nodenumber']
        
        # LPF package arrays
        n_nodes = gridprops["nodes"]
        hk = np.ones(n_nodes) * k_horiz
        vka = np.ones(n_nodes) * k_vert
        sy_arr = np.ones(n_nodes) * sy
        ss_arr = np.ones(n_nodes) * ss
        
        # Pseudo-lake: Layer 0 basin nodes
        # High conductivity so the water surface stays flat instantly
        hk[basin_nodes_L0] = 100.0
        vka[basin_nodes_L0] = 100.0
        sy_arr[basin_nodes_L0] = 1.0
        ss_arr[basin_nodes_L0] = 1.0 / max_depth
        
        # Bed layer: Layer 1 basin nodes (thickness = bed_thick)
        # Apply the user's bed_k and side_k to simulate the physical clogging layer
        vka[basin_nodes_L1] = bed_k
        if mode == "full":
            hk[basin_nodes_L1] = side_k
        elif mode == "vertical":
            # For purely vertical infiltration, disable horizontal spreading from the clogging layer
            hk[basin_nodes_L1] = 1e-4
        
        # laytyp=4 uses the Upstream Weighting formulation (required for Newton-Raphson)
        lpf = flopy.mfusg.MfUsgLpf(sim, hk=hk, vka=vka, sy=sy_arr, ss=ss_arr, laytyp=4)
        
        # BAS Package
        strt = np.ones(n_nodes) * initial_head
        strt[basin_nodes_L0] = floor_elev + 1e-4
        
        # Make outer cells of Layer 0 inactive so water doesn't flow horizontally "through the air"
        n_cells_per_layer = n_nodes // nlay
        layer_0_nodes = np.arange(n_cells_per_layer)
        outer_L0 = np.setdiff1d(layer_0_nodes, basin_nodes_L0)
        
        ibound = np.ones(n_nodes, dtype=int)
        ibound[outer_L0] = 0
        
        bas = flopy.modflow.ModflowBas(sim, ibound=ibound, strt=strt)
        
        # WEL package for Inflow (applied to refined basin nodes in Layer 0)
        # gridprops["area"] is a list of arrays per layer
        try:
            print(f"gridprops['nodes']: {gridprops['nodes']}")
            node_areas = np.array(gridprops["area"][0], dtype=float)
            basin_areas = node_areas[np.array(basin_nodes_L0, dtype=int)]
            total_basin_area = np.sum(basin_areas)
            print(f"Min basin area: {np.min(basin_areas)}, Max basin area: {np.max(basin_areas)}, Total: {total_basin_area}")
        except Exception as e:
            print(e)
            
        wel_data = {}
        for i in range(nper):
            q_total = flows_m3day[i]
            if q_total > 0:
                wel_spd = []
                q_node = float(q_total / len(basin_nodes_L0))
                for node in basin_nodes_L0:
                    wel_spd.append([node, q_node])
                wel_data[i] = wel_spd
            else:
                wel_data[i] = 0
            
        wel = flopy.mfusg.MfUsgWel(sim, stress_period_data=wel_data)

        # Constant Head Boundary (CHD) to prevent the domain from filling up like a closed box
        edge_lines = [
            LineString([(0, 0), (Lx, 0)]),
            LineString([(Lx, 0), (Lx, Ly)]),
            LineString([(Lx, Ly), (0, Ly)]),
            LineString([(0, Ly), (0, 0)])
        ]
        chd_spd = {}
        for i in range(nper):
            chd_spd[i] = []
        for lay in range(nlay):
            for edge in edge_lines:
                try:
                    intersect = g.intersect([edge], "line", lay)
                    for node in intersect['nodenumber']:
                        for i in range(nper):
                            chd_spd[i].append([node, initial_head, initial_head])
                except Exception:
                    pass
        for i in range(nper):
            unique_chd = {item[0]: item for item in chd_spd[i]}
            chd_spd[i] = list(unique_chd.values())
            if not chd_spd[i]:
                chd_spd[i] = 0
        chd = flopy.modflow.ModflowChd(sim, stress_period_data=chd_spd)

        # 3. Virtual Overflow Drain (Prevent solver explosion if basin overfills)
        # Place a drain at the basin rim (floor_elev + max_depth)
        drn_spd = {}
        rim_elev = floor_elev + max_depth
        for i in range(nper):
            drn_list = []
            for node in basin_nodes_L0:
                drn_list.append([node, rim_elev, 1e5]) # High conductance
            drn_spd[i] = drn_list
        drn = flopy.modflow.ModflowDrn(sim, ipakcb=50, stress_period_data=drn_spd)
        
        # 4. Solvers and Output Control
        spd = {}
        for i in range(nper):
            spd[(i, 0)] = ['save head', 'save budget']
        oc = flopy.modflow.ModflowOc(sim, stress_period_data=spd)
        
        # SMS Solver
        sms = flopy.mfusg.MfUsgSms(
            sim, hclose=1e-2, hiclose=1e-2, mxiter=500, 
            iter1=200, iprsms=1, nonlinmeth=2, linmeth=1,
            theta=0.8, akappa=0.1, gamma=0.2, amomentum=0.1,
            numtrack=50, btol=1.05, breduc=0.2, reslim=1.0
        )
        
        import time
        max_retries = 5
        for attempt in range(max_retries):
            try:
                sim.write_input()
                break
            except PermissionError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(1.0)
        
        import subprocess
        res = subprocess.run([mfusg_exe, f"{model_name}.nam"], cwd=model_dir, capture_output=True, text=True)
        success = (res.returncode == 0 and "Normal termination" in res.stdout)
        
        # Parse outputs to compute stage
        import flopy.utils.binaryfile as bf
        hds_file = model_dir / f"{model_name}.hds"
        
        stages = []
        times = []
        current_time = 0.0
        peak_stage = -float('inf')
        peak_time = 0.0
        
        max_head_array = None
        max_head_all_array = None
        
        # Get botm_all to filter out dry cell artifacts (which report their head as their cell bottom)
        try:
            ugrid_props = g.get_gridprops_unstructuredgrid()
            bot_raw = ugrid_props["bot"]
            if isinstance(bot_raw, list) and len(bot_raw) > 0 and isinstance(bot_raw[0], (int, float)):
                ncpl = ugrid_props["ncpl"]
                botm_all = np.concatenate([np.full(n, b) for n, b in zip(ncpl, bot_raw)])
            else:
                botm_all = np.array(bot_raw).flatten()
        except:
            botm_all = None
        
        if success and hds_file.exists():
            hds = bf.HeadUFile(str(hds_file))
            kstpkper = hds.get_kstpkper()
            for i, (kstp, kper) in enumerate(kstpkper):
                head_array = hds.get_data(kstpkper=(kstp, kper))
                
                # unstructured grid head_array is a list of 1D arrays per layer
                head_all_flat = np.concatenate(head_array)
                
                if botm_all is not None:
                    dry_mask = head_all_flat <= botm_all + 1e-3
                    wet_head_flat = np.where(dry_mask, -1e9, head_all_flat)
                    n_cells_per_layer = len(head_array[0])
                    wet_head_reshaped = wet_head_flat.reshape(len(head_array), n_cells_per_layer)
                    water_table_ts = np.max(wet_head_reshaped, axis=0)
                    water_table_ts = np.where(water_table_ts == -1e9, initial_head, water_table_ts)
                else:
                    water_table_ts = np.max(np.array(head_array), axis=0)
                
                # Update max head array
                if max_head_array is None:
                    max_head_array = np.copy(water_table_ts)
                    max_head_all_array = np.copy(head_all_flat)
                else:
                    max_head_array = np.maximum(max_head_array, water_table_ts)
                    max_head_all_array = np.maximum(max_head_all_array, head_all_flat)
                    
                basin_heads = head_array[0][basin_nodes_L0]
                stage = float(np.max(basin_heads))
                stages.append(stage)
                
                dt = perlen[kper]
                current_time += dt
                times.append(float(current_time))
                
                if stage > peak_stage:
                    peak_stage = stage
                    peak_time = current_time
            hds.close()
                    
        else:
            print("Model failed. Output:")
            print(res.stdout)
            print(res.stderr)
            success = False
            
        # Write CSV
        if len(times) > 0:
            df_out = pd.DataFrame({'time_days': times, 'stage_m': stages})
            df_out.to_csv(model_dir / f"{model_name}_lak_stage.csv", index=False)
            
            # Post-process for outlet
            try:
                # Calculate storage change from MODFLOW output
                stg2vol, vol2stg = _geom_stage_to_storage_fn(basin_cfg, floor_elev)
                stg_arr = np.array(stages, float)
                storage_m3_arr = stg2vol(stg_arr)
                peak_storage_m3 = float(np.nanmax(storage_m3_arr))
                
                # Prepend the initial state (t=0)
                t_sec = np.array(times, float) * 86400.0
                t_all = np.concatenate([[0.0], t_sec])
                
                s_initial = stg2vol(floor_elev + 1e-4)
                s_all = np.concatenate([[s_initial], storage_m3_arr])
                
                dt = np.diff(t_all)
                dt = np.where(dt == 0.0, 1e-3, dt) # Prevent div by zero
                dS = np.diff(s_all)
                dSdt = dS / dt
                
                # Inflow in m3/s. MODFLOW WEL package applies constant flow over the entire stress period.
                q_in_m3s = flows_m3day[:len(dSdt)] / 86400.0
                
                # Modflow's exact net subsurface flux (m3/s) at each timestep
                qinf_ts = q_in_m3s - dSdt
                
                # We can just pass this exact array to the mass balance router
                infiltration_rating = qinf_ts
                
                # Generate FloPy Heatmap
                heatmap_b64 = None
                if max_head_array is not None:
                    try:
                        fig, ax = plt.subplots(figsize=(6, 5))
                        ugrid_props = g.get_gridprops_unstructuredgrid()
                        ugrid = flopy.discretization.UnstructuredGrid(**ugrid_props)
                        pmv = flopy.plot.PlotMapView(modelgrid=ugrid, ax=ax, layer=0)
                        
                        # Filter dry cells by checking if head is at or below the cell bottom elevation (floor_elev for Layer 0)
                        # We no longer mask out cells below floor_elev, as max_head_array now represents the true water table
                        # across all layers, allowing the full mound to be visualised.
                        masked_head = max_head_array
                        
                        cb = pmv.plot_array(masked_head, cmap='viridis', alpha=0.9)
                        pmv.plot_grid(colors='white', lw=0.2, alpha=0.3)
                        pmv.contour_array(masked_head, colors='black', linewidths=0.5, levels=10)
                        
                        plt.colorbar(cb, shrink=0.7, label='Peak GW Head (m AHD)')
                        ax.set_title("Peak Groundwater Contours")
                        ax.set_xlabel("Easting (m)")
                        ax.set_ylabel("Northing (m)")
                        
                        # Add basin boundary for context
                        if isinstance(basin_poly, Polygon):
                            x, y = basin_poly.exterior.xy
                            ax.plot(x, y, color='red', linewidth=2, label='Basin Boundary')
                            ax.legend(loc='upper right', framealpha=0.9)
                        
                        buf = io.BytesIO()
                        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
                        plt.close(fig)
                        buf.seek(0)
                        heatmap_b64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
                        
                        # Generate Cross-Section Visualization
                        cs_b64 = None
                        if max_head_all_array is not None:
                            try:
                                # MODFLOW-USG Upstream Weighting outputs the cell bottom elevation for dry cells.
                                # To avoid plotting massive horizontal blocks of 'head' outside the basin,
                                # we must mask out any cell where the head is at or below its bottom elevation.
                                if botm_all is not None:
                                    masked_head_all = np.ma.masked_where(max_head_all_array <= botm_all + 1e-3, max_head_all_array)
                                else:
                                    masked_head_all = max_head_all_array
                                    
                                fig_cs, ax_cs = plt.subplots(figsize=(8, 4))
                                pxs = flopy.plot.PlotCrossSection(modelgrid=ugrid, line={'line': [(0, Ly/2), (Lx, Ly/2)]}, ax=ax_cs)
                                cb_cs = pxs.plot_array(masked_head_all, cmap='viridis', alpha=0.9)
                                pxs.plot_grid(colors='white', lw=0.2, alpha=0.3)
                                
                                plt.colorbar(cb_cs, shrink=0.7, label='Peak GW Head (m AHD)')
                                ax_cs.set_title("Cross-Section (West-East)")
                                ax_cs.set_xlabel("Distance along section (m)")
                                ax_cs.set_ylabel("Elevation (m AHD)")
                                
                                # Add basin floor marker
                                x_basin = [Lx/2 - basin_length/2, Lx/2 + basin_length/2]
                                y_basin = [floor_elev, floor_elev]
                                ax_cs.plot(x_basin, y_basin, color='red', linewidth=3, label='Basin Floor')
                                ax_cs.legend(loc='upper right')
                                
                                buf_cs = io.BytesIO()
                                plt.savefig(buf_cs, format='png', bbox_inches='tight', dpi=150)
                                plt.close(fig_cs)
                                buf_cs.seek(0)
                                cs_b64 = f"data:image/png;base64,{base64.b64encode(buf_cs.read()).decode('utf-8')}"
                            except Exception as e:
                                import traceback
                                print(f"Failed to generate cross section: {e}")
                                traceback.print_exc()
                            
                    except Exception as e:
                        import traceback
                        print(f"Failed to generate heatmap: {e}")
                        traceback.print_exc()
                        
                # Export lak_allobs.csv for the GUI's "Inflow - Storage - Outflow" graph
                # The GUI expects: time, LAK_STAGE, LAK_EXT_INFLOW, LAK_GW, LAK_VOLUME
                # LAK_GW represents net flow from lake to GW. So outflow to GW is negative.
                lak_gw_m3d = -qinf_ts * 86400.0
                df_allobs = pd.DataFrame({
                    'time': times,
                    'LAK_STAGE': stages,
                    'LAK_EXT_INFLOW': flows_m3day[:len(times)],
                    'LAK_GW': lak_gw_m3d[:len(times)],
                    'LAK_VOLUME': storage_m3_arr[:len(times)]
                })
                timeseries_payload = {
                    "time_days": times,
                    "stage_m": stages,
                    "inflow_m3s": (flows_m3day[:len(times)] / 86400.0).tolist(),
                    "infiltration_m3s": qinf_ts.tolist(), 
                }
                if heatmap_b64:
                    timeseries_payload["heatmap_base64"] = heatmap_b64
                if cs_b64:
                    timeseries_payload["cross_section_base64"] = cs_b64
                
            except Exception as e:
                infiltration_rating = None
                peak_storage_m3 = 0.0
                timeseries_payload = {
                    "time_days": times,
                    "stage_m": stages,
                    "inflow_m3s": (flows_m3day[:len(times)] / 86400.0).tolist(),
                }
                
            summary = {
                "success": success,
                "ts1_file": str(ts1_path),
                "scenario": scenario_title,
                "model_name": model_name,
                "peak_stage_m": float(peak_stage),
                "peak_storage_m3": float(peak_storage_m3),
                "inflow_total_m3": float(np.sum(flows_m3day[:len(times)] * np.append([perlen[0]], np.diff(times)))) if len(times) > 0 else 0.0
            }
                
            # 5. Outlets post-processing
            summary["outlet_enabled"] = False
            out_cfg = config.get("outlets", config.get("outlet", None))
            
            out_structs = []
            if isinstance(out_cfg, dict):
                if out_cfg.get("enabled", False):
                    out_structs.append(create_outlet_from_config(out_cfg))
            elif isinstance(out_cfg, list):
                for oc in out_cfg:
                    if oc.get("enabled", False):
                        out_structs.append(create_outlet_from_config(oc))
                        
            if len(out_structs) > 0:
                summary["outlet_enabled"] = True
                try:
                    res_out = apply_outlet_to_results(
                        time_days=np.array(times, float),
                        modflow_stage=stg_arr,
                        modflow_inflow=flows_m3day / 86400.0,
                        modflow_infiltration=infiltration_rating,
                        outlet_structure=out_structs,
                        basin_geometry=basin_cfg,
                        floor_elev=floor_elev
                    )                  
                    df_out_outlet = pd.DataFrame({
                        'time_days': res_out['time_days'],
                        'stage_with_outlet_m': res_out['stage_with_outlet'],
                        'storage_with_outlet_m3': res_out['storage_with_outlet'],
                        'outlet_discharge_m3s': res_out['outlet_discharge']
                    })
                    df_out_outlet.to_csv(model_dir / f"{model_name}_lak_stage_with_outlet.csv", index=False)
                    
                    # Update timeseries_payload for frontend graphing
                    timeseries_payload.update({
                        "stage_m": res_out['stage_with_outlet'].tolist(),
                        "storage_m3": res_out['storage_with_outlet'].tolist(),
                        "outlet_discharge_m3s": res_out['outlet_discharge'].tolist()
                    })
                    
                    summary["peak_stage_with_outlet_m"] = float(np.nanmax(res_out['stage_with_outlet']))
                    summary["peak_storage_with_outlet_m3"] = float(np.nanmax(res_out['storage_with_outlet']))
                    summary["peak_outlet_m3s"] = float(res_out.get("peak_outlet_m3s", 0.0))
                    summary["total_outlet_m3"] = float(res_out.get("total_outlet_m3", 0.0))
                    summary["outlet_enabled"] = True
                except Exception as e:
                    print(f"Error applying outlet: {e}")
                    summary["outlet_error"] = str(e)
        else:
            summary = {
                "success": False,
                "ts1_file": str(ts1_path),
                "scenario": scenario_title,
                "error": "No output timeseries found"
            }
        
        with open(model_dir / 'scenario_summary.json', 'w') as fp:
            json.dump(summary, fp, indent=2)
            
        return success, summary, timeseries_payload, str(model_dir)

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
