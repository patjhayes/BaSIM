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
import os
import json
from celery import chord
from src.api.worker import (
    run_ilsax_task,
    run_ts1_task,
    finalize_ilsax_ensemble,
    finalize_ts1_batch,
    simulation_error_callback,
    redis_client
)
import redis.asyncio as redis_async
from fastapi import Depends
from src.api.billing import router as billing_router, _add_credits
from src.api.auth_utils import get_current_user

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
app.include_router(billing_router, prefix="/api/billing")

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

@app.post("/api/upload-observed")
async def upload_observed(file: UploadFile = File(...)):
    try:
        up_dir = Path("model_input/observed_files/uploads")
        up_dir.mkdir(parents=True, exist_ok=True)
        dest = up_dir / file.filename
        with dest.open("wb") as f:
            f.write(await file.read())
        return {"filepath": str(dest), "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-shapefile")
async def upload_shapefile(file: UploadFile = File(...)):
    import zipfile
    import shapefile
    import shutil
    try:
        up_dir = Path("model_input/shapefiles/uploads")
        up_dir.mkdir(parents=True, exist_ok=True)
        zip_dest = up_dir / file.filename
        with zip_dest.open("wb") as f:
            f.write(await file.read())
            
        extract_dir = up_dir / file.filename.replace(".zip", "")
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_dest, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        shp_file = next(extract_dir.glob("*.shp"), None)
        if not shp_file:
            raise ValueError("No .shp file found in the uploaded zip.")
            
        sf = shapefile.Reader(str(shp_file))
        shapes = sf.shapes()
        if not shapes:
            raise ValueError("Shapefile contains no shapes.")
            
        # Get the first shape's points
        points = shapes[0].points
        
        # Cleanup
        shutil.rmtree(extract_dir, ignore_errors=True)
        zip_dest.unlink(missing_ok=True)
        
        return {"points": points}
    except Exception as e:
        logger.error(f"Shapefile parsing failed: {e}")
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
async def simulate(cfg: Dict, bg: BackgroundTasks, user: dict = Depends(get_current_user)):
    # 1. Determine cost
    inflow_source = cfg.get("inflow_source", "ilsax")
    if inflow_source == "ts1":
        ts1_files = cfg.get("ts1_files", [])
        if cfg.get("ts1_file") and not ts1_files:
            ts1_files = [cfg["ts1_file"]]
        cost = len(ts1_files)
    else:
        # ILSAX mode
        ensemble_rainfalls = cfg.get("ensemble_rainfalls", [])
        cost = len(ensemble_rainfalls) if ensemble_rainfalls else 1
        
    project_code = cfg.get("project_code")
    if not project_code:
        raise HTTPException(status_code=400, detail="project_code is required")
        
    # 2. Check .gov.au free tier
    email = user.get("email", "")
    is_gov = email.endswith(".gov.au")
    
    # 3. Check credits and deduct if not .gov.au
    if not is_gov:
        # We need to query the balance natively via service role
        from src.api.auth_utils import supabase_admin
        proj_resp = supabase_admin.table('projects').select('credit_balance, company_id').eq('project_code', project_code).execute()
        
        if not proj_resp.data:
            raise HTTPException(status_code=400, detail="Project not found. Please create it or check billing.")
            
        project = proj_resp.data[0]
        if project['company_id'] != user['company_id']:
            raise HTTPException(status_code=403, detail="Not authorized to run on this project")
            
        if project['credit_balance'] < cost:
            raise HTTPException(status_code=402, detail=f"Insufficient credits. Cost: {cost}, Balance: {project['credit_balance']}")
            
        # Deduct credits
        _add_credits(project_code, -cost, 'simulation', user['id'], f"Simulation Run ({cost} runs)")

    sim_id = str(uuid.uuid4())
    simulations[sim_id] = {
        "id": sim_id,
        "status": "running",
        "progress": 0,
        "config": cfg,
        "started_at": datetime.utcnow().isoformat(),
        "user_email": email
    }
    
    bg.add_task(dispatch_simulation, sim_id, cfg)
    return {"simulation_id": sim_id, "status": "started", "message": "Simulation started", "cost": 0 if is_gov else cost}


async def dispatch_simulation(sim_id: str, config: Dict):
    """Background task to set up and dispatch Celery tasks."""
    try:
        await asyncio.sleep(1.5)  # Give the WebSocket a chance to connect before blasting messages
        
        redis_client.publish(f"sim:{sim_id}", json.dumps({"type": "progress", "progress": 5, "message": "Dispatching to workers..."}))
        
        inflow_source = config.get("inflow_source", "ilsax")
        
        if inflow_source == "ts1":
            ts1_files = config.get("ts1_files", [])
            if config.get("ts1_file") and not ts1_files:
                ts1_files = [config["ts1_file"]]
                
            if not ts1_files:
                raise RuntimeError("No TS1 files provided")
                
            redis_client.publish(f"sim:{sim_id}", json.dumps({"type": "progress", "progress": 20, "message": f"Dispatching {len(ts1_files)} TS1 simulations..."}))
            
            header = [run_ts1_task.s(f, config, sim_id) for f in ts1_files]
            callback = finalize_ts1_batch.s(sim_id, config).on_error(simulation_error_callback.s(sim_id))
            chord(header)(callback)
            
        else:
            # ILSAX Ensemble Mode
            ensemble_rainfalls = config.get("ensemble_rainfalls", [])
            if not ensemble_rainfalls:
                if not config.get("rainfall", {}).get("depths_mm"):
                    raise RuntimeError("No rainfall data provided for ILSAX run")
                ensemble_rainfalls = [{
                    "run_name": "Single Run",
                    "duration_minutes": config["rainfall"].get("duration_minutes", 60),
                    "pattern_rank": 1,
                    "timestep_minutes": config["rainfall"].get("timestep_minutes", 5.0),
                    "depths_mm": config["rainfall"]["depths_mm"]
                }]
            
            redis_client.publish(f"sim:{sim_id}", json.dumps({"type": "progress", "progress": 20, "message": f"Dispatching {len(ensemble_rainfalls)} ILSAX ensemble simulations..."}))
            
            header = [run_ilsax_task.s(r, config, sim_id) for r in ensemble_rainfalls]
            callback = finalize_ilsax_ensemble.s(sim_id).on_error(simulation_error_callback.s(sim_id))
            chord(header)(callback)
        
    except Exception as e:
        logger.error(f"Dispatch {sim_id} failed: {e}", exc_info=True)
        simulations[sim_id]["status"] = "failed"
        simulations[sim_id]["error"] = str(e)
        redis_client.publish(f"sim:{sim_id}", json.dumps({"type": "error", "message": f"Dispatch failed: {e}"}))


@app.get("/api/simulations/{sim_id}")
async def simulation_status(sim_id: str):
    sim = simulations.get(sim_id)
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


@app.websocket("/ws/{client_id}")
async def ws_progress(ws: WebSocket, client_id: str):
    await manager.connect(ws, client_id)
    
    celery_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    r = redis_async.from_url(celery_url)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"sim:{client_id}")
    
    async def reader():
        try:
            while True:
                await ws.receive_text()
        except Exception:
            pass

    async def writer():
        import redis.exceptions
        try:
            while True:
                try:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            data = json.loads(message["data"])
                            await manager.send(client_id, data)
                            if data.get("type") in ("complete", "error"):
                                return
                except redis.exceptions.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"WS writer listen error: {e}")
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"WS writer fatal error: {e}")

    try:
        await asyncio.gather(reader(), writer())
    finally:
        await pubsub.unsubscribe(f"sim:{client_id}")
        await r.aclose()
        manager.disconnect(client_id)


# Serve built frontend when available
if Path("frontend/dist").exists():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
