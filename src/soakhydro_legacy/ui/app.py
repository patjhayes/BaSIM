from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from ..config import default_project_settings
from ..hydraulics.optimizer import SoakwellDesignParameters
from ..models.common import AEP, Coordinate
from ..pipeline import create_sample_project
from .map_widget import MapWidget
from .workers import PipelineWorker


class SoakSimWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SoakSIM Desktop")
        self.resize(1200, 720)

        self.map_widget = MapWidget(self)

        controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(12, 12, 12, 12)
        controls_layout.setSpacing(10)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(6)
        self.lat_spin.setSingleStep(0.0001)

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(6)
        self.lon_spin.setSingleStep(0.0001)

        self.aep_combo = QComboBox()
        for aep in default_project_settings().ae_ps:
            self.aep_combo.addItem(aep.to_label(), userData=aep)

        self.pattern_spin = QSpinBox()
        self.pattern_spin.setRange(1, 10)
        self.pattern_spin.setValue(1)

        self.infiltration_spin = QDoubleSpinBox()
        self.infiltration_spin.setRange(1.0, 500.0)
        self.infiltration_spin.setValue(80.0)
        self.infiltration_spin.setSuffix(" mm/hr")

        self.drain_time_spin = QDoubleSpinBox()
        self.drain_time_spin.setRange(1.0, 72.0)
        self.drain_time_spin.setValue(24.0)
        self.drain_time_spin.setSuffix(" h")

        self.safety_factor_spin = QDoubleSpinBox()
        self.safety_factor_spin.setRange(1.0, 2.5)
        self.safety_factor_spin.setDecimals(2)
        self.safety_factor_spin.setValue(1.2)

        self.use_live_checkbox = QCheckBox("Fetch live ARR/BOM data")
        self.mixed_checkbox = QCheckBox("Allow mixed soakwell sizes")
        self.mixed_checkbox.setChecked(True)

        self.max_units_spin = QSpinBox()
        self.max_units_spin.setRange(1, 12)
        self.max_units_spin.setValue(8)

        form_layout.addRow("Latitude", self.lat_spin)
        form_layout.addRow("Longitude", self.lon_spin)
        form_layout.addRow("Design AEP", self.aep_combo)
        form_layout.addRow("Temporal pattern rank", self.pattern_spin)
        form_layout.addRow("Infiltration rate", self.infiltration_spin)
        form_layout.addRow("Drain time", self.drain_time_spin)
        form_layout.addRow("Storage safety factor", self.safety_factor_spin)
        form_layout.addRow(self.use_live_checkbox)
        form_layout.addRow(self.mixed_checkbox)
        form_layout.addRow("Max units", self.max_units_spin)

        controls_layout.addLayout(form_layout)

        self.run_button = QPushButton("Run analysis")
        controls_layout.addWidget(self.run_button)

        self.status_label = QLabel("Select a coordinate to begin.")
        controls_layout.addWidget(self.status_label)

        self.results_view = QPlainTextEdit()
        self.results_view.setReadOnly(True)
        controls_layout.addWidget(self.results_view, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.map_widget)
        splitter.addWidget(controls_widget)
        splitter.setSizes([800, 400])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.worker_thread: QThread | None = None
        self.worker: PipelineWorker | None = None

        self._initialize_defaults()
        self._connect_signals()

    def _initialize_defaults(self) -> None:
        sample_project = create_sample_project()
        coord = sample_project.coordinate
        self.lat_spin.setValue(coord.latitude)
        self.lon_spin.setValue(coord.longitude)
        self.map_widget.set_initial_view(coord.latitude, coord.longitude, zoom=10)
        self.map_widget.set_marker(coord.latitude, coord.longitude)

    def _connect_signals(self) -> None:
        self.map_widget.coordinateSelected.connect(self._on_map_click)
        self.lat_spin.valueChanged.connect(self._on_lat_lon_changed)
        self.lon_spin.valueChanged.connect(self._on_lat_lon_changed)
        self.run_button.clicked.connect(self._on_run_clicked)

    def _on_map_click(self, latitude: float, longitude: float) -> None:
        self.lat_spin.blockSignals(True)
        self.lon_spin.blockSignals(True)
        self.lat_spin.setValue(latitude)
        self.lon_spin.setValue(longitude)
        self.lat_spin.blockSignals(False)
        self.lon_spin.blockSignals(False)
        self.status_label.setText(f"Selected coordinate: {latitude:.4f}, {longitude:.4f}")

    def _on_lat_lon_changed(self) -> None:
        self.map_widget.set_marker(self.lat_spin.value(), self.lon_spin.value())

    def _on_run_clicked(self) -> None:
        if self.worker_thread is not None:
            return
        self.status_label.setText("Running analysis...")
        self.run_button.setEnabled(False)
        project = create_sample_project()
        project = replace(
            project,
            coordinate=Coordinate(latitude=self.lat_spin.value(), longitude=self.lon_spin.value()),
        )
        params = SoakwellDesignParameters(
            infiltration_rate_mm_per_hr=self.infiltration_spin.value(),
            design_drain_time_hours=self.drain_time_spin.value(),
            storage_safety_factor=self.safety_factor_spin.value(),
            allow_mixed_sizes=self.mixed_checkbox.isChecked(),
            max_units=self.max_units_spin.value(),
        )
        aep: AEP = self.aep_combo.currentData()
        pattern_rank = self.pattern_spin.value()
        use_live = self.use_live_checkbox.isChecked()

        self.worker_thread = QThread()
        self.worker = PipelineWorker(
            project=project,
            params=params,
            aep=aep,
            pattern_rank=pattern_rank,
            use_live_data=use_live,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def _on_worker_finished(self, report) -> None:
        self.status_label.setText("Analysis complete.")
    lines: list[str] = []
        if report.ensembles:
            lines.append("Temporal pattern statistics:")
            for (aep, duration), ensemble in report.ensembles.items():
                stats = ensemble.statistics()
                lines.append(
                    f"  {aep.to_label()} @ {duration} min -> peak {stats['max_peak_cms']:.2f} m³/s, "
                    f"median {stats['median_peak_cms']:.2f} m³/s"
                )
        if report.soakwell_designs:
            lines.append("\nSoakwell design summary:")
            for aep, design in report.soakwell_designs.items():
                lines.append(
                    f"  {aep.to_label()}: {design.configuration} | critical {design.critical_duration_minutes} min, "
                    f"storage {design.required_storage_m3:.2f} m³ (residual {design.residual_storage_m3:.2f} m³, "
                    f"shortfall {design.infiltration_shortfall_m3:.2f} m³)"
                )
        self.results_view.setPlainText("\n".join(lines) if lines else "No results")
        self.run_button.setEnabled(True)

    def _on_worker_error(self, message: str) -> None:  # pragma: no cover - UI feedback
        self.status_label.setText("Error during analysis.")
        self.results_view.setPlainText(message)
        self.run_button.setEnabled(True)

    def _cleanup_worker(self) -> None:
        if self.worker_thread:
            self.worker_thread.deleteLater()
        if self.worker:
            self.worker.deleteLater()
        self.worker_thread = None
        self.worker = None


def main() -> None:
    app = QApplication(sys.argv)
    window = SoakSimWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
