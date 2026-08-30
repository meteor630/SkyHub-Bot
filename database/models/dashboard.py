"""``dashboard_messages`` -- ID одного редактируемого "живого" сообщения на
сервер и на назначение (статус бота, текущий трек радио и т.п.).

Общий механизм для любой функции вида "одно сообщение в канале, которое
мы правим на месте вместо того, чтобы спамить новыми": вместо того,
чтобы каждая такая функция сама хранила и восстанавливала после
перезапуска ID своего сообщения, это делается в одном месте.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class DashboardMessage(TimestampMixin, BigIntPK, Base):
    __tablename__ = "dashboard_messages"
    __table_args__ = (UniqueConstraint("guild_id", "kind", name="uq_dashboard_messages_guild_kind"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(50))  # "status" / "radio_now_playing" / ...
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
