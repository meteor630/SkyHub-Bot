"""Тесты для ``ManualRoleSelect`` -- замены ``discord.ui.RoleSelect`` в
``/setup`` (та же причина, что и у ``ManualChannelSelect``, см.
docstring ``plugins/server_setup/commands.py``: нативный компонент
показывал не все существующие роли сервера)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import discord
import pytest

from plugins.server_setup.commands import (
    _OVERFLOW_VALUE,
    ManualRoleSelect,
    _resolve_selected_role,
    _resolve_selected_roles,
)


@dataclass
class FakeRole:
    id: int
    name: str
    position: int = 0

    def is_default(self) -> bool:
        return self.name == "@everyone"


@dataclass
class FakeGuild:
    roles: list[FakeRole] = field(default_factory=list)

    def get_role(self, role_id: int):
        for role in self.roles:
            if role.id == role_id:
                return role
        return None


def test_excludes_everyone_role() -> None:
    guild = FakeGuild(roles=[FakeRole(1, "@everyone", position=0), FakeRole(2, "Moderator", position=1)])
    select = ManualRoleSelect(guild=guild, placeholder="test")
    assert [opt.value for opt in select.options] == ["2"]


def test_all_roles_appear_even_when_many() -> None:
    """Точное воспроизведение бага: раньше нативный RoleSelect показывал
    не все роли сервера. Тут все не-@everyone роли должны попасть в
    список (пока их не больше 25)."""
    guild = FakeGuild(roles=[FakeRole(1, "@everyone", position=0)] + [
        FakeRole(i, f"role-{i}", position=i) for i in range(2, 20)
    ])
    select = ManualRoleSelect(guild=guild, placeholder="test")
    values = {opt.value for opt in select.options}
    assert values == {str(i) for i in range(2, 20)}


def test_sorted_highest_position_first() -> None:
    guild = FakeGuild(roles=[
        FakeRole(1, "@everyone", position=0),
        FakeRole(2, "low", position=1),
        FakeRole(3, "high", position=3),
        FakeRole(4, "mid", position=2),
    ])
    select = ManualRoleSelect(guild=guild, placeholder="test")
    assert [opt.value for opt in select.options] == ["3", "4", "2"]


def test_overflow_beyond_25_roles_shows_sentinel() -> None:
    guild = FakeGuild(roles=[FakeRole(1, "@everyone", position=0)] + [
        FakeRole(i, f"role-{i}", position=i) for i in range(2, 32)  # 30 не-@everyone ролей
    ])
    select = ManualRoleSelect(guild=guild, placeholder="test")
    assert len(select.options) == 25
    assert select.options[-1].value == _OVERFLOW_VALUE


def test_empty_role_list_is_disabled() -> None:
    guild = FakeGuild(roles=[FakeRole(1, "@everyone", position=0)])
    select = ManualRoleSelect(guild=guild, placeholder="test")
    assert select.disabled is True
    assert select.options[0].value == _OVERFLOW_VALUE


def test_default_role_ids_marked_selected() -> None:
    guild = FakeGuild(roles=[FakeRole(1, "@everyone"), FakeRole(2, "Pilot", position=1), FakeRole(3, "ATC", position=2)])
    select = ManualRoleSelect(guild=guild, placeholder="test", min_values=0, max_values=25, default_role_ids=(2,))
    defaults = {opt.value for opt in select.options if opt.default}
    assert defaults == {"2"}


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


async def test_resolve_selected_role_returns_role() -> None:
    guild = FakeGuild(roles=[FakeRole(42, "Moderator")])
    interaction = _FakeInteraction(guild=guild)
    select = _FakeSelectWithValues(["42"])

    role = await _resolve_selected_role(interaction, select)  # type: ignore[arg-type]
    assert role is not None
    assert role.id == 42
    assert not interaction.response.sent


async def test_resolve_selected_role_handles_overflow_sentinel() -> None:
    interaction = _FakeInteraction(guild=FakeGuild(roles=[]))
    select = _FakeSelectWithValues([_OVERFLOW_VALUE])

    role = await _resolve_selected_role(interaction, select)  # type: ignore[arg-type]
    assert role is None
    assert "/setup role" in interaction.response.sent[0]


async def test_resolve_selected_roles_filters_overflow_but_keeps_real_selections() -> None:
    guild = FakeGuild(roles=[FakeRole(1, "Pilot"), FakeRole(2, "ATC")])
    interaction = _FakeInteraction(guild=guild)
    select = _FakeSelectWithValues(["1", _OVERFLOW_VALUE, "2"])

    roles = await _resolve_selected_roles(interaction, select)  # type: ignore[arg-type]
    assert {r.id for r in roles} == {1, 2}


async def test_resolve_selected_roles_empty_selection_clears_list() -> None:
    interaction = _FakeInteraction(guild=FakeGuild(roles=[]))
    select = _FakeSelectWithValues([])

    roles = await _resolve_selected_roles(interaction, select)  # type: ignore[arg-type]
    assert roles == []
