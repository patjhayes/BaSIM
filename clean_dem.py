import re

with open('src/gui/qt_app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Replace _create_basin_group
new_basin_group = """    def _create_basin_group(self):
        \"\"\"Basin geometry inputs\"\"\"
        group = QGroupBox("Basin Geometry")
        layout = QFormLayout()

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
        self.use_custom_da_check = QCheckBox("Use custom depth-area")
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
"""
content = re.sub(r'    def _create_basin_group\(self\):.*?    def _edit_depth_area_table\(self\):', new_basin_group + '\n    def _edit_depth_area_table(self):', content, flags=re.DOTALL)

# 2. Remove unused functions
content = re.sub(r'    def _toggle_basin_source\(self, manual_checked: bool\):.*?    def _browse_dem_file\(self\):', '    def _browse_dem_file(self):', content, flags=re.DOTALL)
content = re.sub(r'    def _browse_dem_file\(self\):.*?    def _update_ui_from_config\(self, config\):', '    def _update_ui_from_config(self, config):', content, flags=re.DOTALL)
content = re.sub(r'    def _is_dem_mode\(self\):.*?    def _get_crest_elevation\(self\) -> float:', '    def _get_crest_elevation(self) -> float:', content, flags=re.DOTALL)
content = re.sub(r'    def _make_dem_viz_uri\(self\):.*?    def generate_html_report\(self\):', '    def generate_html_report(self):', content, flags=re.DOTALL)

# 3. Simplify _get_crest_elevation
content = re.sub(r'    def _get_crest_elevation\(self\) -> float:.*?    def _build_config\(self\):', '    def _get_crest_elevation(self) -> float:\n        return float(self.floor_elev_input.value() + self.depth_input.value())\n\n    def _build_config(self):', content, flags=re.DOTALL)

# 4. Clean up _build_config
bg_replacement = """            _bg = {
                "source": "manual",
                "length_floor": self.length_input.value(),
                "width_floor": self.width_input.value(),
                "max_depth": self.depth_input.value(),
                "side_slope_hv": self.side_slope_input.value(),
                "floor_elev": self.floor_elev_input.value(),
                "use_custom_da": self.use_custom_da_check.isChecked(),
                "custom_da_table": getattr(self, '_custom_da_data', []),
            }"""
content = re.sub(r'            if hasattr\(self, \'basin_source_dem\'\).*?                _bg = \{.*?\}', bg_replacement, content, flags=re.DOTALL)


# 5. Clean up _update_design_view
design_view_replacement = """        if not hasattr(self, 'design_view'):
            return

        cfg = self._build_config()"""
content = re.sub(r'        if not hasattr\(self, \'design_view\'\):\n            return\n.*?        cfg = self\._build_config\(\)', design_view_replacement, content, flags=re.DOTALL)

# 6. Clean up generate_html_report
content = re.sub(r'        _dem_mode = self\._is_dem_mode\(\)\n.*?        # Basin details', '        # Basin details', content, flags=re.DOTALL)
content = re.sub(r'        dem_viz_uri = self\._make_dem_viz_uri\(\) if _dem_mode else None\n', '', content)
content = re.sub(r'            \+ \(f"<h3>DEM Elevation Map</h3><img alt=\'DEM elevation heatmap\' src=\'\{dem_viz_uri\}\' style=\'max-width:100%\'>" if dem_viz_uri else ""\)\n', '', content)
content = re.sub(r'            if _dem_mode:\n.*?            else:\n', '', content, flags=re.DOTALL)
content = re.sub(r'                basin_view_html = \(\n                    "<h2 class=\'break\'>Basin Geometry Preview</h2>"\n                    \+ \(f"<div class=\'imgwrap\'><img src=\'\{design_viz_uri\}\' alt=\'Basin 3D preview\'/></div>" if design_viz_uri else "<div class=\'note\'>Preview unavailable.</div>"\)\n                \)', '            basin_view_html = (\n                "<h2 class=\'break\'>Basin Geometry Preview</h2>"\n                + (f"<div class=\'imgwrap\'><img src=\'{design_viz_uri}\' alt=\'Basin 3D preview\'/></div>" if design_viz_uri else "<div class=\'note\'>Preview unavailable.</div>")\n            )', content)
content = re.sub(r'            if _dem_mode:\n.*?            else:\n', '', content, flags=re.DOTALL)
content = re.sub(r'                basin_rows = \[\n', '            basin_rows = [\n', content)

with open('src/gui/qt_app_cleaned.py', 'w', encoding='utf-8') as f:
    f.write(content)
