from __future__ import annotations

from pathlib import Path
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTextEdit,
    QHBoxLayout,
)

# Support running this file directly (so that 'src' is importable)
try:
    from src.licensing.verifier import LicenseVerifier, LICENSE_PATH
except ModuleNotFoundError:
    # When executed as a script, sys.path points at this file's folder (src/gui).
    # Insert project root so 'src' is importable as a namespace package.
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from src.licensing.verifier import LicenseVerifier, LICENSE_PATH


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BaSIM License")
        self.setModal(True)
        self.ver = LicenseVerifier()

        v = QVBoxLayout(self)
        self.status_lbl = QLabel("")
        v.addWidget(self.status_lbl)

        mh = self.ver.machine_hash()
        self.hash_lbl = QLabel(f"Machine ID (hash): {mh}")
        self.hash_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.hash_lbl)

        row = QHBoxLayout()
        btn_import = QPushButton("Import License…")
        btn_import.clicked.connect(self.import_license)
        btn_req = QPushButton("Save Request File…")
        btn_req.clicked.connect(self.save_request)
        row.addWidget(btn_import)
        row.addWidget(btn_req)
        v.addLayout(row)

        self.info = QTextEdit()
        self.info.setReadOnly(True)
        v.addWidget(self.info)

        self.refresh()

    def refresh(self):
        st = self.ver.validate_installed()
        if st.ok:
            msg = (
                f"Licensed to: {st.customer or '—'} | Edition: {st.edition or '—'} | "
                f"Days left: {st.days_left} | Expires: {st.expiry_utc.date() if st.expiry_utc else '—'}"
            )
        else:
            msg = (
                f"Unlicensed: {st.message}\nInstall a valid license to enable runs.\n"
                f"Expected path: {LICENSE_PATH}"
            )
        self.status_lbl.setText(msg)
        self.info.setText(msg)

    def import_license(self):
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "Select License File",
            "",
            "License Files (*.lic);;JSON Files (*.json);;All Files (*.*)",
        )
        if not fn:
            return
        st = self.ver.install_file(Path(fn))
        if not st.ok:
            QMessageBox.critical(self, "Invalid License", st.message)
        else:
            QMessageBox.information(self, "License Installed", "License installed successfully.")
            self.refresh()
            self.accept()

    def save_request(self):
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save License Request", "license_request.json", "JSON Files (*.json)"
        )
        if not fn:
            return
        parent = self.parent()
        note = ""
        try:
            if hasattr(parent, "scenario_name"):
                note = parent.scenario_name.text()
        except Exception:
            pass
        req = self.ver.make_request(note)
        Path(fn).write_text(__import__("json").dumps(req, indent=2), encoding="utf-8")
        QMessageBox.information(
            self,
            "Request Saved",
            f"Send this file to BaSIM to receive a license.\n{fn}",
        )


if __name__ == "__main__":
    # Minimal runner to open the dialog for manual testing
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = LicenseDialog()
    dlg.show()
    sys.exit(app.exec())
