"""Extract product data from affiliate/product URLs across common marketplaces."""

from __future__ import annotations

import asyncio
import os
import json
import re
from html import unescape
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SUPPORTED_PLATFORMS = {
    "mercadolivre": ("mercadolivre", "meli.la"),
    "amazon": ("amazon.", "amzn.to"),
    "shopee": ("shopee.", "s.shopee"),
    "shein": ("shein.",),
    "aliexpress": ("aliexpress.", "s.click.aliexpress"),
    "magalu": ("magazineluiza.", "magalu."),
    "natura": ("natura.",),
}
PRODUCT_ID_RE = re.compile(r"/p/(MLB\d+)|\b(MLB\d{6,})\b")
ITEM_ID_RE = re.compile(r"(?:wid=|item_id=|/)(MLB\d{6,})\b", re.I)
MLB_URL_ID_RE = re.compile(r"\bMLB-?(\d{6,})\b", re.I)
BR_PRICE_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})")
SPLIT_PRICE_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)(?:\s|,)([0-9]{2})")
WHOLE_PRICE_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)(?!\s*[,\.]?\s*\d{2})(?![0-9])")


async def extrair_produto(
    product_url: str,
    timeout: float = 25,
    use_browser: bool = True,
    strict: bool = True,
    cdp_url: str | None = None,
) -> dict:
    platform = detect_platform(product_url)
    if not platform:
        raise ValueError("Envie um link de marketplace suportado: Mercado Livre, Amazon, Shopee, Shein, AliExpress, Magalu ou Natura.")

    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AppleWebKit/537.36",
        "accept-language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    html_text = ""
    final_url = product_url
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(product_url)
            resp.raise_for_status()
            final_url = str(resp.url)
            html_text = resp.text
            platform = detect_platform(final_url) or platform
    except Exception:
        html_text = ""

    produto = _extract_from_html(final_url, html_text, platform)
    ml_item_details = None
    ml_api_price = None
    if platform == "mercadolivre":
        ml_item_details = await _extract_mercadolivre_api_item(final_url, html_text, timeout)
        if ml_item_details:
            produto.update(ml_item_details)
        ml_api_price = await _extract_mercadolivre_api_price(final_url, html_text, timeout)
        if ml_api_price:
            produto.update(ml_api_price)
    if use_browser and (_needs_browser(produto) or platform in {"mercadolivre", "shopee"}):
        context = None
        try:
            rendered = await asyncio.to_thread(_extract_with_browser, final_url, platform, cdp_url)
            if produto.get("price_source") == "mercadolivre_api":
                for key, value in rendered.items():
                    if key not in {"preco_atual", "preco_original", "desconto_pct", "desconto_estimado"} and value not in (None, "", 0):
                        produto[key] = value
            else:
                produto.update({k: v for k, v in rendered.items() if v not in (None, "", 0)})
            if ml_item_details:
                produto.update({k: v for k, v in ml_item_details.items() if v not in (None, "", 0)})
            if ml_api_price:
                produto.update(ml_api_price)
            produto["extraction_verified"] = True
        except Exception:
            produto["extraction_verified"] = False

    produto = _normalize_prices(produto)
    _validate_product(produto, strict=strict)
    produto["link"] = product_url
    produto["link_original"] = product_url
    produto["source_url"] = final_url
    produto["platform"] = platform
    return produto


def detect_platform(url: str) -> str | None:
    text = (url or "").lower()
    for platform, hints in SUPPORTED_PLATFORMS.items():
        if any(hint in text for hint in hints):
            return platform
    return None


def _extract_from_html(final_url: str, html_text: str, platform: str) -> dict:
    specific = _extract_specific_platform(final_url, html_text, platform)
    if _produto_valido_interno(specific):
        return specific

    soup = BeautifulSoup(html_text or "", "html.parser")
    body_text = soup.get_text("\n", strip=True)
    title_candidates = [*_html_title_candidates(soup)]
    if platform == "mercadolivre":
        title_candidates.extend(_mercadolivre_title_candidates_from_text(body_text))
    title_candidates.extend(
        [
            _meta(soup, "og:title") or "",
            _meta(soup, "twitter:title") or "",
            _title(soup) or "",
        ]
    )
    title = _choose_best_title(
        title_candidates
    )
    image = _meta(soup, "og:image") or _meta(soup, "twitter:image")
    product_id = _product_id(final_url) or _product_id(html_text or "")
    structured = _extract_structured_data(soup)
    meta_price = (
        _meta(soup, "product:price:amount")
        or _meta(soup, "og:price:amount")
        or _meta(soup, "twitter:data1")
        or _itemprop(soup, "price")
        or _itemprop(soup, "lowPrice")
    )
    current_price, original_price, discount_badge = _choose_prices_from_text(body_text or html_text or "", platform=platform)

    fallback_price = structured.get("price") or _parse_any_money(meta_price)
    if not _has_coherent_discount_pair(current_price, original_price, discount_badge):
        current_price = fallback_price or current_price
    original_price = structured.get("original_price") or original_price

    final_image = image or structured.get("image")
    return {
        "id": product_id or final_url,
        "product_id": product_id,
        "platform": platform,
        "titulo": clean_title(title or structured.get("title") or "Oferta selecionada"),
        "preco_atual": current_price or 0,
        "preco_original": original_price or current_price or 0,
        "desconto_pct": discount_badge or _discount(current_price, original_price),
        "desconto_estimado": False,
        "link": final_url,
        "link_original": final_url,
        "source_url": final_url,
        "imagem": final_image,
        "vendidos": _extract_sold(html_text or ""),
        "avaliacao": _extract_rating(html_text or ""),
        "frete_gratis": _has_free_shipping(html_text or ""),
        "parcelamento": None,
        "score": 0,
        "extraction_verified": bool(html_text and final_image and (current_price or title or structured.get("title"))),
    }


def _extract_specific_platform(final_url: str, html_text: str, platform: str) -> dict:
    if platform == "mercadolivre" and "/social/" in final_url:
        return _extract_mercadolivre_social(html_text, final_url)
    if platform == "shopee":
        return _extract_shopee(html_text, final_url)
    if platform == "amazon":
        return _extract_amazon(html_text, final_url)
    if platform == "shein":
        return _extract_shein(html_text, final_url)
    if platform == "aliexpress":
        return _extract_aliexpress(html_text, final_url)
    if platform == "magalu":
        return _extract_magalu(html_text, final_url)
    if platform == "natura":
        return _extract_natura(html_text, final_url)
    return {}


def _extract_mercadolivre_social(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    title = _meta(soup, "og:title") or _meta(soup, "twitter:title")
    image = _meta(soup, "og:image") or _meta(soup, "twitter:image") or _meta(soup, "image")
    card = _extract_ml_social_matching_card(html_text or "", title or "", image or "")
    current = card.get("preco_atual") if card else None
    original = card.get("preco_original") if card else None
    discount = int(card.get("desconto_pct") or 0) if card else 0
    item_id = card.get("id") if card else _item_id(html_text)
    if not current:
        match = re.search(
            r'"previous_price":\{"value":([0-9.]+).*?"current_price":\{"value":([0-9.]+).*?'
            r'(?:"discount(?:_label)?":\{(?:"value":([0-9]+)|"text":"([0-9]+)%))?',
            html_text or "",
            re.S,
        )
        if match:
            original = _parse_any_money(match.group(1))
            current = _parse_any_money(match.group(2))
            discount = int(match.group(3) or match.group(4) or _discount(current, original) or 0)
    return _normalize_prices(
        {
            "id": item_id or url,
            "product_id": item_id,
            "platform": "mercadolivre",
            "titulo": clean_title(title or "Oferta selecionada"),
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": discount or _discount(current, original),
            "desconto_estimado": False,
            "link": url,
            "link_original": url,
            "source_url": url,
            "imagem": image,
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": None,
            "score": 0,
            "extraction_verified": bool(title and image and current),
        }
    )


def _extract_ml_social_matching_card(html_text: str, meta_title: str, meta_image: str = "") -> dict | None:
    best: tuple[float, dict] | None = None
    meta_picture_id = _ml_picture_id(meta_image)
    title_re = re.compile(r'"title":\{"text":"([^"]+)"', re.S)
    for match in title_re.finditer(html_text or ""):
        raw_title = _jsonish_unescape(match.group(1))
        score = _title_similarity(raw_title, meta_title) if meta_title else 0.1
        if meta_title and score < 0.35:
            continue
        start = max(0, match.start() - 2200)
        end = min(len(html_text), match.end() + 3500)
        chunk = html_text[start:end]
        current_match = re.search(r'"current_price":\{"value":([0-9.]+)', chunk)
        if not current_match:
            continue
        previous_match = re.search(r'"previous_price":\{"value":([0-9.]+)', chunk)
        discount_match = re.search(r'"discount(?:_label)?":\{(?:"value":([0-9]+)|"text":"([0-9]+)%[^"]*")', chunk)
        item_match = re.search(r'"metadata":\{"id":"(MLB\d+)"', chunk)
        picture_match = re.search(r'"pictures":\[\{"id":"([^"]+)"', chunk)
        picture_id = picture_match.group(1) if picture_match else ""
        if meta_picture_id and picture_id and picture_id not in meta_picture_id and meta_picture_id not in picture_id:
            continue
        if meta_picture_id and picture_id:
            score += 2.0
        current = _parse_any_money(current_match.group(1))
        previous = _parse_any_money(previous_match.group(1)) if previous_match else current
        discount = int((discount_match.group(1) or discount_match.group(2)) if discount_match else _discount(current, previous) or 0)
        image = None
        if picture_id:
            image = f"https://http2.mlstatic.com/D_NQ_NP_{picture_id}-O.webp"
        item = {
            "id": item_match.group(1) if item_match else None,
            "titulo": clean_title(raw_title),
            "preco_atual": current or 0,
            "preco_original": previous or current or 0,
            "desconto_pct": discount,
            "imagem": image,
        }
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def _ml_picture_id(url: str) -> str:
    match = re.search(r"D_NQ_NP_([^._/-]+(?:-[^._/-]+)?)", url or "")
    return match.group(1) if match else ""


def _jsonish_unescape(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace("\\u002F", "/").replace("\\/", "/")


def _title_similarity(left: str, right: str) -> float:
    a = {word for word in re.findall(r"[\wÀ-ÿ]+", left.lower()) if len(word) > 2}
    b = {word for word in re.findall(r"[\wÀ-ÿ]+", right.lower()) if len(word) > 2}
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def _produto_valido_interno(produto: dict) -> bool:
    title = str(produto.get("titulo") or "").strip()
    image = str(produto.get("imagem") or "").strip()
    price = float(produto.get("preco_atual") or 0)
    return bool(title) and not _bad_product_title(title) and bool(image) and not _bad_image_url(image) and price > 0


def _extract_shopee(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = {
        "id": url,
        "product_id": None,
        "link": url,
        "link_original": url,
        "source_url": url,
        "platform": "shopee",
        "desconto_estimado": False,
        "score": 0,
    }

    title = _meta(soup, "og:title") or _meta(soup, "twitter:title")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else None
    image = _meta(soup, "og:image") or _meta(soup, "twitter:image")
    current, original, discount = _choose_prices_from_text(soup.get_text("\n", strip=True) or html_text, platform="shopee")

    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": image,
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": discount or _discount(current, original),
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": None,
            "extraction_verified": bool(title and image),
        }
    )
    return _normalize_prices(produto)


def _extract_amazon(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = {
        "id": url,
        "product_id": None,
        "link": url,
        "link_original": url,
        "source_url": url,
        "platform": "amazon",
        "desconto_estimado": False,
        "score": 0,
    }

    title_el = soup.find(id="productTitle")
    title = title_el.get_text(" ", strip=True) if title_el else None
    title = title or _meta(soup, "og:title") or _meta(soup, "twitter:title") or _title(soup)

    image = None
    img_el = soup.find(id="landingImage") or soup.find(id="imgBlkFront")
    if img_el:
        image = img_el.get("src") or img_el.get("data-src")
    image = image or _meta(soup, "og:image") or _meta(soup, "twitter:image")

    current = None
    for selector in (
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        ".priceToPay .a-offscreen",
    ):
        el = soup.select_one(selector)
        if not el:
            continue
        current = _parse_any_money(el.get_text(" ", strip=True))
        if current:
            break
    structured = _extract_structured_data(soup)
    current = current or structured.get("price")
    text_current, text_original, text_discount = _choose_prices_from_text(html_text or "", current_hint=current, platform="amazon")
    current = current or text_current
    original = text_original or current

    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": image,
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": text_discount or _discount(current, original),
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": None,
            "extraction_verified": bool(title and image),
        }
    )
    return _normalize_prices(produto)


def _extract_shein(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = {
        "id": url,
        "product_id": None,
        "link": url,
        "link_original": url,
        "source_url": url,
        "platform": "shein",
        "desconto_estimado": False,
        "score": 0,
    }

    title = None
    image = None
    current = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        for item in _walk_json(data):
            if not isinstance(item, dict) or str(item.get("@type", "")).lower() != "product":
                continue
            title = item.get("name") or title
            offers = item.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                current = _parse_any_money(offers.get("price")) or current
            imgs = item.get("image")
            if isinstance(imgs, list) and imgs:
                image = str(imgs[0])
            elif isinstance(imgs, str):
                image = imgs
            break
        if title or image or current:
            break

    title = title or _meta(soup, "og:title") or _meta(soup, "twitter:title") or _title(soup)
    image = image or _meta(soup, "og:image") or _meta(soup, "twitter:image")
    if not current:
        current, _, _ = _choose_prices_from_text(soup.get_text("\n", strip=True) or html_text, platform="shein")

    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": image,
            "preco_atual": current or 0,
            "preco_original": current or 0,
            "desconto_pct": 0,
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": None,
            "extraction_verified": bool(title and image),
        }
    )
    return _normalize_prices(produto)


def _extract_aliexpress(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = _base_product(url, "aliexpress")
    structured = _extract_structured_data(soup)
    title = structured.get("title") or _meta(soup, "og:title") or _meta(soup, "twitter:title") or _title(soup)
    image = structured.get("image") or _meta(soup, "og:image") or _meta(soup, "twitter:image")
    current = structured.get("price")
    original = structured.get("original_price")
    url_current, url_original, url_discount = _aliexpress_prices_from_url(url)

    # AliExpress often embeds product data in JSON assigned to window.runParams / __AER_DATA__.
    for match in re.finditer(r'(?:"(?:salePrice|actSalePrice|formattedPrice|price|lowPrice)"\s*:\s*"([^"]+)")', html_text or ""):
        current = current or _parse_any_money(match.group(1))
        if current:
            break
    for match in re.finditer(r'(?:"(?:originalPrice|skuAmount|listPrice)"\s*:\s*"([^"]+)")', html_text or ""):
        original = original or _parse_any_money(match.group(1))
        if original:
            break
    if not title:
        match = re.search(r'"(?:subject|productTitle|title)"\s*:\s*"([^"]{10,250})"', html_text or "")
        title = match.group(1) if match else None
    if not image:
        match = re.search(r'"(?:imagePath|imageUrl|productImage)"\s*:\s*"([^"]+)"', html_text or "")
        image = match.group(1).replace("\\/", "/") if match else None
    current = current or url_current
    original = original or url_original
    if not current:
        current, original_from_text, discount = _choose_prices_from_text(soup.get_text("\n", strip=True) or html_text, platform="aliexpress")
        original = original or original_from_text
    else:
        discount = url_discount or _discount(current, original)

    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": _normalize_image_url(image),
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": discount or _discount(current, original),
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": None,
            "extraction_verified": bool(title and image and current),
        }
    )
    return _normalize_prices(produto)


def _aliexpress_prices_from_url(url: str) -> tuple[float | None, float | None, int]:
    parsed = urlparse(url)
    query = parsed.query
    match = re.search(r"dis%21BRL%21([0-9.]+)%21([0-9.]+)%21", query, re.I)
    if not match:
        match = re.search(r"dis!BRL!([0-9.]+)!([0-9.]+)!", query, re.I)
    if not match:
        return None, None, 0
    original = _parse_any_money(match.group(1))
    current = _parse_any_money(match.group(2))
    return current, original, _discount(current, original)


def _extract_magalu(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = _base_product(url, "magalu")
    structured = _extract_structured_data(soup)
    title = (
        structured.get("title")
        or _meta(soup, "og:title")
        or _meta(soup, "twitter:title")
        or _text_first(soup, ("[data-testid='heading-product-title']", "h1"))
        or _title(soup)
    )
    image = structured.get("image") or _meta(soup, "og:image") or _meta(soup, "twitter:image")
    current = structured.get("price")
    original = structured.get("original_price")
    if not current:
        current, original_from_text, discount = _choose_prices_from_text(soup.get_text("\n", strip=True) or html_text, platform="magalu")
        original = original or original_from_text
    else:
        discount = _discount(current, original)
    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": _normalize_image_url(image),
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": discount or _discount(current, original),
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": _extract_installments_text(html_text),
            "extraction_verified": bool(title and image and current),
        }
    )
    return _normalize_prices(produto)


def _extract_natura(html_text: str, url: str) -> dict:
    soup = BeautifulSoup(html_text or "", "html.parser")
    produto = _base_product(url, "natura")
    structured = _extract_structured_data(soup)
    title = structured.get("title") or _meta(soup, "og:title") or _meta(soup, "twitter:title") or _text_first(soup, ("h1",)) or _title(soup)
    image = structured.get("image") or _meta(soup, "og:image") or _meta(soup, "twitter:image")
    current = structured.get("price")
    original = structured.get("original_price")
    if not current:
        current, original_from_text, discount = _choose_prices_from_text(soup.get_text("\n", strip=True) or html_text, platform="natura")
        original = original or original_from_text
    else:
        discount = _discount(current, original)
    produto.update(
        {
            "titulo": clean_title(title or "Oferta selecionada"),
            "imagem": _normalize_image_url(image),
            "preco_atual": current or 0,
            "preco_original": original or current or 0,
            "desconto_pct": discount or _discount(current, original),
            "vendidos": _extract_sold(html_text or ""),
            "avaliacao": _extract_rating(html_text or ""),
            "frete_gratis": _has_free_shipping(html_text or ""),
            "parcelamento": _extract_installments_text(html_text),
            "extraction_verified": bool(title and image and current),
        }
    )
    return _normalize_prices(produto)


def _base_product(url: str, platform: str) -> dict:
    return {
        "id": url,
        "product_id": None,
        "link": url,
        "link_original": url,
        "source_url": url,
        "platform": platform,
        "desconto_estimado": False,
        "score": 0,
    }


def _needs_browser(produto: dict) -> bool:
    return produto.get("titulo") in {"Oferta selecionada", "Produto Mercado Livre"} or not produto.get("preco_atual") or not produto.get("imagem")


def _normalize_prices(produto: dict) -> dict:
    current = float(produto.get("preco_atual") or 0)
    original = float(produto.get("preco_original") or 0)
    discount = int(produto.get("desconto_pct") or 0)
    has_real_original = current > 0 and original > current

    if current > 0 and has_real_original:
        if discount <= 0:
            discount = max(1, round((1 - current / original) * 100))
        produto["desconto_estimado"] = False
    elif current > 0:
        original = current
        discount = 0
        produto["desconto_estimado"] = False
    else:
        produto["desconto_estimado"] = False

    produto["preco_atual"] = current
    produto["preco_original"] = original or current
    produto["desconto_pct"] = discount
    produto["score"] = discount
    return produto


def clean_title(title: str) -> str:
    title = unescape(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s+\|\s+.*$", "", title)
    title = re.sub(r"\s+[-|] Mercado Livre.*$", "", title, flags=re.I)
    title = re.sub(r"\s+no Mercado Livre.*$", "", title, flags=re.I)
    return title or "Oferta selecionada"


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    value = tag.get("content") if tag else None
    return str(value).strip() if value else None


def _itemprop(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find(attrs={"itemprop": name})
    if not tag:
        return None
    value = tag.get("content") or tag.get("value") or tag.get_text(" ", strip=True)
    return str(value).strip() if value else None


def _title(soup: BeautifulSoup) -> str | None:
    return soup.title.text.strip() if soup.title and soup.title.text else None


def _html_title_candidates(soup: BeautifulSoup) -> list[str]:
    selectors = [
        "h1.ui-pdp-title",
        ".ui-pdp-title",
        '[data-testid="product-title"]',
        '[class*="product-title"]',
        '[class*="item-title"]',
        ".poly-component__title",
        "h1",
        "h2",
    ]
    candidates: list[str] = []
    for selector in selectors:
        for tag in soup.select(selector):
            text = tag.get_text(" ", strip=True)
            if text:
                candidates.append(text)
    return candidates


def _product_id(text: str) -> str | None:
    match = PRODUCT_ID_RE.search(text or "")
    return (match.group(1) or match.group(2)) if match else None


def _item_id(text: str) -> str | None:
    match = ITEM_ID_RE.search(text or "")
    if match:
        return match.group(1).upper()
    match = MLB_URL_ID_RE.search(text or "")
    return f"MLB{match.group(1)}".upper() if match else None


async def _extract_mercadolivre_api_item(final_url: str, html_text: str, timeout: float) -> dict | None:
    item_id = _item_id(final_url) or _item_id(html_text)
    if not item_id:
        return None
    headers = {"Accept": "application/json"}
    token = os.getenv("ML_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            resp = await client.get(f"https://api.mercadolibre.com/items/{item_id}")
            if resp.status_code >= 400:
                return None
            data = resp.json()
    except Exception:
        return None
    current = _parse_any_money(data.get("price"))
    original = _parse_any_money(data.get("original_price")) or current
    pictures = data.get("pictures") or []
    image = None
    if isinstance(pictures, list) and pictures:
        first = pictures[0] or {}
        image = first.get("secure_url") or first.get("url")
    image = image or data.get("secure_thumbnail") or data.get("thumbnail")
    return {
        "id": item_id,
        "product_id": data.get("catalog_product_id") or item_id,
        "platform": "mercadolivre",
        "titulo": clean_title(str(data.get("title") or "")),
        "preco_atual": current or 0,
        "preco_original": original or current or 0,
        "desconto_pct": _discount(current, original),
        "desconto_estimado": False,
        "imagem": image,
        "vendidos": f"{data.get('sold_quantity')} vendidos" if data.get("sold_quantity") else "",
        "frete_gratis": bool(((data.get("shipping") or {}).get("free_shipping"))),
        "source_url": data.get("permalink") or final_url,
        "extraction_verified": bool(data.get("title") and image and current),
    }


async def _extract_mercadolivre_api_price(final_url: str, html_text: str, timeout: float) -> dict | None:
    item_id = _item_id(final_url) or _item_id(html_text)
    token = os.getenv("ML_ACCESS_TOKEN")
    if not item_id or not token:
        return None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    urls = [
        f"https://api.mercadolibre.com/items/{item_id}/sale_price?context=channel_marketplace",
        f"https://api.mercadolibre.com/items/{item_id}/prices",
    ]
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
            except Exception:
                continue
            parsed = _parse_mercadolivre_price_payload(data)
            if parsed:
                parsed["price_source"] = "mercadolivre_api"
                parsed["extraction_verified"] = True
                return parsed
    return None


def _parse_mercadolivre_price_payload(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    if "amount" in data:
        current = _parse_any_money(data.get("amount"))
        original = _parse_any_money(data.get("regular_amount")) or current
        if current:
            return {
                "preco_atual": current,
                "preco_original": original,
                "desconto_pct": _discount(current, original),
                "desconto_estimado": False,
            }
    prices = data.get("prices") or []
    if isinstance(prices, list):
        marketplace = [p for p in prices if "channel_marketplace" in (((p or {}).get("conditions") or {}).get("context_restrictions") or [])]
        candidates = marketplace or prices
        for price in candidates:
            current = _parse_any_money((price or {}).get("amount"))
            original = _parse_any_money((price or {}).get("regular_amount")) or current
            if current:
                return {
                    "preco_atual": current,
                    "preco_original": original,
                    "desconto_pct": _discount(current, original),
                    "desconto_estimado": False,
                }
    return None


def _extract_structured_data(soup: BeautifulSoup) -> dict:
    result: dict = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except json.JSONDecodeError:
            continue
        for item in _walk_json(data):
            if not isinstance(item, dict):
                continue
            if str(item.get("@type", "")).lower() == "product":
                if item.get("name") and not result.get("title"):
                    result["title"] = str(item.get("name"))
                image = item.get("image")
                if image and not result.get("image"):
                    if isinstance(image, list):
                        result["image"] = str(image[0]) if image else ""
                    else:
                        result["image"] = str(image)
                aggregate = item.get("aggregateRating")
                if isinstance(aggregate, dict):
                    rating = _parse_any_money(aggregate.get("ratingValue"))
                    if rating:
                        result["rating"] = rating
            offers = item.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = _parse_any_money(offers.get("price") or offers.get("lowPrice"))
                if price:
                    result["price"] = price
                high = _parse_any_money(offers.get("highPrice"))
                if high and high > price:
                    result["original_price"] = high
                if result.get("title") and result.get("image") and result.get("price"):
                    return result
    return result


def _walk_json(data):
    if isinstance(data, list):
        for item in data:
            yield from _walk_json(item)
    elif isinstance(data, dict):
        yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from _walk_json(value)


def _choose_prices_from_text(
    text: str,
    current_hint: float | None = None,
    platform: str | None = None,
) -> tuple[float | None, float | None, int]:
    text = unescape(text or "")
    if platform == "shopee":
        top_text = re.split(r"Compre Agora|Comprar Agora|Melhores Escolhas|Produtos similares", text, maxsplit=1, flags=re.I)[0]
        top_prices = _prices_from_text(top_text[:6000])
        top_discount = _discount_badge(top_text[:6000])
        if top_prices:
            current = top_prices[0]
            original = round(current / (1 - top_discount / 100), 2) if top_discount else current
            return current, original, top_discount

    discount_match = _discount_match(text)
    if discount_match:
        discount = int(discount_match.group(1))
        start = max(0, discount_match.start() - 900)
        prices = _prices_from_text(text[start:discount_match.start() + 120])
        if len(prices) >= 2:
            original, current = prices[0], prices[1]
            if original > current:
                return current, original, discount
        if current_hint:
            original = round(current_hint / (1 - discount / 100), 2)
            return current_hint, original, discount

    prices = _prices_from_text(text[:250000])
    if not prices:
        return None, None, 0
    if current_hint:
        higher = [p for p in prices if p > current_hint]
        return current_hint, min(higher, key=lambda p: abs(p - current_hint)) if higher else current_hint, 0

    meaningful = [p for p in prices if p >= 5]
    if not meaningful:
        return prices[0], prices[0], 0
    if platform == "shopee":
        current = meaningful[0]
        return current, current, 0
    return meaningful[0], meaningful[0], 0


def _discount_match(text: str):
    return re.search(r"-?\s*(\d{1,2})\s*%\s*(?:OFF)?", text, re.I)


def _discount_badge(text: str) -> int:
    match = _discount_match(text)
    return int(match.group(1)) if match else 0


def _prices_from_text(text: str) -> list[float]:
    matches: list[tuple[int, tuple[int, int], float]] = []
    text = text or ""

    for start, end, price in _line_prices_from_text(text):
        if 0.5 <= price <= 100000:
            matches.append((start, (start, end), price))

    for match in BR_PRICE_RE.finditer(text):
        price = _parse_brl(match.group(1))
        if 0.5 <= price <= 100000:
            matches.append((match.start(), match.span(), price))

    for match in SPLIT_PRICE_RE.finditer(text):
        price = _parse_brl(f"{match.group(1)},{match.group(2)}")
        if 0.5 <= price <= 100000:
            matches.append((match.start(), match.span(), price))

    occupied = [span for _, span, _ in matches]
    for match in WHOLE_PRICE_RE.finditer(text):
        span = match.span()
        if any(not (span[1] <= used[0] or span[0] >= used[1]) for used in occupied):
            continue
        price = float(match.group(1).replace(".", ""))
        if 5 <= price <= 100000:
            matches.append((match.start(), span, price))

    values: list[float] = []
    for _, _, price in sorted(matches, key=lambda item: item[0]):
        if not values or values[-1] != price:
            values.append(price)
    return values


def _line_prices_from_text(text: str) -> list[tuple[int, int, float]]:
    lines = list(re.finditer(r"[^\r\n]+", text or ""))
    prices: list[tuple[int, int, float]] = []
    for index, line_match in enumerate(lines[:-3]):
        if line_match.group(0).strip() != "R$":
            continue
        whole = lines[index + 1].group(0).strip()
        comma = lines[index + 2].group(0).strip()
        cents = lines[index + 3].group(0).strip()
        if comma == "," and re.fullmatch(r"\d[\d.]*", whole) and re.fullmatch(r"\d{2}", cents):
            start = line_match.start()
            end = lines[index + 3].end()
            prices.append((start, end, _parse_brl(f"{whole},{cents}")))
    return prices


def _parse_any_money(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        price = float(value)
        return price if price > 0 else None
    text = str(value)
    match = BR_PRICE_RE.search(text)
    if match:
        return _parse_brl(match.group(1))
    match = re.search(r"[0-9]+(?:\.[0-9]{2})", text)
    return float(match.group(0)) if match else None


def _text_first(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return None


def _normalize_image_url(value: object) -> str | None:
    if not value:
        return None
    url = str(value).strip().replace("\\/", "/")
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _extract_installments_text(text: str) -> str | None:
    match = re.search(r"(\d{1,2}\s*x\s+de\s+R\$\s*[\d.,]+(?:\s+sem\s+juros)?)", unescape(text or ""), re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def _parse_brl(value: str) -> float:
    return float(str(value).replace(".", "").replace(",", "."))


def _discount(current: float | None, original: float | None) -> int:
    if not current or not original or original <= current:
        return 0
    return max(0, min(95, round((1 - current / original) * 100)))


def _has_coherent_discount_pair(current: float | None, original: float | None, discount: int) -> bool:
    if not current or not original or original <= current or discount <= 0:
        return False
    computed = _discount(current, original)
    return abs(computed - discount) <= 3


def _extract_sold(text: str) -> str:
    text = unescape(text or "")
    match = re.search(r"(\+?\s*[\d\.]+\s*(?:mil)?\s+vendidos)", text, re.I)
    if not match:
        match = re.search(r"([\d\.]+\s*(?:mil)?\s+comprados)", text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).replace(". ", "") if match else ""


def _extract_rating(text: str) -> float:
    text = unescape(text or "")
    match = re.search(r"([0-5][,.][0-9])\s*(?:de\s+5|estrelas|\|)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else 0


def _has_free_shipping(text: str) -> bool:
    text = unescape(text or "").lower()
    return "frete grátis" in text or "frete gratis" in text or "envio grátis" in text or "envio gratis" in text


def _extract_with_browser(product_url: str, platform: str, cdp_url: str | None = None) -> dict:
    """Extrai produto via browser headless. Nao depende de Chrome aberto."""
    with sync_playwright() as p:
        browser = None
        using_cdp = False
        if cdp_url:
            try:
                browser = p.chromium.connect_over_cdp(cdp_url, timeout=5000)
                using_cdp = True
            except Exception:
                browser = None
        if browser is None:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
            )
            if not using_cdp:
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            page = context.new_page()
            page.goto(product_url, wait_until="domcontentloaded", timeout=40000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            text = page.locator("body").inner_text(timeout=10000)
            html_text = page.content()
            title = _best_product_title(page, platform, text) or _safe_title(page) or "Oferta selecionada"
            image = (
                _safe_attr(page, 'meta[property="og:image"]', "content")
                or _safe_attr(page, 'meta[name="twitter:image"]', "content")
                or _first_product_image(page)
            )
            dom_price = _extract_price_from_dom(page, platform)
            if dom_price:
                current, original, discount_badge = dom_price
            else:
                current, original, discount_badge = _choose_prices_from_text(text, platform=platform)
            product_id = _product_id(page.url) or _product_id(text)
            source_url = page.url
            page.close()
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            browser.close()
    platform_detected = detect_platform(source_url) or platform
    specific = _extract_specific_platform(source_url, html_text, platform_detected)
    if _produto_valido_interno(specific):
        return specific
    return {
        "id": product_id or source_url,
        "product_id": product_id,
        "platform": platform_detected,
        "source_url": source_url,
        "titulo": clean_title(title),
        "preco_atual": current or 0,
        "preco_original": original or current or 0,
        "desconto_pct": discount_badge or _discount(current, original),
        "desconto_estimado": False,
        "imagem": image,
        "vendidos": _extract_sold(text),
        "avaliacao": _extract_rating(text),
        "frete_gratis": _has_free_shipping(text),
    }


def _safe_inner_text(page, selector: str) -> str | None:
    try:
        loc = page.locator(selector)
        return loc.first.inner_text(timeout=3000).strip() if loc.count() else None
    except Exception:
        return None


def _best_product_title(page, platform: str, body_text: str = "") -> str | None:
    candidates: list[str] = []
    try:
        items = page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const selectors = [
                'h1.ui-pdp-title',
                '.ui-pdp-title',
                '[data-testid="product-title"]',
                '[class*="product-title"]',
                '[class*="item-title"]',
                '.poly-component__title',
                'h1',
                'h2'
              ];
              const out = [];
              for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                  if (visible(el)) out.push(el.innerText || el.textContent || '');
                }
              }
              return out;
            }
            """
        )
        candidates.extend(str(item) for item in (items or []))
    except Exception:
        pass

    if platform == "mercadolivre":
        candidates.extend(_mercadolivre_title_candidates_from_text(body_text))
    candidates.append(_safe_inner_text(page, "h1") or "")
    candidates.append(_safe_title(page) or "")
    return _choose_best_title(candidates)


def _mercadolivre_title_candidates_from_text(text: str) -> list[str]:
    lines = [clean_title(line) for line in (text or "").splitlines()]
    candidates: list[str] = []
    skip_starts = (
        "novo ",
        "usado ",
        "mais vendido",
        "ganhos extras",
        "compartilhar",
        "conferir produtos",
        "sabor:",
        "unidades por kit",
    )
    for line in lines:
        lowered = line.lower()
        if (
            18 <= len(line) <= 180
            and not _bad_product_title(line)
            and not lowered.startswith(skip_starts)
            and not re.fullmatch(r"[\d\s,.+()]+", line)
        ):
            candidates.append(line)
    return candidates


def _choose_best_title(candidates: list[str]) -> str | None:
    seen: set[str] = set()
    best: tuple[int, str] | None = None
    for raw in candidates:
        title = clean_title(raw)
        key = title.lower()
        if key in seen or _bad_product_title(title):
            continue
        seen.add(key)
        score = _title_score(title)
        if best is None or score > best[0]:
            best = (score, title)
    return best[1] if best else None


def _bad_product_title(title: str | None) -> bool:
    text = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    if len(text) < 10:
        return True
    bad_bits = (
        "oferta selecionada",
        "produto selecionado",
        "produto mercado livre",
        "shopee brasil",
        "amazon.com.br",
        "magazine luiza",
        "você tem 30 dias",
        "voce tem 30 dias",
        "recebimento do produto",
        "devolvê-lo",
        "devolve-lo",
        "não importa o motivo",
        "nao importa o motivo",
        "não é possível acessar",
        "nao e possivel acessar",
        "qg baltigo",
        "geek hunter",
        "central de afiliados",
        "mercado livre",
        "compartilhar",
        "conferir produtos",
        "ganhos extras",
        "afiliados ganhe",
        "mensagem fixada",
    )
    return any(bit in text for bit in bad_bits)


def _title_score(title: str) -> int:
    lowered = title.lower()
    score = len(title)
    if re.search(r"\d", title):
        score += 40
    for word in ("kit", "display", "unidades", "sabor", "whey", "creatina", "fone", "tenis", "iphone", "notebook"):
        if word in lowered:
            score += 20
    if len(title) > 150:
        score -= 50
    return score


def _safe_attr(page, selector: str, attr: str) -> str | None:
    try:
        loc = page.locator(selector)
        value = loc.first.get_attribute(attr, timeout=3000) if loc.count() else None
        return value.strip() if value else None
    except Exception:
        return None


def _extract_price_from_dom(page, platform: str) -> tuple[float | None, float | None, int] | None:
    if platform == "mercadolivre":
        return _extract_mercadolivre_price_from_dom(page)
    if platform == "shopee":
        return _extract_shopee_price_from_dom(page)
    return None


def _extract_mercadolivre_price_from_dom(page) -> tuple[float | None, float | None, int] | None:
    scripts = [
        """
        () => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const money = (root) => {
            if (!root || !visible(root)) return null;
            const fraction = root.querySelector('.andes-money-amount__fraction')?.innerText || '';
            const cents = root.querySelector('.andes-money-amount__cents')?.innerText || '';
            const aria = root.getAttribute('aria-label') || '';
            if (fraction.trim()) return { fraction, cents };
            return { text: aria || root.innerText || '' };
          };
          const priceBox = document.querySelector('.ui-pdp-price, [class*="price"]') || document.body;
          const current = money(priceBox.querySelector('.ui-pdp-price__second-line .andes-money-amount, [data-testid="price-part"] .andes-money-amount, .andes-money-amount:not(.andes-money-amount--previous)'));
          const original = money(priceBox.querySelector('.ui-pdp-price__original-value .andes-money-amount, .andes-money-amount--previous'));
          const discountText = priceBox.innerText || '';
          return { current, original, discountText };
        }
        """,
    ]
    for script in scripts:
        try:
            data = page.evaluate(script)
            text_current, text_original, text_discount = _choose_prices_from_text(
                data.get("discountText") or "", platform="mercadolivre"
            ) if data else (None, None, 0)
            if _has_coherent_discount_pair(text_current, text_original, text_discount):
                return text_current, text_original, text_discount
            current = _money_from_dom(data.get("current") if data else None)
            original = _money_from_dom(data.get("original") if data else None)
            discount = _discount_badge(data.get("discountText") or "") if data else 0
            if current:
                if not original and discount:
                    original = round(current / (1 - discount / 100), 2)
                return current, original or current, discount or _discount(current, original)
        except Exception:
            continue
    return None


def _extract_shopee_price_from_dom(page) -> tuple[float | None, float | None, int] | None:
    try:
        data = page.evaluate(
            """
            () => {
              const body = document.body.innerText || '';
              const buyIndex = body.search(/Compre Agora|Comprar Agora|Adicionar ao carrinho/i);
              const top = buyIndex > 0 ? body.slice(0, buyIndex) : body.slice(0, 5000);
              return top;
            }
            """
        )
        current, original, discount = _choose_prices_from_text(data or "", platform="shopee")
        if current:
            return current, original or current, discount
    except Exception:
        return None
    return None


def _money_from_dom(value: object) -> float | None:
    if not value:
        return None
    if isinstance(value, dict):
        if value.get("fraction"):
            fraction = str(value.get("fraction") or "").strip()
            cents = str(value.get("cents") or "00").strip() or "00"
            return _parse_brl(f"{fraction},{cents[:2]}")
        value = value.get("text")
    text = str(value or "")
    prices = _prices_from_text(text)
    return prices[0] if prices else None


def _first_product_image(page) -> str | None:
    selectors = [
        'img[src*="shopee"]',
        'img[src*="mlstatic"]',
        'img[src*="alicdn"]',
        'img',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), 20)
            for index in range(count):
                src = loc.nth(index).get_attribute("src", timeout=1000)
                if src and src.startswith("http") and not _looks_like_icon(src):
                    return src
        except Exception:
            continue
    return None


def _looks_like_icon(src: str) -> bool:
    lowered = src.lower()
    return _bad_image_url(lowered)


def _bad_image_url(src: str) -> bool:
    lowered = (src or "").lower()
    return any(
        bit in lowered
        for bit in (
            "sprite",
            "logo",
            "icon",
            "avatar",
            "placeholder",
            "favicon",
            "brand",
            "shopee-logo",
            "shopee-pcmall",
            "shopee-mobilemall",
            "error-robot",
            "shared/magalu/error",
        )
    )


def _validate_product(produto: dict, strict: bool = True) -> None:
    platform = produto.get("platform")
    strict_check = strict and platform in {"shopee", "mercadolivre"}
    if strict_check and not produto.get("extraction_verified"):
        raise ValueError(
            "Nao consegui confirmar os dados reais do produto. "
            "Tente o link direto da pagina do produto."
        )
    if strict and not produto.get("imagem"):
        raise ValueError(
            "Nao consegui confirmar a imagem real do produto. "
            "Tente o link direto da pagina do produto."
        )
    if strict and float(produto.get("preco_atual") or 0) <= 0:
        raise ValueError(
            "Nao consegui confirmar o preco real do produto. "
            "Tente o link direto da pagina do produto."
        )


def _safe_title(page) -> str | None:
    try:
        return page.title()
    except Exception:
        return None
