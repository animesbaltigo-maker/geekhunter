"""SQLite storage for the multi-user Telegram bot."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time
from typing import Any


class Storage:
    def __init__(self, path: str = "data/multiuser.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            create table if not exists users (
                telegram_user_id integer primary key,
                first_name text,
                username text,
                state text,
                state_data text,
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
                created_at real not null
            );
            """
        )
        self.conn.commit()

    def upsert_user(self, user: dict[str, Any]) -> None:
        now = time()
        self.conn.execute(
            """
            insert into users (telegram_user_id, first_name, username, created_at, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(telegram_user_id) do update set
                first_name=excluded.first_name,
                username=excluded.username,
                updated_at=excluded.updated_at
            """,
            (
                user["id"],
                user.get("first_name"),
                user.get("username"),
                now,
                now,
            ),
        )
        self.conn.commit()

    def set_state(self, user_id: int, state: str | None, data: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "update users set state=?, state_data=?, updated_at=? where telegram_user_id=?",
            (state, json.dumps(data or {}), time(), user_id),
        )
        self.conn.commit()

    def get_state(self, user_id: int) -> tuple[str | None, dict[str, Any]]:
        row = self.conn.execute(
            "select state, state_data from users where telegram_user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None, {}
        return row["state"], json.loads(row["state_data"] or "{}")

    def add_channel(self, user_id: int, channel: dict[str, Any]) -> None:
        self.conn.execute(
            """
            insert or replace into channels
                (telegram_user_id, channel_id, channel_title, channel_username, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                str(channel["id"]),
                channel.get("title"),
                channel.get("username"),
                time(),
            ),
        )
        self.conn.commit()

    def list_channels(self, user_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "select * from channels where telegram_user_id=? order by created_at desc",
                (user_id,),
            )
        )

    def get_channel(self, channel_db_id: int, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "select * from channels where id=? and telegram_user_id=?",
            (channel_db_id, user_id),
        ).fetchone()

    def remove_channel(self, channel_db_id: int, user_id: int) -> bool:
        cur = self.conn.execute(
            "delete from channels where id=? and telegram_user_id=?",
            (channel_db_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def add_pending_post(self, user_id: int, product_url: str) -> int:
        cur = self.conn.execute(
            "insert into pending_posts (telegram_user_id, product_url, created_at) values (?, ?, ?)",
            (user_id, product_url, time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_pending_post(self, pending_id: int, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "select * from pending_posts where id=? and telegram_user_id=?",
            (pending_id, user_id),
        ).fetchone()

    def delete_pending_post(self, pending_id: int, user_id: int) -> None:
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
        self.conn.execute(
            """
            insert into posts
                (telegram_user_id, channel_id, product_url, affiliate_url, telegram_message_id, status, error, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, channel_id, product_url, affiliate_url, telegram_message_id, status, error, time()),
        )
        self.conn.commit()
