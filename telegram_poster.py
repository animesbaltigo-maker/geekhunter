"""Post messages and images to a Telegram channel."""

from __future__ import annotations

import logging
import json
from pathlib import Path

import httpx

from config import Settings

log = logging.getLogger(__name__)


async def postar_no_canal(
    texto: str,
    imagem_url: str | None,
    settings: Settings,
    link: str | None = None,
    reply_markup: dict | None = None,
) -> int | None:
    """Post to Telegram, or only log the post when DRY_RUN is enabled."""
    if settings.dry_run:
        log.info("DRY_RUN ativo. Post que seria enviado:\n%s", texto)
        return None

    if not settings.can_post_to_telegram:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHANNEL_ID para postar.")

    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        if not imagem_url:
            raise RuntimeError("Produto sem imagem confirmada; postagem bloqueada.")
        sent = await _postar_com_foto(client, base, texto, imagem_url, settings, link=link, reply_markup=reply_markup)
        if sent is not None:
            return sent
        raise RuntimeError("Falha ao enviar imagem do produto; postagem bloqueada para evitar preview errado.")


async def _postar_com_foto(
    client: httpx.AsyncClient,
    base: str,
    texto: str,
    imagem_url: str,
    settings: Settings,
    link: str | None = None,
    reply_markup: dict | None = None,
) -> int | None:
    payload = {
        "chat_id": settings.telegram_channel_id,
        "photo": imagem_url,
        "caption": texto,
        "parse_mode": "HTML",
        "show_caption_above_media": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    elif link:
        payload["reply_markup"] = buy_keyboard(link)
    local_image = _local_file(imagem_url)
    if local_image:
        data = {
            key: json.dumps(value) if key == "reply_markup" else str(value)
            for key, value in payload.items()
            if key != "photo"
        }
        with local_image.open("rb") as file_obj:
            resp = await client.post(
                f"{base}/sendPhoto",
                data=data,
                files={"photo": (local_image.name, file_obj, "image/png")},
            )
    else:
        resp = await client.post(
            f"{base}/sendPhoto",
            json=payload,
        )
    if resp.status_code == 200:
        log.info("Post com foto enviado.")
        return int((resp.json().get("result") or {}).get("message_id") or 0)
    log.warning("Falha ao enviar foto (%s): %s", resp.status_code, resp.text[:300])
    return None


async def _postar_texto(
    client: httpx.AsyncClient,
    base: str,
    texto: str,
    settings: Settings,
) -> None:
    resp = await client.post(
        f"{base}/sendMessage",
        json={
            "chat_id": settings.telegram_channel_id,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    resp.raise_for_status()
    log.info("Post de texto enviado.")


def buy_keyboard(link: str) -> dict:
    return {"inline_keyboard": [[{"text": "🛒 Comprar agora", "url": link}]]}


def _local_file(value: str) -> Path | None:
    if value.startswith(("http://", "https://")):
        return None
    path = Path(value)
    if path.exists() and path.is_file():
        return path
    return None
