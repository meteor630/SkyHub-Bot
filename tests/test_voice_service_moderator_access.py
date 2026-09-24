"""Тесты доступа роли модератора к временным голосовым комнатам
(``services/voice_service.py::VoiceService.create_room``) -- роль
получает СВОЙ overwrite ``connect=True`` на канале при создании, поэтому
продолжает заходить свободно даже после того, как владелец закроет
комнату (``/voice lock``) -- overwrite конкретной роли всегда важнее
общего overwrite'а @everyone у Discord, close_room() overwrite роли
никогда не трогает."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import discord

from services.voice_service import VoiceService


class _FakeSessionCtx:
    def __init__(self) -> None:
        self.session = Mock()
        self.session.add = Mock()
        self.session.flush = AsyncMock()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args: object) -> bool:
        return False


def _make_guild(*, moderator_role: Mock | None) -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.default_role = Mock(spec=discord.Role)
    guild.get_role = Mock(return_value=moderator_role)
    channel = Mock(spec=discord.VoiceChannel)
    channel.id = 123
    guild.create_voice_channel = AsyncMock(return_value=channel)
    return guild


def _make_service() -> VoiceService:
    db = Mock()
    db.session = Mock(return_value=_FakeSessionCtx())
    return VoiceService(db)


async def test_create_room_grants_moderator_role_connect_when_role_configured() -> None:
    moderator_role = Mock(spec=discord.Role)
    guild = _make_guild(moderator_role=moderator_role)
    member = Mock(spec=discord.Member, guild=guild, display_name="Test")

    await _make_service().create_room(member=member, category=None, moderator_role_id=555)

    guild.get_role.assert_called_once_with(555)
    overwrites = guild.create_voice_channel.await_args.kwargs["overwrites"]
    assert overwrites[moderator_role].connect is True
    assert overwrites[moderator_role].view_channel is True


async def test_create_room_without_moderator_role_id_adds_no_extra_overwrite() -> None:
    guild = _make_guild(moderator_role=None)
    member = Mock(spec=discord.Member, guild=guild, display_name="Test")

    await _make_service().create_room(member=member, category=None)

    guild.get_role.assert_not_called()
    overwrites = guild.create_voice_channel.await_args.kwargs["overwrites"]
    assert set(overwrites) == {guild.default_role, member}


async def test_create_room_ignores_unknown_moderator_role_id() -> None:
    """Роль была настроена (/setup roles), но с тех пор удалена с
    сервера -- не должно падать, просто без лишнего overwrite'а."""
    guild = _make_guild(moderator_role=None)  # guild.get_role возвращает None -- роли больше нет
    member = Mock(spec=discord.Member, guild=guild, display_name="Test")

    await _make_service().create_room(member=member, category=None, moderator_role_id=999)

    overwrites = guild.create_voice_channel.await_args.kwargs["overwrites"]
    assert set(overwrites) == {guild.default_role, member}
