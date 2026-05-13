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
    max_price: float | None = None
    posts_per_round: int = 3
    niche_rotate_min_posts: int = 3
    niche_rotate_max_posts: int = 5
    round_interval_minutes: int = 60
    dry_run: bool = True
    use_sample_data: bool = False
    product_source: str = "panel"
    promotion_types: list[str] = field(default_factory=list)
    history_path: str = "data/posted_items.json"
    request_timeout: float = 20
    multiuser_browser_fallback: bool = False
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    ai_provider: str = "fallback"
    ai_model: str | None = None
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None

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
        max_price=float(os.getenv("MAX_PRICE")) if os.getenv("MAX_PRICE") else None,
        posts_per_round=int(os.getenv("POSTS_PER_ROUND", os.getenv("POSTS_POR_RODADA", "3"))),
        niche_rotate_min_posts=int(os.getenv("NICHE_ROTATE_MIN_POSTS", "3")),
        niche_rotate_max_posts=int(os.getenv("NICHE_ROTATE_MAX_POSTS", "5")),
        round_interval_minutes=int(os.getenv("ROUND_INTERVAL_MINUTES", "60")),
        dry_run=_bool_env("DRY_RUN", True),
        use_sample_data=_bool_env("USE_SAMPLE_DATA", False),
        product_source=os.getenv("PRODUCT_SOURCE", "panel").strip().lower(),
        promotion_types=_split_csv(os.getenv("PROMOTION_TYPES", "DOD,LIGHTNING,DEAL")),
        history_path=os.getenv("HISTORY_PATH", "data/posted_items.json"),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
        multiuser_browser_fallback=_bool_env("MULTIUSER_BROWSER_FALLBACK", False),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        ai_provider=os.getenv("AI_PROVIDER", "fallback").strip().lower(),
        ai_model=os.getenv("AI_MODEL") or None,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", os.getenv("TELEGRAM_CANAL_ID")) or None,
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
