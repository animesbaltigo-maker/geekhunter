"""Autopost scheduler for the owner's affiliate channel."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from functools import partial
from logging.handlers import RotatingFileHandler

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from affiliate_linker import generate_affiliate_link
from ai_generator import gerar_post
from autopost_state import AutopostState
from config import Settings, load_settings
from history import PostedHistory
from ml_promotions import buscar_promocoes_oficiais
from ml_scraper import buscar_ofertas_do_dia
from panel_scraper import buscar_produtos_do_painel
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
        try:
            produtos = await asyncio.to_thread(
                partial(
                    buscar_produtos_do_painel,
                    limite=candidate_limit,
                    cdp_url=settings.panel_cdp_url,
                    search_terms=active_terms,
                )
            )
        except Exception:
            log.exception("Falha ao ler painel de afiliados nesta rodada. Vou tentar de novo na próxima.")
            return
    elif settings.product_source == "promotions":
        produtos = await buscar_promocoes_oficiais(settings, limite=candidate_limit)
    else:
        produtos = None

    if settings.product_source != "panel" and not settings.use_sample_data and not settings.ml_access_token:
        log.error("Falta ML_ACCESS_TOKEN no .env.")
        return

    history = PostedHistory(settings.history_path)
    if produtos is None:
        produtos = await buscar_ofertas_do_dia(settings, limite=candidate_limit)
    if not produtos:
        log.warning("Nenhuma oferta encontrada nesta rodada.")
        return

    postados = 0
    for produto in produtos:
        if postados >= settings.posts_per_round:
            break
        product_key = produto.get("id") or produto.get("product_id") or produto.get("link_original")
        if not ignore_history and (history.seen(product_key) or state.recently_posted(product_key)):
            log.info("Pulando repetido recente: %s", produto["titulo"][:100])
            continue

        try:
            if settings.product_source == "panel" or not produto.get("preco_atual") or not produto.get("imagem"):
                enriched = await extrair_produto(produto["link_original"], settings.request_timeout)
                if settings.product_source == "panel":
                    # Se o painel traz desconto real, ele pode ser mais preciso que a pagina final.
                    panel_title = produto.get("titulo")
                    panel_price = _price_snapshot(produto)
                    produto.update(enriched)
                    if _is_better_panel_price(panel_price, enriched):
                        produto.update(panel_price)
                    if _bad_enriched_title(produto.get("titulo")) and panel_title:
                        produto["titulo"] = panel_title
                    if panel_title:
                        produto["titulo"] = panel_title
                else:
                    produto.update({key: value for key, value in enriched.items() if value not in (None, "", 0)})

            if not produto.get("imagem"):
                log.warning("Produto sem imagem apos enriquecer: %s", produto.get("titulo", "")[:100])

            if settings.product_source == "panel" and settings.ml_affiliate_label_id:
                link = await asyncio.to_thread(
                    generate_affiliate_link,
                    produto["link_original"],
                    settings.ml_affiliate_label_id,
                    product_id=produto.get("product_id"),
                    item_id=produto.get("id"),
                )
                produto["link"] = link.short_url
                if link.product_code:
                    produto["product_code"] = link.product_code

            texto = await gerar_post(produto, settings)
            await postar_no_canal(texto, produto.get("imagem"), settings)
            history.mark(product_key)
            state.remember_product(product_key)
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
            log.exception("Erro ao processar produto %s", produto.get("id"))

    log.info("Rodada concluida: %s posts processados.", postados)


def _bad_enriched_title(title: str | None) -> bool:
    text = (title or "").strip().lower()
    if not text:
        return True
    bad_bits = ("qg baltigo", "central de afiliados", "mercado livre", "shopee brasil")
    return any(bit in text for bit in bad_bits) or len(text) < 8


def _price_snapshot(produto: dict) -> dict:
    return {
        "preco_atual": float(produto.get("preco_atual") or 0),
        "preco_original": float(produto.get("preco_original") or 0),
        "desconto_pct": int(produto.get("desconto_pct") or 0),
        "desconto_estimado": bool(produto.get("desconto_estimado", False)),
    }


def _is_better_panel_price(panel: dict, enriched: dict) -> bool:
    panel_current = float(panel.get("preco_atual") or 0)
    panel_original = float(panel.get("preco_original") or 0)
    panel_discount = int(panel.get("desconto_pct") or 0)
    enriched_current = float(enriched.get("preco_atual") or 0)
    enriched_original = float(enriched.get("preco_original") or 0)
    enriched_discount = int(enriched.get("desconto_pct") or 0)

    panel_has_real_discount = panel_current > 0 and panel_original > panel_current and panel_discount > 0
    enriched_has_real_discount = enriched_current > 0 and enriched_original > enriched_current and enriched_discount > 0
    if not panel_has_real_discount:
        return False
    if not enriched_has_real_discount:
        return True
    return panel_current < enriched_current and abs(panel_discount - enriched_discount) <= 5


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
