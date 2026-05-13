# VPS no modo ideal

Essa e a opcao B: a VPS vira a maquina oficial do bot.

- A autopostagem usa um Chrome/Chromium aberto na propria VPS, logado no painel de afiliados do Mercado Livre.
- O bot multiusuario nao depende desse Chrome por padrao. Ele extrai dados por HTML publico e usa o link que a pessoa mandou.
- Seu PC nao precisa ficar aberto depois que a VPS estiver configurada.

## 1. Preparar a VPS

Use Ubuntu 22.04/24.04.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl wget unzip xvfb
```

Clone o repositorio:

```bash
cd /opt
sudo git clone https://github.com/animesbaltigo-maker/geekhunter.git
sudo chown -R $USER:$USER /opt/geekhunter
cd /opt/geekhunter
```

Crie o ambiente Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

## 2. Criar o .env na VPS

```bash
cp .env.example .env
nano .env
```

Valores importantes:

```env
DRY_RUN=false
PRODUCT_SOURCE=panel
PANEL_CDP_URL=http://127.0.0.1:9222
MULTIUSER_BROWSER_FALLBACK=false
POSTS_PER_ROUND=1
ROUND_INTERVAL_MINUTES=10
```

Preencha tambem:

```env
TELEGRAM_BOT_TOKEN=token_do_botfather
TELEGRAM_CHANNEL_ID=@seu_canal_ou_-100xxxxxxxxxx
ML_AFFILIATE_LABEL_ID=sua_etiqueta
AFFILIATE_LINK_MODE=template
AFFILIATE_URL_TEMPLATE=
```

Nao suba o `.env` para o GitHub.

## 3. Deixar o painel do Mercado Livre logado na VPS

O painel precisa ficar logado uma vez no perfil da VPS. O jeito mais simples e usar uma VPS com desktop/noVNC, abrir o navegador, fazer login e resolver captcha se aparecer.

Depois deixe um Chrome/Chromium rodando com CDP:

```bash
mkdir -p /opt/geekhunter/browser_profile/chrome_cdp
chromium \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/geekhunter/browser_profile/chrome_cdp \
  --no-sandbox \
  --disable-dev-shm-usage
```

Se sua VPS usar Google Chrome:

```bash
google-chrome \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/geekhunter/browser_profile/chrome_cdp \
  --no-sandbox \
  --disable-dev-shm-usage
```

Abra `https://www.mercadolivre.com.br/afiliados` nesse navegador e confirme que o painel aparece logado.

## 4. Testar antes de deixar fixo

Com o Chrome da VPS aberto:

```bash
cd /opt/geekhunter
source .venv/bin/activate
python bot.py --once --dry-run
```

Se o teste estiver bom, poste uma rodada real:

```bash
python bot.py --once --post
```

Para rodar tudo junto:

```bash
python bot.py
```

Esse comando liga autopostagem + multiusuario.

## 5. Systemd para manter rodando

Crie o servico do Chrome:

```bash
sudo nano /etc/systemd/system/geekhunter-chrome.service
```

```ini
[Unit]
Description=GeekHunter Chrome CDP
After=network.target

[Service]
User=SEU_USUARIO
WorkingDirectory=/opt/geekhunter
ExecStart=/usr/bin/chromium --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/opt/geekhunter/browser_profile/chrome_cdp --no-sandbox --disable-dev-shm-usage
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Se o binario for outro, descubra com:

```bash
which chromium
which google-chrome
```

Crie o servico do bot:

```bash
sudo nano /etc/systemd/system/geekhunter-bot.service
```

```ini
[Unit]
Description=GeekHunter Affiliate Bot
After=network.target geekhunter-chrome.service
Requires=geekhunter-chrome.service

[Service]
User=SEU_USUARIO
WorkingDirectory=/opt/geekhunter
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/geekhunter/.venv/bin/python /opt/geekhunter/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Ative:

```bash
sudo systemctl daemon-reload
sudo systemctl enable geekhunter-chrome geekhunter-bot
sudo systemctl start geekhunter-chrome
sudo systemctl start geekhunter-bot
```

Ver logs:

```bash
journalctl -u geekhunter-bot -f
journalctl -u geekhunter-chrome -f
```

## 6. Como fica para muitos usuarios

O gargalo do Google/Chrome nao fica no multiusuario.

Quando alguem manda link no privado:

1. O bot valida se a pessoa e admin do canal cadastrado.
2. O bot usa o link enviado pela pessoa.
3. O bot extrai titulo, preco, imagem e vendidos sem depender do Chrome.
4. O bot posta no canal da pessoa.

O Chrome logado da VPS fica reservado para a autopostagem que le produtos do painel do Mercado Livre Afiliados.

## 7. Problemas comuns

Erro `Conflict: terminated by other getUpdates request`:

```bash
ps aux | grep bot.py
sudo systemctl stop geekhunter-bot
```

Deixe apenas uma instancia do bot rodando.

Erro ao ler painel:

```bash
curl http://127.0.0.1:9222/json/version
```

Se nao responder, o Chrome CDP nao esta aberto.

Se o painel pedir login de novo, entre via noVNC/desktop da VPS e refaca o login no perfil:

```text
/opt/geekhunter/browser_profile/chrome_cdp
```
