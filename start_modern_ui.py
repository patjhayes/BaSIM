"""
Entry point to launch the BaSIM modern Qt GUI.
"""

import sys
from pathlib import Path

# Ensure project root (containing src/) is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    """
    Launch the BaSIM Qt application via the main_app entry point.
    """
    # If qt_app.py defines a main(), import and call it:
    try:
        from src.gui.qt_app import main as gui_main
        gui_main()
    except ImportError:
        # Fallback: execute qt_app as a script
        import runpy
        runpy.run_module("src.gui.qt_app", run_name="__main__")


if __name__ == "__main__":
    main()