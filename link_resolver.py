"""Resolve, classify, and canonicalize marketplace links before extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from product_extractor import detect_platform


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "msclkid",
    "spm",
    "scm",
    "pvid",
    "gatewayadapt",
    "afsmartredirect",
    "forceinapp",
}
AFFILIATE_KEYS = {
    "tag",
    "ascsubtag",
    "linkcode",
    "linkid",
    "matt_tool",
    "matt_word",
    "matt_word",
    "matt_source",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "uls_trackid",
    "aff_fcid",
    "aff_fsk",
    "aff_platform",
    "aff_trace_key",
    "terminal_id",
    "sk",
}


@dataclass(frozen=True)
class ResolvedLink:
    original_url: str
    final_url: str
    canonical_url: str
    platform: str | None
    product_id: str | None
    already_affiliate: bool
    resolved: bool


def extract_first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>\"]+", text or "")
    if not match:
        return None
    return match.group(0).rstrip(").,;]")


async def resolve_product_link(url: str, timeout: float = 12) -> ResolvedLink:
    original = (url or "").strip()
    final = original
    resolved = False
    try:
        async with httpx.AsyncClient(
            timeout=min(max(timeout, 3), 20),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
            },
        ) as client:
            resp = await client.get(original)
            final = str(resp.url) or original
            resolved = final != original
    except Exception:
        final = original

    platform = detect_platform(final) or detect_platform(original)
    return ResolvedLink(
        original_url=original,
        final_url=final,
        canonical_url=canonicalize_url(final, platform),
        platform=platform,
        product_id=extract_product_id(final, platform) or extract_product_id(original, platform),
        already_affiliate=_has_affiliate_markers(original) or _has_affiliate_markers(final),
        resolved=resolved,
    )


def canonicalize_url(url: str, platform: str | None = None) -> str:
    parsed = urlparse(url)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") and platform != "shopee":
            continue
        if low in TRACKING_KEYS or any(low.startswith(prefix) for prefix in TRACKING_PREFIXES):
            if low not in AFFILIATE_KEYS:
                continue
        query.append((key, value))

    product_id = extract_product_id(url, platform)
    if platform == "amazon" and product_id:
        host = parsed.netloc or "www.amazon.com.br"
        suffix = f"/dp/{product_id}"
        return urlunparse((parsed.scheme or "https", host, suffix, "", urlencode(query), ""))
    if platform == "mercadolivre" and product_id and product_id.startswith("MLB"):
        return f"https://www.mercadolivre.com.br/p/{product_id}"
    if platform == "aliexpress" and product_id:
        return f"https://pt.aliexpress.com/item/{product_id}.html"
    if platform == "shopee":
        ids = _shopee_ids(url)
        if ids:
            shop_id, item_id = ids
            return f"https://shopee.com.br/product/{shop_id}/{item_id}"

    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", urlencode(query), ""))


def extract_product_id(url: str, platform: str | None = None) -> str | None:
    platform = platform or detect_platform(url)
    if platform == "amazon":
        match = re.search(r"(?:/dp/|/gp/product/|/gp/aw/d/)([A-Z0-9]{10}|\d{9}[X0-9])", url, re.I)
        return match.group(1).upper() if match else None
    if platform == "mercadolivre":
        match = re.search(r"\b(MLB\d{6,})\b|\bMLB-(\d{6,})\b", url, re.I)
        if not match:
            return None
        return (match.group(1) or f"MLB{match.group(2)}").upper()
    if platform == "aliexpress":
        match = re.search(r"/item/(\d+)\.html|productIds=(\d+)", url, re.I)
        return match.group(1) or match.group(2) if match else None
    if platform == "shopee":
        ids = _shopee_ids(url)
        return f"{ids[0]}:{ids[1]}" if ids else None
    if platform == "natura":
        match = re.search(r"/p/[^/?#]+/([A-Z0-9-]+)", url, re.I)
        return match.group(1).upper() if match else None
    return None


def _shopee_ids(url: str) -> tuple[str, str] | None:
    for pattern in (r"/product/(\d+)/(\d+)", r"-i\.(\d+)\.(\d+)", r"/(\d+)/(\d+)(?:[/?#]|$)"):
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return None


def _has_affiliate_markers(url: str) -> bool:
    parsed = urlparse(url or "")
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    host = parsed.netloc.lower()
    return bool(query_keys & AFFILIATE_KEYS) or host in {"meli.la", "amzn.to", "s.shopee.com.br", "s.click.aliexpress.com"}
