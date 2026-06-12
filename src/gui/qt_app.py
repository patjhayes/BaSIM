"""
BaSIM Professional - Enhanced Desktop Application
Built on top of the existing working Tkinter application
"""

import sys
import os
from pathlib import Path

# MUST be set before ANY Qt/COM objects are created.
# This tells Windows to treat this process as "BaSIM" not "python.exe"
# so the taskbar icon is ours rather than the Python interpreter's.
_APPID = 'BaSIM.BasinSimulator.App.2'
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APPID)
except Exception:
    pass

from typing import Optional, Dict, List, Tuple
import json
from datetime import datetime
import re
import traceback

# PyQt6 imports
from PyQt6.QtCore import Qt, QTimer, QPointF, QLineF, QUrl, QThread
from PyQt6.QtGui import QPainter, QBrush, QColor, QPen, QFont, QAction, QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QSpinBox,
    QComboBox,
    QPushButton,
    QStatusBar,
    QScrollArea,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QMessageBox,
    QProgressBar,
    QTextEdit,
    QFileDialog,
    QProgressDialog,
    QToolButton,
    QToolTip,
    QRadioButton,
    QButtonGroup,
    QSplitter,
)

# Optional plotting backend
try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except Exception:
    pg = None  # type: ignore
    PYQTGRAPH_AVAILABLE = False

import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from PyQt6.QtGui import QCursor
# Add project root (dev) to sys.path and compute app/data roots for both dev and frozen runs
DEV_ROOT = Path(__file__).resolve().parents[2]
if str(DEV_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_ROOT))

def _app_base_dir() -> Path:
    """Return the base directory where bundled resources live.

    - PyInstaller onefile: sys._MEIPASS
    - PyInstaller onedir: directory of the executable
    - Dev: repository root (DEV_ROOT)
    """
    try:
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
    except Exception:
        pass
    return DEV_ROOT

APP_BASE = _app_base_dir()

def _user_data_base() -> Path:
    """A persistent, user-writable base directory for BaSIM data and state.

    Preference order (first available is used):
      1) ~/Documents/BaSIM
      2) %APPDATA%/BaSIM (Roaming)
      3) ~/.BaSIM
    """
    # 1) Documents/BaSIM
    try:
        docs = Path.home() / "Documents"
        base = docs / "BaSIM"
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        pass
    # 2) AppData/Roaming/BaSIM on Windows; elsewhere fallback to home
    try:
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "BaSIM"
        else:
            base = Path.home() / ".BaSIM"
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        pass
    # 3) Last resort
    return Path.home() / ".BaSIM"

USER_BASE = _user_data_base()

# Boot logging helper
def _ensure_dir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

_BOOT_DIR = USER_BASE / "model_output" / "_progress"
_ensure_dir(_BOOT_DIR)
_BOOT_LOG = _BOOT_DIR / "gui_boot.log"

def _boot_log(msg: str):
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _BOOT_LOG.write_text((_BOOT_LOG.read_text(encoding='utf-8', errors='ignore') if _BOOT_LOG.exists() else '') + f"[{ts}] {msg}\n", encoding='utf-8')
    except Exception:
        try:
            print(msg)
        except Exception:
            pass

# Defer importing the heavy model runner (pandas, flopy, etc.) until a simulation starts
# to keep GUI startup fast and reliable on networked/OneDrive environments.
run_phase3_step32_with_config = None  # set at runtime when needed (detailed MODFLOW 6)

from src.gui.style import apply_dark_palette, DARK_STYLESHEET
from src.gui.license_dialog import LicenseDialog
from src.licensing.verifier import LicenseVerifier

# Matplotlib canvas for the design preview raster
try:
    import matplotlib
    matplotlib.use('QtAgg')
    import matplotlib.pyplot as _mpl_plt
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FigureCanvas
    from matplotlib.figure import Figure as _MplFigure
    import numpy as _np
    _HAS_MPL_CANVAS = True
except Exception:
    _HAS_MPL_CANVAS = False


class DesignPreviewCanvas(QWidget):
    """Raster elevation heatmap preview for both manual geometry and DEM mode.

    Shows the same style as the PDF report: terrain colourmap, basin boundary
    contour (red), crest contour (white dashed), floor marker, and a colour-bar.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        if _HAS_MPL_CANVAS:
            self._fig = _MplFigure(figsize=(5, 4), dpi=100, facecolor='#2b2b2b')
            self._canvas = _FigureCanvas(self._fig)
            self._layout.addWidget(self._canvas)
        else:
            self._fig = None
            self._canvas = None
            lbl = QLabel("matplotlib not available – install matplotlib for design preview")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(lbl)

        # Cache the last‐rendered state to avoid redundant redraws
        self._last_key: tuple | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def render_manual(self, length: float, width: float, depth: float,
                      slope: float, floor_elev: float, gw_head: float,
                      crest_elev: float | None = None):
        """Generate a synthetic raster from the trapezoidal basin geometry."""
        key = ('manual', length, width, depth, slope, floor_elev, gw_head, crest_elev)
        if key == self._last_key:
            return
        self._last_key = key
        if not _HAS_MPL_CANVAS:
            return
        try:
            self._draw_manual(length, width, depth, slope, floor_elev, gw_head, crest_elev)
        except Exception as exc:
            self._draw_fallback(f"Preview error: {exc}")

    def render_dem(self, dem_path: str, crest: float, gw_head: float | None = None):
        """Render a raster from an actual DEM file."""
        key = ('dem', dem_path, crest, gw_head)
        if key == self._last_key:
            return
        self._last_key = key
        if not _HAS_MPL_CANVAS:
            return
        try:
            self._draw_dem(dem_path, crest, gw_head)
        except Exception as exc:
            self._draw_fallback(f"DEM preview error: {exc}")

    def render_placeholder(self, msg: str = "Select a DEM file to preview basin geometry."):
        key = ('placeholder', msg)
        if key == self._last_key:
            return
        self._last_key = key
        self._draw_fallback(msg)

    # ------------------------------------------------------------------
    # Internal drawing helpers
    # ------------------------------------------------------------------
    def _draw_manual(self, length, width, depth, slope, floor_elev, gw_head, crest_elev):
        """Build a synthetic elevation raster for a trapezoidal basin."""
        import numpy as np

        crest = crest_elev if crest_elev is not None else floor_elev + depth
        # Total footprint including slopes
        total_l = length + 2 * slope * depth
        total_w = width + 2 * slope * depth
        # Add padding around the basin so the boundary contour isn't at the plot edge
        pad = max(slope * depth, max(total_l, total_w) * 0.15, 5.0)
        domain_l = total_l + 2 * pad
        domain_w = total_w + 2 * pad
        # Resolution: ~1 m cells, capped at 200 cells per axis
        res = max(domain_l, domain_w) / 200.0
        res = max(res, 0.5)
        nx = max(10, int(domain_l / res))
        ny = max(10, int(domain_w / res))

        xs = np.linspace(0, domain_l, nx)
        ys = np.linspace(0, domain_w, ny)
        xx, yy = np.meshgrid(xs, ys)

        # Distance inward from each edge of the basin footprint (offset by padding)
        margin_l = slope * depth  # slope run from crest to floor
        # Distance from basin outer edge (the crest rectangle starts at pad)
        dx = np.minimum(xx - pad, total_l + pad - xx)
        dy = np.minimum(yy - pad, total_w + pad - yy)
        d_in = np.minimum(dx, dy)

        # Elevation: outside basin → crest, slope zone → ramp, inside → floor
        if margin_l > 1e-6:
            elev = np.where(
                d_in < 0,
                crest,                                          # outside basin footprint
                np.where(
                    d_in >= margin_l,
                    floor_elev,                                 # flat floor
                    crest - (crest - floor_elev) * d_in / margin_l,  # slope
                ),
            )
        else:
            elev = np.where(d_in < 0, crest, floor_elev)

        basin_mask = elev < crest - 1e-4

        self._render_raster(
            grid=elev, basin_mask=basin_mask, crest=crest,
            floor_elev=floor_elev, gw_head=gw_head,
            title=f'Basin  {length:.0f}×{width:.0f} m, depth {depth:.1f} m',
            xlabel=f'Length  ({length:.0f} m)', ylabel=f'Width  ({width:.0f} m)',
            extent=[0, domain_l, domain_w, 0],
            show_boundary=False,
        )

    def _draw_dem(self, dem_path, crest, gw_head):
        """Render an actual DEM raster."""
        import numpy as np
        from src.utils.dem_parser import parse_dem_file

        dem = parse_dem_file(dem_path)
        grid = np.where(dem.valid_mask, dem.grid, np.nan)
        basin_mask = (grid < crest) & dem.valid_mask
        floor_elev = float(np.nanmin(grid[basin_mask])) if int(np.sum(basin_mask)) > 0 else float(np.nanmin(grid))

        n_basin = int(np.sum(basin_mask))
        plan_area = n_basin * dem.cell_area
        depth = crest - floor_elev
        title = (f'DEM  {dem.n_rows}×{dem.n_cols}  res {dem.cell_size_x:.1f} m  |  '
                 f'Basin {n_basin} cells  ({plan_area:,.0f} m²)  depth {depth:.1f} m')

        self._render_raster(
            grid=grid, basin_mask=basin_mask, crest=crest,
            floor_elev=floor_elev, gw_head=gw_head,
            title=title,
            xlabel='Column', ylabel='Row',
        )

    def _render_raster(self, *, grid, basin_mask, crest, floor_elev,
                       gw_head, title, xlabel, ylabel, extent=None,
                       show_boundary=True):
        """Core renderer: terrain heatmap with basin boundary and overlays."""
        import numpy as np

        fig = self._fig
        fig.clear()
        ax = fig.add_subplot(111)

        ax.set_facecolor('#2b2b2b')

        kw = dict(cmap='terrain', aspect='equal',
                  vmin=float(np.nanmin(grid)), vmax=float(np.nanmax(grid)))
        if extent is not None:
            kw['extent'] = extent
        im = ax.imshow(grid, **kw)

        # Basin boundary contour (red) — only for DEM mode
        if show_boundary:
            try:
                ax.contour(basin_mask.astype(float), levels=[0.5],
                           colors='red', linewidths=1.5)
            except Exception:
                pass

        # Crest contour (white dashed)
        try:
            ax.contour(grid, levels=[crest], colors='white',
                       linewidths=1.0, linestyles='dashed')
        except Exception:
            pass

        cbar = fig.colorbar(im, ax=ax, shrink=0.82, label='Elevation (m)')
        cbar.ax.yaxis.label.set_color('white')
        cbar.ax.tick_params(colors='white')

        ax.set_title(title, fontsize=9, color='white')
        ax.set_xlabel(xlabel, fontsize=8, color='#cccccc')
        ax.set_ylabel(ylabel, fontsize=8, color='#cccccc')
        ax.tick_params(colors='#aaaaaa', labelsize=7)

        # Legend annotations
        handles = []
        import matplotlib.lines as mlines
        if show_boundary:
            handles.append(mlines.Line2D([], [], color='red', lw=1.5, label='Basin boundary'))
        handles.append(mlines.Line2D([], [], color='white', lw=1.0, ls='--', label=f'Crest ({crest:.1f} m)'))
        handles.append(mlines.Line2D([], [], color='cyan', lw=1.0, ls=':', label=f'Floor ({floor_elev:.2f} m)'))
        if gw_head is not None:
            gw_rel = gw_head - floor_elev
            if gw_rel >= 0:
                gw_label = f'GW head ({gw_head:.1f} m, {gw_rel:.1f} m above floor)'
            else:
                gw_label = f'GW head ({gw_head:.1f} m, {abs(gw_rel):.1f} m below floor)'
            handles.append(mlines.Line2D([], [], color='#50c878', lw=1.0, ls='-.', label=gw_label))
        ax.legend(handles=handles, loc='upper right', fontsize=6, framealpha=0.6,
                  facecolor='#333333', edgecolor='#555555', labelcolor='white')

        fig.tight_layout(pad=1.0)
        self._canvas.draw_idle()

    def _draw_fallback(self, msg: str):
        if not _HAS_MPL_CANVAS:
            return
        fig = self._fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor('#2b2b2b')
        ax.text(0.5, 0.5, msg, transform=ax.transAxes,
                ha='center', va='center', color='#aaaaaa', fontsize=10,
                wrap=True)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.tight_layout()
        self._canvas.draw_idle()


class BaSIMMainWindow(QMainWindow):
    """Enhanced version of the working Tkinter application"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BaSim - Basin Simulator")
        self.setGeometry(100, 100, 1400, 900)
        self._set_window_icon()

        # Apply professional styling
        apply_dark_palette(QApplication.instance())
        self.setStyleSheet(DARK_STYLESHEET)

        # Initialize with defaults
        self.config = self._get_default_config()
        self.ts1_files = []
        self.results = {}
        self.ts1_widgets = {}
        # custom depth–area table storage [(depth_m, area_m2), ...]
        self.custom_depth_area = []
        self.use_custom_da = False
        # last-run overlays
        self._last_peak_stage = None
        self._last_spill = False
        # static groundwater overlay head (do not live-update while editing)
        try:
            self._gw_overlay_head = float(self.config.get("aquifer", {}).get("initial_head", 5.0))
        except Exception:
            self._gw_overlay_head = 4.0

        try:
            self._init_ui()
        except Exception as e:
            _boot_log(f"_init_ui failed: {e}\n{traceback.format_exc()}")
            raise
        self._load_saved_config()

    def _set_window_icon(self):
        """Set a window/taskbar icon from bundled logo assets.

        Uses two complementary approaches:
        1. Qt setWindowIcon on both QApplication and QMainWindow
        2. Win32 WM_SETICON with explicit 48x48 (taskbar) + small icon
        """
        try:
            base_dir = APP_BASE
            ico_path = base_dir / "logo" / "logomark.ico"
            if not ico_path.exists():
                for p in [base_dir / "logo" / "transparent_logomark.png",
                           base_dir / "logo" / "transparent_logo.png"]:
                    if p.exists():
                        self.setWindowIcon(QIcon(str(p)))
                        return
                return

            # 1) Qt icon on both app and window
            icon = QIcon(str(ico_path))
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app:
                app.setWindowIcon(icon)

            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            ico_str = str(ico_path)

            # 2) Win32 WM_SETICON — load specific sizes
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x00000010

            # Big icon: 48x48 for taskbar, 32x32 for Alt-Tab
            big = user32.LoadImageW(0, ico_str, IMAGE_ICON, 48, 48,
                                    LR_LOADFROMFILE)
            if not big:
                big = user32.LoadImageW(0, ico_str, IMAGE_ICON, 32, 32,
                                        LR_LOADFROMFILE)
            # Small icon: 16x16 for title bar
            small = user32.LoadImageW(0, ico_str, IMAGE_ICON, 16, 16,
                                      LR_LOADFROMFILE)
            if big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
            if small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)

        except Exception as e:
            _boot_log(f"_set_window_icon failed: {e}")
        
    def _get_stylesheet(self):
        """Professional dark theme matching your Tkinter app style"""
        return """
            QMainWindow {
                background-color: #2b2b2b;
            }
            QLabel {
                color: #ffffff;
                font-size: 12px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                color: #ffffff;
                padding: 5px;
                border-radius: 3px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #0d7377;
            }
            QPushButton {
                background-color: #0d7377;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 3px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #14a085;
            }
            QPushButton:pressed {
                background-color: #0a5d61;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #999999;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTabWidget::pane {
                background-color: #3c3c3c;
                border: 1px solid #555555;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #ffffff;
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0d7377;
            }
            QTabBar::tab:hover {
                background-color: #4a4a4a;
            }
            QListWidget {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #0d7377;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #0d7377;
                border-radius: 3px;
            }
            QTableWidget {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #0d7377;
            }
            QHeaderView::section {
                background-color: #2b2b2b;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #555555;
            }
            QTextEdit {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                color: #ffffff;
            }
            QMessageBox {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """
    
    def _get_default_config(self):
        """Same defaults as your working Tkinter application"""
        return {
            "scenario_title": "Scenario 1",
            "model_tag": "desktop",
            "analysis_mode": "detailed",
            "basin_geometry": {
                "length_floor": 50.0,
                "width_floor": 30.0,
                "max_depth": 3.0,
                "side_slope_hv": 3.0,
                "floor_elev": 5.0,
            },
            "aquifer": {
                "k_horizontal_mpd": 0.864,  # 1e-5 m/s * 86400
                "k_vertical_mpd": 0.0864,   # 1e-6 m/s * 86400
                "ss": 1e-5,
                "sy": 0.10,
                "initial_head": 5.0,
                "bottom_elev": -5.0,
            },
            "infiltration": {
                "mode": "full",
                "bed_thickness_m": 0.5,
                "bed_k_mpd": 5.0,
                "side_k_mpd": 2.5,
                "side_k_separate": False,
            },
            "uzf": {
                "thts": 0.35,
                "thtr": 0.05,
                "eps": 4.0,
                "thti": 0.10,
            },
            "perf": {
                # Performance preset fixed to fast; other modes removed
                "mode": "fast",
            },
            "post_storm_days": 3.0,
            "post_storm_step_hours": 1.0,
            "lightweight_outputs": True,
            "cleanup_heavy": True,
        }
    
    def _init_ui(self):
        """Initialize UI matching your Tkinter layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout – use a splitter so the data-entry panel is prominent
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ----- Central panel – Configuration (the main workspace) -----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        # No max-width cap – the splitter handle lets users resize freely
        left_scroll.setMinimumWidth(420)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Add all configuration groups in same order as Tkinter
        left_layout.addWidget(self._create_basin_group())
        left_layout.addWidget(self._create_aquifer_group())
        left_layout.addWidget(self._create_infiltration_group())
        # New: Outlet hydraulics overlay (post-processing)
        left_layout.addWidget(self._create_outlet_group())
        left_layout.addWidget(self._create_performance_group())
        left_layout.addWidget(self._create_ts1_group())
        left_layout.addWidget(self._create_simulation_group())
        left_layout.addWidget(self._create_run_controls())
        left_layout.addStretch()

        left_scroll.setWidget(left_panel)
        splitter.addWidget(left_scroll)

        # ----- Right panel – Tabs (results / viz) -----
        self.results_tabs = QTabWidget()
        splitter.addWidget(self.results_tabs)

        # Give data-entry ~60 % of window width by default
        splitter.setStretchFactor(0, 3)   # config panel
        splitter.setStretchFactor(1, 2)   # results tabs
        splitter.setSizes([840, 560])     # initial pixel split at 1400 px

        main_layout.addWidget(splitter)
        
        # Design preview tab
        self.design_tab = QWidget()
        dt_layout = QVBoxLayout(self.design_tab)
        self.design_view = DesignPreviewCanvas(self)
        dt_layout.addWidget(self.design_view)
        self.results_tabs.addTab(self.design_tab, "Design Preview")
        
        # Create result tabs
        self._create_results_tabs()
        
        # Menu bar
        self._create_menu_bar()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        # Draw initial preview overlays once at startup
        try:
            self._update_design_view()
        except Exception:
            pass
        # Show license status on startup
        try:
            self._update_license_status_bar()
        except Exception:
            pass
        # Periodically refresh license indicator
        try:
            if not hasattr(self, "_lic_timer"):
                self._lic_timer = QTimer(self)
                self._lic_timer.timeout.connect(self._update_license_status_bar)
                self._lic_timer.start(60000)  # every 60s
        except Exception:
            pass
        # On first show, if unlicensed, prompt to open the License dialog
        try:
            self._did_prompt_license = False
            QTimer.singleShot(600, self._maybe_prompt_license_on_first_run)
        except Exception:
            pass

    def _create_basin_group(self):
        """Basin geometry inputs"""
        group = QGroupBox("Basin Geometry")
        layout = QFormLayout()

        # Basin shape fixed to Rectangle (manual mode)
        shape_row = QWidget()
        h = QHBoxLayout(shape_row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Shape: Rectangle")
        info = self._make_info_button("Basin planform is rectangular. Circular and trapezoidal basins are not supported in this version.")
        h.addWidget(lbl)
        h.addWidget(info)
        h.addStretch()
        self.manual_shape_row = shape_row
        layout.addRow(shape_row)
        
        # Length
        self.length_input = QDoubleSpinBox()
        self.length_input.setRange(1, 10000)
        self.length_input.setValue(self.config["basin_geometry"]["length_floor"])
        self.length_input.setSuffix(" m")
        self.length_input.setDecimals(1)
        layout.addRow(self._label_with_info("Floor Length:", "Length of the flat basin floor in meters (x-direction)."), self.length_input)
        
        # Width
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(1, 10000)
        self.width_input.setValue(self.config["basin_geometry"]["width_floor"])
        self.width_input.setSuffix(" m")
        self.width_input.setDecimals(1)
        layout.addRow(self._label_with_info("Floor Width:", "Width of the flat basin floor in meters (y-direction)."), self.width_input)
        
        # Depth
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0.1, 20)
        self.depth_input.setValue(self.config["basin_geometry"]["max_depth"])
        self.depth_input.setSuffix(" m")
        self.depth_input.setDecimals(2)
        layout.addRow(self._label_with_info("Max Depth:", "Water depth from basin floor to crest. Controls sidewall extent with slope."), self.depth_input)
        
        # Side slope
        self.side_slope_input = QDoubleSpinBox()
        self.side_slope_input.setRange(0, 10)
        self.side_slope_input.setValue(self.config["basin_geometry"]["side_slope_hv"])
        self.side_slope_input.setSuffix(" H:V")
        self.side_slope_input.setDecimals(1)
        layout.addRow(self._label_with_info("Side Slope:", "Horizontal:Vertical side slope (e.g., 3 means 3H:1V)."), self.side_slope_input)
        
        # Floor elevation (basin level)
        self.floor_elev_input = QDoubleSpinBox()
        self.floor_elev_input.setRange(-100, 1000)
        self.floor_elev_input.setValue(self.config["basin_geometry"]["floor_elev"])
        self.floor_elev_input.setSuffix(" m AHD")
        self.floor_elev_input.setDecimals(2)
        layout.addRow(self._label_with_info("Floor Elevation:", "Elevation of basin floor (m AHD)."), self.floor_elev_input)
        
        # Custom depth-area relationship
        da_row = QWidget()
        da_h = QHBoxLayout(da_row)
        da_h.setContentsMargins(0, 0, 0, 0)
        self.use_custom_da_check = QCheckBox("Use custom depth-area...")
        self.use_custom_da_check.setToolTip("Provide your own depth (m) vs surface area (m²) table; volume is integrated from the curve.")
        edit_btn = QPushButton("Edit Table...")
        edit_btn.clicked.connect(self._edit_depth_area_table)
        da_h.addWidget(self.use_custom_da_check)
        da_h.addWidget(edit_btn)
        da_h.addStretch()
        layout.addRow(self._label_with_info("Depth-Area:", "Optionally override trapezoid geometry with your own depth-surface area relationship."), da_row)
        
        # hook design preview updates
        try:
            self.length_input.valueChanged.connect(self._update_design_view)
            self.width_input.valueChanged.connect(self._update_design_view)
            self.depth_input.valueChanged.connect(self._update_design_view)
            self.side_slope_input.valueChanged.connect(self._update_design_view)
            self.floor_elev_input.valueChanged.connect(self._update_design_view)
        except Exception:
            pass

        group.setLayout(layout)
        return group



    def _edit_depth_area_table(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Depth–Area Table")
        dlg.resize(420, 420)
        v = QVBoxLayout(dlg)
        tip = QLabel("Enter depth (m) and surface area (m²). Depth 0 corresponds to basin floor. Provide at least 2 rows.")
        tip.setWordWrap(True)
        v.addWidget(tip)
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Depth (m)", "Area (m²)"])
        table.horizontalHeader().setStretchLastSection(True)
        # load existing
        rows = self.custom_depth_area if self.custom_depth_area else [(0.0, self.length_input.value()*self.width_input.value()), (self.depth_input.value(), (self.length_input.value()+2*self.side_slope_input.value()*self.depth_input.value())*(self.width_input.value()+2*self.side_slope_input.value()*self.depth_input.value()))]
        table.setRowCount(len(rows))
        for r,(d,a) in enumerate(rows):
            d_item = QTableWidgetItem(f"{float(d):.3f}")
            a_item = QTableWidgetItem(f"{float(a):.3f}")
            table.setItem(r,0,d_item)
            table.setItem(r,1,a_item)
        v.addWidget(table)
        # controls
        h = QHBoxLayout()
        add_btn = QPushButton("Add Row")
        rem_btn = QPushButton("Remove Row")
        h.addWidget(add_btn)
        h.addWidget(rem_btn)
        h.addStretch()
        v.addLayout(h)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(btns)
        def add_row():
            table.insertRow(table.rowCount())
            table.setItem(table.rowCount()-1, 0, QTableWidgetItem("0"))
            table.setItem(table.rowCount()-1, 1, QTableWidgetItem("0"))
        def rem_row():
            r = table.currentRow()
            if r >= 0:
                table.removeRow(r)
            else:
                if table.rowCount() > 0:
                    table.removeRow(table.rowCount() - 1)

        def on_ok():
            new_rows: List[Tuple[float, float]] = []
            for r in range(table.rowCount()):
                try:
                    d_item = table.item(r, 0)
                    a_item = table.item(r, 1)
                    if d_item is None or a_item is None:
                        continue
                    d = float(d_item.text())
                    a = float(a_item.text())
                    if d < 0 or a <= 0:
                        continue
                    new_rows.append((d, a))
                except Exception:
                    continue
            new_rows.sort(key=lambda x: x[0])
            if len(new_rows) >= 2:
                self.custom_depth_area = new_rows
                self.use_custom_da_check.setChecked(True)
                dlg.accept()
            else:
                QMessageBox.warning(self, "Invalid Table", "Provide at least two valid rows with positive area.")
        btns.accepted.connect(on_ok)
        btns.rejected.connect(dlg.reject)
    
    def _create_aquifer_group(self):
        """Aquifer properties - matching Tkinter"""
        group = QGroupBox("Aquifer Properties")
        layout = QFormLayout()

        # Anisotropy toggle: Kh separate
        self.sep_kh_check = QCheckBox("Use separate Kh")
        self.sep_kh_check.setToolTip("Enable to set horizontal K (Kh) separately from vertical K (Kv). If unchecked, Kh = Kv.")
        layout.addRow(self.sep_kh_check)

        # Kv (m/day) primary
        self.kv_input = QDoubleSpinBox()
        self.kv_input.setRange(1e-6, 1e5)
        self.kv_input.setDecimals(6)
        self.kv_input.setValue(self.config["aquifer"]["k_vertical_mpd"])
        self.kv_input.setSuffix(" m/day")
        layout.addRow(self._label_with_info("Kv (m/day):", "Vertical hydraulic conductivity (m/day). Typical: Sand 1–30, Silty sand 0.1–1, Silt 0.001–0.1, Clay 1e-6–1e-3."), self.kv_input)

        # Kh (m/day) optionally separate
        self.kh_input = QDoubleSpinBox()
        self.kh_input.setRange(1e-6, 1e5)
        self.kh_input.setDecimals(6)
        self.kh_input.setValue(self.config["aquifer"]["k_horizontal_mpd"])
        self.kh_input.setSuffix(" m/day")
        self.kh_input.setEnabled(False)
        layout.addRow(self._label_with_info("Kh (m/day):", "Horizontal hydraulic conductivity (m/day). Often >= Kv. Typical: Sand 1–50, Silty sand 0.2–2, Silt 0.002–0.2, Clay 1e-6–1e-3."), self.kh_input)

        def _sync_kh(v: float):
            if not self.sep_kh_check.isChecked():
                self.kh_input.blockSignals(True)
                self.kh_input.setValue(float(v))
                self.kh_input.blockSignals(False)
        self.kv_input.valueChanged.connect(_sync_kh)
        def _toggle_sep():
            self.kh_input.setEnabled(self.sep_kh_check.isChecked())
            if not self.sep_kh_check.isChecked():
                _sync_kh(self.kv_input.value())
        self.sep_kh_check.toggled.connect(_toggle_sep)
        # Initialize checkbox based on configured anisotropy; preserve Kh if different
        try:
            kh_cfg = float(self.config["aquifer"]["k_horizontal_mpd"])
            kv_cfg = float(self.config["aquifer"]["k_vertical_mpd"])
            anis = abs(kh_cfg - kv_cfg) > 1e-12
        except Exception:
            anis = False
        self.sep_kh_check.setChecked(anis)
        self.kh_input.setEnabled(anis)
        if not anis:
            # Start with Kh = Kv only if no anisotropy configured
            _sync_kh(self.kv_input.value())

        # Ss
        self.ss_input = QDoubleSpinBox()
        self.ss_input.setRange(1e-8, 1e-2)
        self.ss_input.setDecimals(8)
        self.ss_input.setSingleStep(1e-6)
        self.ss_input.setValue(self.config["aquifer"]["ss"])
        layout.addRow(self._label_with_info("Ss (1/m):", "Specific storage (1/m). Typical: Sand ~1e-6–1e-5, Silt ~5e-6–5e-5, Clay ~1e-5–1e-3."), self.ss_input)

        # Sy
        self.sy_input = QDoubleSpinBox()
        self.sy_input.setRange(0.01, 0.5)
        self.sy_input.setValue(self.config["aquifer"]["sy"])
        self.sy_input.setDecimals(3)
        self.sy_input.setSingleStep(0.01)
        layout.addRow(self._label_with_info("Sy (-):", "Specific yield (–). Typical: Coarse sand/gravel 0.2–0.35, Sand 0.15–0.3, Silt 0.05–0.2, Clay 0.01–0.1."), self.sy_input)

        # Initial head
        self.initial_head_input = QDoubleSpinBox()
        self.initial_head_input.setRange(-100, 1000)
        self.initial_head_input.setValue(self.config["aquifer"]["initial_head"])
        self.initial_head_input.setSuffix(" m AHD")
        self.initial_head_input.setDecimals(2)
        layout.addRow(self._label_with_info("Initial GW Head:", "Initial groundwater head across the model domain (m AHD)."), self.initial_head_input)

        # Bottom elevation
        self.bottom_elev_input = QDoubleSpinBox()
        self.bottom_elev_input.setRange(-1000, 1000)
        self.bottom_elev_input.setValue(self.config["aquifer"]["bottom_elev"])
        self.bottom_elev_input.setSuffix(" m AHD")
        self.bottom_elev_input.setDecimals(2)
        layout.addRow(self._label_with_info("Aquifer Bottom:", "Optional bottom elevation of the aquifer/layer (m AHD). Prevents head < bottom errors."), self.bottom_elev_input)

        # hook overlay updates
        try:
            self.kv_input.valueChanged.connect(self._update_design_view)
            self.kh_input.valueChanged.connect(self._update_design_view)
            self.ss_input.valueChanged.connect(self._update_design_view)
            self.sy_input.valueChanged.connect(self._update_design_view)
            self.initial_head_input.valueChanged.connect(self._update_design_view)
            self.bottom_elev_input.valueChanged.connect(self._update_design_view)
        except Exception:
            pass

        group.setLayout(layout)
        return group
    
    def _create_infiltration_group(self):
        """Infiltration settings - matching Tkinter"""
        group = QGroupBox("Infiltration Properties")
        layout = QFormLayout()

        # Mode
        self.infiltration_mode = QComboBox()
        self.infiltration_mode.addItems(["full", "vertical"])
        self.infiltration_mode.setCurrentText(self.config["infiltration"]["mode"])
        layout.addRow(self._label_with_info("Infiltration Mode:", "Vertical: bed-only leakage. Full: bed and sidewalls leak."), self.infiltration_mode)

        # Bed thickness
        self.bed_thickness_input = QDoubleSpinBox()
        self.bed_thickness_input.setRange(0.01, 5)
        self.bed_thickness_input.setValue(self.config["infiltration"]["bed_thickness_m"])
        self.bed_thickness_input.setSuffix(" m")
        self.bed_thickness_input.setDecimals(2)
        layout.addRow(self._label_with_info("Bed Thickness:", "Thickness of basin bed (liner) controlling leakage path length."), self.bed_thickness_input)

        # Bed K
        self.bed_k_input = QDoubleSpinBox()
        self.bed_k_input.setRange(0.001, 1000)
        self.bed_k_input.setValue(self.config["infiltration"]["bed_k_mpd"])
        self.bed_k_input.setSuffix(" m/day")
        self.bed_k_input.setDecimals(3)
        layout.addRow(self._label_with_info("Bed K:", "Hydraulic conductivity of the basin bed/liner (m/day)."), self.bed_k_input)

        # Separate Side K checkbox (controls whether side K is independent)
        self.side_k_separate_check = QCheckBox("Use separate Side K")
        self.side_k_separate_check.setChecked(self.config["infiltration"].get("side_k_separate", False))
        layout.addRow(self._label_with_info("Side K Control:", "When unchecked, Side K equals Bed K automatically (recommended)."), self.side_k_separate_check)

        # Side K
        self.side_k_input = QDoubleSpinBox()
        self.side_k_input.setRange(0.0, 1000)
        self.side_k_input.setValue(self.config["infiltration"].get("side_k_mpd", 2.5))
        self.side_k_input.setSuffix(" m/day")
        self.side_k_input.setDecimals(3)
        layout.addRow(self._label_with_info("Side K:", "Hydraulic conductivity along basin sidewalls (m/day)."), self.side_k_input)

        # UZF Soil Parameters (Unsaturated Zone Flow)
        uzf_defaults = self.config.get("uzf", {})

        self.thts_input = QDoubleSpinBox()
        self.thts_input.setRange(0.10, 0.60)
        self.thts_input.setValue(float(uzf_defaults.get("thts", 0.35)))
        self.thts_input.setDecimals(3)
        self.thts_input.setSingleStep(0.01)
        layout.addRow(self._label_with_info("θs (sat. water content):", "Saturated water content (porosity). Sand 0.3–0.4, Silt 0.4–0.5, Clay 0.4–0.6."), self.thts_input)

        self.thtr_input = QDoubleSpinBox()
        self.thtr_input.setRange(0.01, 0.30)
        self.thtr_input.setValue(float(uzf_defaults.get("thtr", 0.05)))
        self.thtr_input.setDecimals(3)
        self.thtr_input.setSingleStep(0.01)
        layout.addRow(self._label_with_info("θr (resid. water content):", "Residual (irreducible) water content. Sand 0.03–0.08, Silt 0.05–0.15, Clay 0.07–0.2."), self.thtr_input)

        self.eps_input = QDoubleSpinBox()
        self.eps_input.setRange(1.0, 10.0)
        self.eps_input.setValue(float(uzf_defaults.get("eps", 4.0)))
        self.eps_input.setDecimals(1)
        self.eps_input.setSingleStep(0.5)
        layout.addRow(self._label_with_info("ε (Brooks-Corey):", "Brooks-Corey exponent controlling unsaturated K curve. Sand 3–5, Silt 4–8, Clay 2–4."), self.eps_input)

        self.thti_input = QDoubleSpinBox()
        self.thti_input.setRange(0.01, 0.50)
        self.thti_input.setValue(float(uzf_defaults.get("thti", 0.10)))
        self.thti_input.setDecimals(3)
        self.thti_input.setSingleStep(0.01)
        layout.addRow(self._label_with_info("θi (initial water content):", "Initial soil water content. Must satisfy θr ≤ θi ≤ θs. Typically near θr for dry soils."), self.thti_input)

        # Enforce θr ≤ θi ≤ θs constraint via signals
        def _clamp_uzf_params():
            try:
                thts = self.thts_input.value()
                thtr = self.thtr_input.value()
                if thtr >= thts:
                    self.thtr_input.setValue(thts - 0.01)
                thti = self.thti_input.value()
                thtr = self.thtr_input.value()  # re-read after possible clamp
                if thti < thtr:
                    self.thti_input.setValue(thtr)
                if thti > thts:
                    self.thti_input.setValue(thts)
            except Exception:
                pass
        self.thts_input.valueChanged.connect(_clamp_uzf_params)
        self.thtr_input.valueChanged.connect(_clamp_uzf_params)
        self.thti_input.valueChanged.connect(_clamp_uzf_params)

        # Wire interactions: mode changes, separate checkbox, and bed K changes affect side K enable/value
        try:
            self.infiltration_mode.currentTextChanged.connect(self._sync_infiltration_side_controls)
            self.side_k_separate_check.toggled.connect(self._sync_infiltration_side_controls)
            self.bed_k_input.valueChanged.connect(self._sync_infiltration_side_controls)
        except Exception:
            pass

        # Initial sync
        self._sync_infiltration_side_controls()

        group.setLayout(layout)
        return group

    def _sync_infiltration_side_controls(self):
        """Enforce rules:
        - Vertical mode: side leakage disabled (side_k_input disabled, forced to 0 in config)
        - Full mode: if not separate, side K mirrors bed K and is read-only; if separate, side K is editable
        """
        try:
            mode = self.infiltration_mode.currentText().strip().lower()
            separate = self.side_k_separate_check.isChecked()
            if mode == "vertical":
                # Disable side leakage in UI; keep value display-only and disabled
                self.side_k_input.setEnabled(False)
                # Do not override the displayed value here; config builder will force 0
            else:  # full
                if separate:
                    # Allow independent editing
                    self.side_k_input.setEnabled(True)
                else:
                    # Mirror bed K and lock
                    self.side_k_input.blockSignals(True)
                    self.side_k_input.setValue(self.bed_k_input.value())
                    self.side_k_input.blockSignals(False)
                    self.side_k_input.setEnabled(False)
        except Exception:
            pass
    
    def _create_performance_group(self):
        """Performance settings"""
        group = QGroupBox("Performance Settings")
        layout = QFormLayout()
        # Performance preset is fixed internally to "fast"; UI control removed
        note = QLabel("Performance Mode: fast (fixed)")
        note.setToolTip("Grid resolution and solver settings are fixed to the fast preset.")
        layout.addRow(note)
        
        group.setLayout(layout)
        return group

    def _create_outlet_group(self):
        """Outlet hydraulics overlay (post-processing).

        Supports multiple outlets: configure parameters below, then click
        "Add outlet" to append the current one to the list. Remove or clear
        as needed. Discharges are summed in post-processing.
        """
        group = QGroupBox("Outlet (post-processing overlay)")
        layout = QFormLayout()

        # Enable toggle
        self.outlet_enable = QCheckBox("Enable outlet overlay")
        self.outlet_enable.setChecked(False)
        layout.addRow(self._label_with_info("Enable:", "Apply outlet discharge to MF6 stage as a post-process. MF6 run is unchanged."), self.outlet_enable)

        # Type selector
        self.outlet_type = QComboBox()
        self.outlet_type.addItems(["pipe", "broad-crested weir", "grated inlet"])
        layout.addRow(self._label_with_info("Type:", "Choose the outlet structure type."), self.outlet_type)

        # Stacked parameter panels
        self.outlet_stack = QStackedWidget()
        # --- Pipe params ---
        pipe_w = QWidget(); pform = QFormLayout(pipe_w)
        self.pipe_diam = QDoubleSpinBox(); self.pipe_diam.setRange(0.01, 5.0); self.pipe_diam.setDecimals(3); self.pipe_diam.setValue(0.6); self.pipe_diam.setSuffix(" m")
        self.pipe_len = QDoubleSpinBox(); self.pipe_len.setRange(0.1, 500.0); self.pipe_len.setDecimals(2); self.pipe_len.setValue(10.0); self.pipe_len.setSuffix(" m")
        self.pipe_invert = QDoubleSpinBox(); self.pipe_invert.setRange(-1000, 1000); self.pipe_invert.setDecimals(3); self.pipe_invert.setSuffix(" m AHD"); self.pipe_invert.setValue(self.config["basin_geometry"]["floor_elev"])  # default at floor
        self.pipe_slope = QDoubleSpinBox(); self.pipe_slope.setRange(0.0001, 0.2); self.pipe_slope.setDecimals(4); self.pipe_slope.setSingleStep(0.001); self.pipe_slope.setValue(0.01)
        self.pipe_n = QDoubleSpinBox(); self.pipe_n.setRange(0.005, 0.05); self.pipe_n.setDecimals(3); self.pipe_n.setSingleStep(0.001); self.pipe_n.setValue(0.013)
        self.pipe_count = QSpinBox(); self.pipe_count.setRange(1, 10); self.pipe_count.setValue(1)
        self.pipe_entrance = QComboBox(); self.pipe_entrance.addItems(["square", "rounded", "beveled"]) 
        pform.addRow("Diameter:", self.pipe_diam)
        pform.addRow("Length:", self.pipe_len)
        pform.addRow("Invert level:", self.pipe_invert)
        pform.addRow(self._label_with_info("Slope (m/m):", "Pipe grade as m/m (e.g., 0.01 = 1%)."), self.pipe_slope)
        pform.addRow("Manning n:", self.pipe_n)
        pform.addRow("Count:", self.pipe_count)
        pform.addRow("Entrance:", self.pipe_entrance)
        self.outlet_stack.addWidget(pipe_w)
        # --- Weir params ---
        weir_w = QWidget(); wform = QFormLayout(weir_w)
        self.weir_crest = QDoubleSpinBox(); self.weir_crest.setRange(-1000, 1000); self.weir_crest.setDecimals(3); self.weir_crest.setSuffix(" m AHD"); self.weir_crest.setValue(self.config["basin_geometry"]["floor_elev"] + self.config["basin_geometry"]["max_depth"]) 
        self.weir_length = QDoubleSpinBox(); self.weir_length.setRange(0.1, 200.0); self.weir_length.setDecimals(3); self.weir_length.setValue(1.0); self.weir_length.setSuffix(" m")
        self.weir_Cd = QDoubleSpinBox(); self.weir_Cd.setRange(0.1, 2.0); self.weir_Cd.setDecimals(3); self.weir_Cd.setValue(0.577)
        wform.addRow("Crest level:", self.weir_crest)
        wform.addRow("Crest length:", self.weir_length)
        wform.addRow("Cd:", self.weir_Cd)
        self.outlet_stack.addWidget(weir_w)
        # --- Grate params ---
        grate_w = QWidget(); gform = QFormLayout(grate_w)
        self.grate_crest = QDoubleSpinBox(); self.grate_crest.setRange(-1000, 1000); self.grate_crest.setDecimals(3); self.grate_crest.setSuffix(" m AHD"); self.grate_crest.setValue(self.config["basin_geometry"]["floor_elev"]) 
        self.grate_area = QDoubleSpinBox(); self.grate_area.setRange(0.00, 10.0); self.grate_area.setDecimals(4); self.grate_area.setValue(0.06); self.grate_area.setSuffix(" m²")
        self.grate_perim = QDoubleSpinBox(); self.grate_perim.setRange(0.00, 20.0); self.grate_perim.setDecimals(3); self.grate_perim.setValue(1.2); self.grate_perim.setSuffix(" m")
        self.grate_type = QComboBox(); self.grate_type.addItems(["generic", "p1-1/8", "p1-7/8", "reticuline"]) 
        gform.addRow("Crest level:", self.grate_crest)
        gform.addRow("Open area:", self.grate_area)
        gform.addRow("Perimeter:", self.grate_perim)
        gform.addRow("Grate type:", self.grate_type)
        self.outlet_stack.addWidget(grate_w)

        # Wiring
        def _update_stack():
            idx = {"pipe": 0, "broad-crested weir": 1, "grated inlet": 2}.get(self.outlet_type.currentText().strip().lower(), 0)
            self.outlet_stack.setCurrentIndex(idx)
            en = self.outlet_enable.isChecked()
            self.outlet_type.setEnabled(en)
            self.outlet_stack.setEnabled(en)
        self.outlet_type.currentTextChanged.connect(_update_stack)
        self.outlet_enable.toggled.connect(_update_stack)
        _update_stack()

        # Add/Remove buttons and list of configured outlets
        layout.addRow(self.outlet_stack)
        btn_row = QHBoxLayout()
        self.btn_outlet_add = QPushButton("Add outlet")
        self.btn_outlet_remove = QPushButton("Remove selected")
        self.btn_outlet_clear = QPushButton("Clear all")
        btn_row.addWidget(self.btn_outlet_add)
        btn_row.addWidget(self.btn_outlet_remove)
        btn_row.addWidget(self.btn_outlet_clear)
        btn_row.addStretch()
        layout.addRow(btn_row)

        self.outlet_list = QListWidget()
        self.outlet_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addRow(self._label_with_info("Configured outlets:", "Order isn't important; flows are summed."), self.outlet_list)

        # Internal store
        self._outlets_cfg = []  # type: list[dict]

        def _add_current_outlet():
            if not self.outlet_enable.isChecked():
                return
            cfg = {"enabled": True}
            typ_txt = self.outlet_type.currentText().strip().lower()
            if "pipe" in typ_txt:
                cfg.update({
                    "type": "pipe",
                    "diameter_m": float(self.pipe_diam.value()),
                    "length_m": float(self.pipe_len.value()),
                    "invert_mAHD": float(self.pipe_invert.value()),
                    "grade": float(self.pipe_slope.value()),
                    "mannings_n": float(self.pipe_n.value()),
                    "count": int(self.pipe_count.value()),
                    "entrance_type": self.pipe_entrance.currentText().strip().lower(),
                })
                label = f"Pipe D={cfg['diameter_m']:.3f}m inv={cfg['invert_mAHD']:.3f}m x{cfg['count']}"
            elif "broad" in typ_txt:
                cfg.update({
                    "type": "broad_crested_weir",
                    "crest_mAHD": float(self.weir_crest.value()),
                    "crest_length_m": float(self.weir_length.value()),
                    "Cd": float(self.weir_Cd.value()),
                })
                label = f"Weir z={cfg['crest_mAHD']:.3f}m L={cfg['crest_length_m']:.2f}m"
            else:
                cfg.update({
                    "type": "grated_inlet",
                    "crest_mAHD": float(self.grate_crest.value()),
                    "grate_area_m2": float(self.grate_area.value()),
                    "perimeter_m": float(self.grate_perim.value()),
                    "grate_type": self.grate_type.currentText().strip().lower(),
                })
                label = f"Grate z={cfg['crest_mAHD']:.3f}m A={cfg['grate_area_m2']:.3f}m²"
            self._outlets_cfg.append(cfg)
            self.outlet_list.addItem(label)

        def _remove_selected():
            rows = sorted({idx.row() for idx in self.outlet_list.selectedIndexes()}, reverse=True)
            for r in rows:
                if 0 <= r < len(self._outlets_cfg):
                    del self._outlets_cfg[r]
                    self.outlet_list.takeItem(r)

        def _clear_all():
            self._outlets_cfg.clear()
            self.outlet_list.clear()

        self.btn_outlet_add.clicked.connect(_add_current_outlet)
        self.btn_outlet_remove.clicked.connect(_remove_selected)
        self.btn_outlet_clear.clicked.connect(_clear_all)

        # Expand enable toggle to include new widgets
        def _toggle_group(en: bool):
            self.outlet_type.setEnabled(en)
            self.outlet_stack.setEnabled(en)
            self.btn_outlet_add.setEnabled(en)
            self.btn_outlet_remove.setEnabled(en)
            self.btn_outlet_clear.setEnabled(en)
            self.outlet_list.setEnabled(en)
        try:
            self.outlet_enable.toggled.connect(_toggle_group)
            _toggle_group(self.outlet_enable.isChecked())
        except Exception:
            pass

        group.setLayout(layout)
        return group
    
    def _create_ts1_group(self):
        """TS1 file selection"""
        group = QGroupBox("Storm Events (TS1 Files)")
        layout = QVBoxLayout()

        # Header with import and folder links
        header = QHBoxLayout()
        btn_import = QPushButton("Import TS1…")
        btn_import.clicked.connect(self.add_ts1_files)
        header.addWidget(btn_import)
        btn_import_dir = QPushButton("Import Folder…")
        btn_import_dir.clicked.connect(self.add_ts1_folder)
        header.addWidget(btn_import_dir)
        header.addStretch()
        # Input/Output folder buttons should appear after a run
        self.btn_open_in = QPushButton("Open Input Folder")
        self.btn_open_in.clicked.connect(self.open_input_folder)
        self.btn_open_in.setVisible(False)
        header.addWidget(self.btn_open_in)
        self.btn_open_out = QPushButton("Open Output Folder")
        self.btn_open_out.clicked.connect(self.open_output_folder)
        self.btn_open_out.setVisible(False)
        header.addWidget(self.btn_open_out)
        layout.addLayout(header)

        # List widget with per-item progress bars
        self.ts1_list = QListWidget()
        self.ts1_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.ts1_list)

        # Footer buttons
        button_layout = QHBoxLayout()
        self.remove_ts1_button = QPushButton("Remove Selected")
        self.remove_ts1_button.clicked.connect(self.remove_ts1_files)
        button_layout.addWidget(self.remove_ts1_button)
        self.clear_ts1_button = QPushButton("Clear All")
        self.clear_ts1_button.clicked.connect(self.clear_ts1_files)
        button_layout.addWidget(self.clear_ts1_button)
        layout.addLayout(button_layout)

    # Do not auto-preload TS1 files; user will add them explicitly
    # (disabled previous call to self._preload_ts1_files())

        group.setLayout(layout)
        return group
    
    def _create_simulation_group(self):
        """Simulation settings"""
        group = QGroupBox("Simulation Settings")
        layout = QFormLayout()

        # Scenario name
        self.scenario_name = QLineEdit(self.config.get("scenario_title", "Scenario 1"))
        self.scenario_name.setToolTip("User-defined scenario name used in outputs and reports.")
        layout.addRow(self._label_with_info("Scenario Name:", "Name for this scenario; appears in output folders and reports."), self.scenario_name)

        # Post-storm days
        self.post_storm_days_input = QDoubleSpinBox()
        self.post_storm_days_input.setRange(0, 30)
        self.post_storm_days_input.setValue(self.config["post_storm_days"])
        self.post_storm_days_input.setSuffix(" days")
        self.post_storm_days_input.setDecimals(1)
        layout.addRow(self._label_with_info("Post-storm Duration:", "Days simulated after storm ends."), self.post_storm_days_input)

        # Post-storm step
        self.post_storm_step_input = QDoubleSpinBox()
        self.post_storm_step_input.setRange(0.1, 24)
        self.post_storm_step_input.setValue(self.config["post_storm_step_hours"])
        self.post_storm_step_input.setSuffix(" hours")
        self.post_storm_step_input.setDecimals(1)
        layout.addRow(self._label_with_info("Post-storm Step:", "Time step during post-storm period (hours)."), self.post_storm_step_input)

    # (Removed boundary tuning and bed leak controls per request)

        # Output options
        self.lightweight_check = QCheckBox("Lightweight outputs")
        self.lightweight_check.setChecked(self.config["lightweight_outputs"])
        layout.addRow("", self.lightweight_check)

        self.cleanup_check = QCheckBox("Clean up heavy files (.bud/.hds/.lst/basin_budget.txt)")
        # Default enabled
        try:
            self.cleanup_check.setChecked(bool(self.config.get("cleanup_heavy", True)))
        except Exception:
            self.cleanup_check.setChecked(True)
        layout.addRow("", self.cleanup_check)

    # Output base directory selector
        out_row = QWidget()
        out_h = QHBoxLayout(out_row)
        out_h.setContentsMargins(0, 0, 0, 0)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Default (workspace/model_output/phase3/step32/scenarios)")
        browse_btn = QPushButton("Browse…")
        def _choose_out():
            d = QFileDialog.getExistingDirectory(self, "Select Output Base Folder", str(USER_BASE / "model_output"))
            if d:
                try:
                    self.output_dir_edit.setText(d)
                except Exception:
                    pass
        browse_btn.clicked.connect(_choose_out)
        out_h.addWidget(self.output_dir_edit, 1)
        out_h.addWidget(browse_btn, 0)
        layout.addRow(self._label_with_info("Output Folder:", "Base folder for scenario outputs. Each TS1 gets a subfolder."), out_row)

        group.setLayout(layout)
        return group
    
    def _create_run_controls(self):
        """Run controls"""
        group = QGroupBox("Execution")
        layout = QVBoxLayout()

        # Parallel processing
        self.parallel_check = QCheckBox("Use parallel processing (all CPU cores)")
        self.parallel_check.setChecked(True)
        layout.addWidget(self.parallel_check)

        # Run button
        self.run_button = QPushButton("Run Simulations")
        self.run_button.clicked.connect(self.run_simulations)
        layout.addWidget(self.run_button)

        # Clear + Re-Run
        self.clear_rerun_button = QPushButton("Clear Results and Re-Run")
        self.clear_rerun_button.setToolTip("Deletes this scenario's outputs, clears plots/tables, then runs fresh.")
        self.clear_rerun_button.clicked.connect(self.clear_and_rerun)
        layout.addWidget(self.clear_rerun_button)

        # Show run log button
        self.show_log_button = QPushButton("Show Run Log")
        self.show_log_button.clicked.connect(self.show_run_log)
        layout.addWidget(self.show_log_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Current status
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        group.setLayout(layout)
        return group

    def _scenario_dirs(self) -> tuple[Path, Path, Path]:
        """Return (scen_dir, inputs_dir, outputs_root) for current scenario."""
        scenario_title = self.scenario_name.text().strip() or "Scenario 1"
        base = self.output_dir_edit.text().strip() or str(USER_BASE / "model_output" / "phase3" / "step32" / "scenarios")
        base_out = Path(base)
        scen_dir = base_out / scenario_title
        inputs_dir = scen_dir / "inputs"
        outputs_root = scen_dir / "outputs"
        return scen_dir, inputs_dir, outputs_root

    def _clear_ui_results(self):
        """Clear in-memory results and associated UI widgets/plots."""
        try:
            self.results_table.setRowCount(0)
            self.results.clear()
        except Exception:
            pass
        # Clear any cached water-balance DataFrames
        try:
            if hasattr(self, '_wb_cache') and isinstance(self._wb_cache, dict):
                self._wb_cache.clear()
        except Exception:
            pass
        # Clear overlay plot
        try:
            if hasattr(self, 'plot_widget') and self.plot_widget is not None:
                self.plot_widget.clear()
        except Exception:
            pass
        # Clear flow plot and selector
        try:
            if hasattr(self, 'flow_plot') and self.flow_plot is not None:
                self.flow_plot.clear()
            if hasattr(self, 'flow_run_select') and self.flow_run_select is not None:
                self.flow_run_select.clear()
        except Exception:
            pass
        # Clear report preview if present
        try:
            if hasattr(self, 'report_preview') and self.report_preview is not None:
                self.report_preview.clear()
        except Exception:
            pass
        # Reset status
        try:
            self.status_label.setText("Ready")
        except Exception:
            pass

    def clear_and_rerun(self):
        """Delete scenario outputs, clear UI state, and re-run with current parameters."""
        try:
            print("[BaSIM] Clear Results and Re-Run: clicked")
            # Visible feedback that the click was handled
            try:
                self.status_bar.showMessage("Clear Results and Re-Run clicked", 3000)
                self._log_line("Clear Results and Re-Run clicked")
            except Exception:
                pass

            # Prefer deriving paths from existing results (authoritative) if available
            scen_dir, inputs_dir, outputs_root = self._scenario_dirs()
            try:
                if getattr(self, 'results', None):
                    for ts1_key, res in self.results.items():
                        out_dir = res.get('output_dir')
                        if out_dir:
                            out_dir_p = Path(out_dir)
                            if out_dir_p.exists():
                                outputs_root = out_dir_p.parent
                                scen_dir = outputs_root.parent
                                inputs_dir = scen_dir / 'inputs'
                                break
            except Exception:
                pass

            # Confirm (use static question to get StandardButton result reliably in Qt6)
            print(f"[BaSIM] Clear Results and Re-Run: confirming for outputs at {outputs_root}")
            ret = QMessageBox.question(
                self,
                "Clear Results and Re-Run",
                f"This will delete results under:\n{outputs_root}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                print("[BaSIM] Clear Results and Re-Run: user cancelled")
                return

            # Delete outputs folder (preserve inputs)
            try:
                import shutil
                if outputs_root.exists():
                    print(f"[BaSIM] Deleting outputs folder: {outputs_root}")
                    # try robust removal; if still exists, attempt rename fallback
                    shutil.rmtree(outputs_root, ignore_errors=True)
                    if outputs_root.exists():
                        try:
                            from datetime import datetime as _dt
                            fallback = outputs_root.with_name(f"outputs_old_{_dt.now().strftime('%Y%m%d_%H%M%S')}")
                            outputs_root.rename(fallback)
                            print(f"[BaSIM] Outputs locked, renamed to: {fallback}")
                        except Exception:
                            pass
            except Exception as e:
                QMessageBox.warning(self, "Clear Results", f"Failed to delete outputs: {e}")

            # Remove stale scenario caches
            try:
                for pat in ("*overlay*.png", "*overlay*.svg", "scenario_summary.json"):
                    for p in scen_dir.glob(pat):
                        try:
                            p.unlink(missing_ok=True)
                            print(f"[BaSIM] Removed cache: {p.name}")
                        except Exception:
                            pass
            except Exception:
                pass

            # Clear UI and re-run
            try:
                self.status_label.setText("Clearing…")
            except Exception:
                pass
            try:
                self._log_line(f"Clearing outputs under: {outputs_root}")
            except Exception:
                pass
            self._clear_ui_results()
            try:
                self.status_label.setText("Re-running…")
            except Exception:
                pass
            # Ensure the run log is visible for feedback
            try:
                self.show_run_log()
            except Exception:
                pass
            # Disable run button to prevent double triggers during kick-off
            try:
                self.run_button.setEnabled(False)
            except Exception:
                pass
            print("[BaSIM] Starting run_simulations() from Clear Results and Re-Run")
            self.run_simulations()
        except Exception as e:
            try:
                QMessageBox.critical(self, "Clear & Re-Run Error", str(e))
            except Exception:
                pass
    
    def _create_results_tabs(self):
        """Create result tabs"""
        # Summary tab
        self.summary_tab = QWidget()
        summary_layout = QVBoxLayout(self.summary_tab)

        # Total basin storage label (shown above table)
        self._basin_storage_label = QLabel("")
        self._basin_storage_label.setWordWrap(True)
        self._basin_storage_label.setStyleSheet("font-size: 13px; padding: 4px 8px;")
        summary_layout.addWidget(self._basin_storage_label)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(12)
        self.results_table.setHorizontalHeaderLabels([
            "TS1 File", "Status", "Peak Stage (m)",
            "Cumulative Inflow (m³)", "Peak Storage (m³)",
            "Mean Infil (m³/day)", "Spill",
            "Peak Outlet (m³/s)", "Total Outlet (m³)",
            "Runtime (s)", "Ensemble", "Output Directory"
        ])
        summary_layout.addWidget(self.results_table)

        self.results_tabs.addTab(self.summary_tab, "Summary")

        # Stage Timeseries tab
        self.timeseries_tab = QWidget()
        ts_layout = QVBoxLayout(self.timeseries_tab)

        if PYQTGRAPH_AVAILABLE:
            # Top: overlay plot (all runs)
            self.plot_widget = pg.GraphicsLayoutWidget()
            ts_layout.addWidget(self.plot_widget)

            # Informative note: detailed inflow/storage moved to dedicated tab
            moved_lbl = QLabel("Detailed inflow, cumulative inflow, and storage plots are now in the 'Inflow - Storage - Outflow' tab.")
            moved_lbl.setWordWrap(True)
            ts_btn_row = QHBoxLayout()
            ts_btn_row.addWidget(moved_lbl, 1)
            btn_export_stage_csv = QPushButton("Export Graph Data (CSV)")
            btn_export_stage_csv.clicked.connect(self._export_stage_csv)
            ts_btn_row.addWidget(btn_export_stage_csv)
            ts_layout.addLayout(ts_btn_row)

            # Keep placeholders to avoid attribute errors if referenced; hide container
            self.detail_plot = None  # type: ignore
            self._detail_right_axis = None
            self._detail_right_view = None
            self._detail_legend = None
            self._detail_container = QWidget()
            self._detail_container.setLayout(QVBoxLayout())
            self._detail_container.setVisible(False)
            # Hidden controls to satisfy selector references in detailed plot logic
            # (we moved inflow/storage details to the Flow tab, but keep these stubs to avoid AttributeErrors)
            try:
                ctrl_row = QWidget()
                ctrl_row.setLayout(QHBoxLayout())
                ctrl_row.layout().setContentsMargins(0, 0, 0, 0)
                self.detail_run_select = QComboBox()
                self.detail_run_select.currentIndexChanged.connect(self._update_detailed_plot)
                self.detail_time_unit_select = QComboBox()
                self.detail_time_unit_select.addItem("Days", userData="days")
                self.detail_time_unit_select.addItem("Hours", userData="hours")
                self.detail_time_unit_select.setCurrentIndex(0)
                self.detail_time_unit_select.currentIndexChanged.connect(self._update_detailed_plot)
                # Add but keep the whole detailed container hidden
                ctrl_row.layout().addWidget(QLabel("Run:"))
                ctrl_row.layout().addWidget(self.detail_run_select, 1)
                ctrl_row.layout().addWidget(QLabel("Time:"))
                ctrl_row.layout().addWidget(self.detail_time_unit_select)
                self._detail_container.layout().addWidget(ctrl_row)
            except Exception:
                pass
            ts_layout.addWidget(self._detail_container)

            # Cache for water balance CSVs
            self._wb_cache = {}
        else:
            ts_layout.addWidget(QLabel("Install pyqtgraph for plotting: pip install pyqtgraph"))

        self.results_tabs.addTab(self.timeseries_tab, "Stage Timeseries")

        # Inflow - Storage - Outflow tab
        self.flow_tab = QWidget()
        flow_layout = QVBoxLayout(self.flow_tab)
        if PYQTGRAPH_AVAILABLE:
            flow_ctrl = QHBoxLayout()
            flow_ctrl.addWidget(QLabel("Run:"))
            self.flow_run_select = QComboBox()
            self.flow_run_select.currentIndexChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_run_select, 1)
            flow_ctrl.addWidget(QLabel("Time:"))
            self.flow_time_unit_select = QComboBox()
            self.flow_time_unit_select.addItem("Days", userData="days")
            self.flow_time_unit_select.addItem("Hours", userData="hours")
            self.flow_time_unit_select.setCurrentIndex(0)
            self.flow_time_unit_select.currentIndexChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_time_unit_select)
            # Toggle
            self.flow_chk_cum_in = QCheckBox("Inflows (right)")
            self.flow_chk_cum_in.setChecked(True)
            self.flow_chk_cum_in.stateChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_chk_cum_in)
            self.flow_chk_storage = QCheckBox("Storage")
            self.flow_chk_storage.setChecked(True)
            self.flow_chk_storage.stateChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_chk_storage)
            # cumulative infiltration removed per user request
            self.flow_chk_gwf_in = QCheckBox("GW inflow (left)")
            self.flow_chk_gwf_in.setChecked(True)
            self.flow_chk_gwf_in.stateChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_chk_gwf_in)
            self.flow_chk_outlet = QCheckBox("Outlet (left)")
            self.flow_chk_outlet.setChecked(True)
            self.flow_chk_outlet.stateChanged.connect(self._update_flow_plot)
            flow_ctrl.addWidget(self.flow_chk_outlet)
            flow_layout.addLayout(flow_ctrl)

            # Big plot container
            self.flow_plot = None  # created lazily
            self._flow_right_axis = None
            self._flow_right_view = None
            self._flow_legend = None
            self._flow_container = QWidget()
            self._flow_container.setLayout(QVBoxLayout())
            flow_layout.addWidget(self._flow_container, 1)

            # Residual diagnostic label
            self.flow_diag_label = QLabel("")
            self.flow_diag_label.setWordWrap(True)
            flow_diag_row = QHBoxLayout()
            flow_diag_row.addWidget(self.flow_diag_label, 1)
            btn_export_flow_csv = QPushButton("Export Graph Data (CSV)")
            btn_export_flow_csv.clicked.connect(self._export_flow_csv)
            flow_diag_row.addWidget(btn_export_flow_csv)
            flow_layout.addLayout(flow_diag_row)
        else:
            flow_layout.addWidget(QLabel("Install pyqtgraph for plotting: pip install pyqtgraph"))
        self.results_tabs.addTab(self.flow_tab, "Inflow - Storage - Outflow")

        # Report tab with Export button
        self.report_container = QWidget()
        rep_layout = QVBoxLayout(self.report_container)
        rep_top = QHBoxLayout()
        self.btn_export_pdf = QPushButton("Export Design Report (PDF)")
        self.btn_export_pdf.clicked.connect(self.export_report_pdf)
        rep_top.addWidget(self.btn_export_pdf)
        rep_top.addStretch()
        rep_layout.addLayout(rep_top)
        self.report_edit = QTextEdit()
        self.report_edit.setReadOnly(True)
        rep_layout.addWidget(self.report_edit, 1)
        self.results_tabs.addTab(self.report_container, "Report")

        # Run log dialog
        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle("Run Log")
        self.log_dialog.resize(800, 500)
        ld_layout = QVBoxLayout(self.log_dialog)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        ld_layout.addWidget(self.log_text)
    
    def _create_menu_bar(self):
        """Create menu bar"""
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        import_ts1_action = QAction("Import TS1 Files…", self)
        import_ts1_action.triggered.connect(self.add_ts1_files)
        file_menu.addAction(import_ts1_action)

        import_ts1_folder_action = QAction("Import TS1 Folder…", self)
        import_ts1_folder_action.triggered.connect(self.add_ts1_folder)
        file_menu.addAction(import_ts1_folder_action)

        file_menu.addSeparator()

        save_config_action = QAction("Save Configuration", self)
        save_config_action.triggered.connect(self.save_configuration)
        file_menu.addAction(save_config_action)

        load_config_action = QAction("Load Configuration", self)
        load_config_action.triggered.connect(self.load_configuration)
        file_menu.addAction(load_config_action)

        file_menu.addSeparator()

        export_results_action = QAction("Export Results...", self)
        export_results_action.triggered.connect(self.export_results)
        file_menu.addAction(export_results_action)

        export_stage_csv_action = QAction("Export Stage Graph Data (CSV)…", self)
        export_stage_csv_action.triggered.connect(self._export_stage_csv)
        file_menu.addAction(export_stage_csv_action)

        export_flow_csv_action = QAction("Export Flow Graph Data (CSV)…", self)
        export_flow_csv_action.triggered.connect(self._export_flow_csv)
        file_menu.addAction(export_flow_csv_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # No top toolbar per request

        # Convert menu (between File and Help)
        convert_menu = menubar.addMenu("Convert")
        convert_action = QAction("Batch Convert to TS1…", self)
        convert_action.triggered.connect(self._open_convert_to_ts1_dialog)
        convert_menu.addAction(convert_action)

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = QAction("About BaSIM", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        lic_action = QAction("License…", self)
        lic_action.triggered.connect(self.show_license_dialog)
        help_menu.addAction(lic_action)

    # --- Licensing ---
    def _license_verifier(self) -> LicenseVerifier:
        try:
            return LicenseVerifier()
        except Exception:
            return LicenseVerifier()

    def _update_license_status_bar(self):
        ver = self._license_verifier()
        st = ver.validate_installed()
        if st.ok:
            msg = f"Ready — License: {st.edition or 'Standard'} | {st.days_left} days left"
        else:
            msg = "Ready — Unlicensed (runs disabled)"
        try:
            self.status_bar.showMessage(msg)
        except Exception:
            pass
        # Also reflect license state on the Run button
        try:
            if st.ok:
                self.run_button.setEnabled(True)
                self.run_button.setToolTip("")
            else:
                self.run_button.setEnabled(False)
                self.run_button.setToolTip("Install a valid license via Help → License… to enable runs.")
        except Exception:
            pass

    def show_license_dialog(self):
        try:
            dlg = LicenseDialog(self)
            dlg.exec()
        finally:
            self._update_license_status_bar()

    def _ensure_license_for_run(self) -> bool:
        ver = self._license_verifier()
        st = ver.validate_installed()
        if st.ok:
            # Optional: warn if near expiry
            try:
                if st.days_left is not None and st.days_left <= 7:
                    self.status_bar.showMessage(f"License expiring soon: {st.days_left} day(s) left", 8000)
            except Exception:
                pass
            return True
        # Not licensed: prompt
        ret = QMessageBox.question(
            self,
            "License Required",
            "This action requires a valid BaSIM license. Open License manager now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.show_license_dialog()
            st2 = ver.validate_installed()
            if st2.ok:
                return True
        # Final notice
        try:
            QMessageBox.critical(self, "License Missing", st.message or "No valid license installed.")
        except Exception:
            pass
        return False

    def _maybe_prompt_license_on_first_run(self):
        """If no license is installed, proactively open the License dialog once at startup."""
        if getattr(self, "_did_prompt_license", False):
            return
        try:
            ver = self._license_verifier()
            st = ver.validate_installed()
            if not st.ok:
                self._did_prompt_license = True
                # Inform the user and open the license manager
                try:
                    QMessageBox.information(
                        self,
                        "License Required",
                        "BaSIM requires a valid license before running simulations. The License window will open now.",
                    )
                except Exception:
                    pass
                self.show_license_dialog()
        except Exception:
            pass

    # --- Convert to TS1 support ---
    def _find_convert_to_ts1_exe(self) -> Optional[str]:
        """Locate convert_to_ts1_w64.exe in dev or packaged layouts (onefile/onedir)."""
        exe_name = 'convert_to_ts1_w64.exe'
        candidates: List[Path] = []
        try:
            # Dev checkout locations
            candidates.append(DEV_ROOT / exe_name)
            candidates.append(DEV_ROOT / 'bin' / exe_name)
            # Packaged (PyInstaller) locations: APP_BASE is either _MEIPASS or folder of EXE
            candidates.append(APP_BASE / 'bin' / exe_name)
            candidates.append(APP_BASE / exe_name)
        except Exception:
            pass
        for c in candidates:
            try:
                if c and c.exists():
                    return str(c)
            except Exception:
                continue
        return None

    def _open_convert_to_ts1_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Batch Convert to TS1")
        lay = QFormLayout(dlg)

        fmt = QComboBox()
        fmt.addItem("RAFTS (.tot/.loc)", "-rafts")
        fmt.addItem("RORB (.out)", "-rorb")
        fmt.addItem("URBS (.q)", "-urbs")
        fmt.addItem("WBNM (_Meta.out)", "-wbnm")
        fmt.addItem("XP-SWMM (.int/.ext)", "-xp")
        fmt.addItem("Rows (blocks, no time)", "-rows")
        lay.addRow("Input format:", fmt)

        dt_box = QSpinBox()
        dt_box.setRange(1, 1440)
        dt_box.setValue(5)
        dt_box.setSuffix(" min")
        dt_row = QWidget(); dt_row.setLayout(QHBoxLayout()); dt_row.layout().setContentsMargins(0,0,0,0)
        dt_row.layout().addWidget(dt_box)
        dt_note = QLabel("Required for RORB (-dt)")
        dt_note.setStyleSheet("color: #aaa")
        dt_row.layout().addWidget(dt_note)
        lay.addRow("RORB dt:", dt_row)

        s0 = QCheckBox("Insert zero at start (-s0)")
        e0 = QCheckBox("Insert zero at end (-e0)")
        opts = QWidget(); opts.setLayout(QHBoxLayout()); opts.layout().setContentsMargins(0,0,0,0)
        opts.layout().addWidget(s0); opts.layout().addWidget(e0)
        lay.addRow("Options:", opts)

        files_edit = QLineEdit(); files_edit.setReadOnly(True)
        pick_files_btn = QPushButton("Select files…")
        def pick_files():
            # Allow any files; enforce same format by user selection
            files, _ = QFileDialog.getOpenFileNames(dlg, "Select input files", str(USER_BASE))
            if files:
                files_edit.setText("; ".join(files))
        pick_files_btn.clicked.connect(pick_files)
        frow = QWidget(); frow.setLayout(QHBoxLayout()); frow.layout().setContentsMargins(0,0,0,0)
        frow.layout().addWidget(files_edit, 1); frow.layout().addWidget(pick_files_btn)
        lay.addRow("Files:", frow)

        out_edit = QLineEdit(); out_edit.setReadOnly(True)
        pick_out_btn = QPushButton("Select folder…")
        def pick_out():
            d = QFileDialog.getExistingDirectory(dlg, "Select output folder", str(USER_BASE / 'model_input' / 'ts1_files'))
            if d:
                out_edit.setText(d)
        pick_out_btn.clicked.connect(pick_out)
        orow = QWidget(); orow.setLayout(QHBoxLayout()); orow.layout().setContentsMargins(0,0,0,0)
        orow.layout().addWidget(out_edit, 1); orow.layout().addWidget(pick_out_btn)
        lay.addRow("Save TS1 to:", orow)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addRow(btns)

        def on_ok():
            exe = self._find_convert_to_ts1_exe()
            if not exe:
                QMessageBox.critical(self, "Converter Not Found", "convert_to_ts1_w64.exe not found. It should be bundled under bin/.")
                return
            files = [f.strip() for f in files_edit.text().split(';') if f.strip()]
            if not files:
                QMessageBox.warning(self, "No Files", "Please select one or more input files.")
                return
            out_dir = out_edit.text().strip()
            if not out_dir:
                QMessageBox.warning(self, "No Output Folder", "Please choose where to save the TS1 files.")
                return
            # Build args - use relative filenames only
            args = [str(Path(exe).resolve()), fmt.currentData(), '-ts1', '-b']
            if fmt.currentData() == '-rorb':
                args.append(f"-dt{int(dt_box.value())}")
            if s0.isChecked():
                args.append('-s0')
            if e0.isChecked():
                args.append('-e0')
            
            # Group files by directory and process each directory separately
            files_by_dir = {}
            for f in files:
                p = Path(f)
                dir_path = p.parent
                if dir_path not in files_by_dir:
                    files_by_dir[dir_path] = []
                files_by_dir[dir_path].append(p.name)

            # Snapshot existing ts1 in involved folders
            before_map: Dict[Path, set] = {}
            for dir_path in files_by_dir.keys():
                try:
                    before_map[dir_path] = set(x.name for x in dir_path.glob('*.ts1'))
                except Exception:
                    before_map[dir_path] = set()

            # Run in worker so UI stays responsive
            prog = QProgressDialog("Converting…", None, 0, 0, self)
            prog.setWindowTitle("Convert to TS1")
            prog.setWindowModality(Qt.WindowModality.ApplicationModal)
            prog.show()

            result_holder = {"ok": False, "err": None}

            def work():
                try:
                    # Process each directory separately (like the working batch file)
                    all_new_files = []
                    for dir_path, filenames in files_by_dir.items():
                        # Run converter in each directory with relative filenames
                        dir_args = args + filenames
                        cp = subprocess.run(dir_args, cwd=str(dir_path), capture_output=True, text=True, shell=False)
                        if cp.returncode != 0:
                            result_holder["err"] = f"Directory {dir_path}:\n{cp.stderr or cp.stdout or f'Exit code {cp.returncode}'}"
                            return
                        
                        # Collect new ts1 files from this directory (including .out.ts1 files)
                        before = before_map.get(dir_path, set())
                        try:
                            # Get all .ts1 files after conversion
                            all_ts1_files = list(dir_path.glob('*.ts1'))
                            after = set(x.name for x in all_ts1_files)
                            new_files = after - before
                            
                            # If no new files detected by diff, assume all ts1 files are new
                            # (in case the before snapshot missed some due to timing)
                            if not new_files and all_ts1_files:
                                new_files = after
                            
                            for name in sorted(new_files):
                                all_new_files.append(dir_path / name)
                        except Exception:
                            pass
                    
                    # Copy all new files to output directory
                    Path(out_dir).mkdir(parents=True, exist_ok=True)
                    for nf in all_new_files:
                        try:
                            shutil.copy2(str(nf), str(Path(out_dir) / nf.name))
                        except Exception:
                            pass
                    result_holder["ok"] = True
                except Exception as e:
                    result_holder["err"] = str(e)

            # Spin up thread
            import threading
            t = threading.Thread(target=work, daemon=True)
            t.start()
            while t.is_alive():
                QApplication.processEvents()
                QThread.msleep(50)
            prog.close()

            if not result_holder["ok"]:
                QMessageBox.critical(self, "Conversion Failed", f"convert_to_ts1 failed.\n\n{result_holder['err']}")
            else:
                QMessageBox.information(self, "Conversion Complete", f"Conversion finished. TS1 files saved to:\n{out_dir}")
            dlg.accept()

        btns.accepted.connect(on_ok)
        btns.rejected.connect(dlg.reject)
        dlg.exec()
    
    def _preload_ts1_files(self):
        """Pre-load TS1 files from default directory"""
        ts1_dir = USER_BASE / "model_input" / "ts1_files"
        if ts1_dir.exists():
            for ts1_file in sorted(ts1_dir.glob("*.ts1")):
                self._add_ts1_item(str(ts1_file))
    
    def add_ts1_files(self):
        """Add TS1 files"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select TS1 Files",
            str(USER_BASE / "model_input" / "ts1_files"),
            "TS1 Files (*.ts1);;All Files (*.*)"
        )
        
        for file in files:
            if file not in self.ts1_files:
                self._add_ts1_item(file)
    
    def add_ts1_folder(self):
        """Add all TS1 files from a selected folder"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select TS1 Folder",
            str(USER_BASE / "model_input" / "ts1_files")
        )
        if not folder:
            return
        for p in sorted(Path(folder).glob("*.ts1")):
            sp = str(p)
            if sp not in self.ts1_files:
                self._add_ts1_item(sp)
    
    def remove_ts1_files(self):
        """Remove selected TS1 files"""
        for item in self.ts1_list.selectedItems():
            row = self.ts1_list.row(item)
            witem = self.ts1_list.takeItem(row)
            # remove mapping by path
            for path, (it, _, _) in list(self.ts1_widgets.items()):
                if it is witem:
                    self.ts1_widgets.pop(path, None)
                    if path in self.ts1_files:
                        self.ts1_files.remove(path)
                    break
    
    def clear_ts1_files(self):
        """Clear all TS1 files"""
        self.ts1_list.clear()
        self.ts1_files.clear()
        self.ts1_widgets.clear()

    def _add_ts1_item(self, path: str):
        item = QListWidgetItem()
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(6, 4, 6, 4)
        lbl = QLabel(Path(path).name)
        lbl.setToolTip(path)
        bar = QProgressBar()
        bar.setMaximumHeight(16)
        bar.setTextVisible(True)
        bar.setRange(0, 0)  # busy spinner by default
        bar.setFormat("Queued")
        h.addWidget(lbl, 1)
        h.addWidget(bar, 0)
        widget.setLayout(h)
        self.ts1_list.addItem(item)
        self.ts1_list.setItemWidget(item, widget)
        self.ts1_files.append(path)
        self.ts1_widgets[path] = (item, widget, bar)

    def open_input_folder(self):
        # Prefer the input folder of the last run if available
        path = None
        # open inputs folder alongside last output run
        last_inputs = getattr(self, "_last_inputs_dir", None)
        if last_inputs:
            p = Path(last_inputs)
            if p.exists():
                path = p
        else:
            base = getattr(self, "_last_output_dir", None)
            if base:
                # engine writes inputs under scen_dir/inputs/<ts1_short>
                p = Path(base).parent.parent / "inputs"
                if p.exists():
                    path = p
        if not path:
            path = USER_BASE / "model_input" / "ts1_files"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_output_folder(self):
        # Prefer the output folder of the last run if available
        # If a custom output base is selected, open that; else last run
        custom = getattr(self, "output_dir_edit", None)
        if custom and custom.text().strip():
            path = Path(custom.text().strip())
        else:
            base = getattr(self, "_last_output_dir", None)
            path = Path(base) if base else (USER_BASE / "model_output")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    
    def build_config(self):
        """Build configuration from UI values"""
        try:
            # Values are in m/day; kv primary, kh mirrors kv if not separate
            kv_mpd = float(self.kv_input.value())
            kh_mpd = float(self.kh_input.value()) if self.sep_kh_check.isChecked() else kv_mpd
            # derive min_cells_wide from performance mode (fixed to fast)
            perf_mode = "fast"
            perf_min_cells = {"fast": 3}.get(perf_mode, 3)
            # Infiltration side K behavior
            infil_mode = self.infiltration_mode.currentText().strip().lower()
            bed_k = float(self.bed_k_input.value())
            side_sep = bool(self.side_k_separate_check.isChecked())
            if infil_mode == "vertical":
                side_k = 0.0  # disabled in vertical-only mode
            else:  # full
                side_k = float(self.side_k_input.value()) if side_sep else bed_k
            
            # Build basin geometry config
            _bg = {
                "source": "manual",
                "length_floor": self.length_input.value(),
                "width_floor": self.width_input.value(),
                "max_depth": self.depth_input.value(),
                "side_slope_hv": self.side_slope_input.value(),
                "floor_elev": self.floor_elev_input.value(),
            }

            config = {
                "scenario_title": self.scenario_name.text().strip() or "Scenario 1",
                "model_tag": "desktop",
                # Preliminary Green–Ampt mode removed; always use detailed MF6 engine
                "analysis_mode": "detailed",
                "basin_geometry": _bg,
                "aquifer": {
                    "k_horizontal_mpd": kh_mpd,
                    "k_vertical_mpd": kv_mpd,
                    "ss": float(self.ss_input.value()),
                    "sy": self.sy_input.value(),
                    "initial_head": self.initial_head_input.value(),
                    "bottom_elev": self.bottom_elev_input.value(),
                },
                "infiltration": {
                    "mode": self.infiltration_mode.currentText(),
                    "bed_thickness_m": self.bed_thickness_input.value(),
                    "bed_k_mpd": bed_k,
                    "side_k_mpd": side_k,
                    "side_k_separate": side_sep,
                },
                "uzf": {
                    "thts": self.thts_input.value(),
                    "thtr": self.thtr_input.value(),
                    "eps": self.eps_input.value(),
                    "thti": self.thti_input.value(),
                },
                "perf": {
                    # Performance preset fixed to fast
                    "mode": perf_mode,
                    "min_cells_wide": perf_min_cells,
                },
                "post_storm_days": self.post_storm_days_input.value(),
                "post_storm_step_hours": self.post_storm_step_input.value(),
                # Boundary tuning removed; engine will use defaults
                "lightweight_outputs": self.lightweight_check.isChecked(),
                "cleanup_heavy": self.cleanup_check.isChecked(),
            }
            # Outlet overlay (require explicitly added entries; no implicit default)
            if self.outlet_enable.isChecked():
                if hasattr(self, "_outlets_cfg") and len(self._outlets_cfg) >= 1:
                    import json as _json
                    config["outlets"] = [_json.loads(_json.dumps(o)) for o in self._outlets_cfg]
                # else: overlay enabled but no outlets added — do not inject a default outlet
            # optional output folder
            if self.output_dir_edit.text().strip():
                config["output_dir"] = self.output_dir_edit.text().strip()
            # custom depth–area
            self.use_custom_da = self.use_custom_da_check.isChecked()
            if self.use_custom_da and len(self.custom_depth_area) >= 2:
                # ensure sorted and unique depths
                das = sorted({float(d): float(a) for d, a in self.custom_depth_area}.items())
                config["custom_depth_area"] = [[d, a] for d, a in das]
            
            return config
            
        except ValueError as e:
            QMessageBox.critical(self, "Configuration Error", f"Invalid input values: {str(e)}")
            return None
    
    def run_simulations(self):
        """Run simulations - matching Tkinter logic"""
        # Require license before running
        if not self._ensure_license_for_run():
            return
        if not self.ts1_files:
            QMessageBox.warning(self, "No TS1 Files", "Please add at least one TS1 file.")
            return
        
        config = self.build_config()
        if config is None:
            return
        
        # Disable controls during run
        self.run_button.setEnabled(False)
        # make global bar indeterminate while workers run
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        # start elapsed timer feedback
        self._run_start_time = datetime.now()
        # capture static GW overlay head for this run
        try:
            self._gw_overlay_head = float(self.initial_head_input.value())
        except Exception:
            pass
        if not hasattr(self, "_elapsed_timer"):
            self._elapsed_timer = QTimer(self)
            self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._elapsed_timer.start(1000)
        
        # Clear previous results
        self.results_table.setRowCount(0)
        self.results.clear()
        
        # Show log and set per-item progress busy
        self.log_text.clear()
        self.show_run_log()
        for path, (_, _, bar) in self.ts1_widgets.items():
            bar.setRange(0, 0)
            bar.setValue(0)
        
        # Hide folder buttons until we have outputs
        if hasattr(self, "btn_open_in"):
            self.btn_open_in.setVisible(False)
        if hasattr(self, "btn_open_out"):
            self.btn_open_out.setVisible(False)

    # Run simulations via thread pool; if not parallel, use 1 worker
        use_parallel = self.parallel_check.isChecked()
        max_workers = (os.cpu_count() or 2) if use_parallel else 1
        self._run_parallel(config, max_workers=max_workers)
    
    def _run_parallel(self, config, max_workers=None):
        """Run simulations using a thread pool; UI remains responsive via polling."""
        if max_workers is None:
            max_workers = os.cpu_count() or 2
        self._log_line(f"Queuing {len(self.ts1_files)} simulations with {max_workers} worker(s)…")
        
        # create per-run progress files for timestep-based progress
        # Use a user-writable base by default (Documents\BaSIM\model_output)
        from pathlib import Path as _P
        def _default_output_base():
            # If the user configured an output_dir, use that as base
            try:
                txt = self.output_dir_edit.text().strip()
                if txt:
                    return _P(txt)
            except Exception:
                pass
            # Else prefer Documents\BaSIM\model_output
            try:
                home = _P.home()
                docs = home / 'Documents'
                base = docs / 'BaSIM' / 'model_output'
                base.mkdir(parents=True, exist_ok=True)
                return base
            except Exception:
                pass
            # Fallback to project ROOT (may fail on Program Files installs)
            return USER_BASE / 'model_output'
        progress_dir = _default_output_base() / "_progress"
        try:
            progress_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # last resort: temp directory
            import tempfile as _tf
            progress_dir = _P(_tf.gettempdir()) / 'BaSIM' / 'model_output' / '_progress'
            progress_dir.mkdir(parents=True, exist_ok=True)
        import uuid, json as _json
        self._progress_files: Dict[str, Path] = {}
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for ts1_file in self.ts1_files:
                cfg = json.loads(json.dumps(config))  # deep copy via json
                pf = progress_dir / f"progress_{uuid.uuid4().hex}.json"
                cfg["progress_file"] = str(pf)
                self._progress_files[ts1_file] = pf
                futures.append((executor.submit(self._run_single_simulation, ts1_file, cfg), ts1_file))
            future_to_ts1 = {f: ts1 for (f, ts1) in futures}
            pending = set(future_to_ts1.keys())
            completed = 0
            # set determinate range now that tasks are queued
            self.progress_bar.setRange(0, len(self.ts1_files))
            while pending:
                done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                # poll progress files for per-item progress updates
                try:
                    for ts1 in self.ts1_files:
                        pf = self._progress_files.get(ts1)
                        if not pf or not pf.exists():
                            continue
                        try:
                            import json as _json
                            data = _json.loads(pf.read_text(encoding='utf-8'))
                            cur = int(max(0, data.get("current", 0)))
                            tot = int(max(1, data.get("total", 1)))
                            pct = int(min(100, max(0, round(cur * 100 / tot))))
                            item, _, bar = self.ts1_widgets.get(ts1, (None, None, None))
                            if bar is not None:
                                bar.setRange(0, 100)
                                # show percentage text while updating
                                try:
                                    bar.setTextVisible(True)
                                    bar.setFormat("%p%")
                                except Exception:
                                    pass
                                bar.setValue(pct)
                            # also reflect progress in Run Log occasionally
                            try:
                                from pathlib import Path as _P
                                name = _P(ts1).name
                                # emit a log line each 5% change
                                key = f"_last_pct_{ts1}"
                                last = getattr(self, key, -1)
                                if abs(pct - int(last)) >= 5:
                                    self._log_line(f"{name}: {pct}%")
                                    setattr(self, key, pct)
                            except Exception:
                                pass
                            # tail MF6 live stdout and errors into the log
                            try:
                                from pathlib import Path as _P
                                model_dir = data.get("model_dir")
                                if model_dir:
                                    stdout_log = _P(model_dir) / 'mf6_stdout.log'
                                    err_file = _P(model_dir) / 'last_error.txt'
                                    # append any new stdout lines
                                    if stdout_log.exists():
                                        # track last read size per ts1
                                        off_key = f"_tail_off_{ts1}"
                                        last_off = getattr(self, off_key, 0)
                                        sz = stdout_log.stat().st_size
                                        if sz > last_off:
                                            with open(stdout_log, 'r', encoding='utf-8', errors='ignore') as fp:
                                                fp.seek(last_off)
                                                chunk = fp.read()
                                            if chunk:
                                                for ln in chunk.splitlines():
                                                    # keep it compact; only interesting lines
                                                    if ln.strip():
                                                        self._log_line(ln.rstrip())
                                            setattr(self, off_key, sz)
                                    # surface any error quickly
                                    if err_file.exists():
                                        try:
                                            err_txt = err_file.read_text(encoding='utf-8', errors='ignore').strip()
                                            if err_txt:
                                                self._log_line(f"ERROR: {err_txt}")
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
                for future in done:
                    ts1_file = future_to_ts1[future]
                    completed += 1
                    try:
                        success, summary, output_dir = future.result()
                        self._update_results(ts1_file, success, summary, output_dir)
                        # Additional failure diagnostics in run log
                        if not success:
                            try:
                                err_msg = ''
                                if isinstance(summary, dict):
                                    err_msg = summary.get('error') or ''
                                self._log_line(f"[diag] Failure detail: {err_msg if err_msg else 'No error text returned'}")
                                if output_dir:
                                    self._log_line(f"[diag] Output dir: {output_dir}")
                            except Exception:
                                pass
                    except Exception as e:
                        self._update_results(ts1_file, False, {"error": str(e)}, "")
                        success = False
                    self.progress_bar.setValue(completed)
                    self.status_label.setText(f"Completed {completed}/{len(self.ts1_files)} simulations")
                    self._set_item_done(ts1_file, success)
                    self._log_line(f"{Path(ts1_file).name}: {'Success' if self.results[ts1_file]['success'] else 'Failed'}")
                QApplication.processEvents()
        self.run_button.setEnabled(True)
        if hasattr(self, "_elapsed_timer"):
            self._elapsed_timer.stop()
        self.status_bar.showMessage("All simulations completed")
        self._generate_report()
        # Set global progress label to Complete/Failed
        try:
            all_ok = all(res.get('success') for res in self.results.values()) if self.results else False
            self.progress_bar.setFormat("Complete" if all_ok else "Failed")
            self.progress_bar.setTextVisible(True)
        except Exception:
            pass
        # Show completion dialog as requested
        try:
            if all_ok:
                QMessageBox.information(self, "ALL RUNS COMPLETE", "ALL RUNS COMPLETE")
        except Exception:
            pass
        if hasattr(self, "btn_open_in"):
            self.btn_open_in.setVisible(True)
        if hasattr(self, "btn_open_out"):
            self.btn_open_out.setVisible(True)
        # update preview water stage and spill warning using max peak from results
        try:
            peak_vals = [res["summary"].get("peak_stage_with_outlet_m", res["summary"].get("peak_stage_m")) for res in self.results.values() if res.get("success") and isinstance(res.get("summary"), dict)]
            peak = max([p for p in peak_vals if p is not None], default=None)
            if peak is not None:
                crest = self._get_crest_elevation()
                spilled = any(res["summary"].get("spill_detected", False) for res in self.results.values() if res.get("success")) or (peak > crest + 1e-6)
                self._last_peak_stage = float(peak)
                self._last_spill = bool(spilled)
                # Display spill warning prominently
                freeboard = crest - float(peak)
                if spilled:
                    self.status_bar.showMessage(
                        f"\u26a0 SPILL WARNING: Peak stage {peak:.2f} m exceeds crest {crest:.2f} m by {-freeboard:.2f} m"
                    )
                    self.status_bar.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold;")
                else:
                    self.status_bar.showMessage(
                        f"All runs complete. Peak stage {peak:.2f} m  |  Freeboard {freeboard:.2f} m  |  Crest {crest:.2f} m"
                    )
                    self.status_bar.setStyleSheet("")
        except Exception:
            pass
        # Plot all results with legend and critical highlight
        try:
            if PYQTGRAPH_AVAILABLE:
                self._plot_all_results()
                self.results_tabs.setCurrentWidget(self.timeseries_tab)
                # Sync new flow tab selector and draw
                try:
                    self._populate_flow_selector()
                    self._update_flow_plot()
                except Exception:
                    pass
        except Exception:
            pass
    
    # _run_sequential no longer needed; sequential uses 1-worker pool
    
    def _run_single_simulation(self, ts1_file, config):
        """Run a single simulation using the detailed MODFLOW 6 engine."""
        global run_phase3_step32_with_config

        # Always use full MODFLOW 6 engine (preliminary Green–Ampt mode removed)
        if run_phase3_step32_with_config is None:
            try:
                from src.usg_model_builder import run_simulation as _runner
                run_phase3_step32_with_config = _runner
            except Exception as e:
                # Propagate so caller marks this run as failed and surfaces message
                raise RuntimeError(f"Failed to load model engine: {e}")

        # Global trace pre-dispatch (to detect if we die before entering engine wrapper)
        try:
            from pathlib import Path as _P0, datetime as _dt0, sys as _sys0
            _trace_file0 = _P0.home()/ 'Documents' / 'BaSIM' / 'onefile_trace.log'
            _trace_file0.parent.mkdir(parents=True, exist_ok=True)
            with _trace_file0.open('a', encoding='utf-8') as _tf0:
                _tf0.write(f"[{_dt0.datetime.utcnow().isoformat()}Z] GUI about to dispatch run_phase3_step32_with_config ts1={ts1_file} frozen={getattr(_sys0,'frozen',False)}\n")
        except Exception:
            pass

        # Pre-compute and log the expected output MODEL_DIR for diagnostics (mirrors engine logic)
        try:
            scen_title = str(config.get("scenario_title", "Scenario 1")).strip() or "Scenario 1"
            base = config.get("output_dir") or None
            from pathlib import Path as _P
            if not base:
                # Mirror default base in engine (Documents/BaSIM/model_output/phase3/step32/scenarios)
                docs = _P.home() / 'Documents' / 'BaSIM' / 'model_output' / 'phase3' / 'step32' / 'scenarios'
                base = str(docs)
            base_p = _P(base)
            # Derive short ts1 token similar to engine (fallback to stem)
            ts_short = None
            try:
                if ts1_file:
                    stem = _P(ts1_file).stem
                    import re as _re
                    m_aep = _re.search(r"(\d+)\s*(?:pct|percent)\s*AEP", stem, _re.IGNORECASE)
                    if m_aep:
                        ts_short = f"{m_aep.group(1)}pct"
                    if not ts_short:
                        ts_short = stem[:40]
                else:
                    ts_short = 'synthetic'
            except Exception:
                ts_short = 'unknown'
            model_dir_guess = base_p / scen_title / ts_short
            self._log_line(f"[diag] Planning run -> model_dir: {model_dir_guess}")
        except Exception:
            pass
        try:
            self.signals.log.emit("Starting USG Simulation Worker...")
        except Exception:
            pass

        ok, summary, outdir = run_phase3_step32_with_config(ts1_file, config)
        try:
            if not ok and summary and isinstance(summary, dict):
                err = summary.get('error') or ''
                self._log_line(f"[diag] Run failed. error={err}")
                self._log_line(f"[diag] Output dir reported: {outdir}")
        except Exception:
            pass
        return ok, summary, outdir
    
    def _update_results(self, ts1_file, success, summary, output_dir):
        """Update results table and store results"""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        
        # TS1 file name
        self.results_table.setItem(row, 0, QTableWidgetItem(Path(ts1_file).name))
        # Fallback: if reported failed but outputs indicate success, override
        try:
            if not success and output_dir:
                ss_path = Path(output_dir) / 'scenario_summary.json'
                if ss_path.exists():
                    import json as _json
                    ss = _json.loads(ss_path.read_text(encoding='utf-8'))
                    if isinstance(ss, dict) and ss.get('success') is True:
                        success = True
                        summary = ss
                if not success:
                    # Secondary fallback: check mfsim.lst for Normal termination
                    lst = Path(output_dir) / 'mfsim.lst'
                    if lst.exists():
                        tail = lst.read_text(encoding='utf-8', errors='ignore')[-4000:]
                        if 'Normal termination of simulation' in tail:
                            success = True
        except Exception:
            pass
        
        # Status
        status_item = QTableWidgetItem("Success" if success else "Failed")
        if not success:
            status_item.setBackground(QColor(255, 200, 200))
        self.results_table.setItem(row, 1, status_item)
        
        # Results
        if success and summary:
            # Try to augment with mass balance percent error from .lst
            try:
                mbe = self._extract_mass_balance_error(output_dir)
                if mbe is not None:
                    summary['mass_balance_error_pct'] = mbe
            except Exception:
                pass
            # Prefer with-outlet peak stage when present (detailed); otherwise compute for prelim
            peak = summary.get('peak_stage_with_outlet_m', summary.get('peak_stage_m', summary.get('max_stage', 0)))
            # Recompute cumulative inflow
            cum_in = summary.get('cumulative_inflow_m3', None)
            try:
                outp = Path(output_dir) if output_dir else None
                if outp and outp.exists():
                    # Detailed: use LAK allobs
                    if cum_in is None:
                        cand = []
                        cand.extend(list(outp.glob('*_lak_allobs.parquet')))
                        cand.extend(list(outp.glob('*_lak_allobs.csv')))
                        cand.extend(list(outp.glob('*_lak_allobs.csv.gz')))
                        obs = max(cand or [], key=lambda p: p.stat().st_mtime)
                        if obs and obs.exists():
                            import pandas as _pd, numpy as _np
                            try:
                                if obs.suffix.lower() == '.parquet':
                                    d = _pd.read_parquet(obs)
                                else:
                                    d = _pd.read_csv(obs)
                            except Exception:
                                d = _pd.read_csv(obs)
                                if 'time' in d.columns and 'LAK_EXT_INFLOW' in d.columns:
                                    t_days = d['time'].astype(float).values
                                    q_m3d = d['LAK_EXT_INFLOW'].astype(float).values
                                    try:
                                        from scipy.integrate import cumulative_trapezoid as _ct
                                        cum = _ct(q_m3d, t_days, initial=0.0)
                                    except Exception:
                                        dt = _np.diff(t_days)
                                        qm = 0.5 * (q_m3d[:-1] + q_m3d[1:])
                                        cum = _np.concatenate([[0.0], _np.cumsum(qm * dt)])
                                    cum_in = float(cum[-1])
            except Exception:
                pass
            # Prefer with-outlet peak storage if provided by engine
            peak_storage = summary.get('peak_storage_with_outlet_m3', summary.get('peak_storage_m3', None))
            # cum_infil no longer calculated - show N/A
            rt = summary.get('runtime_seconds', 0)
            self.results_table.setItem(row, 2, QTableWidgetItem(f"{float(peak):.2f}"))
            self.results_table.setItem(row, 3, QTableWidgetItem("--" if cum_in is None else f"{float(cum_in):.0f}"))
            self.results_table.setItem(row, 4, QTableWidgetItem("--" if peak_storage is None else f"{float(peak_storage):.0f}"))
            # Mean infiltration rate
            mean_infil = self._compute_mean_infiltration_rate(output_dir) if output_dir else None
            self.results_table.setItem(row, 5, QTableWidgetItem("--" if mean_infil is None else f"{float(mean_infil):.1f}"))
            # Spill indicator
            try:
                crest = self._get_crest_elevation()
                spill_flag = summary.get('spill_detected', False) or (float(peak) > crest + 1e-6)
            except Exception:
                spill_flag = summary.get('spill_detected', False)
            spill_item = QTableWidgetItem("YES" if spill_flag else "No")
            if spill_flag:
                spill_item.setBackground(QColor(204, 51, 51))
                spill_item.setForeground(QColor(255, 255, 255))
            self.results_table.setItem(row, 6, spill_item)
            # Outlet metrics
            pk_out = summary.get('peak_outlet_m3s', None)
            tot_out = summary.get('total_outlet_m3', None)
            self.results_table.setItem(row, 7, QTableWidgetItem("--" if pk_out is None else f"{float(pk_out):.3f}"))
            self.results_table.setItem(row, 8, QTableWidgetItem("--" if tot_out is None else f"{float(tot_out):.0f}"))
            self.results_table.setItem(row, 9, QTableWidgetItem(f"{float(rt):.1f}"))
            # Store mean infiltration in summary for report
            if mean_infil is not None:
                summary['mean_infiltration_m3d'] = mean_infil
        else:
            for c in range(2, 10):
                self.results_table.setItem(row, c, QTableWidgetItem("--"))
        
        # Output directory
        self.results_table.setItem(row, 11, QTableWidgetItem(str(output_dir)))
        # Update total basin storage label
        try:
            total_storage = self._get_total_basin_storage()
            crest = self._get_crest_elevation()
            if total_storage is not None:
                self._basin_storage_label.setText(
                    f"Total Basin Storage Available: {total_storage:,.0f} m\u00b3  |  Crest Elevation: {crest:.2f} m AHD"
                )
            else:
                self._basin_storage_label.setText(f"Crest Elevation: {crest:.2f} m AHD")
        except Exception:
            pass
        
        # Store full results
        self.results[ts1_file] = {
            "success": success,
            "summary": summary,
            "output_dir": output_dir
        }
        # remember last output dir for folder buttons
        if output_dir:
            self._last_output_dir = output_dir
            # infer inputs dir
            try:
                outp = Path(output_dir)
                cand = outp.parent.parent / "inputs"
                if cand.exists():
                    self._last_inputs_dir = str(cand)
            except Exception:
                pass

        # Cleanup heavy files if requested (.bud/.hds/.lst + basin_budget.txt)
        try:
            if success and output_dir and self.cleanup_check.isChecked():
                for ext in ("*.bud", "*.hds", "*.lst"):
                    for pth in Path(output_dir).glob(ext):
                        try:
                            pth.unlink(missing_ok=True)
                        except Exception:
                            pass
                # Remove explicit basin budget text file if present
                try:
                    bb = Path(output_dir) / 'basin_budget.txt'
                    if bb.exists():
                        bb.unlink(missing_ok=True)
                except Exception:
                    pass
                # Also remove stale error breadcrumbs and legacy CSVs if present
                for fname in (
                    'last_error.txt', 'mf6_tail.log',
                    'water_balance_timeseries.csv', 'inflow_timeseries.csv',
                ):
                    try:
                        f = Path(output_dir) / fname
                        if f.exists():
                            f.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass
        
        # Try to plot if successful
        if success and output_dir and PYQTGRAPH_AVAILABLE:
            self._plot_results(output_dir)
            # switch to time series tab on first plot
            try:
                self.results_tabs.setCurrentWidget(self.timeseries_tab)
            except Exception:
                pass
            # Update flow tab too
            try:
                self._populate_flow_selector()
                self._update_flow_plot()
            except Exception:
                pass
        # update report incrementally
        self._generate_report()
        QApplication.processEvents()

    def _extract_mass_balance_error(self, output_dir: str | Path) -> Optional[float]:
        """Parse the MODFLOW .lst file in output_dir and return the global percent discrepancy.

        Returns the last occurrence of 'PERCENT DISCREPANCY' as a float, if found.
        """
        try:
            p = Path(output_dir)
            lst_files = list(p.glob("*.lst"))
            if not lst_files:
                return None
            # Prefer model-specific listing over mfsim.lst; else newest
            prefer = [f for f in lst_files if f.name.lower() != "mfsim.lst"]
            candidates = prefer if prefer else lst_files
            lst = max(candidates, key=lambda x: x.stat().st_mtime)
            val: Optional[float] = None
            pat = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([+-]?[0-9]*\.?[0-9]+)")
            with open(lst, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    for m in pat.finditer(line):
                        try:
                            val = float(m.group(1))
                        except Exception:
                            continue
            return val
        except Exception:
            return None
    
    def _plot_results(self, output_dir):
        """Plot time series for a single output directory (compat). Uses overlay plot of all runs."""
        try:
            self._plot_all_results()
            # Populate/refresh flow tab plots (detailed inflow/storage moved there)
            if PYQTGRAPH_AVAILABLE:
                self._populate_flow_selector()
                self._update_flow_plot()
        except Exception as e:
            print(f"Error plotting results: {e}")

    def _plot_all_results(self):
        """Plot time series for all successful runs with ensemble grouping.

        Files that share the same AEP + duration are grouped into ensembles.
        For each ensemble:
        - A shaded min-max envelope shows the spread across TPs
        - The median-peak-stage member is drawn as a bold line
        - Non-median members are drawn faintly inside the envelope
        Ungrouped files are drawn as plain coloured lines.
        """
        if not PYQTGRAPH_AVAILABLE:
            return
        try:
            import pandas as pd
            import numpy as np
            from src.utils.ts1_ensemble import (
                group_ts1_files, select_median_by_peak_stage,
                ensemble_label, StormMember,
            )

            # ── 1. Collect time-series data from completed runs ──────
            series = []   # each: {label, time, stage, peak, ts1_file}
            for ts1_file, result in self.results.items():
                if not result.get('success'):
                    continue
                out_dir = result.get('output_dir')
                if not out_dir:
                    continue
                output_path = Path(out_dir)
                mode = str(result.get('summary', {}).get('analysis_mode', '')).strip().lower()
                time = stage = None
                if mode.startswith('prelim'):
                    try:
                        prelim_csv = output_path / 'prelim_timeseries.csv'
                        if prelim_csv.exists():
                            dpf = pd.read_csv(prelim_csv)
                            if 'time_hours' in dpf.columns and 'stage_m' in dpf.columns:
                                time = dpf['time_hours'].astype(float).values / 24.0
                                stage = dpf['stage_m'].astype(float).values
                    except Exception:
                        time = stage = None
                else:
                    try:
                        allow_outlet = bool(result.get('summary', {}).get('outlet_enabled', False))
                        outlet_csv = max(list(output_path.glob('*_with_outlet.csv')) or [], key=lambda x: x.stat().st_mtime) if allow_outlet else None
                    except Exception:
                        outlet_csv = None
                    if outlet_csv and outlet_csv.exists():
                        try:
                            dfo = pd.read_csv(outlet_csv)
                            if 'time_days' in dfo.columns and 'stage_with_outlet_m' in dfo.columns:
                                time = dfo['time_days'].astype(float).values
                                stage = dfo['stage_with_outlet_m'].astype(float).values
                        except Exception:
                            time = stage = None
                    if time is None or stage is None:
                        stage_files = list(output_path.glob("*_lak_stage.csv"))
                        if stage_files:
                            stage_file = max(stage_files, key=lambda p: p.stat().st_mtime)
                            try:
                                df = pd.read_csv(stage_file)
                                if len(df.columns) >= 2:
                                    time = df.iloc[:, 0].astype(float).values
                                    stage = df.iloc[:, 1].astype(float).values
                            except Exception:
                                pass
                    if time is None or stage is None:
                        try:
                            prelim_csv = output_path / 'prelim_timeseries.csv'
                            if prelim_csv.exists():
                                dpf = pd.read_csv(prelim_csv)
                                if 'time_hours' in dpf.columns and 'stage_m' in dpf.columns:
                                    time = dpf['time_hours'].astype(float).values / 24.0
                                    stage = dpf['stage_m'].astype(float).values
                        except Exception:
                            pass
                if time is None or stage is None:
                    continue
                label = result.get('summary', {}).get('ts1_short') or Path(ts1_file).stem
                peak = float(np.nanmax(stage)) if len(stage) else float('nan')
                series.append({
                    "label": label, "time": time, "stage": stage,
                    "peak": peak, "ts1_file": ts1_file,
                })

            if not series:
                return

            # ── 2. Group into ensembles ──────────────────────────────
            ts1_files = [s["ts1_file"] for s in series]
            ensembles, ungrouped_members = group_ts1_files(ts1_files)

            # Map ts1_file → series dict for quick lookup
            file_to_series = {s["ts1_file"]: s for s in series}

            # Populate peak_stage on ensemble members
            for ens in ensembles:
                for m in ens.members:
                    sd = file_to_series.get(m.filepath)
                    if sd:
                        m.peak_stage = sd["peak"]
                select_median_by_peak_stage(ens)

            # Set of ungrouped ts1 paths
            ungrouped_set = {m.filepath for m in ungrouped_members}

            # ── 3. Build plot ────────────────────────────────────────
            self.plot_widget.clear()
            plot = self.plot_widget.addPlot(title="Lake Stage Over Time (all runs)")
            try:
                legend = plot.addLegend(labelTextSize='12pt')
                if hasattr(legend, 'anchor'):
                    legend.anchor((1, 0), (1, 0), offset=(-10, 10))
            except Exception:
                pass
            plot.setLabel('left', 'Stage', units='m')
            plot.setLabel('bottom', 'Time', units='days')

            COLORS = ['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
                       '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ab']

            overall_max_peak = -1e9
            overall_max_idx = None

            # ── 3a. Plot ensembles ───────────────────────────────────
            for ei, ens in enumerate(ensembles):
                color = COLORS[ei % len(COLORS)]
                qcolor = QColor(color)

                # Gather all member time-series
                member_series = []
                for m in ens.members:
                    sd = file_to_series.get(m.filepath)
                    if sd:
                        member_series.append(sd)

                if not member_series:
                    continue

                # ─ Envelope (min-max band) ──────────────────────
                # Interpolate all to a common time axis
                t_all = np.unique(np.concatenate([ms["time"] for ms in member_series]))
                interp_stages = []
                for ms in member_series:
                    interp = np.interp(t_all, ms["time"], ms["stage"])
                    interp_stages.append(interp)
                interp_arr = np.array(interp_stages)
                env_min = np.nanmin(interp_arr, axis=0)
                env_max = np.nanmax(interp_arr, axis=0)

                # Draw shaded fill between min/max
                try:
                    fill_color = QColor(color)
                    fill_color.setAlpha(40)
                    curve_top = pg.PlotDataItem(t_all, env_max)
                    curve_bot = pg.PlotDataItem(t_all, env_min)
                    fill = pg.FillBetweenItem(curve_top, curve_bot, brush=fill_color)
                    plot.addItem(fill)
                    # thin boundary lines
                    plot.plot(t_all, env_max, pen=pg.mkPen(color, width=0.5, style=2))  # dashed
                    plot.plot(t_all, env_min, pen=pg.mkPen(color, width=0.5, style=2))
                except Exception:
                    pass

                # ─ Median bold line ─────────────────────────────
                median_m = ens.median_member
                if median_m:
                    sd = file_to_series.get(median_m.filepath)
                    if sd:
                        tp_lbl = median_m.tp or "?"
                        ens_lbl = ensemble_label(ens)
                        pen = pg.mkPen(color, width=3)
                        plot.plot(sd["time"], sd["stage"], pen=pen,
                                  name=f"{ens_lbl} median {tp_lbl}")
                        if sd["peak"] > overall_max_peak:
                            overall_max_peak = sd["peak"]
                            overall_max_idx = sd

            # ── 3b. Plot ungrouped files ─────────────────────────────
            ui = len(ensembles)
            for s in series:
                if s["ts1_file"] not in ungrouped_set:
                    continue
                ci = (ui) % len(COLORS)
                ui += 1
                pen = pg.mkPen(COLORS[ci], width=1.5)
                plot.plot(s["time"], s["stage"], pen=pen, name=s["label"])
                if s["peak"] > overall_max_peak:
                    overall_max_peak = s["peak"]
                    overall_max_idx = s

            # ── 4. Annotate overall critical peak ────────────────────
            if overall_max_idx is not None:
                try:
                    idx = int(np.nanargmax(overall_max_idx["stage"]))
                    tx = pg.TextItem(
                        text=f"Peak {overall_max_idx['stage'][idx]:.2f} m",
                        color='#e15759',
                    )
                    tx.setPos(float(overall_max_idx["time"][idx]),
                              float(overall_max_idx["stage"][idx]))
                    plot.addItem(tx)
                except Exception:
                    pass

            # ── 5. Draw crest elevation line ────────────────────────
            try:
                crest = self._get_crest_elevation()
                crest_line = pg.InfiniteLine(
                    pos=crest, angle=0,
                    pen=pg.mkPen('#ff4444', width=2.0, style=Qt.PenStyle.DashLine),
                    label=f'Crest {crest:.2f} m',
                    labelOpts={'color': '#ff4444', 'position': 0.02, 'anchors': [(0, 1), (0, 1)]},
                )
                plot.addItem(crest_line)
            except Exception:
                pass

            # ── 6. Store ensemble info for table highlighting ────────
            self._ensembles = ensembles
            self._ungrouped_members = ungrouped_members

            # Cache series for CSV export
            self._stage_plot_series = series

            try:
                self._populate_detailed_selector()
            except Exception:
                pass
            # Highlight medians in results table
            try:
                self._highlight_median_rows()
            except Exception:
                pass
        except Exception as e:
            print(f"Error plotting all results: {e}")

    def _highlight_median_rows(self):
        """Populate the Ensemble column and highlight median rows in the results table."""
        if not hasattr(self, '_ensembles'):
            return
        from src.utils.ts1_ensemble import ensemble_label

        # Build mapping: ts1_file → (ensemble_label, is_median)
        file_info: dict = {}
        for ens in self._ensembles:
            elbl = ensemble_label(ens)
            median_fp = ens.median_member.filepath if ens.median_member else None
            for m in ens.members:
                file_info[m.filepath] = (elbl, m.filepath == median_fp)
        for m in self._ungrouped_members:
            file_info[m.filepath] = ("—", False)

        # Walk table rows
        median_bg = QColor(230, 245, 230)  # light green
        median_font = self.results_table.font()
        median_font.setBold(True)

        for row in range(self.results_table.rowCount()):
            ts1_item = self.results_table.item(row, 0)
            if not ts1_item:
                continue
            # Match by looking up the stored results dict
            ts1_file = None
            for fp in self.results:
                if Path(fp).name == ts1_item.text() or ts1_item.text() in fp:
                    ts1_file = fp
                    break
            if not ts1_file:
                continue

            info = file_info.get(ts1_file)
            if not info:
                self.results_table.setItem(row, 10, QTableWidgetItem("—"))
                continue

            elbl, is_median = info
            ens_item = QTableWidgetItem(elbl)
            if is_median:
                ens_item.setText(f"⭐ {elbl}")
                for col in range(self.results_table.columnCount()):
                    cell = self.results_table.item(row, col)
                    if cell:
                        cell.setBackground(median_bg)
                        cell.setFont(median_font)
                ens_item.setBackground(median_bg)
                ens_item.setFont(median_font)
            self.results_table.setItem(row, 10, ens_item)

    def _populate_detailed_selector(self):
        """Fill the run selector with available successful runs."""
        if not PYQTGRAPH_AVAILABLE:
            return
        # Ensure the detailed plot exists once we have anything to show
        try:
            if self.detail_plot is None and any(res.get('success') for res in self.results.values()):
                self._ensure_detail_plot()
        except Exception:
            pass
        # Preserve current selection label
        current_label = self.detail_run_select.currentText() if self.detail_run_select.count() else None
        self.detail_run_select.blockSignals(True)
        self.detail_run_select.clear()
        # Build items as (label, ts1_key)
        items = []
        for ts1_file, result in self.results.items():
            if not result.get('success'):
                continue
            label = result.get('summary', {}).get('ts1_short') or Path(ts1_file).stem
            items.append((label, ts1_file))
        # Stable order by label
        items.sort(key=lambda x: x[0])
        for label, key in items:
            self.detail_run_select.addItem(label, userData=key)
        # Try to restore selection; otherwise select last
        if current_label and any(self.detail_run_select.itemText(i) == current_label for i in range(self.detail_run_select.count())):
            idx = next(i for i in range(self.detail_run_select.count()) if self.detail_run_select.itemText(i) == current_label)
            self.detail_run_select.setCurrentIndex(idx)
        elif self.detail_run_select.count():
            self.detail_run_select.setCurrentIndex(self.detail_run_select.count() - 1)
        self.detail_run_select.blockSignals(False)
        # Keep the new flow tab selector in sync
        try:
            self._populate_flow_selector()
        except Exception:
            pass

    def _sync_detail_views(self):
        """Keep right view box aligned with left on resize."""
        if not PYQTGRAPH_AVAILABLE or self.detail_plot is None or self._detail_right_view is None:
            return
        try:
            gv = self.detail_plot.getViewBox()
            self._detail_right_view.setGeometry(gv.sceneBoundingRect())
            # Manually map the right view to the left view's range
            self._detail_right_view.linkedViewChanged(gv, self._detail_right_view.XAxis)
        except Exception:
            pass

    def _update_detailed_plot(self):
        """Render the detailed per-run plot with inflow and cumulative metrics."""
        if not PYQTGRAPH_AVAILABLE:
            return
        # Ensure the detailed plot exists
        try:
            if self.detail_plot is None:
                self._ensure_detail_plot()
        except Exception:
            return
        # Clear previous items in both views
        try:
            if self.detail_plot is not None:
                left_vb = self.detail_plot.getViewBox()
                for it in list(getattr(left_vb, 'addedItems', [])):
                    try:
                        left_vb.removeItem(it)
                    except Exception:
                        pass
            if self._detail_right_view is not None:
                for it in list(getattr(self._detail_right_view, 'addedItems', [])):
                    try:
                        self._detail_right_view.removeItem(it)
                    except Exception:
                        pass
            # Clear legend
            try:
                if self._detail_legend is not None:
                    self._detail_legend.clear()
            except Exception:
                pass
        except Exception:
            pass

        if self.detail_run_select.count() == 0:
            return
        ts1_key = self.detail_run_select.currentData()
        if not ts1_key:
            return
        result = self.results.get(ts1_key, {})
        out_dir = result.get('output_dir')
        if not out_dir:
            return

        # Load series
        series = self._load_wb_series(ts1_key, out_dir, self.detail_time_unit_select)
        if series is None:
            return
        t, inflow, gwf_in, cum_in, storage, cum_infil = series

        # Plot curves
        colors = {
            'inflow': '#1f77b4',
            'cum_in': '#ff7f0e',
            'storage': '#2ca02c',
        }
        # Left axis: inflow hydrograph (+ optional GW inflow)
        if inflow is not None:
            inflow_curve = self.detail_plot.plot(t, inflow, pen=pg.mkPen(colors['inflow'], width=2.0), name='Inflow (m3/s)')
        else:
            inflow_curve = None
        gwf_curve = None
        try:
            if gwf_in is not None and getattr(self, 'chk_show_gwf_in', None) is not None and self.chk_show_gwf_in.isChecked():
                gwf_curve = self.detail_plot.plot(t, gwf_in, pen=pg.mkPen('#9467bd', width=2.0, style=Qt.PenStyle.DashLine), name='GW inflow (m3/s)')
        except Exception:
            pass
        # Right axis: cumulative/volume series (respect toggles)
        right_series = []
        try:
            if self.chk_show_cum_in.isChecked():
                right_series.append((cum_in, 'Cumulative inflow (m3)', colors['cum_in']))
            if self.chk_show_storage.isChecked():
                right_series.append((storage, 'Storage volume (m3)', colors['storage']))
            # cumulative infiltration removed
        except Exception:
            right_series = [
                (cum_in, 'Cumulative inflow (m³)', colors['cum_in']),
                (storage, 'Storage volume (m³)', colors['storage']),
            ]

        for y, nm, col in right_series:
            curve = pg.PlotDataItem(t, y, pen=pg.mkPen(col, width=2.0))
            if self._detail_right_view is not None:
                self._detail_right_view.addItem(curve)
            # Add to legend
            if self._detail_legend is not None:
                self._detail_legend.addItem(curve, nm)
        # Also add inflow to legend explicitly (it self-registers only in some versions)
        try:
            if self._detail_legend is not None:
                self._detail_legend.addItem(inflow_curve, 'Inflow (m3/s)')
                if gwf_curve is not None:
                    self._detail_legend.addItem(gwf_curve, 'GW inflow (m3/s)')
        except Exception:
            pass

        # Nice ranges and grid
        try:
            if self.detail_plot is not None:
                self.detail_plot.showGrid(x=True, y=True, alpha=0.2)
            # Match x-range for both views
            self._sync_detail_views()
        except Exception:
            pass

    def _load_wb_series(self, ts1_key: str, out_dir: str | Path, unit_combo: Optional[QComboBox]):
        """Load water-balance data and return (t, inflow, gwf_in, cum_in, storage, cum_infil).

    Supports both Detailed (MODFLOW 6) and Preliminary (Richards 1D) runs.
        """
        try:
            import pandas as pd, numpy as np
            output_path = Path(out_dir)
            output_path = output_path.resolve()
            # Determine source file to load (prelim preferred)
            data_file = None
            source = 'detailed'
            prelim_csv = output_path / 'prelim_timeseries.csv'
            if prelim_csv.exists():
                data_file = prelim_csv
                source = 'prelim'
            else:
                obs_files = list(output_path.glob("*_lak_allobs.parquet")) or list(output_path.glob("*_lak_allobs.csv")) or list(output_path.glob("*_lak_allobs.csv.gz"))
                if obs_files:
                    data_file = max(obs_files, key=lambda p: p.stat().st_mtime)
                    source = 'detailed'
            if data_file is None or not data_file.exists():
                return None
            # Cache key includes output directory and the chosen data file path
            cache_key = f"{ts1_key}::{str(output_path)}::{data_file.name}"
            mtime_key = cache_key + "__mtime"
            if not hasattr(self, '_wb_cache'):
                self._wb_cache = {}
            use_cache = False
            if cache_key in self._wb_cache and mtime_key in self._wb_cache:
                try:
                    cur_mtime = data_file.stat().st_mtime
                    if abs(float(self._wb_cache.get(mtime_key, 0.0)) - float(cur_mtime)) < 1e-6:
                        use_cache = True
                except Exception:
                    use_cache = False
            if use_cache:
                df = self._wb_cache[cache_key]
                source = self._wb_cache.get(cache_key + "__src", source)
            else:
                # Load fresh
                try:
                    if data_file.suffix.lower() == '.parquet':
                        df = pd.read_parquet(data_file)
                    else:
                        df = pd.read_csv(data_file)
                except Exception:
                    df = pd.read_csv(data_file)
                # Update cache
                try:
                    self._wb_cache[cache_key] = df
                    self._wb_cache[cache_key + "__src"] = source
                    self._wb_cache[mtime_key] = data_file.stat().st_mtime
                except Exception:
                    pass

            # Units selector
            try:
                unit = unit_combo.currentData() if unit_combo is not None else None
            except Exception:
                unit = None

            if source == 'prelim':
                # Expect time_hours, inflow_m3s, stage_m
                if not all(col in df.columns for col in ('time_hours', 'inflow_m3s', 'stage_m')):
                    return None
                t_hours = df['time_hours'].astype(float).values
                inflow = df['inflow_m3s'].astype(float).values
                # Prefer precomputed cumulative integrals when present
                if 'cum_in_m3' in df.columns:
                    try:
                        cum_in = df['cum_in_m3'].astype(float).values
                    except Exception:
                        cum_in = None
                else:
                    cum_in = None
                if cum_in is None:
                    try:
                        from scipy.integrate import cumulative_trapezoid
                        cum_in = cumulative_trapezoid(inflow, t_hours * 3600.0, initial=0.0)
                    except Exception:
                        dt = np.diff(t_hours) * 3600.0
                        qm = 0.5 * (inflow[:-1] + inflow[1:])
                        cum_in = np.concatenate([[0.0], np.cumsum(qm * dt)])
                # Storage from stage using depth–area mapping (ensures consistency with stage–storage curve)
                storage = None
                try:
                    # Get absolute stage or derive from depth + floor
                    if 'stage_m' in df.columns:
                        stg = df['stage_m'].astype(float).values
                    elif 'depth_m' in df.columns:
                        # Prefer meta floor; fallback to UI
                        floor = None
                        try:
                            import json as _json
                            meta = None
                            mp = output_path / 'model_meta.json'
                            if mp.exists():
                                meta = _json.loads(mp.read_text(encoding='utf-8'))
                            if not meta:
                                sp = output_path / 'scenario_summary.json'
                                if sp.exists():
                                    meta = _json.loads(sp.read_text(encoding='utf-8'))
                            if isinstance(meta, dict):
                                floor = meta.get('floor_elev_mAHD', meta.get('floor_elev', floor))
                        except Exception:
                            pass
                        if floor is None:
                            floor = float(self.floor_elev_input.value())
                        stg = float(floor) + df['depth_m'].astype(float).values
                    else:
                        stg = None
                    if stg is not None:
                        # Load geometry (meta preferred)
                        floor = None; Lf = None; Wf = None; m = None; Dmax = None
                        try:
                            import json as _json
                            meta = None
                            mp = output_path / 'model_meta.json'
                            if mp.exists():
                                meta = _json.loads(mp.read_text(encoding='utf-8'))
                            if not meta:
                                sp = output_path / 'scenario_summary.json'
                                if sp.exists():
                                    meta = _json.loads(sp.read_text(encoding='utf-8'))
                            if isinstance(meta, dict):
                                floor = meta.get('floor_elev_mAHD', meta.get('floor_elev', floor))
                                Lf = meta.get('length_floor_m', Lf)
                                Wf = meta.get('width_floor_m', Wf)
                                m = meta.get('side_slope_hv', m)
                                Dmax = meta.get('max_depth_m', Dmax)
                        except Exception:
                            pass
                        if floor is None:
                            floor = float(self.floor_elev_input.value())
                        if Lf is None:
                            Lf = float(self.length_input.value())
                        if Wf is None:
                            Wf = float(self.width_input.value())
                        if m is None:
                            m = float(self.side_slope_input.value())
                        if Dmax is None:
                            Dmax = float(self.depth_input.value())
                        d = np.maximum(0.0, np.minimum(np.asarray(stg, float) - float(floor), max(0.0, float(Dmax))))
                        # Custom depth–area table takes precedence
                        if getattr(self, 'use_custom_da', False) and len(getattr(self, 'custom_depth_area', []) or []) >= 2:
                            rows = sorted({float(dd): float(aa) for dd, aa in self.custom_depth_area}.items())
                            cda_d = np.array([r[0] for r in rows], float)
                            cda_a = np.array([r[1] for r in rows], float)
                            # Precompute volume along the curve
                            try:
                                from scipy.integrate import cumulative_trapezoid as _cumtrapz
                                vols = _cumtrapz(cda_a, cda_d, initial=0.0)
                            except Exception:
                                dd = np.diff(cda_d)
                                am = 0.5 * (cda_a[:-1] + cda_a[1:])
                                vols = np.concatenate([[0.0], np.cumsum(am * dd)])
                            from numpy import interp as _interp
                            storage = _interp(d, cda_d, vols, left=0.0, right=float(vols[-1]))
                        else:
                            # Trapezoid analytic volume
                            A0 = max(0.0, float(Lf) * float(Wf))
                            storage = A0 * d + float(m) * (float(Lf) + float(Wf)) * (d ** 2) + (4.0 / 3.0) * (float(m) ** 2) * (d ** 3)
                except Exception:
                    storage = None
                # Fallbacks only if stage-based mapping failed
                if storage is None:
                    # Use cumulative balances if present
                    try:
                        if cum_in is not None and ('cum_infil_m3' in df.columns or 'cum_spill_m3' in df.columns):
                            cum_inf = df['cum_infil_m3'].astype(float).values if 'cum_infil_m3' in df.columns else 0.0
                            cum_spill = df['cum_spill_m3'].astype(float).values if 'cum_spill_m3' in df.columns else 0.0
                            storage = np.asarray(cum_in, float) - np.asarray(cum_inf, float) - np.asarray(cum_spill, float)
                            storage = np.maximum(0.0, storage)
                    except Exception:
                        storage = None
                if storage is None:
                    try:
                        # Prefer geometry from output metadata (so UI edits after run don't skew storage)
                        floor = None
                        Lf = None
                        Wf = None
                        m = None
                        Dmax = None
                        try:
                            import json as _json
                            meta = None
                            # Check common meta files written by engines
                            meta_path = output_path / 'model_meta.json'
                            if meta_path.exists():
                                meta = _json.loads(meta_path.read_text(encoding='utf-8'))
                            if not meta:
                                ss_path = output_path / 'scenario_summary.json'
                                if ss_path.exists():
                                    meta = _json.loads(ss_path.read_text(encoding='utf-8'))
                            if isinstance(meta, dict):
                                floor = meta.get('floor_elev_mAHD', meta.get('floor_elev', floor))
                                Lf = meta.get('length_floor_m', Lf)
                                Wf = meta.get('width_floor_m', Wf)
                                m = meta.get('side_slope_hv', m)
                                Dmax = meta.get('max_depth_m', Dmax)
                        except Exception:
                            pass
                        # Fallback to current UI values if still missing
                        if floor is None:
                            floor = float(self.floor_elev_input.value())
                        if Lf is None:
                            Lf = float(self.length_input.value())
                        if Wf is None:
                            Wf = float(self.width_input.value())
                        if m is None:
                            m = float(self.side_slope_input.value())
                        if Dmax is None:
                            Dmax = float(self.depth_input.value())
                        # If floor remains inconsistent, derive from series minimum
                        try:
                            floor = float(floor)
                        except Exception:
                            floor = None
                        stg = df['stage_m'].astype(float).values
                        if floor is None:
                            floor = float(np.nanmin(stg)) if len(stg) else 0.0
                        # Compute storage using custom depth–area if provided; else trapezoid analytic volume
                        d = np.maximum(0.0, stg - float(floor))
                        d = np.minimum(d, max(0.0, float(Dmax)))
                        if getattr(self, 'use_custom_da', False) and len(getattr(self, 'custom_depth_area', []) or []) >= 2:
                            import numpy as _np
                            rows = sorted({float(dd): float(aa) for dd, aa in self.custom_depth_area}.items())
                            cda_d = _np.array([r[0] for r in rows], float)
                            cda_a = _np.array([r[1] for r in rows], float)
                            # Precompute volume along curve
                            try:
                                from scipy.integrate import cumulative_trapezoid as _cumtrapz
                                vols = _cumtrapz(cda_a, cda_d, initial=0.0)
                            except Exception:
                                dd = _np.diff(cda_d)
                                am = 0.5 * (cda_a[:-1] + cda_a[1:])
                                vols = _np.concatenate([[0.0], _np.cumsum(am * dd)])
                            from numpy import interp as _interp
                            storage = _interp(d, cda_d, vols, left=0.0, right=float(vols[-1]))
                        else:
                            A0 = max(0.0, float(Lf) * float(Wf))
                            storage = A0 * d + float(m) * (float(Lf) + float(Wf)) * (d ** 2) + (4.0 / 3.0) * (float(m) ** 2) * (d ** 3)
                    except Exception:
                        storage = None
                # Time base per selection
                t = t_hours if unit == 'hours' else (t_hours / 24.0)
                gwf_in = None
                # Prefer precomputed cum_infiltration when present
                cum_infil = None
                if 'cum_infil_m3' in df.columns:
                    try:
                        cum_infil = df['cum_infil_m3'].astype(float).values
                    except Exception:
                        cum_infil = None
                return (t, inflow, gwf_in, cum_in, storage, cum_infil)
            else:
                # Detailed (MODFLOW 6 LAK allobs)
                if not all(col in df.columns for col in ('time', 'LAK_EXT_INFLOW', 'LAK_STAGE')):
                    return None
                t_days = df['time'].astype(float).values
                stage_m = df['LAK_STAGE'].astype(float).values
                inflow_m3d = df['LAK_EXT_INFLOW'].astype(float).values
                inflow = inflow_m3d / 86400.0  # m3/s for plotting
                # Cum inflow in m3 over days
                try:
                    from scipy.integrate import cumulative_trapezoid
                    cum_in = cumulative_trapezoid(inflow_m3d, t_days, initial=0.0)
                except Exception:
                    dt = np.diff(t_days)
                    qm = 0.5 * (inflow_m3d[:-1] + inflow_m3d[1:])
                    cum_in = np.concatenate([[0.0], np.cumsum(qm * dt)])
                # Storage: prefer direct LAK allobs fields, else LAKTAB, else geometry fallback
                storage = None
                try:
                    if 'LAK_VOLUME' in df.columns:
                        storage = df['LAK_VOLUME'].astype(float).values
                    elif 'LAK_STORAGE' in df.columns:
                        storage = df['LAK_STORAGE'].astype(float).values
                except Exception:
                    storage = None
                try:
                    laktabs = list(output_path.glob('*.laktab'))
                    if storage is None and laktabs:
                        stg_tab, vol_tab = [], []
                        in_table = False
                        with open(laktabs[0], 'r', encoding='utf-8', errors='ignore') as tf:
                            for line in tf:
                                s = line.strip()
                                if not s or s.startswith('#'):
                                    continue
                                u = s.upper()
                                if u.startswith('BEGIN TABLE'):
                                    in_table = True; continue
                                if u.startswith('END TABLE'):
                                    break
                                if in_table:
                                    parts = s.split()
                                    if len(parts) >= 2:
                                        stg = float(parts[0]); vol = float(parts[1])
                                        stg_tab.append(stg); vol_tab.append(max(0.0, vol))
                        if storage is None and len(stg_tab) >= 2:
                            from numpy import interp
                            storage = interp(stage_m, np.array(stg_tab, float), np.array(vol_tab, float), left=0.0, right=float(vol_tab[-1]))
                except Exception:
                    pass
                if storage is None:
                    try:
                        floor = None
                        Lf = float(self.length_input.value())
                        Wf = float(self.width_input.value())
                        m = float(self.side_slope_input.value())
                        Dmax = float(self.depth_input.value())
                        meta = None
                        meta_path = output_path / 'model_meta.json'
                        if meta_path.exists():
                            import json as _json
                            meta = _json.loads(meta_path.read_text(encoding='utf-8'))
                        if meta:
                            floor = float(meta.get('floor_elev_mAHD', floor))
                            Lf = float(meta.get('length_floor_m', Lf))
                            Wf = float(meta.get('width_floor_m', Wf))
                            m = float(meta.get('side_slope_hv', m))
                            Dmax = float(meta.get('max_depth_m', Dmax))
                        if floor is None:
                            floor = float(np.nanmin(stage_m))
                        d = np.maximum(0.0, stage_m - floor)
                        d = np.minimum(d, max(0.0, Dmax))
                        A0 = max(0.0, Lf * Wf)
                        storage = A0 * d + m * (Lf + Wf) * (d ** 2) + (4.0 / 3.0) * (m ** 2) * (d ** 3)
                    except Exception:
                        storage = None
                # Time axis selection
                t = t_days * 24.0 if unit == 'hours' else t_days
                gwf_in = None
                cum_infil = None
                return (t, inflow, gwf_in, cum_in, storage, cum_infil)

        except Exception as e:
            print(f"Error loading MODFLOW water balance data: {e}")
            return None

    # ---- Large Inflow & Storage tab ----
    def _populate_flow_selector(self):
        if not PYQTGRAPH_AVAILABLE:
            return
        # Ensure plot exists first
        if getattr(self, 'flow_plot', None) is None and any(res.get('success') for res in self.results.values()):
            self._ensure_flow_plot()
        cur = self.flow_run_select.currentText() if self.flow_run_select.count() else None
        self.flow_run_select.blockSignals(True)
        self.flow_run_select.clear()
        items = []
        for ts1_file, result in self.results.items():
            if not result.get('success'):
                continue
            label = result.get('summary', {}).get('ts1_short') or Path(ts1_file).stem
            items.append((label, ts1_file))
        items.sort(key=lambda x: x[0])
        for label, key in items:
            self.flow_run_select.addItem(label, userData=key)
        if cur and any(self.flow_run_select.itemText(i) == cur for i in range(self.flow_run_select.count())):
            idx = next(i for i in range(self.flow_run_select.count()) if self.flow_run_select.itemText(i) == cur)
            self.flow_run_select.setCurrentIndex(idx)
        elif self.flow_run_select.count():
            self.flow_run_select.setCurrentIndex(self.flow_run_select.count() - 1)
        self.flow_run_select.blockSignals(False)

    def _update_flow_plot(self):
        if not PYQTGRAPH_AVAILABLE or getattr(self, 'flow_plot', None) is None:
            return
        if self.flow_run_select.count() == 0:
            return
        # Update title with selected run
        try:
            run_label = self.flow_run_select.currentText()
            if run_label:
                self.flow_plot.setTitle(f"Inflow vs Storage vs Outflow ({run_label})")
        except Exception:
            pass
        ts1_key = self.flow_run_select.currentData()
        if not ts1_key:
            return
        result = self.results.get(ts1_key, {})
        out_dir = result.get('output_dir')
        if not out_dir:
            return
        series = self._load_wb_series(ts1_key, out_dir, self.flow_time_unit_select)
        if series is None:
            return
        t, inflow, gwf_in, cum_in, storage, cum_infil = series
        # Try to load outlet-adjusted series only if this run actually enabled outlets
        outlet_t = outlet_q = None
        storage_out_t = storage_out = None
        try:
            if bool(result.get('summary', {}).get('outlet_enabled', False)):
                import pandas as _pd
                p = Path(out_dir)
                f = max(list(p.glob('*_with_outlet.csv')) or [], key=lambda x: x.stat().st_mtime)
                if f and f.exists():
                    d = _pd.read_csv(f)
                    if 'time_days' in d.columns:
                        # match unit selection
                        tt = d['time_days'].astype(float).values
                        if 'outlet_discharge_m3s' in d.columns:
                            if self.flow_time_unit_select.currentData() == 'hours':
                                outlet_t = tt * 24.0
                            else:
                                outlet_t = tt
                            outlet_q = d['outlet_discharge_m3s'].astype(float).values
                        # Prefer storage_with_outlet for right axis storage
                        if 'storage_with_outlet_m3' in d.columns:
                            storage_out_t = tt * (24.0 if (self.flow_time_unit_select.currentData()=='hours') else 1.0)
                            storage_out = d['storage_with_outlet_m3'].astype(float).values
        except Exception:
            outlet_t = outlet_q = None
            storage_out_t = storage_out = None

        # Clear existing items and legend
        try:
            lvb = self.flow_plot.getViewBox()
            for it in list(getattr(lvb, 'addedItems', [])):
                try:
                    lvb.removeItem(it)
                except Exception:
                    pass
            if self._flow_right_view is not None:
                # Remove all child items from right view box
                try:
                    for it in list(self._flow_right_view.addedItems) if hasattr(self._flow_right_view, 'addedItems') else []:
                        try:
                            self._flow_right_view.removeItem(it)
                        except Exception:
                            pass
                except Exception:
                    pass
            if self._flow_legend is not None:
                self._flow_legend.clear()
        except Exception:
            pass

        # Update bottom label
        try:
            unit = self.flow_time_unit_select.currentData() or 'days'
            self.flow_plot.setLabel('bottom', 'Time', units=('hours' if unit=='hours' else 'days'))
        except Exception:
            pass

        # Plot left axis: inflow + optional GW inflow + optional outlet
        if inflow is not None:
            inflow_curve = self.flow_plot.plot(t, inflow, pen=pg.mkPen('#1f77b4', width=3.0), name='Inflow (m3/s)')
        else:
            inflow_curve = None
        gwf_curve = None
        if gwf_in is not None and self.flow_chk_gwf_in.isChecked():
            try:
                gwf_curve = self.flow_plot.plot(t, gwf_in, pen=pg.mkPen('#9467bd', width=3.0, style=Qt.PenStyle.DashLine), name='GW inflow (m3/s)')
            except Exception:
                pass
        outlet_curve = None
        try:
            if outlet_t is not None and outlet_q is not None and self.flow_chk_outlet.isChecked():
                outlet_curve = self.flow_plot.plot(outlet_t, outlet_q, pen=pg.mkPen('#e15759', width=2.5), name='Outlet (m3/s)')
        except Exception:
            outlet_curve = None

        # Right axis: cumulative inflow and storage (prefer outlet-adjusted storage if available)
        cum_in_curve = storage_curve = None
        try:
            if self._flow_right_view is not None:
                if cum_in is not None and self.flow_chk_cum_in.isChecked():
                    cum_in_curve = pg.PlotDataItem(t, cum_in, pen=pg.mkPen('#2ca02c', width=2.0))
                    self._flow_right_view.addItem(cum_in_curve)
                if self.flow_chk_storage.isChecked():
                    # If outlet-adjusted storage available, interpolate onto current time base
                    if storage_out is not None and storage_out_t is not None:
                        try:
                            import numpy as _np
                            y = _np.interp(_np.asarray(t, float), _np.asarray(storage_out_t, float), _np.asarray(storage_out, float))
                            storage_curve = pg.PlotDataItem(t, y, pen=pg.mkPen('#ff7f0e', width=2.0))
                            self._flow_right_view.addItem(storage_curve)
                        except Exception:
                            storage_curve = None
                    elif storage is not None:
                        storage_curve = pg.PlotDataItem(t, storage, pen=pg.mkPen('#ff7f0e', width=2.0))
                        self._flow_right_view.addItem(storage_curve)
        except Exception:
            pass

        try:
            if inflow_curve is not None:
                self._flow_legend.addItem(inflow_curve, 'Inflow (m3/s)')
            if gwf_curve is not None:
                self._flow_legend.addItem(gwf_curve, 'GW inflow (m3/s)')
            if outlet_curve is not None:
                self._flow_legend.addItem(outlet_curve, 'Outlet (m3/s)')
            if cum_in_curve is not None:
                self._flow_legend.addItem(cum_in_curve, 'Cumulative inflow (m3)')
            if storage_curve is not None:
                self._flow_legend.addItem(storage_curve, 'Storage (m3)')
        except Exception:
            pass
        try:
            self.flow_plot.showGrid(x=True, y=True, alpha=0.2)
            self._sync_flow_views()
        except Exception:
            pass

        # Simple diagnostic: show residual after inflow stops
        try:
            import numpy as _np
            diag_parts = []
            # Residual after inflow stops
            if inflow is not None:
                idx = _np.where(_np.asarray(inflow) > (_np.nanmax(inflow) * 1e-3 + 1e-6))[0]
                if len(idx):
                    last = int(idx[-1])
                    if storage is not None and last+1 < len(storage):
                        dt = (t[last+1] - t[last]) * (3600.0 if (self.flow_time_unit_select.currentData()=='hours') else 86400.0)
                        dSdt = (storage[last+1] - storage[last]) / max(dt, 1e-9)
                        gw_in_val = float(gwf_in[last]) if gwf_in is not None else 0.0
                        diag_parts.append(f"After inflow ends: dS/dt ≈ {dSdt:.4f} m3/s, GW inflow ≈ {gw_in_val:.4f} m3/s.")
            # Correlation between inflow and storage shapes
            try:
                if storage is not None and inflow is not None and len(storage) == len(inflow) and len(inflow) > 8:
                    s = _np.asarray(storage, float)
                    q = _np.asarray(inflow, float)
                    def _zn(x):
                        m = _np.nanmean(x); sd = _np.nanstd(x)
                        return (x - m) / (sd if sd > 0 else 1.0)
                    r = float(_np.corrcoef(_zn(q), _zn(s))[0, 1])
                    if r > 0.92:
                        diag_parts.insert(0, "Note: Storage is highly correlated with inflow; ensure it comes from solver or Qin−infil−spill integration.")
            except Exception:
                pass
            self.flow_diag_label.setText("  ".join(diag_parts))
        except Exception:
            self.flow_diag_label.setText("")

    def _ensure_flow_plot(self):
        if not PYQTGRAPH_AVAILABLE or getattr(self, 'flow_plot', None) is not None:
            return
        self.flow_plot = pg.PlotWidget()
        self.flow_plot.setTitle("Inflow vs Storage vs Outflow (selected run)")
        self.flow_plot.setLabel('bottom', 'Time', units='days')
        # Use plain ASCII units and disable SI auto-prefix to prevent 'mm3/s'
        self.flow_plot.setLabel('left', 'Inflow', units='m3/s')
        # Right axis
        self._flow_right_axis = pg.AxisItem('right')
        self.flow_plot.addItem(self._flow_right_axis)
        self.flow_plot.showAxis('right')
        self.flow_plot.getAxis('right').setLabel(text='Cumulative / Storage', units='m3')
        self._flow_right_view = pg.ViewBox()
        self._flow_right_view.setXLink(self.flow_plot)
        self.flow_plot.scene().addItem(self._flow_right_view)
        self.flow_plot.getAxis('right').linkToView(self._flow_right_view)
        self.flow_plot.getViewBox().sigResized.connect(self._sync_flow_views)
        self._flow_legend = pg.LegendItem(offset=(10, 10), labelTextSize='12pt')
        self._flow_legend.setParentItem(self.flow_plot.getPlotItem().graphicsItem())
        # Anchor flow legend to top-right to reduce clashes with curves
        try:
            if hasattr(self._flow_legend, 'anchor'):
                self._flow_legend.anchor((1, 0), (1, 0), offset=(-10, 10))
            else:
                # Fallback: position near top-right
                gi = self.flow_plot.getPlotItem().graphicsItem()
                br = gi.boundingRect()
                self._flow_legend.setPos(br.right() - 150, br.top() + 10)
        except Exception:
            pass
        # Disable SI auto prefix on both left and right axes
        try:
            self.flow_plot.getPlotItem().getAxis('left').enableAutoSIPrefix(False)
            self.flow_plot.getAxis('right').enableAutoSIPrefix(False)
        except Exception:
            pass
        if self._flow_container.layout() is not None:
            self._flow_container.layout().addWidget(self.flow_plot)

    def _sync_flow_views(self):
        if not PYQTGRAPH_AVAILABLE or self.flow_plot is None or self._flow_right_view is None:
            return
        try:
            gv = self.flow_plot.getViewBox()
            self._flow_right_view.setGeometry(gv.sceneBoundingRect())
            self._flow_right_view.linkedViewChanged(gv, self._flow_right_view.XAxis)
        except Exception:
            pass

    def _ensure_detail_plot(self):
        """Create the detailed PlotWidget and its right-side view/legend lazily."""
        if not PYQTGRAPH_AVAILABLE:
            return
        if self.detail_plot is not None:
            return
        # Build a minimal plot; detailed inflow/storage moved to Flow tab
        self.detail_plot = pg.PlotWidget()
        self.detail_plot.setTitle("Lake stage (use 'Inflow - Storage - Outflow' tab for inflow/storage details)")
        self.detail_plot.setLabel('bottom', 'Time', units='days')
        self.detail_plot.setLabel('left', 'Stage', units='m')
        try:
            self.detail_plot.getPlotItem().getAxis('left').enableAutoSIPrefix(False)
        except Exception:
            pass
        cont = getattr(self, '_detail_container', None)
        if cont is not None and cont.layout() is not None:
            cont.layout().addWidget(self.detail_plot)
    
    def _is_dem_mode(self):
        """DEM mode is disabled."""
        return False

    def _get_crest_elevation(self) -> float:
        """Return the crest elevation (m AHD) for the current basin source mode."""
        return float(self.floor_elev_input.value() + self.depth_input.value())

    def _get_total_basin_storage(self) -> float | None:
        """Compute the maximum basin storage volume (m³) at crest level.

        Uses the custom depth–area table if enabled; otherwise analytic trapezoidal formula.
        """
        try:
            import numpy as _np

            # Manual mode
            Lf = float(self.length_input.value())
            Wf = float(self.width_input.value())
            Dmax = float(self.depth_input.value())
            m = float(self.side_slope_input.value())

            if getattr(self, 'use_custom_da', False) and len(getattr(self, 'custom_depth_area', []) or []) >= 2:
                rows = sorted({float(d): float(a) for d, a in self.custom_depth_area}.items())
                cda_d = _np.array([r[0] for r in rows], float)
                cda_a = _np.array([r[1] for r in rows], float)
                try:
                    from scipy.integrate import cumulative_trapezoid as _cumtrapz
                    vols = _cumtrapz(cda_a, cda_d, initial=0.0)
                except Exception:
                    dd = _np.diff(cda_d)
                    am = 0.5 * (cda_a[:-1] + cda_a[1:])
                    vols = _np.concatenate([[0.0], _np.cumsum(am * dd)])
                return float(vols[-1])

            # Analytic trapezoidal volume at depth = Dmax
            d = Dmax
            vol = Lf * Wf * d + m * (Lf + Wf) * (d ** 2) + (4.0 / 3.0) * (m ** 2) * (d ** 3)
            return float(vol)
        except Exception:
            return None

    def _compute_mean_infiltration_rate(self, out_dir) -> float | None:
        """Compute the time-averaged infiltration rate (m\u00b3/day) from LAK allobs data.

        Uses LAK_GW (sum of lake-groundwater exchange) or falls back to the
        total conductance * head difference approach.  Returns None on failure.
        """
        try:
            import pandas as pd, numpy as np
            output_path = Path(out_dir)
            obs_files = (list(output_path.glob('*_lak_allobs.parquet'))
                         or list(output_path.glob('*_lak_allobs.csv'))
                         or list(output_path.glob('*_lak_allobs.csv.gz')))
            if not obs_files:
                return None
            f = max(obs_files, key=lambda p: p.stat().st_mtime)
            if f.suffix.lower() == '.parquet':
                df = pd.read_parquet(f)
            else:
                df = pd.read_csv(f)

            if 'time' not in df.columns:
                return None

            t = df['time'].astype(float).values  # days

            # Prefer LAK_GW column (net lake\u2192GW exchange in m\u00b3/day, negative = out of lake)
            # Some MF6 builds write LAK_GW; some sum across connections.
            # If LAK_GW is absent, sum CONDUCTANCE_C* \u00d7 (stage - aquifer_head) per step
            # which requires head info we may not have.  Simpler fallback:
            #   infiltration \u2248 inflow - \u0394storage  integrated over the event.
            if 'LAK_GW' in df.columns:
                q_gw = df['LAK_GW'].astype(float).values  # m\u00b3/day
                # Positive = INTO lake from GW, negative = FROM lake to GW (infiltration)
                infil = -q_gw  # infiltration is water leaving the lake
            elif 'LAK_EXT_INFLOW' in df.columns and 'LAK_STORAGE' in df.columns:
                inflow = df['LAK_EXT_INFLOW'].astype(float).values  # m\u00b3/day
                storage = df['LAK_STORAGE'].astype(float).values  # m\u00b3/day rate of change
                infil = inflow - storage  # residual \u2248 infiltration (simplified)
            else:
                return None

            # Time-weighted mean (only during positive infiltration)
            dt = np.diff(t)
            if len(dt) == 0:
                return None
            # Use midpoint values
            infil_mid = 0.5 * (infil[:-1] + infil[1:])
            total_time = float(t[-1] - t[0])
            if total_time <= 0:
                return None
            mean_rate = float(np.sum(infil_mid * dt) / total_time)
            return mean_rate  # m\u00b3/day
        except Exception:
            return None

    def _make_dem_viz_uri(self):
        """Render a DEM elevation heatmap with basin boundary and return a file URI."""
        try:
            import numpy as _np
            import tempfile as _tempfile
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as _plt
            from pathlib import Path as _Path
            from src.utils.dem_parser import parse_dem_file

            dem_path = self.dem_file_edit.text().strip() if hasattr(self, 'dem_file_edit') else ""
            if not dem_path:
                return None
            crest = self.dem_crest_input.value() if hasattr(self, 'dem_crest_input') else 0.0
            dem = parse_dem_file(dem_path)
            grid = _np.where(dem.valid_mask, dem.grid, _np.nan)
            basin_mask = (grid < crest) & dem.valid_mask

            fig, ax = _plt.subplots(figsize=(5.0, 4.0), dpi=150)
            im = ax.imshow(grid, cmap='terrain', aspect='equal',
                           vmin=_np.nanmin(grid), vmax=_np.nanmax(grid))
            # Draw basin boundary contour
            try:
                ax.contour(basin_mask.astype(float), levels=[0.5], colors='red', linewidths=1.5)
            except Exception:
                pass
            # Draw crest contour
            try:
                ax.contour(grid, levels=[crest], colors='white', linewidths=1.0, linestyles='dashed')
            except Exception:
                pass
            cbar = fig.colorbar(im, ax=ax, shrink=0.8, label='Elevation')
            ax.set_title(f'DEM Elevation  (crest = {crest:.1f})', fontsize=10)
            ax.set_xlabel('Column')
            ax.set_ylabel('Row')
            # Legend annotation
            try:
                ax.plot([], [], color='red', lw=1.5, label='Basin boundary')
                ax.plot([], [], color='white', lw=1.0, ls='--', label='Crest contour')
                ax.legend(loc='upper right', fontsize=7, framealpha=0.7)
            except Exception:
                pass
            fig.tight_layout()
            tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            tmp_path = tmp.name
            tmp.close()
            fig.savefig(tmp_path, dpi=150)
            _plt.close(fig)
            return _Path(tmp_path).resolve().as_uri()
        except Exception:
            return None

    def _generate_report(self):
        """Generate summary report (HTML preview used for PDF export)"""
        try:
            scenario = self.scenario_name.text().strip() or "Scenario"
            _dem_mode = self._is_dem_mode()

            # Capture 3D basin image or DEM heatmap
            basin_img_uri = None
            dem_viz_uri = None
            try:
                from pathlib import Path as _Path
                import tempfile, os
                if _dem_mode:
                    dem_viz_uri = self._make_dem_viz_uri()
                elif hasattr(self, 'design_view') and self.design_view is not None:
                    pm = self.design_view.grab()
                    _tmpdir = tempfile.mkdtemp(prefix="basim_cfg_")
                    _png = os.path.join(_tmpdir, 'basin_3d.png')
                    pm.save(_png, 'PNG')
                    basin_img_uri = _Path(_png).resolve().as_uri()
            except Exception:
                basin_img_uri = None

            # Helper: build and return a stage–storage PNG URI
            def _make_stage_storage_uri() -> str | None:
                try:
                    import numpy as _np
                    import tempfile as _tempfile, os as _os
                    import matplotlib
                    matplotlib.use('Agg')
                    import matplotlib.pyplot as _plt

                    # DEM mode: use LAKTAB data from the DEM
                    if _dem_mode:
                        try:
                            from src.utils.dem_parser import parse_dem_file
                            from src.utils.dem_model_builder import build_dem_model_config
                            dem_path = self.dem_file_edit.text().strip()
                            crest = self.dem_crest_input.value()
                            dem = parse_dem_file(dem_path)
                            dem_cfg = build_dem_model_config(dem, crest_elev=crest)
                            if dem_cfg.laktab_rows:
                                stages = _np.array([r[0] for r in dem_cfg.laktab_rows])
                                vols = _np.array([r[1] for r in dem_cfg.laktab_rows])
                                fig, ax = _plt.subplots(figsize=(4.0, 3.0), dpi=150)
                                ax.plot(stages, vols, color='#2a9d8f', lw=2.0)
                                ax.set_xlabel('Stage (m AHD)')
                                ax.set_ylabel('Storage (m³)')
                                ax.grid(alpha=0.3)
                                fig.tight_layout()
                                tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                                tmp_path = tmp.name
                                tmp.close()
                                fig.savefig(tmp_path, dpi=150)
                                _plt.close(fig)
                                return _Path(tmp_path).resolve().as_uri()
                        except Exception:
                            pass
                        return None

                    # Manual mode: analytic / custom depth-area
                    floor = float(self.floor_elev_input.value())
                    Dmax = float(self.depth_input.value())
                    Lf = float(self.length_input.value())
                    Wf = float(self.width_input.value())
                    m = float(self.side_slope_input.value())
                    d = _np.linspace(0.0, max(0.01, Dmax), 64)
                    if getattr(self, 'use_custom_da', False) and len(getattr(self, 'custom_depth_area', []) or []) >= 2:
                        rows = sorted({float(dd): float(aa) for dd, aa in self.custom_depth_area}.items())
                        cda_d = _np.array([r[0] for r in rows], float)
                        cda_a = _np.array([r[1] for r in rows], float)
                        try:
                            from scipy.integrate import cumulative_trapezoid as _cumtrapz
                            vols = _cumtrapz(cda_a, cda_d, initial=0.0)
                        except Exception:
                            dd = _np.diff(cda_d)
                            am = 0.5 * (cda_a[:-1] + cda_a[1:])
                            vols = _np.concatenate([[0.0], _np.cumsum(am * dd)])
                        from numpy import interp as _interp
                        v = _interp(d, cda_d, vols, left=0.0, right=float(vols[-1]))
                    else:
                        v = Lf*Wf*d + m*(Lf+Wf)*(d**2) + (4.0/3.0)*(m**2)*(d**3)
                    stg = floor + d
                    fig, ax = _plt.subplots(figsize=(4.0, 3.0), dpi=150)
                    ax.plot(stg, v, color='#2a9d8f', lw=2.0)
                    ax.set_xlabel('Stage (m AHD)')
                    ax.set_ylabel('Storage (m³)')
                    ax.grid(alpha=0.3)
                    fig.tight_layout()
                    tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    tmp_path = tmp.name
                    tmp.close()
                    fig.savefig(tmp_path, dpi=150)
                    _plt.close(fig)
                    return _Path(tmp_path).resolve().as_uri()
                except Exception:
                    return None

            # Helper: build small, styled table section
            def _tbl(title: str, rows: list[tuple[str, str]]) -> str:
                trs = "".join([f"<tr><td class='k'>{k}</td><td class='v'>{v}</td></tr>" for k, v in rows])
                return f"<h3>{title}</h3><table class='param'><tbody>{trs}</tbody></table>"

            # Build parameter tables
            if _dem_mode:
                _dem_path = self.dem_file_edit.text().strip() if hasattr(self, 'dem_file_edit') else ""
                _dem_crest = self.dem_crest_input.value() if hasattr(self, 'dem_crest_input') else 0.0
                # Compute DEM stats for the table
                _dem_stats = {}
                try:
                    from src.utils.dem_parser import parse_dem_file
                    import numpy as _np
                    _dem = parse_dem_file(_dem_path)
                    _basin_mask = (_dem.grid < _dem_crest) & _dem.valid_mask
                    _n_basin = int(_np.sum(_basin_mask))
                    _plan_area = _n_basin * _dem.cell_area
                    _floor_e = float(_np.nanmin(_dem.grid[_basin_mask])) if _n_basin > 0 else _dem.min_elev
                    _dem_stats = {
                        'grid_size': f"{_dem.grid.shape[0]} \u00d7 {_dem.grid.shape[1]}",
                        'cell_size': f"{_dem.cell_size_x:.2f} \u00d7 {_dem.cell_size_y:.2f}",
                        'basin_cells': f"{_n_basin:,}",
                        'plan_area': f"{_plan_area:,.1f} m\u00b2",
                        'floor_elev': f"{_floor_e:.2f} m AHD",
                        'elev_range': f"{_dem.min_elev:.2f} \u2013 {_dem.max_elev:.2f}",
                    }
                except Exception:
                    pass
                from pathlib import Path as _Path
                basin_rows = [
                    ("Source", "DEM file"),
                    ("DEM file", _Path(_dem_path).name if _dem_path else "(none)"),
                    ("Grid size (rows \u00d7 cols)", _dem_stats.get('grid_size', '--')),
                    ("Cell size", _dem_stats.get('cell_size', '--')),
                    ("Basin cells (below crest)", _dem_stats.get('basin_cells', '--')),
                    ("Basin plan area", _dem_stats.get('plan_area', '--')),
                    ("Crest elevation", f"{_dem_crest:.2f} m AHD"),
                    ("Floor elevation (min)", _dem_stats.get('floor_elev', '--')),
                    ("DEM elevation range", _dem_stats.get('elev_range', '--')),
                    ("Max depth", f"{_dem_crest - float(_dem_stats.get('floor_elev', '0').split()[0]):.2f} m" if _dem_stats.get('floor_elev') else '--'),
                ]
            else:
                basin_rows = [
                    ("Source", "Manual geometry"),
                    ("Shape", "Rectangle"),
                    ("Floor length", f"{self.length_input.value()} m"),
                    ("Floor width", f"{self.width_input.value()} m"),
                    ("Max depth", f"{self.depth_input.value()} m"),
                    ("Side slope (H:V)", f"{self.side_slope_input.value()}"),
                    ("Floor elevation", f"{self.floor_elev_input.value()} m AHD"),
                    ("Custom depth\u2013area", "Yes" if getattr(self, 'custom_depth_area', None) else "No"),
                ]
            hydro_rows = [
                ("Kh (m/day)", f"{self.kh_input.value()}"),
                ("Kv (m/day)", f"{self.kv_input.value()}"),
                ("Ss (1/m)", f"{self.ss_input.value():.6f}"),
                ("Sy (-)", f"{self.sy_input.value()}"),
                ("Initial groundwater level", f"{self.initial_head_input.value()} m AHD"),
                ("Aquifer bottom", f"{self.bottom_elev_input.value()} m AHD"),
            ]
            infil_rows = [
                ("Mode", self.infiltration_mode.currentText()),
                ("Bed thickness", f"{self.bed_thickness_input.value()} m"),
                ("Bed K", f"{self.bed_k_input.value()} m/day"),
                ("Side K", f"{self.side_k_input.value()} m/day" + (" (separate)" if self.side_k_separate_check.isChecked() else " (mirrors bed)")),
            ]
            sim_rows = [
                ("Performance mode", "fast (fixed)"),
                ("Post-storm duration", f"{self.post_storm_days_input.value()} days"),
                ("Post-storm step", f"{self.post_storm_step_input.value()} hours"),
                ("Lightweight outputs", "Yes" if self.lightweight_check.isChecked() else "No"),
                ("Cleanup heavy outputs", "Yes" if self.cleanup_check.isChecked() else "No"),
            ]

            # Outlets table
            outlets_html = ""
            try:
                outlets = list(getattr(self, '_outlets_cfg', []) or [])
                if self.outlet_enable.isChecked() and not outlets:
                    # Single outlet configured but not added to list yet
                    typ_txt = self.outlet_type.currentText().strip().lower()
                    if "pipe" in typ_txt:
                        outlets.append({
                            "type": "pipe", "diameter_m": float(self.pipe_diam.value()), "length_m": float(self.pipe_len.value()),
                            "invert_mAHD": float(self.pipe_invert.value()), "grade": float(self.pipe_slope.value()),
                            "mannings_n": float(self.pipe_n.value()), "count": int(self.pipe_count.value()),
                            "entrance_type": self.pipe_entrance.currentText().strip().lower(),
                        })
                    elif "broad" in typ_txt:
                        outlets.append({
                            "type": "broad_crested_weir", "crest_mAHD": float(self.weir_crest.value()),
                            "crest_length_m": float(self.weir_length.value()), "Cd": float(self.weir_Cd.value()),
                        })
                    else:
                        outlets.append({
                            "type": "grated_inlet", "crest_mAHD": float(self.grate_crest.value()),
                            "grate_area_m2": float(self.grate_area.value()), "perimeter_m": float(self.grate_perim.value()),
                            "grate_type": self.grate_type.currentText().strip().lower(),
                        })
                if outlets:
                    rows = []
                    for i, o in enumerate(outlets, 1):
                        t = o.get('type', 'pipe')
                        if t == 'pipe':
                            desc = f"Pipe D={o.get('diameter_m', 0):.3f} m, L={o.get('length_m', 0):.2f} m, inv={o.get('invert_mAHD', 0):.3f} m, n={o.get('mannings_n', 0):.3f}, S={o.get('grade', 0):.4f}, x{o.get('count', 1)}"
                        elif 'weir' in t:
                            desc = f"Broad-crested weir zc={o.get('crest_mAHD', 0):.3f} m, L={o.get('crest_length_m', 0):.2f} m, Cd={o.get('Cd', 0):.3f}"
                        else:
                            desc = f"Grate zc={o.get('crest_mAHD', 0):.3f} m, A={o.get('grate_area_m2', 0):.3f} m², P={o.get('perimeter_m', 0):.2f} m, type={o.get('grate_type', 'generic')}"
                        rows.append((f"Outlet {i}", desc))
                    outlets_html = _tbl("Outlets", rows)
                else:
                    outlets_html = _tbl("Outlets", [("Configured", "None")])
            except Exception:
                outlets_html = _tbl("Outlets", [("Configured", "None")])

            # Results summary table
            # Build rows and find critical (highest peak stage with outlet if available)
            res_rows = []
            try:
                peaks = []
                for ts1_file, result in self.results.items():
                    if not result.get("success"):
                        res_rows.append((Path(ts1_file).name, False, None, None, None, None, None, None, None, None, None))
                        continue
                    s = result.get("summary", {})
                    pk = s.get('peak_stage_with_outlet_m', s.get('peak_stage_m', s.get('max_stage', 0)))
                    peaks.append(float(pk) if pk is not None else -1e9)
                    # Spill detection
                    try:
                        _crest = self._get_crest_elevation()
                        _spill = s.get('spill_detected', False) or (float(pk) > _crest + 1e-6)
                    except Exception:
                        _spill = s.get('spill_detected', False)
                    res_rows.append((
                        Path(ts1_file).name, True,
                        pk,
                        s.get('cumulative_inflow_m3', s.get('inflow_total_m3', 0)),
                        s.get('peak_storage_with_outlet_m3', s.get('peak_storage_m3', 0)),
                        s.get('mean_infiltration_m3d', None),
                        _spill,
                        s.get('peak_outlet_m3s', None),
                        s.get('total_outlet_m3', None),
                        s.get('mass_balance_error_pct', None),
                        s.get('runtime_seconds', 0),
                    ))
                crit_idx = peaks.index(max(peaks)) if peaks else -1
            except Exception:
                crit_idx = -1

            res_html_rows = []
            for i, tpl in enumerate(res_rows):
                name, ok, pk, cin, psto, mean_inf, spill, pkout, tout, mbe, rt = tpl
                if not ok:
                    res_html_rows.append(
                        f"<tr><td>{name}</td><td>Failed</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>"
                    )
                else:
                    cls = " class='crit'" if i == crit_idx else ""
                    spill_txt = "<span style='color:#ff4444;font-weight:bold'>YES</span>" if spill else "No"
                    inf_txt = f"{float(mean_inf):.1f}" if mean_inf is not None else "--"
                    res_html_rows.append(
                        f"<tr{cls}><td>{name}</td><td>Success</td><td>{float(pk):.2f}</td><td>{float(cin):.0f}</td><td>{float(psto):.0f}</td><td>{inf_txt}</td><td>{spill_txt}</td><td>{'--' if pkout is None else f'{float(pkout):.3f}'}</td><td>{'--' if tout is None else f'{float(tout):.0f}'}</td><td>{'--' if mbe is None else f'{float(mbe):.2f}'}</td><td>{float(rt):.1f}</td></tr>"
                    )

            # Style + sections with page breaks
            style = """
                <style>
                body { font-family: Segoe UI, Arial, Helvetica, sans-serif; color:#e6e6e6; background:#2b2b2b; }
                h1 { font-size: 22px; margin: 0 0 6px 0; color:#ffffff; }
                h2 { font-size: 18px; margin: 16px 0 8px 0; color:#9fd9d4; }
                h3 { font-size: 15px; margin: 12px 0 6px 0; color:#c8f2ee; }
                .meta { color:#bbb; font-size: 11px; margin-bottom: 12px; }
                .section { margin-top: 10px; }
                .break { page-break-before: always; break-before: page; }
                table.param { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
                table.param td { border: 1px solid #444; padding: 6px 8px; }
                table.param td.k { width: 40%; background:#1f1f1f; color:#cfd3d5; font-weight: 600; }
                table.param td.v { background:#262626; }
                table.results { width: 100%; border-collapse: collapse; }
                table.results th, table.results td { border:1px solid #444; padding:6px 8px; }
                table.results th { background:#1f1f1f; color:#dfe3e5; }
                table.results tr:nth-child(even) td { background:#262626; }
                table.results tr:nth-child(odd) td { background:#2d2d2d; }
                table.results tr.crit td { background: rgba(255, 196, 0, 0.20); color:#141414; font-weight:600; }
                .imgwrap { text-align:center; }
                .imgwrap img { max-width: 90%; border:1px solid #555; border-radius:6px; }
                .note { color:#aaa; font-size: 10px; }
                </style>
            """

            # Total basin storage and crest info for the report
            _total_storage = self._get_total_basin_storage()
            _crest_elev = self._get_crest_elevation()
            storage_info_html = ""
            if _total_storage is not None:
                storage_info_html = (
                    "<h3>Basin Capacity</h3><table class='param'><tbody>"
                    f"<tr><td class='k'>Total Storage Available</td><td class='v'>{_total_storage:,.0f} m\u00b3</td></tr>"
                    f"<tr><td class='k'>Crest Elevation</td><td class='v'>{_crest_elev:.2f} m AHD</td></tr>"
                    "</tbody></table>"
                )

            # Sections
            header_html = f"<h1>BaSIM Simulation Report</h1><div class='meta'><b>Scenario:</b> {scenario} &nbsp;&nbsp; <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>"
            params_html = (
                "<h2>Model Parameters</h2>"
                + _tbl("Basin Geometry", basin_rows)
                + storage_info_html
                + _tbl("Hydrogeological Parameters", hydro_rows)
                + _tbl("Infiltration", infil_rows)
                + _tbl("Simulation", sim_rows)
                + outlets_html
                + (f"<h3>Stage\u2013Storage Curve</h3><div class='imgwrap'><img src='{_make_stage_storage_uri()}' alt='Stage\u2013storage curve'/></div>" if _make_stage_storage_uri() else "")
            )
            if _dem_mode:
                basin_view_html = (
                    "<h2 class='break'>DEM Elevation Map</h2>"
                    + (f"<div class='imgwrap'><img src='{dem_viz_uri}' alt='DEM elevation heatmap with basin boundary'/></div>" if dem_viz_uri else "<div class='note'>DEM visualization unavailable.</div>")
                )
            else:
                basin_view_html = (
                    "<h2 class='break'>3D Basin View</h2>"
                    + (f"<div class='imgwrap'><img src='{basin_img_uri}' alt='Basin 3D view at peak water stage'/></div>" if basin_img_uri else "<div class='note'>3D view unavailable.</div>")
                )
            results_html = (
                "<h2 class='break'>Results Summary</h2>"
                + "<table class='results'><thead><tr>"
                + "".join([f"<th>{h}</th>" for h in ["TS1 File","Status","Peak Stage (m)","Cumulative Inflow (m\u00b3)","Peak Storage (m\u00b3)","Mean Infil (m\u00b3/day)","Spill","Peak Outlet (m\u00b3/s)","Total Outlet (m\u00b3)","Mass Balance Error (%)","Runtime (s)"]])
                + "</tr></thead><tbody>"
                + "".join(res_html_rows)
                + "</tbody></table>"
            )
            graphs_html = (
                "<h2 class='break'>Graphs</h2>"
                "<div class='note'>Graphs will be embedded when exporting to PDF.</div>"
                "<div id='graphs-section'></div>"
            )

            report_html = f"<html><head><meta charset='utf-8'>{style}</head><body>{header_html}<div class='section'>{params_html}</div><div class='section'>{basin_view_html}</div><div class='section'>{results_html}</div><div class='section'>{graphs_html}</div></body></html>"
            self.report_edit.setHtml(report_html)
        except Exception:
            # Fallback minimal report to avoid breaking UI
            try:
                self.report_edit.setHtml("<h3>Report unavailable</h3>")
            except Exception:
                pass

    def export_report_pdf(self):
        """Export a minimal PDF with header and the current graphs, no watermark, no HTML.

        This draws directly to the PDF using QPainter and widget snapshots for reliability.
        """
        try:
            from PyQt6.QtGui import QPdfWriter, QPageSize, QPainter, QFont, QPixmap, QImage, QColor
            from PyQt6.QtCore import QRectF, QCoreApplication, QSizeF
        except Exception:
            QMessageBox.critical(self, "PDF Export Unavailable", "Qt PDF support is not available in this build.")
            return

        # Choose destination
        default_name = f"{(self.scenario_name.text().strip() or 'Scenario').replace(' ', '_')}_design_report.pdf"
        file_path, _ = QFileDialog.getSaveFileName(self, "Export PDF", default_name, "PDF Files (*.pdf)")
        if not file_path:
            return
        if not file_path.lower().endswith('.pdf'):
            file_path = file_path + ".pdf"

        # Prepare writer
        writer = QPdfWriter(file_path)
        try:
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        except Exception:
            pass
        writer.setResolution(300)

        # Ensure plots are rendered: briefly switch to tabs and update
        prev_idx = None
        try:
            if hasattr(self, 'results_tabs') and self.results_tabs is not None:
                prev_idx = self.results_tabs.currentIndex()
        except Exception:
            prev_idx = None
        try:
            if getattr(self, 'plot_widget', None) is not None and hasattr(self, 'timeseries_tab'):
                try:
                    idx = self.results_tabs.indexOf(self.timeseries_tab)
                    if idx >= 0:
                        self.results_tabs.setCurrentIndex(idx)
                        QCoreApplication.processEvents()
                except Exception:
                    pass
            if PYQTGRAPH_AVAILABLE:
                try:
                    self._ensure_flow_plot()
                    self._update_flow_plot()
                except Exception:
                    pass
            if getattr(self, 'flow_tab', None) is not None:
                try:
                    idx2 = self.results_tabs.indexOf(self.flow_tab)
                    if idx2 >= 0:
                        self.results_tabs.setCurrentIndex(idx2)
                        QCoreApplication.processEvents()
                except Exception:
                    pass
        finally:
            if prev_idx is not None and hasattr(self, 'results_tabs'):
                try:
                    self.results_tabs.setCurrentIndex(prev_idx)
                    QCoreApplication.processEvents()
                except Exception:
                    pass

        # Gather graph widgets to render later at full width
        graph_items = []
        if getattr(self, 'plot_widget', None) is not None:
            graph_items.append(("Stage Timeseries", self.plot_widget))
        # Add one Flow plot page per run
        flow_pages = 0
        if getattr(self, 'flow_plot', None) is not None and getattr(self, 'flow_run_select', None) is not None:
            try:
                cnt = int(self.flow_run_select.count())
            except Exception:
                cnt = 0
            if cnt > 0:
                for i in range(cnt):
                    run_label = None
                    try:
                        run_label = self.flow_run_select.itemText(i)
                    except Exception:
                        run_label = None
                    graph_items.append((
                        "Inflow vs Storage vs Outflow",
                        self.flow_plot,
                        {"run_index": i, "run_label": run_label}
                    ))
                flow_pages = cnt
        # One page for tables + stage page (optional) + one page per flow run
        total_pages = 1 + (1 if getattr(self, 'plot_widget', None) is not None else 0) + flow_pages

    # Build simple tables (parameters + results) as lightweight HTML
        def _safe(val, fmt="{}"):
            try:
                return fmt.format(val)
            except Exception:
                return "--"

        # Parameter tables
        _dem_mode = self._is_dem_mode()
        try:
            if _dem_mode:
                _dem_path = self.dem_file_edit.text().strip() if hasattr(self, 'dem_file_edit') else ""
                _dem_crest = self.dem_crest_input.value() if hasattr(self, 'dem_crest_input') else 0.0
                _dem_stats = {}
                try:
                    from src.utils.dem_parser import parse_dem_file
                    import numpy as _np
                    _dem = parse_dem_file(_dem_path)
                    _basin_mask = (_dem.grid < _dem_crest) & _dem.valid_mask
                    _n_basin = int(_np.sum(_basin_mask))
                    _plan_area = _n_basin * _dem.cell_area
                    _floor_e = float(_np.nanmin(_dem.grid[_basin_mask])) if _n_basin > 0 else _dem.min_elev
                    _dem_stats = {
                        'grid_size': f"{_dem.grid.shape[0]} \u00d7 {_dem.grid.shape[1]}",
                        'cell_size': f"{_dem.cell_size_x:.2f} \u00d7 {_dem.cell_size_y:.2f}",
                        'basin_cells': f"{_n_basin:,}",
                        'plan_area': f"{_plan_area:,.1f} m\u00b2",
                        'floor_elev': f"{_floor_e:.2f} m AHD",
                        'elev_range': f"{_dem.min_elev:.2f} \u2013 {_dem.max_elev:.2f}",
                    }
                except Exception:
                    pass
                from pathlib import Path as _PD
                basin_rows = [
                    ("Source", "DEM file"),
                    ("DEM file", _PD(_dem_path).name if _dem_path else "(none)"),
                    ("Grid size (rows \u00d7 cols)", _dem_stats.get('grid_size', '--')),
                    ("Cell size", _dem_stats.get('cell_size', '--')),
                    ("Basin cells (below crest)", _dem_stats.get('basin_cells', '--')),
                    ("Basin plan area", _dem_stats.get('plan_area', '--')),
                    ("Crest elevation", f"{_dem_crest:.2f} m AHD"),
                    ("Floor elevation (min)", _dem_stats.get('floor_elev', '--')),
                    ("DEM elevation range", _dem_stats.get('elev_range', '--')),
                    ("Max depth", f"{_dem_crest - float(_dem_stats.get('floor_elev', '0').split()[0]):.2f} m" if _dem_stats.get('floor_elev') else '--'),
                ]
            else:
                basin_rows = [
                    ("Source", "Manual geometry"),
                    ("Shape", "Rectangle"),
                    ("Floor length", _safe(self.length_input.value(), "{:.2f} m")),
                    ("Floor width", _safe(self.width_input.value(), "{:.2f} m")),
                    ("Max depth", _safe(self.depth_input.value(), "{:.2f} m")),
                    ("Side slope (H:V)", _safe(self.side_slope_input.value(), "{:.2f}")),
                    ("Floor elevation", _safe(self.floor_elev_input.value(), "{:.3f} m AHD")),
                    ("Custom depth\u2013area", "Yes" if getattr(self, 'custom_depth_area', None) else "No"),
                ]
        except Exception:
            basin_rows = []
        try:
            hydro_rows = [
                ("Kh (m/day)", _safe(self.kh_input.value(), "{:.3f}")),
                ("Kv (m/day)", _safe(self.kv_input.value(), "{:.3f}")),
                ("Ss (1/m)", _safe(self.ss_input.value(), "{:.6f}")),
                ("Sy (-)", _safe(self.sy_input.value(), "{:.3f}")),
                ("Initial groundwater level", _safe(self.initial_head_input.value(), "{:.3f} m AHD")),
                ("Aquifer bottom", _safe(self.bottom_elev_input.value(), "{:.3f} m AHD")),
            ]
        except Exception:
            hydro_rows = []
        try:
            infil_rows = [
                ("Mode", getattr(self.infiltration_mode, 'currentText', lambda: "")( ) if hasattr(self, 'infiltration_mode') else ""),
                ("Bed thickness", _safe(self.bed_thickness_input.value(), "{:.3f} m")),
                ("Bed K", _safe(self.bed_k_input.value(), "{:.3f} m/day")),
                ("Side K", _safe(self.side_k_input.value(), "{:.3f} m/day") + (" (separate)" if getattr(self, 'side_k_separate_check', None) and self.side_k_separate_check.isChecked() else " (mirrors bed)")),
            ]
        except Exception:
            infil_rows = []
        try:
            sim_rows = [
                ("Performance mode", "fast (fixed)"),
                ("Post-storm duration", _safe(self.post_storm_days_input.value(), "{:.0f} days")),
                ("Post-storm step", _safe(self.post_storm_step_input.value(), "{:.0f} hours")),
                ("Lightweight outputs", "Yes" if getattr(self, 'lightweight_check', None) and self.lightweight_check.isChecked() else "No"),
                ("Cleanup heavy outputs", "Yes" if getattr(self, 'cleanup_check', None) and self.cleanup_check.isChecked() else "No"),
            ]
        except Exception:
            sim_rows = []

        # Results summary table rows
        res_html_rows = []
        try:
            from pathlib import Path as _Path
            for ts1_file, result in (self.results or {}).items():
                name = _Path(ts1_file).name
                if not result.get("success"):
                    res_html_rows.append(f"<tr><td>{name}</td><td>Failed</td>" + "<td>--</td>"*7 + "</tr>")
                    continue
                s = result.get('summary', {})
                pk = s.get('peak_stage_with_outlet_m', s.get('peak_stage_m', s.get('max_stage', None)))
                cin = s.get('cumulative_inflow_m3', s.get('inflow_total_m3', None))
                psto = s.get('peak_storage_with_outlet_m3', s.get('peak_storage_m3', None))
                pkout = s.get('peak_outlet_m3s', None)
                tout = s.get('total_outlet_m3', None)
                mbe = s.get('mass_balance_error_pct', None)
                rt = s.get('runtime_seconds', None)
                res_html_rows.append(
                    "<tr>"
                    f"<td>{name}</td><td>Success</td>"
                    f"<td>{'--' if pk is None else f'{float(pk):.2f}'}</td>"
                    f"<td>{'--' if cin is None else f'{float(cin):.0f}'}</td>"
                    f"<td>{'--' if psto is None else f'{float(psto):.0f}'}</td>"
                    f"<td>{'--' if pkout is None else f'{float(pkout):.3f}'}</td>"
                    f"<td>{'--' if tout is None else f'{float(tout):.0f}'}</td>"
                    f"<td>{'--' if mbe is None else f'{float(mbe):.2f}'}</td>"
                    f"<td>{'--' if rt is None else f'{float(rt):.1f}'}</td>"
                    "</tr>"
                )
        except Exception:
            pass

        def _tbl_html(title, rows):
            if not rows:
                return ""
            trs = "".join([f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows])
            return f"<h3>{title}</h3><table><tbody>{trs}</tbody></table>"

        simple_style = (
            "<style>"
            "body{font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:#000;}"
            "h2{margin:6px 0 4px 0;font-size:14pt;}"
            "h3{margin:6px 0 2px 0;font-size:11pt;}"
            "table{width:100%;border-collapse:collapse;margin:4px 0;}"
            "td,th{border:1px solid #666;padding:4px 6px;font-size:9pt;}"
            "th{background:#eee;}"
            "</style>"
        )

    # Build a stage–storage curve image for embedding
        stage_storage_uri = None
        try:
            import numpy as _np
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as _plt
            from pathlib import Path as _Path
            import tempfile as _tempfile

            if _dem_mode:
                # DEM mode: use LAKTAB from DEM builder
                try:
                    from src.utils.dem_parser import parse_dem_file
                    from src.utils.dem_model_builder import build_dem_model_config
                    dem_path = self.dem_file_edit.text().strip()
                    crest = self.dem_crest_input.value()
                    dem = parse_dem_file(dem_path)
                    dem_cfg = build_dem_model_config(dem, crest_elev=crest)
                    if dem_cfg.laktab_rows:
                        stages = _np.array([r[0] for r in dem_cfg.laktab_rows])
                        vols = _np.array([r[1] for r in dem_cfg.laktab_rows])
                        fig, ax = _plt.subplots(figsize=(4.0, 3.0), dpi=150)
                        ax.plot(stages, vols, color='#2a9d8f', lw=2.0)
                        ax.set_xlabel('Stage (m AHD)')
                        ax.set_ylabel('Storage (m\u00b3)')
                        ax.grid(alpha=0.3)
                        fig.tight_layout()
                        tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                        tmp_path = tmp.name
                        tmp.close()
                        fig.savefig(tmp_path, dpi=150)
                        _plt.close(fig)
                        stage_storage_uri = _Path(tmp_path).resolve().as_uri()
                except Exception:
                    pass
            else:
                floor = float(self.floor_elev_input.value()); Dmax = float(self.depth_input.value())
                Lf = float(self.length_input.value()); Wf = float(self.width_input.value()); m = float(self.side_slope_input.value())
                d = _np.linspace(0.0, max(0.01, Dmax), 64)
                if getattr(self, 'use_custom_da', False) and len(getattr(self, 'custom_depth_area', []) or []) >= 2:
                    rows = sorted({float(dd): float(aa) for dd, aa in self.custom_depth_area}.items())
                    cda_d = _np.array([r[0] for r in rows], float)
                    cda_a = _np.array([r[1] for r in rows], float)
                    try:
                        from scipy.integrate import cumulative_trapezoid as _cumtrapz
                        vols = _cumtrapz(cda_a, cda_d, initial=0.0)
                    except Exception:
                        dd = _np.diff(cda_d); am = 0.5 * (cda_a[:-1] + cda_a[1:])
                        vols = _np.concatenate([[0.0], _np.cumsum(am * dd)])
                    from numpy import interp as _interp
                    v = _interp(d, cda_d, vols, left=0.0, right=float(vols[-1]))
                else:
                    v = Lf*Wf*d + m*(Lf+Wf)*(d**2) + (4.0/3.0)*(m**2)*(d**3)
                stg = floor + d
                fig, ax = _plt.subplots(figsize=(4.0, 3.0), dpi=150)
                ax.plot(stg, v, color='#2a9d8f', lw=2.0)
                ax.set_xlabel('Stage (m AHD)'); ax.set_ylabel('Storage (m\u00b3)'); ax.grid(alpha=0.3)
                fig.tight_layout()
                tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.png'); tmp_path = tmp.name; tmp.close()
                fig.savefig(tmp_path, dpi=150); _plt.close(fig)
                stage_storage_uri = _Path(tmp_path).resolve().as_uri()
        except Exception:
            stage_storage_uri = None

        # DEM visualization for PDF
        dem_viz_uri = self._make_dem_viz_uri() if _dem_mode else None

        # Scenario + date heading at top, then parameters and results
        scenario = self.scenario_name.text().strip() or "Scenario"
        date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        tables_html = (
            f"<html><head><meta charset='utf-8'>{simple_style}</head><body>"
            f"<h2>Scenario and Date</h2>"
            f"<table><tbody><tr><td><b>Scenario</b></td><td>{scenario}</td></tr>"
            f"<tr><td><b>Date</b></td><td>{date_str}</td></tr></tbody></table>"
            f"<h2>Model Parameters</h2>"
            f"{_tbl_html('Basin Geometry', basin_rows)}"
            f"{_tbl_html('Hydrogeological Parameters', hydro_rows)}"
            f"{_tbl_html('Infiltration', infil_rows)}"
            f"{_tbl_html('Simulation', sim_rows)}"
            + (f"<h3>Stage\u2013Storage Curve</h3><img alt='Stage\u2013storage curve' src='{stage_storage_uri}'>" if stage_storage_uri else "")
            + (f"<h3>DEM Elevation Map</h3><img alt='DEM elevation heatmap' src='{dem_viz_uri}' style='max-width:100%'>" if dem_viz_uri else "")
            + f"<h2>Results Summary</h2>"
            + f"<table><thead><tr>"
            + "".join([f"<th>{h}</th>" for h in [
                "TS1 File","Status","Peak Stage (m)","Cumulative Inflow (m³)",
                "Peak Storage (m³)","Peak Outlet (m³/s)","Total Outlet (m³)",
                "Mass Balance Error (%)","Runtime (s)"
            ]])
            + "</tr></thead><tbody>"
            + ("".join(res_html_rows) if res_html_rows else "")
            + "</tbody></table>"
            + "</body></html>"
        )

        # Start painting
        painter = QPainter()
        if not painter.begin(writer):
            QMessageBox.critical(self, "Export Failed", "Could not open PDF for writing. Try a local folder like C:\\Temp.")
            return

        # Prepare legend label backup container up-front for safety
        _legend_labels = []

        try:
            # Ensure a white page background and black pen for text
            try:
                painter.fillRect(QRectF(0, 0, writer.width(), writer.height()), QColor("white"))
                painter.setPen(QColor("black"))
            except Exception:
                pass

            # Page metrics
            res = writer.resolution()
            page_w = writer.width()
            page_h = writer.height()
            margin = int(0.5 * res)  # 0.5 inch margin
            x0 = margin
            y = margin
            avail_w = page_w - 2 * margin
            avail_h = page_h - 2 * margin

            # Footer drawer: disclaimer + page numbers, always inside page
            def _draw_footer(page_idx: int, total: int):
                try:
                    painter.save()
                    footer_h = int(0.55 * res)  # ~0.55"
                    fy = page_h - margin - footer_h + int(0.05 * res)
                    try:
                        painter.setPen(QColor("black"))
                    except Exception:
                        pass
                    from src.version import VERSION as _v
                    disclaimer = f"Generated by BaSIM v{_v}"
                    try:
                        small_font = QFont("Segoe UI", 8)
                    except Exception:
                        small_font = QFont(); small_font.setPointSize(8)
                    painter.setFont(small_font)
                    # Disclaimer (left-aligned)
                    painter.drawText(QRectF(x0, fy, avail_w * 0.7, footer_h * 0.9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, disclaimer)
                    # Page number (right-aligned)
                    page_txt = f"page {page_idx} of {total}"
                    painter.drawText(QRectF(x0, fy, avail_w, footer_h * 0.9), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, page_txt)
                    painter.restore()
                except Exception:
                    pass

            # Temporarily enlarge legend fonts for readability in export
            try:
                # Stage plot legend
                if getattr(self, 'plot_widget', None) is not None and hasattr(self.plot_widget, 'plotItem'):
                    pi = getattr(self.plot_widget, 'plotItem', None) or getattr(self.plot_widget, 'getPlotItem', lambda: None)()
                    leg = getattr(pi, 'legend', None)
                    if leg is not None and hasattr(leg, 'items'):
                        for sample, label in getattr(leg, 'items', []):
                            try:
                                oldf = label.font()
                                _legend_labels.append((label, oldf))
                                nf = QFont(oldf)
                                nf.setPointSize(max(11, oldf.pointSize() + 2))
                                label.setFont(nf)
                            except Exception:
                                pass
                # Flow plot legend
                if getattr(self, '_flow_legend', None) is not None and hasattr(self._flow_legend, 'items'):
                    for sample, label in getattr(self._flow_legend, 'items', []):
                        try:
                            oldf = label.font()
                            _legend_labels.append((label, oldf))
                            nf = QFont(oldf)
                            nf.setPointSize(max(11, oldf.pointSize() + 2))
                            label.setFont(nf)
                        except Exception:
                            pass
            except Exception:
                _legend_labels = []

            # Draw tables (full width). Scale CSS (96 dpi) to device and keep room for footer.
            try:
                from PyQt6.QtGui import QTextDocument
                doc = QTextDocument()
                doc.setHtml(tables_html)
                css_scale = res / 96.0
                doc.setPageSize(QSizeF(avail_w / css_scale, 100000))
                doc.adjustSize()
                doc_h_css = doc.size().height()
                # Reserve footer space
                footer_h = int(0.55 * res)
                content_h = avail_h - footer_h - int(0.05 * res)
                needed_h = doc_h_css * css_scale
                scale_factor = css_scale
                if needed_h > content_h - 10:  # shrink to fit within content area
                    shrink = max(0.5, (content_h - 10) / max(1.0, needed_h))
                    scale_factor = css_scale * shrink
                painter.save()
                painter.translate(x0, y)
                painter.scale(scale_factor, scale_factor)
                doc.drawContents(painter)
                painter.restore()
                # Fallback text if document height was zero (nothing drawn)
                try:
                    if needed_h <= 0:
                        painter.setFont(QFont("Segoe UI", 10))
                        painter.setPen(QColor("black"))
                        painter.drawText(QRectF(x0, y, avail_w, int(0.4 * res)), 0, "Model parameters unavailable")
                        y += int(0.4 * res)
                except Exception:
                    pass
                # Footer on first page
                _draw_footer(1, total_pages)
                y = margin  # move graphs to new page for clarity
                writer.newPage()
                # Clear for next page content
                try:
                    painter.fillRect(QRectF(0, 0, writer.width(), writer.height()), QColor("white"))
                except Exception:
                    pass
            except Exception:
                # If anything goes wrong, skip tables and continue with graphs
                pass

            # Helper to render a widget to a high-res image that fits the page width
            def make_graph_image(w, target_w_px: int, max_h_px: int):
                try:
                    if w is None or target_w_px <= 0 or max_h_px <= 0:
                        return None
                    # Prefer pyqtgraph exporter for precise sizing
                    if PYQTGRAPH_AVAILABLE:
                        try:
                            from pyqtgraph.exporters import ImageExporter
                            export_item = None
                            # PlotWidget
                            if hasattr(w, 'plotItem') and w.plotItem is not None:
                                export_item = w.plotItem
                            # GraphicsLayoutWidget (flow layout)
                            elif hasattr(w, 'scene') and callable(w.scene):
                                export_item = w.scene()
                            if export_item is not None:
                                exporter = ImageExporter(export_item)
                                # set target width in pixels; exporter preserves aspect ratio
                                try:
                                    exporter.parameters()['width'] = int(target_w_px)
                                except Exception:
                                    exporter.params['width'] = int(target_w_px)
                                import tempfile, os
                                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                                tmp_path = tmp.name
                                tmp.close()
                                try:
                                    exporter.export(tmp_path)
                                    img = QImage(tmp_path)
                                finally:
                                    try:
                                        os.unlink(tmp_path)
                                    except Exception:
                                        pass
                                if not img.isNull():
                                    # Constrain height if needed
                                    if img.height() > max_h_px:
                                        img = img.scaled(int(target_w_px), int(max_h_px), aspectRatioMode=1, transformMode=1)
                                    return img
                        except Exception:
                            pass
                    base_sz = w.size()
                    if base_sz.width() <= 0 or base_sz.height() <= 0:
                        base_sz = w.sizeHint()
                    bw, bh = base_sz.width(), base_sz.height()
                    if bw <= 0 or bh <= 0:
                        return None
                    scale = float(target_w_px) / float(bw)
                    target_h = int(bh * scale)
                    if target_h > max_h_px:
                        scale *= float(max_h_px) / float(target_h)
                        target_h = max_h_px
                    img = QImage(int(target_w_px), int(target_h), QImage.Format.Format_ARGB32)
                    img.fill(0xFFFFFFFF)
                    p = QPainter(img)
                    try:
                        p.scale(scale, scale)
                        w.render(p)
                    finally:
                        p.end()
                    return img
                except Exception:
                    # Fallback to a simple grab scaled up/down
                    try:
                        pm = w.grab()
                        if pm.isNull():
                            return None
                        img = pm.toImage()
                        # Preserve aspect; fit width then clamp height
                        img = img.scaled(int(target_w_px), int(target_w_px * (img.height()/max(1.0, img.width()))), aspectRatioMode=1, transformMode=1)
                        if img.height() > max_h_px:
                            img = img.scaled(int(target_w_px), int(max_h_px), aspectRatioMode=1, transformMode=1)
                        return img
                    except Exception:
                        return None

            # Draw each graph on its own page for simplicity
            first = True
            page_idx = 2
            # Preserve current flow selection to restore later
            prev_flow_idx = None
            try:
                if getattr(self, 'flow_run_select', None) is not None:
                    prev_flow_idx = self.flow_run_select.currentIndex()
            except Exception:
                prev_flow_idx = None

            for item in graph_items:
                # Allow tuples of length 2 or 3: (title, widget[, info])
                if isinstance(item, (tuple, list)):
                    if len(item) >= 2:
                        title, widget = item[0], item[1]
                        info = item[2] if len(item) >= 3 else None
                    else:
                        continue
                else:
                    continue
                # If this is a flow page with a specific run, switch selection and refresh
                if widget is getattr(self, 'flow_plot', None) and isinstance(info, dict) and 'run_index' in info:
                    try:
                        idx_sel = int(info.get('run_index'))
                        if getattr(self, 'flow_run_select', None) is not None and 0 <= idx_sel < self.flow_run_select.count():
                            self.flow_run_select.setCurrentIndex(idx_sel)
                            QCoreApplication.processEvents()
                            try:
                                self._update_flow_plot()
                            except Exception:
                                pass
                            QCoreApplication.processEvents()
                    except Exception:
                        pass
                # If this is the flow plot, annotate with run label
                if widget is getattr(self, 'flow_plot', None):
                    try:
                        run_label = None
                        if isinstance(info, dict) and info.get('run_label'):
                            run_label = info.get('run_label')
                        elif getattr(self, 'flow_run_select', None):
                            run_label = self.flow_run_select.currentText()
                        if run_label:
                            title = f"Inflow vs Storage vs Outflow — {run_label}"
                    except Exception:
                        pass
                if not first:
                    writer.newPage()
                    y = margin
                    # Clear page contents
                    try:
                        painter.fillRect(QRectF(0, 0, writer.width(), writer.height()), QColor("white"))
                    except Exception:
                        pass
                    try:
                        title_font = QFont("Segoe UI", 12)
                    except Exception:
                        title_font = QFont(); title_font.setPointSize(12)
                    painter.setFont(title_font)
                    try:
                        from PyQt6.QtGui import QFontMetrics
                        tfm = QFontMetrics(title_font)
                        title_h = int(tfm.height() * 1.2)
                    except Exception:
                        title_h = int(45)
                    painter.drawText(QRectF(x0, y, avail_w, title_h), 0, title)
                    y += title_h
                    y += int(res * 0.06)
                else:
                    # first graph page after tables
                    y = margin
                    try:
                        title_font = QFont("Segoe UI", 12)
                    except Exception:
                        title_font = QFont(); title_font.setPointSize(12)
                    painter.setFont(title_font)
                    try:
                        from PyQt6.QtGui import QFontMetrics
                        tfm = QFontMetrics(title_font)
                        title_h = int(tfm.height() * 1.2)
                    except Exception:
                        title_h = int(45)
                    painter.drawText(QRectF(x0, y, avail_w, title_h), 0, title)
                    y += title_h
                    y += int(res * 0.06)
                first = False

                # Leave space for footer
                footer_h = int(0.55 * res)
                max_h_for_graph = page_h - y - footer_h - int(0.05 * res)
                # Ensure a small padding below title and fit within content rect
                img = make_graph_image(widget, int(avail_w), int(max_h_for_graph))
                if img is None:
                    _draw_footer(page_idx, total_pages); page_idx += 1; continue
                iw, ih = img.width(), img.height()
                if iw <= 0 or ih <= 0:
                    _draw_footer(page_idx, total_pages); page_idx += 1; continue
                # Draw at full available width (already sized), preserve margins
                painter.drawImage(QRectF(x0, y, avail_w, ih), img, QRectF(0, 0, iw, ih))
                # Footer on this page
                _draw_footer(page_idx, total_pages)
                page_idx += 1
                # No need to advance y; next graph starts on a new page
            # All pages drew their own footers
            # Restore previous flow selection
            try:
                if prev_flow_idx is not None and getattr(self, 'flow_run_select', None) is not None:
                    if 0 <= prev_flow_idx < self.flow_run_select.count():
                        self.flow_run_select.setCurrentIndex(prev_flow_idx)
                        QCoreApplication.processEvents()
            except Exception:
                pass

            # Done
        finally:
            # Restore legend fonts
            try:
                for label, oldf in _legend_labels:
                    try:
                        label.setFont(oldf)
                    except Exception:
                        pass
            except Exception:
                pass
            painter.end()

        # Verify file size
        try:
            import os as _os
            size = _os.path.getsize(file_path) if _os.path.exists(file_path) else 0
        except Exception:
            size = 0
        if size == 0:
            QMessageBox.critical(self, "Export Failed", "PDF file is empty. Please save to a local folder (e.g., C:\\Temp) and try again.")
        else:
            QMessageBox.information(self, "Export Complete", f"Report exported to:\n{file_path}")

    def show_run_log(self):
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    def _log_line(self, text: str):
        self.log_text.append(text)

    def _set_item_done(self, ts1_file: str, success: bool = True):
        triple = self.ts1_widgets.get(ts1_file)
        if triple:
            _, _, bar = triple
            bar.setRange(0, 100)
            bar.setValue(100)
            try:
                bar.setFormat("Complete" if success else "Failed")
                if not success:
                    bar.setStyleSheet("QProgressBar::chunk { background-color: #bb4444; } QProgressBar { color: white; }")
                else:
                    bar.setStyleSheet("")
            except Exception:
                pass
    
    def save_configuration(self):
        """Save current configuration to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            "basim_config.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            config = self.build_config()
            if config:
                with open(file_path, 'w') as f:
                    json.dump(config, f, indent=2)

    # RTF export was removed per user request
    
    def load_configuration(self):
        """Load configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    config = json.load(f)
                self._apply_config(config)
                self.status_bar.showMessage(f"Configuration loaded from {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load configuration: {str(e)}")
    
    def _load_saved_config(self):
        """Load last saved configuration if exists"""
        config_file = USER_BASE / "basim_last_config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                self._apply_config(config)
            except:
                pass  # Ignore errors loading saved config
    
    def _apply_config(self, config):
        """Apply configuration to UI"""
        try:
            # Basin geometry
            bg = config.get("basin_geometry", {})
            self.length_input.setValue(bg.get("length_floor", 50))
            self.width_input.setValue(bg.get("width_floor", 30))
            self.depth_input.setValue(bg.get("max_depth", 3))
            self.side_slope_input.setValue(bg.get("side_slope_hv", 3))
            self.floor_elev_input.setValue(bg.get("floor_elev", 5))
            self._update_design_view()
            
            # Aquifer
            aq = config.get("aquifer", {})
            kv = float(aq.get('k_vertical_mpd', 0.0864))
            kh = float(aq.get('k_horizontal_mpd', kv))
            self.kv_input.setValue(kv)
            self.sep_kh_check.setChecked(kh != kv)
            self.kh_input.setEnabled(self.sep_kh_check.isChecked())
            self.kh_input.setValue(kh)
            self.ss_input.setValue(aq.get('ss', 1e-5))
            self.sy_input.setValue(aq.get("sy", 0.1))
            self.initial_head_input.setValue(aq.get("initial_head", 5.0))
            self.bottom_elev_input.setValue(aq.get("bottom_elev", -5))
            
            # Infiltration
            inf = config.get("infiltration", {})
            self.infiltration_mode.setCurrentText(inf.get("mode", "full"))
            self.bed_thickness_input.setValue(inf.get("bed_thickness_m", 0.5))
            self.bed_k_input.setValue(inf.get("bed_k_mpd", 5))
            # side-k separate flag and value
            try:
                self.side_k_separate_check.setChecked(bool(inf.get("side_k_separate", False)))
            except Exception:
                pass
            self.side_k_input.setValue(inf.get("side_k_mpd", 2.5))
            try:
                self.bed_thickness_input.valueChanged.connect(self._update_design_view)
                self.floor_elev_input.valueChanged.connect(self._update_design_view)
            except Exception:
                pass
            # sync enable/lock state after applying values
            try:
                self._sync_infiltration_side_controls()
            except Exception:
                pass

            # UZF soil parameters
            uzf = config.get("uzf", {})
            if isinstance(uzf, dict):
                try:
                    self.thts_input.setValue(float(uzf.get("thts", 0.35)))
                    self.thtr_input.setValue(float(uzf.get("thtr", 0.05)))
                    self.eps_input.setValue(float(uzf.get("eps", 4.0)))
                    self.thti_input.setValue(float(uzf.get("thti", 0.10)))
                except Exception:
                    pass
            
            # Performance: internal mode is always fast; ignore any saved values
            # (UI no longer exposes a performance dropdown.)
            
            # Simulation
            self.post_storm_days_input.setValue(config.get("post_storm_days", 3))
            self.post_storm_step_input.setValue(config.get("post_storm_step_hours", 1))
            self.lightweight_check.setChecked(config.get("lightweight_outputs", True))
            self.cleanup_check.setChecked(config.get("cleanup_heavy", True))
            # Scenario name
            self.scenario_name.setText(config.get("scenario_title", "Scenario 1"))
            # Output dir
            try:
                if "output_dir" in config and isinstance(self.output_dir_edit, QLineEdit):
                    self.output_dir_edit.setText(str(config.get("output_dir") or ""))
            except Exception:
                pass

            # Outlet overlay
            out_cfg = config.get("outlet", {}) if isinstance(config.get("outlet", {}), dict) else {}
            enabled = bool(out_cfg.get("enabled", False))
            self.outlet_enable.setChecked(enabled)
            typ = str(out_cfg.get("type", "")).strip().lower()
            if typ in ("pipe", "piped", "culvert"):
                self.outlet_type.setCurrentText("pipe")
                try:
                    self.pipe_diam.setValue(float(out_cfg.get("diameter_m", self.pipe_diam.value())))
                    self.pipe_len.setValue(float(out_cfg.get("length_m", self.pipe_len.value())))
                    self.pipe_invert.setValue(float(out_cfg.get("invert_mAHD", self.pipe_invert.value())))
                    self.pipe_slope.setValue(float(out_cfg.get("grade", out_cfg.get("slope", self.pipe_slope.value()))))
                    self.pipe_n.setValue(float(out_cfg.get("mannings_n", self.pipe_n.value())))
                    self.pipe_count.setValue(int(out_cfg.get("count", 1)))
                    ent = str(out_cfg.get("entrance_type", self.pipe_entrance.currentText())).strip().lower()
                    idx = max(0, self.pipe_entrance.findText(ent))
                    self.pipe_entrance.setCurrentIndex(idx)
                except Exception:
                    pass
            elif "weir" in typ:
                self.outlet_type.setCurrentText("broad-crested weir")
                try:
                    self.weir_crest.setValue(float(out_cfg.get("crest_mAHD", self.weir_crest.value())))
                    self.weir_length.setValue(float(out_cfg.get("crest_length_m", self.weir_length.value())))
                    self.weir_Cd.setValue(float(out_cfg.get("Cd", self.weir_Cd.value())))
                except Exception:
                    pass
            elif typ:
                self.outlet_type.setCurrentText("grated inlet")
                try:
                    self.grate_crest.setValue(float(out_cfg.get("crest_mAHD", self.grate_crest.value())))
                    self.grate_area.setValue(float(out_cfg.get("grate_area_m2", self.grate_area.value())))
                    self.grate_perim.setValue(float(out_cfg.get("perimeter_m", self.grate_perim.value())))
                    gt = str(out_cfg.get("grate_type", self.grate_type.currentText())).strip().lower()
                    idx = max(0, self.grate_type.findText(gt))
                    self.grate_type.setCurrentIndex(idx)
                except Exception:
                    pass
            # ensure stack enable/disable reflects config
            try:
                # Reuse the handler to update
                if hasattr(self, 'outlet_type') and hasattr(self, 'outlet_stack'):
                    idx = {"pipe": 0, "broad-crested weir": 1, "grated inlet": 2}.get(self.outlet_type.currentText().strip().lower(), 0)
                    self.outlet_stack.setCurrentIndex(idx)
                    self.outlet_stack.setEnabled(enabled)
                    self.outlet_type.setEnabled(enabled)
            except Exception:
                pass
            
        except Exception as e:
            print(f"Error applying config: {e}")
    
    def _export_stage_csv(self):
        """Export stage timeseries graph data for all runs to a single CSV."""
        series = getattr(self, '_stage_plot_series', None)
        if not series:
            QMessageBox.information(self, "No Data", "Run a simulation first to generate stage data.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Stage Graph Data", "stage_timeseries.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        try:
            import pandas as pd, numpy as np
            # Build a common time axis from all series
            t_all = np.unique(np.concatenate([s["time"] for s in series]))
            data = {"time_days": t_all}
            for s in series:
                label = s["label"].replace(",", "_")
                data[f"stage_{label}_m"] = np.interp(t_all, s["time"], s["stage"])
            # Add crest
            try:
                crest = self._get_crest_elevation()
                data["crest_m"] = np.full_like(t_all, crest)
            except Exception:
                pass
            df = pd.DataFrame(data)
            df.to_csv(file_path, index=False, float_format="%.6f")
            self.status_bar.showMessage(f"Stage data exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export stage data: {e}")

    def _export_flow_csv(self):
        """Export the current Inflow-Storage-Outflow graph data to CSV."""
        if not hasattr(self, 'flow_run_select') or self.flow_run_select.count() == 0:
            QMessageBox.information(self, "No Data", "No flow data available to export.")
            return
        ts1_key = self.flow_run_select.currentData()
        result = self.results.get(ts1_key, {})
        out_dir = result.get('output_dir')
        if not out_dir:
            QMessageBox.information(self, "No Data", "No output directory found for selected run.")
            return
        series = self._load_wb_series(ts1_key, out_dir, self.flow_time_unit_select)
        if series is None:
            QMessageBox.information(self, "No Data", "Could not load water balance data for selected run.")
            return
        run_label = self.flow_run_select.currentText() or "run"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Flow Graph Data", f"flow_data_{run_label}.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        try:
            import pandas as pd
            t, inflow, gwf_in, cum_in, storage, cum_infil = series
            unit = self.flow_time_unit_select.currentData() or 'days'
            data = {f"time_{unit}": t}
            if inflow is not None:
                data["inflow_m3s"] = inflow
            if gwf_in is not None:
                data["gw_inflow_m3s"] = gwf_in
            if cum_in is not None:
                data["cumulative_inflow_m3"] = cum_in
            if storage is not None:
                data["storage_m3"] = storage
            if cum_infil is not None:
                data["cumulative_infiltration_m3"] = cum_infil
            # Try to add outlet data too
            try:
                if bool(result.get('summary', {}).get('outlet_enabled', False)):
                    p = Path(out_dir)
                    f = max(list(p.glob('*_with_outlet.csv')) or [], key=lambda x: x.stat().st_mtime)
                    if f and f.exists():
                        d = pd.read_csv(f)
                        if 'time_days' in d.columns:
                            import numpy as np
                            tt = d['time_days'].astype(float).values
                            if unit == 'hours':
                                tt = tt * 24.0
                            if 'outlet_discharge_m3s' in d.columns:
                                data['outlet_discharge_m3s'] = np.interp(t, tt, d['outlet_discharge_m3s'].astype(float).values)
                            if 'storage_with_outlet_m3' in d.columns:
                                data['storage_with_outlet_m3'] = np.interp(t, tt, d['storage_with_outlet_m3'].astype(float).values)
            except Exception:
                pass
            df = pd.DataFrame(data)
            df.to_csv(file_path, index=False, float_format="%.6f")
            self.status_bar.showMessage(f"Flow data exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export flow data: {e}")

    def export_results(self):
        """Export results to CSV"""
        if not self.results:
            QMessageBox.information(self, "No Results", "No results to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "basim_results.csv",
            "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                import pandas as pd
                
                rows = []
                for ts1_file, result in self.results.items():
                    s = result.get("summary", {}) if result["success"] else {}
                    pk = s.get('peak_stage_with_outlet_m', s.get('peak_stage_m', s.get('max_stage', 0)))
                    try:
                        _crest = self._get_crest_elevation()
                        _spill = s.get('spill_detected', False) or (float(pk) > _crest + 1e-6)
                    except Exception:
                        _spill = s.get('spill_detected', False)
                    row = {
                        "TS1_File": Path(ts1_file).name,
                        "Success": result["success"],
                        "Peak_Stage_m": float(pk) if result["success"] else "",
                        "Cumulative_Inflow_m3": s.get('cumulative_inflow_m3', "") if result["success"] else "",
                        "Peak_Storage_m3": s.get('peak_storage_with_outlet_m3', s.get('peak_storage_m3', "")) if result["success"] else "",
                        "Mean_Infiltration_m3d": s.get('mean_infiltration_m3d', "") if result["success"] else "",
                        "Spill": "YES" if _spill else "No",
                        "Peak_Outlet_m3s": s.get('peak_outlet_m3s', "") if result["success"] else "",
                        "Total_Outlet_m3": s.get('total_outlet_m3', "") if result["success"] else "",
                        "Runtime_s": s.get("runtime_seconds", 0) if result["success"] else "",
                        "Output_Directory": str(result["output_dir"])
                    }
                    rows.append(row)
                
                df = pd.DataFrame(rows)
                df.to_csv(file_path, index=False)
                self.status_bar.showMessage(f"Results exported to {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export results: {str(e)}")
    
    def show_about(self):
        """Show about dialog"""
        from src.version import VERSION, RELEASE_DATE
        QMessageBox.about(
            self,
            "About BaSIM - Basin Simulator",
            f"""<h3>BaSIM - Basin Simulator</h3>
            <p>Version {VERSION} ({RELEASE_DATE})</p>
            <p>Stormwater basin simulation powered by MODFLOW 6</p>
            <p>Built on MODFLOW 6 groundwater modeling system</p>
            <p>&copy; 2025-2026</p>
            """
        )
    
    def closeEvent(self, event):
        """Save configuration on exit"""
        config = self.build_config()
        if config:
            config_file = USER_BASE / "basim_last_config.json"
            try:
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)
            except:
                pass  # Ignore errors saving config
        event.accept()

    # --- helper UI builders ---
    def _label_with_info(self, text: str, tip: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(text)
        info = self._make_info_button(tip)
        h.addWidget(lbl)
        h.addWidget(info)
        h.addStretch()
        return w

    def _make_info_button(self, tip: str) -> QToolButton:
        info = QToolButton()
        info.setText("i")
        info.setAutoRaise(True)
        info.setToolTip(tip)
        info.setFixedSize(18, 18)
        info.setCursor(Qt.CursorShape.PointingHandCursor)
        # Show tooltip on click as a pop-up to ensure visibility
        def _show_tip():
            QToolTip.showText(QCursor.pos(), tip, info)
        info.clicked.connect(_show_tip)
        return info

    def _update_design_view(self):
        if not hasattr(self, 'design_view'):
            return

        # In DEM mode, render the actual DEM raster
        if hasattr(self, 'basin_source_dem') and self.basin_source_dem.isChecked():
            dem_path = self.dem_file_edit.text().strip() if hasattr(self, 'dem_file_edit') else ""
            crest = self.dem_crest_input.value() if hasattr(self, 'dem_crest_input') else 0.0
            gw = None
            try:
                gw = float(self.initial_head_input.value())
            except Exception:
                pass
            if dem_path:
                self.design_view.render_dem(dem_path, crest, gw)
            else:
                self.design_view.render_placeholder()
            return

        # Manual mode — synthetic raster preview
        try:
            length = self.length_input.value()
            width = self.width_input.value()
            depth = self.depth_input.value()
            slope = self.side_slope_input.value()
            floor_elev = self.floor_elev_input.value()
            gwh = getattr(self, "_gw_overlay_head", self.initial_head_input.value())
            crest_elev = floor_elev + depth
            self.design_view.render_manual(
                length, width, depth, slope,
                floor_elev, float(gwh), crest_elev,
            )
        except Exception:
            pass

    # elapsed timer tick for run feedback
    def _tick_elapsed(self):
        try:
            elapsed = (datetime.now() - getattr(self, "_run_start_time", datetime.now())).total_seconds()
            self.status_label.setText(f"Running… Elapsed {int(elapsed)} s")
        except Exception:
            pass


# --- Application entry point helpers ---
def launch_app():
    """Launch the PyQt6 GUI application.

    Returns the Qt application exit code. This is used by basim.py.
    """
    # On Windows, set AppUserModelID (redundant with module-level, but safe)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APPID)
    except Exception:
        pass

    # Set HiDPI policy before creating the application
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication.instance()
    if app is None:
        # Create the application before any widgets
        app = QApplication(sys.argv)

    # Set application-wide icon (ensures taskbar + Alt-Tab show BaSIM logo)
    try:
        _logo_ico = Path(__file__).resolve().parent.parent.parent / "logo" / "logomark.ico"
        if not _logo_ico.exists():
            _logo_ico = Path(__file__).resolve().parent.parent.parent / "logo" / "transparent_logomark.png"
        if _logo_ico.exists():
            app.setWindowIcon(QIcon(str(_logo_ico)))
    except Exception:
        pass

    win = BaSIMMainWindow()
    win.show()
    try:
        return app.exec()
    except Exception:
        # Ensure a numeric exit code in case of unexpected errors
        return 1


if __name__ == "__main__":
    # Allow launching this module directly for development
    sys.exit(launch_app())
