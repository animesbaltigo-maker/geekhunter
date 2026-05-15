"""Optional outgoing webhook after successful posts."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from config import Settings

log = logging.getLogger(__name__)


async def fire(settings: Settings, produto: dict, post_data: dict) -> None:
    if not getattr(settings, "outgoing_webhook_url", None):
        return
    payload = {
        "event": "post_published",
        "timestamp": datetime.now().isoformat(),
        "product": {
            "title": produto.get("titulo"),
            "price": produto.get("preco_atual"),
            "original_price": produto.get("preco_original"),
            "discount_pct": produto.get("desconto_pct"),
            "image": produto.get("imagem"),
            "link": produto.get("link") or produto.get("link_original"),
            "platform": produto.get("platform"),
            "free_shipping": produto.get("frete_gratis"),
        },
        "channel": post_data.get("channel_id"),
        "telegram_message_id": post_data.get("message_id"),
    }
    headers = {"X-Webhook-Secret": getattr(settings, "outgoing_webhook_secret", "") or ""}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.outgoing_webhook_url, json=payload, headers=headers)
    except Exception as exc:
        log.warning("Webhook de saida falhou: %s", exc)
