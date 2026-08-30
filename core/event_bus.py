"""Асинхронная шина событий (pub/sub), разделяющая плагины друг от друга.

Особенности реализации
------------------------
* Обработчики ищутся по точному ``type(event)``. Подписка на базовый
  класс не получает события подклассов неявно — это делает доставку
  предсказуемой и O(1).
* Каждый вызов обработчика изолирован: исключение в одном подписчике
  перехватывается, направляется в ErrorHandler и *не* останавливает
  остальных подписчиков и не всплывает к тому, кто опубликовал
  событие. Именно этот механизм обеспечивает принцип "один сломанный
  плагин не может сломать другой".
* Подписки помечаются ``owner`` (именем плагина), поэтому PluginManager
  может аккуратно удалить всех слушателей, зарегистрированных плагином,
  при его остановке/перезагрузке — плагину не нужно самому хранить
  токены подписок (хотя он может, через возвращаемый объект Subscription).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from core.events import Event

logger = logging.getLogger("skyhub.event_bus")

EventT = TypeVar("EventT", bound=Event)
Handler = Callable[[Any], Awaitable[None]]

ErrorSink = Callable[[BaseException, str, str], Awaitable[None]]
"""Сигнатура: (исключение, имя_плагина_владельца, имя_класса_события) -> None"""


@dataclass(frozen=True)
class Subscription:
    event_type: type[Event]
    handler: Handler
    owner: str


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[Subscription]] = defaultdict(list)
        self._error_sink: ErrorSink | None = None

    def set_error_sink(self, sink: ErrorSink) -> None:
        """Подключает центральный обработчик ошибок. Вызывается один раз при старте бота."""
        self._error_sink = sink

    def subscribe(self, event_type: type[EventT], handler: Callable[[EventT], Awaitable[None]], *, owner: str) -> Subscription:
        sub = Subscription(event_type=event_type, handler=handler, owner=owner)  # type: ignore[arg-type]
        self._subscribers[event_type].append(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        bucket = self._subscribers.get(subscription.event_type)
        if bucket and subscription in bucket:
            bucket.remove(subscription)

    def unsubscribe_all(self, *, owner: str) -> int:
        """Удаляет все подписки, зарегистрированные ``owner``. Возвращает количество удалённых."""
        removed = 0
        for event_type, bucket in self._subscribers.items():
            before = len(bucket)
            bucket[:] = [s for s in bucket if s.owner != owner]
            removed += before - len(bucket)
        return removed

    def emit(self, event: Event) -> asyncio.Task[None]:
        """Планирует рассылку события и возвращает задачу (вызывающий код её не ждёт)."""
        return asyncio.create_task(self._dispatch(event), name=f"event:{type(event).__name__}")

    async def emit_and_wait(self, event: Event) -> None:
        """Рассылает событие синхронно, дожидаясь всех обработчиков. Полезно в тестах."""
        await self._dispatch(event)

    async def _dispatch(self, event: Event) -> None:
        subs = list(self._subscribers.get(type(event), ()))
        if not subs:
            return
        results = await asyncio.gather(
            *(self._run_one(sub, event) for sub in subs),
            return_exceptions=True,
        )
        for sub, result in zip(subs, results):
            if isinstance(result, BaseException):
                await self._report(result, sub, event)

    async def _run_one(self, sub: Subscription, event: Event) -> None:
        await sub.handler(event)

    async def _report(self, exc: BaseException, sub: Subscription, event: Event) -> None:
        logger.error(
            "Необработанное исключение в обработчике события",
            extra={"plugin": sub.owner, "event": type(event).__name__},
            exc_info=exc,
        )
        if self._error_sink is not None:
            try:
                await self._error_sink(exc, sub.owner, type(event).__name__)
            except Exception:
                logger.exception("Обработчик ошибок сам выбросил исключение при обработке ошибки")

    def subscriber_count(self, event_type: type[Event] | None = None) -> int:
        if event_type is not None:
            return len(self._subscribers.get(event_type, ()))
        return sum(len(v) for v in self._subscribers.values())
