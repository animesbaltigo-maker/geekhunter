"""Offer ranking and lightweight quality filters."""

from __future__ import annotations

import math
import re
from urllib.parse import urlparse

from config import Settings


def score_product(produto: dict, settings: Settings | None = None) -> float:
    desconto = _to_float(produto.get("desconto_pct"))
    vendidos = _sold_count(produto.get("vendidos"))
    avaliacao = _to_float(produto.get("avaliacao"))
    preco = _to_float(produto.get("preco_atual"))
    frete = bool(produto.get("frete_gratis"))
    imagem = bool(produto.get("imagem"))
    platform = _platform(produto)

    score = 0.0
    score += desconto * 3
    score += min(math.log1p(vendidos) * 15, 80)
    score += avaliacao * 8
    score += 12 if frete else 0
    score += 8 if imagem else -35
    score += 6 if platform == "mercadolivre" else 0
    if 0 < preco <= 200:
        score += 10
    if _preco_suspeito(preco, _to_float(produto.get("preco_original"))):
        score -= 80
    if settings and is_blocked_product(produto, settings):
        score -= 500
    return round(score, 2)


def is_blocked_product(produto: dict, settings: Settings) -> bool:
    title = str(produto.get("titulo") or "").lower()
    if settings.blocked_words and any(word.lower() in title for word in settings.blocked_words):
        return True
    if settings.max_price and _to_float(produto.get("preco_atual")) > settings.max_price:
        return True
    if settings.min_rating and _to_float(produto.get("avaliacao")) and _to_float(produto.get("avaliacao")) < settings.min_rating:
        return True
    if settings.min_sold_quantity and _sold_count(produto.get("vendidos")) < settings.min_sold_quantity:
        return True
    return False


def _preco_suspeito(preco_atual: float, preco_original: float) -> bool:
    if preco_atual <= 0:
        return True
    if preco_original > 0 and preco_atual / preco_original < 0.05:
        return True
    return False


def _platform(produto: dict) -> str:
    platform = str(produto.get("platform") or "").lower()
    if platform:
        return platform
    link = str(produto.get("link") or produto.get("link_original") or "")
    host = urlparse(link).netloc.lower()
    if "mercadolivre" in host or "meli.la" in host:
        return "mercadolivre"
    return host


def _sold_count(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").lower().strip()
    if not text:
        return 0
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(mil|k)?", text)
    if not match:
        return 0
    number = float(match.group(1).replace(".", "").replace(",", "."))
    if match.group(2) in {"mil", "k"}:
        number *= 1000
    return int(number)


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("R$", "").replace(" ", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0
