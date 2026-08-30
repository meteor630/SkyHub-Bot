"""Сам Discord-клиент. Намеренно тонкий: подключение к шлюзу, пара
всегда включённых базовых команд (``/status``, ``/plugin``), а всё
остальное делегируется :class:`core.plugin_manager.PluginManager`
(ТЗ §2, §44 -- никакого ``bot.py`` на 5000 строк).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config.settings import Settings
from core.command_registry import CommandRegistry
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.permissions import PermissionCheckFailure, PermissionService, Role, require
from core.plugin_manager import PluginManager, PluginStatus
from database.database import Database
from database.repositories.guild_repository import GuildRepository
from utils.cache import TTLCache
from utils.i18n import I18n
from utils.time import format_duration, format_latency_ms

logger = logging.getLogger("skyhub.bot")

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True

DISCORD_UNKNOWN_INTERACTION = 10062


def _is_expired_interaction(error: BaseException) -> bool:
    """True, если ошибка -- это ``discord.NotFound`` с кодом 10062
    (Unknown interaction), в том числе обёрнутая в ``CommandInvokeError``.
    Такое случается, когда между созданием интеракции Discord'ом и нашим
    первым ответом на неё прошло больше 3 секунд -- окно, которое
    целиком определяется загрузкой системы/сети в момент запроса, а не
    логикой команды."""
    original = getattr(error, "original", error)
    return isinstance(original, discord.NotFound) and original.code == DISCORD_UNKNOWN_INTERACTION


class CoreCog(commands.Cog):
    """Всегда загруженные команды, которые должны работать, даже если все
    плагины отключены -- статус/здоровье и управление плагинами прямо из Discord."""

    plugin_group = app_commands.Group(name="plugin", description="Управление плагинами бота")

    def __init__(self, bot: SkyHubBot) -> None:
        self.bot = bot

    @app_commands.command(name="status", description="Показать статус бота")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db_ok = await self.bot.db.ping()
        online = sum(1 for r in self.bot.plugin_manager.list_plugins() if r.status is PluginStatus.ONLINE)
        total = len(self.bot.plugin_manager.list_plugins())
        embed = discord.Embed(title="📊 Статус SkyHub Bot", color=discord.Color.green() if db_ok else discord.Color.red())
        embed.add_field(name="Задержка Discord", value=format_latency_ms(self.bot.latency))
        embed.add_field(name="База данных", value="🟢 ONLINE" if db_ok else "🔴 OFFLINE")
        embed.add_field(name="Плагины", value=f"{online}/{total}")
        embed.add_field(name="Аптайм", value=format_duration(time.time() - self.bot.started_at))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @plugin_group.command(name="list", description="Список плагинов")
    @require(Role.ADMIN)
    async def plugin_list(self, interaction: discord.Interaction) -> None:
        records = self.bot.plugin_manager.list_plugins()
        lines = [f"`{r.name.ljust(20)}` {r.meta.version if r.meta else '?':<10} {r.status.value}" for r in records]
        await interaction.response.send_message("\n".join(lines) or "Плагинов нет.", ephemeral=True)

    @plugin_group.command(name="reload", description="Горячая перезагрузка плагина")
    @app_commands.describe(name="Имя плагина")
    @require(Role.ADMIN)
    async def plugin_reload(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.plugin_manager.reload(name)
            await interaction.followup.send(f"✅ Плагин `{name}` перезагружен.", ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(f"❌ Не удалось перезагрузить `{name}`: {exc}", ephemeral=True)

    @plugin_group.command(name="enable", description="Включить плагин")
    @require(Role.ADMIN)
    async def plugin_enable(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.plugin_manager.enable(name)
            await interaction.followup.send(f"✅ Плагин `{name}` включен.", ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @plugin_group.command(name="disable", description="Отключить плагин")
    @require(Role.ADMIN)
    async def plugin_disable(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.plugin_manager.disable(name)
        await interaction.followup.send(f"✅ Плагин `{name}` отключен.", ephemeral=True)


class SkyHubBot(commands.Bot):
    def __init__(
        self,
        *,
        settings: Settings,
        config: dict[str, Any],
        event_bus: EventBus,
        db: Database,
        permissions: PermissionService,
        error_handler: ErrorHandler,
        i18n: I18n,
        cache: TTLCache,
    ) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=INTENTS, help_command=None)
        self.settings = settings
        self.config = config
        self.event_bus = event_bus
        self.db = db
        self.permissions = permissions
        self.error_handler = error_handler
        self.i18n = i18n
        self.cache = cache
        self.started_at = time.time()

        self.command_registry = CommandRegistry(self, dev_guild_id=settings.dev_guild_id)
        self.plugin_manager = PluginManager(
            bot=self,
            event_bus=event_bus,
            db=db,
            permissions=permissions,
            error_handler=error_handler,
            i18n=i18n,
            cache=cache,
            global_config=config,
            plugins_root=settings.plugins_dir,
        )

        self.tree.on_error = self._on_app_command_error  # type: ignore[assignment]

    async def setup_hook(self) -> None:
        await self.add_cog(CoreCog(self))
        await self.plugin_manager.load_all()
        try:
            await self.command_registry.sync()
        except discord.HTTPException:
            logger.exception("Не удалось выполнить первичную синхронизацию slash-команд")

    async def on_ready(self) -> None:
        from app.lifecycle import on_ready

        await on_ready(self)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with self.db.session() as session:
            await GuildRepository(session).get_or_create(guild.id, guild.name)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        import sys

        exc_type, exc, _ = sys.exc_info()
        if exc is not None:
            await self.error_handler.handle(exc, event=event_method)

    async def _on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if _is_expired_interaction(error):
            # Discord даёт всего 3 секунды на первый ответ на интеракцию.
            # Если это окно упущено (нагрузка на систему, сетевой затор,
            # временная просадка у самого Discord), любой ответ -- в том
            # числе попытка сообщить об этой самой ошибке -- вернёт тот же
            # "Unknown interaction". Гонять это через полноценный
            # ErrorHandler (traceback, embed в канал ошибок) бессмысленно
            # и только пугает: чинить тут нечего, пользователю достаточно
            # просто повторить команду. Ограничиваемся тихой записью в лог.
            plugin_name = interaction.command.qualified_name if interaction.command else "?"
            logger.warning(
                "Интеракция '%s' устарела до ответа (не уложились в 3 секунды) -- "
                "пользователь может просто повторить команду",
                plugin_name,
            )
            return

        if isinstance(error, PermissionCheckFailure):
            message = self.i18n.t("error.permission_denied", required=error.required.name)
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"⏳ Подождите {error.retry_after:.0f} сек. перед повторным использованием."
        else:
            plugin_name = interaction.command.qualified_name if interaction.command else None
            error_id = await self.error_handler.handle(
                error, plugin=plugin_name, event="app_command",
                guild_id=interaction.guild_id, user_id=interaction.user.id,
            )
            message = self.i18n.t("error.generic", error_id=error_id)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
