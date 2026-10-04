"""BaSIM FastAPI service for auth, billing, and durable analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

from src.api.billing import router as billing_router
from src.api.legal import router as legal_router
from src.api.routes.analyses import router as analyses_router
from src.api.routes.jobs import router as jobs_router


app = FastAPI(
    title="BaSIM API",
    description="Authenticated GAH-3D basin design and clogging analyses",
    version="4.0.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("BASIM_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.onrender\.com|https://.*\.innealta\.com\.au",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(billing_router, prefix="/api/billing")
app.include_router(legal_router)
app.include_router(analyses_router)
app.include_router(jobs_router)


SOIL_PROFILES = (
    ("Sand", 0.045, 0.430, 14.50, 2.68, 0.27),
    ("Loamy Sand", 0.057, 0.410, 12.40, 2.28, 0.25),
    ("Sandy Loam", 0.065, 0.410, 7.50, 1.89, 0.20),
    ("Loam", 0.078, 0.430, 3.60, 1.56, 0.13),
    ("Silt Loam", 0.067, 0.450, 2.00, 1.41, 0.13),
    ("Silt", 0.034, 0.460, 1.60, 1.37, 0.10),
    ("Sandy Clay Loam", 0.100, 0.390, 5.90, 1.48, 0.13),
    ("Clay Loam", 0.095, 0.410, 1.90, 1.31, 0.08),
    ("Silty Clay Loam", 0.089, 0.430, 1.00, 1.23, 0.06),
    ("Sandy Clay", 0.100, 0.380, 2.70, 1.23, 0.05),
    ("Silty Clay", 0.070, 0.360, 0.50, 1.09, 0.04),
    ("Clay", 0.068, 0.380, 0.80, 1.09, 0.03),
)

WA_SOIL_WMS_URL = (
    "https://public-services.slip.wa.gov.au/public/services/"
    "SLIP_Public_Services/Soil_Landscape/MapServer/WMSServer"
)
WEB_MERCATOR_RADIUS_M = 6_378_137


@app.get("/")
def root() -> dict:
    return {"name": "BaSIM API", "version": app.version}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/soil-profiles")
def soil_profiles() -> list[dict]:
    return [
        {
            "name": name,
            "theta_r": theta_r,
            "theta_s": theta_s,
            "alpha_per_m": alpha_per_m,
            "n_vg": n_vg,
            "specific_yield": specific_yield,
        }
        for name, theta_r, theta_s, alpha_per_m, n_vg, specific_yield in SOIL_PROFILES
    ]


@app.get("/api/soil-type")
def soil_type(
    lat: float = Query(..., ge=-85.05112878, le=85.05112878),
    lng: float = Query(..., ge=-180, le=180),
) -> dict[str, str | None]:
    longitude_rad = math.radians(lng)
    latitude_rad = math.radians(lat)
    x = WEB_MERCATOR_RADIUS_M * longitude_rad
    y = WEB_MERCATOR_RADIUS_M * math.log(math.tan(math.pi / 4 + latitude_rad / 2))
    pixel_radius_m = 0.5
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": "0",
        "QUERY_LAYERS": "0",
        "STYLES": "",
        "CRS": "EPSG:3857",
        "BBOX": (
            f"{x - pixel_radius_m},{y - pixel_radius_m},"
            f"{x + pixel_radius_m},{y + pixel_radius_m}"
        ),
        "WIDTH": "1",
        "HEIGHT": "1",
        "I": "0",
        "J": "0",
        "INFO_FORMAT": "application/geo+json",
        "FEATURE_COUNT": "1",
    }

    try:
        response = requests.get(WA_SOIL_WMS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="WA soil type service is unavailable",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="WA soil type service returned invalid data",
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise HTTPException(
            status_code=502,
            detail="WA soil type service returned invalid data",
        )
    features = data["features"]
    if not features:
        return {"soil_type": None}
    feature = features[0]
    if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
        raise HTTPException(
            status_code=502,
            detail="WA soil type service returned invalid feature data",
        )
    soil_type = feature["properties"].get("Decoded WA Soil Group description")
    if not isinstance(soil_type, str) or not soil_type:
        raise HTTPException(
            status_code=502,
            detail="WA soil type service returned no soil group description",
        )
    return {
        "soil_type": soil_type,
    }