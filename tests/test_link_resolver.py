from link_resolver import canonicalize_url, extract_first_url, extract_product_id


def test_extract_first_url_strips_punctuation() -> None:
    assert extract_first_url("olha https://amzn.to/abc123).") == "https://amzn.to/abc123"


def test_canonicalize_amazon_dp_keeps_product_id() -> None:
    url = "https://www.amazon.com.br/Produto-Legal/dp/B0ABC12345/ref=abc?utm_source=x&tag=geek-20"

    assert canonicalize_url(url, "amazon") == "https://www.amazon.com.br/dp/B0ABC12345?tag=geek-20"


def test_canonicalize_mercadolivre_item() -> None:
    url = "https://produto.mercadolivre.com.br/MLB-1234567890-produto-_JM?utm_source=x"

    assert canonicalize_url(url, "mercadolivre") == "https://www.mercadolivre.com.br/p/MLB1234567890"


def test_extract_ids_for_supported_short_target_patterns() -> None:
    assert extract_product_id("https://pt.aliexpress.com/item/1005005902446151.html", "aliexpress") == "1005005902446151"
    assert extract_product_id("https://shopee.com.br/product/1142052307/58257288693", "shopee") == "1142052307:58257288693"
