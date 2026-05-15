"""Owner notifications and scheduled reports."""

from __future__ import annotations

import logging

import httpx

from config import Settings

log = logging.getLogger(__name__)


async def notify_owner(settings: Settings, text: str) -> None:
    owner_id = getattr(settings, "owner_telegram_id", None) or getattr(settings, "admin_telegram_id", None)
    token = settings.telegram_bot_token
    if not owner_id or not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": owner_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as exc:
        log.warning("Falha ao notificar owner: %s", exc)


async def send_weekly_report(settings: Settings, analytics: "Analytics") -> None:
    try:
        report = await analytics.get_weekly_report()
        top = report.get("top_product") or {}
        text = (
            "<b>Relatorio semanal</b>\n\n"
            f"Posts publicados: <b>{report.get('total_posts', 0)}</b>\n"
            f"Usuarios ativos: <b>{report.get('active_users', 0)}</b>\n"
            f"Canais ativos: <b>{report.get('active_channels', 0)}</b>\n"
            f"Erros: <b>{report.get('errors', 0)}</b>\n"
            f"Horario de pico: <b>{report.get('peak_hour', 0)}h</b>\n\n"
            f"Top produto: {top.get('title', 'sem dados')}"
        )
        await notify_owner(settings, text)
    except Exception as exc:
        log.warning("Falha ao gerar relatorio semanal: %s", exc)
