"""
3D Basin geometry visualization component.
Provides a function to render an interactive 3D basin view and optionally export a PNG snapshot.
Uses plotly for interactivity (falls back to matplotlib 3D if plotly is missing).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BasinGeom:
    length_floor: float
    width_floor: float
    max_depth: float
    side_slope_hv: float  # horizontal:vertical ratio
    floor_elev: float
    bottom_elev: Optional[float] = None
    bed_thickness: Optional[float] = None
    gw_level: Optional[float] = None


def render_basin_3d(geom: BasinGeom, out_png: Optional[str] = None):
    """Render an interactive 3D basin geometry with key planes and labels.
    If out_png is provided and kaleido is installed, a static PNG is saved.
    """
    # Try plotly first
    try:
        import numpy as np
        import plotly.graph_objects as go

        L = float(geom.length_floor)
        W = float(geom.width_floor)
        D = float(geom.max_depth)
        s = float(geom.side_slope_hv)
        z_floor = float(geom.floor_elev)
        z_bottom = float(geom.bottom_elev) if geom.bottom_elev is not None else z_floor - (D + 5.0)
        bed_thk = float(geom.bed_thickness) if geom.bed_thickness is not None else 0.0
        z_gw = float(geom.gw_level) if geom.gw_level is not None else z_floor

        # Create a simple frustum-like basin: expand dimensions with depth by slope
        # At depth z: half-extensions grow by (depth * s)
        nx = ny = 30
        x = np.linspace(-L/2, L/2, nx)
        y = np.linspace(-W/2, W/2, ny)
        X, Y = np.meshgrid(x, y)
        depth = np.linspace(0, D, 4)  # 4 layers for a wireframe look

        fig = go.Figure()
        for k, d in enumerate(depth):
            hx = L/2 + d * s
            hy = W/2 + d * s
            # draw perimeter rectangle at this depth
            z = z_floor + d  # up is positive; for visual separation
            rect_x = [-hx, hx, hx, -hx, -hx]
            rect_y = [-hy, -hy, hy, hy, -hy]
            rect_z = [z] * 5
            fig.add_trace(go.Scatter3d(x=rect_x, y=rect_y, z=rect_z, mode='lines',
                                       line=dict(color='#1976D2', width=4 if k == 0 else 2),
                                       name=f'Depth {d:.1f} m'))

        # Floor plane
        fig.add_trace(go.Surface(x=X, y=Y, z=np.full_like(X, z_floor), opacity=0.6,
                                 colorscale=[[0, '#BCAAA4'], [1, '#8D6E63']],
                                 showscale=False, name='Floor'))
        # Bed thickness (above floor)
        if bed_thk > 0:
            fig.add_trace(go.Surface(x=X, y=Y, z=np.full_like(X, z_floor + bed_thk), opacity=0.4,
                                     colorscale=[[0, '#D7CCC8'], [1, '#A1887F']],
                                     showscale=False, name='Bed'))
        # Groundwater level
        fig.add_trace(go.Surface(x=X, y=Y, z=np.full_like(X, z_gw), opacity=0.3,
                                 colorscale=[[0, '#64B5F6'], [1, '#1E88E5']],
                                 showscale=False, name='GW Level'))
        # Aquifer bottom
        fig.add_trace(go.Surface(x=X, y=Y, z=np.full_like(X, z_bottom), opacity=0.2,
                                 colorscale=[[0, '#E0E0E0'], [1, '#BDBDBD']],
                                 showscale=False, name='Aquifer Bottom'))

        fig.update_layout(
            scene=dict(
                xaxis_title='X (m)', yaxis_title='Y (m)', zaxis_title='Elevation (mAHD)'
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            title='Basin Geometry',
            showlegend=False,
        )

        if out_png:
            try:
                fig.write_image(out_png)  # requires kaleido
            except Exception:
                pass
        return fig
    except Exception:
        pass

    # Fallback: simple static matplotlib 3D
    try:
        import numpy as np
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

        L = float(geom.length_floor)
        W = float(geom.width_floor)
        D = float(geom.max_depth)
        s = float(geom.side_slope_hv)
        z_floor = float(geom.floor_elev)
        z_bottom = float(geom.bottom_elev) if geom.bottom_elev is not None else z_floor - (D + 5.0)
        bed_thk = float(geom.bed_thickness) if geom.bed_thickness is not None else 0.0
        z_gw = float(geom.gw_level) if geom.gw_level is not None else z_floor

        fig = plt.figure(figsize=(8, 6))
        ax = fig.add_subplot(111, projection='3d')

        # Draw floor rectangle
        X = np.array([-L/2, L/2, L/2, -L/2, -L/2])
        Y = np.array([-W/2, -W/2, W/2, W/2, -W/2])
        Z = np.full_like(X, z_floor)
        ax.plot3D(X, Y, Z, color='tab:blue', lw=2)

        # GW plane edge
        ax.plot3D(X, Y, np.full_like(X, z_gw), color='tab:blue', lw=1, alpha=0.5)

        # Bottom plane edge
        ax.plot3D(X, Y, np.full_like(X, z_bottom), color='gray', lw=1, alpha=0.5)

        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_zlabel('Elevation (mAHD)')
        ax.set_title('Basin Geometry')
        fig.tight_layout()
        if out_png:
            fig.savefig(out_png, dpi=150)
        return fig
    except Exception:
        pass
