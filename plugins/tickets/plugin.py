"""Плагин ``tickets``: система обращений (ТЗ §41, "Support / Tickets") --
у каждого обращения приватный канал для автора и, если настроен форум
(``/setup tickets-forum``, см. ``plugins/tickets/forum.py``), пост в
приватном форуме для сапорта; ``plugins/tickets/bridge.py`` зеркалит
сообщения между ними.

Кнопки (панель создания и "закрыть") регистрируются как персистентные
через ``bot.add_view()`` -- они продолжают отвечать на нажатия даже
после перезапуска бота, без необходимости заново публиковать панель.

Закрытый тикет больше не удаляется сразу (переписка остаётся видна
сапорту), а автоматически удаляется -- канал и пост форума -- спустя
``TICKET_PURGE_AFTER_DAYS`` дней после закрытия (клиентский запрос:
"открытые сверху, закрытые снизу [это Discord и так делает сам для
активных/архивных постов форума], а сами закрытые -- удалять через месяц").
"""
from __future__ import annotations

import asyncio
import datetime as dt

import discord

from core.base_plugin import BasePlugin, PluginMeta
from database.repositories.ticket_repository import TicketRepository
from plugins.tickets.bridge import build_ticket_bridge_cog
from plugins.tickets.commands import build_ticket_cog
from plugins.tickets.views import TicketControlView, TicketPanelView

# Раз в 6 часов вполне достаточно -- тикетов закрывается не так много,
# чтобы гнаться за секундной точностью автоудаления через месяц.
PURGE_CHECK_INTERVAL_SECONDS = 6 * 3600
TICKET_PURGE_AFTER_DAYS = 30


class TicketsPlugin(BasePlugin):
    meta = PluginMeta(
        name="tickets", version="1.1.0",
        description="/ticket panel|close -- приватные каналы обращений + пост в форуме для сапорта, автоудаление через месяц",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_ticket_cog(self.ctx))
        await self.ctx.add_cog(build_ticket_bridge_cog(self.ctx))
        # Персистентные View не завязаны на конкретное сообщение -- их
        # можно (и нужно) регистрировать один раз при загрузке плагина,
        # ещё до того, как бот подключился к шлюзу.
        self.ctx.bot.add_view(TicketPanelView(self.ctx))
        self.ctx.bot.add_view(TicketControlView(self.ctx))
        self.log.info("tickets готов к работе")

    async def start(self) -> None:
        self.ctx.create_task(self._purge_loop(), name="tickets-purge-loop")

    async def _purge_loop(self) -> None:
        while True:
            await self._purge_old_tickets()
            await asyncio.sleep(PURGE_CHECK_INTERVAL_SECONDS)

    async def _purge_old_tickets(self) -> None:
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=TICKET_PURGE_AFTER_DAYS)
        for guild in self.ctx.bot.guilds:
            try:
                await self._purge_guild(guild, cutoff)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="ticket_purge", guild_id=guild.id)

    async def _purge_guild(self, guild: discord.Guild, cutoff: dt.datetime) -> None:
        async with self.ctx.db.session() as session:
            stale = await TicketRepository(session).closed_before(guild.id, cutoff)
            # Достаём нужные поля, пока запись ещё привязана к сессии --
            # после выхода из "async with" обращаться к ним небезопасно.
            stale_ids = [(t.id, t.channel_id, t.forum_thread_id) for t in stale]

        if not stale_ids:
            return

        for ticket_id, channel_id, forum_thread_id in stale_ids:
            await self._delete_ticket_traces(guild, ticket_id=ticket_id, channel_id=channel_id, forum_thread_id=forum_thread_id)
            async with self.ctx.db.session() as session:
                await TicketRepository(session).delete(ticket_id)

        self.log.info(
            "Автоудаление тикетов на сервере %s: удалено %d (закрыты более %d дн. назад)",
            guild.name, len(stale_ids), TICKET_PURGE_AFTER_DAYS,
        )

    async def _delete_ticket_traces(self, guild: discord.Guild, *, ticket_id: int, channel_id: int, forum_thread_id: int | None) -> None:
        channel = guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="Тикет закрыт более месяца назад")
            except discord.HTTPException as exc:
                await self.ctx.report_error(exc, event="ticket_purge_channel", guild_id=guild.id, ticket_id=ticket_id)

        if not forum_thread_id:
            return
        thread = guild.get_thread(forum_thread_id)
        if thread is None:
            try:
                thread = await self.ctx.bot.fetch_channel(forum_thread_id)
            except discord.HTTPException:
                thread = None
        if thread is not None:
            try:
                await thread.delete()
            except discord.HTTPException as exc:
                await self.ctx.report_error(exc, event="ticket_purge_thread", guild_id=guild.id, ticket_id=ticket_id)


PLUGIN_CLASS = TicketsPlugin
