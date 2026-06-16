"""
FastAPI backend for BaSIM
"""
from __future__ import annotations

from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Optional, List
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

sim_executor = ThreadPoolExecutor(max_workers=2)

# Ensure project root on sys.path for existing modules
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import existing backend pieces
try:
    from src.main_phase3_step32_time_varying import run_phase3_step32_with_config
except Exception:  # type: ignore
    run_phase3_step32_with_config = None  # mocked in dev

try:
    from src.utils.performance_profiles import DEFAULT_PROFILES as PERFORMANCE_PROFILES
except Exception:  # type: ignore
    PERFORMANCE_PROFILES = {
        'fast': {'divisor': 15.0, 'min_floor_m': 2.0},
        'balanced': {'divisor': 25.0, 'min_floor_m': 2.0},
        'accurate': {'divisor': 40.0, 'min_floor_m': 2.0},
    }

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("basim.api")

app = FastAPI(title="BaSIM API", version="0.1.0")

# CORS for local dev (Vue vite server) and Render frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active simulations store (in-memory for dev)
simulations: Dict[str, Dict] = {}


class BasinConfig(BaseModel):
    basin_type: str = "rectangle"
    dimensions: Dict[str, float] = {"length": 50.0, "width": 30.0, "depth": 3.0}
    performance_mode: str = "balanced"
    hydraulic_properties: Dict[str, float] = {
        # UI provides Kh, Kv in m/s; Ss (1/m); Sy (-)
        "Kh": 1e-5,
        "Kv": 1e-6,
        "Ss": 1e-5,
        "Sy": 0.05,
    }
    simulation_time_days: float = 7.0
    ts1_file: Optional[str] = None
    initial_head: float = 0.5  # Groundwater level (m AHD)
    bottom_elev: Optional[float] = None  # Optional aquifer bottom elevation (m AHD)


class SimulationResponse(BaseModel):
    simulation_id: str
    status: str
    message: str


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, client_id: str):
        await ws.accept()
        self.active[client_id] = ws

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)

    async def send(self, client_id: str, data: Dict):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_json(data)


manager = ConnectionManager()


@app.get("/")
async def root():
    # In production, serve built frontend
    index_path = Path("frontend/dist/index.html")
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "BaSIM API running", "ts": datetime.utcnow().isoformat()}


@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.get("/api/performance-profiles")
async def get_profiles():
    # Normalize to plain dict
    def _to_dict(p):
        try:
            return {"divisor": float(p.divisor), "min_floor_m": float(p.min_floor_m)}
        except Exception:
            return {"divisor": float(p.get("divisor", 25.0)), "min_floor_m": float(p.get("min_floor_m", 2.0))}
    details = {k: _to_dict(v) for k, v in dict(PERFORMANCE_PROFILES).items()}
    return {"profiles": list(details.keys()), "details": details}


@app.get("/api/ts1-files")
async def list_ts1_files():
    ts1_dir = Path("model_input/ts1_files")
    files: List[str] = []
    if ts1_dir.exists():
        files = [p.name for p in ts1_dir.glob("*.ts1")]
    return {"files": files}


class ClimateRequest(BaseModel):
    lat: float
    lon: float

@app.post("/api/upload-ts1")
async def upload_ts1(file: UploadFile = File(...)):
    try:
        up_dir = Path("model_input/ts1_files/uploads")
        up_dir.mkdir(parents=True, exist_ok=True)
        dest = up_dir / file.filename
        with dest.open("wb") as f:
            f.write(await file.read())
        return {"filepath": str(dest), "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fetch-climate")
async def fetch_climate(req: ClimateRequest):
    try:
        from src.soakhydro_legacy.models.common import Coordinate, AEP
        from src.soakhydro_legacy.services.bom import BoMIFDClient
        from src.soakhydro_legacy.services.arr import ARRTemporalPatternClient
        
        coord = Coordinate(latitude=req.lat, longitude=req.lon)
        
        # We fetch all common AEPs and Durations
        aeps = [AEP.AEP_63_2, AEP.AEP_50, AEP.AEP_20, AEP.AEP_10, AEP.AEP_5, AEP.AEP_2, AEP.AEP_1]
        durations = [10, 15, 20, 30, 45, 60, 90, 120, 180, 270, 360, 540, 720, 1080, 1440, 2880, 4320]
        
        bom = BoMIFDClient()
        ifd_results = bom.fetch_ifd(coord, durations, aeps)
        ifd_dicts = [r.to_dict() for r in ifd_results]
        
        arr = ARRTemporalPatternClient()
        tp_results = arr.fetch_temporal_patterns(coord, durations, aeps)
        
        try:
            ccf_resp = arr.fetch_climate_factors(coord)
            ccf_data = ccf_resp.get("parsed", {})
            arr_raw_txt = ccf_resp.get("raw_txt", "")
        except Exception as ccf_err:
            logger.warning(f"Failed to fetch climate factors: {ccf_err}")
            ccf_data = {}
            arr_raw_txt = ""
            
        # tp_results is Dict[tuple, List[TemporalPattern]]
        # We need to flatten this to be JSON serializable
        tp_dicts = []
        for (aep_tier, duration), patterns in tp_results.items():
            for p in patterns:
                d = p.to_dict()
                d["aep_tier"] = aep_tier
                tp_dicts.append(d)
                
        return {
            "ifd": ifd_dicts,
            "temporal_patterns": tp_dicts,
            "ccf": ccf_data,
            "arr_raw_txt": arr_raw_txt
        }
    except Exception as e:
        logger.error(f"Failed to fetch climate data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate")
async def simulate(cfg: Dict, bg: BackgroundTasks):
    sim_id = str(uuid.uuid4())
    simulations[sim_id] = {
        "id": sim_id,
        "status": "running",
        "progress": 0,
        "config": cfg,
        "started_at": datetime.utcnow().isoformat(),
    }
    
    bg.add_task(run_simulation_task, sim_id, cfg)
    return {"simulation_id": sim_id, "status": "started", "message": "Simulation started"}


async def run_simulation_task(sim_id: str, config: Dict):
    try:
        await manager.send(sim_id, {"type": "progress", "progress": 5, "message": "Initializing model engine..."})
        loop = asyncio.get_event_loop()
        from src.usg_model_builder import run_simulation
        
        inflow_source = config.get("inflow_source", "ilsax")
        
        if inflow_source == "ts1":
            ts1_files = config.get("ts1_files", [])
            if config.get("ts1_file") and not ts1_files:
                ts1_files = [config["ts1_file"]]
                
            if not ts1_files:
                raise RuntimeError("No TS1 files provided")
                
            await manager.send(sim_id, {"type": "progress", "progress": 20, "message": f"Running {len(ts1_files)} TS1 simulations..."})
            
            async def run_ts1(filepath: str):
                cfg_copy = dict(config)
                cfg_copy["sim_id"] = sim_id
                run_name = Path(filepath).stem
                await manager.send(sim_id, {"type": "subtask_started", "run_name": run_name})
                try:
                    def _run():
                        return run_simulation(ts1_path=filepath, config=cfg_copy)
                    res = await loop.run_in_executor(sim_executor, _run)
                except Exception as e:
                    await manager.send(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": str(e)})
                    raise
                await manager.send(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": res[0]})
                return res
                
            tasks = [run_ts1(f) for f in ts1_files]
            run_results = await asyncio.gather(*tasks)
            
            parsed_results = []
            for filepath, (ok, summary, ts_payload, outdir) in zip(ts1_files, run_results):
                parsed_results.append({
                    "filename": Path(filepath).name,
                    "ok": ok,
                    "peak_stage": summary.get("peak_stage_m") or summary.get("peak_stage"),
                    "peak_storage": summary.get("peak_storage_m3") or summary.get("total_infiltration"),
                    "inflow_total": summary.get("inflow_total_m3"),
                    "summary": summary,
                    "timeseries": ts_payload
                })
            
            results = {
                "type": "ts1_batch",
                "runs": parsed_results
            }
            
        else:
            # ILSAX Ensemble Mode
            ensemble_rainfalls = config.get("ensemble_rainfalls", [])
            if not ensemble_rainfalls:
                # Fallback to single run if ensemble array not provided
                if not config.get("rainfall", {}).get("depths_mm"):
                    raise RuntimeError("No rainfall data provided for ILSAX run")
                ensemble_rainfalls = [{
                    "run_name": "Single Run",
                    "duration_minutes": config["rainfall"].get("duration_minutes", 60),
                    "pattern_rank": 1,
                    "timestep_minutes": config["rainfall"].get("timestep_minutes", 5.0),
                    "depths_mm": config["rainfall"]["depths_mm"]
                }]
            
            await manager.send(sim_id, {"type": "progress", "progress": 20, "message": f"Running {len(ensemble_rainfalls)} ILSAX ensemble simulations..."})
            
            async def run_ilsax(run_info: Dict):
                cfg_copy = dict(config)
                cfg_copy["rainfall"] = {
                    "timestep_minutes": run_info["timestep_minutes"],
                    "depths_mm": run_info["depths_mm"]
                }
                run_name = run_info.get("run_name", "synthetic")
                cfg_copy["run_name"] = run_name
                cfg_copy["sim_id"] = sim_id
                
                await manager.send(sim_id, {"type": "subtask_started", "run_name": run_name})
                
                try:
                    def _run():
                        return run_simulation(ts1_path="", config=cfg_copy)
                    ok, summary, ts_payload, outdir = await loop.run_in_executor(sim_executor, _run)
                except Exception as e:
                    await manager.send(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": str(e)})
                    raise
                
                await manager.send(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": ok})
                
                return {
                    "run_info": run_info,
                    "ok": ok,
                    "peak_stage": float(summary.get("peak_stage_m") or summary.get("peak_stage", 0.0)),
                    "summary": summary,
                    "timeseries": ts_payload
                }
                
            tasks = [run_ilsax(r) for r in ensemble_rainfalls]
            completed_runs = await asyncio.gather(*tasks)
            
            # Group by duration
            grouped = {}
            for r in completed_runs:
                dur = r["run_info"]["duration_minutes"]
                if dur not in grouped:
                    grouped[dur] = []
                grouped[dur].append(r)
                
            duration_summaries = {}
            for dur, runs in grouped.items():
                # Sort by peak stage descending
                runs_sorted = sorted(runs, key=lambda x: x["peak_stage"], reverse=True)
                
                # 5th highest is median if there are 10. We just take index 4 if len >= 5, else mid
                if len(runs_sorted) >= 10:
                    median_run = runs_sorted[4] # 5th highest
                else:
                    median_run = runs_sorted[len(runs_sorted) // 2]
                    
                max_run = runs_sorted[0]
                
                duration_summaries[dur] = {
                    "median_peak_stage": median_run["peak_stage"],
                    "max_peak_stage": max_run["peak_stage"],
                    "median_run": median_run,
                    "max_run": max_run,
                    "all_runs": runs_sorted
                }
            
            # Find critical duration (highest median peak stage)
            critical_dur = max(duration_summaries.keys(), key=lambda d: duration_summaries[d]["median_peak_stage"])
            
            results = {
                "type": "ilsax_ensemble",
                "durations": duration_summaries,
                "critical_duration": critical_dur
            }

        simulations[sim_id]["status"] = "completed"
        simulations[sim_id]["results"] = results
        await manager.send(sim_id, {"type": "progress", "progress": 100, "message": "Simulation complete"})
        await manager.send(sim_id, {"type": "complete", "results": results})
        
    except Exception as e:
        logger.error(f"Simulation {sim_id} failed: {e}", exc_info=True)
        simulations[sim_id]["status"] = "failed"
        simulations[sim_id]["error"] = str(e)
        await manager.send(sim_id, {"type": "error", "message": f"Simulation failed: {e}"})


@app.get("/api/simulations/{sim_id}")
async def simulation_status(sim_id: str):
    sim = simulations.get(sim_id)
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


@app.websocket("/ws/{client_id}")
async def ws_progress(ws: WebSocket, client_id: str):
    await manager.connect(ws, client_id)
    try:
        while True:
            # Keep-alive / consume client pings
            await ws.receive_text()
    except Exception:
        manager.disconnect(client_id)


# Serve built frontend when available
if Path("frontend/dist").exists():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
