"""Small JSON-file key/value caches, kept in .cache/ and persisted by actions/cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CACHE_DIR = Path(".cache")


class JsonCache:
    def __init__(self, name: str, directory: Path = CACHE_DIR):
        self.path = directory / f"{name}.json"
        self._data: dict[str, Any] = json.loads(self.path.read_text()) if self.path.exists() else {}
        self._dirty = False

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def save(self) -> None:
        if self._dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=1, sort_keys=True))
            self._dirty = False
