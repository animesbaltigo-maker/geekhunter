"""Generate polished Telegram offer captions."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from config import Settings

MAX_TITLE_LEN = 135

PLATFORM_TAGS = {
    "mercadolivre": "#MercadoLivre",
    "meli.la": "#MercadoLivre",
    "amazon": "#Amazon",
    "amzn": "#Amazon",
    "shopee": "#Shopee",
    "shein": "#Shein",
    "aliexpress": "#AliExpress",
    "magazineluiza": "#Magalu",
    "magalu": "#Magalu",
    "natura": "#Natura",
}

CATEGORY_RULES = [
    (("creatina", "whey", "suplement", "vitamina", "protein"), "#Suplementos"),
    (("tênis", "tenis", "adidas", "puma", "nike", "camiseta", "meia", "jaqueta", "calça", "bolsa", "sandália"), "#Moda"),
    (("fone", "bluetooth", "caixa de som", "carregador", "iphone", "headset", "anker", "soundcore"), "#Eletrônicos"),
    (("xiaomi", "smartphone", "celular", "motorola", "samsung", "iphone"), "#Celulares"),
    (("notebook", "ssd", "monitor", "teclado", "mouse", "gamer", "tablet"), "#Tecnologia"),
    (("air fryer", "chaleira", "potes", "cozinha", "panela", "cafeteira", "liquidificador"), "#Casa"),
    (("mangueira", "varal", "colchão", "travesseiro", "lençol", "organizador"), "#Casa"),
    (("ferramenta", "chaves", "compressor", "furadeira", "parafusadeira", "alicate"), "#Ferramentas"),
    (("relógio", "relogio", "perfume", "maquiagem", "natura", "creme", "skincare"), "#Beleza"),
    (("funko", "boneco", "brinquedo", "lego", "pop", "k-pop", "kpop", "colecion"), "#Colecionáveis"),
    (("livro", "mangá", "manga", "hq", "box"), "#Livros"),
    (("pet", "ração", "gato", "cachorro"), "#PetShop"),
]


async def gerar_post(produto: dict, settings: Settings) -> str:
    return gerar_post_fallback(produto)


def preparar_preco(produto: dict) -> dict:
    produto = dict(produto)
    current = _to_float(produto.get("preco_atual"))
    original = _to_float(produto.get("preco_original"))
    discount = int(_to_float(produto.get("desconto_pct")) or 0)

    has_real_original = current > 0 and original > current

    if current > 0 and has_real_original:
        if discount <= 0:
            discount = max(1, round((1 - current / original) * 100))
        produto["desconto_estimado"] = False
    elif current > 0:
        original = current
        discount = 0
        produto["desconto_estimado"] = False
    else:
        produto["desconto_estimado"] = False

    produto["preco_atual"] = current
    produto["preco_original"] = original or current
    produto["desconto_pct"] = discount
    return produto


def gerar_post_fallback(produto: dict) -> str:
    produto = preparar_preco(produto)
    titulo = _titulo_post(produto.get("titulo") or "Oferta selecionada")
    link = produto.get("link") or produto.get("link_original") or ""
    hashtags = _hashtags(produto)

    if not (produto["desconto_pct"] > 0 and produto["preco_original"] > produto["preco_atual"]):
        linhas = [
            f"🔥 <b>{html.escape(titulo)}</b>",
            "",
            f"💰 <b>Preço encontrado: R$ {_money(produto['preco_atual'])}</b>",
        ]
        if produto["preco_atual"] <= 0:
            linhas = [linhas[0], "", "🛒 <b>Confira o valor atualizado no link</b>"]
        if produto.get("frete_gratis"):
            linhas.append("🚚 <b>Frete grátis</b>")
        social = _social_line(produto)
        if social:
            linhas.extend(["", f"<blockquote>{social}</blockquote>"])
        linhas.extend(["", f"👉 {html.escape(link)}", "", hashtags])
        return "\n".join(linhas)

    linhas = [
        f"🔥 <b>{html.escape(titulo)}</b>",
        "",
        f"❌ De <s>R$ {_money(produto['preco_original'])}</s>",
        f"✅ Por <b>R$ {_money(produto['preco_atual'])}</b> <b>({produto['desconto_pct']}% OFF)</b>",
    ]
    if produto.get("frete_gratis"):
        linhas.append("🚚 <b>Frete grátis</b>")

    social = _social_line(produto)
    if social:
        linhas.extend(["", f"<blockquote>{social}</blockquote>"])

    linhas.extend(["", f"👉 {html.escape(link)}", "", hashtags])
    return "\n".join(linhas)


def _titulo_post(titulo: str) -> str:
    titulo = re.sub(r"\s+", " ", html.unescape(str(titulo))).strip()
    titulo = _remove_noise(titulo)
    if len(titulo) <= MAX_TITLE_LEN:
        return titulo
    words: list[str] = []
    for word in titulo.split():
        candidate = " ".join(words + [word])
        if len(candidate) > MAX_TITLE_LEN:
            break
        words.append(word)
    short = " ".join(words).rstrip(" -,.;:")
    return short or titulo[:MAX_TITLE_LEN].rstrip(" -,.;:")


def _remove_noise(titulo: str) -> str:
    cleaned = titulo
    replacements = [
        r"\s+no Mercado Livre.*$",
        r"\s+\|\s+.*$",
        r"\s+-\s+Mercado Livre.*$",
        r"\b127/220v\b",
        r"\b127v\b",
        r"\b220v\b",
    ]
    for pattern in replacements:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I).strip(" -,.|/")
    return cleaned or titulo


def _money(value: float) -> str:
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _social_line(produto: dict) -> str:
    parts: list[str] = []
    rating = _to_float(produto.get("avaliacao"))
    sold = _normalize_sold(produto.get("vendidos"))
    if rating:
        parts.append(f"⭐ {rating:.1f} de avaliação")
    if sold:
        parts.append(sold)
    return html.escape(" + ".join(parts))


def _normalize_sold(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("++", "+")
    text = re.sub(r"^\+\s*", "", text)
    if "vendido" not in text.lower():
        text = f"{text} vendidos"
    return text


def _platform_tag(produto: dict) -> str:
    platform = str(produto.get("platform") or "").lower()
    link = str(produto.get("link") or produto.get("link_original") or produto.get("source_url") or "")
    host = urlparse(link).netloc.lower()
    haystack = f"{platform} {host}"
    for needle, tag in PLATFORM_TAGS.items():
        if needle in haystack:
            return tag
    return "#Achadinhos"


def _hashtags(produto: dict) -> str:
    title = (produto.get("titulo") or "").lower()
    tags = ["#Oferta", _platform_tag(produto)]
    for needles, tag in CATEGORY_RULES:
        if any(needle in title for needle in needles):
            tags.append(tag)
            break
    if _has_real_discount(produto):
        tags.append("#Promoção")
    else:
        tags.append("#Achadinho")
    if produto.get("frete_gratis"):
        tags.append("#FreteGrátis")
    return " ".join(dict.fromkeys(tags[:5]))


def _has_real_discount(produto: dict) -> bool:
    current = _to_float(produto.get("preco_atual"))
    original = _to_float(produto.get("preco_original"))
    discount = int(_to_float(produto.get("desconto_pct")) or 0)
    return current > 0 and original > current and discount > 0


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0
