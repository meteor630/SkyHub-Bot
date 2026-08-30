"""Централизованная система обработки ошибок (ТЗ §20-23).

Каждое исключение, возникшее где угодно в боте — внутри slash-команды
плагина, обработчика event bus или фоновой задачи — в итоге проходит
через :meth:`ErrorHandler.handle`. Оттуда оно всегда:

1. Получает стабильный, легко ищущийся ``error_id`` (``ERR-ГГГГММДД-XXXXXX``).
2. Логируется в консоль с полным traceback.
3. (С ограничением частоты) публикуется как красивый embed в
   настроенный Discord-канал ошибок, чтобы операторам не приходилось
   читать логи сервера напрямую.

Ничто здесь никогда не выбрасывает исключение обратно вызывающему —
сломанный путь обработки ошибок не должен становиться второй аварией.
"""
from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord

from utils.ids import new_error_id

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = logging.getLogger("skyhub.errors")

ChannelResolver = Callable[[int | None], Awaitable["discord.abc.Messageable | None"]]


@dataclass
class ErrorReport:
    error_id: str
    plugin: str | None
    event: str | None
    function: str | None
    exception: BaseException
    guild_id: int | None = None
    user_id: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def traceback_text(self) -> str:
        return "".join(
            traceback.format_exception(type(self.exception), self.exception, self.exception.__traceback__)
        )


class ErrorHandler:
    """Единая точка входа для всех ошибок бота. См. докстринг модуля."""

    #: Не публиковать одну и ту же комбинацию (плагин, событие, тип
    #: исключения) в Discord чаще, чем раз в столько секунд -- иначе
    #: сломанный обработчик, срабатывающий на каждом событии шлюза,
    #: завалит канал ошибок спамом.
    DEDUPE_WINDOW_SECONDS = 60.0

    def __init__(self, *, channel_resolver: ChannelResolver | None = None, event_bus: EventBus | None = None) -> None:
        self._channel_resolver = channel_resolver
        self._event_bus = event_bus
        self._recent: dict[tuple[str | None, str | None, str], float] = {}

    def set_channel_resolver(self, resolver: ChannelResolver) -> None:
        self._channel_resolver = resolver

    def set_event_bus(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(
        self,
        exc: BaseException,
        *,
        plugin: str | None = None,
        event: str | None = None,
        function: str | None = None,
        guild_id: int | None = None,
        user_id: int | None = None,
        **context: Any,
    ) -> str:
        """Обрабатывает исключение: логирует, публикует событие, отправляет
        в Discord (с ограничением частоты). Возвращает ``error_id``."""
        report = ErrorReport(
            error_id=new_error_id(),
            plugin=plugin,
            event=event,
            function=function,
            exception=exc,
            guild_id=guild_id,
            user_id=user_id,
            context=context,
        )
        self._log_console(report)
        if self._event_bus is not None and plugin is not None:
            from core.events import PluginError as PluginErrorEvent

            self._event_bus.emit(
                PluginErrorEvent(
                    plugin=plugin,
                    error_id=report.error_id,
                    message=str(exc),
                    guild_id=guild_id,
                )
            )
        if self._should_post(report):
            await self._post_discord(report)
        return report.error_id

    def _log_console(self, report: ErrorReport) -> None:
        logger.error(
            "%s в plugin=%s event=%s function=%s: %s",
            report.error_id,
            report.plugin,
            report.event,
            report.function,
            report.exception,
            extra={
                "plugin": report.plugin,
                "event": report.event,
                "guild_id": report.guild_id,
                "user_id": report.user_id,
                "request_id": report.error_id,
            },
            exc_info=report.exception,
        )

    def _should_post(self, report: ErrorReport) -> bool:
        """Проверяет, не публиковали ли мы такую же ошибку слишком недавно."""
        key = (report.plugin, report.event, type(report.exception).__name__)
        now = report.created_at
        last = self._recent.get(key)
        self._recent[key] = now
        if last is not None and (now - last) < self.DEDUPE_WINDOW_SECONDS:
            return False
        return True

    async def _post_discord(self, report: ErrorReport) -> None:
        if self._channel_resolver is None:
            return
        try:
            channel = await self._channel_resolver(report.guild_id)
        except Exception:
            logger.exception("Не удалось определить Discord-канал для ошибок")
            return
        if channel is None:
            return

        tb = report.traceback_text
        if len(tb) > 1500:
            tb = tb[-1500:]

        embed = discord.Embed(
            title="🚨 ОШИБКА БОТА",
            description=f"```py\n{tb}\n```",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Плагин", value=f"`{report.plugin or '—'}`", inline=True)
        embed.add_field(name="Событие / Функция", value=f"`{report.event or report.function or '—'}`", inline=True)
        embed.add_field(name="Исключение", value=f"`{type(report.exception).__name__}`", inline=True)
        if report.user_id:
            embed.add_field(name="Пользователь", value=f"<@{report.user_id}>", inline=True)
        embed.add_field(name="ID ошибки", value=f"`{report.error_id}`", inline=False)
        embed.set_footer(text="SkyHub Bot · Лог ошибок")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Не удалось доставить embed с ошибкой в Discord-канал ошибок")
