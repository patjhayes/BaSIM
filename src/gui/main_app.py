#!/usr/bin/env python3
# Minimal GUI shell for BaSIM using CustomTkinter

import customtkinter as ctk  # type: ignore
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import sys
import threading
import json
import os
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed

# Ensure imports work whether run as module or script
try:
    # Add project root and src to sys.path if needed
    _here = Path(__file__).resolve()
    _src_dir = _here.parent.parent
    _proj_root = _src_dir.parent
    for _p in (str(_proj_root), str(_src_dir)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
except Exception:
    pass

from src.main_phase3_step32_time_varying import (
    inspect_ts1_columns,
    validate_basin_configuration,
)
from src.usg_model_builder import run_simulation
from src.utils.parallel_runner import run_model_worker
from src.version import VERSION, RELEASE_DATE, RELEASE_NOTES, BUILD_METADATA, check_for_updates
from src.core.update_channel import check_manifest, apply_update, check_manifest_cached
from src.utils import error_reporter
from src.licensing.license_manager import LicenseManager
from pathlib import Path

class BaseBaSIMApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Program title in OS title bar
        self.title("BaSIM - Basin Simulator")
        self.geometry("1200x800")
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        # Logging to file (rotating), plus GUI console mirroring via _log()
        self._logger = None
        self._init_logging()
        # Set window/taskbar icon from logo assets (safe no-op if unavailable)
        try:
            self._set_logo_image(24)
        except Exception:
            pass

        # Predefine optional UI fields to avoid Tk __getattr__ fallback
        self.ent_folder = None
        self.lbl_folder_status = None

        # Determine available cores first (needed by UI builder)
        # Prefer leaving 1 core for UI; minimum 1
        try:
            self._max_cores = max(1, (os.cpu_count() or 2) - 1)
        except Exception:
            self._max_cores = 1

        # Install global error reporting early
        try:
            error_reporter.install(app_window=self, logger=self._logger)
        except Exception:
            pass

        # Build UI and initialize state
        self._build_layout()
        self._reset_state()
        # Load last-used folder preference (if any)
        try:
            self._load_prefs()
        except Exception:
            pass
        # Validate and auto-scan if folder present
        try:
            self._validate_folder_status()
            if self.ent_folder is not None and (self.ent_folder.get().strip()):
                self._load_ts1_from_folder()
        except Exception:
            pass
        # Run state
        self._has_run_before = False
        self._previous_scenario = None
        # Initialize run button style
        self._update_run_button()
        # Save prefs on close
        try:
            self.protocol("WM_DELETE_WINDOW", self.on_close)
        except Exception:
            pass
        try:
            self._logger.info("BaSIM v%s launched and UI initialized", VERSION)
        except Exception:
            pass

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top controls
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        try:
            top.grid_columnconfigure(7, weight=1)  # spacer before progress bar
        except Exception:
            pass

        # Title (top-left)
        self._logo_img = None  # kept for compatibility; no image used
        self._logo_lbl = ctk.CTkLabel(top, text="BaSIM - Basin Simulator", font=("Arial", 16, "bold"))
        self._logo_lbl.grid(row=0, column=0, padx=(2, 14), sticky="w")

        # TS1 controls and Run
        self.btn_add_ts1 = ctk.CTkButton(top, text="Add TS1…", command=self._add_ts1)
        self.btn_add_ts1.grid(row=0, column=1, padx=6)
        self.btn_run = ctk.CTkButton(top, text="Run", command=self._run_all)
        self.btn_run.grid(row=0, column=2, padx=6)
        self.btn_toggle_log = ctk.CTkButton(top, text="Show Log", command=self._show_log_popup)
        self.btn_toggle_log.grid(row=0, column=5, padx=6)

        # Infiltration mode control with info balloon and user-friendly labels
        mode_frame = ctk.CTkFrame(top)
        mode_frame.grid(row=0, column=3, padx=8)
        lbl_mode = ctk.CTkLabel(mode_frame, text="Infiltration Mode:")
        lbl_mode.pack(side="left")
        self._attach_info_balloon(lbl_mode, "Choose how infiltration is applied.\n- Vertical only: leakage through the basin floor.\n- Full infiltration: floor + bank seepage via horizontal connections.")
        self.mode_display_to_internal = {"Vertical only": "vertical", "Full infiltration": "full"}
        self.mode_opt = ctk.CTkOptionMenu(mode_frame, values=list(self.mode_display_to_internal.keys()))
        self.mode_opt.set("Full infiltration")
        self.mode_opt.pack(side="left", padx=6)

        # Performance profile control (Fast / Balanced / Accurate)
        try:
            # spacer
            ctk.CTkLabel(mode_frame, text="  •  ").pack(side="left")
        except Exception:
            pass
        perf_lbl = ctk.CTkLabel(mode_frame, text="Performance:")
        perf_lbl.pack(side="left")
        self._attach_info_balloon(
            perf_lbl,
            "Select grid resolution profile.\n- Fast: coarser grid for quicker runs.\n- Balanced: default balance of speed/accuracy.\n- Accurate: finer grid for more detail.\nNote: A minimum 0.5 m cell size is always enforced."
        )
        self.perf_display_to_internal = {"Fast": "fast", "Balanced": "balanced", "Accurate": "accurate"}
        self.perf_opt = ctk.CTkOptionMenu(mode_frame, values=list(self.perf_display_to_internal.keys()))
        self.perf_opt.set("Balanced")
        self.perf_opt.pack(side="left", padx=6)

        # CPU cores selector (before progress bar on the right)
        try:
            core_frame = ctk.CTkFrame(top)
            core_frame.grid(row=0, column=6, padx=8, sticky="e")
            ctk.CTkLabel(core_frame, text="Cores:").pack(side="left")
            values = [str(i) for i in range(1, int(self._max_cores) + 1)]
            self.core_opt = ctk.CTkOptionMenu(core_frame, values=values)
            default_cores = "1"
            try:
                default_cores = str(min(4, int(self._max_cores)))
            except Exception:
                pass
            self.core_opt.set(default_cores)
            self.core_opt.pack(side="left", padx=4)
        except Exception:
            self.core_opt = None

        # Scenario title entry
        scen_frame = ctk.CTkFrame(top)
        scen_frame.grid(row=0, column=4, padx=8, sticky="w")
        ctk.CTkLabel(scen_frame, text="Scenario Title:").pack(side="left")
        self.ent_scen = ctk.CTkEntry(scen_frame, width=200)
        self.ent_scen.pack(side="left", padx=6)
        self.ent_scen.insert(0, "Scenario 1")

        # Progress bar at far right
        self.progress = ctk.CTkProgressBar(top)
        self.progress.grid(row=0, column=7, sticky="ew", padx=6)
        self.progress.set(0)

        # Main split: left inputs, right
        body = ctk.CTkFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Scrollable left panel
        left = ctk.CTkScrollableFrame(body, width=420, height=720)
        left.grid(row=0, column=0, sticky="nsw")
        # Unified project folder selection (used for scanning TS1 and saving outputs)
        io_container = ctk.CTkFrame(left)
        io_container.pack(fill="x", padx=4, pady=(4, 6))
        row = ctk.CTkFrame(io_container)
        row.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(row, text="Project Folder:").pack(side="left")
        self.ent_folder = ctk.CTkEntry(row, width=300)
        self.ent_folder.pack(side="left", padx=6)
        # Live validation + Enter to scan
        try:
            self.ent_folder.bind("<KeyRelease>", lambda _e: self._validate_folder_status())
            self.ent_folder.bind("<FocusOut>", lambda _e: self._validate_folder_status())
            self.ent_folder.bind("<Return>", lambda _e: self._load_ts1_from_folder())
        except Exception:
            pass
        ctk.CTkButton(row, text="Browse", width=70, command=self._browse_folder).pack(side="left")
        ctk.CTkButton(row, text="Load .ts1", width=80, command=self._load_ts1_from_folder).pack(side="left", padx=(6, 0))
        # Inline status (exists/writable)
        self.lbl_folder_status = ctk.CTkLabel(io_container, text="", text_color="#999999")
        self.lbl_folder_status.pack(anchor="w", padx=2, pady=(2, 0))

        ctk.CTkLabel(left, text="TS1 Files").pack(anchor="w")
        self.ts1_list = tk.Listbox(left, selectmode=tk.SINGLE, width=50, height=12)
        self.ts1_list.pack(padx=4, pady=4)
        self.btn_remove = ctk.CTkButton(left, text="Remove Selected", command=self._remove_selected)
        self.btn_remove.pack(padx=4, pady=4)
        try:
            # Handy shortcuts
            self.bind("<Control-r>", lambda _e: self._run_all())
            self.ts1_list.bind("<Delete>", lambda _e: self._remove_selected())
            self.ts1_list.bind("<Double-1>", self._open_ts1_in_explorer)
        except Exception:
            pass

        # Basin geometry inputs with tooltips
        params = ctk.CTkFrame(left)
        params.pack(fill="x", padx=4, pady=8)
        header_geo = ctk.CTkFrame(params)
        header_geo.pack(fill="x")
        geo_lbl = ctk.CTkLabel(header_geo, text="Basin Geometry")
        geo_lbl.pack(side="left", anchor="w")
        self._attach_info_balloon(geo_lbl, "Geometry used to build LAKTAB and the refined grid.\nLength/Width are floor dimensions; Max Depth is working depth above the floor;\nSide Slope is H:V (e.g., 3 = 3H:1V); Floor Elev is basin floor elevation (m AHD).")
        self.preview_enabled = tk.BooleanVar(value=True)
        toggle = ctk.CTkCheckBox(header_geo, text="Visualize live", variable=self.preview_enabled)
        toggle.pack(side="right")
        refresh_btn = ctk.CTkButton(header_geo, text="Refresh", width=80, command=self._refresh_previews)
        refresh_btn.pack(side="right", padx=6)
        self._make_labeled_entry(params, "Length (m)", "Plan length of basin floor (m)")
        self.ent_len = self._last_entry; self.ent_len.insert(0, "50")
        self._make_labeled_entry(params, "Width (m)", "Plan width of basin floor (m)")
        self.ent_wid = self._last_entry; self.ent_wid.insert(0, "50")
        self._make_labeled_entry(params, "Max Depth (m)", "Maximum operating water depth above basin floor (m)")
        self.ent_dep = self._last_entry; self.ent_dep.insert(0, "2.0")
        self._make_labeled_entry(params, "Side Slope (H:V)", "Horizontal:Vertical side slope (e.g., 2 = 2H:1V)")
        self.ent_slope = self._last_entry; self.ent_slope.insert(0, "2.0")
        self._make_labeled_entry(params, "Floor Elev (m AHD)", "Basin floor elevation (m AHD)")
        self.ent_floor = self._last_entry; self.ent_floor.insert(0, "5.0")
        ctk.CTkLabel(params, text="").pack(pady=2)

        # Infiltration
        infil = ctk.CTkFrame(left)
        infil.pack(fill="x", padx=4, pady=8)
        header_inf = ctk.CTkFrame(infil)
        header_inf.pack(fill="x")
        inf_lbl = ctk.CTkLabel(header_inf, text="Infiltration")
        inf_lbl.pack(side="left", anchor="w")
        self._attach_info_balloon(inf_lbl, "Infiltration parameters for the lakebed and (optionally) banks.\nBed thickness and K determine vertical leakance (K/thickness).\nBank K applies only when mode = Full infiltration.")
        self._make_labeled_entry(infil, "Bed Thickness (m)", "Lakebed sealing/soil thickness (m)")
        self.ent_bed_thk = self._last_entry; self.ent_bed_thk.insert(0, "0.5")
        self._make_labeled_entry(infil, "Bed K (m/day)", "Hydraulic conductivity of lakebed (m/day)")
        self.ent_bed_k = self._last_entry; self.ent_bed_k.insert(0, "5.0")
        self._make_labeled_entry(infil, "Bank K (m/day, optional)", "Horizontal bank conductivity for side seepage (m/day); leave blank to use bed K")
        self.ent_side_k = self._last_entry; self.ent_side_k.insert(0, "")
        ctk.CTkLabel(infil, text="").pack(pady=2)

        # Aquifer
        aqu = ctk.CTkFrame(left)
        aqu.pack(fill="x", padx=4, pady=8)
        header_aqu = ctk.CTkFrame(aqu)
        header_aqu.pack(fill="x")
        aqu_lbl = ctk.CTkLabel(header_aqu, text="Aquifer")
        aqu_lbl.pack(side="left", anchor="w")
        self._attach_info_balloon(
            aqu_lbl,
            "Bulk aquifer parameters controlling drainage.\nSoil K is horizontal conductivity (m/day). Sy is specific yield (0-0.3 typical).\nGroundwater Level is the initial water table elevation (m AHD).\nBottom of Aquifer sets the model base elevation. Overall K (optional) sets both horizontal and vertical K for all layers."
        )
        self._make_labeled_entry(aqu, "Soil K (m/day)", "Horizontal hydraulic conductivity of the aquifer (m/day)")
        self.ent_soil_k = self._last_entry; self.ent_soil_k.insert(0, "20.0")
        self._make_labeled_entry(aqu, "Sy (–)", "Specific yield (drainable porosity), dimensionless")
        self.ent_sy = self._last_entry; self.ent_sy.insert(0, "0.05")
        self._make_labeled_entry(aqu, "Groundwater Level (m AHD)", "Initial water table elevation for the model domain")
        self.ent_gw = self._last_entry; self.ent_gw.insert(0, "4.0")
        self._make_labeled_entry(aqu, "Bottom of Aquifer (m AHD)", "Base elevation of the model (bottom of aquifer). The grid will be scaled to this base.")
        self.ent_bot = self._last_entry; self.ent_bot.insert(0, "-65.0")
        self._make_labeled_entry(aqu, "Overall K (m/day, optional)", "If set, this K value is applied to both horizontal and vertical hydraulic conductivity for all layers.")
        self.ent_overall_k = self._last_entry; self.ent_overall_k.insert(0, "")

        # Right side: tabbed view (Preview, Results)
        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        tabs = ctk.CTkTabview(right)
        tabs.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tab_preview = tabs.add("Preview")
        self.tab_results = tabs.add("Results")

        self.tab_preview.grid_columnconfigure((0, 1), weight=1)
        self.tab_preview.grid_rowconfigure((0,), weight=1)

        frame_x = ctk.CTkFrame(self.tab_preview)
        frame_x.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        frame_x.grid_rowconfigure(0, weight=1)
        frame_x.grid_columnconfigure(0, weight=1)
        # Removed header label; image fills the frame
        self.preview_x = ctk.CTkLabel(frame_x, text="")
        self.preview_x.grid(row=0, column=0, sticky="nsew")

        frame_y = ctk.CTkFrame(self.tab_preview)
        frame_y.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        frame_y.grid_rowconfigure(0, weight=1)
        frame_y.grid_columnconfigure(0, weight=1)
        # Removed header label; image fills the frame
        self.preview_y = ctk.CTkLabel(frame_y, text="")
        self.preview_y.grid(row=0, column=0, sticky="nsew")

        # Basin diagram schematic removed per request

        summary = ctk.CTkFrame(self.tab_results)
        summary.pack(fill="x", expand=False, padx=6, pady=(6, 0))
        summary.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(summary, text="Results", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ctk.CTkLabel(summary, text="TS1:").grid(row=1, column=0, sticky="w")
        self.lbl_ts1 = ctk.CTkLabel(summary, text="-")
        self.lbl_ts1.grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(summary, text="Peak Stage (m):").grid(row=2, column=0, sticky="w")
        self.lbl_peak = ctk.CTkLabel(summary, text="-")
        self.lbl_peak.grid(row=2, column=1, sticky="w")
        ctk.CTkLabel(summary, text="Peak Time (days):").grid(row=3, column=0, sticky="w")
        self.lbl_peakt = ctk.CTkLabel(summary, text="-")
        self.lbl_peakt.grid(row=3, column=1, sticky="w")
        ctk.CTkLabel(summary, text="Detention (hr):").grid(row=4, column=0, sticky="w")
        self.lbl_det = ctk.CTkLabel(summary, text="-")
        self.lbl_det.grid(row=4, column=1, sticky="w")
        ctk.CTkLabel(summary, text="Total Inflow (m³):").grid(row=5, column=0, sticky="w")
        self.lbl_vol = ctk.CTkLabel(summary, text="-")
        self.lbl_vol.grid(row=5, column=1, sticky="w")
        self.btn_open = ctk.CTkButton(summary, text="Open Output Folder", command=self._open_output)
        self.btn_open.grid(row=1, column=2, rowspan=2, padx=6, sticky="e")
        self.lbl_badge = ctk.CTkLabel(summary, text="", text_color="#d9534f")
        self.lbl_badge.grid(row=0, column=2, sticky="e")

        self.lbl_max_summary = ctk.CTkLabel(self.tab_results, text="", justify="left")
        self.lbl_max_summary.pack(fill="x", padx=6, pady=(4, 6))

        self.preview_hint = ctk.CTkLabel(self.tab_preview, text="")
        self.preview_hint.grid_remove()

        self._ensure_results_controls()

        self.console = tk.Text(self, wrap="word")
        self.console.configure(height=20, width=100)
        self._log_popup = None
        self._log_mirror = None

        self._preview_job = None
        self._preview_last_ts = 0.0
        for ent in (self.ent_len, self.ent_wid, self.ent_dep, self.ent_slope, self.ent_floor,
                    self.ent_soil_k, self.ent_sy, self.ent_gw, self.ent_bot, self.ent_overall_k,
                    self.ent_bed_thk, self.ent_bed_k, self.ent_side_k):
            try:
                ent.bind("<KeyRelease>", self._schedule_preview_refresh)
                ent.bind("<FocusOut>", self._schedule_preview_refresh)
            except Exception:
                pass
        self.after(100, self._refresh_previews)

        self._busy = False
        self._busy_tick_id = None

    def _set_logo_image(self, desired_height: int = 36):
        """Load the app logo from logo/logo_background.svg, convert to PNG if needed, and set on the top bar.
        Falls back to a PNG in the logo folder if SVG conversion isn't available."""
        try:
            from PIL import Image
            import io
            base_dir = Path(__file__).parents[2]
            # Prefer high-contrast black logo
            svg_path = base_dir / 'logo' / 'logo_black.svg'
            img_obj = None
            if svg_path.exists():
                try:
                    import cairosvg  # type: ignore
                    png_bytes = cairosvg.svg2png(url=str(svg_path), output_height=desired_height)
                    img_obj = Image.open(io.BytesIO(png_bytes))
                except Exception:
                    img_obj = None
            if img_obj is None:
                # Fallback to a PNG asset in the logo folder
                png_candidates = [
                    base_dir / 'logo' / 'logo_black.png',
                    base_dir / 'logo' / 'logo_background.svg',  # render if cairosvg available later
                    base_dir / 'logo' / 'logo_background.png',
                    base_dir / 'logo' / 'transparent_logo.png',
                    base_dir / 'logo' / 'wmark_logo_black.png',
                ]
                for p in png_candidates:
                    if p.exists():
                        try:
                            if p.suffix.lower() == '.svg':
                                try:
                                    import cairosvg  # type: ignore
                                    png_bytes = cairosvg.svg2png(url=str(p), output_height=desired_height)
                                    img_obj = Image.open(io.BytesIO(png_bytes))
                                except Exception:
                                    img_obj = None
                            else:
                                img_obj = Image.open(p)
                        except Exception:
                            img_obj = None
                        if img_obj is not None:
                            break
            if img_obj is None:
                return
            # Scale keeping aspect ratio to desired height
            aspect = img_obj.width / max(1, img_obj.height)
            w = int(desired_height * aspect)
            h = int(desired_height)
            img_resized = img_obj.resize((max(1, w), max(1, h)))
            # Prepare a CTkImage (kept for potential future use), but do not
            # attach it to the title label—we use text there now.
            cimg = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(w, h))
            self._logo_img = cimg
            # Also try to set window icon for titlebar/taskbar
            try:
                from tkinter import PhotoImage
                bio = io.BytesIO()
                img_resized.save(bio, format='PNG')
                bio.seek(0)
                icon = PhotoImage(data=bio.read())
                # Works on many platforms
                try:
                    self.iconphoto(True, icon)
                except Exception:
                    pass
            except Exception:
                pass
            # On Windows, iconbitmap with a .ico file is most reliable; create a temp .ico
            try:
                import tempfile
                tmp_dir = Path(tempfile.gettempdir()) / 'basim_tmp'
                tmp_dir.mkdir(parents=True, exist_ok=True)
                ico_path = tmp_dir / 'basim_app.ico'
                # Save multiple sizes for crisp scaling
                sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]
                # Convert to RGBA if needed
                pil_img = img_resized.convert('RGBA') if hasattr(img_resized, 'convert') else img_resized
                pil_img.save(ico_path, format='ICO', sizes=sizes)
                try:
                    self.iconbitmap(default=str(ico_path))
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _init_logging(self):
        """Initialize rotating file logging under user profile (~/.basim/logs)."""
        try:
            log_dir = Path.home() / ".basim" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "app.log"
            logger = logging.getLogger("basim")
            logger.setLevel(logging.INFO)
            # Avoid duplicate handlers if reinitialized
            if not any(isinstance(h, RotatingFileHandler) and getattr(h, 'baseFilename', '').endswith('app.log') for h in logger.handlers):
                handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
                fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
                handler.setFormatter(fmt)
                logger.addHandler(handler)
            self._logger = logger
            logger.info("Logging initialized")
        except Exception:
            # Silent fallback; GUI console will still work
            self._logger = None

    def _make_labeled_entry(self, parent, label, tooltip):
        """Build a labeled entry row with an info tooltip; stores entry in self._last_entry."""
        row = ctk.CTkFrame(parent)
        row.pack(fill="x", pady=2)
        header = ctk.CTkFrame(row)
        header.pack(fill="x")
        lbl = ctk.CTkLabel(header, text=label)
        lbl.pack(side="left", anchor="w")
        self._attach_info_balloon(lbl, tooltip)
        ent = ctk.CTkEntry(row)
        ent.pack(fill="x", pady=2)
        self._last_entry = ent

    def _show_log_popup(self):
        if self._log_popup and tk.Toplevel.winfo_exists(self._log_popup):
            try:
                self._log_popup.lift(); self._log_popup.focus_force()
            except Exception:
                pass
            return
        win = tk.Toplevel(self)
        win.title("Run Log")
        win.geometry("900x400")
        self._log_popup = win
        frm = ctk.CTkFrame(win)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word")
        txt.pack(fill="both", expand=True)
        # seed with current buffer
        try:
            txt.insert("1.0", self.console.get("1.0", tk.END))
        except Exception:
            pass
        # simple mirroring: when we append to console, also to popup
        self._log_mirror = txt

    def _attach_info_balloon(self, widget, text: str):
        """Attach a hover info tooltip next to the given widget."""
        parent = widget.master
        info_lbl = ctk.CTkLabel(parent, text="ⓘ", width=16, text_color="#3A7EBF")
        info_lbl.pack(side="left", padx=4)
        tip = None

        def show_tip(_e=None):
            nonlocal tip
            if tip is not None:
                return
            tip = tk.Toplevel(self)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            # Position near the info label
            x = info_lbl.winfo_rootx() + 12
            y = info_lbl.winfo_rooty() + 18
            tip.wm_geometry(f"+{x}+{y}")
            frm = tk.Frame(tip, bg="#FFFFE0", bd=1, relief="solid")
            frm.pack()
            msg = tk.Label(frm, text=text, bg="#FFFFE0", justify="left", padx=6, pady=4)
            msg.pack()

        def hide_tip(_e=None):
            nonlocal tip
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass
                tip = None

        info_lbl.bind("<Enter>", show_tip)
        info_lbl.bind("<Leave>", hide_tip)
        widget.bind("<Enter>", show_tip)
        widget.bind("<Leave>", hide_tip)

    def _reset_state(self):
        self.ts1_files = []
        self._worker = None
        self._ts1_col_choice = None  # 0-based index into data columns as per inspector
        # TS1 statuses and results mapping
        self._ts1_status = {}  # path -> 'idle'|'running'|'done'
        self._results_by_ts1 = {}  # path -> outdir
        # Cross-run summaries
        self._run_summaries = {}

    def _get_float_entry(self, entry: ctk.CTkEntry, default: float) -> float:
        """Safely parse a float from a CTk entry; fall back to default on blanks or errors."""
        try:
            s = entry.get().strip()
            return float(s) if s != "" else float(default)
        except Exception:
            return float(default)

    def _get_optional_float(self, entry: ctk.CTkEntry):
        """Parse a float from entry; return None if blank or invalid."""
        try:
            s = entry.get().strip()
            if s == "":
                return None
            return float(s)
        except Exception:
            return None

    def _prefs_path(self) -> Path:
        try:
            base = Path.home() / ".basim"
            base.mkdir(parents=True, exist_ok=True)
            return base / "prefs.json"
        except Exception:
            # fallback to cwd
            return Path("prefs.json")

    def _load_prefs(self):
        p = self._prefs_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            folder = data.get("project_folder", "")
            if folder and self.ent_folder is not None:
                self.ent_folder.delete(0, tk.END)
                self.ent_folder.insert(0, folder)
            # Restore Performance mode if available
            try:
                perf_mode = str(data.get("perf_mode", "Balanced"))
                if hasattr(self, 'perf_opt') and perf_mode in getattr(self, 'perf_display_to_internal', {}).keys():
                    self.perf_opt.set(perf_mode)
            except Exception:
                pass
        except Exception:
            pass

    def _save_prefs(self):
        try:
            folder = (self.ent_folder.get().strip() if self.ent_folder is not None else "")
        except Exception:
            folder = ""
        try:
            perf_mode = None
            try:
                perf_mode = (self.perf_opt.get() if hasattr(self, 'perf_opt') and self.perf_opt is not None else None)
            except Exception:
                perf_mode = None
            data = {"project_folder": folder}
            if perf_mode:
                data["perf_mode"] = perf_mode
            self._prefs_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _validate_folder_status(self):
        if self.lbl_folder_status is None:
            return
        txt = (self.ent_folder.get().strip() if self.ent_folder is not None else "")
        if not txt:
            self.lbl_folder_status.configure(text="No folder selected.", text_color="#999999")
            return
        if not os.path.isdir(txt):
            self.lbl_folder_status.configure(text="Folder does not exist.", text_color="#d9534f")
            return
        # Writable check: try to create a temp dir or file
        ok_write = True
        try:
            test = Path(txt) / ".basim_write_test.tmp"
            with open(test, "w") as fp:
                fp.write("ok")
            test.unlink(missing_ok=True)
        except Exception:
            ok_write = False
        if ok_write:
            self.lbl_folder_status.configure(text="Folder found and writable.", text_color="#3c763d")
        else:
            self.lbl_folder_status.configure(text="Folder found but not writable.", text_color="#f0ad4e")

    def _add_ts1(self):
        from tkinter import filedialog
        # Prefer the current Project Folder as the starting point
        init_dir = None
        try:
            txt = (self.ent_folder.get().strip() if self.ent_folder is not None else "")
            init_dir = txt if (txt and os.path.isdir(txt)) else None
        except Exception:
            init_dir = None
        paths = filedialog.askopenfilenames(
            title="Select TS1 files",
            filetypes=[("TS1 Files", "*.ts1"), ("All Files", "*.*")],
            initialdir=init_dir or os.getcwd(),
        )
        added = False
        for p in paths:
            if p not in self.ts1_files:
                self.ts1_files.append(p)
                self._ts1_status[p] = 'idle'
                added = True
        self._refresh_ts1_list()
        # If a TS1 present, inspect columns and maybe prompt
        try:
            if self.ts1_files:
                self._prepare_ts1_column_choice(self.ts1_files[0])
        except Exception as e:
            self._log(f"TS1 inspection warning: {e}\n")

    def _remove_selected(self):
        sel = self.ts1_list.curselection()
        if sel:
            idx = sel[0]
            # resolve base path (strip status prefix if any)
            disp = self.ts1_list.get(idx)
            path = self._undecorate_ts1_text(disp)
            self.ts1_files = [p for p in self.ts1_files if p != path]
            self._ts1_status.pop(path, None)
            self._results_by_ts1.pop(path, None)
            self._refresh_ts1_list()
            self._update_results_runs()

    def _decorate_ts1_text(self, path: str) -> str:
        st = self._ts1_status.get(path, 'idle')
        prefix = '  '
        if st == 'running':
            prefix = '⏳ '
        elif st == 'done':
            prefix = '✅ '
        name = os.path.basename(path)
        return f"{prefix}{name}"

    def _undecorate_ts1_text(self, display_text: str) -> str:
        # Map displayed item back to full path by matching basename
        base = display_text.lstrip('⏳✅ ').strip()
        for p in self.ts1_files:
            if os.path.basename(p) == base or p == base:
                return p
        return base

    def _refresh_ts1_list(self):
        try:
            self.ts1_list.delete(0, tk.END)
            for p in self.ts1_files:
                self.ts1_list.insert(tk.END, self._decorate_ts1_text(p))
        except Exception:
            pass

    def _build_base_config(self) -> dict:
        """Capture current UI settings into a config dictionary (without run_id)."""
        mode_internal = self.mode_display_to_internal.get(self.mode_opt.get(), "vertical")
        # Map Performance selection to internal mode token
        try:
            perf_display = self.perf_opt.get()
            perf_mode_internal = self.perf_display_to_internal.get(perf_display, "balanced")
        except Exception:
            perf_mode_internal = "balanced"
        # Safely read custom base output directory from the unified folder selector
        outdir_txt = ""
        try:
            if getattr(self, 'ent_folder', None):
                outdir_txt = self.ent_folder.get().strip()
        except Exception:
            outdir_txt = ""
        cfg = {
            "model_tag": "gui",
            "scenario_title": (self.ent_scen.get().strip() or "Scenario 1"),
            "post_storm_days": 3.0,
            # honor custom output directory if provided
            "output_dir": (outdir_txt or None),
            "basin_geometry": {
                "length_floor": self._get_float_entry(self.ent_len, 50),
                "width_floor": self._get_float_entry(self.ent_wid, 50),
                "max_depth": self._get_float_entry(self.ent_dep, 2),
                "side_slope_hv": self._get_float_entry(self.ent_slope, 2),
                "floor_elev": self._get_float_entry(self.ent_floor, 5),
            },
            "aquifer": {
                "k_horizontal_mpd": self._get_float_entry(self.ent_soil_k, 20.0),
                "sy": self._get_float_entry(self.ent_sy, 0.05),
                "initial_head": self._get_float_entry(self.ent_gw, 5.0),
                "bottom_elev": self._get_optional_float(self.ent_bot),
            },
            "infiltration": {
                "mode": mode_internal,
                "bed_thickness_m": self._get_float_entry(self.ent_bed_thk, 0.5),
                "bed_k_mpd": self._get_float_entry(self.ent_bed_k, 5.0),
                "side_k_mpd": self._get_optional_float(self.ent_side_k),
            },
            # Performance profile used by backend to compute min_cell_size if no explicit override
            "perf": {
                "mode": perf_mode_internal
            },
        }
        # Apply Overall K if provided
        try:
            overall_k_txt = self.ent_overall_k.get().strip()
            if overall_k_txt != "":
                overall_k = float(overall_k_txt)
                cfg["aquifer"]["k_horizontal_mpd"] = overall_k
                cfg["aquifer"]["k_vertical_mpd"] = overall_k
            else:
                cfg["aquifer"].setdefault("k_vertical_mpd", cfg["aquifer"]["k_horizontal_mpd"])
        except Exception:
            cfg["aquifer"].setdefault("k_vertical_mpd", cfg["aquifer"]["k_horizontal_mpd"])
        return cfg

    def _browse_folder(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Select Project Folder (TS1 in, results out)")
        if path:
            try:
                self.ent_folder.delete(0, tk.END)
                self.ent_folder.insert(0, path)
            except Exception:
                pass
            try:
                self._validate_folder_status()
                self._save_prefs()
            except Exception:
                pass
            # Auto-scan after choosing folder
            try:
                self._load_ts1_from_folder()
            except Exception:
                pass

    def _load_ts1_from_folder(self):
        """Scan the chosen project folder (recursively) for .ts1 files and populate the list."""
        try:
            base = (self.ent_folder.get() or "").strip()
        except Exception:
            base = ""
        if not base or not os.path.isdir(base):
            self._log("Input folder not set or does not exist.\n")
            return
        try:
            found = []
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    if fn.lower().endswith('.ts1'):
                        found.append(os.path.join(root, fn))
            if not found:
                self._log("No .ts1 files found in the selected folder.\n")
                return
            # Deduplicate and sort (by name)
            found = sorted(set(found), key=lambda p: (os.path.basename(p).lower(), p.lower()))
            self.ts1_files = found
            # Reset statuses
            self._ts1_status = {p: 'idle' for p in self.ts1_files}
            self._results_by_ts1 = {p: self._results_by_ts1.get(p, '') for p in self.ts1_files}
            self._refresh_ts1_list()
            self._log(f"Loaded {len(found)} TS1 files from folder.\n")
            try:
                self._save_prefs()
            except Exception:
                pass
            # Pre-inspect first file to set column choice
            try:
                if self.ts1_files:
                    self._prepare_ts1_column_choice(self.ts1_files[0])
            except Exception:
                pass
        except Exception as e:
            self._log(f"Failed to scan input folder: {e}\n")

    def _run_all(self):
        if not self.ts1_files:
            self._log("No TS1 selected. Add a file first.")
            return
        # Pre-run geometry validation (frontend)
        warns = self._validate_geometry()
        if warns:
            msg = "Geometry may cause convergence issues:\n\n" + "\n".join(f"• {w}" for w in warns) + "\n\nContinue anyway?"
            if not messagebox.askyesno("Geometry Warning", msg):
                return
        # Check Project Folder status if provided
        folder_txt = ""
        try:
            folder_txt = (self.ent_folder.get().strip() if self.ent_folder is not None else "")
        except Exception:
            folder_txt = ""
        base_config = self._build_base_config()
        if folder_txt:
            exists = os.path.isdir(folder_txt)
            writable = False
            try:
                test = Path(folder_txt) / ".basim_write_test.tmp"
                with open(test, "w") as fp:
                    fp.write("ok")
                test.unlink(missing_ok=True)
                writable = True
            except Exception:
                writable = False
            if not exists or not writable:
                prompt = (
                    "The selected Project Folder is "
                    + ("missing" if not exists else "not writable")
                    + ".\n\nProceed using the default output location instead?"
                )
                if messagebox.askyesno("Folder Issue", prompt):
                    base_config["output_dir"] = None
                else:
                    return
        scenario_title = base_config.get("scenario_title", "Scenario 1").strip() or "Scenario 1"
        # If re-running same scenario, clear prior outputs
        if self._has_run_before and self._previous_scenario == scenario_title:
            try:
                self._clear_previous_results(scenario_title)
                self._log(f"Cleared previous results for '{scenario_title}'\n")
            except Exception as e:
                self._log(f"Could not clear previous results: {e}\n")
        # Run in background so UI stays responsive
        self._start_busy()
        # Determine number of cores requested
        try:
            num_cores = int(self.core_opt.get()) if self.core_opt is not None else 1
        except Exception:
            num_cores = 1
        # Switch to parallel if more than 1 core and multiple files
        if num_cores > 1 and len(self.ts1_files) > 1:
            threading.Thread(
                target=self._run_batch_parallel,
                args=(list(self.ts1_files), base_config, num_cores),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._run_batch_worker,
                args=(list(self.ts1_files), base_config),
                daemon=True,
            ).start()
        # Update button state to reflect re-run capability
        self._has_run_before = True
        self._previous_scenario = scenario_title
        self._update_run_button()

    def _run_batch_worker(self, ts1_list, base_config):
        import copy, uuid, time
        total = len(ts1_list)
        for idx, ts1 in enumerate(ts1_list, start=1):
            # Ensure column choice for this file
            try:
                self._prepare_ts1_column_choice(ts1)
            except Exception as e:
                self._enqueue_log(f"TS1 inspection error for {Path(ts1).name}: {e}\n")
                continue
            config = copy.deepcopy(base_config)
            config["run_id"] = str(uuid.uuid4())
            if self._ts1_col_choice is not None:
                config["ts1_column_index"] = int(self._ts1_col_choice)
            # Start progress polling tied to this run & file
            self.progress.set(0.01)
            self._enqueue_log(f"Running scenario ({idx}/{total}): {Path(ts1).name} ({config['infiltration']['mode']})\n")
            # Mark TS1 as running in UI
            self.after(0, lambda p=ts1: self._set_ts1_status(p, 'running'))
            progress_thread = threading.Thread(target=self._poll_progress, args=(config, ts1), daemon=True)
            progress_thread.start()
            try:
                ok, summary, outdir = run_phase3_step32_with_config(ts1, config)
                self._enqueue_log(json.dumps(summary, indent=2) + "\n")
                self._enqueue_log(f"Output: {outdir}\n")
                self.after(0, lambda v=(1.0 if ok else 0.0): self.progress.set(v))
                self.after(0, lambda s=summary, o=outdir: self._set_summary(s, o))
                # Mark done and record results mapping
                self._results_by_ts1[ts1] = outdir
                self.after(0, self._update_results_runs)
                self.after(0, lambda p=ts1: self._set_ts1_status(p, 'done'))
            except Exception as e:
                self._enqueue_log(f"Error running {Path(ts1).name}: {e}\n")
                self.after(0, lambda: self.progress.set(0.0))
                self.after(0, lambda p=ts1: self._set_ts1_status(p, 'idle'))
            # Tiny pause to allow file watchers to settle
            time.sleep(0.2)
        # done
        self.after(0, self._stop_busy)

    def _run_batch_parallel(self, ts1_list, base_config, num_workers: int):
        import copy, uuid, time
        total = len(ts1_list)
        done = 0
        # Prepare configs and ensure TS1 column choices are decided in main thread
        configs = []
        for ts1 in ts1_list:
            try:
                self._prepare_ts1_column_choice(ts1)
            except Exception as e:
                self._enqueue_log(f"TS1 inspection error for {Path(ts1).name}: {e}\n")
                continue
            cfg = copy.deepcopy(base_config)
            cfg["run_id"] = str(uuid.uuid4())
            if self._ts1_col_choice is not None:
                cfg["ts1_column_index"] = int(self._ts1_col_choice)
            configs.append((ts1, cfg))
        if not configs:
            self.after(0, self._stop_busy); return
        # Submit parallel tasks
        self._enqueue_log(f"Starting parallel run on {min(num_workers, len(configs))} cores...\n")
        try:
            with ProcessPoolExecutor(max_workers=num_workers) as ex:
                futures = {}
                for ts1, cfg in configs:
                    self.after(0, lambda p=ts1: self._set_ts1_status(p, 'running'))
                    fut = ex.submit(run_model_worker, ts1, cfg)
                    futures[fut] = ts1
                for fut in as_completed(futures):
                    ts1 = futures[fut]
                    try:
                        ok, summary, outdir = fut.result()
                    except Exception as e:
                        ok, summary, outdir = False, {"error": str(e), "ts1_file": ts1}, None
                    done += 1
                    frac = max(0.0, min(1.0, done / max(1, total)))
                    self.after(0, lambda v=frac: self.progress.set(v))
                    if ok:
                        self._enqueue_log(json.dumps(summary, indent=2) + "\n")
                        self._enqueue_log(f"Output: {outdir}\n")
                        self._results_by_ts1[ts1] = (str(outdir) if outdir else "")
                        self.after(0, self._update_results_runs)
                        self.after(0, lambda p=ts1: self._set_ts1_status(p, 'done'))
                        # Update summary widgets to last finished
                        self.after(0, lambda s=summary, o=outdir: self._set_summary(s, o))
                    else:
                        self._enqueue_log(f"Error running {Path(ts1).name}: {summary.get('error','Unknown error')}\n")
                        self.after(0, lambda: self.progress.set(frac))
                        self.after(0, lambda p=ts1: self._set_ts1_status(p, 'idle'))
        finally:
            self.after(0, self._stop_busy)

    def _clear_previous_results(self, scenario_title: str):
        """Delete ALL previous results for this scenario and reset UI state.

        Strategy:
        - Remove the entire scenario folder under .../model_output/phase3/step32/scenarios/<scenario_title>
          to ensure combined plots, meta files, spill flags, and per-run outputs are all cleared.
        - Recreate an empty folder structure with 'inputs' and 'outputs'.
        - Purge any cached mappings in the current session that point to the removed paths.
        """
        try:
            custom = ""
            try:
                if getattr(self, 'ent_folder', None):
                    custom = self.ent_folder.get().strip()
            except Exception:
                custom = ""
            base_out = Path(custom) if custom else (Path(__file__).parents[2] / 'model_output' / 'phase3' / 'step32' / 'scenarios')
            scen_dir = base_out / scenario_title
            # Remove entire scenario directory to ensure no stale files remain
            if scen_dir.exists():
                shutil.rmtree(scen_dir, ignore_errors=True)
            # Recreate clean structure
            (scen_dir / 'inputs').mkdir(parents=True, exist_ok=True)
            (scen_dir / 'outputs').mkdir(parents=True, exist_ok=True)

            # Also clear in-memory references for this scenario
            try:
                to_delete = []
                for ts1, outdir in list(self._results_by_ts1.items()):
                    try:
                        if outdir and Path(outdir).resolve().is_relative_to((scen_dir / 'outputs').resolve()):
                            to_delete.append(ts1)
                    except Exception:
                        # Fallback: string prefix check
                        if outdir and str(outdir).replace("\\", "/").startswith(str((scen_dir / 'outputs')).replace("\\", "/")):
                            to_delete.append(ts1)
                for ts1 in to_delete:
                    self._results_by_ts1.pop(ts1, None)
                # Remove summaries for deleted runs
                for ts1 in to_delete:
                    name = os.path.basename(ts1)
                    self._run_summaries.pop(name, None)
                # Refresh results UI
                self._update_results_runs()
                # Clear images area
                if hasattr(self, 'results_images_frame'):
                    for w in list(self.results_images_frame.winfo_children()):
                        try:
                            w.destroy()
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    def _update_run_button(self):
        try:
            if getattr(self, '_has_run_before', False):
                self.btn_run.configure(text="Clear Results and Re-Run")
            else:
                self.btn_run.configure(text="Run")
        except Exception:
            pass

    def _set_ts1_status(self, path: str, status: str):
        try:
            self._ts1_status[path] = status
            self._refresh_ts1_list()
        except Exception:
            pass

    def _start_busy(self):
        if self._busy:
            return
        self._busy = True
        # Disable key controls
        try:
            self.btn_run.configure(state="disabled")
            self.btn_add_ts1.configure(state="disabled")
        except Exception:
            pass
        # Set cursor and animate progress indeterminate
        try:
            self.configure(cursor="watch")
        except Exception:
            pass
        self.progress.set(0)
        self._busy_anim()

    def _busy_anim(self):
        if not self._busy:
            return
        try:
            # simple marquee: increment by 0.05 and wrap
            val = getattr(self, "_busy_val", 0.0)
            val = (val + 0.05) % 1.0
            self._busy_val = val
            self.progress.set(val)
        except Exception:
            pass
        self._busy_tick_id = self.after(120, self._busy_anim)

    def _stop_busy(self):
        self._busy = False
        if self._busy_tick_id is not None:
            try:
                self.after_cancel(self._busy_tick_id)
            except Exception:
                pass
            self._busy_tick_id = None
        try:
            self.configure(cursor="")
        except Exception:
            pass
        try:
            self.btn_run.configure(state="normal")
            self.btn_add_ts1.configure(state="normal")
        except Exception:
            pass
        
    def _prepare_ts1_column_choice(self, ts1_path: str):
        """Inspect TS1 and ensure a column choice is set; prompt if multiple."""
        info = inspect_ts1_columns(ts1_path)
        data_cols = info.get("data_cols", [])
        # If exactly one, pick it
        if len(data_cols) == 1:
            self._ts1_col_choice = 0  # index among data columns for read_ts1_file preferred_column semantics
            return
        # If multiple, prompt user
        if len(data_cols) > 1:
            self._prompt_ts1_column_choice(info)
            return
        raise ValueError("No data columns found in TS1")

    def _prompt_ts1_column_choice(self, info: dict):
        """Modal dialog to choose which TS1 data column to use (no auto-sum)."""
        data_cols = info.get("data_cols", [])
        labels = info.get("labels", {})
        # Build pretty names like "[0] Cat1 (col 1)"
        items = []
        for idx, c in enumerate(data_cols):
            label = labels.get(c, f"col{c}")
            items.append(f"[{idx}] {label} (col {c})")

        dialog = ctk.CTkToplevel(self)
        dialog.title("Select TS1 Data Column")
        dialog.grab_set()
        dialog.geometry("420x260")
        ctk.CTkLabel(dialog, text="Select the flow column to use from the TS1 file:").pack(anchor="w", padx=10, pady=10)
        listbox = tk.Listbox(dialog, selectmode=tk.SINGLE, height=min(8, len(items)))
        for it in items:
            listbox.insert(tk.END, it)
        listbox.select_set(0)
        listbox.pack(fill="both", expand=True, padx=10, pady=6)

        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(fill="x", pady=6)

        def _confirm():
            sel = listbox.curselection()
            if not sel:
                return
            self._ts1_col_choice = int(sel[0])
            dialog.grab_release()
            dialog.destroy()

        def _cancel():
            # keep default 0
            self._ts1_col_choice = 0 if data_cols else None
            dialog.grab_release()
            dialog.destroy()

        ok_btn = ctk.CTkButton(btn_frame, text="Use Selected", command=_confirm)
        ok_btn.pack(side="right", padx=8)
        cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=_cancel)
        cancel_btn.pack(side="right")
        # Center over parent
        self.update_idletasks()
        w = dialog.winfo_width(); h = dialog.winfo_height()
        x = self.winfo_x() + (self.winfo_width()//2 - w//2)
        y = self.winfo_y() + (self.winfo_height()//2 - h//2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")
        dialog.wait_window()

    # _run_worker removed (unused) — batch worker/parallel paths are used instead.

    def _log(self, text: str):
        # direct (main thread only)
        self.console.insert(tk.END, text)
        self.console.see(tk.END)
        # mirror to popup if open
        try:
            if self._log_mirror is not None:
                self._log_mirror.insert(tk.END, text)
                self._log_mirror.see(tk.END)
        except Exception:
            pass
        # also write to rotating file logger (line by line to keep formatting)
        try:
            if self._logger is not None and text:
                for line in str(text).splitlines():
                    if line.strip():
                        self._logger.info(line)
        except Exception:
            pass

    def _enqueue_log(self, text: str):
        # schedule on main thread
        self.after(0, lambda t=text: self._log(t))

    def _poll_progress(self, config: dict, ts1_path: str):
        try:
            # Locate scenario output folder from config and ts1
            from pathlib import Path
            if not ts1_path:
                return
            base_out = Path(config.get('output_dir') or (Path(__file__).parents[2] / 'model_output' / 'phase3' / 'step32' / 'scenarios'))
            scen_title = (config.get('scenario_title') or 'Scenario 1').strip()
            # Shorten TS1 using same logic as backend (~s1 AEP, ~s2 duration, ~s3 TP) with fallback to first line
            def _short_ts1(name: str) -> str:
                import re
                from pathlib import Path as _Path
                def _extract_tokens(text: str):
                    s1 = s2 = s3 = None
                    t = text or ""
                    t_sp = re.sub(r"[_,]+", " ", t)
                    m_pct = re.search(r"\b(\d+)\s*%\b", t_sp, re.IGNORECASE)
                    m_aep_pct = re.search(r"\baep\s*(\d+)\s*%\b", t_sp, re.IGNORECASE)
                    m_pc = re.search(r"\b(\d+)\s*p(?:c|ct)\b", t_sp, re.IGNORECASE)
                    m_ey = re.search(r"\b(\d+)\s*ey\b", t_sp, re.IGNORECASE)
                    m_1inx = re.search(r"\b1\s*in\s*(\d+)\b", t_sp, re.IGNORECASE)
                    m_ari1 = re.search(r"\bari\s*(\d+)\s*(?:yr|year|years)?\b", t_sp, re.IGNORECASE)
                    m_ari2 = re.search(r"\b(\d+)\s*(?:yr|year|years)\s*ari\b", t_sp, re.IGNORECASE)
                    if m_pct:
                        s1 = f"{m_pct.group(1)}pct"
                    elif m_aep_pct:
                        s1 = f"{m_aep_pct.group(1)}pct"
                    elif m_pc:
                        s1 = f"{m_pc.group(1)}pct"
                    elif m_ey:
                        s1 = f"{m_ey.group(1)}EY"
                    elif m_1inx:
                        s1 = f"1in{m_1inx.group(1)}"
                    elif m_ari1:
                        s1 = f"1in{m_ari1.group(1)}"
                    elif m_ari2:
                        s1 = f"1in{m_ari2.group(1)}"
                    m_h_word = re.search(r"\b(\d+)\s*h(?:our|r|rs)?\b", t_sp, re.IGNORECASE)
                    m_m_word = re.search(r"\b(\d+)\s*m(?:in(?:ute)?s?)?\b", t_sp, re.IGNORECASE)
                    m_d_word = re.search(r"\b(\d+)\s*d(?:ay)?s?\b", t_sp, re.IGNORECASE)
                    m_h_compact = re.search(r"\b(\d+)h\b", t_sp, re.IGNORECASE)
                    m_m_compact = re.search(r"\b(\d+)m\b", t_sp, re.IGNORECASE)
                    m_d_compact = re.search(r"\b(\d+)d\b", t_sp, re.IGNORECASE)
                    if m_h_word:
                        s2 = f"{m_h_word.group(1)}h"
                    elif m_h_compact:
                        s2 = f"{m_h_compact.group(1)}h"
                    elif m_m_word:
                        s2 = f"{m_m_word.group(1)}m"
                    elif m_m_compact:
                        s2 = f"{m_m_compact.group(1)}m"
                    elif m_d_word:
                        s2 = f"{m_d_word.group(1)}d"
                    elif m_d_compact:
                        s2 = f"{m_d_compact.group(1)}d"
                    m_tp = re.search(r"\bTP\s*0*(\d+)\b", t_sp, re.IGNORECASE)
                    m_storm = re.search(r"\bstorm\s*0*(\d+)\b", t_sp, re.IGNORECASE)
                    if m_tp:
                        s3 = f"TP{int(m_tp.group(1))}"
                    elif m_storm:
                        s3 = f"TP{int(m_storm.group(1))}"
                    return s1, s2, s3
                p = _Path(name)
                stem = p.stem
                s1, s2, s3 = _extract_tokens(stem)
                if not (s1 and s2):
                    try:
                        with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                            for _ in range(10):
                                ln = f.readline()
                                if not ln:
                                    break
                                s1f, s2f, s3f = _extract_tokens(ln.strip())
                                s1 = s1 or s1f; s2 = s2 or s2f; s3 = s3 or s3f
                                if s1 and s2 and s3:
                                    break
                    except Exception:
                        pass
                if not s1:
                    try:
                        parts = [q for q in p.parts[-5:]]
                        for txt in reversed(parts):
                            s1f, _, s3f = _extract_tokens(txt)
                            if s1f:
                                s1 = s1f
                                if not s3 and s3f:
                                    s3 = s3f
                                break
                    except Exception:
                        pass
                parts = []
                if s1: parts.append(s1)
                if s2: parts.append(s2)
                if s3: parts.append(s3)
                short = "_".join(parts) if parts else stem
                short = re.sub(r"[^A-Za-z0-9_]+", "", short)
                return short[:40]
            sub = _short_ts1(ts1_path)
            model_dir = base_out / scen_title / 'outputs' / sub
            meta = model_dir / 'run_meta.json'
            import time, json
            last_total = 0
            expected_run = str(config.get('run_id',''))
            while True:
                if meta.exists():
                    try:
                        with open(meta, 'r') as fp:
                            data = json.load(fp)
                        # Ignore stale meta from previous runs
                        if expected_run and data.get('run_id') not in (expected_run,):
                            time.sleep(0.25)
                            continue
                        # Prefer step-based progress if available; fallback to periods
                        t_steps = int(data.get('total_steps') or 0)
                        c_steps = int(data.get('completed_steps') or 0)
                        if t_steps > 0:
                            total = t_steps
                            done = max(0, min(c_steps, t_steps))
                        else:
                            total = int(data.get('total_periods', 0))
                            cur_per = int(data.get('current_period', data.get('completed_periods', 0)))
                            done = min(cur_per, total) if total else int(data.get('completed_periods', 0))
                        state = data.get('state','building')
                        last_total = total or last_total
                        if last_total:
                            frac = max(0.0, min(1.0, done/last_total))
                            self.after(0, lambda v=frac: self.progress.set(v))
                            # lightweight textual progress for visibility (stress period based)
                            self._enqueue_log(f"Progress: {done}/{last_total} ({int(frac*100)}%)\r")
                        if state in ('saving','done'):
                            if state == 'saving':
                                self._enqueue_log('💾 Saving outputs...\n')
                            break
                    except Exception:
                        pass
                time.sleep(0.25)
        except Exception:
            pass

    def _set_summary(self, summary: dict, outdir: str):
        self._last_outdir = outdir
        self.lbl_ts1.configure(text=os.path.basename(summary.get("ts1_file", "-")))
        self.lbl_peak.configure(text=f"{summary.get('peak_stage_m', float('nan')):.3f}" if 'peak_stage_m' in summary else "-")
        self.lbl_peakt.configure(text=f"{summary.get('peak_time_days', float('nan')):.3f}" if 'peak_time_days' in summary else "-")
        self.lbl_det.configure(text=f"{summary.get('detention_time_hours', float('nan')):.2f}" if 'detention_time_hours' in summary else "-")
        self.lbl_vol.configure(text=f"{summary.get('inflow_total_m3', float('nan')):.1f}" if 'inflow_total_m3' in summary else "-")
        # Spill badge from summary or spill_warning.txt
        try:
            spilled = bool(summary.get('spill_detected'))
            if not spilled and outdir and os.path.isdir(outdir):
                sw = Path(outdir) / 'spill_warning.txt'
                spilled = sw.exists()
            self.lbl_badge.configure(text=("🌊 Spill — do not rely beyond crest" if spilled else ""))
        except Exception:
            self.lbl_badge.configure(text="")
        # Track for cross-run max summary
        try:
            ts1_name = os.path.basename(summary.get("ts1_file", "")) or "(unknown)"
            self._run_summaries[ts1_name] = summary
            self._update_max_summary()
        except Exception:
            pass
        # Backend no longer generates 3D snapshot; preview is handled by live basin diagram
        # Ensure Results run selector is available
        try:
            self._ensure_results_controls()
            # If this run belongs to a TS1 we know, preselect it
            for p, d in self._results_by_ts1.items():
                if d == outdir:
                    self.sel_run.set(os.path.basename(p))
                    self._on_select_run(os.path.basename(p))
                    break
        except Exception:
            pass

    def _update_max_summary(self):
        try:
            if not self._run_summaries:
                self.lbl_max_summary.configure(text="")
                return
            # Find max peak_stage_m across runs
            best_name = None
            best_val = None
            for name, summ in self._run_summaries.items():
                val = summ.get('peak_stage_m')
                try:
                    if val is None:
                        continue
                    val = float(val)
                except Exception:
                    continue
                if (best_val is None) or (val > best_val):
                    best_val = val
                    best_name = name
            if best_val is None:
                self.lbl_max_summary.configure(text="")
            else:
                txt = f"Max stage across runs: {best_val:.3f} m  —  {best_name}"
                self.lbl_max_summary.configure(text=txt)
        except Exception:
            pass

    def _ensure_results_controls(self):
        if getattr(self, '_results_ui_ready', False):
            return
        try:
            # Controls live inside Results tab, below summary grid
            container = ctk.CTkFrame(self.tab_results)
            container.pack(fill="both", expand=True, padx=6, pady=(6, 12))
            topbar = ctk.CTkFrame(container)
            topbar.pack(fill="x")
            ctk.CTkLabel(topbar, text="Run:").pack(side="left")
            self.sel_run = ctk.CTkOptionMenu(topbar, values=[], command=self._on_select_run)
            self.sel_run.set("(none)")
            self.sel_run.pack(side="left", padx=6)
            # Images area (scrollable) to show saved result PNGs
            self.results_images_frame = ctk.CTkScrollableFrame(container)
            self.results_images_frame.pack(fill="both", expand=True, padx=6, pady=6)
            self._results_imgs_refs = []  # keep CTkImage refs alive
            self._results_ui_ready = True
        except Exception:
            pass

    def _update_results_runs(self):
        try:
            self._ensure_results_controls()
            names = [os.path.basename(p) for p in self._results_by_ts1.keys()]
            if not names:
                self.sel_run.configure(values=["(none)"])
                self.sel_run.set("(none)")
                return
            self.sel_run.configure(values=names)
            if self.sel_run.get() not in names:
                self.sel_run.set(names[0])
                # Trigger initial render
                self._on_select_run(names[0])
        except Exception:
            pass

    def _on_select_run(self, display_name: str):
        # find ts1 path
        try:
            target = None
            for p in self._results_by_ts1.keys():
                if os.path.basename(p) == display_name:
                    target = p; break
            if not target:
                return
            outdir = self._results_by_ts1.get(target)
            if not outdir:
                return
            self._render_results_plot(target, outdir)
        except Exception:
            pass

    def _render_results_plot(self, ts1_path: str, outdir: str):
        """Load saved PNGs from the output directory and display them in the Results tab."""
        try:
            from pathlib import Path
            from PIL import Image
            self._ensure_results_controls()
            # Clear previous images
            try:
                for w in list(self.results_images_frame.winfo_children()):
                    w.destroy()
            except Exception:
                pass
            self._results_imgs_refs = []
            out = Path(outdir)
            # Spill banner if present
            try:
                sw = out / 'spill_warning.txt'
                if sw.exists():
                    txt = sw.read_text(errors='ignore').strip().splitlines()[0] if sw.stat().st_size > 0 else "Basin spill detected."
                    banner = ctk.CTkLabel(self.results_images_frame, text=f"🌊 {txt}", text_color="#d9534f")
                    banner.pack(fill='x', padx=4, pady=(6, 6))
            except Exception:
                pass
            # Prioritized list of plot files to show
            # Prefer scenario-level combined plot if present
            scen_combined = (Path(outdir).parent / 'combined_stages.png') if outdir else None
            plot_files = []
            if scen_combined and scen_combined.exists():
                plot_files.append(scen_combined)
            plot_files += [
                out / 'effective_infiltration_rate.png',
                out / 'inflow_stage_overlay.png',
                out / 'stage_timeseries.png',
                out / 'max_head_contours.png',
            ]
            found = [p for p in plot_files if p.exists()]
            if not found:
                # Also look for any pngs in folder as fallback
                found = sorted([p for p in out.glob('*.png') if p.name.lower().endswith('.png')])
            if not found:
                # Show a friendly message
                msg = ctk.CTkLabel(self.results_images_frame, text="No result plots found for this run yet.")
                msg.pack(pady=12)
                return
            # Display images stacked vertically
            for p in found:
                try:
                    img = Image.open(p)
                    # Scale to fit area
                    w = max(420, min(1000, int(self.winfo_width() * 0.7)))
                    aspect = img.height / max(1, img.width)
                    h = int(w * aspect)
                    img = img.resize((w, h))
                    cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
                    title = ctk.CTkLabel(self.results_images_frame, text=p.stem.replace('_', ' ').title(), font=("Arial", 12, "bold"))
                    title.pack(anchor='w', padx=4, pady=(10, 4))
                    lbl = ctk.CTkLabel(self.results_images_frame, image=cimg, text="")
                    lbl.pack(fill='x', padx=4, pady=(0, 10))
                    self._results_imgs_refs.append(cimg)
                except Exception:
                    continue
        except Exception:
            pass

    def _validate_geometry(self) -> list:
        """Use backend validator on current UI values and return warnings list."""
        try:
            from types import SimpleNamespace
            length = self._get_float_entry(self.ent_len, 50)
            width = self._get_float_entry(self.ent_wid, 50)
            depth = self._get_float_entry(self.ent_dep, 2)
            slope = self._get_float_entry(self.ent_slope, 2)
            floor = self._get_float_entry(self.ent_floor, 5)
            gw = self._get_float_entry(self.ent_gw, (floor - 1.0))
            bot_txt = self.ent_bot.get().strip()
            bottom = (self._get_float_entry(self.ent_bot, float("nan")) if bot_txt != "" else None)
            basin_geom = SimpleNamespace(
                length_floor=length,
                width_floor=width,
                max_depth=depth,
                side_slope_hv=slope,
                floor_elev=floor,
            )
            warns = validate_basin_configuration(basin_geom, gw, bottom)
            return warns or []
        except Exception:
            return []

    def _schedule_preview_refresh(self, _e=None):
        # debounce rapid edits
        try:
            if not getattr(self, 'preview_enabled', None) or not self.preview_enabled.get():
                return
            if self._preview_job is not None:
                self.after_cancel(self._preview_job)
        except Exception:
            pass
        self._preview_job = self.after(400, self._refresh_previews)

    def _refresh_previews(self):
        # Respect live toggle
        try:
            if not getattr(self, 'preview_enabled', None) or not self.preview_enabled.get():
                return
        except Exception:
            pass
        # Throttle heavy rendering
        try:
            import time as _time
            last = getattr(self, '_preview_last_ts', 0.0)
            if _time.time() - float(last) < 0.8:
                try:
                    if self._preview_job is not None:
                        self.after_cancel(self._preview_job)
                except Exception:
                    pass
                self._preview_job = self.after(400, self._refresh_previews)
                return
            self._preview_last_ts = _time.time()
        except Exception:
            pass
        # Build a simple geometry from current inputs
        try:
            length = self._get_float_entry(self.ent_len, 50)
            width = self._get_float_entry(self.ent_wid, 50)
            depth = self._get_float_entry(self.ent_dep, 2)
            slope = self._get_float_entry(self.ent_slope, 2)
            z_floor = self._get_float_entry(self.ent_floor, 5)
            z_gw = self._get_float_entry(self.ent_gw, z_floor)
            bed_thk = self._get_float_entry(self.ent_bed_thk, 0.0)
            bot_txt = self.ent_bot.get().strip()
            z_bottom = (self._get_float_entry(self.ent_bot, float("nan")) if bot_txt != "" else None)
        except Exception:
            return

        # Render to temp files
        try:
            import tempfile
            from pathlib import Path
            from src.utils.preview_plots import SimpleGeom, render_cross_section_x, render_cross_section_y
            from PIL import Image

            tdir = Path(tempfile.gettempdir()) / "basim_preview"
            tdir.mkdir(parents=True, exist_ok=True)
            pngx = tdir / "preview_x.png"
            pngy = tdir / "preview_y.png"

            sgeom = SimpleGeom(
                length_floor=length, width_floor=width, max_depth=depth,
                side_slope_hv=slope, floor_elev=z_floor,
                bottom_elev=z_bottom, bed_thickness=bed_thk, gw_level=z_gw,
            )
            try:
                render_cross_section_x(sgeom, str(pngx))
                render_cross_section_y(sgeom, str(pngy))
            except Exception:
                pass

            # Load images
            def _set_img(lbl, path_attr:str, png_path):
                try:
                    if png_path.exists():
                        # Avoid reloading identical content repeatedly
                        key = (path_attr, png_path.stat().st_mtime_ns)
                        if getattr(self, '_prev_img_key', None) == key:
                            return
                        img = Image.open(png_path)
                        # scale to use more of the available width
                        w = max(450, min(1000, int(self.winfo_width() * 0.48)))
                        aspect = img.height / max(1, img.width)
                        h = int(w * aspect)
                        img = img.resize((w, h))
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
                        setattr(self, path_attr, ctk_img)
                        lbl.configure(image=ctk_img, text="")
                        self._prev_img_key = key
                except Exception:
                    pass

            _set_img(self.preview_x, "_ctk_prevx", pngx)
            _set_img(self.preview_y, "_ctk_prevy", pngy)
        except Exception:
            pass

    def _open_output(self):
        if hasattr(self, "_last_outdir") and self._last_outdir and os.path.isdir(self._last_outdir):
            try:
                os.startfile(self._last_outdir)  # Windows
            except Exception:
                pass

    def _open_ts1_in_explorer(self, _e=None):
        """Open the selected TS1's containing folder in Explorer."""
        try:
            sel = self.ts1_list.curselection()
            if not sel:
                return
            disp = self.ts1_list.get(sel[0])
            path = self._undecorate_ts1_text(disp)
            if path and os.path.exists(path):
                os.startfile(os.path.dirname(path))
        except Exception:
            pass

    def on_close(self):
        """Persist simple prefs and close the app."""
        try:
            self._save_prefs()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


class BaSIMApp(BaseBaSIMApp):
    def __init__(self):
        # Initialize the CTk root without running Base UI initializer
        ctk.CTk.__init__(self)
        # Install global error reporting early
        try:
            error_reporter.install(app_window=self, logger=getattr(self, '_logger', None))
        except Exception:
            pass
        # EULA gating before licensing
        if not self._ensure_eula_accepted():
            return
        # License gating before heavy UI init
        self.license_mgr = LicenseManager()
        # Seed privileged perpetual license if applicable
        try:
            self.license_mgr.ensure_privileged_seed()
        except Exception:
            pass
        if not self._check_license():
            self._show_license_dialog()
        else:
            self._initialize_main_ui()

    def _ensure_eula_accepted(self) -> bool:
        """Show EULA on first run; store acceptance under ~/.basim/eula_accept.json."""
        try:
            store = Path.home() / ".basim" / "eula_accept.json"
            store.parent.mkdir(parents=True, exist_ok=True)
            if store.exists():
                return True
            # Load EULA text
            try:
                eula_path = Path(__file__).parents[2] / 'src' / 'legal' / 'eula.txt'
                text = eula_path.read_text(encoding='utf-8') if eula_path.exists() else ""
            except Exception:
                text = ""
            # Build modal dialog
            dlg = ctk.CTkToplevel(self)
            dlg.title("BaSIM - End-User License Agreement")
            dlg.geometry("700x500")
            dlg.grab_set(); dlg.focus_force()
            # Center
            dlg.update_idletasks()
            w = dlg.winfo_width(); h = dlg.winfo_height()
            x = (dlg.winfo_screenwidth() // 2) - (w // 2)
            y = (dlg.winfo_screenheight() // 2) - (h // 2)
            dlg.geometry(f"{w}x{h}+{x}+{y}")
            ctk.CTkLabel(dlg, text="End-User License Agreement", font=("Arial", 18, "bold")).pack(pady=8)
            txt = ctk.CTkTextbox(dlg, width=660, height=360)
            txt.pack(padx=10, pady=6, fill='both', expand=True)
            try:
                txt.insert('1.0', text or "BaSIM EULA not found. Continue only if you agree to the terms.")
            except Exception:
                pass
            chk_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(dlg, text="I have read and agree to the EULA", variable=chk_var).pack(pady=6)
            btn_row = ctk.CTkFrame(dlg); btn_row.pack(pady=8)

            accepted = {'ok': False}
            def _agree():
                if not chk_var.get():
                    return
                try:
                    import json, time
                    store.write_text(json.dumps({"accepted": True, "ts": time.time()}), encoding='utf-8')
                except Exception:
                    pass
                accepted['ok'] = True
                dlg.destroy()

            def _decline():
                accepted['ok'] = False
                dlg.destroy()
                try:
                    self.destroy()
                except Exception:
                    pass

            ctk.CTkButton(btn_row, text="I Agree", command=_agree, width=120).pack(side='left', padx=6)
            ctk.CTkButton(btn_row, text="Decline", command=_decline, width=120, fg_color="#6c757d").pack(side='left', padx=6)
            dlg.protocol("WM_DELETE_WINDOW", _decline)
            dlg.wait_window()
            return bool(accepted['ok'])
        except Exception:
            # Fail-open: if anything unexpected occurs, let app continue
            return True

    def _initialize_main_ui(self):
        # Program title in OS title bar
        self.title("BaSIM - Basin Simulator")
        self.geometry("1200x800")
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        # Menubar (File/Help with About)
        try:
            self._create_menubar()
        except Exception:
            pass

        # Logging to file (rotating), plus GUI console mirroring via _log()
        self._logger = None
        self._init_logging()
        # Set window/taskbar icon from logo assets (safe no-op if unavailable)
        try:
            self._set_logo_image(24)
        except Exception:
            pass

        # Predefine optional UI fields to avoid Tk __getattr__ fallback
        self.ent_folder = None
        self.lbl_folder_status = None

        # Determine available cores first (needed by UI builder)
        try:
            self._max_cores = max(1, (os.cpu_count() or 2) - 1)
        except Exception:
            self._max_cores = 1

        # Build UI and initialize state
        self._build_layout()
        self._reset_state()
        # Load last-used folder preference (if any)
        try:
            self._load_prefs()
        except Exception:
            pass
        # Validate and auto-scan if folder present
        try:
            self._validate_folder_status()
            if self.ent_folder is not None and (self.ent_folder.get().strip()):
                self._load_ts1_from_folder()
        except Exception:
            pass
        # Run state
        self._has_run_before = False
        self._previous_scenario = None
        # Initialize run button style
        self._update_run_button()
        # Background update check (cached manifest) — silent, sets badge if newer
        try:
            import threading
            def _chk_cached():
                status = check_manifest_cached(VERSION)
                if status.get('ok') and status.get('newer') and status.get('manifest'):
                    latest = status['manifest'].get('version')
                    if latest:
                        self.after(0, lambda: self.lbl_badge.configure(text=f"Update available: v{latest}"))
            threading.Thread(target=_chk_cached, daemon=True).start()
        except Exception:
            pass
        # Save prefs on close
        try:
            self.protocol("WM_DELETE_WINDOW", self.on_close)
        except Exception:
            pass
        try:
            self._logger.info("BaSIM v%s launched and UI initialized", VERSION)
        except Exception:
            pass

    def _check_license(self) -> bool:
        try:
            stored = self.license_mgr.load_stored_license()
            if stored:
                validation = self.license_mgr.validate_license(stored.get('email', ''), stored.get('key'))
                return bool(validation.get('valid'))
        except Exception:
            pass
        return False

    def _show_license_dialog(self):
        # Hide main window during activation
        try:
            self.withdraw()
        except Exception:
            pass
        import re
        dialog = ctk.CTkToplevel(self)
        dialog.title("BaSIM - License Activation")
        dialog.geometry("450x380")
        dialog.grab_set()
        dialog.focus_force()
        # Center dialog
        dialog.update_idletasks()
        w = dialog.winfo_width(); h = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        ctk.CTkLabel(dialog, text="BaSIM License Activation", font=("Arial", 18, "bold")).pack(pady=15)
        ctk.CTkLabel(dialog, text="Enter your email to start a 30-day trial\nor activate with a license key", font=("Arial", 11)).pack(pady=5)
        ctk.CTkLabel(dialog, text="Email Address:", font=("Arial", 12)).pack(pady=(15, 5))
        email_entry = ctk.CTkEntry(dialog, width=350, placeholder_text="user@example.com")
        email_entry.pack(pady=5)
        ctk.CTkLabel(dialog, text="License Key (optional):", font=("Arial", 12)).pack(pady=(10, 5))
        key_entry = ctk.CTkEntry(dialog, width=350, placeholder_text="XXXX-XXXX-XXXX-XXXX")
        key_entry.pack(pady=5)
        status_label = ctk.CTkLabel(dialog, text="", height=20)
        status_label.pack(pady=10)
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=15)

        def _close_app():
            try:
                dialog.destroy()
            except Exception:
                pass
            try:
                self.destroy()
            except Exception:
                pass

        def _activate():
            email = email_entry.get().strip()
            key = key_entry.get().strip() or None
            if not email:
                status_label.configure(text="Please enter your email address", text_color="#d9534f"); return
            if not re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email):
                status_label.configure(text="Please enter a valid email address", text_color="#d9534f"); return
            status_label.configure(text="Validating...", text_color="#999999")
            dialog.update()
            try:
                result = self.license_mgr.validate_license(email, key)
            except Exception as e:
                status_label.configure(text=f"Error: {e}", text_color="#d9534f"); return
            if result.get('valid'):
                try:
                    self.license_mgr.save_license(email, key)
                except Exception:
                    pass
                msg = result.get('message', f"Activated: {result.get('type','')}")
                status_label.configure(text=f"✓ {msg}", text_color="#3c763d")
                dialog.after(800, lambda: [dialog.destroy(), self.deiconify(), self._initialize_main_ui()])
            else:
                msg = result.get('message', 'Invalid license')
                status_label.configure(text=f"✗ {msg}", text_color="#d9534f")

        ctk.CTkButton(btn_frame, text="Activate", command=_activate, width=120, height=35).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Exit", command=_close_app, width=120, height=35, fg_color="#6c757d").pack(side="left", padx=5)
        note = ctk.CTkLabel(dialog, text="✓ Free unlimited access for .wa.gov.au email addresses", font=("Arial", 10), text_color="#3c763d")
        note.pack(pady=(10, 0))
        dialog.protocol("WM_DELETE_WINDOW", _close_app)
        email_entry.focus_set()

def launch_app():
    """Entry point used by basim.py to launch the GUI."""
    app = BaSIMApp()
    try:
        app.mainloop()
    except Exception:
        # If the window was closed during gating, mainloop may not be valid
        pass

    def _create_menubar(self):
        try:
            menubar = tk.Menu(self)
            # File menu
            file_menu = tk.Menu(menubar, tearoff=0)
            file_menu.add_command(label="Open Logs Folder", command=self._open_logs_folder)
            file_menu.add_separator()
            file_menu.add_command(label="Exit", command=self.on_close)
            menubar.add_cascade(label="File", menu=file_menu)
            # Help menu
            help_menu = tk.Menu(menubar, tearoff=0)
            help_menu.add_command(label="Check for Updates", command=self._manual_check_updates)
            help_menu.add_command(label="View EULA", command=self._open_eula_window)
            help_menu.add_separator()
            help_menu.add_command(label="About BaSIM...", command=self._show_about_dialog)
            menubar.add_cascade(label="Help", menu=help_menu)
            self.config(menu=menubar)
            self._menubar = menubar
        except Exception:
            pass

    def _manual_check_updates(self):
        """Enhanced Phase 9 update workflow using JSON manifest and hash verification."""
        # Non-blocking: perform network fetch in a short-lived thread then present dialog
        import threading
        def _worker():
            result = check_manifest(VERSION)
            self.after(0, lambda: self._show_update_dialog(result))
        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            try:
                messagebox.showwarning("Update", "Unable to start update check thread.")
            except Exception:
                pass

    def _show_update_dialog(self, manifest_status: dict):
        try:
            if not manifest_status.get('ok'):
                messagebox.showinfo("Update", f"Manifest fetch failed: {manifest_status.get('error','Unknown error')}")
                return
            manifest = manifest_status.get('manifest') or {}
            remote_v = manifest.get('version') or "?"
            newer = manifest_status.get('newer', False)
            if not newer:
                messagebox.showinfo("Up to date", f"You're running v{VERSION}. No newer version found (remote {remote_v}).")
                return
            # Build selection dialog
            dlg = ctk.CTkToplevel(self)
            dlg.title("BaSIM Update Available")
            dlg.geometry("560x480")
            dlg.grab_set(); dlg.focus_force()
            ctk.CTkLabel(dlg, text=f"New Version v{remote_v} Available", font=("Arial", 18, "bold")).pack(pady=10)
            # Release notes
            notes = manifest.get('release_notes') or manifest.get('notes') or "(No release notes provided.)"
            txt = ctk.CTkTextbox(dlg, width=520, height=240)
            txt.pack(padx=10, pady=6, fill='both', expand=True)
            try:
                txt.insert('1.0', notes)
            except Exception:
                pass
            choice_var = tk.StringVar(value='portable')
            frame_opts = ctk.CTkFrame(dlg); frame_opts.pack(fill='x', padx=10, pady=6)
            has_portable = bool(manifest.get('url_windows_portable') and manifest.get('sha256_windows_portable'))
            has_installer = bool(manifest.get('url_windows_installer') and manifest.get('sha256_windows_installer'))
            if has_portable:
                ctk.CTkRadioButton(frame_opts, text="Portable (.zip)", variable=choice_var, value='portable').pack(side='left', padx=6)
            if has_installer:
                ctk.CTkRadioButton(frame_opts, text="Installer", variable=choice_var, value='installer').pack(side='left', padx=6)
            if not (has_portable or has_installer):
                ctk.CTkLabel(frame_opts, text="Manifest missing Windows artifacts.", text_color="#d9534f").pack(anchor='w')
            status_lbl = ctk.CTkLabel(dlg, text="", text_color="#999999")
            status_lbl.pack(pady=(4,2))
            prog_box = ctk.CTkTextbox(dlg, width=520, height=120)
            prog_box.pack(padx=10, pady=(4, 8), fill='both', expand=False)
            prog_box.configure(state='disabled')

            btn_frame = ctk.CTkFrame(dlg); btn_frame.pack(pady=6)

            def _append(msg: str):
                try:
                    prog_box.configure(state='normal')
                    prog_box.insert(tk.END, msg + "\n")
                    prog_box.see(tk.END)
                    prog_box.configure(state='disabled')
                except Exception:
                    pass

            def _do_download():
                if not (has_portable or has_installer):
                    status_lbl.configure(text="No downloadable artifacts.", text_color="#d9534f"); return
                status_lbl.configure(text="Downloading...", text_color="#999999")
                sel = choice_var.get()
                import threading
                def _dl():
                    res = apply_update(manifest, choice=sel)
                    def _finish():
                        for line in res.get('progress_log', []):
                            _append(line)
                        if res.get('ok'):
                            status_lbl.configure(text="Update staged successfully." if res.get('staged_dir') else ("Installer launched." if res.get('launched_installer') else "Update downloaded."), text_color="#3c763d")
                            if res.get('staged_dir'):
                                _append(f"Staged at: {res['staged_dir']}")
                        else:
                            status_lbl.configure(text=f"Failed: {res.get('error','Unknown error')}", text_color="#d9534f")
                    self.after(0, _finish)
                try:
                    threading.Thread(target=_dl, daemon=True).start()
                except Exception as e:
                    status_lbl.configure(text=f"Unable to start download: {e}", text_color="#d9534f")

            def _close():
                try:
                    dlg.destroy()
                except Exception:
                    pass

            ctk.CTkButton(btn_frame, text="Download", command=_do_download, width=140).pack(side='left', padx=6)
            ctk.CTkButton(btn_frame, text="Close", command=_close, width=110, fg_color="#6c757d").pack(side='left', padx=6)
            # Fallback manual link
            manual = manifest.get('manual_download_url') or manifest.get('homepage') or manifest.get('url_windows_portable') or manifest.get('url_windows_installer')
            if manual:
                link_frame = ctk.CTkFrame(dlg); link_frame.pack(fill='x', padx=10, pady=(2,8))
                ctk.CTkLabel(link_frame, text=f"Manual download: {manual}", text_color="#3A7EBF", wraplength=500, justify='left').pack(anchor='w')
        except Exception:
            try:
                messagebox.showwarning("Update", "Unexpected error building update dialog.")
            except Exception:
                pass

    def _open_logs_folder(self):
        try:
            logs = Path.home() / ".basim" / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            os.startfile(str(logs))
        except Exception:
            pass

    def _open_eula_window(self):
        try:
            # Load EULA text from src/legal/eula.txt
            eula_path = Path(__file__).parents[1] / 'legal' / 'eula.txt'
            text = eula_path.read_text(encoding='utf-8') if eula_path.exists() else "EULA file not found."
            win = ctk.CTkToplevel(self)
            win.title("BaSIM - EULA")
            win.geometry("700x500")
            win.grab_set(); win.focus_force()
            ctk.CTkLabel(win, text="End-User License Agreement", font=("Arial", 18, "bold")).pack(pady=8)
            txt = ctk.CTkTextbox(win, width=660, height=420)
            txt.pack(padx=10, pady=6, fill='both', expand=True)
            try:
                txt.insert('1.0', text)
            except Exception:
                pass
            btn = ctk.CTkButton(win, text="Close", command=win.destroy, width=120)
            btn.pack(pady=8)
        except Exception:
            pass

    def _show_about_dialog(self):
        try:
            win = ctk.CTkToplevel(self)
            win.title("About BaSIM")
            win.geometry("560x480")
            win.grab_set(); win.focus_force()
            # Header
            ctk.CTkLabel(win, text="BaSIM", font=("Arial", 22, "bold")).pack(pady=(14, 6))
            vers_txt = f"Version {VERSION}"
            try:
                if BUILD_METADATA:
                    vers_txt += f" ({BUILD_METADATA})"
            except Exception:
                pass
            ctk.CTkLabel(win, text=f"{vers_txt} — {RELEASE_DATE}").pack()
            ctk.CTkLabel(win, text="© Innealta Software").pack(pady=(2, 6))
            # Buttons row
            row = ctk.CTkFrame(win); row.pack(pady=8)
            ctk.CTkButton(row, text="View EULA", width=120, command=self._open_eula_window).pack(side='left', padx=6)
            ctk.CTkButton(row, text="Open Logs Folder", width=160, command=self._open_logs_folder).pack(side='left', padx=6)
            ctk.CTkButton(row, text="Check for Updates", width=160, command=self._manual_check_updates).pack(side='left', padx=6)
            # Release notes
            ctk.CTkLabel(win, text="Release Notes:", font=("Arial", 14, "bold")).pack(anchor='w', padx=12, pady=(10, 4))
            txt = ctk.CTkTextbox(win, width=520, height=280)
            txt.pack(padx=12, pady=(0, 10), fill='both', expand=True)
            try:
                txt.insert('1.0', RELEASE_NOTES or "-")
            except Exception:
                pass
            ctk.CTkButton(win, text="Close", command=win.destroy, width=120).pack(pady=(4, 10))
        except Exception:
            pass
