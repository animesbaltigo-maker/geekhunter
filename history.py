"""Small JSON store used to avoid posting the same item repeatedly."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any

from price_history import canonical_product_key, _to_float


class PostedHistory:
    def __init__(self, path: str, ttl_days: int = 14) -> None:
        self.path = Path(path)
        self.ttl_seconds = ttl_days * 24 * 60 * 60
        self._items = self._load()
        self._prune()

    def _load(self) -> dict[str, dict[str, float]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items: dict[str, dict[str, float]] = {}
            for key, value in data.items():
                canonical_key = canonical_product_key(key)
                if not canonical_key:
                    continue
                entry = self._normalize_entry(value)
                if not entry:
                    continue
                current = items.get(canonical_key)
                if not current or entry["posted_at"] > current["posted_at"]:
                    if current:
                        current_lowest = float(current.get("lowest_price") or current.get("price") or 0)
                        entry_lowest = float(entry.get("lowest_price") or entry.get("price") or 0)
                        if current_lowest > 0 and (entry_lowest <= 0 or current_lowest < entry_lowest):
                            entry["lowest_price"] = current_lowest
                        if entry.get("price", 0) <= 0 and current.get("price", 0) > 0:
                            entry["price"] = current["price"]
                    items[canonical_key] = entry
                elif entry.get("price", 0) > 0 and current.get("price", 0) <= 0:
                    current["price"] = entry["price"]
                if entry.get("lowest_price", 0) > 0:
                    lowest = current.get("lowest_price", 0) if current else 0
                    if lowest <= 0 or entry["lowest_price"] < lowest:
                        items[canonical_key]["lowest_price"] = entry["lowest_price"]
            return items
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _prune(self) -> None:
        cutoff = time() - self.ttl_seconds
        self._items = {
            key: entry
            for key, entry in self._items.items()
            if float(entry.get("posted_at") or 0) >= cutoff
        }

    def seen(self, item_id: str | None) -> bool:
        key = canonical_product_key(item_id)
        return bool(key and key in self._items)

    def should_skip(self, item_id: str | None, current_price: object = None) -> bool:
        key = canonical_product_key(item_id)
        if not key or key not in self._items:
            return False
        price = _to_float(current_price)
        previous_lowest = self.lowest_price(key)
        return not (price > 0 and previous_lowest > 0 and price < previous_lowest)

    def lowest_price(self, item_id: str | None) -> float:
        key = canonical_product_key(item_id)
        entry = self._items.get(key) if key else None
        if not entry:
            return 0.0
        return float(entry.get("lowest_price") or entry.get("price") or 0)

    def mark(self, item_id: str | None, price: object = None) -> None:
        key = canonical_product_key(item_id)
        if not key:
            return
        numeric_price = _to_float(price)
        current_lowest = self.lowest_price(key)
        entry = {
            "posted_at": time(),
            "price": numeric_price,
            "lowest_price": numeric_price if numeric_price > 0 else current_lowest,
        }
        if current_lowest > 0 and (numeric_price <= 0 or current_lowest < numeric_price):
            entry["lowest_price"] = current_lowest
        self._items[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def _normalize_entry(self, value: Any) -> dict[str, float]:
        if isinstance(value, (int, float, str)):
            return {"posted_at": float(value), "price": 0.0, "lowest_price": 0.0}
        if isinstance(value, dict):
            posted_at = float(value.get("posted_at") or value.get("time") or value.get("timestamp") or 0)
            if posted_at <= 0:
                return {}
            price = _to_float(value.get("price") or value.get("posted_price"))
            lowest = _to_float(value.get("lowest_price")) or price
            return {"posted_at": posted_at, "price": price, "lowest_price": lowest}
        return {}
