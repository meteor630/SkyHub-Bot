"""Регрессионный тест для utils/time.py::format_latency_ms.

``discord.Client.latency`` возвращает ``float('nan')`` в первые мгновения
после подключения, до первого ответа на heartbeat -- без защиты от этого
``/status`` и консольная команда ``status`` падали с
``ValueError: cannot convert float NaN to integer``.

Отдельно от NaN, ``latency`` может быть и ``float('inf')`` (например,
пока веб-сокет ещё не установлен/переподключается) -- это тот самый
баг, что уронил ``status_dashboard`` в проде: ``round(inf * 1000)``
кидает не ``ValueError``, а ``OverflowError``, поэтому старая проверка
только на NaN его не ловила."""
from __future__ import annotations

import math

from utils.time import format_latency_ms


def test_format_latency_handles_nan_without_crashing() -> None:
    assert format_latency_ms(float("nan")) == "н/д"


def test_format_latency_handles_infinity_without_crashing() -> None:
    assert format_latency_ms(float("inf")) == "н/д"


def test_format_latency_formats_normal_value() -> None:
    assert format_latency_ms(0.042) == "42 мс"


def test_format_latency_rounds() -> None:
    assert format_latency_ms(0.0456) == "46 мс"


def test_nan_is_actually_what_discord_py_can_return() -> None:
    # документирует контракт, который мы обходим: nan не равен сам себе
    assert math.isnan(float("nan"))
