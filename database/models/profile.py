"""``user_profiles`` -- авиационный профиль участника (роль/симулятор/сеть),
идея "системы контекста пользователя" из финальной заметки клиента к ТЗ.

Выбор ``role_type`` при сохранении профиля (см. ``plugins/aviation_profile``)
приводит к выдаче соответствующей Discord-роли из
``GuildSettings.profile_role_ids`` -- аналогично тому, как ``/setup roles``
настраивает роли модерации.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    role_type: Mapped[str] = mapped_column(String(30))  # pilot / atc / virtual_airline / flight_simmer / spotter / enthusiast
    simulator: Mapped[str | None] = mapped_column(String(30), nullable=True)  # msfs / xplane / prepar3d / dcs
    network: Mapped[str | None] = mapped_column(String(30), nullable=True)  # vatsim / ivao / pilotedge
    vatsim_id: Mapped[str | None] = mapped_column(String(30), nullable=True)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), onupdate=lambda: dt.datetime.now(dt.UTC), default=lambda: dt.datetime.now(dt.UTC)
    )
