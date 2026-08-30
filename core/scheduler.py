"""Лёгкие вспомогательные функции планирования поверх asyncio.

Это не полноценная очередь задач -- фоновая работа SkyHub бывает либо
"выполнять это вечно каждые N секунд" (проверки здоровья, зачистка
осиротевших голосовых каналов), либо "выполнить один раз после
небольшой задержки" (удалить опустевший временный голосовой канал
через 5-15 секунд, ТЗ §17). Оба случая настолько простые, что
подключение APScheduler/Celery было бы избыточным усложнением для
текущих задач; архитектура не мешает заменить это позже.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("skyhub.scheduler")


class Scheduler:
    """Владеет набором задач, чтобы вызывающий код (обычно PluginContext)
    мог отменить всё, что он запустил, одним вызовом."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def run_every(
        self,
        interval_seconds: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str | None = None,
        run_immediately: bool = False,
    ) -> asyncio.Task:
        """Запускает корутину повторно с заданным интервалом."""

        async def _loop() -> None:
            if not run_immediately:
                await asyncio.sleep(interval_seconds)
            while True:
                try:
                    await coro_factory()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Периодическая задача %s выбросила исключение", name)
                await asyncio.sleep(interval_seconds)

        return self._track(asyncio.create_task(_loop(), name=name))

    def run_after(
        self,
        delay_seconds: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str | None = None,
    ) -> asyncio.Task:
        """Запускает корутину один раз после заданной задержки."""

        async def _delayed() -> None:
            await asyncio.sleep(delay_seconds)
            await coro_factory()

        return self._track(asyncio.create_task(_delayed(), name=name))

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def cancel_all(self) -> None:
        """Отменяет все запланированные этим Scheduler'ом задачи."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
