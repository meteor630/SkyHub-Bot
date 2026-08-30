"""Модели ``guilds`` и ``guild_settings`` (ТЗ §26)."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin


class Guild(TimestampMixin, Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # ID сервера Discord
    name: Mapped[str] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(String(8), default="ru")

    settings: Mapped[GuildSettings] = relationship(back_populates="guild", uselist=False, cascade="all, delete-orphan")


class GuildSettings(Base):
    """Всё, что настраивается через ``/setup`` (ТЗ §24, идея клиента №1)."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)

    welcome_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    moderation_logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deleted_messages_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    edited_messages_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    member_logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audit_logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    temporary_voice_creator_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    temporary_voice_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    radio_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    radio_text_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    flight_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tickets_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    moderator_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    support_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Роли, выдачу/снятие которых НЕ нужно писать в лог модерации --
    # самовыдаваемые/массовые роли иначе заваливают канал логов сотнями
    # записей в день (клиентский запрос).
    ignored_log_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    # {"pilot": role_id, "atc": role_id, ...} -- см. plugins/aviation_profile.
    profile_role_ids: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)

    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    guild: Mapped[Guild] = relationship(back_populates="settings")
