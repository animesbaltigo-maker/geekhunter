"""Small JSON store used to avoid posting the same item repeatedly."""

from __future__ import annotations

import json
from pathlib import Path
from time import time


class PostedHistory:
    def __init__(self, path: str, ttl_days: int = 14) -> None:
        self.path = Path(path)
        self.ttl_seconds = ttl_days * 24 * 60 * 60
        self._items = self._load()
        self._prune()

    def _load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(key): float(value) for key, value in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _prune(self) -> None:
        cutoff = time() - self.ttl_seconds
        self._items = {key: posted_at for key, posted_at in self._items.items() if posted_at >= cutoff}

    def seen(self, item_id: str | None) -> bool:
        return bool(item_id and item_id in self._items)

    def mark(self, item_id: str | None) -> None:
        if not item_id:
            return
        self._items[item_id] = time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")
