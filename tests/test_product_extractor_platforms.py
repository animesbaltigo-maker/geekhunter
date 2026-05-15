from product_extractor import _extract_from_html
from multiuser_bot import _produto_valido


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


def test_extract_aliexpress_from_json_like_payload() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Cabo USB C Turbo 100W">
        <meta property="og:image" content="//ae01.alicdn.test/item.jpg">
      </head>
      <body>
        <script>
          window.runParams = {
            "salePrice": "R$ 29,90",
            "originalPrice": "R$ 59,90"
          };
        </script>
      </body>
    </html>
    """

    produto = _extract_from_html("https://pt.aliexpress.com/item/100500123.html", html, "aliexpress")

    assert produto["titulo"] == "Cabo USB C Turbo 100W"
    assert produto["imagem"] == "https://ae01.alicdn.test/item.jpg"
    assert produto["preco_atual"] == 29.90
    assert produto["desconto_pct"] == 50


def test_extract_magalu_from_json_ld() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
          {
            "@type": "Product",
            "name": "Fone Bluetooth Magalu",
            "image": "https://img.magalu.test/fone.jpg",
            "offers": {"price": "99.90", "highPrice": "149.90"}
          }
        </script>
      </body>
    </html>
    """

    produto = _extract_from_html("https://www.magazineluiza.com.br/fone/p/abc123", html, "magalu")

    assert produto["titulo"] == "Fone Bluetooth Magalu"
    assert produto["imagem"] == "https://img.magalu.test/fone.jpg"
    assert produto["preco_atual"] == 99.90


def test_extract_natura_from_json_ld() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
          {
            "@type": "Product",
            "name": "Natura Essencial Masculino",
            "image": ["https://static.natura.test/perfume.jpg"],
            "offers": {"price": "129.90"}
          }
        </script>
      </body>
    </html>
    """

    produto = _extract_from_html("https://www.natura.com.br/p/essencial-masculino", html, "natura")

    assert produto["titulo"] == "Natura Essencial Masculino"
    assert produto["imagem"] == "https://static.natura.test/perfume.jpg"
    assert produto["preco_atual"] == 129.90


def test_multiuser_validation_rejects_placeholder_shopee_preview() -> None:
    produto = {
        "titulo": "Oferta selecionada",
        "imagem": "https://deo.shopeemobile.com/shopee/shopee-logo.png",
        "preco_atual": 0,
    }

    assert not _produto_valido(produto)


def test_extract_mercadolivre_social_uses_og_product_and_matching_price() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Colônia Linda Felicidade 100ml O Boticário">
        <meta property="og:image" content="https://http2.mlstatic.test/colonia.webp">
      </head>
      <body>
        <script>
          {"type":"price","price":{"previous_price":{"value":143.00,"currency":"BRL"},"current_price":{"value":35.75,"currency":"BRL"},"discount":{"value":75}}}
        </script>
      </body>
    </html>
    """

    produto = _extract_from_html("https://www.mercadolivre.com.br/social/sk123", html, "mercadolivre")

    assert produto["titulo"] == "Colônia Linda Felicidade 100ml O Boticário"
    assert produto["imagem"] == "https://http2.mlstatic.test/colonia.webp"
    assert produto["preco_atual"] == 35.75
    assert produto["preco_original"] == 143.0


def test_extract_aliexpress_uses_affiliate_url_price_payload() -> None:
    url = "https://pt.aliexpress.com/item/1005005902446151.html?pdp_npi=6%40dis%21BRL%2156.74%2117.59%21%21"
    html = """
    <html>
      <head>
        <meta property="og:title" content="Lentes Verdes Coloridas AliExpress">
        <meta property="og:image" content="https://ae01.alicdn.test/lentes.jpg">
      </head>
    </html>
    """

    produto = _extract_from_html(url, html, "aliexpress")

    assert produto["titulo"] == "Lentes Verdes Coloridas AliExpress"
    assert produto["preco_atual"] == 17.59
    assert produto["preco_original"] == 56.74
    assert produto["desconto_pct"] == 69
