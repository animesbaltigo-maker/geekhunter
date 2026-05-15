"""Read offers from the logged-in Shopee affiliate panel."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright

SHOPEE_PANEL_URL = "https://affiliate.shopee.com.br/offer/product_offer"
BR_PRICE_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})")
DISCOUNT_RE = re.compile(r"(\d+)\s*%")
COMMISSION_RE = re.compile(r"(?:comiss[aã]o|commission)\D*(\d+(?:[,.]\d+)?)\s*%", re.I)
SOLD_RE = re.compile(r"(\+?\s*[0-9.]+(?:mil|k)?\s*(?:vendidos?|sold))", re.I)
RATING_RE = re.compile(r"\b([0-5][,.][0-9])\b")


def buscar_produtos_da_shopee(
    limite: int = 12,
    cdp_url: str = "http://127.0.0.1:9222",
    panel_url: str = SHOPEE_PANEL_URL,
) -> list[dict]:
    """Use an already logged-in Chrome session to collect Shopee affiliate offers."""
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(panel_url, wait_until="domcontentloaded", timeout=45000)
        _settle_page(page, wait_ms=2500)
        _ensure_shopee_panel_ready(page)

        cards: list[dict] = []
        for _ in range(8):
            cards.extend(_extract_visible_cards_with_affiliate_links(page, limite))
            if len(_unique_cards(cards)) >= limite:
                break
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(1200)
            _try_click_more(page)
        browser.close()

    return _unique_cards(cards)[:limite]


def _ensure_shopee_panel_ready(page) -> None:
    url = page.url.lower()
    try:
        body = page.locator("body").inner_text(timeout=2500)
    except Exception:
        body = ""
    normalized = _remove_accents(body).lower()

    if "verify/captcha" in url or "erro de carregamento" in normalized or "tentar novamente" in normalized:
        raise RuntimeError(
            "A Shopee abriu uma verificacao/captcha. Resolva manualmente no Chrome CDP e rode o bot novamente."
        )
    if "login" in url or "entrar" in normalized and "obter link" not in normalized:
        raise RuntimeError("A Shopee parece deslogada. Faca login no Chrome CDP e rode o bot novamente.")
    if page.get_by_text("Obter link", exact=True).count() == 0:
        raise RuntimeError("Nao encontrei botoes 'Obter link' na pagina da Shopee. Abra Oferta > Oferta de produto.")


def _extract_visible_cards_with_affiliate_links(page, limite: int) -> list[dict]:
    products: list[dict] = []
    buttons = page.get_by_text("Obter link", exact=True)
    try:
        count = buttons.count()
    except Exception:
        return products

    for index in range(count):
        if len(products) >= limite:
            break
        try:
            raw = _extract_card_from_button(page, index)
            if not raw:
                continue
            product = _normalizar_card(raw)
            if not product:
                continue
            affiliate_link = _get_affiliate_link_from_button(page, index)
            if affiliate_link:
                product["link"] = affiliate_link
                product["link_original"] = affiliate_link
                product["source_url"] = raw.get("href") or affiliate_link
                product["affiliate_offer_url"] = raw.get("href") or ""
            products.append(product)
        except Exception:
            _close_link_modal(page)
            continue
    return products


def _extract_card_from_button(page, index: int) -> dict | None:
    return page.evaluate(
        """
        (index) => {
          const buttons = Array.from(document.querySelectorAll('button'))
            .filter((button) => (button.innerText || '').trim() === 'Obter link');
          const button = buttons[index];
          if (!button) return null;

          const root = button.closest('.AffiliateItemCard')
            || button.closest('.product-offer-item')
            || button.closest('a[href*="/offer/product_offer/"]')
            || button.parentElement;

          const anchor = root.querySelector('a[href*="/offer/product_offer/"]')
            || root.closest('a[href*="/offer/product_offer/"]')
            || root.querySelector('a[href]');
          const img = root.querySelector('img');
          return {
            href: anchor ? anchor.href : '',
            text: (root.innerText || '').trim(),
            anchorText: anchor ? (anchor.innerText || '').trim() : '',
            image: img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '',
          };
        }
        """,
        index,
    )


def _get_affiliate_link_from_button(page, index: int) -> str | None:
    _close_link_modal(page)
    buttons = page.get_by_text("Obter link", exact=True)
    button = buttons.nth(index)
    button.scroll_into_view_if_needed(timeout=3000)
    button.click(timeout=5000)
    page.wait_for_timeout(1200)

    textarea = page.locator(".ant-modal textarea, textarea").last
    try:
        textarea.wait_for(state="visible", timeout=6000)
        value = textarea.input_value(timeout=2000).strip()
    except Exception:
        value = ""
    _close_link_modal(page)

    if value.startswith("http") and "shopee" in value.lower():
        return value
    return None


def _close_link_modal(page) -> None:
    try:
        if page.locator(".ant-modal").count() == 0:
            return
    except Exception:
        return
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        close = page.locator(".ant-modal-close").last
        if close.count() > 0:
            close.click(timeout=1000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def _extract_visible_cards(page) -> list[dict]:
    raw_cards = page.evaluate(
        """
        () => {
          const candidates = [];
          const seen = new Set();
          const anchors = Array.from(document.querySelectorAll('a[href]'));
          const usefulAnchors = anchors.filter((a) => {
            const href = a.href || '';
            const text = (a.innerText || '').trim();
            return /shopee\\.com\\.br|s\\.shopee|affiliate\\.shopee/.test(href)
              && !/login|seller|help|terms|privacy/i.test(href)
              && (text || a.querySelector('img'));
          });

          for (const anchor of usefulAnchors) {
            let root = anchor;
            for (let i = 0; i < 5 && root && root.parentElement; i += 1) {
              const parent = root.parentElement;
              const text = parent.innerText || '';
              if (text.includes('R$') || /comiss|commission|vendid|sold/i.test(text)) {
                root = parent;
              } else {
                break;
              }
            }
            const href = anchor.href;
            if (!href || seen.has(href)) continue;
            seen.add(href);
            const img = root.querySelector('img') || anchor.querySelector('img');
            const src = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
            candidates.push({
              href,
              text: (root.innerText || anchor.innerText || '').trim(),
              anchorText: (anchor.innerText || '').trim(),
              image: src,
            });
          }
          return candidates;
        }
        """
    )
    cards = []
    for raw in raw_cards:
        product = _normalizar_card(raw)
        if product:
            cards.append(product)
    return cards


def _normalizar_card(raw: dict) -> dict | None:
    href = _normalize_url(str(raw.get("href") or ""))
    text = re.sub(r"\s+", "\n", str(raw.get("text") or "")).strip()
    if not href or "shopee" not in href.lower():
        return None

    prices = [_parse_money(match.group(1)) for match in BR_PRICE_RE.finditer(text)]
    prices = [price for price in prices if price > 0]
    current_price = min(prices) if prices else 0.0
    previous_price = max(prices) if len(prices) > 1 else current_price

    discount = 0
    discount_match = DISCOUNT_RE.search(text)
    if discount_match:
        discount = int(discount_match.group(1))
    elif previous_price > current_price > 0:
        discount = round((1 - current_price / previous_price) * 100)

    title = _extract_title(raw, text)
    if not title:
        return None

    image = _normalize_url(str(raw.get("image") or ""))
    commission_match = COMMISSION_RE.search(text)
    rating_match = RATING_RE.search(text)
    sold_match = SOLD_RE.search(text)

    score = discount
    if commission_match:
        score += round(float(commission_match.group(1).replace(",", ".")))

    return {
        "id": href,
        "product_id": _product_id_from_url(href) or href,
        "platform": "shopee",
        "titulo": title,
        "preco_atual": current_price,
        "preco_original": previous_price,
        "desconto_pct": max(discount, 0),
        "desconto_estimado": False,
        "link": href,
        "link_original": href,
        "source_url": href,
        "imagem": image or None,
        "vendidos": sold_match.group(1).strip() if sold_match else "",
        "avaliacao": float(rating_match.group(1).replace(",", ".")) if rating_match else 0,
        "frete_gratis": "frete gratis" in _remove_accents(text).lower(),
        "parcelamento": None,
        "score": score,
        "commission": commission_match.group(0) if commission_match else "",
    }


def _extract_title(raw: dict, text: str) -> str:
    candidates = []
    anchor_text = str(raw.get("anchorText") or "").strip()
    if anchor_text:
        candidates.extend(anchor_text.splitlines())
    candidates.extend(text.splitlines())

    for line in candidates:
        line = re.sub(r"\s+", " ", line).strip(" -|")
        if not line or len(line) < 12:
            continue
        lower = _remove_accents(line).lower()
        if any(skip in lower for skip in ("r$", "%", "comissao", "commission", "vendido", "cupom", "frete")):
            continue
        return line[:160]
    return ""


def _unique_cards(cards: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for card in cards:
        key = card.get("product_id") or card.get("link")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(card)
    return sorted(unique, key=lambda item: item.get("score", 0), reverse=True)


def _settle_page(page, wait_ms: int = 1500) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except (PlaywrightError, PlaywrightTimeoutError):
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except (PlaywrightError, PlaywrightTimeoutError):
        pass
    page.wait_for_timeout(wait_ms)


def _try_click_more(page) -> bool:
    for text in ("Ver mais", "Mostrar mais", "Carregar mais", "Load more", "More"):
        try:
            loc = page.get_by_text(text, exact=False)
            if loc.count() > 0 and loc.first.is_visible(timeout=800):
                loc.first.click(timeout=2500)
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    return False


def _parse_money(value: str) -> float:
    normalized = value.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def _normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin("https://affiliate.shopee.com.br", url)
    return url


def _product_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    match = re.search(r"(?:i\.|product/)(\d+)[./](\d+)", parsed.path)
    if match:
        return f"shopee-{match.group(1)}-{match.group(2)}"
    return None


def _remove_accents(text: str) -> str:
    return (
        text.replace("á", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("õ", "o")
        .replace("ô", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
