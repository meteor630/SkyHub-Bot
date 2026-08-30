"""Плагин ``status_dashboard``: один живой, постоянно обновляемый embed
в канале, настроенном через ``/setup status`` -- статус бота, базы
данных и каждого плагина, без необходимости заходить в консоль или
дёргать ``/status`` руками.

Сообщение не пересоздаётся каждый раз (это заспамило бы канал) -- ID
канала и сообщения запоминаются в БД (``dashboard_messages``) и
переиспользуются между перезапусками; если сообщение удалили руками,
плагин просто создаст новое и запомнит его заново.
"""
from __future__ import annotations

import asyncio
import time

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import PluginError as PluginErrorEvent
from core.events import PluginLoaded, PluginReloaded
from core.plugin_manager import PluginStatus
from database.repositories.dashboard_repository import DashboardRepository
from utils.time import format_duration, format_latency_ms

REFRESH_INTERVAL_SECONDS = 60.0
DASHBOARD_KIND = "status"

STATUS_EMOJI = {
    PluginStatus.ONLINE: "🟢",
    PluginStatus.LOADING: "🟡",
    PluginStatus.DISABLED: "⚪",
    PluginStatus.ERROR: "🔴",
    PluginStatus.BLOCKED: "🟠",
}


class StatusDashboardCog(commands.Cog):
    """Хранит по одной фоновой задаче обновления на каждый сервер, где
    настроен канал статуса."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._refresh_locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self._refresh_locks.setdefault(guild_id, asyncio.Lock())

    async def refresh(self, guild: discord.Guild) -> None:
        """Обновляет (или создаёт заново) дашборд на конкретном сервере.
        Лок на сервер нужен, чтобы событие плагина и периодический тик не
        попытались одновременно создать два разных сообщения."""
        async with self._lock_for(guild.id):
            channel_id = await self.ctx.guild_config().resolve_channel_id(guild.id, "status")
            if not channel_id:
                return
            channel = self.ctx.bot.get_channel(channel_id)
            if channel is None:
                return

            embed = await self._build_embed(guild)

            async with self.ctx.db.session() as session:
                repo = DashboardRepository(session)
                existing = await repo.get(guild.id, DASHBOARD_KIND)

            message = None
            if existing is not None and existing.channel_id == channel_id:
                try:
                    message = await channel.fetch_message(existing.message_id)
                    await message.edit(embed=embed)
                except discord.NotFound:
                    message = None
                except discord.HTTPException as exc:
                    await self.ctx.report_error(exc, event="dashboard_edit", guild_id=guild.id)
                    return

            if message is None:
                try:
                    message = await channel.send(embed=embed)
                except discord.HTTPException as exc:
                    await self.ctx.report_error(exc, event="dashboard_create", guild_id=guild.id)
                    return
                async with self.ctx.db.session() as session:
                    await DashboardRepository(session).upsert(
                        guild_id=guild.id, kind=DASHBOARD_KIND, channel_id=channel_id, message_id=message.id
                    )

    async def _build_embed(self, guild: discord.Guild) -> discord.Embed:
        bot = self.ctx.bot
        pm = bot.plugin_manager
        records = pm.list_plugins()
        online = sum(1 for r in records if r.status is PluginStatus.ONLINE)

        db_ok = await bot.db.ping()

        embed = discord.Embed(
            title="📊 Статус SkyHub Bot",
            color=discord.Color.green() if db_ok else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Бот", value="🟢 ONLINE" if bot.is_ready() else "🟡 Подключается", inline=True)
        embed.add_field(name="Задержка Discord", value=format_latency_ms(bot.latency), inline=True)
        embed.add_field(name="База данных", value="🟢 ONLINE" if db_ok else "🔴 OFFLINE", inline=True)
        embed.add_field(name="Аптайм", value=format_duration(time.time() - bot.started_at), inline=True)
        embed.add_field(name="Участников на сервере", value=str(guild.member_count or "—"), inline=True)
        embed.add_field(name="Плагины", value=f"{online}/{len(records)} онлайн", inline=True)

        lines = [
            f"{STATUS_EMOJI.get(r.status, '❔')} `{r.name}` v{r.meta.version if r.meta else '?'}"
            for r in records
        ]
        embed.add_field(name="Список плагинов", value="\n".join(lines)[:1024] or "—", inline=False)
        embed.set_footer(text="Обновляется автоматически каждую минуту и при изменении состояния плагинов")
        return embed


class StatusDashboardPlugin(BasePlugin):
    meta = PluginMeta(
        name="status_dashboard", version="1.0.0",
        description="Живой embed со статусом бота и всех плагинов в отдельном канале (/setup status)",
        dependencies=(),
    )

    async def setup(self) -> None:
        self.cog = StatusDashboardCog(self.ctx)
        await self.ctx.add_cog(self.cog)
        self.ctx.subscribe(PluginLoaded, self._on_plugin_event)
        self.ctx.subscribe(PluginReloaded, self._on_plugin_event)
        self.ctx.subscribe(PluginErrorEvent, self._on_plugin_event)
        self.log.info("status_dashboard готов к работе")

    async def start(self) -> None:
        self.ctx.create_task(self._refresh_loop(), name="status-dashboard-loop")

    async def _refresh_loop(self) -> None:
        # Небольшая задержка перед первым обновлением -- даём остальным
        # плагинам время закончить start() и попасть в дашборд уже в
        # финальном состоянии, а не "LOADING".
        await asyncio.sleep(3.0)
        while True:
            await self._refresh_all()
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)

    async def _refresh_all(self) -> None:
        for guild in self.ctx.bot.guilds:
            try:
                await self.cog.refresh(guild)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="dashboard_refresh", guild_id=guild.id)

    async def _on_plugin_event(self, event) -> None:  # noqa: ANN001 -- событие одно из трёх типов выше
        await self._refresh_all()


PLUGIN_CLASS = StatusDashboardPlugin
