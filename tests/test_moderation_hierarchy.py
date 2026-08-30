"""``/mod ban|kick|timeout|warn`` не должны позволять действовать на
себя или на участника с равным/более высоким уровнем доступа --
иначе младший модератор мог бы забанить/замьютить старшего или
другого модератора (найдено при аудите безопасности)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.permissions import Role
from plugins.moderation.commands import ModerationCog


class _FakePermissions:
    def __init__(self, roles: dict[int, Role]) -> None:
        self._roles = roles

    def resolve(self, member) -> Role:
        return self._roles[member.id]


@dataclass
class _FakeMember:
    id: int


class _FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str, ephemeral: bool = False) -> None:
        self.sent.append(content)


@dataclass
class _FakeInteraction:
    user: _FakeMember

    def __post_init__(self) -> None:
        self.followup = _FakeFollowup()


@dataclass
class _FakeCtx:
    permissions: _FakePermissions


def _cog(roles: dict[int, Role]) -> ModerationCog:
    return ModerationCog(ctx=_FakeCtx(permissions=_FakePermissions(roles)), service=None)


async def test_blocks_acting_on_self() -> None:
    cog = _cog({1: Role.MODERATOR})
    interaction = _FakeInteraction(user=_FakeMember(id=1))

    allowed = await cog._check_hierarchy(interaction, _FakeMember(id=1))
    assert allowed is False
    assert "самому себе" in interaction.followup.sent[0]


async def test_blocks_acting_on_equal_role() -> None:
    """Два модератора одного уровня не должны мочь наказывать друг друга."""
    cog = _cog({1: Role.MODERATOR, 2: Role.MODERATOR})
    interaction = _FakeInteraction(user=_FakeMember(id=1))

    allowed = await cog._check_hierarchy(interaction, _FakeMember(id=2))
    assert allowed is False
    assert "прав" in interaction.followup.sent[0]


async def test_blocks_acting_on_higher_role() -> None:
    """Модератор не может забанить администратора."""
    cog = _cog({1: Role.MODERATOR, 2: Role.ADMIN})
    interaction = _FakeInteraction(user=_FakeMember(id=1))

    allowed = await cog._check_hierarchy(interaction, _FakeMember(id=2))
    assert allowed is False


async def test_allows_acting_on_lower_role() -> None:
    cog = _cog({1: Role.MODERATOR, 2: Role.MEMBER})
    interaction = _FakeInteraction(user=_FakeMember(id=1))

    allowed = await cog._check_hierarchy(interaction, _FakeMember(id=2))
    assert allowed is True
    assert not interaction.followup.sent


async def test_owner_can_act_on_admin() -> None:
    cog = _cog({1: Role.OWNER, 2: Role.ADMIN})
    interaction = _FakeInteraction(user=_FakeMember(id=1))

    allowed = await cog._check_hierarchy(interaction, _FakeMember(id=2))
    assert allowed is True
