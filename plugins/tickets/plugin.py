"""Плагин ``tickets``: система обращений (ТЗ §41, "Support / Tickets") --
у каждого обращения приватный канал для автора и, если настроен форум
(``/setup tickets-forum``, см. ``plugins/tickets/forum.py``), пост в
приватном форуме для сапорта; ``plugins/tickets/bridge.py`` зеркалит
сообщения между ними.

Кнопки (панель создания и "закрыть") регистрируются как персистентные
через ``bot.add_view()`` -- они продолжают отвечать на нажатия даже
после перезапуска бота, без необходимости заново публиковать панель.
Кнопка "закрыть" стоит и на приватном канале, и на посте форума --
у обоих один ``custom_id``, поэтому регистрировать её нужно только
один раз (см. ``plugins/tickets/views.py::close_ticket``).

Закрытый тикет больше не удаляется сразу -- у автора и у сапорта разное
время хранения (клиентский запрос: у автора обращение должно пропадать
быстро, а у сапорта -- оставаться дольше как история):
- приватный канал автора удаляется через ``CHANNEL_PURGE_AFTER_DAYS``
  (1 день) после закрытия;
- пост в форуме сапорта -- через ``FORUM_PURGE_AFTER_DAYS`` (30 дней);
  до этого он просто архивируется/блокируется и помечается тегом
  "Закрыт" (открытые посты сверху, закрытые архивные -- снизу, это
  Discord и так делает сам, донастраивать не нужно).
Запись в БД удаляется только когда истекли ОБА срока (то есть по
самому длинному, форумному).
"""
from __future__ import annotations

import asyncio
import datetime as dt

import discord

from core.base_plugin import BasePlugin, PluginMeta
from database.repositories.ticket_repository import TicketRepository
from plugins.tickets.bridge import build_ticket_bridge_cog
from plugins.tickets.commands import build_ticket_cog
from plugins.tickets.views import TicketControlView, TicketDeleteView, TicketPanelView

# Раз в 6 часов вполне достаточно -- тикетов закрывается не так много,
# чтобы гнаться за секундной точностью автоудаления.
PURGE_CHECK_INTERVAL_SECONDS = 6 * 3600
CHANNEL_PURGE_AFTER_DAYS = 1
FORUM_PURGE_AFTER_DAYS = 30


class TicketsPlugin(BasePlugin):
    meta = PluginMeta(
        name="tickets", version="1.2.0",
        description="/ticket panel|close -- приватные каналы обращений + пост в форуме для сапорта, разное время автоудаления",
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
        self.ctx.bot.add_view(TicketDeleteView(self.ctx))
        self.log.info("tickets готов к работе")

    async def start(self) -> None:
        self.ctx.create_task(self._purge_loop(), name="tickets-purge-loop")

    async def _purge_loop(self) -> None:
        while True:
            await self._purge_old_tickets()
            await asyncio.sleep(PURGE_CHECK_INTERVAL_SECONDS)

    async def _purge_old_tickets(self) -> None:
        now = dt.datetime.now(dt.UTC)
        for guild in self.ctx.bot.guilds:
            try:
                await self._purge_guild(guild, now)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="ticket_purge", guild_id=guild.id)

    async def _purge_guild(self, guild: discord.Guild, now: dt.datetime) -> None:
        channel_cutoff = now - dt.timedelta(days=CHANNEL_PURGE_AFTER_DAYS)
        forum_cutoff = now - dt.timedelta(days=FORUM_PURGE_AFTER_DAYS)

        async with self.ctx.db.session() as session:
            # Канал живёт МЕНЬШЕ, чем пост форума -- значит выборка по
            # channel_cutoff -- надмножество тех, кому уже пора чистить
            # и форум тоже (раз он держится дольше).
            candidates = await TicketRepository(session).closed_before(guild.id, channel_cutoff)
            # Достаём нужные поля, пока запись ещё привязана к сессии --
            # после выхода из "async with" обращаться к ним небезопасно.
            rows = [(t.id, t.channel_id, t.forum_thread_id, t.closed_at) for t in candidates]

        if not rows:
            return

        channels_deleted = 0
        rows_deleted = 0
        for ticket_id, channel_id, forum_thread_id, closed_at in rows:
            if await self._delete_stale_channel(guild, ticket_id=ticket_id, channel_id=channel_id):
                channels_deleted += 1

            fully_expired = closed_at is not None and closed_at <= forum_cutoff
            if not fully_expired:
                continue
            await self._delete_stale_forum_thread(guild, ticket_id=ticket_id, forum_thread_id=forum_thread_id)
            async with self.ctx.db.session() as session:
                await TicketRepository(session).delete(ticket_id)
            rows_deleted += 1

        if channels_deleted or rows_deleted:
            self.log.info(
                "Автоудаление тикетов на сервере %s: каналов удалено %d, тикетов полностью удалено %d "
                "(канал > %d дн., полностью > %d дн. после закрытия)",
                guild.name, channels_deleted, rows_deleted, CHANNEL_PURGE_AFTER_DAYS, FORUM_PURGE_AFTER_DAYS,
            )

    async def _delete_stale_channel(self, guild: discord.Guild, *, ticket_id: int, channel_id: int) -> bool:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return False
        try:
            await channel.delete(reason=f"Тикет закрыт более {CHANNEL_PURGE_AFTER_DAYS} дн. назад")
            return True
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="ticket_purge_channel", guild_id=guild.id, ticket_id=ticket_id)
            return False

    async def _delete_stale_forum_thread(self, guild: discord.Guild, *, ticket_id: int, forum_thread_id: int | None) -> None:
        if not forum_thread_id:
            return
        thread = guild.get_thread(forum_thread_id)
        if thread is None:
            try:
                thread = await self.ctx.bot.fetch_channel(forum_thread_id)
            except discord.HTTPException:
                thread = None
        if thread is None:
            return
        try:
            await thread.delete()
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="ticket_purge_thread", guild_id=guild.id, ticket_id=ticket_id)


PLUGIN_CLASS = TicketsPlugin
