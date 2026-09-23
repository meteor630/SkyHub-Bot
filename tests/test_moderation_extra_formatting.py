"""Тесты форматирования поля "Дополнительно" в логе модерации
(``plugins/moderation/plugin.py``) -- раньше показывало сырые значения
как есть (напр. ``until: 2026-09-23 18:59:40.668000+00:00``), теперь --
человекочитаемые подписи и, для ``until``, родную временную метку
Discord (``<t:...:f>``), которую каждый зритель видит в СВОЁМ локальном
часовом поясе (у модераторов -- МСК)."""
from __future__ import annotations

from plugins.moderation.plugin import _format_extra, _format_extra_value


def test_until_becomes_discord_timestamp_not_raw_python_string() -> None:
    value = _format_extra_value("until", "2026-09-23 18:59:40.668000+00:00")
    assert value == "<t:1790189980:f>"
    assert "668000" not in value  # микросекунды из сырой строки не должны просочиться


def test_until_falls_back_to_raw_string_on_unparsable_value() -> None:
    assert _format_extra_value("until", "не дата") == "не дата"


def test_minutes_gets_a_unit_suffix() -> None:
    assert _format_extra_value("minutes", 30) == "30 мин."


def test_unknown_key_is_shown_as_plain_string() -> None:
    assert _format_extra_value("role", "Pilot") == "Pilot"


def test_format_extra_uses_friendly_russian_labels() -> None:
    text = _format_extra({"until": "2026-09-23 18:59:40.668000+00:00"})
    assert text == "**Тайм-аут до:** <t:1790189980:f>"


def test_format_extra_joins_multiple_fields_on_separate_lines() -> None:
    text = _format_extra({"before": "Old", "after": "New"})
    assert text == "**Было:** Old\n**Стало:** New"
