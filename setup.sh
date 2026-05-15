#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env criado a partir do .env.example. Edite os tokens antes de iniciar."
fi

mkdir -p data logs

cat > ml-affiliate-bot.service <<SERVICE
[Unit]
Description=ML Affiliate Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python bot.py
Restart=always
RestartSec=5
EnvironmentFile=$(pwd)/.env

[Install]
WantedBy=multi-user.target
SERVICE

echo "Setup concluido."
echo "Servico systemd exemplo gerado em ml-affiliate-bot.service"
