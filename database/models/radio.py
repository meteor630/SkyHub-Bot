"""``radio_tracks`` -- плейлист непрерывного "радио" для голосового канала.

Каждая запись -- один загруженный администратором аудиофайл, сохранённый
локально на диске (см. ``plugins/radio/plugin.py``); ``position``
определяет порядок циклического воспроизведения. Поля ``artist``/
``album``/``composer``/``duration_seconds``/``bitrate_kbps``/``cover_path``
заполняются автоматически из тегов файла при добавлении
(``plugins/radio/metadata.py``) -- вручную их указывать не нужно.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, BigIntPK, TimestampMixin


class RadioTrack(TimestampMixin, BigIntPK, Base):
    __tablename__ = "radio_tracks"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str] = mapped_column(String(500))  # путь к файлу на диске, относительно data/radio/
    added_by_id: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer, default=0)

    artist: Mapped[str | None] = mapped_column(String(200), nullable=True)
    album: Mapped[str | None] = mapped_column(String(300), nullable=True)
    composer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # тоже относительно data/radio/
