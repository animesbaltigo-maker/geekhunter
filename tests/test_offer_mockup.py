from PIL import Image

from offer_mockup import _render_card


def test_render_offer_mockup_card() -> None:
    product_image = Image.new("RGBA", (400, 300), (120, 100, 200, 255))
    produto = {
        "titulo": "Smartphone Samsung Galaxy S26 Ultra 5G 256GB Violeta",
        "preco_atual": 5817.60,
        "preco_original": 11499.00,
        "desconto_pct": 49,
    }

    background = Image.new("RGB", (1080, 1920), (22, 22, 22))
    card = _render_card(produto, product_image, "@GeekHunter_Br", background=background)

    assert card.size == (1080, 1350)
    assert card.mode == "RGB"
