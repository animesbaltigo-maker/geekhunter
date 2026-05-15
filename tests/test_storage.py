from time import time

from storage import Storage


def test_storage_migrates_pending_preview_columns(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))

    pending_id = db.add_pending_post(
        123,
        "https://mercadolivre.com.br/p/MLB123",
        1,
        {"titulo": "Produto", "link": "https://mercadolivre.com.br/p/MLB123"},
        "<b>Produto</b>",
        "https://img.test/p.jpg",
    )
    row = db.get_pending_post(pending_id, 123)

    assert row is not None
    assert row["caption"] == "<b>Produto</b>"
    assert db.pending_product(row)["titulo"] == "Produto"


def test_storage_rate_events_are_counted(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))

    db.add_rate_event(123, "link")

    assert db.count_rate_events(123, "link", time() - 60) == 1
    assert db.count_rate_events(123, "post", time() - 60) == 0


def test_storage_user_stats_and_recent_posts(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.upsert_user({"id": 123, "first_name": "Teste", "username": "teste"})
    db.add_channel(123, {"id": -100, "title": "Canal", "username": "canal"})
    db.add_post(123, "-100", "https://mercadolivre.com.br/p/MLB123", None, "posted", 10)
    db.add_post(123, "-100", "https://mercadolivre.com.br/p/MLB124", None, "error", error="x")

    stats = db.user_post_stats(123)
    recent = db.recent_posts(123)

    assert db.ping()
    assert stats["channels"] == 1
    assert stats["posts_total"] == 1
    assert stats["errors_7d"] == 1
    assert len(recent) == 2


def test_storage_plan_defaults_and_expiration(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.upsert_user({"id": 123, "first_name": "Teste"})

    assert db.get_user_plan(123)["plan"] == "free"

    db.set_user_plan(123, "pro", time() + 3600, changed_by=1)
    assert db.get_user_plan(123)["plan"] == "pro"

    db.set_user_plan(123, "pro", time() - 10, changed_by=1)
    assert db.get_user_plan(123)["plan"] == "free"


def test_storage_channel_limits_by_plan(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.upsert_user({"id": 123, "first_name": "Teste"})
    db.add_channel(123, {"id": -100, "title": "Canal", "username": "canal"})

    allowed, count, limit, plan = db.can_add_channel(123, free_limit=1, pro_limit=0)
    assert (allowed, count, limit, plan) == (False, 1, 1, "free")

    db.set_user_plan(123, "pro", time() + 3600, changed_by=1)
    allowed, count, limit, plan = db.can_add_channel(123, free_limit=1, pro_limit=0)
    assert (allowed, count, limit, plan) == (True, 1, 0, "pro")


def test_storage_daily_post_limits_by_plan(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.upsert_user({"id": 123, "first_name": "Teste"})
    for index in range(20):
        db.add_post(123, "-100", f"https://example.test/{index}", None, "posted", index)

    allowed, count, limit, plan = db.can_post_today(123, free_limit=20, pro_limit=0)
    assert (allowed, count, limit, plan) == (False, 20, 20, "free")

    db.set_user_plan(123, "pro", time() + 3600, changed_by=1)
    allowed, count, limit, plan = db.can_post_today(123, free_limit=20, pro_limit=0)
    assert (allowed, count, limit, plan) == (True, 20, 0, "pro")


def test_storage_redeems_activation_code_once(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.upsert_user({"id": 123, "first_name": "Teste"})
    db.upsert_user({"id": 456, "first_name": "Outro"})
    db.add_activation_code("PRO30", "pro", 30)

    result = db.redeem_activation_code(123, "pro30")

    assert result is not None
    assert result["plan"] == "pro"
    assert result["duration_days"] == 30
    assert db.get_user_plan(123)["plan"] == "pro"
    assert db.redeem_activation_code(456, "PRO30") is None


def test_storage_offer_requests_and_alert_count(tmp_path) -> None:
    db = Storage(str(tmp_path / "multiuser.sqlite3"))
    db.add_offer_request(123, "Air Fryer")
    db.add_offer_request(456, "air fryer")

    with db._lock:
        db.conn.execute(
            """
            insert into price_alerts
                (telegram_user_id, item_id, product_url, status, created_at)
            values (?, ?, ?, 'active', ?)
            """,
            (123, "item-1", "https://example.test/1", time()),
        )
        db.conn.commit()

    assert db.count_offer_requests("air fryer") == 2
    assert db.top_offer_requests(days=7, limit=1) == ["air fryer"]
    assert db.active_price_alert_count(123) == 1
