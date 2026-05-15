"""Minimal Telegram Bot API client."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str, timeout: float = 30) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def call(self, method: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        request_timeout = timeout or self.timeout
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.post(
                    f"{self.base_url}/{method}",
                    json=payload or {},
                    timeout=request_timeout,
                )
                data = resp.json()
                if resp.status_code == 429:
                    retry_after = int((data.get("parameters") or {}).get("retry_after") or 1)
                    await asyncio.sleep(min(retry_after, 30))
                    continue
                if resp.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram {method} falhou: {data}")
                return data["result"]
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
        raise RuntimeError(f"Telegram {method} falhou apos retries") from last_exc

    async def call_multipart(
        self,
        method: str,
        data: dict,
        files: dict,
        timeout: float | None = None,
    ) -> dict:
        request_timeout = timeout or self.timeout
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.post(
                    f"{self.base_url}/{method}",
                    data=data,
                    files=files,
                    timeout=request_timeout,
                )
                payload = resp.json()
                if resp.status_code == 429:
                    retry_after = int((payload.get("parameters") or {}).get("retry_after") or 1)
                    await asyncio.sleep(min(retry_after, 30))
                    continue
                if resp.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                if not payload.get("ok"):
                    raise RuntimeError(f"Telegram {method} falhou: {payload}")
                return payload["result"]
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
        raise RuntimeError(f"Telegram {method} falhou apos retries") from last_exc

    async def close(self) -> None:
        await self._client.aclose()

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
        disable_notification: bool = False,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
            "disable_notification": disable_notification,
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

    async def edit_message_caption(
        self,
        chat_id: int | str,
        message_id: int,
        caption: str,
        reply_markup: dict | None = None,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "HTML",
            "show_caption_above_media": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageCaption", payload)

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
        disable_notification: bool = False,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "parse_mode": "HTML",
            "show_caption_above_media": False,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        local_photo = _local_file(photo)
        if local_photo:
            data = {
                key: json.dumps(value) if key == "reply_markup" else str(value)
                for key, value in payload.items()
                if key != "photo"
            }
            with local_photo.open("rb") as file_obj:
                return await self.call_multipart(
                    "sendPhoto",
                    data=data,
                    files={"photo": (local_photo.name, file_obj, "image/png")},
                )
        return await self.call("sendPhoto", payload)

    async def send_media_group(self, chat_id: int | str, media: list[dict]) -> list[dict]:
        return await self.call("sendMediaGroup", {"chat_id": chat_id, "media": media})

    async def send_poll(
        self,
        chat_id: int | str,
        question: str,
        options: list[str],
        **kwargs,
    ) -> dict:
        payload = {"chat_id": chat_id, "question": question, "options": options}
        payload.update(kwargs)
        return await self.call("sendPoll", payload)

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


def _local_file(value: str) -> Path | None:
    if value.startswith(("http://", "https://")):
        return None
    path = Path(value)
    if path.exists() and path.is_file():
        return path
    return None
