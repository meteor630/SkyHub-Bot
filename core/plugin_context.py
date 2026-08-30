"""Всё, что получает плагин в момент создания.

``PluginContext`` — намеренно *единственный* способ, которым плагин
взаимодействует с ботом, event bus, базой данных или конфигурацией.
Каждый метод регистрации запоминает, что именно он создал, под именем
плагина, чтобы :meth:`release` могла потом всё это отменить — это и
есть основа безопасной горячей перезагрузки (ТЗ §5): автору плагина не
нужно вручную помнить об отмене регистрации чего-либо.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from discord import app_commands
from discord.ext import commands

from core.event_bus import EventBus, Subscription
from core.events import Event

if TYPE_CHECKING:
    from core.error_handler import ErrorHandler
    from core.permissions import PermissionService
    from database.database import Database
    from utils.cache import TTLCache
    from utils.i18n import I18n

EventT = TypeVar("EventT", bound=Event)


class PluginLoggerAdapter(logging.LoggerAdapter):
    """Добавляет имя плагина к каждой лог-записи автоматически."""

    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("plugin", self.extra.get("plugin"))
        return msg, kwargs


class PluginContext:
    def __init__(
        self,
        *,
        plugin_name: str,
        bot: commands.Bot,
        event_bus: EventBus,
        db: Database,
        config: dict[str, Any],
        global_config: dict[str, Any],
        permissions: PermissionService,
        error_handler: ErrorHandler,
        i18n: I18n,
        cache: TTLCache,
    ) -> None:
        self.plugin_name = plugin_name
        self.bot = bot
        self.event_bus = event_bus
        self.db = db
        self.config = config
        self.global_config = global_config
        self.permissions = permissions
        self.error_handler = error_handler
        self.i18n = i18n
        self.cache = cache

        self._cog_names: list[str] = []
        self._standalone_commands: list[str] = []
        self._tasks: set[asyncio.Task] = set()
        self._subscriptions: list[Subscription] = []
        self._guild_config = None

    def guild_config(self):
        """Отложенно создаваемый :class:`services.guild_config_service.GuildConfigService`,
        общий для любого плагина, которому нужны ID каналов/ролей
        (сначала БД, затем YAML как запасной вариант)."""
        if self._guild_config is None:
            from services.guild_config_service import GuildConfigService

            self._guild_config = GuildConfigService(self.db, self.global_config, self.cache)
        return self._guild_config

    # -- логирование -----------------------------------------------------

    def get_logger(self) -> logging.LoggerAdapter:
        base = logging.getLogger(f"skyhub.plugins.{self.plugin_name}")
        return PluginLoggerAdapter(base, {"plugin": self.plugin_name})

    # -- регистрация в Discord -----------------------------------------

    async def add_cog(self, cog: commands.Cog) -> None:
        """Регистрирует cog в боте и запоминает его для последующей очистки."""
        await self.bot.add_cog(cog)
        self._cog_names.append(cog.qualified_name)

    def add_command(self, command: app_commands.Command | app_commands.Group) -> None:
        """Регистрирует отдельную (не через cog) slash-команду или группу."""
        self.bot.tree.add_command(command)
        self._standalone_commands.append(command.name)

    # -- event bus -----------------------------------------------------

    def subscribe(self, event_type: type[EventT], handler: Callable[[EventT], Awaitable[None]]) -> Subscription:
        """Подписывается на событие от имени этого плагина (для автоочистки при выгрузке)."""
        return self.event_bus.subscribe(event_type, handler, owner=self.plugin_name)  # type: ignore[arg-type]

    def emit(self, event: Event) -> None:
        """Публикует событие в event bus."""
        self.event_bus.emit(event)

    # -- фоновая работа -----------------------------------------------

    def create_task(self, coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task:
        """Создаёт фоновую задачу, которая будет автоматически отменена при
        остановке/перезагрузке плагина."""
        task = asyncio.create_task(coro, name=name or f"{self.plugin_name}-task")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- отправка ошибок -------------------------------------------------

    async def report_error(self, exc: BaseException, *, event: str | None = None, **context: Any) -> str:
        """Передаёт исключение в централизованный ErrorHandler и возвращает error_id."""
        return await self.error_handler.handle(exc, plugin=self.plugin_name, event=event, **context)

    # -- очистка (вызывается PluginManager'ом, не самим плагином) --------

    async def release(self) -> None:
        """Отменяет все задачи, отписывает все подписки на события и
        удаляет все cog'и/команды, зарегистрированные этим плагином."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        self.event_bus.unsubscribe_all(owner=self.plugin_name)
        self._subscriptions.clear()

        for cog_name in list(self._cog_names):
            try:
                await self.bot.remove_cog(cog_name)
            except Exception:
                logging.getLogger("skyhub.plugin_manager").exception(
                    "Не удалось удалить cog %s плагина %s", cog_name, self.plugin_name
                )
        self._cog_names.clear()

        for command_name in list(self._standalone_commands):
            try:
                self.bot.tree.remove_command(command_name)
            except Exception:  # noqa: BLE001
                pass
        self._standalone_commands.clear()

    @property
    def tracked_summary(self) -> dict[str, int]:
        """Сводка отслеживаемых ресурсов -- удобно для диагностики утечек."""
        return {
            "cogs": len(self._cog_names),
            "commands": len(self._standalone_commands),
            "tasks": len(self._tasks),
            "event_subscriptions": self.event_bus.subscriber_count(),
        }
