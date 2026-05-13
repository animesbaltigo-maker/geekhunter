# Bot de Ofertas Mercado Livre para Telegram

Busca ofertas no Mercado Livre, ranqueia as melhores, gera texto com IA ou fallback local e posta no canal do Telegram.

Por seguranca, o bot vem em `DRY_RUN=true`: ele mostra no log o que postaria, mas nao envia nada.

## Estrutura

```text
bot.py              Entrada principal e agendamento
config.py           Leitura das variaveis de ambiente
ml_scraper.py       Busca, filtros, score e link afiliado
ai_generator.py     Copy para Telegram com IA ou fallback local
telegram_poster.py  Envio para canal Telegram
history.py          Historico para nao repetir produto
.env.example        Exemplo de configuracao
```

## Instalar

```bash
pip install -r requirements.txt
copy .env.example .env
```

Preencha o `.env`.

## Rodar uma rodada de teste

```bash
python bot.py --once
```

Isso busca ofertas e imprime os posts no log sem enviar ao Telegram.

Se ainda nao tiver token do Mercado Livre, teste com dados ficticios:

```powershell
$env:USE_SAMPLE_DATA="true"
python bot.py --once
```

## Postar de verdade

1. Crie um bot com `@BotFather`.
2. Adicione o bot como administrador do canal.
3. Preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHANNEL_ID`.
4. Configure seu link oficial de afiliado em `AFFILIATE_URL_TEMPLATE`, se o painel do Mercado Livre fornecer um formato de deeplink.
5. Rode:

```bash
python bot.py --once --post
```

Para ligar tudo, use:

```bash
python bot.py
```

Isso inicia:

```text
autopostagem do seu canal
bot multiusuario no privado
```

Para deixar somente a autopostagem em loop:

```bash
DRY_RUN=false
python bot.py --only-auto
```

No PowerShell:

```powershell
$env:DRY_RUN="false"
python bot.py
```

Ou rode sem alterar o `.env`:

```bash
python bot.py --only-auto --post
```

O projeto esta configurado para 10 minutos por rodada:

```env
ROUND_INTERVAL_MINUTES=10
```

Fontes de produtos:

```env
PRODUCT_SOURCE=panel
```

Usa o painel de afiliados, que e a fonte principal do canal automatico.

```env
PRODUCT_SOURCE=promotions
```

Usa os endpoints oficiais `seller-promotions` para `DOD`, `LIGHTNING` e `DEAL`. Essa fonte so retorna produtos quando a conta tem promocoes/campanhas elegiveis.

## Bot multiusuario

Para rodar somente o modo onde varias pessoas cadastram canais e mandam links no privado:

```bash
python bot.py --only-multiuser
```

Ele salva usuarios, canais e historico em:

```text
data/multiuser.sqlite3
```

Veja detalhes em `VPS_E_MULTIUSUARIO.md`.

## IA

O bot funciona sem IA paga usando `AI_PROVIDER=fallback`.

Para usar Groq:

```env
AI_PROVIDER=groq
GROQ_API_KEY=...
AI_MODEL=llama-3.3-70b-versatile
```

O endpoint usado e o OpenAI-compatible da Groq:

```text
https://api.groq.com/openai/v1/chat/completions
```

Outras opcoes:

```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

ou:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=...
```

## Sobre cookies

Este projeto nao automatiza cookies da sua conta. Cookies expiram, podem acionar bloqueios e sao uma base fragil para automacao. O caminho mais estavel e usar busca/API publica do Mercado Livre e o formato oficial de afiliado/deeplink no `AFFILIATE_URL_TEMPLATE`.

## Mercado Livre OAuth

Preencha no `.env`:

```env
ML_APP_ID=
ML_SECRET_KEY=
ML_REDIRECT_URI=
```

Depois gere a URL de autorizacao:

```bash
python meli_oauth.py auth-url
```

Abra a URL, autorize o app e copie o parametro `code` que voltar na URL. Troque por tokens:

```bash
python meli_oauth.py exchange --code CODIGO_RETORNADO
```

Quando o token expirar:

```bash
python meli_oauth.py refresh
```

## Afiliados

No painel "Gerar link / ID de produto", a "Etiqueta em uso" vai em:

```env
ML_AFFILIATE_LABEL_ID=5520241221205245
```

O link `https://meli.la/...` gerado pelo painel e um shortlink criado pelo Mercado Livre. Para automatizar 100%, precisamos descobrir se o painel oferece um formato oficial de deeplink ou endpoint para gerar esse shortlink. Se oferecer, coloque o modelo em:

```env
AFFILIATE_LINK_MODE=template
AFFILIATE_URL_TEMPLATE=https://...
```

O modo `query` existe para teste controlado:

```env
AFFILIATE_LINK_MODE=query
```

Ele adiciona `matt_tool` e `matt_word` ao permalink, mas voce deve validar no painel se os cliques/vendas aparecem antes de usar em producao.

## Painel de afiliados

Como a API publica de busca pode retornar 403, existe um assistente para abrir o painel e capturar links `meli.la`.

Primeiro abra e faca login:

```bash
python affiliate_panel.py open
```

Depois tente gerar/capturar um link:

```bash
python affiliate_panel.py generate --product-url "https://www.mercadolivre.com.br/..."
```

Se o painel mudar ou o script nao achar os botoes, ele deixa o navegador aberto para voce gerar manualmente uma vez e captura o `https://meli.la/...` quando aparecer na tela.

## Ajustes uteis

```env
SEARCH_TERMS=ofertas do dia,iphone,ssd,air fryer
CATEGORY_IDS=MLB1051,MLB1648
MIN_DISCOUNT_PCT=15
MIN_SOLD_QUANTITY=25
MAX_PRICE=2000
POSTS_PER_ROUND=5
ROUND_INTERVAL_MINUTES=30
```
