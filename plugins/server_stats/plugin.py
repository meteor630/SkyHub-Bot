"""Плагин ``server_stats``: ``/server stats`` (ТЗ §41, "/server статистика").

Зависит от ``aviation_profile`` только на уровне импорта словаря подписей
ролей (``ROLE_TYPE_LABELS``); данные читает напрямую из БД, поэтому
формально жёсткой зависимости в ``PluginMeta.dependencies`` не объявляем --
плагин просто покажет пустой список профилей, если ``aviation_profile``
выключен."""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.server_stats.commands import build_server_stats_cog


class ServerStatsPlugin(BasePlugin):
    meta = PluginMeta(
        name="server_stats", version="1.0.0",
        description="/server stats -- сводная статистика сервера",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_server_stats_cog(self.ctx))
        self.log.info("server_stats готов к работе")


PLUGIN_CLASS = ServerStatsPlugin
