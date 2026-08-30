"""Асинхронное управление движком и сессиями SQLAlchemy (ТЗ §1, §26).

Единственный экземпляр :class:`Database` создаётся при старте и
передаётся каждому плагину через :class:`core.plugin_context.PluginContext`.
Плагины обязаны работать через :meth:`Database.session` (асинхронный
контекстный менеджер) -- никогда не держать долгоживущую сессию, это
сводит на нет пул соединений и усложняет очистку при горячей перезагрузке.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models.base import Base

logger = logging.getLogger("skyhub.database")


class Database:
    def __init__(self, url: str, *, echo: bool = False, pool_size: int = 5) -> None:
        self._engine = create_async_engine(url, echo=echo, pool_size=pool_size, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        async with self._engine.connect() as conn:
            await conn.run_sync(lambda _: None)
        self._connected = True
        logger.info("Соединение с базой данных установлено")

    async def create_all(self) -> None:
        """Используется для быстрого локального/dev-запуска; в продакшене
        вместо этого нужно применять миграции Alembic (см. database/migrations)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.run_sync(lambda _: None)
            return True
        except Exception:
            logger.exception("Проверка доступности БД (ping) завершилась ошибкой")
            return False

    async def close(self) -> None:
        await self._engine.dispose()
        self._connected = False
        logger.info("Соединение с базой данных закрыто")
