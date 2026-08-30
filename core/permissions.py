"""Централизованная система прав доступа (ТЗ §25).

Никто и никогда не должен писать ``if user.id == 123456`` или
``if role.name == "Admin"`` внутри плагина. Вместо этого плагины
объявляют *уровень роли*, который им требуется, и спрашивают
``PermissionService``, достаточно ли прав. Соответствие между нашими
абстрактными ролями и реальными ID ролей Discord хранится в
``guild_settings`` (настраивается прямо из Discord через ``/setup``),
а при первом запуске берётся из ``config.yaml``.
"""
from __future__ import annotations

from enum import IntEnum

import discord
from discord import app_commands

from core.exceptions import PermissionDeniedError


class Role(IntEnum):
    USER = 0
    MEMBER = 20
    SUPPORT = 40
    MODERATOR = 60
    ADMIN = 80
    OWNER = 100

    @classmethod
    def from_name(cls, name: str) -> Role:
        return cls[name.upper()]


class PermissionService:
    """Определяет :class:`Role` участника Discord и проверяет права доступа.

    Порядок определения роли (побеждает наивысшая):
      1. Владелец сервера / право Discord "Administrator" -> OWNER/ADMIN
      2. Настроенные ID ролей Discord (guild_settings.role_map),
         проверяются от OWNER до SUPPORT
      3. MEMBER для любого, кто ещё состоит в сервере
      4. USER как абсолютный минимум (например, контекст личных сообщений)
    """

    def __init__(self) -> None:
        # guild_id -> {Role: ID роли Discord}
        self._role_maps: dict[int, dict[Role, int]] = {}

    def configure_guild(self, guild_id: int, role_map: dict[Role, int]) -> None:
        """Задаёт соответствие ролей для конкретного сервера (вызывается из /setup)."""
        self._role_maps[guild_id] = dict(role_map)

    def get_role_map(self, guild_id: int) -> dict[Role, int]:
        return dict(self._role_maps.get(guild_id, {}))

    def resolve(self, member: discord.Member | discord.User | None) -> Role:
        """Определяет наивысшую роль участника по правилам выше."""
        if member is None or not isinstance(member, discord.Member):
            return Role.USER

        guild = member.guild
        if guild.owner_id == member.id:
            return Role.OWNER

        if member.guild_permissions.administrator:
            return Role.ADMIN

        role_map = self._role_maps.get(guild.id, {})
        member_role_ids = {r.id for r in member.roles}
        for level in (Role.OWNER, Role.ADMIN, Role.MODERATOR, Role.SUPPORT):
            configured_id = role_map.get(level)
            if configured_id and configured_id in member_role_ids:
                return level

        return Role.MEMBER

    def has_role(self, member: discord.Member | discord.User | None, required: Role) -> bool:
        return self.resolve(member) >= required

    def check(self, member: discord.Member | discord.User | None, required: Role) -> None:
        """Выбрасывает :class:`PermissionDeniedError`, если роли не хватает."""
        actual = self.resolve(member)
        if actual < required:
            raise PermissionDeniedError(required.name, actual.name)


class PermissionCheckFailure(app_commands.CheckFailure):
    """Выбрасывается предикатом проверки из :func:`require`. Настоящий
    подкласс ``app_commands.CheckFailure``, поэтому discord.py считает
    это ожидаемым, корректно оформленным отказом проверки, а не
    необработанным багом -- общий обработчик ``on_app_command_error``
    рисует по нему дружелюбное локализованное сообщение вместо того,
    чтобы прогонять его через ErrorHandler."""

    def __init__(self, required: Role, actual: Role) -> None:
        self.required = required
        self.actual = actual
        super().__init__(f"Требуется роль >= {required.name} (у пользователя {actual.name})")


def require(role: Role):
    """Фабрика проверки для ``app_commands``: ``@permissions.require(Role.MODERATOR)``."""

    async def predicate(interaction: discord.Interaction) -> bool:
        service: PermissionService = interaction.client.permissions  # type: ignore[attr-defined]
        actual = service.resolve(interaction.user)  # type: ignore[arg-type]
        if actual < role:
            raise PermissionCheckFailure(role, actual)
        return True

    return app_commands.check(predicate)
