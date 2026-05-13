"""Optional Mercado Livre seller-promotions source.

Docs covered:
- Ofertas do dia: promotion_type=DOD
- Ofertas relampago: promotion_type=LIGHTNING
- Campanhas tradicionais: promotion_type=DEAL

These endpoints are seller/campaign oriented. They only return products when
the logged-in seller has eligible/invited promotions.
"""

from __future__ import annotations

import logging

import httpx

from config import Settings
from ml_scraper import gerar_link_afiliado

log = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"
PROMOTION_TYPES = ("DOD", "LIGHTNING", "DEAL")


async def buscar_promocoes_oficiais(settings: Settings, limite: int = 20) -> list[dict]:
    if not settings.ml_access_token or not settings.ml_user_id:
        return []

    headers = {"Authorization": f"Bearer {settings.ml_access_token}"}
    produtos: list[dict] = []

    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers) as client:
        promotions = await _list_promotions(client, settings.ml_user_id)
        for promo in promotions:
            promo_type = promo.get("type")
            promo_id = promo.get("id")
            if promo_type not in PROMOTION_TYPES or not promo_id:
                continue
            items = await _list_promotion_items(client, promo_id, promo_type)
            for item in items:
                produto = _normalizar_promocao(item, promo_type, settings)
                if produto:
                    produtos.append(produto)
                if len(produtos) >= limite:
                    return produtos
    return produtos


async def _list_promotions(client: httpx.AsyncClient, user_id: str) -> list[dict]:
    resp = await client.get(
        f"{BASE_URL}/seller-promotions/users/{user_id}",
        params={"app_version": "v2"},
    )
    if resp.status_code != 200:
        log.warning("seller-promotions/users retornou HTTP %s", resp.status_code)
        return []
    return resp.json().get("results", [])


async def _list_promotion_items(client: httpx.AsyncClient, promo_id: str, promo_type: str) -> list[dict]:
    resp = await client.get(
        f"{BASE_URL}/seller-promotions/promotions/{promo_id}/items",
        params={"promotion_type": promo_type, "app_version": "v2", "status_item": "active"},
    )
    if resp.status_code != 200:
        log.warning("Itens da promocao %s/%s retornaram HTTP %s", promo_id, promo_type, resp.status_code)
        return []
    return resp.json().get("results", [])


def _normalizar_promocao(item: dict, promo_type: str, settings: Settings) -> dict | None:
    item_id = item.get("id") or item.get("item_id")
    title = item.get("title") or item.get("name") or item_id
    price = item.get("price") or item.get("deal_price") or item.get("top_deal_price") or 0
    original = item.get("original_price") or item.get("regular_price") or price
    permalink = item.get("permalink") or (f"https://www.mercadolivre.com.br/p/{item.get('catalog_product_id')}" if item.get("catalog_product_id") else "")
    if not item_id or not permalink:
        return None

    discount = 0
    if original and price and original > price:
        discount = round((1 - float(price) / float(original)) * 100)
    elif item.get("discount_percentage"):
        discount = round(float(item["discount_percentage"]))

    return {
        "id": item_id,
        "product_id": item.get("catalog_product_id") or "",
        "titulo": title,
        "preco_atual": float(price or 0),
        "preco_original": float(original or price or 0),
        "desconto_pct": discount,
        "link": gerar_link_afiliado(permalink, item_id, settings),
        "link_original": permalink,
        "imagem": item.get("thumbnail") or item.get("picture_url"),
        "vendidos": "",
        "avaliacao": 0,
        "frete_gratis": False,
        "parcelamento": None,
        "score": discount * 3,
        "promotion_type": promo_type,
    }
