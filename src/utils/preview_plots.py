"""
Preview plotting utilities for basin geometry.
Renders simple cross-sections (X and Y) as PNGs showing floor, clogged layer,
groundwater level, and aquifer bottom with side slopes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
# Use non-interactive backend for thread-safe PNG rendering
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt


@dataclass
class SimpleGeom:
    length_floor: float
    width_floor: float
    max_depth: float
    side_slope_hv: float
    floor_elev: float
    bottom_elev: Optional[float] = None
    bed_thickness: Optional[float] = None
    gw_level: Optional[float] = None


def _render_cross_section(half_span: float, geom: SimpleGeom, title: str, out_png: str) -> None:

    Lh = float(half_span)
    D = float(geom.max_depth)
    s = float(geom.side_slope_hv)
    zf = float(geom.floor_elev)
    # We no longer draw the aquifer bottom; instead fix the axis lower bound
    # 2 m below the groundwater level so geometry is clearer.
    thk = float(geom.bed_thickness) if geom.bed_thickness is not None else 0.0
    zgw = float(geom.gw_level) if geom.gw_level is not None else zf

    # Compute top edge of banks (for visual reference only)
    z_top = zf + D
    x_left_top = -Lh - D * s
    x_right_top = Lh + D * s

    fig, ax = plt.subplots(figsize=(6, 3))

    # Draw side slopes as lines
    ax.plot([-Lh, x_left_top], [zf, z_top], color="#6D4C41", lw=2)
    ax.plot([Lh, x_right_top], [zf, z_top], color="#6D4C41", lw=2)
    # Draw floor line
    ax.hlines(zf, -Lh, Lh, colors="#8D6E63", linestyles="-", lw=3, label="Floor")
    # Clogged layer (bed thickness) above floor
    if thk > 0:
        ax.hlines(zf + thk, -Lh, Lh, colors="#A1887F", linestyles="-", lw=3, label="Bed")
    # Groundwater level
    ax.hlines(zgw, x_left_top, x_right_top, colors="#1E88E5", linestyles="--", lw=2, label="GW")
    # Aquifer bottom omitted (implied) per UI request

    ax.set_title(title)
    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Elevation (mAHD)")
    # Nice margins with padding to avoid over-zoom after parameter changes
    pad_x = max(0.5, 0.1 * max(1.0, x_right_top - x_left_top))
    ax.set_xlim(x_left_top - pad_x, x_right_top + pad_x)
    # Bottom of graph fixed at 2 m below GW level (at least 0.5 m padding)
    zmin = min(zgw - 2.0, zf - 0.5)
    # Top of graph a bit above water surface with padding
    zmax = max(z_top, zgw + 0.2 * D) + 0.5
    if zmax <= zmin:
        zmax = zmin + max(1.0, 0.5 * D)
    ax.set_ylim(zmin, zmax)
    ax.grid(True, alpha=0.2)
    try:
        ax.legend(loc="best", fontsize=8)
    except Exception:
        pass
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def render_cross_section_x(geom: SimpleGeom, out_png: str) -> None:
    """Cross section in X direction (use length as span)."""
    _render_cross_section(half_span=float(geom.length_floor) / 2.0, geom=geom, title="Cross-section X", out_png=out_png)


def render_cross_section_y(geom: SimpleGeom, out_png: str) -> None:
    """Cross section in Y direction (use width as span)."""
    _render_cross_section(half_span=float(geom.width_floor) / 2.0, geom=geom, title="Cross-section Y", out_png=out_png)


def render_plan_view(geom: SimpleGeom, out_png: str) -> None:
    """Render a simple plan view showing top and floor rectangles (no 3D)."""
    Lf = float(geom.length_floor)
    Wf = float(geom.width_floor)
    D = float(geom.max_depth)
    s = float(geom.side_slope_hv)
    # top extents due to side slopes
    Lt = Lf + 2 * s * D
    Wt = Wf + 2 * s * D

    # Build a simple plan with outer/top and inner/floor rectangles
    fig, ax = plt.subplots(figsize=(5.5, 5.0))
    margin = 0.15 * max(Lt, Wt)
    ax.set_xlim(-margin, Lt + margin)
    ax.set_ylim(-margin, Wt + margin)
    # Outer/top
    ax.add_patch(plt.Rectangle((0, 0), Lt, Wt, fill=True, color="#90CAF9", alpha=0.35, ec="#1E88E5", lw=2, label="Top (at side slopes)"))
    # Inner/floor (offset by slopes)
    offs = s * D
    ax.add_patch(plt.Rectangle((offs, offs), Lf, Wf, fill=False, ec="#0D47A1", lw=2, label="Floor"))
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Length (m)")
    ax.set_ylabel("Width (m)")
    ax.set_title("Plan View")
    ax.grid(True, alpha=0.25)
    try:
        ax.legend(loc="best", fontsize=8)
    except Exception:
        pass
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def render_generic_basin_diagram(geom: SimpleGeom, out_png: str) -> None:
    """Render an isometric-like basin diagram with dimension labels.
    Uses provided geometry for proportions (approximate), but stays lightweight.
    Labels: L (Length), W (Width), D (Depth), t (bed thickness), GW (water table).
    """
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle

    # Canvas
    fig = plt.subplots(figsize=(6.8, 4.2))[0]
    ax = fig.add_subplot(111)
    ax.set_axis_off()

    # Base coordinates for a simple 3D-ish prism (isometric-ish)
    # Roughly map geometry into a compact canvas
    try:
        L = max(1.0, float(geom.length_floor) / max(1.0, float(geom.width_floor)) * 4.0)
        W = 4.0
        D = max(0.5, min(3.0, float(geom.max_depth)))
        t = max(0.0, float(geom.bed_thickness or 0.0))
        gw_y = -min(2.0, max(0.5, float(geom.gw_level or (geom.floor_elev - 1.0)) - float(geom.floor_elev)))
    except Exception:
        L, W, D = 6.0, 4.0, 2.0
        t = 0.3
        gw_y = -1.2
    ox, oy = 0.8, 0.9  # offsets for the top outline

    # Floor rectangle
    ax.add_patch(Rectangle((0, 0), L, W, facecolor="#E3F2FD", edgecolor="#0D47A1", lw=2))
    # Top outline (offset to suggest bank slopes)
    ax.add_patch(Rectangle((ox, oy), L-2*ox, W-2*oy, fill=False, edgecolor="#1976D2", lw=2))

    # Bed thickness band (t) as a strip around the inner floor
    ax.add_patch(Rectangle((0, 0), L, t, facecolor="#B0BEC5", edgecolor="#607D8B", lw=1))  # bottom edge band
    ax.add_patch(Rectangle((0, 0), t, W, facecolor="#B0BEC5", edgecolor="#607D8B", lw=1))  # left band

    # Water table (GW) as a dashed line below the basin
    # computed above
    ax.hlines(gw_y, -0.5, L+0.5, colors="#1E88E5", linestyles="--", lw=2)
    ax.text(L+0.6, gw_y, "GW (water table)", va="center", ha="left", color="#1E88E5")

    # Dimension arrows and labels
    def arrow(xy1, xy2, text, offset=(0, 0)):
        (x1, y1), (x2, y2) = xy1, xy2
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="<->", mutation_scale=12, lw=1.6, color="#424242"))
        tx = (x1 + x2) / 2.0 + offset[0]
        ty = (y1 + y2) / 2.0 + offset[1]
        ax.text(tx, ty, text, ha="center", va="center", fontsize=11, color="#424242")

    # Length L along x
    arrow((-0.05, W+0.5), (L+0.05, W+0.5), "L (Length)")
    # Width W along y
    arrow((L+0.4, -0.02), (L+0.4, W+0.02), "W (Width)", offset=(0.35, 0))
    # Depth D from top inner rim to floor center
    arrow((ox + (L-2*ox)*0.85, oy + (W-2*oy)), (ox + (L-2*ox)*0.85, 0), "D (Depth)", offset=(0.45, 0))
    # Bed thickness t on a corner
    ax.text(0.15, t + 0.08, "t (bed thickness)", ha="left", va="bottom", fontsize=10, color="#424242")

    # Sy label near the prism
    ax.text(L+1.0, W*0.6, "Sy (specific yield)", ha="left", va="center", fontsize=11, color="#616161")

    # Title
    ax.text(0, W+1.0, "Basin Geometry (schematic)", fontsize=13, weight="bold", color="#0D47A1")

    # Limits
    ax.set_xlim(-0.6, L+2.0)
    ax.set_ylim(-1.8, W+1.4)

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
