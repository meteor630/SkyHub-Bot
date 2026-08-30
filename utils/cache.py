"""Небольшой TTL-кэш в памяти (ТЗ §36).

Намеренно не является источником истины: любое значение отсюда должно
снова получаться из PostgreSQL после перезапуска или промаха кэша.
Используется в основном для чтения ``guild_settings``, что происходит
почти при каждой команде.
"""
from __future__ import annotations

import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: K, value: V) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: K) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
