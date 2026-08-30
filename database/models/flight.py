"""``flight_logs`` -- личный бортжурнал пилота (ТЗ §41, "Flight logging")
и ``flight_events``/``flight_event_participants`` -- совместные вылеты
сообщества (ТЗ §41, "Flight events")."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class FlightLog(TimestampMixin, BigIntPK, Base):
    __tablename__ = "flight_logs"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    aircraft: Mapped[str] = mapped_column(String(100))
    departure_icao: Mapped[str] = mapped_column(String(10))
    arrival_icao: Mapped[str] = mapped_column(String(10))
    flight_minutes: Mapped[int] = mapped_column(Integer)
    network: Mapped[str | None] = mapped_column(String(30), nullable=True)  # vatsim / ivao / pilotedge / offline
    vatsim_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)


class FlightEvent(TimestampMixin, BigIntPK, Base):
    __tablename__ = "flight_events"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    route: Mapped[str] = mapped_column(String(100))  # напр. "ULLI -> EFHK"
    aircraft: Mapped[str] = mapped_column(String(100))
    event_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    max_participants: Mapped[int] = mapped_column(Integer, default=0)  # 0 = без лимита
    created_by_id: Mapped[int] = mapped_column(BigInteger)


class FlightEventParticipant(BigIntPK, Base):
    __tablename__ = "flight_event_participants"

    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("flight_events.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
