import json

from history import PostedHistory


def test_history_normalizes_old_tracked_urls_and_blocks_same_or_higher_price(tmp_path) -> None:
    path = tmp_path / "posted_items.json"
    path.write_text(
        json.dumps(
            {
                "https://produto.mercadolivre.com.br/MLB-3482047960-jaqueta-_JM"
                "?searchVariation=1#deal_print_id=abc": 1778733304.0
            }
        ),
        encoding="utf-8",
    )

    history = PostedHistory(str(path))

    assert history.seen("MLB3482047960")
    assert history.should_skip("MLB3482047960", 99.90)


def test_history_allows_repost_only_below_lowest_posted_price(tmp_path) -> None:
    history = PostedHistory(str(tmp_path / "posted_items.json"))
    history.mark("MLB3482047960", 100.0)

    assert history.should_skip("MLB3482047960", 100.0)
    assert history.should_skip("MLB3482047960", 110.0)
    assert not history.should_skip("MLB3482047960", 89.90)

    history.mark("MLB3482047960", 89.90)

    assert history.should_skip("MLB3482047960", 95.0)
    assert not history.should_skip("MLB3482047960", 79.90)


def test_history_blocks_same_title_fingerprint_with_same_price(tmp_path) -> None:
    history = PostedHistory(str(tmp_path / "posted_items.json"))
    key = "title:like-dragon-pirate-yakuza-hawaii-ps4-midia-fisica"

    history.mark(key, 129.90)

    assert history.should_skip(key, 129.90)
    assert history.should_skip(key, 139.90)
    assert not history.should_skip(key, 119.90)
