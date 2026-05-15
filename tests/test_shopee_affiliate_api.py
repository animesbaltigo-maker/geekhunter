from shopee_affiliate_api import shopee_ids_from_url


def test_shopee_ids_from_product_url() -> None:
    ids = shopee_ids_from_url("https://shopee.com.br/product/1142052307/58257288693")

    assert ids is not None
    assert ids.shop_id == "1142052307"
    assert ids.item_id == "58257288693"


def test_shopee_ids_from_path_url() -> None:
    ids = shopee_ids_from_url("https://shopee.com.br/opaanlp/1142052307/58257288693?utm_source=x")

    assert ids is not None
    assert ids.shop_id == "1142052307"
    assert ids.item_id == "58257288693"
