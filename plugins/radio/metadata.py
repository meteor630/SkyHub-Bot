"""Извлечение метаданных и обложки из аудиофайла (ID3/Vorbis/MP4-теги)
через ``mutagen``, чтобы карточка "сейчас играет" показывала настоящие
название/исполнителя/композитора/битрейт трека, а не только имя файла.

Разные форматы хранят одни и те же поля под разными именами (ID3 --
``TIT2``/``TPE1``/``TCOM``, Vorbis/FLAC/OGG -- обычные строковые теги
``title``/``artist``/``composer``, MP4/M4A -- свои коды атомов), поэтому
``mutagen.File(easy=True)`` используется как основной, максимально
единообразный путь, а сырой ``mutagen.File()`` -- отдельно, только для
извлечения обложки (EasyID3 её не отдаёт).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.flac import Picture
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4

logger = logging.getLogger("skyhub.radio.metadata")


@dataclass
class AudioMetadata:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    composer: str | None = None
    duration_seconds: float | None = None
    bitrate_kbps: int | None = None
    cover_bytes: bytes | None = None
    cover_ext: str | None = None  # "jpg" / "png"


def _first(tags, *keys: str) -> str | None:
    if tags is None:
        return None
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            item = value[0] if isinstance(value, list) else value
            text = str(item).strip()
            if text:
                return text
    return None


def _extract_cover(path: Path) -> tuple[bytes | None, str | None]:
    try:
        raw = mutagen.File(path)
    except Exception:  # noqa: BLE001
        return None, None
    if raw is None:
        return None, None

    # ID3 (mp3): обложка -- один из фреймов APIC:*
    if isinstance(raw.tags, ID3):
        for frame in raw.tags.values():
            if isinstance(frame, APIC):
                ext = "png" if "png" in frame.mime else "jpg"
                return frame.data, ext

    # FLAC / OGG (Vorbis comments): список mutagen.flac.Picture в .pictures
    pictures = getattr(raw, "pictures", None)
    if pictures:
        pic: Picture = pictures[0]
        ext = "png" if "png" in pic.mime else "jpg"
        return pic.data, ext

    # MP4 / M4A: обложка в атоме "covr"
    if isinstance(raw, MP4) and raw.tags and "covr" in raw.tags:
        covers = raw.tags["covr"]
        if covers:
            cover = covers[0]
            ext = "png" if cover.imageformat == cover.FORMAT_PNG else "jpg"
            return bytes(cover), ext

    return None, None


def extract_metadata(path: Path) -> AudioMetadata:
    """Читает теги + техническую информацию файла. Никогда не бросает
    исключение -- в худшем случае возвращает пустой :class:`AudioMetadata`,
    чтобы отсутствие/повреждённость тегов не мешало добавить трек в плейлист."""
    result = AudioMetadata()

    try:
        easy = mutagen.File(path, easy=True)
    except Exception:
        logger.warning("Не удалось прочитать теги файла %s", path, exc_info=True)
        easy = None

    if easy is not None:
        tags = easy.tags
        result.title = _first(tags, "title")
        result.artist = _first(tags, "artist")
        result.album = _first(tags, "album")
        result.composer = _first(tags, "composer")
        if easy.info is not None:
            result.duration_seconds = getattr(easy.info, "length", None)
            bitrate = getattr(easy.info, "bitrate", None)
            if bitrate:
                result.bitrate_kbps = round(bitrate / 1000)

    try:
        result.cover_bytes, result.cover_ext = _extract_cover(path)
    except Exception:
        logger.warning("Не удалось извлечь обложку из файла %s", path, exc_info=True)

    return result


def format_duration_long(seconds: float | None) -> str | None:
    """``2 min 16 sec`` -- в стиле референса пользователя."""
    if seconds is None:
        return None
    total = round(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes} мин {secs} сек"
    return f"{secs} сек"
