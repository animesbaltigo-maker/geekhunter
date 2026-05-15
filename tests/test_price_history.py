from price_history import PriceHistory, canonical_product_key, product_keys


def test_price_history_marks_historical_low_after_existing_records(tmp_path) -> None:
    history = PriceHistory(str(tmp_path / "multiuser.sqlite3"))
    product = {
        "id": "MLB123",
        "titulo": "Produto",
        "preco_atual": 100.0,
        "preco_original": 150.0,
        "desconto_pct": 33,
    }

    first = history.record_product(product, "test")
    second = history.record_product({**product, "preco_atual": 90.0}, "test")
    third = history.record_product({**product, "preco_atual": 110.0}, "test")

    assert first.get("historical_low") is False
    assert second.get("historical_low") is False
    assert third.get("historical_low") is False

    low = history.record_product({**product, "preco_atual": 80.0}, "test")

    assert low.get("historical_low") is True
    assert low.get("price_30d_avg") is not None


def test_canonical_product_key_ignores_ml_tracking_url_parts() -> None:
    first = (
        "https://produto.mercadolivre.com.br/MLB-3482047960-jaqueta-de-couro-_JM"
        "?searchVariation=177449513490#polycard_client=offers&deal_print_id=abc"
    )
    second = (
        "https://produto.mercadolivre.com.br/MLB-3482047960-jaqueta-de-couro-_JM"
        "?searchVariation=177449513498#polycard_client=offers&deal_print_id=def"
    )

    assert canonical_product_key(first) == "MLB3482047960"
    assert canonical_product_key(second) == "MLB3482047960"


def test_product_keys_include_title_fingerprint_for_unstable_ids() -> None:
    keys = product_keys(
        {
            "id": "tracking-abc",
            "titulo": "Like A Dragon Pirate Yakuza In Hawaii Ps4 Midia Fisica",
            "link_original": "https://example.test/oferta?tracking=1",
        }
    )

    assert "tracking-abc" in keys
    assert "title:like-dragon-pirate-yakuza-hawaii-ps4-midia-fisica" in keys
