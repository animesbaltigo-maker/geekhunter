"""Runtime configuration overrides stored on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import Settings


class ConfigManager:
    EDITABLE_KEYS = {
        "posts_por_rodada": ("posts_per_round", int, (1, 20)),
        "intervalo": ("round_interval_minutes", int, (5, 1440)),
        "desconto_minimo": ("min_discount_pct", int, (0, 90)),
        "modo_curador": ("curation_mode", bool, None),
        "horario_silencioso": ("silent_hours", str, None),
        "blacklist": ("blacklist_terms", list, None),
    }

    def __init__(self, path: str = "data/config_overrides.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def apply(self, settings: Settings, key: str, value: str) -> str:
        if key not in self.EDITABLE_KEYS:
            raise ValueError("configuracao nao editavel")
        attr, caster, bounds = self.EDITABLE_KEYS[key]
        parsed = self._parse_value(caster, value)
        if bounds and isinstance(parsed, int):
            low, high = bounds
            if parsed < low or parsed > high:
                raise ValueError(f"{key} deve ficar entre {low} e {high}")
        object.__setattr__(settings, attr, parsed)
        data = self._read()
        data[attr] = parsed
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"{key} atualizado para {parsed}"

    def load_overrides(self, settings: Settings) -> Settings:
        for attr, value in self._read().items():
            if hasattr(settings, attr):
                object.__setattr__(settings, attr, value)
        return settings

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _parse_value(self, caster: type, value: str) -> Any:
        if caster is bool:
            return value.strip().lower() in {"1", "true", "sim", "yes", "on", "ligado"}
        if caster is list:
            return [part.strip() for part in value.split(",") if part.strip()]
        return caster(value)
