"""Хелпер повторных попыток для временных ошибок Discord API (ТЗ §35).

discord.py уже сам повторяет запросы при 429 на уровне HTTP, но
редкие 5xx-ошибки и обрывы соединения оставлены на совести вызывающего
кода. Эта функция оборачивает такие вызовы небольшим ограниченным
экспоненциальным backoff'ом, чтобы коду плагинов не приходилось везде
повторять одинаковый try/except.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import discord

logger = logging.getLogger("skyhub.retry")

T = TypeVar("T")

RETRYABLE_STATUS = {500, 502, 503, 504}


async def with_retry(
    action: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    what: str = "вызов Discord API",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except discord.HTTPException as exc:
            last_exc = exc
            retryable = exc.status in RETRYABLE_STATUS or exc.status == 429
            if not retryable or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Повторяем %s после HTTP %s (попытка %s/%s)", what, exc.status, attempt, attempts)
            await asyncio.sleep(delay)
        except (discord.ConnectionClosed, ConnectionError) as exc:
            last_exc = exc
            if attempt == attempts:
                raise
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc
