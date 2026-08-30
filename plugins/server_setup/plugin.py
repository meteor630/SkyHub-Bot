"""Плагин ``server_setup``: конфигуратор сервера ``/setup`` (идея клиента №1)."""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.server_setup.commands import build_server_setup_cog


class ServerSetupPlugin(BasePlugin):
    meta = PluginMeta(
        name="server_setup", version="1.0.0",
        description="/setup -- настройка каналов и ролей полностью из Discord",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_server_setup_cog(self.ctx))
        self.log.info("server_setup готов к работе")


PLUGIN_CLASS = ServerSetupPlugin
