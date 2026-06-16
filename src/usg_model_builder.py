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
    bed_k = float(config["infiltration"]["bed_k_mpd"])
    if config["infiltration"].get("side_k_separate", False):
        side_k = float(config["infiltration"].get("side_k_mpd", bed_k))
    else:
        side_k = bed_k
    mode = config["infiltration"].get("mode", "full")
    
    try:
        # We need a base grid to refine from.
        # Gridgen is known to segfault on highly non-square base cells when refining deeply.
        # Let's force the base grid to be perfectly square.
        max_dim = max(basin_length, basin_width)
        Lx = max_dim * 10
        Ly = max_dim * 10
        nrow, ncol = 10, 10
        delr = Lx / ncol
        delc = Ly / nrow
        
        top_elev = floor_elev + max_depth
        clogged_bottom = floor_elev - bed_thick
        
        # Sub-layer the aquifer to ~1.0m thickness to prevent vertical throttling artifacts
        aq_thickness = clogged_bottom - aq_bottom
        target_thickness = 1.0
        n_aq_layers = max(1, int(np.ceil(aq_thickness / target_thickness)))
        
        botm = [floor_elev, clogged_bottom]
        for i in range(1, n_aq_layers + 1):
            botm.append(clogged_bottom - i * (aq_thickness / n_aq_layers))
            
        nlay = len(botm)
        
        sim_base = flopy.modflow.Modflow(modelname="base", model_ws=str(workspace))
        dis_base = flopy.modflow.ModflowDis(sim_base, nlay=nlay, nrow=nrow, ncol=ncol, delr=delr, delc=delc, top=top_elev, botm=botm)
        
        # Basin polygon
        x0, y0 = (Lx - basin_length) / 2, (Ly - basin_width) / 2
        eps = 0.001123
        basin_poly = Polygon([
            (x0 + eps, y0 + eps), (x0 + basin_length - eps, y0 + eps), 
            (x0 + basin_length - eps, y0 + basin_width - eps), (x0 + eps, y0 + basin_width - eps)
        ])
        
        g = Gridgen(dis_base, model_ws=str(workspace), exe_name=gridgen_exe)
        g.add_refinement_features([basin_poly], featuretype="polygon", level=4, layers=list(range(nlay)))
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
        bas = flopy.modflow.ModflowBas(sim, ibound=1, strt=strt)
        
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
        
        if success and hds_file.exists():
            hds = bf.HeadUFile(str(hds_file))
            kstpkper = hds.get_kstpkper()
            for i, (kstp, kper) in enumerate(kstpkper):
                head_array = hds.get_data(kstpkper=(kstp, kper))
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
                
                t_sec = np.array(times, float) * 86400.0
                dt = np.diff(t_sec)
                dt = np.where(dt == 0.0, 1e-3, dt) # Prevent div by zero
                dS = np.diff(storage_m3_arr)
                dSdt = np.concatenate([[dS[0]/dt[0]], dS/dt])
                
                # Inflow in m3/s
                q_in_m3s = flows_m3day / 86400.0
                if len(q_in_m3s) != len(dSdt):
                    q_in_m3s = np.resize(q_in_m3s, len(dSdt))
                
                # Modflow's exact net subsurface flux (m3/s) at each timestep
                qinf_ts = q_in_m3s - dSdt
                
                # We can just pass this exact array to the mass balance router
                infiltration_rating = qinf_ts
                
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
