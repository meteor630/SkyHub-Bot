"""Плагин ``tickets``: система обращений (ТЗ §41, "Support / Tickets") --
каждое обращение -- отдельный приватный канал, создаваемый по кнопке.

Кнопки (панель создания и "закрыть") регистрируются как персистентные
через ``bot.add_view()`` -- они продолжают отвечать на нажатия даже
после перезапуска бота, без необходимости заново публиковать панель.
"""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.tickets.commands import build_ticket_cog
from plugins.tickets.views import TicketControlView, TicketPanelView


class TicketsPlugin(BasePlugin):
    meta = PluginMeta(
        name="tickets", version="1.0.0",
        description="/ticket panel|close -- приватные каналы обращений в поддержку",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_ticket_cog(self.ctx))
        # Персистентные View не завязаны на конкретное сообщение -- их
        # можно (и нужно) регистрировать один раз при загрузке плагина,
        # ещё до того, как бот подключился к шлюзу.
        self.ctx.bot.add_view(TicketPanelView(self.ctx))
        self.ctx.bot.add_view(TicketControlView(self.ctx))
        self.log.info("tickets готов к работе")


PLUGIN_CLASS = TicketsPlugin
