"""Find and rank Mercado Livre offers using the public API."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus, urlencode, urlparse, parse_qsl, urlunparse

import httpx

from config import Settings
from offer_quality import score_product

log = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"


async def buscar_ofertas_do_dia(settings: Settings, limite: int = 12) -> list[dict]:
    """Fetch discounted products, normalize them, and return the best ranked ones."""
    if settings.use_sample_data:
        log.info("USE_SAMPLE_DATA ativo. Usando ofertas ficticias para teste.")
        return _sample_products(settings)[:limite]

    headers = {
        "Accept": "application/json",
        "User-Agent": "ml-affiliate-bot/1.0 (+telegram-offers)",
    }
    if settings.ml_access_token:
        headers["Authorization"] = f"Bearer {settings.ml_access_token}"

    produtos: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers) as client:
        searches = _build_searches(settings)
        for params in searches:
            if len(produtos) >= limite * 3:
                break
            try:
                resp = await client.get(f"{BASE_URL}/sites/MLB/search", params=params)
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    produto = _normalizar_produto(item, settings)
                    if produto:
                        produtos[produto["id"]] = produto
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    if settings.ml_access_token:
                        log.error(
                            "O Mercado Livre bloqueou o endpoint /sites/MLB/search para este app/token "
                            "(HTTP %s). O token esta valido, mas essa busca publica nao esta liberada.",
                            exc.response.status_code,
                        )
                    else:
                        log.error(
                            "O Mercado Livre recusou a busca (HTTP %s). Gere o ML_ACCESS_TOKEN primeiro.",
                            exc.response.status_code,
                        )
                    break
                else:
                    log.warning("Falha ao buscar ofertas com params %s: %s", params, exc)
            except httpx.HTTPError as exc:
                log.warning("Falha ao buscar ofertas com params %s: %s", params, exc)

    ranked = sorted(produtos.values(), key=lambda item: item["score"], reverse=True)
    log.info("%s ofertas candidatas encontradas.", len(ranked))
    return ranked[:limite]


def _sample_products(settings: Settings) -> list[dict]:
    raw_items = [
        {
            "id": "SAMPLE-AIRFRYER",
            "title": "Air Fryer Digital 5L com Timer e Controle de Temperatura",
            "price": 279.90,
            "original_price": 399.90,
            "permalink": "https://www.mercadolivre.com.br/oferta-exemplo-air-fryer",
            "thumbnail": "",
            "sold_quantity": 320,
            "reviews": {"rating_average": 4.8},
            "shipping": {"free_shipping": True},
            "installments": {"quantity": 10, "amount": 27.99},
        },
        {
            "id": "SAMPLE-FONE",
            "title": "Fone Bluetooth Sem Fio com Cancelamento de Ruido",
            "price": 89.90,
            "original_price": 149.90,
            "permalink": "https://www.mercadolivre.com.br/oferta-exemplo-fone",
            "thumbnail": "",
            "sold_quantity": 850,
            "reviews": {"rating_average": 4.6},
            "shipping": {"free_shipping": True},
            "installments": {"quantity": 5, "amount": 17.98},
        },
        {
            "id": "SAMPLE-SSD",
            "title": "SSD 1TB NVMe Alta Velocidade para PC e Notebook",
            "price": 329.90,
            "original_price": 499.90,
            "permalink": "https://www.mercadolivre.com.br/oferta-exemplo-ssd",
            "thumbnail": "",
            "sold_quantity": 540,
            "reviews": {"rating_average": 4.9},
            "shipping": {"free_shipping": True},
            "installments": {"quantity": 10, "amount": 32.99},
        },
    ]
    products = [_normalizar_produto(item, settings) for item in raw_items]
    return sorted([item for item in products if item], key=lambda item: item["score"], reverse=True)


def _build_searches(settings: Settings) -> list[dict]:
    searches: list[dict] = []
    common = {
        "limit": 20,
        "sort": "relevance",
        "shipping_cost": "free",
    }

    for term in settings.search_terms:
        searches.append({**common, "q": term})

    for category_id in settings.category_ids:
        searches.append({**common, "category": category_id})

    return searches


def _normalizar_produto(item: dict, settings: Settings) -> dict | None:
    preco_atual = float(item.get("price") or 0)
    preco_original = item.get("original_price")
    if not preco_atual or not preco_original:
        return None

    preco_original = float(preco_original)
    if preco_original <= preco_atual:
        return None

    desconto_pct = round((1 - preco_atual / preco_original) * 100)
    if desconto_pct < settings.min_discount_pct:
        return None

    if settings.max_price and preco_atual > settings.max_price:
        return None

    vendidos = int(item.get("sold_quantity") or 0)
    if vendidos < settings.min_sold_quantity:
        return None

    reviews = item.get("reviews") or {}
    avaliacao = float(reviews.get("rating_average") or 0)
    frete_gratis = bool((item.get("shipping") or {}).get("free_shipping"))
    permalink = item.get("permalink") or ""
    item_id = item.get("id") or ""

    return {
        "id": item_id,
        "titulo": item.get("title", "").strip(),
        "preco_atual": preco_atual,
        "preco_original": preco_original,
        "desconto_pct": desconto_pct,
        "link": gerar_link_afiliado(permalink, item_id, settings),
        "link_original": permalink,
        "imagem": _imagem_grande(item.get("thumbnail") or ""),
        "vendidos": vendidos,
        "avaliacao": avaliacao,
        "frete_gratis": frete_gratis,
        "parcelamento": extrair_parcelamento(item),
        "score": score_product(
            {
                "desconto_pct": desconto_pct,
                "vendidos": vendidos,
                "avaliacao": avaliacao,
                "frete_gratis": frete_gratis,
                "preco_atual": preco_atual,
                "preco_original": preco_original,
                "imagem": _imagem_grande(item.get("thumbnail") or ""),
                "platform": "mercadolivre",
            },
            settings,
        ),
    }


def gerar_link_afiliado(url_produto: str, item_id: str, settings: Settings) -> str:
    """Generate an affiliate URL.

    Preferred mode: set AFFILIATE_URL_TEMPLATE with placeholders:
    {url}, {encoded_url}, {item_id}, {affiliate_id}
    """
    if not url_produto:
        return url_produto

    encoded_url = quote_plus(url_produto)
    if settings.affiliate_url_template:
        return settings.affiliate_url_template.format(
            url=url_produto,
            encoded_url=encoded_url,
            item_id=item_id,
            affiliate_id=settings.ml_affiliate_label_id or "",
            label_id=settings.ml_affiliate_label_id or "",
        )

    if settings.affiliate_link_mode == "query" and settings.ml_affiliate_label_id:
        return _add_query_params(
            url_produto,
            {
                "matt_tool": settings.ml_affiliate_matt_tool,
                "matt_word": settings.ml_affiliate_label_id,
            },
        )

    if not settings.ml_affiliate_label_id:
        return url_produto

    return _add_query_params(
        url_produto,
        {
            "utm_source": "telegram",
            "utm_medium": "affiliate",
            "utm_campaign": settings.ml_affiliate_label_id,
        },
    )


def extrair_parcelamento(item: dict) -> str | None:
    installments = item.get("installments") or {}
    qtd = installments.get("quantity")
    valor = installments.get("amount")
    if not qtd or not valor:
        return None
    return f"{int(qtd)}x de R$ {float(valor):.2f}".replace(".", ",")


def _imagem_grande(url: str) -> str | None:
    if not url:
        return None
    return url.replace("-I.jpg", "-O.jpg").replace("I.jpg", "O.jpg")


def _add_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))
