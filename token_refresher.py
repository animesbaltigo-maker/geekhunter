"""Automatic Mercado Livre token refresh."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from config import Settings
from meli_oauth import TOKEN_URL, update_env
from notifier import notify_owner

log = logging.getLogger(__name__)


async def token_refresh_loop(settings: Settings) -> None:
    while True:
        await asyncio.sleep(5 * 3600)
        try:
            new_token, new_refresh = await _renovar(settings)
            updates = {"ML_ACCESS_TOKEN": new_token}
            if new_refresh:
                updates["ML_REFRESH_TOKEN"] = new_refresh
            update_env(Path(".env"), updates)
            object.__setattr__(settings, "ml_access_token", new_token)
            if new_refresh:
                object.__setattr__(settings, "ml_refresh_token", new_refresh)
            log.info("Acesso ML renovado.")
        except Exception as exc:
            log.error("Falha na renovacao ML: %s", exc)
            await notify_owner(settings, f"Falha ao renovar acesso Mercado Livre: {exc}")


async def _renovar(settings: Settings) -> tuple[str, str | None]:
    if not settings.ml_app_id or not settings.ml_secret_key or not settings.ml_refresh_token:
        raise RuntimeError("credenciais ML incompletas para refresh")
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.ml_app_id,
        "client_secret": settings.ml_secret_key,
        "refresh_token": settings.ml_refresh_token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, data=payload)
        resp.raise_for_status()
        data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("ML nao retornou access_token")
    return str(token), data.get("refresh_token")
