"""``user_stats`` -- XP/уровень/репутация/налёт участника (ТЗ §41,
"XP / reputation"). ``flight_minutes`` синхронизируется через Event Bus
из ``plugins/flight_log`` -- ``leveling`` не импортирует этот плагин
напрямую, а подписывается на его событие ``FlightLogged``."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class UserStats(Base):
    __tablename__ = "user_stats"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    messages_count: Mapped[int] = mapped_column(Integer, default=0)
    flight_minutes: Mapped[int] = mapped_column(Integer, default=0)
    reputation: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), onupdate=lambda: dt.datetime.now(dt.UTC), default=lambda: dt.datetime.now(dt.UTC)
    )
