"""Central configuration for the ML affiliate bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

DEFAULT_SEARCH_TERMS = [
    "ofertas do dia",
    "smartphone",
    "iphone",
    "xiaomi",
    "samsung",
    "fone bluetooth",
    "headset gamer",
    "caixa de som bluetooth",
    "smartwatch",
    "carregador iphone",
    "carregador usb c",
    "power bank",
    "notebook",
    "monitor gamer",
    "teclado mecanico",
    "mouse gamer",
    "ssd",
    "tablet",
    "impressora",
    "air fryer",
    "cafeteira",
    "liquidificador",
    "panela eletrica",
    "chaleira eletrica",
    "cozinha",
    "casa",
    "organizadores",
    "cama mesa banho",
    "travesseiro",
    "colchao",
    "ferramentas",
    "furadeira",
    "parafusadeira",
    "kit ferramentas",
    "tenis masculino",
    "tenis feminino",
    "tenis adidas",
    "tenis nike",
    "camiseta",
    "jaqueta",
    "bolsa feminina",
    "relogio",
    "perfume",
    "maquiagem",
    "skincare",
    "creatina",
    "whey protein",
    "suplementos",
    "vitaminas",
    "brinquedos",
    "lego",
    "funko pop",
    "pet shop",
    "racao",
    "livros",
    "manga",
    "games",
    "controle ps5",
    "cadeira gamer",
    "bebes",
    "fralda",
    "material escolar",
    "mochila",
    "auto pecas",
    "acessorios carro",
    "bicicleta",
    "camping",
    "jardim",
    "piscina",
]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    ml_app_id: str | None = None
    ml_secret_key: str | None = None
    ml_redirect_uri: str | None = None
    ml_access_token: str | None = None
    ml_refresh_token: str | None = None
    ml_user_id: str | None = None
    ml_affiliate_label_id: str | None = None
    ml_affiliate_matt_tool: str = "93444346"
    affiliate_link_mode: str = "template"
    affiliate_url_template: str | None = None
    search_terms: list[str] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    min_discount_pct: int = 10
    min_sold_quantity: int = 0
    min_rating: float = 0
    blocked_words: list[str] = field(default_factory=list)
    max_price: float | None = None
    posts_per_round: int = 3
    niche_rotate_min_posts: int = 3
    niche_rotate_max_posts: int = 5
    round_interval_minutes: int = 60
    dry_run: bool = True
    use_sample_data: bool = False
    product_source: str = "panel"
    panel_cdp_url: str = "http://127.0.0.1:9222"
    shopee_panel_url: str = "https://affiliate.shopee.com.br/offer/product_offer"
    shopee_panel_cdp_url: str = "http://127.0.0.1:9222"
    shopee_affiliate_app_id: str | None = None
    shopee_affiliate_secret: str | None = None
    shopee_affiliate_api_url: str = "https://open-api.affiliate.shopee.com.br/graphql"
    shopee_affiliate_enabled: bool = False
    browser_profile_dir: str = "browser_profile/ml_affiliate"
    browser_headless: bool = False
    promotion_types: list[str] = field(default_factory=list)
    history_path: str = "data/posted_items.json"
    request_timeout: float = 20
    multiuser_browser_fallback: bool = True
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    ai_provider: str = "fallback"
    ai_model: str | None = None
    post_emojis: bool = True
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None
    admin_telegram_id: int | None = None
    owner_telegram_id: int | None = None
    health_port: int = 8080
    user_post_cooldown_seconds: int = 60
    user_posts_per_hour: int = 20
    max_channels_free: int = 3
    free_max_channels: int = 1
    free_posts_per_day: int = 20
    pro_max_channels: int = 0
    pro_posts_per_day: int = 0
    token_auto_refresh: bool = True
    price_history_enabled: bool = True
    price_alert_check_interval: int = 30
    max_alerts_free: int = 5
    max_alerts_pro: int = 20
    daily_summary_enabled: bool = True
    daily_summary_hour: int = 23
    weekly_niche_schedule: str = ""
    curation_mode: bool = False
    silent_hours: str = ""
    blacklist_terms: list[str] = field(default_factory=list)
    outgoing_webhook_url: str | None = None
    outgoing_webhook_secret: str | None = None
    rss_enabled: bool = False
    rss_port: int = 8081
    weekly_report_enabled: bool = True
    offer_mockup_enabled: bool = False
    offer_mockup_brand: str = "@GeekHunter_Br"
    offer_mockup_background_url: str | None = "https://i.ibb.co/6R41sKyG/Chat-GPT-Image-13-de-mai-de-2026-21-16-28.png"

    @property
    def can_post_to_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_channel_id)


def load_settings() -> Settings:
    load_dotenv()
    settings = Settings(
        ml_app_id=os.getenv("ML_APP_ID") or None,
        ml_secret_key=os.getenv("ML_SECRET_KEY") or None,
        ml_redirect_uri=os.getenv("ML_REDIRECT_URI") or None,
        ml_access_token=os.getenv("ML_ACCESS_TOKEN") or None,
        ml_refresh_token=os.getenv("ML_REFRESH_TOKEN") or None,
        ml_user_id=os.getenv("ML_USER_ID") or None,
        ml_affiliate_label_id=os.getenv("ML_AFFILIATE_LABEL_ID") or os.getenv("ML_AFFILIATE_ID") or None,
        ml_affiliate_matt_tool=os.getenv("ML_AFFILIATE_MATT_TOOL", "93444346"),
        affiliate_link_mode=os.getenv("AFFILIATE_LINK_MODE", "template").strip().lower(),
        affiliate_url_template=os.getenv("AFFILIATE_URL_TEMPLATE") or None,
        search_terms=_split_csv(os.getenv("SEARCH_TERMS")),
        category_ids=_split_csv(os.getenv("CATEGORY_IDS")),
        min_discount_pct=int(os.getenv("MIN_DISCOUNT_PCT", "10")),
        min_sold_quantity=int(os.getenv("MIN_SOLD_QUANTITY", "0")),
        min_rating=float(os.getenv("MIN_RATING", "0")),
        blocked_words=_split_csv(os.getenv("BLOCKED_WORDS")),
        max_price=float(os.getenv("MAX_PRICE")) if os.getenv("MAX_PRICE") else None,
        posts_per_round=int(os.getenv("POSTS_PER_ROUND", os.getenv("POSTS_POR_RODADA", "3"))),
        niche_rotate_min_posts=int(os.getenv("NICHE_ROTATE_MIN_POSTS", "3")),
        niche_rotate_max_posts=int(os.getenv("NICHE_ROTATE_MAX_POSTS", "5")),
        round_interval_minutes=int(os.getenv("ROUND_INTERVAL_MINUTES", "60")),
        dry_run=_bool_env("DRY_RUN", True),
        use_sample_data=_bool_env("USE_SAMPLE_DATA", False),
        product_source=_autopost_source(os.getenv("PRODUCT_SOURCE", "panel")),
        panel_cdp_url=os.getenv("PANEL_CDP_URL", "http://127.0.0.1:9222").strip(),
        shopee_panel_url=os.getenv(
            "SHOPEE_PANEL_URL",
            "https://affiliate.shopee.com.br/offer/product_offer",
        ).strip(),
        shopee_panel_cdp_url=os.getenv(
            "SHOPEE_PANEL_CDP_URL",
            os.getenv("PANEL_CDP_URL", "http://127.0.0.1:9222"),
        ).strip(),
        shopee_affiliate_app_id=os.getenv("SHOPEE_AFFILIATE_APP_ID") or None,
        shopee_affiliate_secret=os.getenv("SHOPEE_AFFILIATE_SECRET") or None,
        shopee_affiliate_api_url=os.getenv(
            "SHOPEE_AFFILIATE_API_URL",
            "https://open-api.affiliate.shopee.com.br/graphql",
        ).strip(),
        shopee_affiliate_enabled=_bool_env("SHOPEE_AFFILIATE_ENABLED", False),
        browser_profile_dir=os.getenv("BROWSER_PROFILE_DIR", "browser_profile/ml_affiliate").strip(),
        browser_headless=_bool_env("BROWSER_HEADLESS", False),
        promotion_types=_split_csv(os.getenv("PROMOTION_TYPES", "DOD,LIGHTNING,DEAL")),
        history_path=os.getenv("HISTORY_PATH", "data/posted_items.json"),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
        multiuser_browser_fallback=_bool_env("MULTIUSER_BROWSER_FALLBACK", True),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        ai_provider=os.getenv("AI_PROVIDER", "fallback").strip().lower(),
        ai_model=os.getenv("AI_MODEL") or None,
        post_emojis=_bool_env("POST_EMOJIS", True),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", os.getenv("TELEGRAM_CANAL_ID")) or None,
        admin_telegram_id=_int_env("ADMIN_TELEGRAM_ID") or _int_env("OWNER_TELEGRAM_ID"),
        owner_telegram_id=_int_env("OWNER_TELEGRAM_ID") or _int_env("ADMIN_TELEGRAM_ID"),
        health_port=int(os.getenv("HEALTH_PORT", "8080")),
        user_post_cooldown_seconds=int(os.getenv("USER_POST_COOLDOWN_SECONDS", "60")),
        user_posts_per_hour=int(os.getenv("USER_POSTS_PER_HOUR", "20")),
        max_channels_free=int(os.getenv("MAX_CHANNELS_FREE", "3")),
        free_max_channels=int(os.getenv("FREE_MAX_CHANNELS", "1")),
        free_posts_per_day=int(os.getenv("FREE_POSTS_PER_DAY", "20")),
        pro_max_channels=int(os.getenv("PRO_MAX_CHANNELS", "0")),
        pro_posts_per_day=int(os.getenv("PRO_POSTS_PER_DAY", "0")),
        token_auto_refresh=_bool_env("TOKEN_AUTO_REFRESH", True),
        price_history_enabled=_bool_env("PRICE_HISTORY_ENABLED", True),
        price_alert_check_interval=int(os.getenv("PRICE_ALERT_CHECK_INTERVAL", "30")),
        max_alerts_free=int(os.getenv("MAX_ALERTS_FREE", "5")),
        max_alerts_pro=int(os.getenv("MAX_ALERTS_PRO", "20")),
        daily_summary_enabled=_bool_env("DAILY_SUMMARY_ENABLED", True),
        daily_summary_hour=int(os.getenv("DAILY_SUMMARY_HOUR", "23")),
        weekly_niche_schedule=os.getenv("WEEKLY_NICHE_SCHEDULE", ""),
        curation_mode=_bool_env("CURATION_MODE", False),
        silent_hours=os.getenv("SILENT_HOURS", ""),
        blacklist_terms=_split_csv(os.getenv("BLACKLIST_TERMS")),
        outgoing_webhook_url=os.getenv("OUTGOING_WEBHOOK_URL") or None,
        outgoing_webhook_secret=os.getenv("OUTGOING_WEBHOOK_SECRET") or None,
        rss_enabled=_bool_env("RSS_ENABLED", False),
        rss_port=int(os.getenv("RSS_PORT", "8081")),
        weekly_report_enabled=_bool_env("WEEKLY_REPORT_ENABLED", True),
        offer_mockup_enabled=_bool_env("OFFER_MOCKUP_ENABLED", False),
        offer_mockup_brand=os.getenv("OFFER_MOCKUP_BRAND", "@GeekHunter_Br"),
        offer_mockup_background_url=os.getenv(
            "OFFER_MOCKUP_BACKGROUND_URL",
            "https://i.ibb.co/6R41sKyG/Chat-GPT-Image-13-de-mai-de-2026-21-16-28.png",
        )
        or None,
    )
    if not settings.search_terms and not settings.category_ids:
        object.__setattr__(settings, "search_terms", DEFAULT_SEARCH_TERMS)
    if settings.niche_rotate_max_posts < settings.niche_rotate_min_posts:
        object.__setattr__(settings, "niche_rotate_max_posts", settings.niche_rotate_min_posts)
    if not settings.category_ids:
        object.__setattr__(
            settings,
            "category_ids",
            ["MLB1051", "MLB1648", "MLB1574", "MLB1196", "MLB1144"],
        )
    return settings


def _autopost_source(value: str | None) -> str:
    source = (value or "panel").strip().lower()
    if source in {"mixed_panel", "shopee_panel"}:
        return "panel"
    return source
