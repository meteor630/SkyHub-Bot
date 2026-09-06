"""``tickets`` -- система обращений (ТЗ §41, "Support / Tickets"): у
каждого обращения приватный текстовый канал (видит только автор +
сапорт/админы) И, если настроен ``tickets_forum_channel_id``, пост в
приватном форуме для сапорта -- бот зеркалит сообщения между ними."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"


class Ticket(TimestampMixin, BigIntPK, Base):
    __tablename__ = "tickets"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    # Пост в форуме для сапорта, привязанный к этому тикету (см. модуль-
    # докстринг) -- None, если tickets_forum_channel_id ещё не настроен.
    forum_thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
