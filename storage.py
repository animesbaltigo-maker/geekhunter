"""SQLite storage for the multi-user Telegram bot and background services."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from time import time
from typing import Any


class Storage:
    def __init__(self, path: str = "data/multiuser.sqlite3") -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=WAL")
        self.conn.execute("pragma busy_timeout=30000")
        self.conn.execute("pragma foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                create table if not exists users (
                    telegram_user_id integer primary key,
                    first_name text,
                    username text,
                    state text,
                    state_data text,
                    plan text default 'free',
                    plan_expires_at real,
                    plan_updated_at real,
                    created_at real not null,
                    updated_at real not null
                );

                create table if not exists channels (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    channel_id text not null,
                    channel_title text,
                    channel_username text,
                    created_at real not null,
                    unique(telegram_user_id, channel_id)
                );

                create table if not exists posts (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    channel_id text not null,
                    product_url text not null,
                    affiliate_url text,
                    telegram_message_id integer,
                    status text not null,
                    error text,
                    created_at real not null
                );

                create table if not exists pending_posts (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    product_url text not null,
                    channel_db_id integer,
                    product_json text,
                    caption text,
                    image_url text,
                    created_at real not null,
                    updated_at real
                );

                create table if not exists user_rate_events (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    event_type text not null,
                    created_at real not null
                );

                create table if not exists subscriptions (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    plan text not null,
                    status text not null,
                    expires_at real,
                    changed_by integer,
                    created_at real not null
                );

                create table if not exists activation_codes (
                    code text primary key,
                    plan text not null,
                    duration_days integer not null,
                    used_by integer,
                    used_at real
                );

                create table if not exists link_cache (
                    link_original text primary key,
                    short_url text not null,
                    created_at real not null
                );

                create table if not exists posted_history (
                    item_id text primary key,
                    posted_at real not null,
                    price real,
                    lowest_price real
                );

                create table if not exists autopost_kv (
                    key text primary key,
                    value text not null,
                    updated_at real not null
                );

                create table if not exists price_history (
                    item_id text not null,
                    price real not null,
                    original_price real,
                    discount_pct integer,
                    source text,
                    recorded_at real not null,
                    primary key (item_id, recorded_at)
                );

                create table if not exists price_alerts (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    item_id text not null,
                    product_url text not null,
                    affiliate_url text,
                    product_title text,
                    image_url text,
                    current_price real,
                    target_price real,
                    platform text,
                    notify_any_drop integer default 0,
                    status text default 'active',
                    created_at real not null,
                    last_checked_at real,
                    triggered_at real
                );

                create table if not exists system_status (
                    key text primary key,
                    value text not null,
                    updated_at real not null
                );

                create table if not exists offer_requests (
                    id integer primary key autoincrement,
                    telegram_user_id integer not null,
                    term text not null,
                    created_at real not null
                );

                create table if not exists extraction_failures (
                    id integer primary key autoincrement,
                    telegram_user_id integer,
                    platform text,
                    product_url text not null,
                    final_url text,
                    method text,
                    error text not null,
                    confidence_score integer,
                    confidence_issues text,
                    created_at real not null
                );
                """
            )
            for column, definition in {
                "plan": "text default 'free'",
                "plan_expires_at": "real",
                "plan_updated_at": "real",
            }.items():
                self._ensure_column("users", column, definition)
            for column, definition in {
                "channel_db_id": "integer",
                "product_json": "text",
                "caption": "text",
                "image_url": "text",
                "updated_at": "real",
            }.items():
                self._ensure_column("pending_posts", column, definition)
            for column, definition in {
                "price": "real",
                "lowest_price": "real",
            }.items():
                self._ensure_column("posted_history", column, definition)
            self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cols = {row["name"] for row in self.conn.execute(f"pragma table_info({table})")}
        if column not in cols:
            self.conn.execute(f"alter table {table} add column {column} {definition}")

    def upsert_user(self, user: dict[str, Any]) -> None:
        now = time()
        with self._lock:
            self.conn.execute(
                """
                insert into users (telegram_user_id, first_name, username, created_at, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(telegram_user_id) do update set
                    first_name=excluded.first_name,
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (user["id"], user.get("first_name"), user.get("username"), now, now),
            )
            self.conn.commit()

    def set_state(self, user_id: int, state: str | None, data: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "update users set state=?, state_data=?, updated_at=? where telegram_user_id=?",
                (state, json.dumps(data or {}), time(), user_id),
            )
            self.conn.commit()

    def get_state(self, user_id: int) -> tuple[str | None, dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "select state, state_data from users where telegram_user_id=?",
                (user_id,),
            ).fetchone()
        if not row:
            return None, {}
        return row["state"], json.loads(row["state_data"] or "{}")

    def get_user_plan(self, user_id: int) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "select plan, plan_expires_at from users where telegram_user_id=?",
                (user_id,),
            ).fetchone()
        plan = str(row["plan"] if row and row["plan"] else "free").lower()
        expires_at = float(row["plan_expires_at"] or 0) if row else 0.0
        if plan == "pro" and expires_at > 0 and expires_at <= time():
            plan = "free"
        if plan not in {"free", "pro"}:
            plan = "free"
        return {"plan": plan, "expires_at": expires_at or None}

    def set_user_plan(
        self,
        user_id: int,
        plan: str,
        expires_at: float | None = None,
        changed_by: int | None = None,
    ) -> None:
        normalized = plan.strip().lower()
        if normalized not in {"free", "pro"}:
            raise ValueError("plan must be free or pro")
        now = time()
        status = "active" if normalized == "pro" else "disabled"
        with self._lock:
            self.conn.execute(
                """
                insert into users (telegram_user_id, plan, plan_expires_at, plan_updated_at, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict(telegram_user_id) do update set
                    plan=excluded.plan,
                    plan_expires_at=excluded.plan_expires_at,
                    plan_updated_at=excluded.plan_updated_at,
                    updated_at=excluded.updated_at
                """,
                (user_id, normalized, expires_at, now, now, now),
            )
            self.conn.execute(
                """
                insert into subscriptions
                    (telegram_user_id, plan, status, expires_at, changed_by, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (user_id, normalized, status, expires_at, changed_by, now),
            )
            self.conn.commit()

    def add_activation_code(self, code: str, plan: str = "pro", duration_days: int = 30) -> None:
        normalized_plan = plan.strip().lower()
        if normalized_plan not in {"free", "pro"}:
            raise ValueError("plan must be free or pro")
        clean_code = code.strip().upper()
        if not clean_code:
            raise ValueError("code is required")
        with self._lock:
            self.conn.execute(
                """
                insert into activation_codes (code, plan, duration_days)
                values (?, ?, ?)
                on conflict(code) do update set
                    plan=excluded.plan,
                    duration_days=excluded.duration_days
                """,
                (clean_code, normalized_plan, max(1, int(duration_days))),
            )
            self.conn.commit()

    def redeem_activation_code(self, user_id: int, code: str) -> dict[str, Any] | None:
        clean_code = code.strip().upper()
        now = time()
        with self._lock:
            row = self.conn.execute(
                """
                select code, plan, duration_days, used_by
                from activation_codes
                where code=?
                """,
                (clean_code,),
            ).fetchone()
            if not row or row["used_by"]:
                return None
            expires_at = now + int(row["duration_days"]) * 86400 if row["plan"] == "pro" else None
            self.conn.execute(
                "update activation_codes set used_by=?, used_at=? where code=?",
                (user_id, now, clean_code),
            )
            self.conn.commit()
        self.set_user_plan(user_id, str(row["plan"]), expires_at, changed_by=None)
        return {
            "code": clean_code,
            "plan": str(row["plan"]),
            "duration_days": int(row["duration_days"]),
            "expires_at": expires_at,
        }

    def add_channel(self, user_id: int, channel: dict[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """
                insert or replace into channels
                    (telegram_user_id, channel_id, channel_title, channel_username, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (user_id, str(channel["id"]), channel.get("title"), channel.get("username"), time()),
            )
            self.conn.commit()

    def list_channels(self, user_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self.conn.execute(
                    "select * from channels where telegram_user_id=? order by created_at desc",
                    (user_id,),
                )
            )

    def get_channel(self, channel_db_id: int, user_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "select * from channels where id=? and telegram_user_id=?",
                (channel_db_id, user_id),
            ).fetchone()

    def remove_channel(self, channel_db_id: int, user_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "delete from channels where id=? and telegram_user_id=?",
                (channel_db_id, user_id),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def can_add_channel(self, user_id: int, free_limit: int = 1, pro_limit: int = 0) -> tuple[bool, int, int, str]:
        plan = str(self.get_user_plan(user_id)["plan"])
        limit = pro_limit if plan == "pro" else free_limit
        count = len(self.list_channels(user_id))
        return (True, count, limit, plan) if limit <= 0 else (count < limit, count, limit, plan)

    def add_pending_post(
        self,
        user_id: int,
        product_url: str,
        channel_db_id: int | None = None,
        product: dict[str, Any] | None = None,
        caption: str | None = None,
        image_url: str | None = None,
    ) -> int:
        now = time()
        with self._lock:
            cur = self.conn.execute(
                """
                insert into pending_posts
                    (telegram_user_id, product_url, channel_db_id, product_json, caption, image_url, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    product_url,
                    channel_db_id,
                    json.dumps(product or {}, ensure_ascii=False),
                    caption,
                    image_url,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def update_pending_post(
        self,
        pending_id: int,
        user_id: int,
        *,
        product: dict[str, Any] | None = None,
        caption: str | None = None,
        image_url: str | None = None,
        channel_db_id: int | None = None,
    ) -> None:
        pending = self.get_pending_post(pending_id, user_id)
        if not pending:
            return
        with self._lock:
            self.conn.execute(
                """
                update pending_posts
                set product_json=?, caption=?, image_url=?, channel_db_id=?, updated_at=?
                where id=? and telegram_user_id=?
                """,
                (
                    json.dumps(product if product is not None else self.pending_product(pending), ensure_ascii=False),
                    caption if caption is not None else pending["caption"],
                    image_url if image_url is not None else pending["image_url"],
                    channel_db_id if channel_db_id is not None else pending["channel_db_id"],
                    time(),
                    pending_id,
                    user_id,
                ),
            )
            self.conn.commit()

    def get_pending_post(self, pending_id: int, user_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "select * from pending_posts where id=? and telegram_user_id=?",
                (pending_id, user_id),
            ).fetchone()

    def pending_product(self, pending: sqlite3.Row) -> dict[str, Any]:
        try:
            return json.loads(pending["product_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    def delete_pending_post(self, pending_id: int, user_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "delete from pending_posts where id=? and telegram_user_id=?",
                (pending_id, user_id),
            )
            self.conn.commit()

    def add_post(
        self,
        user_id: int,
        channel_id: str,
        product_url: str,
        affiliate_url: str | None,
        status: str,
        telegram_message_id: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                insert into posts
                    (telegram_user_id, channel_id, product_url, affiliate_url, telegram_message_id, status, error, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, channel_id, product_url, affiliate_url, telegram_message_id, status, error, time()),
            )
            self.conn.commit()

    def posts_today(self, user_id: int) -> int:
        since_day = time() - 86400
        with self._lock:
            row = self.conn.execute(
                "select count(*) as total from posts where telegram_user_id=? and status='posted' and created_at>=?",
                (user_id, since_day),
            ).fetchone()
        return int(row["total"] if row else 0)

    def can_post_today(self, user_id: int, free_limit: int = 20, pro_limit: int = 0) -> tuple[bool, int, int, str]:
        plan = str(self.get_user_plan(user_id)["plan"])
        limit = pro_limit if plan == "pro" else free_limit
        count = self.posts_today(user_id)
        return (True, count, limit, plan) if limit <= 0 else (count < limit, count, limit, plan)

    def count_rate_events(self, user_id: int, event_type: str, since_ts: float) -> int:
        with self._lock:
            row = self.conn.execute(
                """
                select count(*) as total from user_rate_events
                where telegram_user_id=? and event_type=? and created_at>=?
                """,
                (user_id, event_type, since_ts),
            ).fetchone()
        return int(row["total"] if row else 0)

    def add_rate_event(self, user_id: int, event_type: str) -> None:
        with self._lock:
            self.conn.execute(
                "insert into user_rate_events (telegram_user_id, event_type, created_at) values (?, ?, ?)",
                (user_id, event_type, time()),
            )
            self.conn.execute("delete from user_rate_events where created_at<?", (time() - 86400,))
            self.conn.commit()

    def ping(self) -> bool:
        with self._lock:
            row = self.conn.execute("select 1 as ok").fetchone()
        return bool(row and row["ok"] == 1)

    def user_post_stats(self, user_id: int) -> dict[str, int]:
        since_day = time() - 86400
        since_week = time() - (7 * 86400)
        with self._lock:
            total = self.conn.execute(
                "select count(*) as total from posts where telegram_user_id=? and status='posted'",
                (user_id,),
            ).fetchone()["total"]
            today = self.conn.execute(
                "select count(*) as total from posts where telegram_user_id=? and status='posted' and created_at>=?",
                (user_id, since_day),
            ).fetchone()["total"]
            errors = self.conn.execute(
                "select count(*) as total from posts where telegram_user_id=? and status='error' and created_at>=?",
                (user_id, since_week),
            ).fetchone()["total"]
            channels = self.conn.execute(
                "select count(*) as total from channels where telegram_user_id=?",
                (user_id,),
            ).fetchone()["total"]
        return {
            "channels": int(channels),
            "posts_total": int(total),
            "posts_today": int(today),
            "errors_7d": int(errors),
        }

    def admin_stats(self) -> dict[str, int]:
        since_day = time() - 86400
        since_week = time() - (7 * 86400)
        now = time()
        with self._lock:
            users = self.conn.execute("select count(*) as total from users").fetchone()["total"]
            pro_users = self.conn.execute(
                "select count(*) as total from users where plan='pro' and (plan_expires_at is null or plan_expires_at>?)",
                (now,),
            ).fetchone()["total"]
            channels = self.conn.execute("select count(*) as total from channels").fetchone()["total"]
            posts = self.conn.execute("select count(*) as total from posts where status='posted'").fetchone()["total"]
            posts_today = self.conn.execute(
                "select count(*) as total from posts where status='posted' and created_at>=?",
                (since_day,),
            ).fetchone()["total"]
            errors_7d = self.conn.execute(
                "select count(*) as total from posts where status='error' and created_at>=?",
                (since_week,),
            ).fetchone()["total"]
        return {
            "users": int(users),
            "pro_users": int(pro_users),
            "channels": int(channels),
            "posts_total": int(posts),
            "posts_today": int(posts_today),
            "errors_7d": int(errors_7d),
        }

    def admin_user_summary(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self.conn.execute(
                    """
                    select u.telegram_user_id, u.first_name, u.username,
                           coalesce(u.plan, 'free') as plan, u.plan_expires_at, u.updated_at,
                           count(distinct c.id) as channels,
                           count(distinct case when p.status='posted' then p.id end) as posts_total
                    from users u
                    left join channels c on c.telegram_user_id = u.telegram_user_id
                    left join posts p on p.telegram_user_id = u.telegram_user_id
                    group by u.telegram_user_id
                    order by u.updated_at desc
                    limit ?
                    """,
                    (limit,),
                )
            )

    def recent_posts(self, user_id: int, limit: int = 5) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self.conn.execute(
                    """
                    select channel_id, product_url, affiliate_url, telegram_message_id, status, error, created_at
                    from posts where telegram_user_id=?
                    order by created_at desc limit ?
                    """,
                    (user_id, limit),
                )
            )

    def get_recent_posts(self, hours: int = 24, limit: int = 50) -> list[sqlite3.Row]:
        cutoff = time() - hours * 3600
        with self._lock:
            return list(
                self.conn.execute(
                    """
                    select * from posts
                    where created_at>=?
                    order by created_at desc
                    limit ?
                    """,
                    (cutoff, limit),
                )
            )

    def kv_get(self, table: str, key: str) -> str | None:
        if table not in {"autopost_kv", "system_status"}:
            raise ValueError("invalid kv table")
        with self._lock:
            row = self.conn.execute(f"select value from {table} where key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def kv_set(self, table: str, key: str, value: str) -> None:
        if table not in {"autopost_kv", "system_status"}:
            raise ValueError("invalid kv table")
        with self._lock:
            self.conn.execute(
                f"""
                insert into {table} (key, value, updated_at)
                values (?, ?, ?)
                on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, time()),
            )
            self.conn.commit()

    def link_cache_get(self, link_original: str, ttl_seconds: int = 7 * 86400) -> str | None:
        cutoff = time() - ttl_seconds
        with self._lock:
            row = self.conn.execute(
                "select short_url from link_cache where link_original=? and created_at>=?",
                (link_original, cutoff),
            ).fetchone()
        return str(row["short_url"]) if row else None

    def link_cache_set(self, link_original: str, short_url: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                insert into link_cache (link_original, short_url, created_at)
                values (?, ?, ?)
                on conflict(link_original) do update set short_url=excluded.short_url, created_at=excluded.created_at
                """,
                (link_original, short_url, time()),
            )
            self.conn.commit()

    def add_offer_request(self, user_id: int, term: str) -> None:
        with self._lock:
            self.conn.execute(
                "insert into offer_requests (telegram_user_id, term, created_at) values (?, ?, ?)",
                (user_id, term.strip(), time()),
            )
            self.conn.commit()

    def count_offer_requests(self, term: str, days: int = 7) -> int:
        cutoff = time() - days * 86400
        normalized = term.strip().lower()
        with self._lock:
            row = self.conn.execute(
                """
                select count(*) as total
                from offer_requests
                where lower(term)=? and created_at>=?
                """,
                (normalized, cutoff),
            ).fetchone()
        return int(row["total"] if row else 0)

    def top_offer_requests(self, days: int = 7, limit: int = 3) -> list[str]:
        cutoff = time() - days * 86400
        with self._lock:
            rows = self.conn.execute(
                """
                select lower(term) as term, count(*) as total
                from offer_requests
                where created_at>=?
                group by lower(term)
                order by total desc
                limit ?
                """,
                (cutoff, limit),
            ).fetchall()
        return [str(row["term"]) for row in rows]

    def add_extraction_failure(
        self,
        product_url: str,
        error: str,
        *,
        user_id: int | None = None,
        platform: str | None = None,
        final_url: str | None = None,
        method: str | None = None,
        confidence_score: int | None = None,
        confidence_issues: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                insert into extraction_failures
                    (telegram_user_id, platform, product_url, final_url, method, error,
                     confidence_score, confidence_issues, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    platform,
                    product_url,
                    final_url,
                    method,
                    error[:1000],
                    confidence_score,
                    json.dumps(list(confidence_issues or []), ensure_ascii=False),
                    time(),
                ),
            )
            self.conn.commit()

    def recent_extraction_failures(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self.conn.execute(
                    """
                    select *
                    from extraction_failures
                    order by created_at desc
                    limit ?
                    """,
                    (limit,),
                )
            )

    def active_price_alert_count(self, user_id: int) -> int:
        with self._lock:
            row = self.conn.execute(
                """
                select count(*) as total
                from price_alerts
                where telegram_user_id=? and status='active'
                """,
                (user_id,),
            ).fetchone()
        return int(row["total"] if row else 0)
