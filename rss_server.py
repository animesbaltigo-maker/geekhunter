"""Small RSS server for recent posts."""

from __future__ import annotations

import asyncio
import email.utils
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

from config import Settings
from storage import Storage

log = logging.getLogger(__name__)


async def start_rss_server(settings: Settings, storage: Storage) -> None:
    if not getattr(settings, "rss_enabled", False):
        return
    try:
        from aiohttp import web
    except ImportError:
        log.warning("aiohttp nao instalado; RSS desativado.")
        return

    async def rss_handler(_request: web.Request) -> web.Response:
        posts = storage.get_recent_posts(hours=72, limit=50)
        return web.Response(text=_build_rss(posts), content_type="application/rss+xml")

    app = web.Application()
    app.router.add_get("/rss.xml", rss_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(settings.rss_port))
    await site.start()
    log.info("RSS ativo na porta %s.", settings.rss_port)
    while True:
        await asyncio.sleep(3600)


def _build_rss(posts: list) -> str:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "ML Affiliate Bot - Ofertas"
    ET.SubElement(channel, "link").text = "https://t.me/"
    ET.SubElement(channel, "description").text = "Ultimas ofertas publicadas"
    for post in posts:
        item = ET.SubElement(channel, "item")
        url = post["affiliate_url"] or post["product_url"]
        ET.SubElement(item, "title").text = post["product_url"]
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid").text = f"{post['channel_id']}:{post['telegram_message_id'] or post['id']}"
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(
            datetime.fromtimestamp(float(post["created_at"]))
        )
    return ET.tostring(root, encoding="unicode")
