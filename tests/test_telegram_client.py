import asyncio

from telegram_client import TelegramClient


class FakeResponse:
    def __init__(self, status_code: int, data: dict) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(429, {"ok": False, "parameters": {"retry_after": 0}})
        return FakeResponse(200, {"ok": True, "result": {"message_id": 10}})

    async def aclose(self) -> None:
        return None


def test_telegram_client_retries_429(monkeypatch) -> None:
    client = TelegramClient("token", timeout=1)
    fake = FakeHttpClient()
    client._client = fake

    async def fake_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("telegram_client.asyncio.sleep", fake_sleep)

    result = asyncio.run(client.call("sendMessage", {"chat_id": 1, "text": "ok"}))

    assert result["message_id"] == 10
    assert fake.calls == 2
