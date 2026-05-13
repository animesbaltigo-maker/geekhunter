# Rodar na VPS

Para postar automaticamente a cada 10 minutos:

```bash
python bot.py
```

Esse comando tambem liga o bot multiusuario no privado.

O intervalo fica no `.env`:

```env
ROUND_INTERVAL_MINUTES=10
POSTS_PER_ROUND=1
PRODUCT_SOURCE=panel
```

Para testar uma rodada sem postar:

```bash
python bot.py --once --dry-run
```

Para testar postando uma rodada:

```bash
python bot.py --once --post
```

## Ponto importante sobre a VPS

Hoje o bot usa o painel de afiliados logado no Chrome para gerar os links `meli.la`.

Na VPS, precisa existir um Chrome/Chromium logado no Mercado Livre Afiliados e aberto com porta de automacao:

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/ml-affiliate/chrome-profile \
  --no-sandbox
```

Na primeira vez, voce provavelmente vai precisar entrar via VNC/noVNC para fazer login e resolver qualquer captcha. Depois disso, o perfil fica salvo.

## Evolucao para varias pessoas

Objetivo:

1. Usuario chama o bot no privado.
2. Usuario cadastra um canal.
3. Bot pede para ser admin do canal.
4. Usuario manda um link de produto.
5. Bot usa o link enviado pela pessoa como link final.
6. Bot extrai titulo, preco, imagem, desconto e vendidos.
7. Bot monta a postagem bonita.
8. Bot publica no canal cadastrado.
9. Bot avisa no privado: "postado com sucesso".

Para isso, vamos precisar mudar de script agendado para um bot Telegram com banco de dados.

Tabela `users`:

```text
telegram_user_id
name
created_at
```

Tabela `channels`:

```text
telegram_user_id
channel_id
channel_title
created_at
```

Tabela `posts`:

```text
telegram_user_id
channel_id
product_url
affiliate_url
telegram_message_id
status
created_at
```

Comandos do bot:

```text
/start
/cadastrar_canal
/meus_canais
/remover_canal
/postar
```

Fluxo ideal:

```text
Usuario manda link
    ↓
Bot pergunta em qual canal postar, se houver mais de um
    ↓
Bot usa o link enviado pela pessoa
    ↓
Bot extrai dados do produto para montar o post
    ↓
Bot envia foto + legenda
    ↓
Bot salva historico
    ↓
Bot confirma no privado
```

Observacao importante:

No modo multiusuario, o bot nao gera link afiliado para a pessoa. Ele usa exatamente o link que a pessoa enviar no privado. Assim cada usuario pode mandar o proprio link de afiliado/etiqueta.

## Rodar o bot multiusuario

O modo multiusuario fica em:

```bash
python bot.py --only-multiuser
```

Ele usa o mesmo `TELEGRAM_BOT_TOKEN` do `.env`.

Fluxo no Telegram:

```text
/start
    ↓
Cadastrar canal
    ↓
Usuario envia @canal
    ↓
Bot valida se e admin
    ↓
Usuario envia link de produto
    ↓
Bot posta no canal e confirma no privado
```

Comandos:

```text
/start - abre o menu principal
/cadastrar_canal - cadastra um canal
/meus_canais - lista canais salvos
/remover_canal - remove um canal salvo
/ajuda - mostra o passo a passo
```

Banco de dados:

```text
data/multiuser.sqlite3
```

Esse arquivo guarda:

```text
usuarios
canais
posts
pedidos pendentes
```

### Importante

O bot multiusuario tambem depende do Chrome logado no Mercado Livre Afiliados para gerar os links `meli.la`.

Na VPS, deixe o Chrome aberto assim:

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/ml-affiliate/chrome-profile \
  --no-sandbox
```

Depois rode o bot:

```bash
python multiuser_bot.py
```

### Servico systemd exemplo

```ini
[Unit]
Description=ML Affiliate Multiuser Bot
After=network.target

[Service]
WorkingDirectory=/opt/ml-affiliate-bot
ExecStart=/usr/bin/python3 multiuser_bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

O Chrome logado deve estar rodando antes do bot, ou a geracao do `meli.la` vai falhar.
