"""Small helper to generate Mercado Livre OAuth tokens.

Usage:
  python meli_oauth.py auth-url
  python meli_oauth.py exchange --code CODIGO_RETORNADO
  python meli_oauth.py refresh
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import dotenv_values

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
AUTH_URL = "https://auth.mercadolivre.com.br/authorization"


def main() -> None:
    parser = argparse.ArgumentParser(description="Helper OAuth do Mercado Livre.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth-url", help="Mostra a URL para autorizar o app.")
    exchange = sub.add_parser("exchange", help="Troca o code por access_token e refresh_token.")
    exchange.add_argument("--code", required=True)
    sub.add_parser("refresh", help="Renova o access_token usando ML_REFRESH_TOKEN.")
    args = parser.parse_args()

    env = dotenv_values(".env")
    app_id = require(env, "ML_APP_ID")
    secret = require(env, "ML_SECRET_KEY")
    redirect_uri = require(env, "ML_REDIRECT_URI")

    if args.cmd == "auth-url":
        params = urlencode(
            {
                "response_type": "code",
                "client_id": app_id,
                "redirect_uri": redirect_uri,
            }
        )
        print(f"{AUTH_URL}?{params}")
        return

    if args.cmd == "exchange":
        payload = {
            "grant_type": "authorization_code",
            "client_id": app_id,
            "client_secret": secret,
            "code": args.code,
            "redirect_uri": redirect_uri,
        }
    else:
        payload = {
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": secret,
            "refresh_token": require(env, "ML_REFRESH_TOKEN"),
        }

    data = httpx.post(TOKEN_URL, data=payload, timeout=30).raise_for_status().json()
    updates = {
        "ML_ACCESS_TOKEN": data.get("access_token", ""),
        "ML_REFRESH_TOKEN": data.get("refresh_token", env.get("ML_REFRESH_TOKEN", "")),
        "ML_USER_ID": str(data.get("user_id", env.get("ML_USER_ID", ""))),
    }
    update_env(Path(".env"), updates)
    print("Tokens salvos no .env:")
    print(f"ML_ACCESS_TOKEN={redact(updates['ML_ACCESS_TOKEN'])}")
    print(f"ML_REFRESH_TOKEN={redact(updates['ML_REFRESH_TOKEN'])}")
    print(f"ML_USER_ID={updates['ML_USER_ID']}")


def require(env: dict, key: str) -> str:
    value = env.get(key)
    if not value:
        raise SystemExit(f"Preencha {key} no .env primeiro.")
    return value


def redact(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    new_lines = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
