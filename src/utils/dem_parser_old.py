"""
DEM Parser for BaSIM – extract basin geometry from USGS DEM files.

Supports USGS DEM (*.dem) and GeoTIFF (*.tif/*.tiff) formats.
Derives a depth–area relationship and approximate rectangular basin parameters
(length, width, max_depth, floor_elevation) from the elevation grid.

The key concept:
  1. Read the DEM grid of elevations.
  2. Identify the basin as the depression (cells below the surrounding rim/crest).
  3. Build a depth→surface‑area table by counting cells at each relative depth.
  4. Derive bounding‑box based length/width and approximate side slope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DEMSummary:
    """Summarised basin information extracted from a DEM."""
    file_path: str
    # Grid metadata
    n_rows: int
    n_cols: int
    cell_size_x: float  # metres
    cell_size_y: float  # metres
    # Derived rectangular approximation
    length_floor: float   # m – x‑extent of the lowest region
    width_floor: float    # m – y‑extent of the lowest region
    max_depth: float      # m – crest_elev − floor_elev
    floor_elev: float     # m – minimum valid elevation
    crest_elev: float     # m – maximum valid elevation (rim)
    side_slope_hv: float  # approximate horizontal:vertical
    # Depth–area table: list of (depth_m, area_m2) sorted by depth ascending
    depth_area: List[Tuple[float, float]] = field(default_factory=list)
    # Full grid for visualisation (valid cells only; nodata→NaN)
    grid: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# USGS DEM Parser
# ---------------------------------------------------------------------------

def _parse_usgs_dem(path: Path) -> DEMSummary:
    """Parse a USGS 7.5‑minute / 1‑degree DEM file.

    The USGS native DEM format stores an *A record* (header) followed by
    one *B record* per profile (south→north column).  Each B record begins
    with a small header (row/col, number of elevations, geographic anchor …)
    then the integer elevation values.

    We make a best‑effort parse by:
      1. Reading the entire file as text.
      2. Extracting all integer tokens.
      3. Skipping known header/profile‑header metadata.
      4. Assembling the remaining integers into an elevation grid.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")

    # ── Approach: split into profiles using the record‑B header pattern ──
    # Each profile header starts with "  1  <col>  <nrows>  1" at fixed
    # positions.  We search for all occurrences of a pattern like
    #   "     1    <N>   120     1" where <N> is the profile (column) number
    # and 120 is the number of elevations in the profile.

    # Regex to find profile headers: "1  <col>  <npts>  1  <easting>D+<exp>  <northing>D+<exp>  …"
    # We'll use a simpler strategy: find all profile header blocks.

    # Pattern: whitespace‑padded "1" then column number then npts then "1"
    # followed by Fortran‑D scientific floats for coords.
    profile_pat = re.compile(
        r'\s+1\s+(\d+)\s+(\d+)\s+1\s+'  # "1  col  npts  1"
        r'(\d+\.\d+D[+\-]\d+)\s+'       # easting
        r'(\d+\.\d+D[+\-]\d+)\s+'       # northing
        r'(\d+\.\d+D[+\-]\d+)\s+'       # local_datum_elev
        r'(\d+\.\d+D[+\-]\d+)\s+'       # min_elev
        r'(\d+\.\d+D[+\-]\d+)'          # max_elev
    )

    profiles: list[dict] = []
    for m in profile_pat.finditer(raw):
        col_idx = int(m.group(1))
        n_pts = int(m.group(2))
        easting = float(m.group(3).replace("D", "E"))
        northing = float(m.group(4).replace("D", "E"))
        min_elev = float(m.group(6).replace("D", "E"))
        max_elev = float(m.group(7).replace("D", "E"))
        start = m.end()
        profiles.append({
            "col": col_idx,
            "n_pts": n_pts,
            "easting": easting,
            "northing": northing,
            "min_elev": min_elev,
            "max_elev": max_elev,
            "text_start": start,
        })

    if not profiles:
        raise ValueError("Could not find any profile records in the DEM file. "
                         "Ensure this is a valid USGS DEM (*.dem) file.")

    n_profiles = len(profiles)
    n_rows = profiles[0]["n_pts"]
    nodata = -32767

    # Parse elevation values from each profile
    grid = np.full((n_rows, n_profiles), np.nan)
    eastings: list[float] = []
    northings: list[float] = []

    for i, prof in enumerate(profiles):
        eastings.append(prof["easting"])
        northings.append(prof["northing"])
        # Extract integer tokens between this profile header end and next profile start
        end = profiles[i + 1]["text_start"] - 200 if i + 1 < n_profiles else len(raw)
        # Go back a bit for safety on end boundary
        if i + 1 < n_profiles:
            # Find the start of next profile match by searching from prof end
            next_match = profile_pat.search(raw, prof["text_start"])
            end = next_match.start() if next_match else len(raw)

        chunk = raw[prof["text_start"]:end]
        # Extract integers (including negative)
        ints = re.findall(r'-?\d+', chunk)
        # Take only n_pts values
        elevs = []
        for v in ints:
            iv = int(v)
            elevs.append(iv)
            if len(elevs) >= prof["n_pts"]:
                break
        for j, e in enumerate(elevs):
            if j < n_rows:
                grid[j, i] = np.nan if e == nodata else float(e)

    # Compute cell sizes from coordinate spacing
    if len(eastings) >= 2:
        cell_x = abs(eastings[1] - eastings[0])
    else:
        cell_x = 1.0
    cell_y = cell_x  # assume square cells for USGS DEM

    return _summarise_grid(grid, cell_x, cell_y, str(path))


# ---------------------------------------------------------------------------
# GeoTIFF Parser (optional – uses rasterio if available)
# ---------------------------------------------------------------------------

def _parse_geotiff(path: Path) -> DEMSummary:
    """Parse a GeoTIFF DEM using rasterio (optional dependency)."""
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
    return _summarise_grid(band, cell_x, cell_y, str(path))


# ---------------------------------------------------------------------------
# Grid summarisation (shared logic)
# ---------------------------------------------------------------------------

def _summarise_grid(grid: np.ndarray, cell_x: float, cell_y: float, file_path: str) -> DEMSummary:
    """Derive basin geometry from a 2‑D elevation grid.

    Steps:
      1. Mask nodata (NaN).
      2. Floor = minimum elevation; crest = maximum elevation.
      3. Build depth→area table at 0.5 m increments.
      4. Estimate rectangular length/width from the bounding box of the lowest 10% of cells.
      5. Approximate side slope from horizontal run / vertical rise of basin perimeter.
    """
    n_rows, n_cols = grid.shape
    valid = ~np.isnan(grid)
    if valid.sum() < 4:
        raise ValueError("DEM has too few valid elevation cells to derive basin geometry.")

    floor_elev = float(np.nanmin(grid))
    crest_elev = float(np.nanmax(grid))
    max_depth = crest_elev - floor_elev

    if max_depth < 0.01:
        raise ValueError(f"DEM has negligible relief ({max_depth:.3f} m). Cannot derive basin.")

    # -- depth–area table --
    # depth is measured from the crest downward: at depth d, water surface = crest − d
    # surface area at that level = count of cells whose elevation ≤ (crest − d) × cell area
    # BUT more useful for basin modelling: depth from floor.
    # depth from floor d → water level = floor + d → area = cells with elev ≤ floor + d
    n_steps = min(100, max(10, int(max_depth / 0.5) + 1))
    depth_area: List[Tuple[float, float]] = []
    for i in range(n_steps + 1):
        d = max_depth * i / n_steps
        water_level = floor_elev + d
        count = np.sum(grid[valid] <= water_level)
        area = float(count) * cell_x * cell_y
        depth_area.append((round(d, 4), round(area, 2)))

    # -- bounding box of lowest 10% cells → approximate floor length/width --
    threshold = floor_elev + 0.1 * max_depth
    low_mask = (grid <= threshold) & valid
    low_rows, low_cols = np.where(low_mask)
    if len(low_rows) < 1:
        # Fallback: use entire valid region
        low_rows, low_cols = np.where(valid)

    row_span = (low_rows.max() - low_rows.min() + 1) * cell_y
    col_span = (low_cols.max() - low_cols.min() + 1) * cell_x
    length_floor = max(col_span, row_span)
    width_floor = min(col_span, row_span)
    # Ensure minimum sizes
    length_floor = max(1.0, length_floor)
    width_floor = max(1.0, width_floor)

    # -- approximate side slope --
    # Average horizontal run from floor edge to crest, divided by vertical rise
    # Use the full valid extent vs the floor extent as proxy
    all_rows, all_cols = np.where(valid)
    full_row_span = (all_rows.max() - all_rows.min() + 1) * cell_y
    full_col_span = (all_cols.max() - all_cols.min() + 1) * cell_x
    h_run_x = max(0, (full_col_span - length_floor) / 2)
    h_run_y = max(0, (full_row_span - width_floor) / 2)
    h_run = max(h_run_x, h_run_y)
    if max_depth > 0.01:
        side_slope = round(h_run / max_depth, 1)
    else:
        side_slope = 3.0
    side_slope = max(0.0, min(20.0, side_slope))  # clamp

    return DEMSummary(
        file_path=file_path,
        n_rows=n_rows,
        n_cols=n_cols,
        cell_size_x=cell_x,
        cell_size_y=cell_y,
        length_floor=round(length_floor, 1),
        width_floor=round(width_floor, 1),
        max_depth=round(max_depth, 2),
        floor_elev=round(floor_elev, 2),
        crest_elev=round(crest_elev, 2),
        side_slope_hv=side_slope,
        depth_area=depth_area,
        grid=grid,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_dem_file(file_path: str | Path) -> DEMSummary:
    """Parse a DEM file and return a summary of the basin geometry.

    Supported formats:
      - USGS DEM (.dem)
      - GeoTIFF (.tif, .tiff) – requires rasterio
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
