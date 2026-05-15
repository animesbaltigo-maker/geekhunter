"""Confidence scoring for extracted marketplace products."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


MIN_CONFIDENCE_TO_POST = 75


@dataclass(frozen=True)
class ProductConfidence:
    score: int
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.score >= MIN_CONFIDENCE_TO_POST and not any(issue.startswith("critical:") for issue in self.issues)


GENERIC_TITLES = {
    "oferta selecionada",
    "produto selecionado",
    "produto",
    "shopee brasil",
    "amazon.com.br",
    "magazine luiza",
    "roupas femininas & masculinas, loja de moda online",
}


def evaluate_product_confidence(produto: dict, *, input_url: str | None = None) -> ProductConfidence:
    score = 0
    issues: list[str] = []
    title = str(produto.get("titulo") or "").strip()
    image = str(produto.get("imagem") or "").strip()
    platform = str(produto.get("platform") or "").strip().lower()
    source_url = str(produto.get("source_url") or produto.get("link") or "")
    price = _as_float(produto.get("preco_atual"))
    original = _as_float(produto.get("preco_original"))

    if title and title.lower() not in GENERIC_TITLES and len(title) >= 10:
        score += 30
    else:
        issues.append("critical:title_missing_or_generic")

    if image and not _looks_like_placeholder_image(image):
        score += 25
    else:
        issues.append("critical:image_missing_or_placeholder")

    if price > 0:
        score += 25
    else:
        issues.append("critical:price_missing")

    if platform:
        score += 5
    else:
        issues.append("platform_missing")

    if produto.get("extraction_verified"):
        score += 8

    if original > price > 0:
        score += 4

    if _platform_blocked_page(platform, source_url):
        issues.append(f"critical:{platform}_blocked_page")

    if input_url and platform and _host_mismatch(input_url, source_url, platform):
        issues.append("source_host_mismatch")
        score -= 10

    return ProductConfidence(score=max(0, min(100, score)), issues=tuple(issues))


def require_confident_product(produto: dict, *, input_url: str | None = None) -> dict:
    confidence = evaluate_product_confidence(produto, input_url=input_url)
    produto["confidence_score"] = confidence.score
    produto["confidence_issues"] = list(confidence.issues)
    if not confidence.ok:
        pretty = ", ".join(issue.replace("critical:", "") for issue in confidence.issues) or "dados insuficientes"
        raise ValueError(f"Extracao sem confianca suficiente ({confidence.score}/100): {pretty}")
    return produto


def _looks_like_placeholder_image(url: str) -> bool:
    lowered = (url or "").lower()
    return any(
        bit in lowered
        for bit in (
            "logo",
            "placeholder",
            "sprite",
            "icon",
            "favicon",
            "shopee-logo",
            "shopee-pcmall",
            "shopee-mobilemall",
            "assets/",
            "error-robot",
            "shared/magalu/error",
        )
    )


def _platform_blocked_page(platform: str, source_url: str) -> bool:
    lowered = (source_url or "").lower()
    return (
        (platform == "shein" and "/risk/challenge" in lowered)
        or (platform == "magalu" and "nao-e-possivel-acessar" in lowered)
        or (platform == "magalu" and "não-é-possível-acessar" in lowered)
        or (platform == "amazon" and "opfcaptcha" in lowered)
    )


def _host_mismatch(input_url: str, source_url: str, platform: str) -> bool:
    input_host = urlparse(input_url).netloc.lower()
    source_host = urlparse(source_url).netloc.lower()
    if not input_host or not source_host:
        return False
    expected = {
        "amazon": ("amazon.", "amzn.to"),
        "mercadolivre": ("mercadolivre.", "meli.la"),
        "shopee": ("shopee.", "s.shopee"),
        "shein": ("shein.",),
        "aliexpress": ("aliexpress.", "s.click.aliexpress"),
        "magalu": ("magazineluiza.", "magalu."),
        "natura": ("natura.",),
    }.get(platform, ())
    return not any(hint in source_host for hint in expected) and not any(hint in input_host for hint in expected)


def _as_float(value: object) -> float:
    try:
        if not isinstance(value, str):
            return float(value or 0)
        cleaned = value.strip().replace("R$", "").replace(" ", "")
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned or 0)
    except (TypeError, ValueError):
        return 0.0
