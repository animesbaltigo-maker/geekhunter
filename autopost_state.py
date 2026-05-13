"""Small JSON state for autopost rotation."""

from __future__ import annotations

import json
from pathlib import Path
from time import time
from typing import Any


class AutopostState:
    def __init__(self, path: str = "data/autopost_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty()

    def _empty(self) -> dict[str, Any]:
        return {
            "term_index": 0,
            "current_niche": "",
            "current_niche_posts": 0,
            "current_niche_target": 3,
            "last_posted_ids": [],
            "last_niches": [],
        }

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def next_terms(self, terms: list[str], count: int = 2) -> list[str]:
        if not terms:
            return []
        index = int(self.data.get("term_index") or 0) % len(terms)
        selected = [terms[(index + i) % len(terms)] for i in range(min(count, len(terms)))]
        self.data["term_index"] = (index + 1) % len(terms)
        self.data["updated_at"] = time()
        self.save()
        return selected

    def active_niche(self, terms: list[str], min_posts: int = 3, max_posts: int = 5) -> str | None:
        if not terms:
            return None
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return None

        index = int(self.data.get("term_index") or 0) % len(normalized_terms)
        current = str(self.data.get("current_niche") or "").strip()
        if current not in normalized_terms:
            current = normalized_terms[index]
            self.data["current_niche"] = current
            self.data["current_niche_posts"] = 0
            self.data["current_niche_target"] = self._target_for_niche(current, min_posts, max_posts)
            self.data["updated_at"] = time()
            self.save()
        return current

    def remember_niche_post(self, terms: list[str], min_posts: int = 3, max_posts: int = 5) -> str | None:
        if not terms:
            return None
        normalized_terms = [term.strip() for term in terms if term.strip()]
        if not normalized_terms:
            return None

        current = self.active_niche(normalized_terms, min_posts, max_posts)
        posts = int(self.data.get("current_niche_posts") or 0) + 1
        target = int(self.data.get("current_niche_target") or min_posts)
        if posts >= target:
            old = current or ""
            index = (normalized_terms.index(old) + 1) % len(normalized_terms) if old in normalized_terms else 0
            new_niche = normalized_terms[index]
            self.data["term_index"] = index
            self.data["current_niche"] = new_niche
            self.data["current_niche_posts"] = 0
            self.data["current_niche_target"] = self._target_for_niche(new_niche, min_posts, max_posts)
            self.data["last_niches"] = ([old] + [n for n in self.data.get("last_niches", []) if n != old])[:20]
            self.data["updated_at"] = time()
            self.save()
            return new_niche

        self.data["current_niche_posts"] = posts
        self.data["updated_at"] = time()
        self.save()
        return current

    def remember_product(self, product_id: str | None) -> None:
        if not product_id:
            return
        ids = [str(product_id)] + [item for item in self.data.get("last_posted_ids", []) if item != str(product_id)]
        self.data["last_posted_ids"] = ids[:80]
        self.data["updated_at"] = time()
        self.save()

    def recently_posted(self, product_id: str | None) -> bool:
        return bool(product_id and str(product_id) in set(self.data.get("last_posted_ids", [])))

    def _target_for_niche(self, niche: str, min_posts: int, max_posts: int) -> int:
        min_posts = max(1, int(min_posts or 1))
        max_posts = max(min_posts, int(max_posts or min_posts))
        span = max_posts - min_posts + 1
        return min_posts + (sum(ord(char) for char in niche) % span)
