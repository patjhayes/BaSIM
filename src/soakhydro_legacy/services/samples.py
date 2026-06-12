from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

SAMPLE_DIR = Path("sample_data")


def load_json(name: str) -> Dict[str, object]:
    path = SAMPLE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Sample data '{name}' not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
