"""``audit_logs`` -- единый таймлайн событий по каждому пользователю (ТЗ §26, идея клиента №2)."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class AuditLog(TimestampMixin, BigIntPK, Base):
    __tablename__ = "audit_logs"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(String(500))
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
