"""Multi-user Telegram bot for affiliate channel posting."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import sys

import httpx

from ai_generator import gerar_post_fallback
from config import load_settings
from product_extractor import extrair_produto
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
    def __init__(self) -> None:
        self.settings = load_settings()
        if not self.settings.telegram_bot_token:
            raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no .env.")
        self.tg = TelegramClient(self.settings.telegram_bot_token, self.settings.request_timeout)
        self.db = Storage()
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
        state, _ = self.db.get_state(user_id)

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

        if state == "awaiting_channel":
            await self.register_channel(chat["id"], user_id, text)
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
            ok = await self.create_and_post(chat_id, user_id, pending["product_url"], channel, service_message_id=message_id, edit_service=True)
            self.db.delete_pending_post(int(pending_id), user_id)
            if ok:
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
            await self.create_and_post(chat_id, user_id, product_url, channels[0], service_message_id=service.get("message_id"))
            return

        pending_id = self.db.add_pending_post(user_id, product_url)
        rows = [[(channel["channel_title"] or channel["channel_id"], f"post:{pending_id}:{channel['id']}")] for channel in channels]
        rows.append([("❌ Cancelar", f"postcancel:{pending_id}")])
        await self.tg.send_message(
            chat_id,
            "📣 <b>Em qual canal devo postar?</b>",
            reply_markup=keyboard(rows),
        )

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

            try:
                produto = await extrair_produto(
                    product_url,
                    self.settings.request_timeout,
                    use_browser=False,
                    strict=False,
                )
            except Exception as public_exc:
                if not self.settings.multiuser_browser_fallback:
                    raise public_exc
                log.info("Extracao publica falhou; tentando fallback controlado com navegador: %s", public_exc)
                async with _BROWSER_FALLBACK_SEMAPHORE:
                    produto = await extrair_produto(
                        product_url,
                        self.settings.request_timeout,
                        use_browser=True,
                        strict=False,
                    )
            produto["link"] = product_url
            caption = gerar_post_fallback(produto)
            if not produto.get("imagem"):
                raise ValueError("Produto sem imagem confirmada; postagem bloqueada.")
            sent = await self.tg.send_photo(channel["channel_id"], produto["imagem"], caption)
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
        return False

    def extract_url(self, text: str) -> str | None:
        match = URL_RE.search(text)
        return match.group(0).strip().rstrip(")].,;!") if match else None


def main_keyboard() -> dict:
    return keyboard(
        [
            [("➕ Cadastrar canal", "start:register"), ("📣 Meus canais", "start:channels")],
            [("❔ Como usar", "start:help")],
        ]
    )


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
