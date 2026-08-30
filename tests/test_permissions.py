from __future__ import annotations

from unittest.mock import Mock

import discord
import pytest

from core.exceptions import PermissionDeniedError
from core.permissions import PermissionService, Role


def make_member(*, guild_owner_id=1, member_id=2, is_admin=False, role_ids=()):
    guild = Mock()
    guild.id = 999
    guild.owner_id = guild_owner_id

    member = Mock(spec=discord.Member)
    member.id = member_id
    member.guild = guild
    member.guild_permissions = Mock(administrator=is_admin)
    member.roles = [Mock(id=rid) for rid in role_ids]
    return member


def test_guild_owner_is_owner_role(permissions: PermissionService) -> None:
    owner = make_member(guild_owner_id=42, member_id=42)
    assert permissions.resolve(owner) is Role.OWNER


def test_administrator_permission_is_admin_role(permissions: PermissionService) -> None:
    admin = make_member(guild_owner_id=1, member_id=2, is_admin=True)
    assert permissions.resolve(admin) is Role.ADMIN


def test_configured_moderator_role_id_resolves_to_moderator(permissions: PermissionService) -> None:
    permissions.configure_guild(999, {Role.MODERATOR: 555})
    member = make_member(role_ids=(555,))
    assert permissions.resolve(member) is Role.MODERATOR


def test_no_matching_role_falls_back_to_member(permissions: PermissionService) -> None:
    member = make_member(role_ids=(111,))
    assert permissions.resolve(member) is Role.MEMBER


def test_non_member_resolves_to_user(permissions: PermissionService) -> None:
    assert permissions.resolve(None) is Role.USER


def test_check_raises_when_role_too_low(permissions: PermissionService) -> None:
    member = make_member()
    with pytest.raises(PermissionDeniedError):
        permissions.check(member, Role.ADMIN)


def test_check_passes_when_role_sufficient(permissions: PermissionService) -> None:
    admin = make_member(is_admin=True)
    permissions.check(admin, Role.MODERATOR)  # не должно выбросить исключение
