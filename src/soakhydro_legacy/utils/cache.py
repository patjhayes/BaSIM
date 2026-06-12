from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Optional


class SimpleCache:
    """File-based cache for API responses."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def load(self, key: str) -> Optional[Any]:
        path = self._key_to_path(key)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, key: str, payload: Any) -> None:
        path = self._key_to_path(key)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    def get_or_fetch(self, key: str, fetcher: Callable[[], Any]) -> Any:
        cached = self.load(key)
        if cached is not None:
            return cached
        payload = fetcher()
        self.save(key, payload)
        return payload
