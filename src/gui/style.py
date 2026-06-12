"""
GUI styling helpers for BaSIM.

Provides a consistent dark theme via a QPalette and a complementary stylesheet.
"""

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt


def apply_dark_palette(app) -> None:
    """Apply a dark QPalette to the given QApplication instance.

    Safe to call multiple times. If app is None, this is a no-op.
    """
    if app is None:
        return

    palette = QPalette()
    # Base colors
    base = QColor(43, 43, 43)
    alt_base = QColor(50, 50, 50)
    text = QColor(235, 235, 235)
    mid = QColor(60, 60, 60)
    dark = QColor(30, 30, 30)
    highlight = QColor(13, 115, 119)
    highlighted_text = QColor(255, 255, 255)

    palette.setColor(QPalette.ColorRole.Window, base)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, alt_base)
    palette.setColor(QPalette.ColorRole.AlternateBase, base)
    palette.setColor(QPalette.ColorRole.ToolTipBase, alt_base)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, mid)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, highlighted_text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(150, 150, 150))
    palette.setColor(QPalette.ColorRole.Base, alt_base)
    palette.setColor(QPalette.ColorRole.Mid, mid)
    palette.setColor(QPalette.ColorRole.Dark, dark)

    app.setPalette(palette)


# Minimal stylesheet to complement the palette. Widgets can extend this as needed.
DARK_STYLESHEET = """
QMainWindow {
    background-color: #2b2b2b;
}
QWidget { color: #ececec; }
QLabel { color: #ffffff; font-size: 12px; }
QGroupBox { border: 1px solid #3f3f3f; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background-color: #3c3c3c; border: 1px solid #555555; color: #ffffff; padding: 5px; border-radius: 3px; font-size: 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus { border: 1px solid #0d7377; }
QPushButton { background-color: #0d7377; color: white; border: none; padding: 8px 15px; border-radius: 3px; font-weight: bold; font-size: 12px; }
QPushButton:hover { background-color: #14a085; }
QPushButton:pressed { background-color: #0a5d61; }
QPushButton:disabled { background-color: #555555; color: #999999; }
QStatusBar { background-color: #2f2f2f; color: #e0e0e0; }
QToolTip { color: #ffffff; background-color: #3c3c3c; border: 1px solid #0d7377; }
QTabBar::tab { background: #333333; color: #cccccc; padding: 6px 10px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar::tab:selected { background: #0d7377; color: #ffffff; }
QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background-color: #0d7377; width: 8px; }
"""
"""
Centralized style guide for BaSIM Professional (PyQt6)
Defines a readable, consistent dark theme using both QPalette and a stylesheet.
"""
from PyQt6.QtGui import QPalette, QColor

# High-contrast dark palette values
BG_DARKEST = QColor(24, 26, 27)      # window background
BG_DARK = QColor(34, 36, 38)         # panels/inputs
BG_LIGHT = QColor(45, 48, 51)        # hover/active
ACCENT = QColor(13, 115, 119)        # primary
ACCENT_HOVER = QColor(20, 160, 133)
BORDER = QColor(70, 73, 76)
TEXT = QColor(230, 230, 230)
TEXT_MUTED = QColor(190, 190, 190)
TEXT_DISABLED = QColor(140, 140, 140)
HIGHLIGHT = QColor(30, 144, 255)


def apply_dark_palette(app):
    """Apply a readable high-contrast dark palette."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, BG_DARKEST)
    pal.setColor(QPalette.ColorRole.WindowText, TEXT)
    pal.setColor(QPalette.ColorRole.Base, BG_DARK)
    pal.setColor(QPalette.ColorRole.AlternateBase, BG_DARKEST)
    pal.setColor(QPalette.ColorRole.ToolTipBase, BG_LIGHT)
    pal.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    pal.setColor(QPalette.ColorRole.Text, TEXT)
    pal.setColor(QPalette.ColorRole.Button, BG_LIGHT)
    pal.setColor(QPalette.ColorRole.ButtonText, TEXT)
    pal.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    pal.setColor(QPalette.ColorRole.Highlight, ACCENT)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.PlaceholderText, TEXT_DISABLED)
    app.setPalette(pal)


DARK_STYLESHEET = f"""
* {{
  font-size: 13px;
}}
QMainWindow {{
  background-color: {BG_DARKEST.name()};
}}
QLabel {{
  color: {TEXT.name()};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
  background-color: {BG_DARK.name()};
  border: 1px solid {BORDER.name()};
  color: {TEXT.name()};
  padding: 6px;
  border-radius: 4px;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
  color: {TEXT_DISABLED.name()};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
  border: 1px solid {ACCENT.name()};
}}
QPushButton {{
  background-color: {ACCENT.name()};
  color: #ffffff;
  border: none;
  padding: 8px 14px;
  border-radius: 4px;
  font-weight: 600;
}}
QPushButton:hover {{
  background-color: {ACCENT_HOVER.name()};
}}
QPushButton:disabled {{
  background-color: {BORDER.name()};
  color: {TEXT_DISABLED.name()};
}}
QGroupBox {{
  color: {TEXT.name()};
  border: 1px solid {BORDER.name()};
  border-radius: 6px;
  margin-top: 12px;
  padding-top: 10px;
  font-weight: 600;
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  left: 10px;
  padding: 0 6px;
}}
QTabWidget::pane {{
  border: 1px solid {BORDER.name()};
  background: {BG_DARK.name()};
}}
QTabBar::tab {{
  background: {BG_DARK.name()};
  color: {TEXT.name()};
  padding: 8px 16px;
  margin-right: 2px;
  border-top-left-radius: 6px;
  border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
  background: {ACCENT.name()};
  color: #ffffff;
}}
QListWidget, QTableWidget {{
  background: {BG_DARK.name()};
  color: {TEXT.name()};
  border: 1px solid {BORDER.name()};
}}
QHeaderView::section {{
  background: {BG_DARKEST.name()};
  color: {TEXT_MUTED.name()};
  border: 1px solid {BORDER.name()};
  padding: 6px;
}}
QProgressBar {{
  background: {BG_DARK.name()};
  color: {TEXT.name()};
  border: 1px solid {BORDER.name()};
  border-radius: 6px;
  text-align: center;
  padding: 2px;
}}
QProgressBar::chunk {{
  background-color: {ACCENT.name()};
  border-radius: 6px;
}}
QMenuBar, QMenu {{
  background: {BG_DARK.name()};
  color: {TEXT.name()};
}}
QMenu::item:selected {{
  background: {ACCENT.name()};
}}
QStatusBar {{
  background: {BG_DARKEST.name()};
  color: {TEXT_MUTED.name()};
}}
QToolTip {{
  background: {BG_LIGHT.name()};
  color: {TEXT.name()};
  border: 1px solid {BORDER.name()};
}}
"""
