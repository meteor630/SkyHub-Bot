"""Плагин модерации: команды + пассивный захват через audit-log + красивые логи (ТЗ §11)."""
from __future__ import annotations

import discord

from core.base_plugin import BasePlugin, PluginMeta
from core.events import ChannelChanged, ModerationAction, RoleChanged
from plugins.moderation.commands import build_moderation_cog
from plugins.moderation.listeners import ModerationAuditListener
from services.moderation_service import ModerationService
from utils.time import discord_full

ACTION_LABELS = {
    "ban": ("🔨", "Бан"),
    "unban": ("✅", "Разбан"),
    "kick": ("👢", "Кик"),
    "timeout": ("⏱", "Тайм-аут"),
    "warn": ("⚠️", "Предупреждение"),
    "role_add": ("➕", "Роль выдана"),
    "role_remove": ("➖", "Роль снята"),
    "nickname": ("✏️", "Изменение никнейма"),
    "bulk_delete": ("🧹", "Массовое удаление сообщений"),
}

# action здесь -- "create" / "delete" / "update" (последняя часть имени
# discord.AuditLogAction, напр. channel_create -> create).
CHANGE_LABELS = {
    "create": "создан",
    "delete": "удалён",
    "update": "изменён",
}


class ModerationPlugin(BasePlugin):
    meta = PluginMeta(
        name="moderation",
        version="1.2.0",
        description="Команды модерации (/mod ...) + захват через audit-log + канал логов модерации",
        dependencies=(),
    )

    async def setup(self) -> None:
        self.service = ModerationService(self.ctx.db)
        await self.ctx.add_cog(build_moderation_cog(self.ctx, self.service))
        await self.ctx.add_cog(ModerationAuditListener(self.ctx))
        self.ctx.subscribe(ModerationAction, self._on_moderation_action)
        self.ctx.subscribe(ChannelChanged, self._on_channel_changed)
        self.ctx.subscribe(RoleChanged, self._on_role_changed)
        self.log.info("moderation готов к работе")

    async def _log_channel(self, guild_id: int | None) -> discord.abc.Messageable | None:
        if guild_id is None:
            return None
        channel_id = await self.ctx.guild_config().resolve_channel_id(guild_id, "moderation_logs")
        if not channel_id:
            return None
        return self.ctx.bot.get_channel(channel_id) or await self._safe_fetch(channel_id)

    async def _safe_fetch(self, channel_id: int) -> discord.abc.Messageable | None:
        try:
            return await self.ctx.bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return None

    async def _on_moderation_action(self, event: ModerationAction) -> None:
        channel = await self._log_channel(event.guild_id)
        if channel is None:
            return
        emoji, label = ACTION_LABELS.get(event.action, ("📋", event.action.title()))
        embed = discord.Embed(title=f"{emoji} {label}", color=discord.Color.dark_orange(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Кто", value=f"<@{event.moderator_id}>" if event.moderator_id else "Discord", inline=True)
        embed.add_field(name="С кем", value=f"<@{event.target_id}>", inline=True)
        embed.add_field(name="Когда", value=discord_full(discord.utils.utcnow()), inline=True)
        embed.add_field(name="Причина", value=event.reason or "—", inline=False)
        if event.extra:
            embed.add_field(name="Дополнительно", value=", ".join(f"{k}: {v}" for k, v in event.extra.items())[:1024], inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_moderation_log", guild_id=event.guild_id)

    async def _on_channel_changed(self, event: ChannelChanged) -> None:
        channel = await self._log_channel(event.guild_id)
        if channel is None:
            return
        embed = discord.Embed(
            title=f"📁 Канал {CHANGE_LABELS.get(event.action, event.action)}",
            description=f"**{event.name or event.channel_id}**",
            color=discord.Color.dark_teal(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Кто", value=f"<@{event.actor_id}>" if event.actor_id else "—")
        await channel.send(embed=embed)

    async def _on_role_changed(self, event: RoleChanged) -> None:
        channel = await self._log_channel(event.guild_id)
        if channel is None:
            return
        embed = discord.Embed(
            title=f"🎭 Роль {CHANGE_LABELS.get(event.action, event.action)}",
            description=f"**{event.name or event.role_id}**",
            color=discord.Color.dark_purple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Кто", value=f"<@{event.actor_id}>" if event.actor_id else "—")
        await channel.send(embed=embed)


PLUGIN_CLASS = ModerationPlugin
