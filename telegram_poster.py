"""Post messages and images to a Telegram channel."""

from __future__ import annotations

import logging

import httpx

from config import Settings

log = logging.getLogger(__name__)


async def postar_no_canal(texto: str, imagem_url: str | None, settings: Settings) -> None:
    """Post to Telegram, or only log the post when DRY_RUN is enabled."""
    if settings.dry_run:
        log.info("DRY_RUN ativo. Post que seria enviado:\n%s", texto)
        return

    if not settings.can_post_to_telegram:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHANNEL_ID para postar.")

    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        if not imagem_url:
            raise RuntimeError("Produto sem imagem confirmada; postagem bloqueada.")
        sent = await _postar_com_foto(client, base, texto, imagem_url, settings)
        if sent:
            return
        raise RuntimeError("Falha ao enviar imagem do produto; postagem bloqueada para evitar preview errado.")


async def _postar_com_foto(
    client: httpx.AsyncClient,
    base: str,
    texto: str,
    imagem_url: str,
    settings: Settings,
) -> bool:
    resp = await client.post(
        f"{base}/sendPhoto",
        json={
            "chat_id": settings.telegram_channel_id,
            "photo": imagem_url,
            "caption": texto,
            "parse_mode": "HTML",
            "show_caption_above_media": False,
        },
    )
    if resp.status_code == 200:
        log.info("Post com foto enviado.")
        return True
    log.warning("Falha ao enviar foto (%s): %s", resp.status_code, resp.text[:300])
    return False


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
