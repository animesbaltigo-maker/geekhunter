import asyncio

import pytest

from multiuser_bot import MultiUserBot


class FakeStorage:
    def upsert_user(self, user: dict) -> None:
        self.user = user

    def get_state(self, user_id: int):
        return None, {}

    def set_state(self, user_id: int, state: str | None, data: dict | None = None) -> None:
        self.state = state


@pytest.mark.parametrize(
    ("command", "method"),
    [
        ("/start", "send_start"),
        ("/cadastrar_canal", "ask_channel"),
        ("/meus_canais", "show_channels"),
        ("/remover_canal", "show_remove_channels"),
        ("/ajuda", "send_help"),
        ("/planos", "send_plans"),
        ("/admin", "send_admin"),
        ("/usuarios", "send_admin_users"),
        ("/ativar_pro 123 30", "activate_pro_command"),
        ("/desativar_pro 123", "deactivate_pro_command"),
        ("/stats", "send_admin_stats"),
        ("/status", "send_status"),
        ("/limites", "send_limits"),
        ("/historico", "send_recent_posts"),
        ("/meus_posts", "send_recent_posts"),
        ("/monitorar https://www.amazon.com.br/Echo-Pop-Cor-Preta/dp/B09WXVH7WK 200", "monitor_command"),
        ("/meus_alertas", "send_alerts"),
        ("/pedir air fryer", "offer_request_command"),
        ("/ativar CODIGO", "activate_code_command"),
        ("/config posts_por_rodada 2", "config_command"),
        ("/suporte", "send_support"),
        ("/health", "send_health"),
    ],
)
def test_command_routes(command: str, method: str) -> None:
    bot = object.__new__(MultiUserBot)
    bot.db = FakeStorage()
    bot._is_admin = lambda user_id: True
    called = []

    async def recorder(*args, **kwargs):
        called.append(method)

    for name in {
        "send_start",
        "ask_channel",
        "show_channels",
        "show_remove_channels",
        "send_help",
        "send_plans",
        "send_admin",
        "send_admin_users",
        "activate_pro_command",
        "deactivate_pro_command",
        "send_admin_stats",
        "send_status",
        "send_limits",
        "send_recent_posts",
        "monitor_command",
        "send_alerts",
        "offer_request_command",
        "activate_code_command",
        "config_command",
        "send_support",
        "send_health",
    }:
        setattr(bot, name, recorder if name == method else _unused)

    asyncio.run(
        bot.handle_message({"chat": {"id": 1, "type": "private"}, "from": {"id": 1852596083}, "text": command})
    )

    assert called == [method]


async def _unused(*args, **kwargs):
    raise AssertionError("wrong command handler called")
