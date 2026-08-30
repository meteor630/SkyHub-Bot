"""Базовый declarative-класс и общие миксины для всех ORM-моделей (ТЗ §26)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# В продакшене (Postgres) везде используется BigInteger, но автоинкремент
# rowid в SQLite срабатывает только для колонки, объявленной как обычный
# INTEGER PRIMARY KEY -- без этого варианта вставки в SQLite (используется
# тестами) будут падать с нарушением NOT NULL для id.
_AUTOINCREMENT_ID = BigInteger().with_variant(Integer(), "sqlite")


class BigIntPK:
    id: Mapped[int] = mapped_column(_AUTOINCREMENT_ID, primary_key=True, autoincrement=True)
