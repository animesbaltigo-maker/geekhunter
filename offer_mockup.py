"""Generate promotional offer mockups using the GeekHunter template."""

from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ai_generator import preparar_preco
from config import Settings

log = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1350
YELLOW = (255, 212, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
DARK = (15, 15, 16)
TEMPLATE_URL = "https://i.ibb.co/6R41sKyG/Chat-GPT-Image-13-de-mai-de-2026-21-16-28.png"


async def maybe_create_offer_mockup(produto: dict, settings: Settings) -> str | None:
    if not settings.offer_mockup_enabled:
        return None
    if not produto.get("imagem"):
        return None
    try:
        return await create_offer_mockup(produto, settings)
    except Exception as exc:
        log.warning("Falha ao gerar mockup da oferta; usando imagem original: %s", exc)
        return None


async def create_offer_mockup(produto: dict, settings: Settings, out_dir: str = "data/mockups") -> str:
    produto = preparar_preco(produto)
    image_url = str(produto.get("imagem") or "")
    bg_url = settings.offer_mockup_background_url or TEMPLATE_URL
    key = hashlib.sha1(
        f"{produto.get('id') or produto.get('link')}-{image_url}-{produto.get('preco_atual')}-{bg_url}-template-1080x1350-v9".encode()
    ).hexdigest()[:16]
    out_path = Path(out_dir) / f"{key}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        return str(out_path.resolve())

    async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True) as client:
        image_resp = await client.get(image_url)
        image_resp.raise_for_status()
    product_image = Image.open(BytesIO(image_resp.content)).convert("RGBA")
    template = await _load_background(settings)
    card = _render_card(produto, product_image, settings.offer_mockup_brand, background=template)
    card.save(out_path, "PNG", optimize=True)
    return str(out_path.resolve())


async def _load_background(settings: Settings) -> Image.Image | None:
    bg_url = settings.offer_mockup_background_url or TEMPLATE_URL
    cache_name = hashlib.sha1(bg_url.encode()).hexdigest()[:12]
    cache = Path("data/mockups") / f"template_{cache_name}.png"
    try:
        if cache.exists():
            return Image.open(cache).convert("RGB")
        async with httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=True) as client:
            resp = await client.get(bg_url)
            resp.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(resp.content)
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        log.warning("Nao consegui carregar fundo do mockup; usando fundo padrao: %s", exc)
        return None


def _render_card(
    produto: dict,
    product_image: Image.Image,
    brand: str,
    background: Image.Image | None = None,
) -> Image.Image:
    produto = preparar_preco(produto)
    canvas = _background_canvas(background).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")

    _paste_product(canvas, product_image)
    _draw_old_price_and_savings(draw, produto)
    _draw_main_price(draw, produto)
    _draw_discount(draw, produto)
    return canvas


def _background_canvas(background: Image.Image | None) -> Image.Image:
    if background is None:
        canvas = Image.new("RGB", (WIDTH, HEIGHT), DARK)
        draw = ImageDraw.Draw(canvas)
        draw.text((20, -10), "PROMO", fill=(255, 212, 0, 46), font=_font_impact(240))
        draw.rounded_rectangle((70, 180, 1010, 800), radius=42, fill=WHITE, outline=YELLOW, width=4)
        draw.rounded_rectangle((95, 770, 985, 875), radius=24, fill=(17, 17, 17), outline=(65, 65, 65), width=2)
        draw.rounded_rectangle((80, 910, 1020, 1090), radius=32, fill=YELLOW)
        draw.rounded_rectangle((60, 1120, 1020, 1225), radius=26, fill=(17, 17, 17), outline=(65, 65, 65), width=2)
        draw.rounded_rectangle((230, 1268, 850, 1328), radius=22, fill=(17, 17, 17), outline=YELLOW, width=2)
        return canvas

    bg = background.copy().convert("RGB")
    if bg.size == (WIDTH, HEIGHT):
        return bg
    return bg.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def _paste_product(canvas: Image.Image, image: Image.Image) -> None:
    # Safe area from the template: X 120, Y 230, W 840, H 520, with 40px padding.
    box = (150, 348, 930, 778)
    max_w = box[2] - box[0]
    max_h = box[3] - box[1]
    image = _trim_product_image(image.copy())
    image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    x = box[0] + (max_w - image.width) // 2
    y = box[1] + (max_h - image.height) // 2

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((x + 40, y + image.height - 18, x + image.width - 40, y + image.height + 34), fill=(0, 0, 0, 55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas.paste(shadow, (0, 0), shadow)
    canvas.paste(image, (x, y), image if image.mode == "RGBA" else None)


def _draw_old_price_and_savings(draw: ImageDraw.ImageDraw, produto: dict) -> None:
    old_price = float(produto.get("preco_original") or 0)
    current = float(produto.get("preco_atual") or 0)
    if old_price <= current or current <= 0:
        return

    label_font = _font_text(24, bold=True)
    old_font = _font_text(42)
    save_label_font = _font_text(22, bold=True)
    save_font = _fit_font(f"R$ {_money(old_price - current)}", 300, 40, 28, impact=False, bold=True)

    draw.text((165, 879), "DE", fill=WHITE, font=label_font)
    old_text = f"R$ {_money(old_price)}"
    draw.text((245, 866), old_text, fill=(213, 213, 213), font=old_font)
    old_bbox = draw.textbbox((0, 0), old_text, font=old_font)
    draw.line((245, 897, 245 + old_bbox[2] - old_bbox[0], 897), fill=YELLOW, width=4)

    draw.text((680, 846), "ECONOMIZE", fill=WHITE, font=save_label_font)
    draw.text((680, 880), f"R$ {_money(old_price - current)}", fill=YELLOW, font=save_font)


def _draw_main_price(draw: ImageDraw.ImageDraw, produto: dict) -> None:
    label_font = _font_text(26, bold=True)
    price_text = f"R$ {_money(float(produto.get('preco_atual') or 0))}"
    price_font = _fit_font(price_text, 650, 100, 68, impact=True, bold=True)

    label_box = (120, 945, 360, 993)
    draw.rounded_rectangle(label_box, radius=14, fill=(17, 17, 17))
    draw.text((142, 954), "POR APENAS", fill=WHITE, font=label_font)
    draw.text((120, 978), price_text, fill=BLACK, font=price_font)


def _draw_discount(draw: ImageDraw.ImageDraw, produto: dict) -> None:
    discount = int(float(produto.get("desconto_pct") or 0))
    if discount <= 0:
        return

    pct_font = _font_impact(38)
    off_font = _font_text(20, bold=True)
    center_x = 890
    group_top = 1005
    pct = f"{discount}%"
    pct_bbox = draw.textbbox((0, 0), pct, font=pct_font)
    off_bbox = draw.textbbox((0, 0), "OFF", font=off_font)
    pct_w = pct_bbox[2] - pct_bbox[0]
    off_w = off_bbox[2] - off_bbox[0]
    draw.text((center_x - pct_w // 2 - pct_bbox[0], group_top - pct_bbox[1]), pct, fill=YELLOW, font=pct_font)
    draw.text((center_x - off_w // 2 - off_bbox[0], group_top + 46 - off_bbox[1]), "OFF", fill=WHITE, font=off_font)


def _trim_product_image(image: Image.Image) -> Image.Image:
    """Crop transparent or near-white margins common in marketplace product photos."""
    image = image.convert("RGBA")
    alpha_bbox = image.getbbox()
    if alpha_bbox:
        image = image.crop(alpha_bbox)

    rgb = image.convert("RGB")
    pix = rgb.load()
    width, height = rgb.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            r, g, b = pix[x, y]
            if not (r >= 245 and g >= 245 and b >= 245):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        return image

    crop_w = max_x - min_x + 1
    crop_h = max_y - min_y + 1
    original_area = width * height
    crop_area = crop_w * crop_h
    if crop_area < original_area * 0.08:
        return image

    pad_x = max(8, int(crop_w * 0.04))
    pad_y = max(8, int(crop_h * 0.04))
    box = (
        max(0, min_x - pad_x),
        max(0, min_y - pad_y),
        min(width, max_x + pad_x + 1),
        min(height, max_y + pad_y + 1),
    )
    return image.crop(box)


def _fit_font(text: str, max_width: int, start: int, minimum: int, *, impact: bool, bold: bool = False) -> ImageFont.ImageFont:
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(start, minimum - 1, -2):
        font = _font_impact(size) if impact else _font_text(size, bold=bold)
        if probe.textlength(text, font=font) <= max_width:
            return font
    return _font_impact(minimum) if impact else _font_text(minimum, bold=bold)


def _money(value: float) -> str:
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _font_impact(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/ANTON.TTF",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    return _load_font(candidates, size)


def _font_text(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/Montserrat-ExtraBold.ttf" if bold else "C:/Windows/Fonts/Montserrat-Medium.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    return _load_font(candidates, size)


def _load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()
