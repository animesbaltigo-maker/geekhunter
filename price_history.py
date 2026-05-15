"""SQLite-backed product price history."""

from __future__ import annotations

import sqlite3
import threading
import re
from pathlib import Path
from time import time
from urllib.parse import parse_qs, urlparse


class PriceHistory:
    def __init__(self, path: str | object = "data/multiuser.sqlite3") -> None:
        if hasattr(path, "path"):
            path = str(getattr(path, "path"))
        self.path = Path(str(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=WAL")
        self.conn.execute("pragma busy_timeout=30000")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self.conn.execute(
                """
                create table if not exists price_history (
                    item_id text not null,
                    price real not null,
                    original_price real,
                    discount_pct integer,
                    source text,
                    recorded_at real not null,
                    primary key (item_id, recorded_at)
                )
                """
            )
            self.conn.commit()

    def record_product(self, produto: dict, source: str) -> dict:
        item_id = product_key(produto)
        price = _to_float(produto.get("preco_atual"))
        if not item_id or price <= 0:
            return produto

        was_low = self.is_historical_low(item_id, price)
        avg_30d = self.price_30d_avg(item_id)
        self.record(
            item_id,
            price,
            _to_float(produto.get("preco_original")),
            int(_to_float(produto.get("desconto_pct")) or 0),
            source,
        )

        enriched = dict(produto)
        enriched["price_history_key"] = item_id
        enriched["historical_low"] = was_low
        if avg_30d:
            enriched["price_30d_avg"] = avg_30d
        return enriched

    def record(self, item_id: str, price: float, original: float, discount: int, source: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                insert or ignore into price_history
                    (item_id, price, original_price, discount_pct, source, recorded_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (item_id, price, original or None, discount, source, time()),
            )
            self.conn.commit()

    def is_historical_low(self, item_id: str, price: float, min_records: int = 2) -> bool:
        with self._lock:
            row = self.conn.execute(
                "select count(*) as total, min(price) as min_price from price_history where item_id=?",
                (item_id,),
            ).fetchone()
        if not row or int(row["total"] or 0) < min_records:
            return False
        min_price = float(row["min_price"] or 0)
        return price <= min_price

    def price_30d_avg(self, item_id: str) -> float | None:
        cutoff = time() - (30 * 86400)
        with self._lock:
            row = self.conn.execute(
                "select avg(price) as avg_price from price_history where item_id=? and recorded_at>=?",
                (item_id, cutoff),
            ).fetchone()
        if not row or row["avg_price"] is None:
            return None
        return round(float(row["avg_price"]), 2)

    async def arecord(self, item_id: str, price: float, original: float, discount: int, source: str) -> None:
        self.record(item_id, price, original, discount, source)

    async def ais_historical_low(self, item_id: str, price: float) -> bool:
        return self.is_historical_low(item_id, price)

    async def aprice_30d_avg(self, item_id: str) -> float | None:
        return self.price_30d_avg(item_id)

    async def is_fake_discount(self, item_id: str, claimed_original: float, threshold: float = 0.80) -> bool:
        if claimed_original <= 0:
            return False
        with self._lock:
            rows = self.conn.execute(
                "select original_price from price_history where item_id=? and original_price is not null",
                (item_id,),
            ).fetchall()
        if len(rows) < 5:
            return False
        same = sum(1 for row in rows if abs(float(row["original_price"] or 0) - claimed_original) < 0.01)
        return same / len(rows) >= threshold

    async def real_discount_pct(self, item_id: str, current: float) -> int | None:
        cutoff = time() - 7 * 86400
        with self._lock:
            row = self.conn.execute(
                "select count(*) as total, avg(price) as avg_price from price_history where item_id=? and recorded_at>=?",
                (item_id, cutoff),
            ).fetchone()
        if not row or int(row["total"] or 0) < 3 or not row["avg_price"] or current <= 0:
            return None
        avg_price = float(row["avg_price"])
        if avg_price <= current:
            return 0
        return max(0, round((1 - current / avg_price) * 100))


def product_key(produto: dict) -> str:
    keys = product_keys(produto)
    return keys[0] if keys else ""


def product_keys(produto: dict) -> list[str]:
    keys: list[str] = []
    for field in ("id", "product_id", "item_id", "link_original", "link", "source_url"):
        key = canonical_product_key(produto.get(field))
        if key and key not in keys:
            keys.append(key)
    title_key = title_fingerprint(produto.get("titulo"))
    if title_key and title_key not in keys:
        keys.append(title_key)
    return keys


def title_fingerprint(title: object) -> str:
    text = str(title or "").lower()
    text = re.sub(r"\b\d+\s*(?:br|v|volts?|gb|tb|ml|kg|g|un|uni|unidade)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [word for word in text.split() if len(word) > 2]
    if len(words) < 3:
        return ""
    return "title:" + "-".join(words[:10])


def _legacy_product_key(produto: dict) -> str:
    raw = str(
        produto.get("id")
        or produto.get("product_id")
        or produto.get("item_id")
        or produto.get("link_original")
        or produto.get("link")
        or ""
    )
    return canonical_product_key(raw)


def canonical_product_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    fragment_query = parse_qs(parsed.fragment)
    for values in (query.get("wid"), fragment_query.get("wid")):
        if values:
            normalized = _normalize_mlb_id(values[0])
            if normalized:
                return normalized

    for pattern in (
        r"\b(MLB)[-_]?(\d{6,})\b",
        r"/p/(MLB\d+)",
        r"/offer/product_offer/(\d+)",
        r"[?&](?:itemid|item_id|product_id)=([^&#]+)",
    ):
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        if len(match.groups()) >= 2 and match.group(1).upper() == "MLB":
            return f"MLB{match.group(2)}"
        normalized = _normalize_mlb_id(match.group(1))
        return normalized or match.group(1)
    return text


def _normalize_mlb_id(value: object) -> str:
    match = re.search(r"\b(MLB)[-_]?(\d{6,})\b", str(value or ""), flags=re.I)
    return f"MLB{match.group(2)}" if match else ""


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("R$", "").replace(" ", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0
