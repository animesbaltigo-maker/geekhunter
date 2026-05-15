from config import Settings
from offer_quality import is_blocked_product, score_product


def test_score_product_rewards_strong_offer() -> None:
    weak = {
        "titulo": "Produto basico",
        "desconto_pct": 5,
        "vendidos": 10,
        "avaliacao": 4.0,
        "frete_gratis": False,
        "preco_atual": 500,
        "preco_original": 550,
        "imagem": "https://img.test/p.jpg",
        "platform": "mercadolivre",
    }
    strong = {
        **weak,
        "desconto_pct": 45,
        "vendidos": "2mil vendidos",
        "avaliacao": 4.8,
        "frete_gratis": True,
        "preco_atual": 150,
        "preco_original": 300,
    }

    assert score_product(strong) > score_product(weak)


def test_blocked_product_uses_settings_filters() -> None:
    settings = Settings(blocked_words=["replica"], max_price=200, min_rating=4.5, min_sold_quantity=20)

    assert is_blocked_product({"titulo": "Tenis replica", "preco_atual": 100}, settings)
    assert is_blocked_product({"titulo": "Tenis", "preco_atual": 300}, settings)
    assert is_blocked_product({"titulo": "Tenis", "preco_atual": 100, "avaliacao": 4.0}, settings)
    assert not is_blocked_product(
        {"titulo": "Tenis original", "preco_atual": 100, "avaliacao": 4.8, "vendidos": "30 vendidos"},
        settings,
    )
