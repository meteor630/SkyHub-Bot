"""``tickets`` -- система обращений (ТЗ §41, "Support / Tickets"): каждое
обращение -- приватный текстовый канал, создаваемый по кнопке."""
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
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
