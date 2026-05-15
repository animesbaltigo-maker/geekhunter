"""Multi-user Telegram bot for affiliate channel posting."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import sys
from time import time, localtime, strftime
from urllib.parse import urlparse

import httpx

from ai_generator import gerar_post
from config_manager import ConfigManager
from config import Settings, load_settings
from health import basic_health, format_health_report
from offer_mockup import maybe_create_offer_mockup
from price_alerts import PriceAlertService
from price_history import PriceHistory
from product_extractor import detect_platform, extrair_produto
from storage import Storage
from telegram_client import TelegramClient, keyboard

URL_RE = re.compile(r"https?://\S+")


SUPPORTED_TEXT = "Mercado Livre, Amazon, Shopee, Shein, AliExpress, Magalu e Natura"


def setup_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


log = logging.getLogger(__name__)
_BROWSER_FALLBACK_SEMAPHORE = asyncio.Semaphore(1)


class MultiUserBot:
    def __init__(self, settings: Settings | None = None, storage: Storage | None = None) -> None:
        self.settings = settings or load_settings()
        if not self.settings.telegram_bot_token:
            raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no .env.")
        self.tg = TelegramClient(self.settings.telegram_bot_token, self.settings.request_timeout)
        self.db = storage or Storage()
        self.price_history = PriceHistory()
        self.alerts = PriceAlertService(self.db, self.tg, self.settings)
        self.config_manager = ConfigManager()
        self.bot_user: dict | None = None

    async def run(self) -> None:
        self.bot_user = await self.tg.get_me()
        log.info("Bot multiusuario iniciado como @%s", self.bot_user.get("username"))
        offset = None
        while True:
            try:
                updates = await self.tg.get_updates(offset=offset, timeout=30)
                for update in updates:
                    offset = update["update_id"] + 1
                    await self.handle_update(update)
            except httpx.ReadTimeout:
                log.debug("Timeout normal do long polling. Continuando...")
            except Exception:
                log.exception("Erro no loop principal")
                await asyncio.sleep(2)

    async def handle_update(self, update: dict) -> None:
        if "message" in update:
            await self.handle_message(update["message"])
        elif "callback_query" in update:
            await self.handle_callback(update["callback_query"])

    async def handle_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        text = (message.get("text") or "").strip()
        if chat.get("type") != "private" or not user:
            return

        self.db.upsert_user(user)
        user_id = int(user["id"])
        state, state_data = self.db.get_state(user_id)

        if text.startswith("/start"):
            self.db.set_state(user_id, None)
            await self.send_start(chat["id"], user)
            return
        if text.startswith("/cadastrar_canal"):
            await self.ask_channel(chat["id"], user_id)
            return
        if text.startswith("/meus_canais"):
            await self.show_channels(chat["id"], user_id)
            return
        if text.startswith("/remover_canal"):
            await self.show_remove_channels(chat["id"], user_id)
            return
        if text.startswith("/ajuda"):
            await self.send_help(chat["id"])
            return
        if text.startswith("/planos"):
            await self.send_plans(chat["id"], user_id)
            return
        if text.startswith("/admin"):
            await self.send_admin(chat["id"], user_id)
            return
        if text.startswith("/usuarios"):
            await self.send_admin_users(chat["id"], user_id)
            return
        if text.startswith("/ativar_pro"):
            await self.activate_pro_command(chat["id"], user_id, text)
            return
        if text.startswith("/desativar_pro"):
            await self.deactivate_pro_command(chat["id"], user_id, text)
            return
        if text.startswith("/stats") and self._is_admin(user_id):
            await self.send_admin_stats(chat["id"], user_id)
            return
        if text.startswith("/status") or text.startswith("/stats"):
            await self.send_status(chat["id"], user_id)
            return
        if text.startswith("/limites"):
            await self.send_limits(chat["id"], user_id)
            return
        if text.startswith("/meus_posts") or text.startswith("/historico"):
            await self.send_recent_posts(chat["id"], user_id)
            return
        if text.startswith("/monitorar"):
            await self.monitor_command(chat["id"], user_id, text)
            return
        if text.startswith("/meus_alertas"):
            await self.send_alerts(chat["id"], user_id)
            return
        if text.startswith("/pedir"):
            await self.offer_request_command(chat["id"], user_id, text)
            return
        if text.startswith("/ativar "):
            await self.activate_code_command(chat["id"], user_id, text)
            return
        if text.startswith("/config"):
            await self.config_command(chat["id"], user_id, text)
            return
        if text.startswith("/suporte"):
            await self.send_support(chat["id"])
            return
        if text.startswith("/health"):
            await self.send_health(chat["id"], user_id)
            return

        if state == "awaiting_channel":
            await self.register_channel(chat["id"], user_id, text)
            return
        if state == "awaiting_caption":
            pending_id = int(state_data.get("pending_id") or 0)
            await self.receive_edited_caption(chat["id"], user_id, pending_id, text)
            return

        url = self.extract_url(text)
        if url:
            await self.receive_product_link(chat["id"], user_id, url)
            return

        await self.tg.send_message(
            chat["id"],
            "⚡ <b>Me mande um link afiliado de produto.</b>\n\n"
            f"Suporto: <b>{SUPPORTED_TEXT}</b>.\n"
            "Eu uso exatamente o link que você enviou e publico no canal escolhido.",
            reply_markup=main_keyboard(),
        )

    async def handle_callback(self, query: dict) -> None:
        data = query.get("data") or ""
        user = query.get("from") or {}
        message = query.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        user_id = int(user["id"])
        self.db.upsert_user(user)

        await self.tg.answer_callback_query(query["id"])

        if data == "start:home":
            await self.send_start(chat_id, user, message_id)
            return
        if data == "start:register":
            await self.ask_channel(chat_id, user_id, message_id)
            return
        if data == "start:channels":
            await self.show_channels(chat_id, user_id, message_id)
            return
        if data == "start:help":
            await self.send_help(chat_id, message_id)
            return
        if data == "remove:list":
            await self.show_remove_channels(chat_id, user_id, message_id)
            return
        if data.startswith("remove:"):
            removed = self.db.remove_channel(int(data.split(":", 1)[1]), user_id)
            text = "✅ <b>Canal removido.</b>" if removed else "⚠️ Não encontrei esse canal."
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
            return
        if data.startswith("postcancel:"):
            pending_id = int(data.split(":", 1)[1])
            self.db.delete_pending_post(pending_id, user_id)
            await self.tg.edit_message_text(chat_id, message_id, "✅ <b>Pedido cancelado.</b>", reply_markup=main_keyboard())
            return
        if data.startswith("preview:publish:"):
            pending_id = int(data.rsplit(":", 1)[1])
            await self.publish_pending(chat_id, user_id, pending_id, service_message_id=message_id)
            return
        if data.startswith("preview:edit:"):
            pending_id = int(data.rsplit(":", 1)[1])
            if not self.db.get_pending_post(pending_id, user_id):
                await self.tg.edit_message_text(chat_id, message_id, "Preview expirou.", reply_markup=main_keyboard())
                return
            self.db.set_state(user_id, "awaiting_caption", {"pending_id": pending_id})
            await self.tg.send_message(chat_id, "Envie o novo texto da legenda. Eu publico assim que receber.")
            return
        if data.startswith("preview:regen:"):
            pending_id = int(data.rsplit(":", 1)[1])
            pending = self.db.get_pending_post(pending_id, user_id)
            if not pending:
                await self.tg.edit_message_text(chat_id, message_id, "Preview expirou.", reply_markup=main_keyboard())
                return
            product = self.db.pending_product(pending)
            caption = await gerar_post(product, self.settings)
            self.db.update_pending_post(pending_id, user_id, caption=caption)
            await self.tg.send_photo(
                chat_id,
                pending["image_url"],
                _preview_caption(caption),
                reply_markup=preview_keyboard(pending_id),
                disable_notification=True,
            )
            return
        if data.startswith("preview:watch:"):
            pending_id = int(data.rsplit(":", 1)[1])
            await self.create_alert_from_pending(chat_id, user_id, pending_id, message_id)
            return
        if data.startswith("preview:cancel:"):
            pending_id = int(data.rsplit(":", 1)[1])
            self.db.delete_pending_post(pending_id, user_id)
            self.db.set_state(user_id, None)
            await self.tg.edit_message_text(chat_id, message_id, "Preview cancelado.", reply_markup=main_keyboard())
            return
        if data.startswith("cancelalert:"):
            alert_id = int(data.rsplit(":", 1)[1])
            cancelled = await self.alerts.cancel_alert(alert_id, user_id)
            text = "Alerta cancelado." if cancelled else "Nao encontrei esse alerta."
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
            return
        if data.startswith("post:"):
            _, pending_id, channel_db_id = data.split(":")
            pending = self.db.get_pending_post(int(pending_id), user_id)
            channel = self.db.get_channel(int(channel_db_id), user_id)
            if not pending or not channel:
                await self.tg.edit_message_text(chat_id, message_id, "⚠️ Esse pedido expirou. Envie o link de novo.", reply_markup=main_keyboard())
                return
            await self.tg.edit_message_text(
                chat_id,
                message_id,
                "🛠️ <b>Criando postagem...</b>\n\n<i>Vou extrair os dados, montar a arte da mensagem e publicar no canal.</i>",
            )
            await self.prepare_preview(
                chat_id,
                user_id,
                pending["product_url"],
                channel,
                pending_id=int(pending_id),
                service_message_id=message_id,
                edit_service=True,
            )
            return

    async def send_start(self, chat_id: int, user: dict, message_id: int | None = None) -> None:
        name = html.escape(user.get("first_name") or "tudo bem")
        text = (
            f"🔥 <b>Olá, {name}.</b>\n\n"
            "Eu transformo links afiliados em posts bonitos para canais de ofertas.\n\n"
            "• Cadastre um ou mais canais\n"
            "• Envie o link afiliado no privado\n"
            "• Escolha o canal e eu publico com imagem, preço e CTA\n\n"
            f"<i>Plataformas: {SUPPORTED_TEXT}.</i>"
        )
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
        else:
            await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_help(self, chat_id: int, message_id: int | None = None) -> None:
        text = (
            "📌 <b>Como usar</b>\n\n"
            "1. Adicione este bot como <b>administrador</b> do seu canal.\n"
            "2. Toque em <b>Cadastrar canal</b>.\n"
            "3. Envie o @ do canal ou o ID numérico.\n"
            "4. Mande o <b>link afiliado</b> do produto no privado.\n"
            "5. Se tiver vários canais, escolha onde postar.\n\n"
            "<i>Eu não gero outro link para o usuário: uso o link afiliado que a pessoa enviou.</i>"
        )
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
        else:
            await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def ask_channel(self, chat_id: int, user_id: int, message_id: int | None = None) -> None:
        allowed, count, limit, plan = self.db.can_add_channel(
            user_id,
            self.settings.free_max_channels,
            self.settings.pro_max_channels,
        )
        if not allowed:
            text = _channel_limit_message(plan, count, limit)
            if message_id:
                await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
            else:
                await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())
            return
        self.db.set_state(user_id, "awaiting_channel")
        text = (
            "📣 <b>Cadastro de canal</b>\n\n"
            "Me envie o @ do canal ou o ID numérico.\n\n"
            "Antes disso, coloque o bot como <b>administrador</b> para ele conseguir publicar."
        )
        markup = keyboard([[('⬅️ Voltar', 'start:home')]])
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            await self.tg.send_message(chat_id, text, reply_markup=markup)

    async def register_channel(self, chat_id: int, user_id: int, channel_ref: str) -> None:
        channel_ref = channel_ref.strip()
        allowed, count, limit, plan = self.db.can_add_channel(
            user_id,
            self.settings.free_max_channels,
            self.settings.pro_max_channels,
        )
        if not allowed:
            self.db.set_state(user_id, None)
            await self.tg.send_message(chat_id, _channel_limit_message(plan, count, limit), reply_markup=main_keyboard())
            return
        try:
            chat = await self.tg.get_chat(channel_ref)
            bot_member = await self.tg.get_chat_member(chat["id"], self.bot_user["id"])
            user_member = await self.tg.get_chat_member(chat["id"], user_id)
        except Exception as exc:
            await self.tg.send_message(
                chat_id,
                "⚠️ <b>Não consegui acessar esse canal.</b>\n\n"
                "Confira se o @ está certo e se o bot já foi adicionado como administrador.",
                reply_markup=main_keyboard(),
            )
            log.warning("Falha ao cadastrar canal: %s", exc)
            return

        if bot_member.get("status") not in {"administrator", "creator"}:
            await self.tg.send_message(
                chat_id,
                "⚠️ <b>O bot ainda não é administrador desse canal.</b>\n\n"
                "Dê permissão de postagem e envie o canal de novo.",
                reply_markup=main_keyboard(),
            )
            return

        if not _can_user_manage_channel(user_member):
            await self.tg.send_message(
                chat_id,
                "⛔ <b>Você precisa ser administrador ou criador desse canal.</b>\n\n"
                "Por segurança, não posso cadastrar canal onde você não tem permissão de administração.",
                reply_markup=main_keyboard(),
            )
            return

        self.db.add_channel(user_id, chat)
        self.db.set_state(user_id, None)
        title = html.escape(chat.get("title") or str(chat.get("id")))
        await self.tg.send_message(
            chat_id,
            f"✅ <b>Canal cadastrado.</b>\n\n📣 {title}\n\nAgora mande um link afiliado de produto.",
            reply_markup=main_keyboard(),
        )

    async def show_channels(self, chat_id: int, user_id: int, message_id: int | None = None) -> None:
        channels = self.db.list_channels(user_id)
        if not channels:
            text = "📭 <b>Você ainda não cadastrou canais.</b>"
            markup = keyboard([[('➕ Cadastrar canal', 'start:register')], [('⬅️ Voltar', 'start:home')]])
        else:
            lines = ["📣 <b>Seus canais cadastrados</b>", ""]
            for channel in channels:
                lines.append(f"• {html.escape(channel['channel_title'] or channel['channel_id'])}")
            text = "\n".join(lines)
            markup = keyboard([[('➕ Cadastrar outro', 'start:register'), ('🧹 Remover', 'remove:list')], [('⬅️ Voltar', 'start:home')]])
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            await self.tg.send_message(chat_id, text, reply_markup=markup)

    async def show_remove_channels(self, chat_id: int, user_id: int, message_id: int | None = None) -> None:
        channels = self.db.list_channels(user_id)
        if not channels:
            text = "📭 <b>Nenhum canal para remover.</b>"
            markup = main_keyboard()
        else:
            rows = [[(channel["channel_title"] or channel["channel_id"], f"remove:{channel['id']}")] for channel in channels]
            rows.append([("⬅️ Voltar", "start:channels")])
            text = "🧹 <b>Qual canal você quer remover?</b>"
            markup = keyboard(rows)
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        else:
            await self.tg.send_message(chat_id, text, reply_markup=markup)

    async def receive_product_link(self, chat_id: int, user_id: int, product_url: str) -> None:
        if not _is_valid_product_url(product_url):
            await self.tg.send_message(
                chat_id,
                "Link nao reconhecido.\n\n"
                f"Envie URLs de: <b>{SUPPORTED_TEXT}</b>.",
                reply_markup=main_keyboard(),
            )
            return
        allowed, wait = self._check_link_rate_limit(user_id)
        if not allowed:
            await self.tg.send_message(
                chat_id,
                f"Aguarde <b>{wait}s</b> antes de preparar outro link.",
                reply_markup=main_keyboard(),
            )
            return
        self.db.add_rate_event(user_id, "link")
        channels = self.db.list_channels(user_id)
        if not channels:
            await self.tg.send_message(
                chat_id,
                "📣 <b>Antes de postar, cadastre um canal.</b>\n\n"
                "Adicione o bot como admin do canal e toque em cadastrar.",
                reply_markup=keyboard([[('➕ Cadastrar canal', 'start:register')]]),
            )
            return

        if len(channels) == 1:
            service = await self.tg.send_message(
                chat_id,
                "🛠️ <b>Criando postagem...</b>\n\n<i>Vou extrair os dados e preparar o post.</i>",
            )
            await self.prepare_preview(chat_id, user_id, product_url, channels[0], service_message_id=service.get("message_id"))
            return

        pending_id = self.db.add_pending_post(user_id, product_url)
        rows = [[(channel["channel_title"] or channel["channel_id"], f"post:{pending_id}:{channel['id']}")] for channel in channels]
        rows.append([("❌ Cancelar", f"postcancel:{pending_id}")])
        await self.tg.send_message(
            chat_id,
            "📣 <b>Em qual canal devo postar?</b>",
            reply_markup=keyboard(rows),
        )

    async def prepare_preview(
        self,
        chat_id: int,
        user_id: int,
        product_url: str,
        channel: dict,
        pending_id: int | None = None,
        service_message_id: int | None = None,
        edit_service: bool = False,
    ) -> bool:
        try:
            if not await self.ensure_user_can_post_to_channel(chat_id, user_id, channel, service_message_id):
                return False
            produto = await self.extract_product_for_post(product_url)
            caption = await gerar_post(produto, self.settings)
            image_url = await maybe_create_offer_mockup(produto, self.settings) or produto.get("imagem")
            if not image_url:
                raise ValueError("Produto sem imagem confirmada; postagem bloqueada.")
            if pending_id is None:
                pending_id = self.db.add_pending_post(user_id, product_url, int(channel["id"]), produto, caption, image_url)
            else:
                self.db.update_pending_post(
                    pending_id,
                    user_id,
                    product=produto,
                    caption=caption,
                    image_url=image_url,
                    channel_db_id=int(channel["id"]),
                )
            if service_message_id and not edit_service:
                await self.tg.delete_message(chat_id, service_message_id)
            await self.tg.send_photo(
                chat_id,
                image_url,
                _preview_caption(caption),
                reply_markup=preview_keyboard(pending_id),
                disable_notification=True,
            )
            return True
        except Exception as exc:
            log.exception("Falha ao preparar preview")
            error_text = _friendly_error(exc)
            if service_message_id and edit_service:
                await self.tg.edit_message_text(chat_id, service_message_id, error_text, reply_markup=main_keyboard())
            else:
                if service_message_id:
                    await self.tg.delete_message(chat_id, service_message_id)
                await self.tg.send_message(chat_id, error_text, reply_markup=main_keyboard())
            return False

    async def publish_pending(
        self,
        chat_id: int,
        user_id: int,
        pending_id: int,
        service_message_id: int | None = None,
    ) -> bool:
        pending = self.db.get_pending_post(pending_id, user_id)
        if not pending:
            await self.tg.send_message(chat_id, "Esse preview expirou. Envie o link de novo.", reply_markup=main_keyboard())
            return False
        channel = self.db.get_channel(int(pending["channel_db_id"]), user_id)
        if not channel:
            await self.tg.send_message(chat_id, "Canal nao encontrado. Cadastre o canal novamente.", reply_markup=main_keyboard())
            return False
        allowed, remaining = self._check_post_rate_limit(user_id)
        if not allowed:
            await self.tg.send_message(
                chat_id,
                f"Limite de posts por hora atingido. Tente novamente em <b>{remaining} min</b>.",
                reply_markup=main_keyboard(),
            )
            return False
        allowed_today, used_today, daily_limit, plan = self.db.can_post_today(
            user_id,
            self.settings.free_posts_per_day,
            self.settings.pro_posts_per_day,
        )
        if not allowed_today:
            await self.tg.send_message(
                chat_id,
                _post_limit_message(plan, used_today, daily_limit),
                reply_markup=main_keyboard(),
            )
            return False
        try:
            if not await self.ensure_user_can_post_to_channel(chat_id, user_id, channel, service_message_id):
                return False
            product_url = pending["product_url"]
            sent = await self.tg.send_photo(
                channel["channel_id"],
                pending["image_url"],
                pending["caption"] or "",
                reply_markup=buy_keyboard(product_url),
            )
            message_id = sent.get("message_id")
            self.db.add_post(user_id, channel["channel_id"], product_url, product_url, "posted", message_id)
            self.db.add_rate_event(user_id, "post")
            self.db.delete_pending_post(pending_id, user_id)
            self.db.set_state(user_id, None)
            title = html.escape(channel["channel_title"] or channel["channel_id"])
            success = f"âœ… <b>Post publicado.</b>\n\nðŸ“£ Canal: {title}"
            if service_message_id:
                await self.tg.edit_message_text(chat_id, service_message_id, success, reply_markup=main_keyboard())
            else:
                await self.tg.send_message(chat_id, success, reply_markup=main_keyboard())
            return True
        except Exception as exc:
            log.exception("Falha ao publicar preview")
            self.db.add_post(user_id, channel["channel_id"], pending["product_url"], None, "error", error=str(exc))
            await self.tg.send_message(chat_id, _friendly_error(exc), reply_markup=main_keyboard())
            return False

    async def receive_edited_caption(self, chat_id: int, user_id: int, pending_id: int, text: str) -> None:
        if not pending_id:
            self.db.set_state(user_id, None)
            await self.tg.send_message(chat_id, "Nao encontrei o preview ativo. Envie o link novamente.", reply_markup=main_keyboard())
            return
        pending = self.db.get_pending_post(pending_id, user_id)
        if not pending:
            self.db.set_state(user_id, None)
            await self.tg.send_message(chat_id, "Esse preview expirou. Envie o link novamente.", reply_markup=main_keyboard())
            return
        safe_caption = _limit_caption(html.escape(text.strip()))
        self.db.update_pending_post(pending_id, user_id, caption=safe_caption)
        self.db.set_state(user_id, None)
        await self.publish_pending(chat_id, user_id, pending_id)

    async def extract_product_for_post(self, product_url: str) -> dict:
        produto = await _extrair_com_fallback(product_url, self.settings)
        produto["link"] = product_url
        return self.price_history.record_product(produto, source="multiuser")

    async def create_and_post(
        self,
        chat_id: int,
        user_id: int,
        product_url: str,
        channel: dict,
        service_message_id: int | None = None,
        edit_service: bool = False,
    ) -> bool:
        try:
            if not await self.ensure_user_can_post_to_channel(chat_id, user_id, channel, service_message_id):
                return False
            allowed_today, used_today, daily_limit, plan = self.db.can_post_today(
                user_id,
                self.settings.free_posts_per_day,
                self.settings.pro_posts_per_day,
            )
            if not allowed_today:
                await self.tg.send_message(
                    chat_id,
                    _post_limit_message(plan, used_today, daily_limit),
                    reply_markup=main_keyboard(),
                )
                return False

            produto = await self.extract_product_for_post(product_url)
            caption = await gerar_post(produto, self.settings)
            if not produto.get("imagem"):
                raise ValueError("Produto sem imagem confirmada; postagem bloqueada.")
            sent = await self.tg.send_photo(
                channel["channel_id"],
                produto["imagem"],
                caption,
                reply_markup=buy_keyboard(product_url),
            )
            message_id = sent.get("message_id")
            self.db.add_post(user_id, channel["channel_id"], product_url, product_url, "posted", message_id)
            title = html.escape(channel["channel_title"] or channel["channel_id"])
            success = f"✅ <b>Post publicado.</b>\n\n📣 Canal: {title}"
            if service_message_id and edit_service:
                await self.tg.edit_message_text(chat_id, service_message_id, success, reply_markup=main_keyboard())
            else:
                if service_message_id:
                    await self.tg.delete_message(chat_id, service_message_id)
                await self.tg.send_message(chat_id, success, reply_markup=main_keyboard())
            return True
        except Exception as exc:
            log.exception("Falha ao criar postagem")
            self.db.add_post(user_id, channel["channel_id"], product_url, None, "error", error=str(exc))
            error_text = (
                "⚠️ <b>Não consegui publicar esse produto.</b>\n\n"
                f"Confira se o link é de uma plataforma suportada: <b>{SUPPORTED_TEXT}</b>."
            )
            if service_message_id and edit_service:
                await self.tg.edit_message_text(chat_id, service_message_id, error_text, reply_markup=main_keyboard())
            else:
                if service_message_id:
                    await self.tg.delete_message(chat_id, service_message_id)
                await self.tg.send_message(chat_id, error_text, reply_markup=main_keyboard())
            return False

    async def ensure_user_can_post_to_channel(
        self,
        chat_id: int,
        user_id: int,
        channel: dict,
        service_message_id: int | None = None,
    ) -> bool:
        try:
            member = await self.tg.get_chat_member(channel["channel_id"], user_id)
        except Exception as exc:
            log.warning("Falha ao validar permissao do usuario no canal %s: %s", channel["channel_id"], exc)
            member = {}

        if _can_user_manage_channel(member):
            return True

        self.db.remove_channel(int(channel["id"]), user_id)
        text = (
            "⛔ <b>Postagem bloqueada por segurança.</b>\n\n"
            "Você não é administrador/criador desse canal, então removi ele da sua lista."
        )
        if service_message_id:
            await self.tg.edit_message_text(chat_id, service_message_id, text, reply_markup=main_keyboard())
        else:
            await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_status(self, chat_id: int, user_id: int) -> None:
        stats = self.db.user_post_stats(user_id)
        plan = self.db.get_user_plan(user_id)
        plan_label = _plan_label(plan)
        text = (
            "<b>Seu status</b>\n\n"
            f"Plano: <b>{plan_label}</b>\n"
            f"Canais ativos: <b>{stats['channels']}</b>\n"
            f"Posts publicados: <b>{stats['posts_total']}</b>\n"
            f"Publicados hoje: <b>{stats['posts_today']}</b>\n"
            f"Erros nos ultimos 7 dias: <b>{stats['errors_7d']}</b>"
        )
        await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_limits(self, chat_id: int, user_id: int) -> None:
        stats = self.db.user_post_stats(user_id)
        plan = self.db.get_user_plan(user_id)
        channel_limit = self._channel_limit_for_plan(str(plan["plan"]))
        post_limit = self._post_limit_for_plan(str(plan["plan"]))
        text = (
            "<b>Seus limites atuais</b>\n\n"
            f"Plano: <b>{_plan_label(plan)}</b>\n"
            f"Canais: <b>{stats['channels']}/{_limit_text(channel_limit)}</b>\n"
            f"Posts hoje: <b>{stats['posts_today']}/{_limit_text(post_limit)}</b>\n"
            f"Intervalo entre links: <b>{self.settings.user_post_cooldown_seconds}s</b>\n"
            f"Posts por hora: <b>{self.settings.user_posts_per_hour}</b>\n\n"
            "Comandos uteis: /status, /planos, /meus_posts, /ajuda"
        )
        await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_plans(self, chat_id: int, user_id: int) -> None:
        plan = self.db.get_user_plan(user_id)
        current = _plan_label(plan)
        free_channels = _limit_text(self.settings.free_max_channels)
        free_posts = _limit_text(self.settings.free_posts_per_day)
        pro_channels = _limit_text(self.settings.pro_max_channels)
        pro_posts = _limit_text(self.settings.pro_posts_per_day)
        text = (
            "<b>Planos</b>\n\n"
            f"Seu plano atual: <b>{current}</b>\n\n"
            f"<b>Free</b>\n"
            f"- Canais: <b>{free_channels}</b>\n"
            f"- Posts por dia: <b>{free_posts}</b>\n\n"
            f"<b>Pro</b>\n"
            f"- Canais: <b>{pro_channels}</b>\n"
            f"- Posts por dia: <b>{pro_posts}</b>\n"
            "- Ideal para operar varios canais com mais volume.\n\n"
            "Para ativar Pro, fale com o administrador do bot."
        )
        await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def monitor_command(self, chat_id: int, user_id: int, text: str) -> None:
        parts = text.split()
        if len(parts) < 2:
            await self.tg.send_message(
                chat_id,
                "Uso: <code>/monitorar LINK PRECO</code>\n"
                "Exemplo: <code>/monitorar https://produto.com 199.90</code>\n"
                "Para avisar qualquer queda: <code>/monitorar LINK queda</code>",
                reply_markup=main_keyboard(),
            )
            return
        product_url = parts[1].strip()
        if not _is_valid_product_url(product_url):
            await self.tg.send_message(chat_id, f"Link nao reconhecido. Envie URLs de: <b>{SUPPORTED_TEXT}</b>.")
            return
        target_price = None
        notify_any_drop = len(parts) >= 3 and parts[2].strip().lower() in {"queda", "qualquer", "any"}
        if len(parts) >= 3 and not notify_any_drop:
            target_price = _parse_money(parts[2])
            if target_price is None or target_price <= 0:
                await self.tg.send_message(chat_id, "Preco alvo invalido. Use algo como <code>199.90</code>.")
                return
        elif not notify_any_drop:
            await self.tg.send_message(chat_id, "Informe um preco alvo ou use <code>queda</code>.")
            return
        if not self._can_create_alert(user_id):
            await self.tg.send_message(chat_id, self._alert_limit_message(user_id), reply_markup=main_keyboard())
            return
        try:
            alert = await self.alerts.add_alert(user_id, product_url, target_price, notify_any_drop)
            target = "qualquer queda" if notify_any_drop else f"R$ {target_price:.2f}"
            await self.tg.send_message(
                chat_id,
                "<b>Alerta criado.</b>\n\n"
                f"{html.escape(str(alert.get('title') or product_url))}\n"
                f"Preco atual: <b>R$ {float(alert.get('current_price') or 0):.2f}</b>\n"
                f"Alvo: <b>{target}</b>",
                reply_markup=main_keyboard(),
            )
        except Exception as exc:
            log.warning("Falha ao criar alerta de preco: %s", exc)
            await self.tg.send_message(chat_id, _friendly_error(exc), reply_markup=main_keyboard())

    async def create_alert_from_pending(
        self,
        chat_id: int,
        user_id: int,
        pending_id: int,
        message_id: int | None,
    ) -> None:
        pending = self.db.get_pending_post(pending_id, user_id)
        if not pending:
            await self.tg.send_message(chat_id, "Preview expirou. Envie o link novamente.", reply_markup=main_keyboard())
            return
        if not self._can_create_alert(user_id):
            await self.tg.send_message(chat_id, self._alert_limit_message(user_id), reply_markup=main_keyboard())
            return
        product = self.db.pending_product(pending)
        current = _parse_money(str(product.get("preco_atual") or "0")) or 0.0
        target = round(current * 0.95, 2) if current > 0 else None
        alert = await self.alerts.add_alert(user_id, pending["product_url"], target, notify_any_drop=True)
        text = (
            "<b>Alerta criado.</b>\n\n"
            f"{html.escape(str(alert.get('title') or pending['product_url']))}\n"
            "Vou te avisar quando houver queda de preco."
        )
        if message_id:
            await self.tg.edit_message_text(chat_id, message_id, text, reply_markup=main_keyboard())
        else:
            await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_alerts(self, chat_id: int, user_id: int) -> None:
        alerts = await self.alerts.list_alerts(user_id)
        if not alerts:
            await self.tg.send_message(chat_id, "Voce nao tem alertas ativos.", reply_markup=main_keyboard())
            return
        lines = ["<b>Seus alertas ativos</b>", ""]
        rows = []
        for alert in alerts[:10]:
            title = html.escape(str(alert.get("product_title") or alert.get("product_url")))
            current = float(alert.get("current_price") or 0)
            target = float(alert.get("target_price") or 0)
            goal = "qualquer queda" if int(alert.get("notify_any_drop") or 0) else f"R$ {target:.2f}"
            lines.append(f"- <b>{title[:80]}</b>")
            lines.append(f"  Atual: R$ {current:.2f} | Alvo: {goal}")
            rows.append([(f"Cancelar #{alert['id']}", f"cancelalert:{alert['id']}")])
        rows.append([("Voltar", "start:home")])
        await self.tg.send_message(chat_id, "\n".join(lines), reply_markup=keyboard(rows))

    async def offer_request_command(self, chat_id: int, user_id: int, text: str) -> None:
        term = text.replace("/pedir", "", 1).strip()
        if len(term) < 2:
            await self.tg.send_message(chat_id, "Uso: <code>/pedir air fryer</code>", reply_markup=main_keyboard())
            return
        clean = html.escape(term[:80])
        self.db.add_offer_request(user_id, term[:80])
        count = self.db.count_offer_requests(term[:80], days=7)
        await self.tg.send_message(
            chat_id,
            "<b>Pedido registrado.</b>\n\n"
            f"Termo: <b>{clean}</b>\n"
            f"Pedidos parecidos esta semana: <b>{count}</b>",
            reply_markup=main_keyboard(),
        )

    async def activate_code_command(self, chat_id: int, user_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await self.tg.send_message(chat_id, "Uso: <code>/ativar CODIGO</code>", reply_markup=main_keyboard())
            return
        result = self.db.redeem_activation_code(user_id, parts[1])
        if not result:
            await self.tg.send_message(chat_id, "Codigo invalido ou ja usado.", reply_markup=main_keyboard())
            return
        await self.tg.send_message(
            chat_id,
            f"Plano <b>{html.escape(result['plan']).upper()}</b> ativado por "
            f"<b>{result['duration_days']}</b> dias.",
            reply_markup=main_keyboard(),
        )

    async def config_command(self, chat_id: int, user_id: int, text: str) -> None:
        if not await self._require_admin(chat_id, user_id):
            return
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            keys = ", ".join(sorted(self.config_manager.EDITABLE_KEYS))
            await self.tg.send_message(
                chat_id,
                "Uso: <code>/config CHAVE VALOR</code>\n\n"
                f"Chaves: <code>{html.escape(keys)}</code>",
                reply_markup=main_keyboard(),
            )
            return
        try:
            result = self.config_manager.apply(self.settings, parts[1], parts[2])
            await self.tg.send_message(chat_id, html.escape(result), reply_markup=main_keyboard())
        except Exception as exc:
            await self.tg.send_message(chat_id, f"Nao consegui aplicar: {html.escape(str(exc))}", reply_markup=main_keyboard())

    async def send_support(self, chat_id: int) -> None:
        await self.tg.send_message(
            chat_id,
            "<b>Suporte</b>\n\n"
            "Envie uma descricao curta do problema para o administrador do bot.\n"
            "Inclua o link do produto, canal usado e horario aproximado.",
            reply_markup=main_keyboard(),
        )

    async def send_recent_posts(self, chat_id: int, user_id: int) -> None:
        posts = self.db.recent_posts(user_id, limit=5)
        if not posts:
            await self.tg.send_message(chat_id, "Voce ainda nao tem posts registrados.", reply_markup=main_keyboard())
            return
        lines = ["<b>Seus ultimos posts</b>", ""]
        for post in posts:
            status = "publicado" if post["status"] == "posted" else "erro"
            channel = html.escape(str(post["channel_id"]))
            url = html.escape(str(post["product_url"]))
            lines.append(f"- <b>{status}</b> em {channel}")
            lines.append(f"  {url}")
        await self.tg.send_message(chat_id, "\n".join(lines), reply_markup=main_keyboard())

    async def send_health(self, chat_id: int, user_id: int) -> None:
        if not self._is_admin(user_id):
            await self.tg.send_message(chat_id, "Comando disponivel apenas para admin.", reply_markup=main_keyboard())
            return
        report = basic_health(self.settings, self.db)
        await self.tg.send_message(chat_id, format_health_report(report), reply_markup=main_keyboard())
        return False

    async def send_admin(self, chat_id: int, user_id: int) -> None:
        if not await self._require_admin(chat_id, user_id):
            return
        text = (
            "<b>Admin</b>\n\n"
            "/stats - resumo global\n"
            "/usuarios - ultimos usuarios\n"
            "/ativar_pro USER_ID DIAS - ativa Pro\n"
            "/desativar_pro USER_ID - volta para Free\n"
            "/health - checagem basica"
        )
        await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_admin_stats(self, chat_id: int, user_id: int) -> None:
        if not await self._require_admin(chat_id, user_id):
            return
        stats = self.db.admin_stats()
        text = (
            "<b>Stats globais</b>\n\n"
            f"Usuarios: <b>{stats['users']}</b>\n"
            f"Usuarios Pro ativos: <b>{stats['pro_users']}</b>\n"
            f"Canais: <b>{stats['channels']}</b>\n"
            f"Posts publicados: <b>{stats['posts_total']}</b>\n"
            f"Posts hoje: <b>{stats['posts_today']}</b>\n"
            f"Erros em 7 dias: <b>{stats['errors_7d']}</b>"
        )
        await self.tg.send_message(chat_id, text, reply_markup=main_keyboard())

    async def send_admin_users(self, chat_id: int, user_id: int) -> None:
        if not await self._require_admin(chat_id, user_id):
            return
        users = self.db.admin_user_summary(limit=10)
        if not users:
            await self.tg.send_message(chat_id, "Nenhum usuario registrado ainda.", reply_markup=main_keyboard())
            return
        lines = ["<b>Ultimos usuarios</b>", ""]
        now = time()
        for row in users:
            expires_at = float(row["plan_expires_at"] or 0)
            plan = str(row["plan"] or "free")
            if plan == "pro" and expires_at > 0 and expires_at <= now:
                plan = "free"
            username = f"@{row['username']}" if row["username"] else html.escape(row["first_name"] or "")
            label = username or str(row["telegram_user_id"])
            lines.append(
                f"- <code>{row['telegram_user_id']}</code> {html.escape(label)} | "
                f"<b>{plan}</b> | canais {row['channels']} | posts {row['posts_total']}"
            )
        await self.tg.send_message(chat_id, "\n".join(lines), reply_markup=main_keyboard())

    async def activate_pro_command(self, chat_id: int, admin_id: int, text: str) -> None:
        if not await self._require_admin(chat_id, admin_id):
            return
        parts = text.split()
        if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
            await self.tg.send_message(chat_id, "Uso: <code>/ativar_pro USER_ID DIAS</code>", reply_markup=main_keyboard())
            return
        target_id = int(parts[1])
        days = max(1, int(parts[2]))
        expires_at = time() + days * 86400
        self.db.set_user_plan(target_id, "pro", expires_at, changed_by=admin_id)
        await self.tg.send_message(
            chat_id,
            f"Pro ativado para <code>{target_id}</code> por <b>{days}</b> dias.",
            reply_markup=main_keyboard(),
        )

    async def deactivate_pro_command(self, chat_id: int, admin_id: int, text: str) -> None:
        if not await self._require_admin(chat_id, admin_id):
            return
        parts = text.split()
        if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
            await self.tg.send_message(chat_id, "Uso: <code>/desativar_pro USER_ID</code>", reply_markup=main_keyboard())
            return
        target_id = int(parts[1])
        self.db.set_user_plan(target_id, "free", None, changed_by=admin_id)
        await self.tg.send_message(
            chat_id,
            f"Usuario <code>{target_id}</code> voltou para o plano Free.",
            reply_markup=main_keyboard(),
        )

    async def _require_admin(self, chat_id: int, user_id: int) -> bool:
        if self._is_admin(user_id):
            return True
        await self.tg.send_message(chat_id, "Comando disponivel apenas para admin.", reply_markup=main_keyboard())
        return False

    def _is_admin(self, user_id: int) -> bool:
        return bool(
            (self.settings.admin_telegram_id and user_id == self.settings.admin_telegram_id)
            or (self.settings.owner_telegram_id and user_id == self.settings.owner_telegram_id)
        )

    def _channel_limit_for_plan(self, plan: str) -> int:
        return self.settings.pro_max_channels if plan == "pro" else self.settings.free_max_channels

    def _post_limit_for_plan(self, plan: str) -> int:
        return self.settings.pro_posts_per_day if plan == "pro" else self.settings.free_posts_per_day

    def _alert_limit_for_plan(self, plan: str) -> int:
        return self.settings.max_alerts_pro if plan == "pro" else self.settings.max_alerts_free

    def _can_create_alert(self, user_id: int) -> bool:
        plan = str(self.db.get_user_plan(user_id)["plan"])
        limit = self._alert_limit_for_plan(plan)
        return limit <= 0 or self.db.active_price_alert_count(user_id) < limit

    def _alert_limit_message(self, user_id: int) -> str:
        plan = str(self.db.get_user_plan(user_id)["plan"])
        limit = self._alert_limit_for_plan(plan)
        return (
            f"Seu plano <b>{html.escape(plan)}</b> permite <b>{_limit_text(limit)}</b> alertas ativos.\n\n"
            "Cancele um alerta em /meus_alertas ou peca ativacao Pro."
        )

    def extract_url(self, text: str) -> str | None:
        match = URL_RE.search(text)
        return match.group(0).strip().rstrip(")].,;!") if match else None

    def _check_link_rate_limit(self, user_id: int) -> tuple[bool, int]:
        cooldown = max(0, int(self.settings.user_post_cooldown_seconds or 0))
        if cooldown <= 0:
            return True, 0
        if self.db.count_rate_events(user_id, "link", time() - cooldown) <= 0:
            return True, 0
        return False, cooldown

    def _check_post_rate_limit(self, user_id: int) -> tuple[bool, int]:
        limit = max(1, int(self.settings.user_posts_per_hour or 20))
        if self.db.count_rate_events(user_id, "post", time() - 3600) < limit:
            return True, 0
        return False, 60


def main_keyboard() -> dict:
    return keyboard(
        [
            [("➕ Cadastrar canal", "start:register"), ("📣 Meus canais", "start:channels")],
            [("❔ Como usar", "start:help")],
        ]
    )


def preview_keyboard(pending_id: int) -> dict:
    return keyboard(
        [
            [("Publicar", f"preview:publish:{pending_id}"), ("Editar texto", f"preview:edit:{pending_id}")],
            [("Gerar outra copy", f"preview:regen:{pending_id}"), ("Cancelar", f"preview:cancel:{pending_id}")],
            [("Monitorar preco", f"preview:watch:{pending_id}")],
        ]
    )


def buy_keyboard(link: str) -> dict:
    return {"inline_keyboard": [[{"text": "🛒 Comprar agora", "url": link}]]}


def _limit_text(limit: int) -> str:
    return "ilimitado" if limit <= 0 else str(limit)


def _plan_label(plan: dict[str, object]) -> str:
    name = str(plan.get("plan") or "free").upper()
    expires_at = float(plan.get("expires_at") or 0)
    if name == "PRO" and expires_at > 0:
        return f"PRO ate {_format_ts(expires_at)}"
    return name


def _format_ts(timestamp: float) -> str:
    return strftime("%d/%m/%Y", localtime(timestamp))


def _channel_limit_message(plan: str, count: int, limit: int) -> str:
    return (
        f"Seu plano <b>{html.escape(plan)}</b> permite <b>{_limit_text(limit)}</b> canal(is).\n\n"
        f"Voce ja tem <b>{count}</b> cadastrado(s). Remova um canal ou peça ativacao Pro ao admin."
    )


def _post_limit_message(plan: str, count: int, limit: int) -> str:
    return (
        f"Seu plano <b>{html.escape(plan)}</b> permite <b>{_limit_text(limit)}</b> posts por dia.\n\n"
        f"Voce ja publicou <b>{count}</b> hoje. Tente novamente amanha ou peça ativacao Pro ao admin."
    )


def _preview_caption(caption: str) -> str:
    return _limit_caption(f"<b>Preview do post:</b>\n\n{caption}")


def _limit_caption(text: str, max_len: int = 1000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip()


def _is_valid_product_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and bool(detect_platform(url))


async def _extrair_com_fallback(product_url: str, settings: Settings) -> dict:
    """
    Tenta extrair o produto em camadas:
    1. HTTP simples, rapido para ML e Magalu.
    2. HTTP com headers de browser, melhor para Amazon.
    3. Playwright headless, melhor para paginas com JS.
    """
    platform = detect_platform(product_url)
    timeout = settings.request_timeout
    needs_browser = {"shopee", "shein", "aliexpress"}

    if platform not in needs_browser:
        try:
            produto = await extrair_produto(product_url, timeout, use_browser=False, strict=False)
            if _produto_valido(produto):
                return produto
        except Exception as exc:
            log.info("Extracao HTTP simples falhou para %s: %s", platform or "unknown", exc)

    try:
        produto = await _extrair_com_headers_reais(product_url, timeout)
        if _produto_valido(produto):
            return produto
    except Exception as exc:
        log.info("Extracao com headers reais falhou para %s: %s", platform or "unknown", exc)

    if settings.multiuser_browser_fallback:
        try:
            async with _BROWSER_FALLBACK_SEMAPHORE:
                produto = await extrair_produto(
                    product_url,
                    max(timeout, 45),
                    use_browser=True,
                    strict=False,
                )
            if _produto_valido(produto):
                return produto
        except Exception as exc:
            log.warning("Browser headless falhou para %s: %s", platform or product_url, exc)
        if settings.panel_cdp_url:
            try:
                async with _BROWSER_FALLBACK_SEMAPHORE:
                    produto = await extrair_produto(
                        product_url,
                        max(timeout, 45),
                        use_browser=True,
                        strict=False,
                        cdp_url=settings.panel_cdp_url,
                    )
                if _produto_valido(produto):
                    return produto
            except Exception as exc:
                log.warning("Browser CDP falhou para %s: %s", platform or product_url, exc)

    raise ValueError(_erro_extracao(platform))


def _produto_valido(produto: dict) -> bool:
    titulo = str(produto.get("titulo") or "").strip()
    imagem = str(produto.get("imagem") or "").strip()
    preco = _parse_money(str(produto.get("preco_atual") or "0")) or 0.0
    if not titulo or titulo.lower() in {"oferta selecionada", "produto selecionado", "produto"}:
        return False
    if not imagem or _looks_like_placeholder_image(imagem):
        return False
    return preco > 0


def _looks_like_placeholder_image(url: str) -> bool:
    lowered = (url or "").lower()
    return any(
        bit in lowered
        for bit in (
            "logo",
            "placeholder",
            "sprite",
            "icon",
            "favicon",
            "shopee-logo",
            "brand",
        )
    )


async def _extrair_com_headers_reais(product_url: str, timeout: float) -> dict:
    from product_extractor import _extract_from_html

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = await client.get(product_url)
        resp.raise_for_status()
        final_url = str(resp.url)
        platform = detect_platform(final_url) or detect_platform(product_url) or "unknown"
        produto = _extract_from_html(final_url, resp.text, platform)
        produto["link"] = product_url
        produto["link_original"] = product_url
        produto["source_url"] = final_url
        produto["platform"] = platform
        return produto


PLATFORM_TIPS = {
    "shopee": (
        "Shopee as vezes bloqueia a extracao automatica.\n\n"
        "Tente:\n"
        "- Abrir o produto no app/site e copiar o link da barra de enderecos\n"
        "- Evitar links encurtados como s.shopee.com.br\n"
        "- Usar o link completo do produto"
    ),
    "amazon": (
        "Nao consegui extrair dados da Amazon.\n\n"
        "Tente:\n"
        "- Usar o link completo do produto, tipo amazon.com.br/dp/...\n"
        "- Evitar links de busca, lista ou recomendacao"
    ),
    "shein": (
        "Shein bloqueia extracao automatica com frequencia.\n\n"
        "Tente o link direto do produto no formato shein.com.br/...-p-XXXXXX.html"
    ),
    "aliexpress": (
        "AliExpress pode bloquear extracao.\n\n"
        "Tente o link direto do produto: aliexpress.com/item/XXXXXX.html"
    ),
}


def _erro_extracao(platform: str | None) -> str:
    if platform and platform in PLATFORM_TIPS:
        return PLATFORM_TIPS[platform]
    return "Nao consegui extrair os dados deste produto. Tente o link direto da pagina do produto."


def _parse_money(value: str) -> float | None:
    cleaned = value.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _telegram_post_link(channel: dict, message_id: int | None) -> str | None:
    if not message_id:
        return None
    username = channel.get("channel_username")
    if username:
        return f"https://t.me/{str(username).lstrip('@')}/{message_id}"
    channel_id = str(channel.get("channel_id") or "")
    if channel_id.startswith("-100"):
        return f"https://t.me/c/{channel_id[4:]}/{message_id}"
    return None


def _friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "imagem" in text:
        return "Nao encontrei imagem neste produto. Tente outro link ou uma URL direta da pagina do produto."
    if "timeout" in text or "timed out" in text:
        return "O site demorou demais para responder. Tente novamente em instantes."
    return f"Nao consegui publicar esse produto.\n\nConfira se o link e de uma plataforma suportada: <b>{SUPPORTED_TEXT}</b>."


def _can_user_manage_channel(member: dict | None) -> bool:
    if not member:
        return False
    status = member.get("status")
    if status == "creator":
        return True
    if status != "administrator":
        return False
    return bool(
        member.get("can_post_messages")
        or member.get("can_manage_chat")
        or member.get("can_promote_members")
        or member.get("can_change_info")
    )


async def main() -> None:
    setup_logging()
    bot = MultiUserBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
