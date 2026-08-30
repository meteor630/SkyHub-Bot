"""Тесты для ``ManualChannelSelect`` -- замены ``discord.ui.ChannelSelect``
в ``/setup`` (см. обоснование в docstring ``plugins/server_setup/commands.py``).

Ключевая проверка: список вариантов строится напрямую из переданного
``guild.channels``, поэтому канал, добавленный туда ПОСЛЕ создания View
(эмулирует свежесозданный канал, ещё не попавший в отдельный индекс
Discord для авто-заполняемых компонентов), всё равно появляется в списке."""
from __future__ import annotations

from dataclasses import dataclass, field

import discord
import pytest

from plugins.server_setup.commands import (
    _OVERFLOW_VALUE,
    ManualChannelSelect,
    _resolve_selected_channel,
)


@dataclass
class FakeChannel:
    id: int
    name: str
    type: discord.ChannelType
    position: int = 0


@dataclass
class FakeGuild:
    channels: list[FakeChannel] = field(default_factory=list)

    def get_channel(self, channel_id: int):
        for channel in self.channels:
            if channel.id == channel_id:
                return channel
        return None


def _text(id_: int, name: str, position: int = 0) -> FakeChannel:
    return FakeChannel(id=id_, name=name, type=discord.ChannelType.text, position=position)


def test_new_channel_appears_immediately() -> None:
    """Эмулирует репортнутый баг: канал 'ккк' создан только что и
    добавлен в guild.channels -- ManualChannelSelect должен его увидеть,
    в отличие от нативного ChannelSelect (тот зависит от отдельного,
    отстающего индекса на стороне Discord, который мы не контролируем)."""
    guild = FakeGuild(channels=[_text(1, "старый-канал", position=0)])
    select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    assert {opt.value for opt in select.options} == {"1"}

    # Канал создан только что (аналог #ккк) -- добавляем в тот же live-кэш.
    guild.channels.append(_text(2, "ккк", position=1))
    select_after = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    values = {opt.value for opt in select_after.options}
    assert "2" in values, "новый канал должен появиться в списке немедленно"
    assert values == {"1", "2"}


def test_filters_by_channel_type() -> None:
    guild = FakeGuild(channels=[
        _text(1, "text-channel"),
        FakeChannel(id=2, name="voice-channel", type=discord.ChannelType.voice),
        FakeChannel(id=3, name="category", type=discord.ChannelType.category),
    ])
    select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    assert [opt.value for opt in select.options] == ["1"]


def test_sorted_by_position() -> None:
    guild = FakeGuild(channels=[_text(3, "c", position=2), _text(1, "a", position=0), _text(2, "b", position=1)])
    select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    assert [opt.value for opt in select.options] == ["1", "2", "3"]


def test_empty_channel_list_is_disabled() -> None:
    guild = FakeGuild(channels=[])
    select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    assert select.disabled is True
    assert len(select.options) == 1
    assert select.options[0].value == _OVERFLOW_VALUE


def test_overflow_beyond_25_channels_shows_sentinel() -> None:
    guild = FakeGuild(channels=[_text(i, f"channel-{i}", position=i) for i in range(30)])
    select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="test")
    assert len(select.options) == 25
    assert select.options[-1].value == _OVERFLOW_VALUE
    real_values = {opt.value for opt in select.options[:-1]}
    assert real_values == {str(i) for i in range(24)}


class _FakeResponse:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.sent.append(content)


@dataclass
class _FakeInteraction:
    guild: FakeGuild

    def __post_init__(self) -> None:
        self.response = _FakeResponse()


class _FakeSelectWithValues:
    def __init__(self, values: list[str]) -> None:
        self.values = values


async def test_resolve_selected_channel_returns_channel() -> None:
    guild = FakeGuild(channels=[_text(42, "ккк")])
    interaction = _FakeInteraction(guild=guild)
    select = _FakeSelectWithValues(["42"])

    channel = await _resolve_selected_channel(interaction, select)  # type: ignore[arg-type]
    assert channel is not None
    assert channel.id == 42
    assert not interaction.response.sent


async def test_resolve_selected_channel_handles_overflow_sentinel() -> None:
    interaction = _FakeInteraction(guild=FakeGuild(channels=[]))
    select = _FakeSelectWithValues([_OVERFLOW_VALUE])

    channel = await _resolve_selected_channel(interaction, select)  # type: ignore[arg-type]
    assert channel is None
    assert "/setup channel" in interaction.response.sent[0]


async def test_resolve_selected_channel_handles_deleted_channel() -> None:
    interaction = _FakeInteraction(guild=FakeGuild(channels=[]))
    select = _FakeSelectWithValues(["999"])

    channel = await _resolve_selected_channel(interaction, select)  # type: ignore[arg-type]
    assert channel is None
    assert "не найден" in interaction.response.sent[0]
