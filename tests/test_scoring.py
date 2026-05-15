from scoring import esta_na_blacklist, preco_suspeito, score_produto


def test_score_high_quality_product() -> None:
    score = score_produto(50, 2500, 4.9, True, 199.90, 8)

    assert score > 250


def test_score_low_quality_product() -> None:
    score = score_produto(0, 0, 0, False, 999.90)

    assert score == 0


def test_preco_suspeito_detects_extreme_discount() -> None:
    assert preco_suspeito(10, 1000)
    assert not preco_suspeito(90, 100)


def test_blacklist_detects_terms() -> None:
    assert esta_na_blacklist({"titulo": "Tenis replica premium"}, ["replica"])
    assert not esta_na_blacklist({"titulo": "Tenis original"}, ["replica"])
