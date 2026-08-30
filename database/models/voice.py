"""Модели ``temporary_voice_channels`` и ``voice_channel_owners`` (ТЗ §15-18, §26)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, BigIntPK, TimestampMixin


class TemporaryVoiceChannel(TimestampMixin, BigIntPK, Base):
    __tablename__ = "temporary_voice_channels"
    # Комнату может попытаться удалить одновременно два независимых пути --
    # кнопка "Удалить" и автоматическая очистка опустевшего канала по
    # таймеру (ТЗ §17) -- это ожидаемая, безобидная гонка (Postgres не
    # даст испортить данные), но без этой настройки SQLAlchemy на втором
    # DELETE предупреждает, что не нашёл строку для удаления.
    __mapper_args__ = {"confirm_deleted_rows": False}

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(20), default="public")  # public / private / locked (публичная/скрытая/закрытая)
    name: Mapped[str] = mapped_column(String(100), default="")
    member_limit: Mapped[int] = mapped_column(default=0)

    owners: Mapped[list[VoiceChannelOwner]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class VoiceChannelOwner(BigIntPK, Base):
    """История владения временным голосовым каналом (создание / передача)."""

    __tablename__ = "voice_channel_owners"
    __mapper_args__ = {"confirm_deleted_rows": False}  # см. комментарий у TemporaryVoiceChannel

    temp_channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("temporary_voice_channels.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    became_owner_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    left_owner_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    channel: Mapped[TemporaryVoiceChannel] = relationship(back_populates="owners")
