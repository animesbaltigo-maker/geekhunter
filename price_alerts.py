"""User price alert service."""

from __future__ import annotations

import asyncio
import logging
from time import time

from config import Settings
from price_history import _to_float, product_key
from product_extractor import extrair_produto
from storage import Storage
from telegram_client import TelegramClient

log = logging.getLogger(__name__)


class PriceAlertService:
    def __init__(self, storage: Storage, tg: TelegramClient, settings: Settings) -> None:
        self.storage = storage
        self.tg = tg
        self.settings = settings

    async def add_alert(
        self,
        user_id: int,
        product_url: str,
        target_price: float | None,
        notify_any_drop: bool = False,
    ) -> dict:
        produto = await extrair_produto(product_url, self.settings.request_timeout, use_browser=False, strict=False)
        produto["link"] = product_url
        item_id = product_key(produto) or product_url
        current = _to_float(produto.get("preco_atual"))
        with self.storage._lock:
            cur = self.storage.conn.execute(
                """
                insert into price_alerts
                    (telegram_user_id, item_id, product_url, affiliate_url, product_title, image_url,
                     current_price, target_price, platform, notify_any_drop, status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    user_id,
                    item_id,
                    product_url,
                    product_url,
                    produto.get("titulo"),
                    produto.get("imagem"),
                    current,
                    target_price,
                    produto.get("platform"),
                    1 if notify_any_drop else 0,
                    time(),
                ),
            )
            self.storage.conn.commit()
            alert_id = int(cur.lastrowid)
        return {"id": alert_id, "item_id": item_id, "title": produto.get("titulo"), "current_price": current}

    async def list_alerts(self, user_id: int) -> list[dict]:
        with self.storage._lock:
            rows = self.storage.conn.execute(
                "select * from price_alerts where telegram_user_id=? and status='active' order by created_at desc",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    async def cancel_alert(self, alert_id: int, user_id: int) -> bool:
        with self.storage._lock:
            cur = self.storage.conn.execute(
                "update price_alerts set status='cancelled' where id=? and telegram_user_id=?",
                (alert_id, user_id),
            )
            self.storage.conn.commit()
        return cur.rowcount > 0

    async def checker_loop(self) -> None:
        interval = max(1, int(self.settings.price_alert_check_interval or 30))
        while True:
            await asyncio.sleep(interval * 60)
            await self.check_once()

    async def check_once(self) -> None:
        with self.storage._lock:
            rows = self.storage.conn.execute(
                "select * from price_alerts where status='active' order by coalesce(last_checked_at, 0) asc limit 50"
            ).fetchall()
        for row in rows:
            try:
                produto = await extrair_produto(row["product_url"], self.settings.request_timeout, use_browser=False, strict=False)
                current = _to_float(produto.get("preco_atual"))
                if current <= 0:
                    continue
                should_notify = False
                target = _to_float(row["target_price"])
                previous = _to_float(row["current_price"])
                if target > 0 and current <= target:
                    should_notify = True
                if int(row["notify_any_drop"] or 0) and previous > 0 and current < previous:
                    should_notify = True
                with self.storage._lock:
                    self.storage.conn.execute(
                        """
                        update price_alerts set current_price=?, last_checked_at=?
                        where id=?
                        """,
                        (current, time(), row["id"]),
                    )
                    self.storage.conn.execute(
                        """
                        insert or ignore into price_history
                            (item_id, price, original_price, discount_pct, source, recorded_at)
                        values (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["item_id"],
                            current,
                            _to_float(produto.get("preco_original")),
                            int(_to_float(produto.get("desconto_pct")) or 0),
                            "alert",
                            time(),
                        ),
                    )
                    self.storage.conn.commit()
                if should_notify:
                    await self._notify(row, current)
            except Exception as exc:
                log.warning("Falha ao checar alerta %s: %s", row["id"], exc)

    async def _notify(self, row, current: float) -> None:
        text = (
            "<b>Alerta de preco</b>\n\n"
            f"{row['product_title'] or row['product_url']}\n"
            f"Preco atual: <b>R$ {current:.2f}</b>\n\n"
            f"{row['affiliate_url'] or row['product_url']}"
        )
        await self.tg.send_message(row["telegram_user_id"], text, disable_web_page_preview=False)
        with self.storage._lock:
            self.storage.conn.execute(
                "update price_alerts set status='triggered', triggered_at=? where id=?",
                (time(), row["id"]),
            )
            self.storage.conn.commit()
