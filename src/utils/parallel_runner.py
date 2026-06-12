"""Parallel execution support for BaSIM models.

This module provides a top-level worker function that can be dispatched to
separate processes (e.g., via concurrent.futures.ProcessPoolExecutor) on
Windows. Keep imports local to avoid pickling issues and ensure the function
is importable from the subprocess context.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple, Dict, Any, Optional


def run_model_worker(ts1_path: str, config: dict) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """Worker function for parallel model execution.

    This is designed to be called in a separate process. It imports the
    model runner lazily and returns a (success, summary, output_dir) tuple.
    """
    try:
        # Ensure project paths are importable inside the spawned process
        here = Path(__file__).resolve()
        src_dir = here.parent.parent  # .../src
        proj_root = src_dir.parent
        for p in (str(src_dir), str(proj_root)):
            if p not in sys.path:
                sys.path.insert(0, p)

        # Try both import styles depending on sys.path
        try:
            from src.main_phase3_step32_time_varying import run_phase3_step32_with_config
        except Exception:
            from main_phase3_step32_time_varying import run_phase3_step32_with_config  # type: ignore

        success, summary, output_dir = run_phase3_step32_with_config(ts1_path, config)
        return success, summary, output_dir
    except Exception as e:  # pragma: no cover - best-effort error propagation
        # Avoid raising across process boundary; return error in summary
        return False, {"error": str(e), "ts1_file": ts1_path}, None
