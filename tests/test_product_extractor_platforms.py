from product_extractor import _extract_from_html


def test_extract_amazon_from_specific_selectors() -> None:
    html = """
    <html>
      <head><meta property="og:image" content="https://images.amazon.test/prod.jpg"></head>
      <body>
        <span id="productTitle">Echo Pop Smart Speaker</span>
        <div id="corePriceDisplay_desktop_feature_div">
          <span class="a-price"><span class="a-offscreen">R$ 249,90</span></span>
        </div>
      </body>
    </html>
    """

    produto = _extract_from_html("https://www.amazon.com.br/dp/B0TEST", html, "amazon")

    assert produto["titulo"] == "Echo Pop Smart Speaker"
    assert produto["imagem"] == "https://images.amazon.test/prod.jpg"
    assert produto["preco_atual"] == 249.90


def test_extract_shopee_from_og_tags_and_price_text() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Controle Bluetooth para Celular">
        <meta property="og:image" content="https://down-shopee.test/item.jpg">
      </head>
      <body>
        <main>
          <div>R$ 89,90</div>
          <button>Comprar Agora</button>
        </main>
      </body>
    </html>
    """

    produto = _extract_from_html("https://shopee.com.br/product/1/2", html, "shopee")

    assert produto["titulo"] == "Controle Bluetooth para Celular"
    assert produto["imagem"] == "https://down-shopee.test/item.jpg"
    assert produto["preco_atual"] == 89.90


def test_extract_shein_from_json_ld() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
          {
            "@type": "Product",
            "name": "Camiseta Basica Geek",
            "image": ["https://img.shein.test/camiseta.jpg"],
            "offers": {"price": "59.99"}
          }
        </script>
      </body>
    </html>
    """

    produto = _extract_from_html("https://br.shein.com/product/camiseta-p-123.html", html, "shein")

    assert produto["titulo"] == "Camiseta Basica Geek"
    assert produto["imagem"] == "https://img.shein.test/camiseta.jpg"
    assert produto["preco_atual"] == 59.99
