import os
import json
import logging
from typing import Dict, List, Any, Union
import redis
from celery import Celery

from src.usg_model_builder import run_simulation
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("basim.worker")

# Get Redis URL from environment
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Initialize Celery app
celery_app = Celery(
    "basim_tasks",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL
)

# Connect to Redis for Pub/Sub progress updates
redis_client = redis.from_url(CELERY_BROKER_URL)


def publish_update(sim_id: str, payload: dict):
    """Publish a progress update to the WebSocket via Redis Pub/Sub."""
    channel = f"sim:{sim_id}"
    try:
        redis_client.publish(channel, json.dumps(payload))
    except Exception as e:
        logger.error(f"Failed to publish to redis: {e}")


@celery_app.task(bind=True)
def run_ilsax_task(self, run_info: Dict, config: Dict, sim_id: str):
    """Run a single ILSAX simulation as part of an ensemble."""
    run_name = run_info.get("run_name", "synthetic")
    
    # Check for cancellation
    if redis_client.get(f"cancel:{sim_id}"):
        publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": "Cancelled by user"})
        return {"run_info": run_info, "ok": False, "peak_stage": 0.0, "summary": {}, "timeseries": {}}
        
    publish_update(sim_id, {"type": "subtask_started", "run_name": run_name})

    # Prepare configuration for this specific run
    cfg_copy = dict(config)
    cfg_copy["rainfall"] = {
        "timestep_minutes": run_info["timestep_minutes"],
        "depths_mm": run_info["depths_mm"]
    }
    cfg_copy["run_name"] = run_name
    cfg_copy["sim_id"] = sim_id

    try:
        ok, summary, ts_payload, outdir = run_simulation(ts1_path="", config=cfg_copy)
    except Exception as e:
        publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": str(e)})
        raise

    publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": ok})

    return {
        "run_info": run_info,
        "ok": ok,
        "peak_stage": float(summary.get("peak_stage_m") or summary.get("peak_stage", 0.0)),
        "summary": summary,
        "timeseries": ts_payload
    }


@celery_app.task(bind=True)
def run_ts1_task(self, ts1_input: Union[str, Dict], config: Dict, sim_id: str):
    """Run a single TS1 simulation."""
    import tempfile
    import uuid
    if isinstance(ts1_input, dict):
        filename = ts1_input.get("name", f"storm_{uuid.uuid4().hex[:8]}.ts1")
        content = ts1_input.get("content", "")
        
        tmp_dir = Path(tempfile.gettempdir()) / "basim_ts1"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        filepath = tmp_dir / filename
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(content)
        run_name = Path(filename).stem
        actual_path = str(filepath)
    else:
        actual_path = str(ts1_input)
        run_name = Path(actual_path).stem

    # Check for cancellation
    if redis_client.get(f"cancel:{sim_id}"):
        publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": "Cancelled by user"})
        return {"filename": Path(actual_path).name, "ok": False, "peak_stage": 0.0, "summary": {}, "timeseries": {}}

    publish_update(sim_id, {"type": "subtask_started", "run_name": run_name})

    cfg_copy = dict(config)
    cfg_copy["sim_id"] = sim_id

    try:
        ok, summary, ts_payload, outdir = run_simulation(ts1_path=actual_path, config=cfg_copy)
    except Exception as e:
        publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": False, "error": str(e)})
        raise

    publish_update(sim_id, {"type": "subtask_completed", "run_name": run_name, "ok": ok})

    return {
        "filename": Path(actual_path).name,
        "ok": ok,
        "peak_stage": float(summary.get("peak_stage_m") or summary.get("peak_stage", 0.0)),
        "peak_storage": float(summary.get("peak_storage_m3") or summary.get("total_infiltration", 0.0)),
        "inflow_total": float(summary.get("inflow_total_m3", 0.0)),
        "summary": summary,
        "timeseries": ts_payload
    }


@celery_app.task(bind=True)
def finalize_ilsax_ensemble(self, completed_runs: List[Dict], sim_id: str):
    """Chord callback to aggregate results from all ILSAX simulations and find critical duration."""
    # Group by duration
    grouped = {}
    for r in completed_runs:
        dur = str(r["run_info"]["duration_minutes"])
        if dur not in grouped:
            grouped[dur] = []
        grouped[dur].append(r)

    duration_summaries = {}
    for dur, runs in grouped.items():
        # Sort by peak stage descending
        runs_sorted = sorted(runs, key=lambda x: x["peak_stage"], reverse=True)

        # 5th highest is median if there are 10. We just take index 4 if len >= 5, else mid
        if len(runs_sorted) >= 10:
            median_run = runs_sorted[4]  # 5th highest
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

    publish_update(sim_id, {"type": "progress", "progress": 100, "message": "Simulation complete"})
    publish_update(sim_id, {"type": "complete", "results": results})
    return results


@celery_app.task(bind=True)
def finalize_ts1_batch(self, completed_runs: List[Dict], sim_id: str, config: Dict = None):
    """Chord callback to aggregate TS1 results and optionally calculate NSE for calibration."""
    if config is None:
        config = {}
        
    import re

    # Group by duration
    grouped = {}
    for r in completed_runs:
        filename = r.get("filename", "")
        # Look for e.g. "1 hour", "30 min", "120m"
        match = re.search(r'(\d+)\s*(hour|hr|h|min|minute|m)s?\b', filename, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            unit = match.group(2).lower()
            if unit.startswith('h'):
                dur = str(val * 60)
            else:
                dur = str(val)
        else:
            dur = "Unknown"
            
        if dur not in grouped:
            grouped[dur] = []
        grouped[dur].append(r)

    duration_summaries = {}
    for dur, runs in grouped.items():
        runs_sorted = sorted(runs, key=lambda x: x.get("peak_stage", 0.0), reverse=True)
        
        if len(runs_sorted) >= 10:
            median_run = runs_sorted[4]
        else:
            median_run = runs_sorted[len(runs_sorted) // 2]
            
        max_run = runs_sorted[0]
        
        duration_summaries[dur] = {
            "median_peak_stage": median_run.get("peak_stage", 0.0),
            "max_peak_stage": max_run.get("peak_stage", 0.0),
            "median_run": median_run,
            "max_run": max_run,
            "all_runs": runs_sorted
        }
        
    critical_dur = max(duration_summaries.keys(), key=lambda d: duration_summaries[d]["median_peak_stage"]) if duration_summaries else "Unknown"

    results = {
        "type": "ts1_ensemble",
        "durations": duration_summaries,
        "critical_duration": critical_dur,
        "runs": completed_runs # keep this for backward compatibility if needed, though not strictly required
    }

    observed_input = config.get("observed_data_file")
    if observed_input and len(completed_runs) == 1 and completed_runs[0].get("ok"):
        try:
            import pandas as pd
            import numpy as np
            import io
            
            if isinstance(observed_input, dict):
                content = observed_input.get("content", "")
                df_obs = pd.read_csv(io.StringIO(content))
            else:
                df_obs = pd.read_csv(observed_input)

            time_obs = df_obs.iloc[:, 0].values
            stage_obs = df_obs.iloc[:, 1].values
            
            # Read modeled data
            run_data = completed_runs[0]["timeseries"]
            time_mod = np.array(run_data["time_days"])
            stage_mod = np.array(run_data["stage_m"])
            
            # Interpolate modeled stage to match observed timestamps
            stage_mod_interp = np.interp(time_obs, time_mod, stage_mod)
            
            # Compute NSE
            mean_obs = np.mean(stage_obs)
            numerator = np.sum((stage_mod_interp - stage_obs)**2)
            denominator = np.sum((stage_obs - mean_obs)**2)
            
            if denominator > 0:
                nse = 1.0 - (numerator / denominator)
            else:
                nse = 0.0
                
            results["calibration"] = {
                "nse": float(nse),
                "observed_time": time_obs.tolist(),
                "observed_stage": stage_obs.tolist(),
                "modeled_interpolated": stage_mod_interp.tolist()
            }
            publish_update(sim_id, {"type": "progress", "progress": 95, "message": f"Calibration NSE calculated: {nse:.3f}"})
        except Exception as e:
            logger.error(f"Failed to calculate NSE: {e}", exc_info=True)
            results["calibration_error"] = str(e)

    publish_update(sim_id, {"type": "progress", "progress": 100, "message": "Simulation complete"})
    publish_update(sim_id, {"type": "complete", "results": results})
    return results


@celery_app.task(bind=True)
def simulation_error_callback(self, request, exc, traceback, sim_id: str):
    """Callback when a chord header task fails."""
    logger.error(f"Chord failed for sim {sim_id}: {exc}")
    publish_update(sim_id, {"type": "error", "message": f"Simulation failed: {exc}"})
