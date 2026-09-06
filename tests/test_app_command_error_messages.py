"""Тесты понятного сообщения для ``app_commands.TransformerError``
(``app/bot.py::_transformer_error_message``) -- такая ошибка означает,
что пользователь напечатал текст руками и нажал Enter, не выбрав
подсказку автодополнения Discord для параметра-участника/канала/роли --
это не баг бота, и канал ошибок не должен получать по ней трейсбек."""
from __future__ import annotations

from types import SimpleNamespace

import discord
from discord import app_commands

from app.bot import _transformer_error_message


def _make_error(value: str, display_name: str) -> app_commands.TransformerError:
    transformer = SimpleNamespace(_error_display_name=display_name)
    return app_commands.TransformerError(value, discord.AppCommandOptionType.user, transformer)


def test_member_transformer_error_uses_friendly_russian_word() -> None:
    message = _transformer_error_message(_make_error("epiklsd", "Member"))
    assert "участника" in message
    assert "epiklsd" in message


def test_channel_transformer_error_uses_friendly_russian_word() -> None:
    message = _transformer_error_message(_make_error("генерал", "TextChannel"))
    assert "канал" in message


def test_role_transformer_error_uses_friendly_russian_word() -> None:
    message = _transformer_error_message(_make_error("Admin", "Role"))
    assert "роль" in message


def test_unknown_transformer_falls_back_to_generic_word() -> None:
    """Незнакомый (например, будущий) тип параметра не должен ронять
    обработчик -- просто общее слово вместо конкретного."""
    message = _transformer_error_message(_make_error("x", "SomeExoticType"))
    assert "значение" in message


def test_message_hints_at_using_discord_suggestion() -> None:
    message = _transformer_error_message(_make_error("x", "Role"))
    assert "подсказки" in message.lower()
