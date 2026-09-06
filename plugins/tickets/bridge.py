"""Мост сообщений между приватным каналом тикета и постом в форуме для
сапорта (см. модуль-докстринг ``database/models/ticket.py`` и
``plugins/tickets/forum.py`` -- почему это два отдельных места, а не
один общий форум). Каждое человеческое сообщение с одной стороны
пересылается на другую через веб-хук, сохраняя имя/аватар исходного
автора -- иначе переписка выглядела бы так, будто всё пишет сам бот.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from database.models.ticket import STATUS_OPEN
from database.repositories.ticket_repository import TicketRepository
from plugins.tickets import forum as ticket_forum


class TicketBridgeCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # author.bot=True отсекает и обычных ботов, и сообщения САМОГО
        # моста (веб-хук технически тоже "бот") -- без этой проверки
        # пересланная копия пересылалась бы обратно до бесконечности.
        if message.author.bot or message.guild is None:
            return

        if isinstance(message.channel, discord.Thread) and isinstance(message.channel.parent, discord.ForumChannel):
            await self._from_forum(message)
        elif isinstance(message.channel, discord.TextChannel):
            await self._from_private_channel(message)

    async def _from_private_channel(self, message: discord.Message) -> None:
        async with self.ctx.db.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(message.channel.id)
            if ticket is None or ticket.status != STATUS_OPEN or not ticket.forum_thread_id:
                return
            forum_thread_id = ticket.forum_thread_id

        thread = await self._resolve_thread(forum_thread_id)
        if thread is None:
            return

        try:
            webhook = await ticket_forum.get_or_create_bridge_webhook(thread.parent)
            await self._relay(webhook, message, thread=thread)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="ticket_bridge_to_forum", channel_id=message.channel.id)

    async def _from_forum(self, message: discord.Message) -> None:
        async with self.ctx.db.session() as session:
            ticket = await TicketRepository(session).get_by_forum_thread_id(message.channel.id)
            if ticket is None or ticket.status != STATUS_OPEN:
                return
            channel_id = ticket.channel_id

        channel = self.ctx.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            webhook = await ticket_forum.get_or_create_bridge_webhook(channel)
            await self._relay(webhook, message)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="ticket_bridge_to_channel", channel_id=channel_id)

    async def _resolve_thread(self, forum_thread_id: int) -> discord.Thread | None:
        thread = self.ctx.bot.get_channel(forum_thread_id)
        if thread is None:
            try:
                thread = await self.ctx.bot.fetch_channel(forum_thread_id)
            except discord.HTTPException:
                return None
        if isinstance(thread, discord.Thread) and isinstance(thread.parent, discord.ForumChannel):
            return thread
        return None

    @staticmethod
    async def _relay(webhook: discord.Webhook, message: discord.Message, *, thread: discord.Thread | None = None) -> None:
        content = message.content[:2000]
        files = [await attachment.to_file() for attachment in message.attachments]
        if not content and not files:
            return  # нечего пересылать -- пустое системное/embed-сообщение
        send_kwargs: dict = {"username": message.author.display_name[:80], "avatar_url": message.author.display_avatar.url}
        if thread is not None:
            send_kwargs["thread"] = thread
        if files:
            send_kwargs["files"] = files
        await webhook.send(content=content or discord.utils.MISSING, **send_kwargs)


def build_ticket_bridge_cog(ctx) -> TicketBridgeCog:
    return TicketBridgeCog(ctx)
