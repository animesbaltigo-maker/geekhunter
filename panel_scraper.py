"""Read product recommendations from the logged-in Mercado Livre affiliate hub."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright

AFFILIATE_HUB = "https://www.mercadolivre.com.br/afiliados"
POLYCARDS_KEY = '"polycards":'


DEFAULT_PANEL_SEARCHES = [
    "tenis adidas",
    "fone bluetooth",
    "xiaomi",
    "air fryer",
    "ssd",
    "notebook",
    "monitor gamer",
    "creatina",
    "casa cozinha",
    "ferramentas",
]


def buscar_produtos_do_painel(
    limite: int = 12,
    cdp_url: str = "http://127.0.0.1:9222",
    search_terms: list[str] | None = None,
) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(AFFILIATE_HUB, wait_until="domcontentloaded", timeout=30000)
        _settle_page(page)
        html_parts = [_safe_page_content(page)]
        _load_more_recommendations(page, html_parts, max_rounds=8)
        for term in search_terms or DEFAULT_PANEL_SEARCHES:
            if len(_collect_unique_cards(html_parts)) >= limite:
                break
            _search_panel(page, term)
            html_parts.append(_safe_page_content(page))
            html_parts.append(json.dumps({"visible_cards": _extract_visible_link_cards(page)}, ensure_ascii=False))
            _load_more_recommendations(page, html_parts, max_rounds=3)
        browser.close()

    cards = _collect_unique_cards(html_parts)

    produtos = []
    for card in cards:
        produto = _normalizar_card(card)
        if produto:
            produtos.append(produto)
        if len(produtos) >= limite:
            break
    return produtos


def _collect_unique_cards(html_parts: list[str]) -> list[dict]:
    cards = []
    seen = set()
    for html in html_parts:
        if '"visible_cards"' in html:
            try:
                cards.extend(json.loads(html).get("visible_cards", []))
            except json.JSONDecodeError:
                pass
            continue
        for card in _extract_polycards(html):
            metadata = card.get("metadata") or {}
            card_id = metadata.get("id") or metadata.get("product_id") or card.get("unique_id")
            if card_id and card_id in seen:
                continue
            if card_id:
                seen.add(card_id)
            cards.append(card)
    return cards


def _extract_visible_link_cards(page) -> list[dict]:
    cards: list[dict] = []
    links = page.locator('a[href*="/p/MLB"]')
    try:
        count = min(links.count(), 30)
    except Exception:
        return cards

    for index in range(count):
        link = links.nth(index)
        try:
            href = link.get_attribute("href", timeout=1000)
            title = link.inner_text(timeout=1000).strip()
            card_text = link.evaluate(
                "el => (el.closest('.poly-card') || el.parentElement)?.innerText || el.innerText"
            )
        except Exception:
            continue
        if not href or not title:
            continue
        product_id_match = re.search(r"/p/(MLB\d+)", href)
        item_id = _wid_from_url(href) or (product_id_match.group(1) if product_id_match else href)
        prices = _prices_from_card_text(card_text or "")
        current_price = prices[-1] if prices else 0
        previous_price = prices[0] if len(prices) > 1 else current_price
        discount = _discount_from_card_text(card_text or "", current_price, previous_price)
        rating, sold = _rating_sold_from_card_text(card_text or "")
        cards.append(
            {
                "metadata": {
                    "id": item_id,
                    "product_id": product_id_match.group(1) if product_id_match else "",
                    "url": href.replace("https://", "").replace("http://", ""),
                    "type": "product",
                },
                "components": [
                    {"id": "title", "title": {"text": title}},
                    {
                        "id": "price",
                        "price": {
                            "current_price": {"value": current_price},
                            "previous_price": {"value": previous_price},
                            "discount": {"value": discount},
                        },
                    },
                    {
                        "id": "review_compacted",
                        "review_compacted": {
                            "values": [
                                {"label": {"text": str(rating).replace(".", ",") if rating else ""}},
                                {"label": {"text": sold}},
                            ]
                        },
                    },
                ],
                "pictures": {"pictures": []},
            }
        )
    return cards


def _prices_from_card_text(text: str) -> list[float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    prices: list[float] = []
    for index, line in enumerate(lines[:-3]):
        if line != "R$":
            continue
        whole = lines[index + 1]
        comma = lines[index + 2]
        cents = lines[index + 3]
        if comma == "," and re.fullmatch(r"\d[\d.]*", whole) and re.fullmatch(r"\d{2}", cents):
            prices.append(float(f"{whole.replace('.', '')}.{cents}"))
    return prices[:2]


def _discount_from_card_text(text: str, current: float, previous: float) -> int:
    match = re.search(r"(\d+)%\s+OFF", text, re.I)
    if match:
        return int(match.group(1))
    if previous and current and previous > current:
        return round((1 - current / previous) * 100)
    return 0


def _rating_sold_from_card_text(text: str) -> tuple[float, str]:
    rating = 0.0
    sold = ""
    match = re.search(r"([0-5][,.][0-9])\s*\|\s*(\+?[0-9.]+(?:mil)?\s+vendidos)", text, re.I)
    if match:
        rating = float(match.group(1).replace(",", "."))
        sold = match.group(2).replace(".", "")
    return rating, sold


def _wid_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("wid"):
        return query["wid"][0]
    fragment_query = parse_qs(parsed.fragment)
    if fragment_query.get("wid"):
        return fragment_query["wid"][0]
    match = re.search(r"wid=(MLB\d+)", url)
    return match.group(1) if match else None


def _search_panel(page, term: str) -> None:
    try:
        field = page.locator('input[placeholder="Busque produtos"]')
        if field.count() == 0:
            return
        field.fill(term, timeout=3000)
        field.press("Enter", timeout=3000)
        _settle_page(page)
    except Exception:
        return


def _settle_page(page, wait_ms: int = 1500) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(wait_ms)


def _safe_page_content(page, retries: int = 4) -> str:
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            return page.content()
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            last_error = exc
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            page.wait_for_timeout(800)
    if last_error:
        raise last_error
    return ""


def _load_more_recommendations(page, html_parts: list[str], max_rounds: int) -> None:
    for _ in range(max_rounds):
        before = len(_product_ids_from_html(html_parts[-1]))
        try:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1200)
            html = _safe_page_content(page)
        except Exception:
            continue
        html_parts.append(html)
        after = len(_product_ids_from_html(html))
        if after <= before:
            maybe_clicked = _try_click_more(page)
            if not maybe_clicked:
                continue
            _settle_page(page)
            try:
                html_parts.append(_safe_page_content(page))
            except Exception:
                continue


def _try_click_more(page) -> bool:
    for text in ("Ver mais", "Mostrar mais", "Carregar mais", "Mais produtos"):
        try:
            loc = page.get_by_text(text, exact=False)
            if loc.count() > 0 and loc.first.is_visible(timeout=1000):
                loc.first.click(timeout=3000)
                return True
        except Exception:
            pass
    return False


def _product_ids_from_html(html: str) -> set[str]:
    return set(re.findall(r'"product_id":"(MLB\d+)"', html))


def _extract_polycards(html: str) -> list[dict]:
    cards: list[dict] = []
    cursor = 0
    while True:
        start = html.find(POLYCARDS_KEY, cursor)
        if start < 0:
            break
        array_start = html.find("[", start)
        if array_start < 0:
            break
        array_end = _find_matching_bracket(html, array_start)
        if array_end < 0:
            break
        raw = html[array_start : array_end + 1]
        raw = unescape(raw).replace("\\u002F", "/")
        try:
            cards.extend(json.loads(raw))
        except json.JSONDecodeError:
            pass
        cursor = array_end + 1
    return cards


def _find_matching_bracket(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _normalizar_card(card: dict) -> dict | None:
    metadata = card.get("metadata") or {}
    components = card.get("components") or []
    title = _component(components, "title")
    price = _component(components, "price")
    review = _component(components, "review_compacted")
    chip = _component(components, "affiliates_commission_chip")
    pictures = ((card.get("pictures") or {}).get("pictures") or [])

    title_text = (((title or {}).get("title") or {}).get("text") or "").strip()
    url = metadata.get("url")
    if not title_text or not url:
        return None

    price_data = ((price or {}).get("price") or {})
    current_price = ((price_data.get("current_price") or {}).get("value") or 0)
    previous_price = ((price_data.get("previous_price") or {}).get("value") or current_price)
    discount = ((price_data.get("discount") or {}).get("value") or 0)
    installments_data = price_data.get("installments") or {}
    installments = _format_installments(installments_data)

    rating = 0
    sold_text = ""
    values = (((review or {}).get("review_compacted") or {}).get("values") or [])
    for value in values:
        label = (value.get("label") or {}).get("text")
        if not label:
            continue
        if "|" in label or "vendidos" in label:
            sold_text = label.replace("|", "").strip()
        else:
            try:
                rating = float(label.replace(",", "."))
            except ValueError:
                pass

    commission = (((chip or {}).get("chip") or {}).get("label") or {}).get("text") or ""
    product_url = "https://" + url.strip("/")
    product_id = metadata.get("product_id") or ""
    item_id = metadata.get("id") or product_id

    return {
        "id": item_id,
        "product_id": product_id,
        "platform": "mercadolivre",
        "titulo": title_text,
        "preco_atual": float(current_price),
        "preco_original": float(previous_price),
        "desconto_pct": int(discount or 0),
        "link": product_url,
        "link_original": product_url,
        "imagem": _picture_url(pictures[0].get("id")) if pictures else None,
        "vendidos": sold_text,
        "avaliacao": rating,
        "frete_gratis": _has_free_shipping(components),
        "parcelamento": installments,
        "score": _score(int(discount or 0), rating, commission),
        "commission": commission,
    }


def _component(components: list[dict], component_id: str) -> dict | None:
    for component in components:
        if component.get("id") == component_id:
            return component
    return None


def _score(discount: int, rating: float, commission: str) -> float:
    score = discount * 3 + rating * 10
    match = re.search(r"(\d+)%", commission)
    if match:
        score += int(match.group(1)) * 4
    return round(score, 2)


def _format_installments(installments: dict) -> str | None:
    text = installments.get("text")
    if not text:
        return None
    values = installments.get("values") or []
    for value in values:
        key = value.get("key")
        price = (value.get("price") or {}).get("value")
        if key and price:
            text = text.replace("{" + key + "}", f"R$ {_money(float(price))}")
    return text


def _picture_url(picture_id: str | None) -> str | None:
    if not picture_id:
        return None
    return f"https://http2.mlstatic.com/D_NQ_NP_2X_{picture_id}-F.webp"


def _money(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _has_free_shipping(components: list[dict]) -> bool:
    text = json.dumps(components, ensure_ascii=False).lower()
    return "frete grátis" in text or "frete gratis" in text
