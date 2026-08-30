"""Плагин ``voice_channels``: временные приватные голосовые комнаты (ТЗ §15-18, §27)."""
from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import VoiceCreated, VoiceDeleted
from plugins.voice_channels.commands import build_voice_cog
from plugins.voice_channels.views import VoiceControlView
from services.voice_service import VoiceService

EMPTY_CHANNEL_DELETE_DELAY_SECONDS = 10.0


class VoiceEventsCog(commands.Cog):
    def __init__(self, ctx, service: VoiceService) -> None:
        self.ctx = ctx
        self.service = service
        self._pending_deletions: dict[int, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        try:
            creator_id = await self.ctx.guild_config().resolve_channel_id(member.guild.id, "temporary_voice_creator")
            if after.channel is not None and creator_id and after.channel.id == creator_id:
                await self._create_room_for(member)

            if before.channel is not None:
                await self._maybe_schedule_deletion(before.channel)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="on_voice_state_update", guild_id=member.guild.id, user_id=member.id)

    async def _create_room_for(self, member: discord.Member) -> None:
        category_id = await self.ctx.guild_config().resolve_category_id(member.guild.id)
        category = member.guild.get_channel(category_id) if category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None

        channel = await self.service.create_room(member=member, category=category)
        await member.move_to(channel, reason="Создана временная голосовая комната")
        self.ctx.emit(VoiceCreated(guild_id=member.guild.id, channel_id=channel.id, owner_id=member.id))

        view = VoiceControlView(self.service)
        embed = discord.Embed(
            title=f"✈️ {channel.name}",
            description="Это ваша личная голосовая комната. Управляйте ей кнопками ниже или командой `/voice`.",
            color=discord.Color.blue(),
        )
        try:
            await channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_voice_control_panel", guild_id=member.guild.id)

    async def _maybe_schedule_deletion(self, channel: discord.VoiceChannel) -> None:
        record = await self.service.get_owner_id(channel.id)
        if record is None:
            return  # это не отслеживаемый временный канал
        if len(channel.members) > 0:
            return

        existing = self._pending_deletions.get(channel.id)
        if existing is not None and not existing.done():
            return

        task = self.ctx.create_task(self._delete_after_delay(channel.id), name=f"voice-cleanup-{channel.id}")
        self._pending_deletions[channel.id] = task

    async def _delete_after_delay(self, channel_id: int) -> None:
        await asyncio.sleep(EMPTY_CHANNEL_DELETE_DELAY_SECONDS)
        self._pending_deletions.pop(channel_id, None)

        channel = self.ctx.bot.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return
        if len(channel.members) > 0:
            return  # кто-то зашёл обратно за время задержки

        owner_id = await self.service.get_owner_id(channel_id)
        await self.service.delete_room(channel)
        self.ctx.emit(VoiceDeleted(guild_id=channel.guild.id, channel_id=channel_id, owner_id=owner_id))


class VoiceChannelsPlugin(BasePlugin):
    meta = PluginMeta(
        name="voice_channels", version="1.4.0",
        description="Временные приватные голосовые комнаты с управлением владельцем (кнопки + /voice)",
        dependencies=(),
    )

    async def setup(self) -> None:
        self.service = VoiceService(self.ctx.db)
        await self.ctx.add_cog(build_voice_cog(self.ctx, self.service))
        await self.ctx.add_cog(VoiceEventsCog(self.ctx, self.service))
        self.log.info("voice_channels готов к работе")

    async def start(self) -> None:
        for guild in self.ctx.bot.guilds:
            try:
                removed, checked = await self.service.reconcile_guild(guild)
                if checked:
                    self.log.info("Проверка временных voice-каналов на сервере %s: удалено %d/%d", guild.name, removed, checked)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="reconcile_guild", guild_id=guild.id)


PLUGIN_CLASS = VoiceChannelsPlugin
