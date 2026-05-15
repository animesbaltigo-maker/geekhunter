import asyncio

import pytest

from ai_generator import gerar_post, gerar_post_fallback
from config import Settings


def test_ai_fallback_provider_uses_local_copy() -> None:
    settings = Settings(ai_provider="fallback", post_emojis=False)
    produto = {"titulo": "Air Fryer 5L", "preco_atual": 199.9, "link": "https://mercadolivre.com.br/p/MLB123"}

    text = asyncio.run(gerar_post(produto, settings))

    assert text == gerar_post_fallback(produto, use_emojis=False)
    assert "Air Fryer" in text


def test_ai_provider_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(ai_provider="openai", openai_api_key="secret", ai_model="x", post_emojis=False)
    produto = {"titulo": "Produto Teste", "preco_atual": 50, "link": "https://mercadolivre.com.br/p/MLB123"}

    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("ai_generator._gerar_openai_compat", boom)

    text = asyncio.run(gerar_post(produto, settings))

    assert text == gerar_post_fallback(produto, use_emojis=False)


def test_ai_provider_response_with_link_falls_back_to_clean_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(ai_provider="groq", groq_api_key="secret", post_emojis=False)
    produto = {"titulo": "Produto Teste", "preco_atual": 50, "link": "https://mercadolivre.com.br/p/MLB123"}

    async def fake_provider(*args, **kwargs):
        return '<b>Oferta</b><script>alert(1)</script><a href="https://x.test">link</a>'

    monkeypatch.setattr("ai_generator._gerar_openai_compat", fake_provider)

    text = asyncio.run(gerar_post(produto, settings))

    assert "<b>Produto Teste</b>" in text
    assert "Preço encontrado" in text
    assert "<script" not in text
    assert "href=" not in text
    assert produto["link"] not in text


def test_fallback_includes_historical_low_badge() -> None:
    settings = Settings(ai_provider="fallback", post_emojis=False)
    produto = {
        "titulo": "Produto Teste",
        "preco_atual": 80,
        "preco_original": 120,
        "desconto_pct": 33,
        "historical_low": True,
        "link": "https://mercadolivre.com.br/p/MLB123",
    }

    text = asyncio.run(gerar_post(produto, settings))

    assert "Menor preço registrado" in text
