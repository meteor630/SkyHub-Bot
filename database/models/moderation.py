"""Модель ``moderation_actions`` (ТЗ §11, §26)."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class ModerationAction(TimestampMixin, BigIntPK, Base):
    __tablename__ = "moderation_actions"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(50))  # ban/unban/kick/timeout/mute/warn/role_add/...
    moderator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
