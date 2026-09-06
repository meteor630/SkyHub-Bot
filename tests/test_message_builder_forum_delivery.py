"""Тесты доставки отрендеренных страниц в обычный канал / пост форума
(``plugins/message_builder/commands.py::_deliver_pages``) -- на фейковых
объектах (``Mock(spec=...)`` заставляет ``isinstance`` отработать
правильно), без настоящего discord.py Guild/подключения."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import discord

from plugins.message_builder.commands import (
    _TEXT_CHANNEL_TYPES,
    _TEXT_OR_FORUM_CHANNEL_TYPES,
    _deliver_pages,
    _forum_missing_topic_error,
    _guild_channel_choices,
    _resolve_channel_choice,
    _resolve_mentions,
)


def _make_channel(spec: type, *, id: int, name: str, position: int, type_: discord.ChannelType) -> Mock:
    channel = Mock(spec=spec)
    channel.id = id
    channel.name = name
    channel.position = position
    channel.type = type_
    return channel


def _make_role(*, id: int, name: str) -> Mock:
    role = Mock(spec=discord.Role)
    role.id = id
    role.name = name
    role.mention = f"<@&{id}>"
    return role


def _make_member(*, id: int, name: str, display_name: str | None = None, global_name: str | None = None) -> Mock:
    member = Mock(spec=discord.Member)
    member.id = id
    member.name = name
    member.display_name = display_name or name
    member.global_name = global_name
    member.mention = f"<@{id}>"
    return member


async def test_deliver_pages_to_regular_channel_sends_each_page_in_order() -> None:
    channel = Mock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    pages = [["embed1"], ["embed2"]]

    destination = await _deliver_pages(channel, pages, topic=None)

    assert destination is channel
    assert channel.send.await_args_list == [
        ((), {"content": None, "embeds": ["embed1"]}),
        ((), {"embeds": ["embed2"]}),
    ]


async def test_deliver_pages_puts_content_only_on_first_message() -> None:
    """content (готовые пинги, см. _resolve_mentions) не должен
    дублироваться на каждой странице длинного объявления."""
    channel = Mock(spec=discord.TextChannel)
    channel.send = AsyncMock()

    await _deliver_pages(channel, [["embed1"], ["embed2"]], topic=None, content="<@&1> <@2>")

    assert channel.send.await_args_list == [
        ((), {"content": "<@&1> <@2>", "embeds": ["embed1"]}),
        ((), {"embeds": ["embed2"]}),
    ]


async def test_deliver_pages_to_forum_creates_thread_from_first_page() -> None:
    """Первая страница становится СТАРТОВЫМ сообщением поста -- не
    отдельным follow-up'ом в уже созданный пустой тред (именно так
    раньше получался плейсхолдер "Оригинальное сообщение удалено")."""
    forum = Mock(spec=discord.ForumChannel)
    thread = Mock()
    thread.send = AsyncMock()
    forum.create_thread = AsyncMock(return_value=Mock(thread=thread))
    pages = [["embed1"], ["embed2"], ["embed3"]]

    destination = await _deliver_pages(forum, pages, topic="Важно")

    forum.create_thread.assert_awaited_once_with(name="Важно", content=None, embeds=["embed1"])
    assert thread.send.await_args_list == [
        ((), {"embeds": ["embed2"]}),
        ((), {"embeds": ["embed3"]}),
    ]
    assert destination is thread


async def test_deliver_pages_to_forum_truncates_topic_to_100_chars() -> None:
    forum = Mock(spec=discord.ForumChannel)
    thread = Mock()
    forum.create_thread = AsyncMock(return_value=Mock(thread=thread))

    await _deliver_pages(forum, [["embed1"]], topic="x" * 150)

    assert len(forum.create_thread.await_args.kwargs["name"]) == 100


async def test_deliver_pages_to_forum_without_topic_uses_placeholder_name() -> None:
    """_deliver_pages сам не валидирует обязательность topic -- это
    ответственность вызывающей команды (см. _forum_missing_topic_error),
    но на пустой topic всё равно не должен падать с TypeError."""
    forum = Mock(spec=discord.ForumChannel)
    thread = Mock()
    forum.create_thread = AsyncMock(return_value=Mock(thread=thread))

    await _deliver_pages(forum, [["embed1"]], topic=None)

    assert forum.create_thread.await_args.kwargs["name"] == "Без темы"


def test_forum_missing_topic_error_mentions_the_parameter() -> None:
    assert "topic" in _forum_missing_topic_error()


# -- автодополнение/резолвинг channel -- собственный кэш, а не нативный ---
# channel-тип параметра slash-команды (у него подтверждённая проблема с
# неполными списками, см. docstring plugins/message_builder/commands.py
# и plugins/server_setup/commands.py -- то, из-за чего форум-каналы не
# показывались в /embed вообще).

def test_guild_channel_choices_filters_by_type_and_sorts_by_position() -> None:
    general = _make_channel(discord.TextChannel, id=1, name="general", position=2, type_=discord.ChannelType.text)
    alerts = _make_channel(discord.TextChannel, id=2, name="alerts", position=1, type_=discord.ChannelType.text)
    voice = _make_channel(discord.VoiceChannel, id=3, name="voice", position=0, type_=discord.ChannelType.voice)
    guild = Mock(spec=discord.Guild)
    guild.channels = [general, alerts, voice]

    choices = _guild_channel_choices(guild, "", channel_types=_TEXT_CHANNEL_TYPES)

    assert [c.value for c in choices] == ["2", "1"]  # alerts (position 1) раньше general (position 2)
    assert all(c.name.startswith("#") for c in choices)


def test_guild_channel_choices_includes_forum_when_requested() -> None:
    """Ключевой сценарий репорта -- форум-канал должен попадать в
    список, когда тип запрошен явно (раньше нативный picker его вообще
    не показывал)."""
    guides = _make_channel(discord.ForumChannel, id=9, name="guides", position=0, type_=discord.ChannelType.forum)
    guild = Mock(spec=discord.Guild)
    guild.channels = [guides]

    choices = _guild_channel_choices(guild, "", channel_types=_TEXT_OR_FORUM_CHANNEL_TYPES)

    assert [c.value for c in choices] == ["9"]


def test_guild_channel_choices_filters_by_current_substring() -> None:
    general = _make_channel(discord.TextChannel, id=1, name="general", position=0, type_=discord.ChannelType.text)
    alerts = _make_channel(discord.TextChannel, id=2, name="alerts", position=1, type_=discord.ChannelType.text)
    guild = Mock(spec=discord.Guild)
    guild.channels = [general, alerts]

    choices = _guild_channel_choices(guild, "gen", channel_types=_TEXT_CHANNEL_TYPES)

    assert [c.value for c in choices] == ["1"]


def test_resolve_channel_choice_from_autocomplete_id() -> None:
    channel = _make_channel(discord.TextChannel, id=42, name="general", position=0, type_=discord.ChannelType.text)
    guild = Mock(spec=discord.Guild)
    guild.get_channel = Mock(return_value=channel)

    assert _resolve_channel_choice(guild, "42", channel_types=_TEXT_CHANNEL_TYPES) is channel


def test_resolve_channel_choice_accepts_manual_mention() -> None:
    channel = _make_channel(discord.TextChannel, id=42, name="general", position=0, type_=discord.ChannelType.text)
    guild = Mock(spec=discord.Guild)
    guild.get_channel = Mock(return_value=channel)

    assert _resolve_channel_choice(guild, "<#42>", channel_types=_TEXT_CHANNEL_TYPES) is channel


def test_resolve_channel_choice_rejects_wrong_type() -> None:
    forum = _make_channel(discord.ForumChannel, id=7, name="guides", position=0, type_=discord.ChannelType.forum)
    guild = Mock(spec=discord.Guild)
    guild.get_channel = Mock(return_value=forum)

    assert _resolve_channel_choice(guild, "7", channel_types=_TEXT_CHANNEL_TYPES) is None


def test_resolve_channel_choice_returns_none_without_guild_or_raw_value() -> None:
    guild = Mock(spec=discord.Guild)
    assert _resolve_channel_choice(None, "42", channel_types=_TEXT_CHANNEL_TYPES) is None
    assert _resolve_channel_choice(guild, None, channel_types=_TEXT_CHANNEL_TYPES) is None
    assert _resolve_channel_choice(guild, "не-число", channel_types=_TEXT_CHANNEL_TYPES) is None


# -- _resolve_mentions -- реальные пинги для content=, не для embed'а -----
# (см. docstring модуля: упоминание внутри embed'а не пингует и не всегда
# красится в цвет роли -- та же причина, что чинилась в plugins/welcome).

def _guild_with(*, roles: list[Mock] = (), members: list[Mock] = ()) -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.roles = list(roles)
    guild.members = list(members)
    guild.get_member = lambda mid: next((m for m in guild.members if m.id == mid), None)
    return guild


def test_resolve_mentions_by_role_name_case_insensitive() -> None:
    pilot = _make_role(id=1, name="Pilot")
    guild = _guild_with(roles=[pilot])

    content, unresolved = _resolve_mentions(guild, "pilot")

    assert content == "<@&1>"
    assert unresolved == []


def test_resolve_mentions_by_role_id_and_raw_mention_syntax() -> None:
    pilot = _make_role(id=1, name="Pilot")
    guild = _guild_with(roles=[pilot])

    assert _resolve_mentions(guild, "1")[0] == "<@&1>"
    assert _resolve_mentions(guild, "<@&1>")[0] == "<@&1>"
    assert _resolve_mentions(guild, "@Pilot")[0] == "<@&1>"


def test_resolve_mentions_by_member_username_display_name_or_global_name() -> None:
    member = _make_member(id=100, name="jdoe", display_name="Johnny", global_name="John Doe")
    guild = _guild_with(members=[member])

    assert _resolve_mentions(guild, "jdoe")[0] == "<@100>"
    assert _resolve_mentions(guild, "Johnny")[0] == "<@100>"
    assert _resolve_mentions(guild, "John Doe")[0] == "<@100>"
    assert _resolve_mentions(guild, "100")[0] == "<@100>"
    assert _resolve_mentions(guild, "<@100>")[0] == "<@100>"


def test_resolve_mentions_combines_multiple_comma_separated_tokens() -> None:
    pilot = _make_role(id=1, name="Pilot")
    member = _make_member(id=100, name="jdoe")
    guild = _guild_with(roles=[pilot], members=[member])

    content, unresolved = _resolve_mentions(guild, "Pilot, jdoe")

    assert content == "<@&1> <@100>"
    assert unresolved == []


def test_resolve_mentions_reports_unresolved_tokens_without_dropping_the_rest() -> None:
    pilot = _make_role(id=1, name="Pilot")
    guild = _guild_with(roles=[pilot])

    content, unresolved = _resolve_mentions(guild, "Pilot, НесуществующаяРоль")

    assert content == "<@&1>"
    assert unresolved == ["НесуществующаяРоль"]


def test_resolve_mentions_accepts_list_input_from_yaml_template() -> None:
    pilot = _make_role(id=1, name="Pilot")
    guild = _guild_with(roles=[pilot])

    content, unresolved = _resolve_mentions(guild, ["Pilot"])

    assert content == "<@&1>"
    assert unresolved == []


def test_resolve_mentions_returns_empty_without_guild_or_raw_value() -> None:
    guild = _guild_with()
    assert _resolve_mentions(None, "Pilot") == (None, [])
    assert _resolve_mentions(guild, None) == (None, [])
    assert _resolve_mentions(guild, "") == (None, [])
