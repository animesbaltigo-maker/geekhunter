"""Generate Mercado Livre affiliate short links using the logged-in affiliate panel session."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

AFFILIATE_HUB = "https://www.mercadolivre.com.br/afiliados"
CREATE_LINK_URL = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
PRODUCT_ID_RE = re.compile(r"/p/(MLB\d+)|\b(MLB\d{6,})\b")


@dataclass
class AffiliateLink:
    short_url: str
    text: str
    product_code: str | None
    long_url: str | None


def generate_affiliate_link(
    product_url: str,
    tag: str,
    cdp_url: str = "http://127.0.0.1:9222",
    product_id: str | None = None,
    item_id: str | None = None,
) -> AffiliateLink:
    """Use the currently logged-in Chrome session to generate a meli.la link."""
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(AFFILIATE_HUB, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        csrf_token = _capture_csrf_from_create_link(page)
        if not csrf_token:
            raise RuntimeError("Nao consegui capturar x-csrf-token. Voce esta logado no painel de afiliados?")

        resolved_item_id = item_id or product_id or _extract_product_id(product_url)
        payload = {
            "itemId": product_id or resolved_item_id,
            "itemAddToList": resolved_item_id,
            "tag": tag,
            "type": "product",
            "urls": [_strip_scheme(product_url)],
            "extraCommission": "false",
        }

        response = page.request.post(
            CREATE_LINK_URL,
            headers={
                "content-type": "application/json",
                "x-csrf-token": csrf_token,
                "referer": "https://www.mercadolivre.com.br/afiliados/hub?is_affiliate=true",
            },
            data=json.dumps(payload),
        )
        if response.status != 200:
            raise RuntimeError(f"createLink falhou: HTTP {response.status} - {response.text()[:500]}")

        data = response.json()
        urls = data.get("urls") or []
        if not urls or not urls[0].get("short_url"):
            raise RuntimeError(f"Resposta sem short_url: {data}")

        first = urls[0]
        browser.close()
        return AffiliateLink(
            short_url=first["short_url"],
            text=first.get("text", ""),
            product_code=first.get("regex"),
            long_url=first.get("long_url"),
        )


def _capture_csrf_from_create_link(page) -> str | None:
    captured: list[str] = []

    def on_request(request):
        if CREATE_LINK_URL in request.url:
            token = request.headers.get("x-csrf-token")
            if token:
                captured.append(token)

    page.on("request", on_request)
    share = page.get_by_text("Compartilhar", exact=True)
    if share.count() == 0:
        return None
    share.first.click(timeout=5000)
    page.wait_for_timeout(2500)
    return captured[-1] if captured else None


def _extract_product_id(url: str) -> str:
    match = PRODUCT_ID_RE.search(url)
    if not match:
        raise ValueError("Nao encontrei um ID de produto MLB na URL. Use uma URL que contenha /p/MLB...")
    return match.group(1) or match.group(2)


def _strip_scheme(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").strip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera link meli.la usando a sessao logada do painel.")
    parser.add_argument("--product-url", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    link = generate_affiliate_link(args.product_url, args.tag)
    print(f"short_url={link.short_url}")
    if link.product_code:
        print(f"product_code={link.product_code}")


if __name__ == "__main__":
    main()
