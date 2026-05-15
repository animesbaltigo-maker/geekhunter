"""Analytics queries for reports and user stats."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time
from time import time

from storage import Storage


class Analytics:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def get_daily_summary(self, day: date) -> dict:
        start = datetime.combine(day, dt_time.min).timestamp()
        end = datetime.combine(day, dt_time.max).timestamp()
        with self.storage._lock:
            posts = self.storage.conn.execute(
                "select count(*) as total from posts where status='posted' and created_at between ? and ?",
                (start, end),
            ).fetchone()["total"]
            errors = self.storage.conn.execute(
                "select count(*) as total from posts where status='error' and created_at between ? and ?",
                (start, end),
            ).fetchone()["total"]
            channel = self.storage.conn.execute(
                """
                select channel_id, count(*) as total from posts
                where status='posted' and created_at between ? and ?
                group by channel_id order by total desc limit 1
                """,
                (start, end),
            ).fetchone()
        return {
            "posts_count": int(posts),
            "errors": int(errors),
            "top_category": "",
            "most_active_channel": channel["channel_id"] if channel else None,
        }

    async def get_weekly_report(self) -> dict:
        cutoff = time() - 7 * 86400
        with self.storage._lock:
            total_posts = self.storage.conn.execute(
                "select count(*) as total from posts where status='posted' and created_at>=?",
                (cutoff,),
            ).fetchone()["total"]
            active_users = self.storage.conn.execute(
                "select count(distinct telegram_user_id) as total from posts where created_at>=?",
                (cutoff,),
            ).fetchone()["total"]
            active_channels = self.storage.conn.execute(
                "select count(distinct channel_id) as total from posts where created_at>=?",
                (cutoff,),
            ).fetchone()["total"]
            errors = self.storage.conn.execute(
                "select count(*) as total from posts where status='error' and created_at>=?",
                (cutoff,),
            ).fetchone()["total"]
            top = self.storage.conn.execute(
                """
                select product_url, count(*) as total from posts
                where status='posted' and created_at>=?
                group by product_url order by total desc limit 1
                """,
                (cutoff,),
            ).fetchone()
        peaks = await self.get_peak_hours(7)
        return {
            "total_posts": int(total_posts),
            "active_users": int(active_users),
            "active_channels": int(active_channels),
            "errors": int(errors),
            "peak_hour": peaks[0][0] if peaks else 0,
            "top_product": {"title": top["product_url"] if top else "sem dados", "discount": 0},
        }

    async def get_peak_hours(self, days: int = 30) -> list[tuple[int, int]]:
        cutoff = time() - days * 86400
        with self.storage._lock:
            rows = self.storage.conn.execute(
                "select created_at from posts where status='posted' and created_at>=?",
                (cutoff,),
            ).fetchall()
        counts: dict[int, int] = {}
        for row in rows:
            hour = datetime.fromtimestamp(float(row["created_at"])).hour
            counts[hour] = counts.get(hour, 0) + 1
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)

    async def get_top_categories(self, days: int = 7) -> list[tuple[str, int]]:
        return []

    async def get_user_stats(self, user_id: int) -> dict:
        stats = self.storage.user_post_stats(user_id)
        recent = self.storage.recent_posts(user_id, limit=1)
        stats["last_post_at"] = int(recent[0]["created_at"]) if recent else 0
        stats["active_channels"] = stats["channels"]
        return stats
