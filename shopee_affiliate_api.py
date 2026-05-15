"""Shopee Affiliate Open API client."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

import httpx

from config import Settings
from link_resolver import ResolvedLink, extract_product_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShopeeIds:
    shop_id: str
    item_id: str


class ShopeeAffiliateAPI:
    def __init__(self, settings: Settings) -> None:
        self.app_id = settings.shopee_affiliate_app_id
        self.secret = settings.shopee_affiliate_secret
        self.api_url = settings.shopee_affiliate_api_url
        self.timeout = settings.request_timeout

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.secret and self.api_url)

    async def graphql(self, payload: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Shopee Affiliate API nao configurada.")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())
        signature_base = f"{self.app_id}{timestamp}{body}{self.secret}"
        signature = hashlib.sha256(signature_base.encode("utf-8")).hexdigest()
        headers = {
            "Authorization": f"SHA256 Credential={self.app_id},Timestamp={timestamp},Signature={signature}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.api_url, content=body.encode("utf-8"), headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errors"):
            raise RuntimeError(_format_graphql_error(data["errors"]))
        return data.get("data") or {}

    async def product_from_link(self, url: str, resolved: ResolvedLink | None = None) -> dict | None:
        ids = shopee_ids_from_url((resolved.final_url if resolved else "") or url) or shopee_ids_from_url(url)
        if not ids:
            product_id = extract_product_id(url, "shopee")
            if product_id and ":" in product_id:
                shop_id, item_id = product_id.split(":", 1)
                ids = ShopeeIds(shop_id=shop_id, item_id=item_id)
        if not ids:
            return None

        query = """
        query ProductOffer($itemId: String!, $shopId: String!) {
          productOfferV2(itemId: $itemId, shopId: $shopId, limit: 1) {
            nodes {
              itemId
              shopId
              productName
              productLink
              imageUrl
              price
              priceMin
              priceMax
              ratingStar
              sales
              commissionRate
              sellerName
            }
          }
        }
        """
        data = await self.graphql({"query": query, "variables": {"itemId": ids.item_id, "shopId": ids.shop_id}})
        nodes = (((data.get("productOfferV2") or {}).get("nodes")) or [])
        if not nodes:
            return None
        return _node_to_product(nodes[0], url, ids)

    async def generate_short_link(self, origin_url: str, sub_ids: list[str] | None = None) -> str | None:
        query = """
        mutation GenerateShortLink($originUrl: String!, $subIds: [String]) {
          generateShortLink(input: {originUrl: $originUrl, subIds: $subIds}) {
            shortLink
          }
        }
        """
        data = await self.graphql({"query": query, "variables": {"originUrl": origin_url, "subIds": sub_ids or []}})
        return ((data.get("generateShortLink") or {}).get("shortLink")) or None


def shopee_ids_from_url(url: str) -> ShopeeIds | None:
    product_id = extract_product_id(url, "shopee")
    if product_id and ":" in product_id:
        shop_id, item_id = product_id.split(":", 1)
        return ShopeeIds(shop_id=shop_id, item_id=item_id)
    return None


def _node_to_product(node: dict, original_url: str, ids: ShopeeIds) -> dict:
    current = _price_to_float(node.get("price") or node.get("priceMin"))
    price_min = _price_to_float(node.get("priceMin"))
    price_max = _price_to_float(node.get("priceMax"))
    original = price_max if price_max and price_max > current else current
    return {
        "id": f"shopee:{ids.shop_id}:{ids.item_id}",
        "product_id": f"{ids.shop_id}:{ids.item_id}",
        "platform": "shopee",
        "titulo": str(node.get("productName") or "").strip(),
        "preco_atual": current,
        "preco_original": original,
        "desconto_pct": _discount(current, original),
        "desconto_estimado": False,
        "imagem": node.get("imageUrl"),
        "link": original_url,
        "link_original": original_url,
        "source_url": node.get("productLink") or original_url,
        "vendidos": node.get("sales") or "",
        "avaliacao": _price_to_float(node.get("ratingStar")),
        "frete_gratis": False,
        "parcelamento": None,
        "score": 0,
        "seller_name": node.get("sellerName"),
        "commission_rate": node.get("commissionRate"),
        "extraction_verified": True,
    }


def _price_to_float(value: object) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace("R$", "").replace("BRL", "").replace(" ", "")
    try:
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        return float(text)
    except ValueError:
        return 0.0


def _discount(current: float, original: float) -> int:
    if current <= 0 or original <= current:
        return 0
    return max(1, round((1 - current / original) * 100))


def _format_graphql_error(errors: list[dict]) -> str:
    first = errors[0] if errors else {}
    message = str(first.get("message") or "erro desconhecido")
    return f"Shopee Affiliate API falhou: {message}"
