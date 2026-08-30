"""Базовый класс репозитория -- держит SQL/ORM-логику отдельно от кода
плагинов (ТЗ §44: никогда не смешивать логику Discord, БД и бизнес-логику
в одном файле).
"""
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
