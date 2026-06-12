"""Minimal smoke test to ensure BaSIM core modules import without error.

This test is intentionally lightweight so that packaging builds can
fail fast if a critical import breaks, without executing heavy simulations.
"""

def test_import_main():
    # Import the GUI launcher module(s) to ensure no syntax/runtime import errors.
    # Avoid actually launching the Qt application.
    import importlib
    importlib.import_module('basim')
    # Optionally verify a symbol exists (adjust if module layout changes)
    assert True
