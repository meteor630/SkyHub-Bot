"""Тесты доставки отрендеренных страниц в обычный канал / пост форума
(``plugins/message_builder/commands.py::_deliver_pages``) -- на фейковых
объектах (``Mock(spec=...)`` заставляет ``isinstance`` отработать
правильно), без настоящего discord.py Guild/подключения."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import discord

from plugins.message_builder.commands import _deliver_pages, _forum_missing_topic_error


async def test_deliver_pages_to_regular_channel_sends_each_page_in_order() -> None:
    channel = Mock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    pages = [["embed1"], ["embed2"]]

    destination = await _deliver_pages(channel, pages, topic=None)

    assert destination is channel
    assert channel.send.await_args_list == [
        ((), {"embeds": ["embed1"]}),
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

    forum.create_thread.assert_awaited_once_with(name="Важно", embeds=["embed1"])
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
