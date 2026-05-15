"""Shared HTTP helpers with conservative retry behavior."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)
T = TypeVar("T")


TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    base_delay: float = 1.0,
    label: str = "http",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return await operation()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt >= retries - 1:
                break
            delay = base_delay * (2**attempt)
            log.warning("%s falhou temporariamente; retry em %.1fs", label, delay)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{label} falhou apos {retries} tentativas")


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    **kwargs,
) -> httpx.Response:
    async def _request() -> httpx.Response:
        resp = await client.request(method, url, **kwargs)
        if resp.status_code == 429:
            retry_after = _retry_after_seconds(resp)
            if retry_after > 0:
                log.warning("HTTP 429; aguardando %.1fs antes de repetir", retry_after)
                await asyncio.sleep(retry_after)
                raise httpx.TimeoutException("rate limited")
        if resp.status_code in TRANSIENT_STATUS and resp.status_code != 429:
            raise httpx.RemoteProtocolError(f"HTTP transitorio {resp.status_code}")
        return resp

    return await with_retry(_request, retries=retries, label=f"{method.upper()} {safe_url_label(url)}")


async def get_with_retry(client: httpx.AsyncClient, url: str, *, retries: int = 3, **kwargs) -> httpx.Response:
    return await request_with_retry(client, "GET", url, retries=retries, **kwargs)


async def post_with_retry(client: httpx.AsyncClient, url: str, *, retries: int = 3, **kwargs) -> httpx.Response:
    return await request_with_retry(client, "POST", url, retries=retries, **kwargs)


def safe_url_label(url: str) -> str:
    return url.split("?", 1)[0].replace("https://api.telegram.org/bot", "https://api.telegram.org/bot***")


def _retry_after_seconds(resp: httpx.Response) -> float:
    try:
        data = resp.json()
        return float((data.get("parameters") or {}).get("retry_after") or 0)
    except Exception:
        return 0.0
