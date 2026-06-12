"""
DEM Parser for BaSIM – read elevation grids from DEM files.

Supports USGS DEM (*.dem) and GeoTIFF (*.tif/*.tiff) formats.
Returns a raw DEMGrid dataclass suitable for direct MODFLOW model
construction (no rectangular approximation – the grid IS the model).

The parser is CRS-agnostic: it reads cell sizes in whatever linear units
the DEM uses.  For GeoTIFF with geographic (lat/lon) CRS a warning flag
is set so the caller can alert the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class DEMGrid:
    """Raw elevation grid extracted from a DEM file."""

    grid: np.ndarray            # 2-D float array (nrow, ncol); NaN = nodata
    cell_size_x: float          # ground units (usually metres)
    cell_size_y: float          # ground units (usually metres)
    x_origin: float             # easting of grid origin (lower-left or upper-left)
    y_origin: float             # northing of grid origin
    file_path: str
    n_rows: int = 0
    n_cols: int = 0
    crs_info: str = ""          # human-readable CRS string (empty if unknown)
    is_geographic: bool = False  # True if CRS is lat/lon (degrees)

    def __post_init__(self):
        self.n_rows, self.n_cols = self.grid.shape

    # convenient derived properties ----------------------------------------
    @property
    def valid_mask(self) -> np.ndarray:
        """Boolean mask of cells with valid (non-NaN) elevation."""
        return ~np.isnan(self.grid)

    @property
    def min_elev(self) -> float:
        return float(np.nanmin(self.grid))

    @property
    def max_elev(self) -> float:
        return float(np.nanmax(self.grid))

    @property
    def cell_area(self) -> float:
        """Area of a single cell in ground units²."""
        return self.cell_size_x * self.cell_size_y

    @property
    def extent_x(self) -> float:
        return self.n_cols * self.cell_size_x

    @property
    def extent_y(self) -> float:
        return self.n_rows * self.cell_size_y


# ---------------------------------------------------------------------------
# USGS DEM Parser
# ---------------------------------------------------------------------------

def _parse_usgs_dem(path: Path) -> DEMGrid:
    """Parse a USGS 7.5-minute / 1-degree DEM file.

    The USGS native DEM format stores an *A record* (header) followed by
    one *B record* per profile (south-to-north column).  Each B record
    begins with a small header then integer elevation values.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")

    # Regex to locate profile (B-record) headers:
    #   "1  <col>  <npts>  1  <easting>D±nn  <northing>D±nn  ..."
    profile_pat = re.compile(
        r'\s+1\s+(\d+)\s+(\d+)\s+1\s+'   # "1  col  npts  1"
        r'(\d+\.\d+D[+\-]\d+)\s+'        # easting
        r'(\d+\.\d+D[+\-]\d+)\s+'        # northing
        r'(\d+\.\d+D[+\-]\d+)\s+'        # local_datum_elev
        r'(\d+\.\d+D[+\-]\d+)\s+'        # min_elev
        r'(\d+\.\d+D[+\-]\d+)'           # max_elev
    )

    profiles: list[dict] = []
    for m in profile_pat.finditer(raw):
        col_idx = int(m.group(1))
        n_pts = int(m.group(2))
        easting = float(m.group(3).replace("D", "E"))
        northing = float(m.group(4).replace("D", "E"))
        profiles.append({
            "col": col_idx,
            "n_pts": n_pts,
            "easting": easting,
            "northing": northing,
            "text_start": m.end(),
        })

    if not profiles:
        raise ValueError(
            "Could not find any profile records in the DEM file. "
            "Ensure this is a valid USGS DEM (*.dem) file."
        )

    n_profiles = len(profiles)
    n_rows = profiles[0]["n_pts"]
    nodata = -32767

    grid = np.full((n_rows, n_profiles), np.nan)
    eastings: list[float] = []
    northings: list[float] = []

    for i, prof in enumerate(profiles):
        eastings.append(prof["easting"])
        northings.append(prof["northing"])

        # Find text span for this profile's elevation values
        if i + 1 < n_profiles:
            next_match = profile_pat.search(raw, prof["text_start"])
            end = next_match.start() if next_match else len(raw)
        else:
            end = len(raw)

        chunk = raw[prof["text_start"]:end]
        ints = re.findall(r'-?\d+', chunk)

        elevs = []
        for v in ints:
            iv = int(v)
            elevs.append(iv)
            if len(elevs) >= prof["n_pts"]:
                break

        for j, e in enumerate(elevs):
            if j < n_rows:
                grid[j, i] = np.nan if e == nodata else float(e)

    # Cell size from coordinate spacing
    if len(eastings) >= 2:
        cell_x = abs(eastings[1] - eastings[0])
    else:
        cell_x = 1.0
    cell_y = cell_x  # USGS DEM profiles are square-cell by convention

    x_origin = min(eastings) if eastings else 0.0
    y_origin = min(northings) if northings else 0.0

    return DEMGrid(
        grid=grid,
        cell_size_x=cell_x,
        cell_size_y=cell_y,
        x_origin=x_origin,
        y_origin=y_origin,
        file_path=str(path),
        crs_info="USGS DEM (projected, units assumed metres)",
        is_geographic=False,
    )


# ---------------------------------------------------------------------------
# GeoTIFF Parser (requires rasterio)
# ---------------------------------------------------------------------------

def _parse_geotiff(path: Path) -> DEMGrid:
    """Parse a GeoTIFF DEM using rasterio."""
    try:
        import rasterio  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'rasterio' package is required to read GeoTIFF DEMs.\n"
            "Install it with: pip install rasterio"
        )

    with rasterio.open(str(path)) as src:
        band = src.read(1).astype(float)
        nodata = src.nodata
        if nodata is not None:
            band[band == nodata] = np.nan

        cell_x = abs(src.res[0])
        cell_y = abs(src.res[1])

        # Extract CRS info and detect geographic (lat/lon) systems
        crs_info = ""
        is_geographic = False
        try:
            crs = src.crs
            if crs is not None:
                crs_info = crs.to_string()
                is_geographic = crs.is_geographic
        except Exception:
            pass

        # Origin from transform
        transform = src.transform
        x_origin = transform.c  # upper-left x
        y_origin = transform.f  # upper-left y

    return DEMGrid(
        grid=band,
        cell_size_x=cell_x,
        cell_size_y=cell_y,
        x_origin=x_origin,
        y_origin=y_origin,
        file_path=str(path),
        crs_info=crs_info,
        is_geographic=is_geographic,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_dem_file(file_path: str | Path) -> DEMGrid:
    """Parse a DEM file and return the raw elevation grid.

    Supported formats:
      - USGS DEM (.dem)
      - GeoTIFF (.tif, .tiff) – requires rasterio

    If the DEM has a geographic (lat/lon) CRS, ``DEMGrid.is_geographic``
    will be True.  The caller should warn the user to reproject.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"DEM file not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".dem":
        return _parse_usgs_dem(p)
    elif suffix in (".tif", ".tiff"):
        return _parse_geotiff(p)
    else:
        # Try USGS format as fallback
        try:
            return _parse_usgs_dem(p)
        except Exception:
            raise ValueError(
                f"Unsupported DEM file extension '{suffix}'. "
                "Use .dem (USGS) or .tif/.tiff (GeoTIFF)."
            )
