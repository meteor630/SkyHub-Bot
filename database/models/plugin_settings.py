"""``plugin_settings`` -- включение/отключение плагина и JSON-настройки для конкретного сервера.

Это сохраняемый в БД аналог секции ``plugins:`` из ``config.yaml``:
config.yaml -- значения по умолчанию для всех серверов, а эта таблица --
переопределение для конкретного сервера, которое администратор может
включить/выключить прямо из Discord, не редактируя YAML.
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class PluginSettings(TimestampMixin, BigIntPK, Base):
    __tablename__ = "plugin_settings"
    __table_args__ = (UniqueConstraint("guild_id", "plugin_name", name="uq_plugin_settings_guild_plugin"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    plugin_name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
