"""Точка входа плагина Message Builder (ТЗ §6-10)."""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.message_builder.commands import build_message_builder_cog


class MessageBuilderPlugin(BasePlugin):
    meta = PluginMeta(
        name="message_builder",
        version="1.0.0",
        description="Красиво оформленные фирменные сообщения Discord: /message, /embed, /announce, /message_template",
        dependencies=(),
        requires_db=False,
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_message_builder_cog(self.ctx))
        self.log.info("message_builder готов к работе")


PLUGIN_CLASS = MessageBuilderPlugin
