"""Плагин ``deleted_messages`` (ТЗ §12): логирует содержимое удалённых
сообщений в отдельный канал, используя "сырые" события шлюза, чтобы
удаления сообщений, выпавших из внутреннего кэша discord.py, тоже
фиксировались (с той метаинформацией, которую Discord ещё способен дать)."""
from __future__ import annotations

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import MessageDeleted
from database.repositories.message_repository import MessageRepository
from utils.text import truncate


class DeletedMessagesCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id is None:
            return
        message = payload.cached_message
        if message is not None and message.author.bot:
            return

        content = message.content if message else "*(сообщение не было в кэше -- содержимое недоступно)*"
        author_id = message.author.id if message else None
        attachments = [a.url for a in message.attachments] if message else []

        await self._record(
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
            author_id=author_id,
            content=content,
            attachments=attachments,
            bulk=False,
        )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if payload.guild_id is None:
            return
        for message in payload.cached_messages:
            if message.author.bot:
                continue
            await self._record(
                guild_id=payload.guild_id,
                channel_id=payload.channel_id,
                message_id=message.id,
                author_id=message.author.id,
                content=message.content,
                attachments=[a.url for a in message.attachments],
                bulk=True,
            )

    async def _record(self, *, guild_id: int, channel_id: int, message_id: int, author_id: int | None,
                       content: str, attachments: list[str], bulk: bool) -> None:
        try:
            async with self.ctx.db.session() as session:
                await MessageRepository(session).log_deleted(
                    guild_id=guild_id, channel_id=channel_id, message_id=message_id, author_id=author_id,
                    content=content, attachments=attachments, bulk=bulk,
                )
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="log_deleted_message", guild_id=guild_id)
            return

        self.ctx.emit(
            MessageDeleted(
                guild_id=guild_id, message_id=message_id, channel_id=channel_id, author_id=author_id,
                content=content, attachments=tuple(attachments), bulk=bulk,
            )
        )
        await self._post_log(guild_id, channel_id, message_id, author_id, content, attachments, bulk)

    async def _post_log(self, guild_id, channel_id, message_id, author_id, content, attachments, bulk) -> None:
        target = await self.ctx.guild_config().resolve_channel_id(guild_id, "deleted_messages")
        if not target:
            return
        channel = self.ctx.bot.get_channel(target)
        if channel is None:
            return

        author = self.ctx.bot.get_user(author_id) if author_id else None
        embed = discord.Embed(
            description=f"🗑️ **Удалено сообщение**{' (массовое удаление)' if bulk else ''}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        if author is not None:
            embed.set_author(name=str(author), icon_url=author.display_avatar.url)
        embed.add_field(name="Текст", value=truncate(content or "*(пусто)*", 1024), inline=False)
        source_channel = self.ctx.bot.get_channel(channel_id)
        embed.add_field(name="Канал", value=source_channel.mention if source_channel else f"`{channel_id}`", inline=True)
        embed.add_field(name="ID сообщения", value=f"`{message_id}`", inline=True)
        if attachments:
            embed.add_field(name="Вложения", value="\n".join(attachments)[:1024], inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_deleted_message_log", guild_id=guild_id)


class DeletedMessagesPlugin(BasePlugin):
    meta = PluginMeta(
        name="deleted_messages", version="1.1.0",
        description="Логирует содержимое удалённых сообщений (включая вложения) в отдельный канал",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(DeletedMessagesCog(self.ctx))
        self.log.info("deleted_messages готов к работе")


PLUGIN_CLASS = DeletedMessagesPlugin
