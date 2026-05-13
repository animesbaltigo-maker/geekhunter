"""Minimal Telegram Bot API client."""

from __future__ import annotations

import httpx


class TelegramClient:
    def __init__(self, token: str, timeout: float = 30) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    async def call(self, method: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
            resp = await client.post(f"{self.base_url}/{method}", json=payload or {})
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {method} falhou: {data}")
            return data["result"]

    async def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        payload = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query", "my_chat_member"],
        }
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload, timeout=timeout + 15)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageText", payload)

    async def delete_message(self, chat_id: int | str, message_id: int) -> bool:
        try:
            return bool(await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id}))
        except Exception:
            return False

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await self.call("answerCallbackQuery", payload, timeout=10)

    async def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        caption: str,
        reply_markup: dict | None = None,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "parse_mode": "HTML",
            "show_caption_above_media": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendPhoto", payload)

    async def get_chat(self, chat_id: int | str) -> dict:
        return await self.call("getChat", {"chat_id": chat_id})

    async def get_chat_member(self, chat_id: int | str, user_id: int) -> dict:
        return await self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def get_me(self) -> dict:
        return await self.call("getMe")


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": data} for text, data in row]
            for row in rows
        ]
    }
