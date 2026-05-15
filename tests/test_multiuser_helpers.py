from multiuser_bot import _is_valid_product_url, buy_keyboard, preview_keyboard


def test_product_url_validation_allows_supported_http_urls() -> None:
    assert _is_valid_product_url("https://www.mercadolivre.com.br/p/MLB123")
    assert not _is_valid_product_url("javascript:alert(1)")
    assert not _is_valid_product_url("https://example.com/produto")


def test_preview_and_buy_keyboards() -> None:
    preview = preview_keyboard(55)
    buy = buy_keyboard("https://mercadolivre.com.br/p/MLB123")

    assert preview["inline_keyboard"][0][0]["callback_data"] == "preview:publish:55"
    assert buy["inline_keyboard"][0][0]["url"] == "https://mercadolivre.com.br/p/MLB123"
