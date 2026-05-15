"""Small in-memory rate limiter for user actions."""

from __future__ import annotations

from collections import defaultdict, deque
from time import time


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, int], deque[float]] = defaultdict(deque)

    def allow(self, scope: str, user_id: int, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time()
        key = (scope, user_id)
        events = self._events[key]
        cutoff = now - window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= limit:
            remaining = max(1, int(window_seconds - (now - events[0])))
            return False, remaining
        events.append(now)
        return True, 0
