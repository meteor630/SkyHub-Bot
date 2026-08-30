"""Модели ``deleted_messages`` и ``edited_messages`` (ТЗ §12, §13, §26)."""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class DeletedMessage(TimestampMixin, BigIntPK, Base):
    __tablename__ = "deleted_messages"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    author_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    bulk: Mapped[bool] = mapped_column(default=False)


class EditedMessage(TimestampMixin, BigIntPK, Base):
    __tablename__ = "edited_messages"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    author_id: Mapped[int] = mapped_column(BigInteger)
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
