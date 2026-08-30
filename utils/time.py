"""Небольшие хелперы для работы со временем, общие для всех плагинов."""
from __future__ import annotations

import datetime as dt
import math


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def format_latency_ms(latency_seconds: float) -> str:
    """Форматирует задержку до шлюза Discord в миллисекундах.

    ``discord.Client.latency`` возвращает ``float('nan')``, пока бот ещё
    не получил ни одного ответа на heartbeat (самые первые мгновения
    после подключения) -- без этой проверки ``/status`` и консольная
    команда ``status``, вызванные в этот момент, падали с
    ``ValueError: cannot convert float NaN to integer``.
    """
    if math.isnan(latency_seconds):
        return "н/д"
    return f"{round(latency_seconds * 1000)} мс"


def format_duration(seconds: float) -> str:
    """Форматирует длительность в компактном виде на русском (напр. ``2д 3ч 5м``)."""
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if seconds or not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


def discord_relative(timestamp: dt.datetime) -> str:
    """Собственная разметка Discord для относительного времени ``<t:...:R>``."""
    return f"<t:{int(timestamp.timestamp())}:R>"


def discord_full(timestamp: dt.datetime) -> str:
    return f"<t:{int(timestamp.timestamp())}:f>"
