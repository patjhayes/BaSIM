"""
LAK Utilities: geometry-based LAKTAB generation and helpers
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class BasinGeometry:
    length_floor: float  # floor length (m)
    width_floor: float   # floor width (m)
    max_depth: float     # maximum water depth (m) above floor
    side_slope_hv: float # horizontal:vertical side slope (H:V), e.g., 2.0 means 2H:1V
    floor_elev: float    # basin floor elevation (m)


def generate_tapered_laktab(geom: BasinGeometry, nrows: int = 41) -> List[Tuple[float, float, float]]:
    """Generate (stage, volume, sarea) rows for a trapezoidal basin with side slopes.

    Formulas (depth d above floor):
      L(d) = Lf + 2*m*d
      W(d) = Wf + 2*m*d
      A(d) = L(d) * W(d)
      V(d) = ∫ A(h) dh, 0..d = Lf*Wf*d + m*(Lf+Wf)*d^2 + (4/3)*m^2*d^3

    Returns a list of tuples: (stage, volume, sarea)
    """
    Lf = float(geom.length_floor)
    Wf = float(geom.width_floor)
    m = max(0.0, float(geom.side_slope_hv))
    D = max(0.0, float(geom.max_depth))
    z0 = float(geom.floor_elev)

    nrows = max(3, int(nrows))
    rows: List[Tuple[float, float, float]] = []

    for i in range(nrows):
        d = D * i / (nrows - 1)
        Ld = Lf + 2.0 * m * d
        Wd = Wf + 2.0 * m * d
        A = max(0.0, Ld * Wd)
        V = (Lf * Wf * d) + (m * (Lf + Wf) * d * d) + ((4.0 / 3.0) * m * m * d * d * d)
        stage = z0 + d
        rows.append((stage, V, A))

    return rows


def write_laktab_file(file_path: str | Path, rows: List[Tuple[float, float, float]]) -> Path:
    """Write a LAKTAB file (TAB6) with provided rows (stage, volume, sarea)."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as tf:
        tf.write("# LAKTAB generated from basin geometry (stage volume sarea)\n")
        tf.write("BEGIN DIMENSIONS\n")
        tf.write(f"  NROW {len(rows)}\n")
        tf.write("  NCOL 3\n")
        tf.write("END DIMENSIONS\n\n")
        tf.write("BEGIN TABLE\n")
        tf.write("# stage  volume  sarea\n")
        for stg, vol, area in rows:
            tf.write(f"  {stg:.6f}  {vol:.6f}  {area:.6f}\n")
        tf.write("END TABLE\n")
    return p


def suggest_domain_factor(geom: BasinGeometry, min_factor: float = 6.0, pad_multiplier: float = 4.0) -> float:
    """Suggest a domain_factor for grid_builder.create_adaptive_refined_grid.

    Ensures domain extends well beyond the maximum wetted extents.
    domain_factor ~ pad_multiplier * max(surface_len/length_floor, surface_wid/width_floor)
    and not less than min_factor.
    """
    Lf = max(1e-6, float(geom.length_floor))
    Wf = max(1e-6, float(geom.width_floor))
    m = max(0.0, float(geom.side_slope_hv))
    D = max(0.0, float(geom.max_depth))

    Lsurf = Lf + 2.0 * m * D
    Wsurf = Wf + 2.0 * m * D
    scale = max(Lsurf / Lf, Wsurf / Wf)
    factor = max(float(min_factor), float(pad_multiplier) * scale)
    return factor
