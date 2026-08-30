"""Модель ``users`` (ТЗ §26) -- одна строка на каждого встреченного пользователя Discord."""
from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # ID пользователя Discord
    username: Mapped[str] = mapped_column(String(200))
    discriminator: Mapped[str | None] = mapped_column(String(8), nullable=True)
