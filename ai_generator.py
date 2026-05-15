"""Generate polished Telegram offer captions."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from urllib.parse import urlparse

import httpx

from config import Settings

MAX_TITLE_LEN = 135
MAX_CAPTION_LEN = 1000
AI_TIMEOUT_SECONDS = 15.0
AI_RETRIES = 2

log = logging.getLogger(__name__)

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

COPY_TEMPLATES = [
    "tom de urgencia, com chamada direta para aproveitar agora",
    "tom de escassez, destacando que a oferta pode mudar rapido",
    "prova social, usando avaliacao e vendidos quando existirem",
    "desconto limpo, focando no preco e economia sem exagero",
    "tom vendedor, curto e forte para canal de ofertas",
    "tom premium, valorizando beneficios do produto",
    "tom achadinho, casual e objetivo",
]


async def gerar_post(produto: dict, settings: Settings) -> str:
    provider = (settings.ai_provider or "fallback").strip().lower()
    if provider == "fallback":
        return gerar_post_fallback(produto, use_emojis=settings.post_emojis)

    try:
        if provider == "groq" and settings.groq_api_key:
            text = await _gerar_openai_compat(
                produto,
                settings,
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                default_model="llama-3.3-70b-versatile",
                provider_name="groq",
            )
        elif provider == "openai" and settings.openai_api_key:
            text = await _gerar_openai_compat(
                produto,
                settings,
                api_key=settings.openai_api_key,
                base_url="https://api.openai.com/v1",
                default_model="gpt-4o-mini",
                provider_name="openai",
            )
        elif provider == "anthropic" and settings.anthropic_api_key:
            text = await _gerar_anthropic(produto, settings)
        else:
            log.info("AI provider %s sem credencial configurada; usando fallback local.", provider)
            return gerar_post_fallback(produto, use_emojis=settings.post_emojis)

        cleaned = _sanitize_ai_caption(text, produto)
        log.info("Copy gerada com AI provider=%s.", provider)
        return cleaned
    except Exception as exc:
        log.warning("Falha ao gerar copy com AI provider=%s; usando fallback local: %s", provider, exc)
        return gerar_post_fallback(produto, use_emojis=settings.post_emojis)


async def _gerar_openai_compat(
    produto: dict,
    settings: Settings,
    *,
    api_key: str,
    base_url: str,
    default_model: str,
    provider_name: str,
) -> str:
    payload = {
        "model": settings.ai_model or default_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(produto)},
        ],
        "temperature": 0.8,
        "max_tokens": 420,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
        data = await _post_json_with_retry(
            client,
            f"{base_url.rstrip('/')}/chat/completions",
            payload,
            headers,
            provider_name,
        )
    return str(data["choices"][0]["message"]["content"]).strip()


async def _gerar_anthropic(produto: dict, settings: Settings) -> str:
    payload = {
        "model": settings.ai_model or "claude-3-5-haiku-latest",
        "max_tokens": 420,
        "temperature": 0.8,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": _user_prompt(produto)}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key or "",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
        data = await _post_json_with_retry(
            client,
            "https://api.anthropic.com/v1/messages",
            payload,
            headers,
            "anthropic",
        )
    parts = data.get("content") or []
    return "\n".join(str(part.get("text", "")) for part in parts if part.get("type") == "text").strip()


async def _post_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    headers: dict[str, str],
    provider_name: str,
) -> dict:
    last_exc: Exception | None = None
    for attempt in range(AI_RETRIES):
        try:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in {408, 429} or resp.status_code >= 500:
                if attempt < AI_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                    continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt < AI_RETRIES - 1:
                await asyncio.sleep(2**attempt)
                continue
            raise
    raise RuntimeError(f"{provider_name} nao retornou resposta valida") from last_exc


def _system_prompt() -> str:
    return (
        "Voce cria captions curtas para Telegram em portugues do Brasil. "
        "Use apenas HTML aceito pelo Telegram: <b>, <i>, <s>, <code>, <blockquote>. "
        "Nao use Markdown. Nao invente preco, desconto, frete, avaliacao ou vendidos. "
        "Nao inclua URL ou link na caption; o bot adiciona um botao separado. "
        "Responda com uma frase curta de venda, sem repetir todos os dados."
    )


def _user_prompt(produto: dict) -> str:
    produto = preparar_preco(produto)
    template = COPY_TEMPLATES[_template_index(produto)]
    fields = {
        "estilo": template,
        "titulo": produto.get("titulo") or "",
        "preco_atual": _money(produto.get("preco_atual") or 0),
        "preco_original": _money(produto.get("preco_original") or 0),
        "desconto_pct": int(produto.get("desconto_pct") or 0),
        "frete_gratis": bool(produto.get("frete_gratis")),
        "avaliacao": produto.get("avaliacao") or "",
        "vendidos": produto.get("vendidos") or "",
        "link": produto.get("link") or produto.get("link_original") or "",
    }
    return (
        "Crie uma caption de oferta com este estilo: {estilo}.\n"
        "Dados do produto:\n"
        "- titulo: {titulo}\n"
        "- preco atual: R$ {preco_atual}\n"
        "- preco original: R$ {preco_original}\n"
        "- desconto: {desconto_pct}%\n"
        "- frete gratis: {frete_gratis}\n"
        "- avaliacao: {avaliacao}\n"
        "- vendidos: {vendidos}\n"
        "- link para botao, nao incluir no texto: {link}\n"
        "Responda somente com uma frase curta em HTML para Telegram, sem URL."
    ).format(**fields)


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
        if str(produto.get("platform") or "").lower() != "shopee":
            discount = 0
        produto["desconto_estimado"] = False
    else:
        produto["desconto_estimado"] = False

    produto["preco_atual"] = current
    produto["preco_original"] = original or current
    produto["desconto_pct"] = discount
    return produto


def gerar_post_fallback(produto: dict, use_emojis: bool = False) -> str:
    return _format_offer_caption(produto, use_emojis=use_emojis)
    produto = preparar_preco(produto)
    titulo = _titulo_post(produto.get("titulo") or "Oferta selecionada")
    link = produto.get("link") or produto.get("link_original") or ""
    hashtags = _hashtags(produto)
    icon_fire = "🔥 " if use_emojis else ""
    icon_money = "💰 " if use_emojis else ""
    icon_cart = "🛒 " if use_emojis else ""
    icon_tag = "🏷️ " if use_emojis else ""
    icon_truck = "🚚 " if use_emojis else ""
    icon_point = "👉 " if use_emojis else ""
    icon_no = "❌ " if use_emojis else ""
    icon_yes = "✅ " if use_emojis else ""
    is_shopee = str(produto.get("platform") or "").lower() == "shopee"

    if not (produto["desconto_pct"] > 0 and produto["preco_original"] > produto["preco_atual"]):
        linhas = [
            f"{icon_fire}<b>{html.escape(titulo)}</b>",
            "",
            f"{icon_money}<b>Preço encontrado: R$ {_money(produto['preco_atual'])}</b>",
        ]
        if produto["preco_atual"] <= 0:
            linhas = [linhas[0], "", f"{icon_cart}<b>Confira o valor atualizado no link</b>"]
        if produto["preco_atual"] > 0 and produto["desconto_pct"] > 0 and not is_shopee:
            linhas.append(f"{icon_tag}<b>{produto['desconto_pct']}% OFF no painel</b>")
        if produto.get("frete_gratis"):
            linhas.append(f"{icon_truck}<b>Frete grátis</b>")
        social = _social_line(produto)
        if social:
            linhas.extend(["", f"<blockquote>{social}</blockquote>"])
        linhas.extend(["", f"{icon_point}{html.escape(link)}", "", hashtags])
        return "\n".join(linhas)

    linhas = [
        f"{icon_fire}<b>{html.escape(titulo)}</b>",
        "",
        f"{icon_no}De <s>R$ {_money(produto['preco_original'])}</s>",
        f"{icon_yes}Por <b>R$ {_money(produto['preco_atual'])}</b> <b>({produto['desconto_pct']}% OFF)</b>",
    ]
    if produto.get("frete_gratis"):
        linhas.append(f"{icon_truck}<b>Frete grátis</b>")

    social = _social_line(produto)
    if social:
        linhas.extend(["", f"<blockquote>{social}</blockquote>"])

    linhas.extend(["", f"{icon_point}{html.escape(link)}", "", hashtags])
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
    if not re.search(r"\bvend(?:a|as|ido|idos|ida|idas)\b", text.lower()):
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


def _template_index(produto: dict) -> int:
    key = str(produto.get("id") or produto.get("product_id") or produto.get("link") or produto.get("titulo") or "")
    return sum(ord(char) for char in key) % len(COPY_TEMPLATES)


def _format_offer_caption(produto: dict, callout: str | None = None, use_emojis: bool = True) -> str:
    produto = preparar_preco(produto)
    titulo = _titulo_post(produto.get("titulo") or "Oferta selecionada")
    hashtags = _hashtags(produto)
    icon_fire = "🔥 " if use_emojis else ""
    icon_money = "💰 " if use_emojis else ""
    icon_cart = "🛒 " if use_emojis else ""
    icon_tag = "🏷️ " if use_emojis else ""
    icon_truck = "🚚 " if use_emojis else ""
    icon_no = "❌ " if use_emojis else ""
    icon_yes = "✅ " if use_emojis else ""

    lines = [f"{icon_fire}<b>{html.escape(titulo)}</b>", ""]
    if callout:
        lines.extend([f"<i>{html.escape(callout)}</i>", ""])

    has_discount = produto["desconto_pct"] > 0 and produto["preco_original"] > produto["preco_atual"]
    if has_discount:
        lines.append(f"{icon_no}De <s>R$ {_money(produto['preco_original'])}</s>")
        lines.append(f"{icon_yes}Por <b>R$ {_money(produto['preco_atual'])}</b> <b>({produto['desconto_pct']}% OFF)</b>")
    elif produto["preco_atual"] > 0:
        lines.append(f"{icon_money}<b>Preço encontrado: R$ {_money(produto['preco_atual'])}</b>")
        if produto["desconto_pct"] > 0 and str(produto.get("platform") or "").lower() != "shopee":
            lines.append(f"{icon_tag}<b>{produto['desconto_pct']}% OFF no painel</b>")
    else:
        lines.append(f"{icon_cart}<b>Confira o valor atualizado no botão abaixo</b>")

    if produto.get("frete_gratis"):
        lines.append(f"{icon_truck}<b>Frete grátis</b>")

    if produto.get("historical_low"):
        lines.append("🏆 <b>Menor preço registrado para este produto</b>")

    social = _social_line(produto)
    if social:
        lines.extend(["", f"<blockquote>{social}</blockquote>"])

    lines.extend(["", hashtags])
    return _limit_caption("\n".join(lines))


def _sanitize_ai_caption(text: str, produto: dict) -> str:
    text = _strip_unsupported_html(text or "").strip()
    if not text:
        raise ValueError("AI retornou caption vazia")
    if re.search(r"https?://|www\.|&lt;a\b|<a\b", text, flags=re.I):
        return _format_offer_caption(produto)
    callout = _plain_text(text)
    callout = re.sub(r"\s+", " ", callout).strip(" -–—\"'")
    if len(callout) > 120:
        callout = ""
    return _format_offer_caption(produto, callout=callout or None)


def _plain_text(text: str) -> str:
    text = re.sub(r"</?(?:b|i|s|code|blockquote)>", "", text, flags=re.I)
    return html.unescape(text)


def _strip_unsupported_html(text: str) -> str:
    allowed = {"b", "i", "s", "code", "blockquote"}

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        tag = match.group(1).lower()
        has_attrs = bool(match.group(2))
        if tag in allowed and not has_attrs:
            return raw.lower()
        return html.escape(raw)

    return re.sub(r"</?\s*([a-zA-Z0-9]+)(\s+[^>]*)?\s*>", repl, text)


def _limit_caption(text: str, max_len: int = MAX_CAPTION_LEN) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1].rstrip()
    last_break = cut.rfind("\n")
    if last_break > max_len * 0.6:
        cut = cut[:last_break].rstrip()
    return cut


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
