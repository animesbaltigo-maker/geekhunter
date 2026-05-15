"""Product scoring helpers."""

from __future__ import annotations

import math


def score_produto(
    desconto_pct: int,
    vendidos: int,
    avaliacao: float,
    frete_gratis: bool,
    preco_atual: float,
    comissao_pct: float = 0,
) -> float:
    score = desconto_pct * 3
    score += min(math.log1p(max(vendidos, 0)) * 15, 80)
    score += max(avaliacao, 0) * 8
    score += 12 if frete_gratis else 0
    score += max(comissao_pct, 0) * 4
    if 0 < preco_atual <= 200:
        score += 10
    return round(score, 2)


def preco_suspeito(preco_atual: float, preco_original: float) -> bool:
    if preco_atual <= 0:
        return True
    if preco_original > 0 and preco_atual / preco_original < 0.05:
        return True
    return False


def esta_na_blacklist(produto: dict, blacklist: list[str]) -> bool:
    texto = (produto.get("titulo") or "").lower()
    return any(term.strip().lower() in texto for term in blacklist if term.strip())
