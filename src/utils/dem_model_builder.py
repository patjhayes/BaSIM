"""
DEM → MODFLOW Model Builder for BaSIM.

Converts a parsed DEMGrid into a complete set of MODFLOW 6 DIS parameters,
LAK connection data, and LAKTAB stage-volume-area table.  This module is the
bridge between the raw DEM and the FloPy model construction in
``main_phase3_step32_time_varying._run_phase3_body()``.

Key design decisions
--------------------
* The DEM grid resolution drives the model grid resolution in the basin
  area.  The model grid is extended with padding cells on all sides so
  that GHB boundaries are far from the basin.
* ``top`` is a 2-D numpy array sampled from the DEM – not a flat scalar.
* Basin cells are identified as cells whose DEM elevation is ≤ a
  user-specified *crest elevation*.
* Lake connections are computed by FloPy's built-in
  ``flopy.mf6.utils.get_lak_connections()`` which handles irregular shapes.
* The LAKTAB (stage-volume-area) table is derived directly from the DEM
  by counting cells at each elevation level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .dem_parser import DEMGrid


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class DEMModelConfig:
    """Everything needed to build a MODFLOW 6 model from a DEM."""

    # Grid dimensions
    nrow: int
    ncol: int
    nlay: int

    # Grid spacing arrays
    delr: np.ndarray            # (ncol,) – column widths
    delc: np.ndarray            # (nrow,) – row widths

    # Elevations
    top: np.ndarray             # (nrow, ncol) – cell top from DEM
    botm: list                  # layer bottom elevations (length nlay)

    # Lake identification
    lake_map: np.ndarray        # (nrow, ncol) int: 0 = lake, -1 = non-lake
    basin_mask: np.ndarray      # (nrow, ncol) boolean: True = basin cell
    idomain: Optional[np.ndarray] = None  # (nlay, nrow, ncol) or None

    # LAKTAB data
    laktab_rows: List[Tuple[float, float, float]] = field(default_factory=list)

    # Derived elevations
    floor_elev: float = 0.0
    crest_elev: float = 0.0
    max_depth: float = 0.0

    # Padding info (rows/cols of DEM within the padded grid)
    dem_row_offset: int = 0
    dem_col_offset: int = 0

    # Cell sizes from DEM (handy for LAKTAB / area calcs)
    cell_size_x: float = 1.0
    cell_size_y: float = 1.0


# ---------------------------------------------------------------------------
# Helper: build padded top array
# ---------------------------------------------------------------------------

def _build_padded_grid(
    dem: DEMGrid,
    pad_cells: int,
    pad_elev: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """Embed the DEM grid inside a larger padded grid.

    Parameters
    ----------
    dem : DEMGrid
        Parsed DEM data.
    pad_cells : int
        Number of padding cells on each side.
    pad_elev : float
        Elevation assigned to padding cells (typically the crest or max DEM elev).

    Returns
    -------
    top_2d : ndarray (nrow_total, ncol_total)
    delr : ndarray (ncol_total,)
    delc : ndarray (nrow_total,)
    row_offset, col_offset : int – position of DEM[0,0] in padded grid
    """
    nr_dem, nc_dem = dem.n_rows, dem.n_cols

    nrow = nr_dem + 2 * pad_cells
    ncol = nc_dem + 2 * pad_cells

    # Uniform cell sizes matching DEM resolution
    delr = np.full(ncol, dem.cell_size_x)
    delc = np.full(nrow, dem.cell_size_y)

    # Fill padded grid with pad_elev, then embed DEM
    top_2d = np.full((nrow, ncol), pad_elev)
    grid_clean = dem.grid.copy()
    # Replace NaN with pad_elev so model cells are always valid
    grid_clean[np.isnan(grid_clean)] = pad_elev
    top_2d[pad_cells:pad_cells + nr_dem, pad_cells:pad_cells + nc_dem] = grid_clean

    return top_2d, delr, delc, pad_cells, pad_cells


# ---------------------------------------------------------------------------
# Identify basin cells
# ---------------------------------------------------------------------------

def identify_basin_cells(
    top_2d: np.ndarray,
    crest_elev: float,
    row_offset: int,
    col_offset: int,
    dem_nrow: int,
    dem_ncol: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Mark cells whose elevation is below the crest as basin (lake) cells.

    Only cells within the DEM footprint are considered (padding is never
    classified as basin).

    Parameters
    ----------
    top_2d : ndarray (nrow, ncol)
    crest_elev : float
    row_offset, col_offset : offsets of DEM within padded grid
    dem_nrow, dem_ncol : size of original DEM

    Returns
    -------
    lake_map : ndarray (nrow, ncol) int – 0 where basin, -1 elsewhere
    basin_mask : ndarray (nrow, ncol) bool – True where basin
    """
    nrow, ncol = top_2d.shape
    basin_mask = np.zeros((nrow, ncol), dtype=bool)
    dem_region = top_2d[
        row_offset:row_offset + dem_nrow,
        col_offset:col_offset + dem_ncol,
    ]
    basin_mask[
        row_offset:row_offset + dem_nrow,
        col_offset:col_offset + dem_ncol,
    ] = dem_region < crest_elev  # strictly below crest = basin

    lake_map = np.full((nrow, ncol), -1, dtype=np.int32)
    lake_map[basin_mask] = 0  # lake number 0

    return lake_map, basin_mask


# ---------------------------------------------------------------------------
# LAKTAB from DEM
# ---------------------------------------------------------------------------

def compute_dem_laktab(
    top_2d: np.ndarray,
    basin_mask: np.ndarray,
    cell_area: float,
    floor_elev: float,
    crest_elev: float,
    nrows: int = 41,
) -> List[Tuple[float, float, float]]:
    """Compute stage–volume–surface-area table from actual DEM elevations.

    At each stage level ``s``, surface area = sum of cell areas where
    ``elev ≤ s`` (within basin mask).  Volume is the trapezoidal integral
    of area from floor up to ``s``.

    Parameters
    ----------
    top_2d : elevation grid (may be padded; basin_mask selects relevant cells)
    basin_mask : boolean mask of basin cells
    cell_area : area of a single cell (cell_size_x × cell_size_y)
    floor_elev : minimum elevation in basin (stage = 0 at floor)
    crest_elev : crest elevation (maximum meaningful stage)
    nrows : number of table rows

    Returns
    -------
    List of (stage, volume, sarea) tuples, sorted by ascending stage.
    """
    max_depth = crest_elev - floor_elev
    if max_depth <= 0:
        return [(floor_elev, 0.0, cell_area)]

    nrows = max(3, nrows)
    basin_elevs = top_2d[basin_mask]

    rows: List[Tuple[float, float, float]] = []
    prev_area = 0.0
    prev_stage = floor_elev
    cumulative_vol = 0.0

    for i in range(nrows):
        d = max_depth * i / (nrows - 1)
        stage = floor_elev + d
        # Surface area: count basin cells whose ground elevation ≤ this stage
        area = float(np.sum(basin_elevs <= stage)) * cell_area
        # Volume: trapezoidal integration step
        if i > 0:
            ds = stage - prev_stage
            cumulative_vol += 0.5 * (prev_area + area) * ds
        rows.append((round(stage, 6), round(cumulative_vol, 6), round(area, 6)))
        prev_area = area
        prev_stage = stage

    return rows


# ---------------------------------------------------------------------------
# Build layer bottoms
# ---------------------------------------------------------------------------

def _build_layer_bottoms(
    floor_elev: float,
    nlay: int = 8,
    total_depth_below_floor: float = 75.0,
) -> list:
    """Create progressive-thickness layer bottoms below the basin floor.

    Returns a list of nlay bottom elevations.  Layer thicknesses increase
    with depth (thin near the lakebed for accuracy, thick at depth for
    performance).
    """
    # Generate progressive thickness ratios (geometric-ish)
    ratios = np.array([1, 1.5, 2.5, 4, 5, 6, 8, 10][:nlay], dtype=float)
    if len(ratios) < nlay:
        # Extend with the last ratio
        ratios = np.append(ratios, np.full(nlay - len(ratios), ratios[-1]))
    ratios /= ratios.sum()
    thicknesses = ratios * total_depth_below_floor

    botm = []
    elev = floor_elev
    for t in thicknesses:
        elev -= t
        botm.append(round(elev, 4))
    return botm


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def build_dem_model_config(
    dem: DEMGrid,
    crest_elev: float,
    *,
    pad_cells: int = 20,
    nlay: int = 8,
    total_depth_below_floor: float = 75.0,
    laktab_nrows: int = 41,
    max_cells: int = 500_000,
    min_cell_size_m: float = 0.0,
) -> DEMModelConfig:
    """Build all MODFLOW grid parameters from a DEM.

    Parameters
    ----------
    dem : DEMGrid
        Parsed DEM (from ``parse_dem_file``).
    crest_elev : float
        Elevation of the basin rim.  Cells below this are lake cells.
    pad_cells : int
        Padding cells on each side of the DEM for boundary conditions.
    nlay : int
        Number of model layers.
    total_depth_below_floor : float
        Total aquifer depth below basin floor (metres).
    laktab_nrows : int
        Number of rows in the LAKTAB stage–volume–area table.
    max_cells : int
        If the total 2-D cell count (with padding) exceeds this, the DEM
        is coarsened by averaging 2×2 blocks until it fits.
    min_cell_size_m : float
        If >0, the DEM is coarsened until cells are at least this size
        in both x and y directions.  Applied *before* the max_cells check.

    Returns
    -------
    DEMModelConfig
    """
    # --- optional coarsening (cell size floor) ------------------------------
    working_dem = dem
    coarsen_factor = 1
    if min_cell_size_m > 0:
        while (working_dem.cell_size_x < min_cell_size_m
               or working_dem.cell_size_y < min_cell_size_m):
            coarsen_factor *= 2
            working_dem = _coarsen_dem(working_dem, 2)
            print(f"   ⚠️ DEM coarsened {coarsen_factor}× to reach min cell size "
                  f"{min_cell_size_m:.1f} m  (now {working_dem.cell_size_x:.1f}×"
                  f"{working_dem.cell_size_y:.1f} m, "
                  f"{working_dem.n_rows}×{working_dem.n_cols} cells)")

    # --- optional coarsening (max cells) ------------------------------------
    while True:
        total_2d = (working_dem.n_rows + 2 * pad_cells) * (working_dem.n_cols + 2 * pad_cells)
        if total_2d <= max_cells:
            break
        coarsen_factor *= 2
        working_dem = _coarsen_dem(working_dem, 2)
        print(f"   ⚠️ DEM coarsened {coarsen_factor}× to fit max_cells={max_cells:,} "
              f"(now {working_dem.n_rows}×{working_dem.n_cols})")

    # --- padded grid --------------------------------------------------------
    pad_elev = max(crest_elev, working_dem.max_elev)
    top_2d, delr, delc, row_off, col_off = _build_padded_grid(
        working_dem, pad_cells, pad_elev,
    )
    nrow, ncol = top_2d.shape

    # --- basin identification -----------------------------------------------
    lake_map, basin_mask = identify_basin_cells(
        top_2d, crest_elev, row_off, col_off,
        working_dem.n_rows, working_dem.n_cols,
    )

    n_basin = int(basin_mask.sum())
    if n_basin == 0:
        raise ValueError(
            f"No basin cells found.  The crest elevation ({crest_elev}) may "
            f"be below the DEM minimum ({working_dem.min_elev:.2f}).  "
            f"Raise the crest or check the DEM."
        )

    floor_elev = float(np.nanmin(top_2d[basin_mask]))
    max_depth = crest_elev - floor_elev

    print(f"   📊 DEM grid: {working_dem.n_rows}×{working_dem.n_cols} "
          f"(padded → {nrow}×{ncol})")
    print(f"   📊 Basin cells: {n_basin} "
          f"({n_basin * working_dem.cell_area:.0f} m² plan area)")
    print(f"   📊 Elev range: {floor_elev:.2f} – {crest_elev:.2f} m "
          f"(depth {max_depth:.2f} m)")

    # --- layer bottoms ------------------------------------------------------
    botm = _build_layer_bottoms(floor_elev, nlay, total_depth_below_floor)

    # --- LAKTAB -------------------------------------------------------------
    laktab_rows = compute_dem_laktab(
        top_2d, basin_mask, working_dem.cell_area,
        floor_elev, crest_elev, laktab_nrows,
    )

    return DEMModelConfig(
        nrow=nrow,
        ncol=ncol,
        nlay=nlay,
        delr=delr,
        delc=delc,
        top=top_2d,
        botm=botm,
        lake_map=lake_map,
        basin_mask=basin_mask,
        laktab_rows=laktab_rows,
        floor_elev=floor_elev,
        crest_elev=crest_elev,
        max_depth=max_depth,
        dem_row_offset=row_off,
        dem_col_offset=col_off,
        cell_size_x=working_dem.cell_size_x,
        cell_size_y=working_dem.cell_size_y,
    )


# ---------------------------------------------------------------------------
# DEM coarsening helper
# ---------------------------------------------------------------------------

def _coarsen_dem(dem: DEMGrid, factor: int = 2) -> DEMGrid:
    """Reduce DEM resolution by averaging factor×factor blocks.

    NaN cells are ignored in the average.  If an entire block is NaN the
    result cell is NaN.
    """
    grid = dem.grid
    nr, nc = grid.shape

    # Trim to multiple of factor
    nr_trim = (nr // factor) * factor
    nc_trim = (nc // factor) * factor
    trimmed = grid[:nr_trim, :nc_trim]

    # Reshape into blocks and nanmean
    new_nr = nr_trim // factor
    new_nc = nc_trim // factor
    blocks = trimmed.reshape(new_nr, factor, new_nc, factor)
    with np.errstate(all="ignore"):
        coarse = np.nanmean(blocks, axis=(1, 3))

    return DEMGrid(
        grid=coarse,
        cell_size_x=dem.cell_size_x * factor,
        cell_size_y=dem.cell_size_y * factor,
        x_origin=dem.x_origin,
        y_origin=dem.y_origin,
        file_path=dem.file_path,
        crs_info=dem.crs_info,
        is_geographic=dem.is_geographic,
    )
