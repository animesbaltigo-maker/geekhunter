"""Runtime health checks and optional HTTP health endpoint."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from config import Settings
from storage import Storage

log = logging.getLogger(__name__)
STARTED_AT = monotonic()
_storage: Storage | None = None
_settings: Settings | None = None


def configure_health(settings: Settings, storage: Storage) -> None:
    global _settings, _storage
    _settings = settings
    _storage = storage


def basic_health(settings: Settings, storage: Storage) -> dict[str, object]:
    db_ok = storage.ping()
    stats = storage.admin_stats()
    checks = {
        "sqlite": db_ok,
        "telegram_token": bool(settings.telegram_bot_token),
        "owner_channel": bool(settings.telegram_channel_id),
        "product_source": settings.product_source,
        "dry_run": settings.dry_run,
    }
    return {
        "status": "ok" if all(value for key, value in checks.items() if key != "dry_run") else "attention",
        "uptime_seconds": int(monotonic() - STARTED_AT),
        "checks": checks,
        "stats": stats,
    }


def format_health_report(report: dict[str, object]) -> str:
    checks = report.get("checks") or {}
    lines = [f"<b>Health:</b> {report.get('status')}", f"uptime: <b>{report.get('uptime_seconds', 0)}s</b>"]
    for key, value in checks.items():
        marker = "OK" if value else "ATENCAO"
        if key == "dry_run":
            marker = "ON" if value else "OFF"
        lines.append(f"- {key}: <b>{marker}</b>")
    stats = report.get("stats") or {}
    if stats:
        lines.extend(
            [
                "",
                "<b>Resumo:</b>",
                f"- usuarios: <b>{stats.get('users', 0)}</b>",
                f"- canais: <b>{stats.get('channels', 0)}</b>",
                f"- posts hoje: <b>{stats.get('posts_today', 0)}</b>",
                f"- erros 7d: <b>{stats.get('errors_7d', 0)}</b>",
            ]
        )
    return "\n".join(lines)


async def health_handler(_request) -> object:
    if not _settings or not _storage:
        return {"status": "down", "reason": "health not configured"}
    return basic_health(_settings, _storage)


async def start_health_server(settings: Settings, storage: Storage | None = None) -> None:
    try:
        from aiohttp import web
    except ImportError:
        log.warning("aiohttp nao instalado; health HTTP desativado.")
        return

    if storage:
        configure_health(settings, storage)

    async def handler(_request: web.Request) -> web.Response:
        report = await health_handler(_request)
        return web.json_response(report)

    app = web.Application()
    app.router.add_get("/health", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(settings.health_port))
    await site.start()
    log.info("Health server ativo na porta %s.", settings.health_port)
    while True:
        await asyncio.sleep(3600)
