"""Плагин ``aviation_profile``: авиационные роли и "система контекста
пользователя" (ТЗ §41, финальная заметка клиента) -- участник указывает,
кто он (Pilot/ATC/...), на каком симуляторе и в какой сети летает.

Роль Discord, если она настроена через ``/setup profile-roles``, ставится
автоматически при сохранении профиля -- никакой ручной работы для
модераторов. Другие плагины (например, ``server_stats``) читают эти
данные напрямую из БД, а не через прямой импорт этого плагина.
"""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.aviation_profile.commands import build_profile_cog


class AviationProfilePlugin(BasePlugin):
    meta = PluginMeta(
        name="aviation_profile", version="1.0.0",
        description="/profile -- авиационная роль/симулятор/сеть участника, с автовыдачей роли Discord",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_profile_cog(self.ctx))
        self.log.info("aviation_profile готов к работе")


PLUGIN_CLASS = AviationProfilePlugin
