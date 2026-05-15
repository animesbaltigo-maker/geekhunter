import pytest

from extraction_quality import evaluate_product_confidence, require_confident_product


def test_confidence_accepts_complete_product() -> None:
    produto = {
        "platform": "shopee",
        "titulo": "Fone Bluetooth Redmi com Estojo",
        "imagem": "https://down-br.img.susercontent.com/file/item.jpg",
        "preco_atual": 8.39,
        "preco_original": 8.39,
        "source_url": "https://shopee.com.br/product/1/2",
        "extraction_verified": True,
    }

    confidence = evaluate_product_confidence(produto, input_url="https://s.shopee.com.br/abc")

    assert confidence.ok
    assert confidence.score >= 75


def test_confidence_rejects_store_placeholder() -> None:
    produto = {
        "platform": "shopee",
        "titulo": "Shopee Brasil",
        "imagem": "https://deo.shopeemobile.com/shopee/shopee-pcmall-live-sg/assets/logo.png",
        "preco_atual": 8.39,
        "source_url": "https://shopee.com.br",
    }

    confidence = evaluate_product_confidence(produto)

    assert not confidence.ok
    assert "critical:title_missing_or_generic" in confidence.issues
    assert "critical:image_missing_or_placeholder" in confidence.issues


def test_require_confident_product_raises_with_clear_reason() -> None:
    with pytest.raises(ValueError, match="Extracao sem confianca suficiente"):
        require_confident_product({"titulo": "Oferta selecionada", "preco_atual": 0, "imagem": ""})
