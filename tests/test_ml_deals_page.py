from types import SimpleNamespace

from ml_deals_page import _parse_offer_page


def test_parse_ml_offer_page_card() -> None:
    html = """
    <div class="poly-card">
      <div class="poly-card__portada">
        <img class="poly-component__picture" src="https://http2.mlstatic.com/D_Q_NP_2X_123-MLB.jpg" />
      </div>
      <div class="poly-card__content">
        <h3><a class="poly-component__title" href="https://www.mercadolivre.com.br/produto/p/MLB1234567?wid=MLB999999">
          Produto Gamer em Oferta
        </a></h3>
        <div class="poly-component__reviews">
          <span class="poly-reviews__rating">4.8</span>
        </div>
        <div class="poly-component__price">
          <s class="andes-money-amount--previous" aria-label="Antes: 1000 reais"></s>
          <div class="poly-price__current">
            <span class="andes-money-amount" aria-label="Agora: 699 reais com 90 centavos"></span>
            <span class="poly-price__disc_label">30% OFF</span>
          </div>
          <span class="poly-price__installments">em 10x sem juros</span>
        </div>
        <div class="poly-component__shipping"><span>Frete gratis</span></div>
      </div>
    </div>
    """
    settings = SimpleNamespace(
        min_discount_pct=10,
        max_price=None,
        affiliate_url_template=None,
        affiliate_link_mode="template",
        ml_affiliate_label_id=None,
        ml_affiliate_matt_tool="93444346",
        blocked_words=[],
        min_rating=0,
        min_sold_quantity=0,
    )

    products = _parse_offer_page(html, settings)

    assert len(products) == 1
    assert products[0]["titulo"] == "Produto Gamer em Oferta"
    assert products[0]["preco_atual"] == 699.90
    assert products[0]["preco_original"] == 1000.0
    assert products[0]["desconto_pct"] == 30
    assert products[0]["frete_gratis"] is True
