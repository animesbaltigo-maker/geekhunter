"""Autopost scheduler for the owner's affiliate channel."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from functools import partial
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from affiliate_linker import generate_affiliate_link
from ai_generator import gerar_post
from autopost_state import AutopostState
from config import Settings, load_settings
from extraction_quality import evaluate_product_confidence
from history import PostedHistory
from ml_deals_page import buscar_ofertas_paginas_ml
from ml_promotions import buscar_promocoes_oficiais
from ml_scraper import buscar_ofertas_do_dia, gerar_link_afiliado
from offer_mockup import maybe_create_offer_mockup
from offer_quality import is_blocked_product, score_product
from panel_scraper import buscar_produtos_do_painel
from price_history import PriceHistory, product_key, product_keys
from product_extractor import extrair_produto
from telegram_poster import postar_no_canal


def setup_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler("bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


log = logging.getLogger(__name__)


async def rodada_de_posts(settings: Settings, ignore_history: bool = False) -> None:
    log.info("Iniciando rodada de posts.")
    state = AutopostState()
    candidate_limit = max(settings.posts_per_round * 35, 35)
    active_niche = (
        state.active_niche(
            settings.search_terms,
            settings.niche_rotate_min_posts,
            settings.niche_rotate_max_posts,
        )
        if settings.product_source == "panel"
        else None
    )
    active_terms = [active_niche] if active_niche else settings.search_terms
    if active_terms:
        current_posts = int(state.data.get("current_niche_posts") or 0)
        target_posts = int(state.data.get("current_niche_target") or 0)
        log.info("Nicho ativo: %s (%s/%s posts)", ", ".join(active_terms), current_posts, target_posts)
    if settings.product_source == "panel":
        panel_products = await _buscar_produtos_ml(settings, candidate_limit, active_terms)
        page_products = await buscar_ofertas_paginas_ml(settings, limite=candidate_limit)
        produtos = _merge_ranked_products(panel_products, page_products)
    elif settings.product_source == "promotions":
        official_products = await buscar_promocoes_oficiais(settings, limite=candidate_limit)
        page_products = await buscar_ofertas_paginas_ml(settings, limite=candidate_limit)
        produtos = _merge_ranked_products(official_products, page_products)
    else:
        produtos = None

    if settings.product_source != "panel" and not settings.use_sample_data and not settings.ml_access_token:
        log.error("Falta ML_ACCESS_TOKEN no .env.")
        return

    history = PostedHistory(settings.history_path)
    price_history = PriceHistory()
    if produtos is None:
        api_products = await buscar_ofertas_do_dia(settings, limite=candidate_limit)
        page_products = await buscar_ofertas_paginas_ml(settings, limite=candidate_limit)
        produtos = _merge_ranked_products(api_products, page_products)
    if not produtos:
        log.warning("Nenhuma oferta encontrada nesta rodada.")
        return
    produtos = _rank_products(produtos, settings)

    postados = 0
    skipped_recent = 0
    skipped_filtered = 0
    failed = 0
    for produto in produtos:
        if postados >= settings.posts_per_round:
            break
        original_keys = product_keys(produto)
        product_id = original_keys[0] if original_keys else ""
        current_price = produto.get("preco_atual")
        if not ignore_history and _should_skip_product(history, state, original_keys, current_price):
            skipped_recent += 1
            log.info("Pulando repetido recente: %s", produto["titulo"][:100])
            continue

        try:
            if is_blocked_product(produto, settings):
                skipped_filtered += 1
                log.info("Pulando produto filtrado: %s", produto.get("titulo", "")[:100])
                continue
            should_enrich = (
                not produto.get("preco_atual")
                or not produto.get("imagem")
                or settings.product_source == "panel"
            )
            if should_enrich:
                original_image = produto.get("imagem")
                original_link = produto.get("link_original") or produto.get("link")
                enriched = await extrair_produto(produto["link_original"], settings.request_timeout, strict=False)
                if settings.product_source == "panel":
                    # Se o painel traz desconto real, ele pode ser mais preciso que a pagina final.
                    panel_title = produto.get("titulo")
                    panel_price = _price_snapshot(produto)
                    panel_social = _social_snapshot(produto)
                    produto.update(enriched)
                    if not produto.get("imagem") and original_image:
                        produto["imagem"] = original_image
                    if original_link:
                        produto["link_original"] = original_link
                    if _is_better_panel_price(panel_price, enriched):
                        produto.update(panel_price)
                    if _bad_enriched_title(produto.get("titulo")) and panel_title:
                        produto["titulo"] = panel_title
                    if panel_title:
                        produto["titulo"] = panel_title
                    _restore_missing_social(produto, panel_social)
                else:
                    produto.update({key: value for key, value in enriched.items() if value not in (None, "", 0)})

            if is_blocked_product(produto, settings):
                skipped_filtered += 1
                log.info("Pulando produto filtrado apos enriquecer: %s", produto.get("titulo", "")[:100])
                continue
            confidence = evaluate_product_confidence(produto, input_url=produto.get("link_original") or produto.get("link"))
            produto["confidence_score"] = confidence.score
            produto["confidence_issues"] = list(confidence.issues)
            if not confidence.ok:
                skipped_filtered += 1
                log.warning(
                    "Pulando produto com baixa confianca (%s/100): %s | %s",
                    confidence.score,
                    produto.get("titulo", "")[:100],
                    ", ".join(confidence.issues),
                )
                continue
            final_keys = product_keys(produto)
            if not ignore_history and _should_skip_product(history, state, final_keys, produto.get("preco_atual")):
                skipped_recent += 1
                log.info("Pulando repetido recente apos enriquecer: %s", produto["titulo"][:100])
                continue
            produto = price_history.record_product(produto, source=settings.product_source)
            produto["score"] = score_product(produto, settings)

            if not produto.get("imagem"):
                log.warning("Produto sem imagem apos enriquecer: %s", produto.get("titulo", "")[:100])

            if settings.product_source == "panel" and settings.ml_affiliate_label_id:
                affiliate_link = None
                if settings.affiliate_link_mode in {"browser", "panel", "meli", "shortlink"}:
                    try:
                        link = await asyncio.wait_for(
                            asyncio.to_thread(
                                generate_affiliate_link,
                                produto["link_original"],
                                settings.ml_affiliate_label_id,
                                cdp_url=settings.panel_cdp_url,
                                product_id=produto.get("product_id"),
                                item_id=produto.get("id"),
                            ),
                            timeout=15,
                        )
                        produto["link"] = link.short_url
                        if link.product_code:
                            produto["product_code"] = link.product_code
                        affiliate_link = link.short_url
                    except Exception as exc:
                        log.error("Nao gerei link afiliado meli.la. Produto nao sera postado: %s", exc)
                else:
                    affiliate_link = gerar_link_afiliado(
                        produto.get("link_original") or produto.get("link") or "",
                        str(produto.get("id") or produto.get("product_id") or product_id or ""),
                        settings,
                    )
                    produto["link"] = affiliate_link
                if not _is_confirmed_affiliate_link(
                    affiliate_link,
                    produto.get("link_original") or "",
                    settings,
                ):
                    skipped_filtered += 1
                    log.error("Pulando produto sem link afiliado confirmado: %s", produto.get("titulo", "")[:100])
                    continue

            texto = await gerar_post(produto, settings)
            post_image = await maybe_create_offer_mockup(produto, settings) or produto.get("imagem")
            await postar_no_canal(texto, post_image, settings, link=produto.get("link") or produto.get("link_original"))
            if settings.dry_run:
                log.info("DRY_RUN ativo. Historico e alternancia nao foram alterados.")
            else:
                for key in dict.fromkeys(original_keys + product_keys(produto)):
                    history.mark(key, produto.get("preco_atual"))
                    state.remember_product(key)
                _remember_marketplace_post(state, produto)
                if settings.product_source == "panel":
                    next_niche = state.remember_niche_post(
                        settings.search_terms,
                        settings.niche_rotate_min_posts,
                        settings.niche_rotate_max_posts,
                    )
                    if next_niche and next_niche not in active_terms:
                        log.info("Proximo nicho sera: %s", next_niche)
            postados += 1
            log.info("Oferta processada: %s | %s%% OFF", produto["titulo"][:100], produto["desconto_pct"])
            await asyncio.sleep(3)
        except Exception:
            failed += 1
            log.exception("Erro ao processar produto %s", produto.get("id"))

    log.info(
        "Rodada concluida: %s posts processados (%s repetidos, %s filtrados, %s com erro, %s candidatos).",
        postados,
        skipped_recent,
        skipped_filtered,
        failed,
        len(produtos),
    )


def _bad_enriched_title(title: str | None) -> bool:
    text = (title or "").strip().lower()
    if not text:
        return True
    bad_bits = ("qg baltigo", "central de afiliados", "mercado livre", "shopee brasil")
    return any(bit in text for bit in bad_bits) or len(text) < 8


def _should_skip_product(
    history: PostedHistory,
    state: AutopostState,
    keys: list[str],
    current_price: object,
) -> bool:
    for key in keys:
        if history.should_skip(key, current_price):
            return True
        if state.recently_posted(key) and not history.seen(key):
            return True
    return False


def _rank_products(produtos: list[dict], settings: Settings) -> list[dict]:
    ranked = []
    for produto in produtos:
        item = dict(produto)
        item["score"] = score_product(item, settings)
        ranked.append(item)
    return sorted(ranked, key=lambda item: item.get("score", 0), reverse=True)


def _price_snapshot(produto: dict) -> dict:
    return {
        "preco_atual": float(produto.get("preco_atual") or 0),
        "preco_original": float(produto.get("preco_original") or 0),
        "desconto_pct": int(produto.get("desconto_pct") or 0),
        "desconto_estimado": bool(produto.get("desconto_estimado", False)),
    }


def _social_snapshot(produto: dict) -> dict:
    return {
        "avaliacao": produto.get("avaliacao"),
        "vendidos": produto.get("vendidos"),
        "frete_gratis": produto.get("frete_gratis"),
        "parcelamento": produto.get("parcelamento"),
    }


def _restore_missing_social(produto: dict, panel_social: dict) -> None:
    for key, original in panel_social.items():
        current = produto.get(key)
        if current in (None, "", 0, 0.0, False) and original not in (None, "", 0, 0.0, False):
            produto[key] = original


def _is_confirmed_affiliate_link(link: str | None, original_url: str, settings: Settings) -> bool:
    if not link:
        return False
    parsed = urlparse(link)
    host = parsed.netloc.lower()
    if host.endswith("meli.la") or host == "meli.la":
        return True
    if settings.affiliate_url_template and link != original_url:
        return True
    query = parse_qs(parsed.query)
    label = settings.ml_affiliate_label_id or ""
    if label and label in query.get("matt_word", []):
        return True
    if label and label in query.get("utm_campaign", []):
        return True
    return False


async def _buscar_produtos_ml(settings: Settings, candidate_limit: int, active_terms: list[str]) -> list[dict]:
    try:
        return await asyncio.to_thread(
            partial(
                buscar_produtos_do_painel,
                limite=candidate_limit,
                cdp_url=settings.panel_cdp_url,
                search_terms=active_terms,
            )
        )
    except Exception:
        log.exception("Falha ao ler painel de afiliados nesta rodada. Vou tentar de novo na próxima.")
        return []


def _is_better_panel_price(panel: dict, enriched: dict) -> bool:
    panel_current = float(panel.get("preco_atual") or 0)
    panel_original = float(panel.get("preco_original") or 0)
    panel_discount = int(panel.get("desconto_pct") or 0)
    enriched_current = float(enriched.get("preco_atual") or 0)
    enriched_original = float(enriched.get("preco_original") or 0)
    enriched_discount = int(enriched.get("desconto_pct") or 0)

    if enriched_current > 0 and panel_current > 0:
        ratio = panel_current / enriched_current
        if ratio < 0.65 or ratio > 1.35:
            log.warning(
                "Preco do painel muito diferente da pagina final; usando pagina final. Painel=%.2f Final=%.2f",
                panel_current,
                enriched_current,
            )
            return False

    panel_has_real_discount = panel_current > 0 and panel_original > panel_current and panel_discount > 0
    enriched_has_real_discount = enriched_current > 0 and enriched_original > enriched_current and enriched_discount > 0
    if not panel_has_real_discount:
        return False
    if not enriched_has_real_discount:
        return True
    return panel_current < enriched_current and abs(panel_discount - enriched_discount) <= 5


def _merge_ranked_products(*groups: list[dict]) -> list[dict]:
    products = []
    seen = set()
    for group in groups:
        for product in group or []:
            key = product_key(product)
            if not key or key in seen:
                continue
            seen.add(key)
            products.append(product)
    return sorted(products, key=lambda item: item.get("score", 0), reverse=True)


def _alternate_marketplace_products(state: AutopostState, ml_products: list[dict], shopee_products: list[dict]) -> list[dict]:
    ml = _dedupe_products(ml_products)
    shopee = _dedupe_products(shopee_products)
    next_marketplace = _next_marketplace(state)

    if next_marketplace == "shopee":
        first, second = shopee, ml
    else:
        first, second = ml, shopee

    ordered: list[dict] = []
    max_len = max(len(first), len(second))
    for index in range(max_len):
        if index < len(first):
            ordered.append(first[index])
        if index < len(second):
            ordered.append(second[index])
    return ordered


def _dedupe_products(products: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for product in sorted(products or [], key=lambda item: item.get("score", 0), reverse=True):
        key = product_key(product)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique


def _next_marketplace(state: AutopostState) -> str:
    last = str(state.data.get("last_marketplace") or "").lower()
    if last == "shopee":
        return "mercadolivre"
    return "shopee"


def _remember_marketplace_post(state: AutopostState, product: dict) -> None:
    platform = str(product.get("platform") or "").lower()
    if "shopee" in platform:
        marketplace = "shopee"
    else:
        marketplace = "mercadolivre"
    state.data["last_marketplace"] = marketplace
    state.save()


async def run_autopost(settings: Settings, ignore_history: bool = False, run_once: bool = False) -> None:
    await rodada_de_posts(settings, ignore_history=ignore_history)
    if run_once:
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(rodada_de_posts, "interval", minutes=settings.round_interval_minutes, args=[settings])
    scheduler.start()
    log.info("Autopost ativo: 1 rodada a cada %s min.", settings.round_interval_minutes)

    while True:
        await asyncio.sleep(3600)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Autopostagem Mercado Livre -> Telegram.")
    parser.add_argument("--once", action="store_true", help="Executa uma rodada e encerra.")
    parser.add_argument("--post", action="store_true", help="Desativa DRY_RUN nesta execucao.")
    parser.add_argument("--ignore-history", action="store_true", help="Nao pula produtos ja processados.")
    args = parser.parse_args()

    setup_logging()
    settings = load_settings()
    if args.post:
        object.__setattr__(settings, "dry_run", False)
    await run_autopost(settings, ignore_history=args.ignore_history, run_once=args.once)


if __name__ == "__main__":
    asyncio.run(main())
