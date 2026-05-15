"""Read public Mercado Livre offer pages and normalize visible deal cards."""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from config import Settings
from ml_scraper import gerar_link_afiliado
from offer_quality import score_product
from price_history import product_key

log = logging.getLogger(__name__)

OFFER_PAGE_URLS = [
    "https://www.mercadolivre.com.br/ofertas#nav-header",
    "https://www.mercadolivre.com.br/ofertas?container_id=MLB779362-1&promotion_type=lightning#filter_applied=promotion_type&filter_position=2&is_recommended_domain=false&origin=scut",
    "https://www.mercadolivre.com.br/ofertas?container_id=MLB1298579-1&deal_ids=MLB1298579#filter_applied=container_id&filter_position=3&is_recommended_domain=false&origin=scut",
]


async def buscar_ofertas_paginas_ml(settings: Settings, limite: int = 60) -> list[dict]:
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    }
    produtos: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers, follow_redirects=True) as client:
        for url in OFFER_PAGE_URLS:
            if len(produtos) >= limite:
                break
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                for produto in _parse_offer_page(resp.text, settings):
                    key = product_key(produto)
                    if key and key not in produtos:
                        produtos[key] = produto
                    if len(produtos) >= limite:
                        break
            except httpx.HTTPError as exc:
                log.warning("Falha ao ler pagina de ofertas ML %s: %s", url, exc)

    ranked = sorted(produtos.values(), key=lambda item: item.get("score", 0), reverse=True)
    log.info("%s ofertas encontradas nas paginas publicas do ML.", len(ranked))
    return ranked[:limite]


def _parse_offer_page(html: str, settings: Settings) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".poly-card")
    produtos: list[dict] = []
    for card in cards:
        produto = _parse_card(card, settings)
        if produto:
            produtos.append(produto)
    return produtos


def _parse_card(card, settings: Settings) -> dict | None:
    title_node = card.select_one(".poly-component__title")
    image_node = card.select_one(".poly-component__picture")
    if not title_node or not image_node:
        return None

    title = _clean_text(title_node.get_text(" ", strip=True))
    permalink = urljoin("https://www.mercadolivre.com.br", title_node.get("href") or "")
    image = image_node.get("data-src") or image_node.get("src") or ""
    if not title or not permalink or not image:
        return None

    old_price = _extract_previous_price(card)
    current_price = _extract_current_price(card)
    discount = _extract_discount(card)
    if current_price <= 0:
        return None
    if old_price <= current_price and discount > 0:
        old_price = round(current_price / (1 - discount / 100), 2)
    if old_price <= current_price:
        return None
    if discount <= 0:
        discount = round((1 - current_price / old_price) * 100)
    if discount < settings.min_discount_pct:
        return None
    if settings.max_price and current_price > settings.max_price:
        return None

    item_id = _extract_item_id(permalink)
    rating = _extract_rating(card)
    sold = _extract_sold(card)
    free_shipping = bool(card.select_one(".poly-component__shipping"))
    produto = {
        "id": item_id or permalink,
        "product_id": item_id or "",
        "titulo": title,
        "preco_atual": current_price,
        "preco_original": old_price,
        "desconto_pct": discount,
        "link": gerar_link_afiliado(permalink, item_id or "", settings),
        "link_original": permalink,
        "imagem": _large_image(image),
        "vendidos": sold,
        "avaliacao": rating,
        "frete_gratis": free_shipping,
        "parcelamento": _extract_installments(card),
        "platform": "mercadolivre",
        "source": "ml_deals_page",
    }
    produto["score"] = score_product(produto, settings)
    return produto


def _extract_previous_price(card) -> float:
    node = card.select_one(".andes-money-amount--previous")
    return _money_from_node(node)


def _extract_current_price(card) -> float:
    node = card.select_one(".poly-price__current .andes-money-amount")
    if not node:
        amounts = card.select(".andes-money-amount")
        node = amounts[0] if amounts else None
    return _money_from_node(node)


def _money_from_node(node) -> float:
    if not node:
        return 0.0
    aria = node.get("aria-label") or ""
    parsed = _money_from_aria(aria)
    if parsed > 0:
        return parsed
    fraction = _clean_text("".join(part.get_text(strip=True) for part in node.select(".andes-money-amount__fraction")))
    cents_node = node.select_one(".andes-money-amount__cents")
    cents = _clean_text(cents_node.get_text(strip=True)) if cents_node else "00"
    if not fraction:
        return 0.0
    try:
        return float(f"{fraction.replace('.', '')}.{cents[:2].zfill(2)}")
    except ValueError:
        return 0.0


def _money_from_aria(text: str) -> float:
    text = unescape(text or "").lower()
    match = re.search(r"(\d[\d.]*)\s+reais(?:\s+com\s+(\d{1,2})\s+centavos?)?", text)
    if not match:
        return 0.0
    reais = match.group(1).replace(".", "")
    cents = (match.group(2) or "00").zfill(2)
    try:
        return float(f"{reais}.{cents}")
    except ValueError:
        return 0.0


def _extract_discount(card) -> int:
    node = card.select_one(".poly-price__disc_label")
    text = _clean_text(node.get_text(" ", strip=True)) if node else card.get_text(" ", strip=True)
    match = re.search(r"(\d{1,2})\s*%\s*OFF", text, flags=re.I)
    return int(match.group(1)) if match else 0


def _extract_rating(card) -> float:
    node = card.select_one(".poly-reviews__rating")
    if not node:
        return 0.0
    try:
        return float(node.get_text(strip=True).replace(",", "."))
    except ValueError:
        return 0.0


def _extract_sold(card) -> int:
    text = _clean_text(card.get_text(" ", strip=True)).lower()
    match = re.search(r"(\d[\d.]*)\s+vendidos", text)
    if not match:
        return 0
    return int(match.group(1).replace(".", ""))


def _extract_installments(card) -> str | None:
    node = card.select_one(".poly-price__installments")
    if not node:
        return None
    text = _clean_text(node.get_text(" ", strip=True))
    if "sem juros" not in text.lower():
        return None
    return text[:120]


def _extract_item_id(url: str) -> str:
    patterns = [
        r"[?&]wid=(MLB\d+)",
        r"\b(MLB)[-_]?(\d{6,})\b",
        r"/p/(MLB\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            if len(match.groups()) >= 2 and match.group(1).upper() == "MLB":
                return f"MLB{match.group(2)}"
            return match.group(1)
    return ""


def _large_image(url: str) -> str:
    return (
        url.replace("D_Q_NP_2X_", "D_NQ_NP_2X_")
        .replace("-AB.webp", "-O.webp")
        .replace("-I.jpg", "-O.jpg")
        .replace("I.jpg", "O.jpg")
    )


def _clean_text(value: str) -> str:
    return " ".join(unescape(value or "").split())
