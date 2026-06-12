"""FastAPI backend for the SoakSIM web dashboard."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import jwt as pyjwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from ..hydraulics.optimizer import SoakwellDesignParameters, SoakwellOptimizer
from ..models.catalogue import DEFAULT_SOAKWELL_CATALOGUE
from ..models.common import AEP, Catchment, Coordinate, Project, ProjectSettings
from ..models.results import SoakwellDesign
from ..pipeline import DataRepository, run_full_pipeline

load_dotenv()

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

# ── Supabase JWT Authentication ─────────────────────────────────────────
# Supabase URL is used to locate the JWKS endpoint for ES256 token verification.
SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://rwtpoehohxbtobxrmedi.supabase.co"
)
_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_jwks_client = pyjwt.PyJWKClient(_JWKS_URL, cache_keys=True)

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    token: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict | None:
    """Verify the Supabase access-token JWT if present.

    Returns the decoded payload for authenticated users, or ``None``
    for anonymous requests (no Authorization header).
    """
    if token is None:
        return None
    try:
        # Fetch the matching public key from the Supabase JWKS endpoint
        signing_key = _jwks_client.get_signing_key_from_jwt(token.credentials)
        payload = pyjwt.decode(
            token.credentials,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.InvalidTokenError as exc:
        LOGGER.error("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


app = FastAPI(
    title="SoakSIM Dashboard",
    description="Free Australian soakwell sizing tool — powered by ARR temporal patterns",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Accept requests from any frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Append no-cache headers to all /static/ responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(NoCacheStaticMiddleware)

# ── Pydantic request / response schemas ──────────────────────────────────


class CatchmentIn(BaseModel):
    name: str = "Roof"
    area_ha: float = Field(0.05, gt=0, description="Catchment area in hectares")
    slope: float = Field(0.01, gt=0)
    # ILSAX surface fractions (must sum to 1.0)
    paved_fraction: float = Field(0.90, ge=0, le=1, description="Directly-connected impervious")
    supplementary_fraction: float = Field(0.0, ge=0, le=1, description="Indirectly-connected impervious")
    grassed_fraction: float = Field(0.10, ge=0, le=1, description="Pervious / grassed")
    # Horton soil type (1=A sandy … 4=D clay)
    soil_type: float = Field(2.0, ge=1, le=4)
    # Antecedent moisture condition (1=dry … 4=saturated)
    amc: float = Field(2.0, ge=1, le=4)
    # ── Detailed flow-path parameters (Ragan & Duru Eq) ──────────────
    # Additional (constant) time per surface (minutes)
    paved_additional_time_minutes: float = Field(0.0, ge=0)
    supplementary_additional_time_minutes: float = Field(0.0, ge=0)
    grassed_additional_time_minutes: float = Field(0.0, ge=0)
    # Flow path length (metres)
    paved_flow_path_length_m: float = Field(15.0, ge=0)
    supplementary_flow_path_length_m: float = Field(10.0, ge=0)
    grassed_flow_path_length_m: float = Field(20.0, ge=0)
    # Flow path slope (percent)
    paved_flow_path_slope_pct: float = Field(1.0, gt=0)
    supplementary_flow_path_slope_pct: float = Field(2.0, gt=0)
    grassed_flow_path_slope_pct: float = Field(2.0, gt=0)
    # Retardance coefficient n* (Woolhiser 1975)
    paved_n_star: float = Field(0.011, gt=0)
    supplementary_n_star: float = Field(0.013, gt=0)
    grassed_n_star: float = Field(0.25, gt=0)
    # Depression storages (mm)
    paved_depression_storage_mm: float = Field(1.0, ge=0)
    supplementary_depression_storage_mm: float = Field(1.0, ge=0)
    grassed_depression_storage_mm: float = Field(5.0, ge=0)


class SoakwellConfigIn(BaseModel):
    """User-specified soakwell configuration: a catalogue size + number of units."""
    size_name: str = Field("1200 x 1200", description="Name from the soakwell catalogue")
    count: int = Field(1, ge=1, le=50, description="Number of soakwells")


class SimulationRequest(BaseModel):
    latitude: float = Field(-31.95, ge=-44.0, le=-10.0, description="Latitude (Australian)")
    longitude: float = Field(115.86, ge=112.0, le=154.0, description="Longitude (Australian)")
    catchments: List[CatchmentIn] = Field(default_factory=lambda: [CatchmentIn()])
    aep_percentages: List[float] = Field(default_factory=lambda: [10.0, 5.0])
    durations_minutes: List[int] = Field(default_factory=lambda: [30, 60])
    infiltration_rate_mm_per_hr: float = Field(50.0, gt=0)
    design_drain_time_hours: float = Field(24.0, gt=0)
    soil_moderation_factor: float = Field(0.5, gt=0, description="Soil moderation factor (U): Sand=0.5, Sandy Clay=1.0, Medium/Heavy Clay=2.0")
    pattern_rank: int = Field(4, ge=1, le=10)
    design_aep_percent: Optional[float] = Field(None, gt=0, description="If omitted, uses the smallest (rarest) selected AEP")
    soakwell_config: List[SoakwellConfigIn] = Field(default_factory=list)
    use_live_data: bool = False
    climate_scenario: Optional[str] = Field("Historical", description="SSP scenario: Historical, SSP1-2.6, SSP2-4.5, SSP3-7.0, SSP5-8.5")
    climate_epoch: Optional[int] = Field(None, description="Planning horizon year: 2030–2100")


class RunoffRow(BaseModel):
    aep: str
    duration_minutes: int
    pattern_rank: int
    peak_discharge_cms: float
    runoff_volume_m3: float
    time_to_peak_minutes: float


class SoakwellDesignOut(BaseModel):
    aep: str
    critical_duration_minutes: int
    selected_pattern_rank: int
    required_storage_m3: float
    residual_storage_m3: float
    infiltration_shortfall_m3: float
    drain_time_hours: float
    configuration: Dict[str, int]


class HyetographOut(BaseModel):
    key: str
    timestep_minutes: float
    depths_mm: List[float]


class HydrographOut(BaseModel):
    key: str
    timestep_minutes: float
    discharge_cms: List[float]


class SoakwellTimeSeriesOut(BaseModel):
    timestep_minutes: float
    time_minutes: List[float]
    cumulative_inflow_m3: List[float]
    storage_volume_m3: List[float]
    depth_m: List[float]
    cumulative_infiltration_m3: List[float]
    spill_flag: List[bool] = []
    cumulative_overflow_m3: List[float] = []


class SimulationResponse(BaseModel):
    project_name: str
    climate_scenario_label: str = "Historical"
    runoff_table: List[RunoffRow]
    soakwell_design: Optional[SoakwellDesignOut] = None
    soakwell_timeseries: Optional[SoakwellTimeSeriesOut] = None
    hyetographs: List[HyetographOut] = []
    hydrographs: List[HydrographOut] = []
    warnings: List[str] = []


class CatalogueItem(BaseModel):
    name: str
    diameter_mm: int
    height_mm: int
    void_ratio: float
    storage_volume_m3: float
    side_area_m2: float
    base_area_m2: float


# ── API routes ───────────────────────────────────────────────────────────


@app.get("/help")
async def help_page():
    return FileResponse(
        STATIC_DIR / "help.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/login")
async def login_page():
    return FileResponse(
        STATIC_DIR / "login.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/")
async def root():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/catalogue")
async def get_catalogue() -> List[CatalogueItem]:
    from ..models.catalogue import DEFAULT_SOAKWELL_CATALOGUE

    return [
        CatalogueItem(
            name=s.name,
            diameter_mm=s.diameter_mm,
            height_mm=s.height_mm,
            void_ratio=s.void_ratio,
            storage_volume_m3=round(s.storage_volume_m3, 4),
            side_area_m2=round(s.side_area_m2, 4),
            base_area_m2=round(s.base_area_m2, 4),
        )
        for s in DEFAULT_SOAKWELL_CATALOGUE.sizes()
    ]


@app.get("/api/aep-options")
async def aep_options():
    return [{"value": a.value, "label": a.to_label()} for a in AEP]


@app.post("/api/simulate", response_model=SimulationResponse)
async def simulate(req: SimulationRequest, _user: dict | None = Depends(get_current_user)):
    warnings: List[str] = []
    # Design AEP defaults to the smallest (rarest) selected AEP
    design_aep_pct = req.design_aep_percent or min(req.aep_percentages)
    try:
        design_aep = AEP.from_percent(design_aep_pct)
    except ValueError:
        raise HTTPException(422, f"Unsupported design AEP: {design_aep_pct}%")

    # Ensure the design AEP is always included in the computed set
    aep_set = set(req.aep_percentages)
    aep_set.add(design_aep_pct)
    try:
        ae_ps = tuple(AEP.from_percent(p) for p in sorted(aep_set, reverse=True))
    except ValueError as exc:
        raise HTTPException(422, f"Invalid AEP: {exc}")

    catchments = tuple(
        Catchment(
            name=c.name,
            area_ha=c.area_ha,
            slope=c.slope,
            paved_fraction=c.paved_fraction,
            supplementary_fraction=c.supplementary_fraction,
            grassed_fraction=c.grassed_fraction,
            soil_type=c.soil_type,
            amc=c.amc,
            paved_additional_time_minutes=c.paved_additional_time_minutes,
            supplementary_additional_time_minutes=c.supplementary_additional_time_minutes,
            grassed_additional_time_minutes=c.grassed_additional_time_minutes,
            paved_flow_path_length_m=c.paved_flow_path_length_m,
            supplementary_flow_path_length_m=c.supplementary_flow_path_length_m,
            grassed_flow_path_length_m=c.grassed_flow_path_length_m,
            paved_flow_path_slope_pct=c.paved_flow_path_slope_pct,
            supplementary_flow_path_slope_pct=c.supplementary_flow_path_slope_pct,
            grassed_flow_path_slope_pct=c.grassed_flow_path_slope_pct,
            paved_n_star=c.paved_n_star,
            supplementary_n_star=c.supplementary_n_star,
            grassed_n_star=c.grassed_n_star,
            paved_depression_storage_mm=c.paved_depression_storage_mm,
            supplementary_depression_storage_mm=c.supplementary_depression_storage_mm,
            grassed_depression_storage_mm=c.grassed_depression_storage_mm,
        )
        for c in req.catchments
    )

    project = Project(
        coordinate=Coordinate(latitude=req.latitude, longitude=req.longitude),
        catchments=catchments,
        settings=ProjectSettings(
            ae_ps=ae_ps,
            durations_minutes=tuple(req.durations_minutes),
        ),
        additional_metadata={"project_name": "SoakSIM Dashboard"},
    )

    params = SoakwellDesignParameters(
        infiltration_rate_mm_per_hr=req.infiltration_rate_mm_per_hr,
        design_drain_time_hours=req.design_drain_time_hours,
        storage_safety_factor=req.soil_moderation_factor,
    )

    data_repo = DataRepository(use_live_data=req.use_live_data)

    try:
        report = run_full_pipeline(
            project=project,
            soakwell_params=params,
            data_repo=data_repo,
            aep_for_design=design_aep,
            pattern_rank=req.pattern_rank,
            climate_scenario=req.climate_scenario,
            climate_epoch=req.climate_epoch,
            run_optimizer=False,
        )
    except Exception as exc:
        LOGGER.exception("Simulation failed")
        raise HTTPException(500, f"Simulation error: {exc}")

    # Build runoff table
    runoff_table = [
        RunoffRow(
            aep=res.aep.to_label(),
            duration_minutes=res.duration_minutes,
            pattern_rank=res.pattern_rank,
            peak_discharge_cms=round(res.peak_discharge_cms, 6),
            runoff_volume_m3=round(res.runoff_volume_m3, 3),
            time_to_peak_minutes=round(res.time_to_peak_minutes, 1),
        )
        for res in sorted(
            report.runoff_results.values(),
            key=lambda r: (r.aep.value, r.duration_minutes, r.pattern_rank),
        )
    ]

    optimizer = SoakwellOptimizer(catalogue=DEFAULT_SOAKWELL_CATALOGUE)

    # Build user-specified soakwell configuration
    user_config: Dict[str, int] = {}
    for sc in req.soakwell_config:
        try:
            DEFAULT_SOAKWELL_CATALOGUE.find(sc.size_name)
        except KeyError:
            raise HTTPException(422, f"Unknown soakwell size: {sc.size_name}")
        user_config[sc.size_name] = user_config.get(sc.size_name, 0) + sc.count

    # ── Critical storm = temporal pattern + duration producing max soakwell depth ──
    # For each duration at the design AEP, route ALL temporal patterns through
    # the soakwell.  Rank by peak depth and adopt the Nth highest (pattern_rank).
    # Then across durations, pick the one with the greatest peak depth.
    tmp_design = SoakwellDesign(
        aep=design_aep,
        critical_duration_minutes=0,
        selected_pattern_rank=req.pattern_rank,
        required_storage_m3=0.0,
        infiltration_shortfall_m3=0.0,
        configuration=user_config,
        residual_storage_m3=0.0,
        drain_time_hours=params.design_drain_time_hours,
        notes="temporary",
    )

    critical = None
    critical_ts = None
    max_depth = -1.0
    adopted_pattern_number: int = 0

    for (res_aep, _dur), ensemble in report.ensembles.items():
        if res_aep != design_aep:
            continue
        if not ensemble.results:
            continue

        # Route every pattern for this duration and collect (peak_depth, result, ts)
        routed = []
        for r in ensemble.results:
            ts = optimizer.route_through_soakwell(
                hydrograph=r,
                design=tmp_design,
                params=params,
            )
            peak_depth = max(ts.depth_m) if ts.depth_m else 0.0
            routed.append((peak_depth, r, ts))

        # Rank by peak depth descending
        routed.sort(key=lambda x: x[0], reverse=True)

        # Pick the Nth highest (1-based pattern_rank)
        idx = min(req.pattern_rank, len(routed)) - 1
        chosen_depth, chosen_result, chosen_ts = routed[idx]

        if chosen_depth > max_depth:
            max_depth = chosen_depth
            critical = chosen_result
            critical_ts = chosen_ts
            adopted_pattern_number = chosen_result.pattern_rank

    # Compute storage requirement (net of infiltration during storm)
    storage_requirement = 0.0
    if critical:
        infil_during_storm = 0.0
        for name, count in user_config.items():
            size = DEFAULT_SOAKWELL_CATALOGUE.find(name)
            rate = optimizer._unit_infiltration_rate_m3_per_hr(size, params)
            infil_during_storm += count * rate * (critical.duration_minutes / 60.0)
        net_inflow = max(0.0, critical.runoff_volume_m3 - infil_during_storm)
        storage_requirement = net_inflow * params.storage_safety_factor

    # Storage / infiltration metrics
    total_storage_m3 = 0.0
    total_infil_capacity_m3 = 0.0
    for name, count in user_config.items():
        size = DEFAULT_SOAKWELL_CATALOGUE.find(name)
        total_storage_m3 += count * optimizer._unit_storage(size)
        total_infil_capacity_m3 += count * optimizer._unit_infiltration(size, params)
    residual_storage = total_storage_m3 - storage_requirement
    infil_shortfall = max(0.0, storage_requirement - total_infil_capacity_m3)

    # ── Compute actual drain time from the time-series ──
    # Drain time = time between end of storm inflow and depth reaching zero
    actual_drain_time_hours = 0.0
    if critical_ts and critical:
        storm_end_minutes = len(critical.discharge_cms) * critical.timestep_minutes
        drain_end_minutes = storm_end_minutes  # fallback
        for j in range(len(critical_ts.time_minutes) - 1, -1, -1):
            if critical_ts.depth_m[j] > 1e-6:
                drain_end_minutes = critical_ts.time_minutes[j]
                if j + 1 < len(critical_ts.time_minutes):
                    drain_end_minutes = critical_ts.time_minutes[j + 1]
                break
        actual_drain_time_hours = max(0.0, (drain_end_minutes - storm_end_minutes) / 60.0)

    # Store the critical storm time-series for the performance chart
    if critical_ts:
        report.soakwell_time_series = critical_ts

    design_out = None
    if critical:
        design_out = SoakwellDesignOut(
            aep=design_aep.to_label(),
            critical_duration_minutes=critical.duration_minutes,
            selected_pattern_rank=adopted_pattern_number,
            required_storage_m3=round(storage_requirement, 3),
            residual_storage_m3=round(residual_storage, 3),
            infiltration_shortfall_m3=round(infil_shortfall, 3),
            drain_time_hours=round(actual_drain_time_hours, 2),
            configuration=user_config,
        )

    # Hyetographs (first 3 ranks of the design AEP + critical duration)
    hyetographs_out: List[HyetographOut] = []
    for (aep, dur, rank), hyeto in sorted(report.hyetographs.items(), key=lambda kv: (kv[0][0].value, kv[0][1], kv[0][2])):
        hyetographs_out.append(HyetographOut(
            key=f"{aep.to_label()} {dur}min Rank {rank}",
            timestep_minutes=hyeto.timestep_minutes,
            depths_mm=[round(d, 4) for d in hyeto.depths_mm],
        ))

    # Hydrographs
    hydrographs_out: List[HydrographOut] = []
    for (aep, dur, rank), res in sorted(report.runoff_results.items(), key=lambda kv: (kv[0][0].value, kv[0][1], kv[0][2])):
        hydrographs_out.append(HydrographOut(
            key=f"{aep.to_label()} {dur}min Rank {rank}",
            timestep_minutes=res.timestep_minutes,
            discharge_cms=[round(d, 6) for d in res.discharge_cms],
        ))

    # Soakwell time-series
    soakwell_ts_out = None
    if report.soakwell_time_series is not None:
        ts = report.soakwell_time_series
        soakwell_ts_out = SoakwellTimeSeriesOut(
            timestep_minutes=ts.timestep_minutes,
            time_minutes=ts.time_minutes,
            cumulative_inflow_m3=[round(v, 4) for v in ts.cumulative_inflow_m3],
            storage_volume_m3=[round(v, 4) for v in ts.storage_volume_m3],
            depth_m=[round(v, 4) for v in ts.depth_m],
            cumulative_infiltration_m3=[round(v, 4) for v in ts.cumulative_infiltration_m3],
            spill_flag=ts.spill_flag,
            cumulative_overflow_m3=[round(v, 4) for v in ts.cumulative_overflow_m3],
        )

    # Build climate scenario label
    scenario = req.climate_scenario or "Historical"
    if scenario == "Historical":
        cc_label = "Historical"
    else:
        epoch_str = str(req.climate_epoch) if req.climate_epoch else ""
        cc_label = f"{scenario} ({epoch_str})" if epoch_str else scenario

    return SimulationResponse(
        project_name=report.project_name,
        climate_scenario_label=cc_label,
        runoff_table=runoff_table,
        soakwell_design=design_out,
        soakwell_timeseries=soakwell_ts_out,
        hyetographs=hyetographs_out,
        hydrographs=hydrographs_out,
        warnings=warnings,
    )


# ── Mount static files last (catch-all) ─────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
