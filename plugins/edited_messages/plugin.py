"""Плагин ``edited_messages`` (ТЗ §13): логирует содержимое "до/после" при редактировании сообщения."""
from __future__ import annotations

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import MessageEdited
from database.repositories.message_repository import MessageRepository
from utils.text import truncate


class EditedMessagesCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if payload.guild_id is None:
            return

        after_content = payload.data.get("content")
        if after_content is None:
            return  # обновление без изменения текста (напр. только embed/разворот ссылки) -- логировать нечего

        before = payload.cached_message
        raw_author = payload.data.get("author") or {}

        # Свои же периодически редактируемые сообщения (живой статус-дашборд,
        # карточка "сейчас играет" у радио) бот обновляет через
        # channel.fetch_message() -- в отличие от сообщений, полученных по
        # шлюзу, discord.py НЕ добавляет их во внутренний кэш, поэтому
        # payload.cached_message тут всегда None и проверка "before.author.bot"
        # эту ситуацию не ловит. Раз содержимое автора всё равно приходит в
        # сыром payload'е самого события редактирования -- используем его как
        # запасной источник, чтобы не логировать правки самого бота.
        is_bot_author = before.author.bot if before is not None else bool(raw_author.get("bot"))
        if is_bot_author:
            return

        before_content = before.content if before is not None else "*(сообщение не было в кэше)*"
        if before is not None and before_content == after_content:
            return

        author_id = before.author.id if before is not None else raw_author.get("id")
        if author_id is not None:
            author_id = int(author_id)
        else:
            return

        try:
            async with self.ctx.db.session() as session:
                await MessageRepository(session).log_edited(
                    guild_id=payload.guild_id, channel_id=payload.channel_id, message_id=payload.message_id,
                    author_id=author_id, before=before_content, after=after_content,
                )
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="log_edited_message", guild_id=payload.guild_id)
            return

        self.ctx.emit(
            MessageEdited(
                guild_id=payload.guild_id, message_id=payload.message_id, channel_id=payload.channel_id,
                author_id=author_id, before=before_content, after=after_content,
            )
        )
        await self._post_log(payload.guild_id, payload.channel_id, author_id, before_content, after_content)

    async def _post_log(self, guild_id: int, channel_id: int, author_id: int, before: str, after: str) -> None:
        target = await self.ctx.guild_config().resolve_channel_id(guild_id, "edited_messages")
        if not target:
            return
        channel = self.ctx.bot.get_channel(target)
        if channel is None:
            return

        author = self.ctx.bot.get_user(author_id)
        embed = discord.Embed(description="✏️ **Сообщение изменено**", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        if author is not None:
            embed.set_author(name=str(author), icon_url=author.display_avatar.url)
        source_channel = self.ctx.bot.get_channel(channel_id)
        embed.add_field(name="Канал", value=source_channel.mention if source_channel else f"`{channel_id}`", inline=False)
        embed.add_field(name="Было", value=truncate(before or "*(пусто)*", 1024), inline=False)
        embed.add_field(name="Стало", value=truncate(after or "*(пусто)*", 1024), inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_edited_message_log", guild_id=guild_id)


class EditedMessagesPlugin(BasePlugin):
    meta = PluginMeta(
        name="edited_messages", version="1.0.0",
        description="Логирует изменения сообщений (до/после) в отдельный канал",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(EditedMessagesCog(self.ctx))
        self.log.info("edited_messages готов к работе")


PLUGIN_CLASS = EditedMessagesPlugin
