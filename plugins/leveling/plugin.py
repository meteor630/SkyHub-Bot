"""Плагин ``leveling``: XP за сообщения, уровни, репутация, синхронизация
налёта из бортжурнала (ТЗ §41, "XP / reputation").

Налёт (``flight_minutes``) не читается напрямую из ``plugins/flight_log``
-- вместо этого плагин подписывается на :class:`core.events.FlightLogged`
через Event Bus, оставаясь полностью независимым от того, включён ли
``flight_log`` вообще (ТЗ §19).
"""
from __future__ import annotations

import time

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import FlightLogged
from database.repositories.stats_repository import StatsRepository
from plugins.leveling.commands import build_leveling_cog

XP_PER_MESSAGE = 5
XP_COOLDOWN_SECONDS = 60.0  # не более одного начисления в минуту на участника


class MessageXPCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._cooldowns: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last = self._cooldowns.get(key)
        if last is not None and (now - last) < XP_COOLDOWN_SECONDS:
            return
        self._cooldowns[key] = now

        try:
            async with self.ctx.db.session() as session:
                stats, leveled_up = await StatsRepository(session).add_message_xp(message.guild.id, message.author.id, XP_PER_MESSAGE)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="on_message_xp", guild_id=message.guild.id, user_id=message.author.id)
            return

        if leveled_up:
            try:
                await message.channel.send(f"🎉 {message.author.mention} достиг уровня **{stats.level}**!")
            except discord.HTTPException:
                pass


class LevelingPlugin(BasePlugin):
    meta = PluginMeta(
        name="leveling", version="1.0.0",
        description="/level, /leaderboard, /rep -- XP за активность, репутация, синхронизация с бортжурналом",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_leveling_cog(self.ctx))
        await self.ctx.add_cog(MessageXPCog(self.ctx))
        self.ctx.subscribe(FlightLogged, self._on_flight_logged)
        self.log.info("leveling готов к работе")

    async def _on_flight_logged(self, event: FlightLogged) -> None:
        if event.guild_id is None:
            return
        async with self.ctx.db.session() as session:
            await StatsRepository(session).add_flight_minutes(event.guild_id, event.user_id, event.flight_minutes)


PLUGIN_CLASS = LevelingPlugin
