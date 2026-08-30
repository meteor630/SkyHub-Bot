"""Плагин ``member_logs`` (ТЗ §14): логирование входов и выходов участников."""
from __future__ import annotations

import datetime as dt

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import MemberJoined, MemberLeft
from utils.time import discord_full, discord_relative, format_duration


class MemberLogsCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        self.ctx.emit(
            MemberJoined(
                guild_id=member.guild.id, user_id=member.id, display_name=member.display_name,
                account_created_at=member.created_at.timestamp(),
            )
        )
        channel = await self._log_channel(member.guild.id)
        if channel is None:
            return
        embed = discord.Embed(title="🟢 Новый участник", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member}`)", inline=False)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Регистрация в Discord", value=discord_full(member.created_at), inline=True)
        embed.add_field(name="Время входа", value=discord_relative(discord.utils.utcnow()), inline=True)
        await self._send(channel, embed, member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        self.ctx.emit(
            MemberLeft(
                guild_id=member.guild.id, user_id=member.id, display_name=member.display_name,
                joined_at=member.joined_at.timestamp() if member.joined_at else None,
            )
        )
        channel = await self._log_channel(member.guild.id)
        if channel is None:
            return
        embed = discord.Embed(title="🔴 Участник покинул сервер", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=f"`{member}`", inline=False)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        if member.joined_at:
            duration = (dt.datetime.now(dt.UTC) - member.joined_at).total_seconds()
            embed.add_field(name="Время на сервере", value=format_duration(duration), inline=True)
        await self._send(channel, embed, member.guild.id)

    async def _log_channel(self, guild_id: int) -> discord.abc.Messageable | None:
        channel_id = await self.ctx.guild_config().resolve_channel_id(guild_id, "member_logs")
        if not channel_id:
            return None
        return self.ctx.bot.get_channel(channel_id)

    async def _send(self, channel: discord.abc.Messageable, embed: discord.Embed, guild_id: int) -> None:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_member_log", guild_id=guild_id)


class MemberLogsPlugin(BasePlugin):
    meta = PluginMeta(
        name="member_logs", version="1.0.0",
        description="Логирование входов и выходов участников в отдельный канал",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(MemberLogsCog(self.ctx))
        self.log.info("member_logs готов к работе")


PLUGIN_CLASS = MemberLogsPlugin
