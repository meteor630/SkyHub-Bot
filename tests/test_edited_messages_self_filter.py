"""``edited_messages`` не должен логировать правки, сделанные самим ботом.

Регрессионный тест на конкретный баг: свои периодически редактируемые
сообщения (живой статус-дашборд, карточка "сейчас играет" у радио) бот
обновляет через ``channel.fetch_message()`` -- в отличие от сообщений,
полученных по шлюзу, discord.py НЕ добавляет их во внутренний кэш
(``payload.cached_message`` остаётся ``None``), поэтому старая проверка
``before.author.bot`` эту ситуацию не ловила и такие правки утекали в
канал логов. Тест дёргает реальный колбэк с ``ctx=None`` -- если фильтр
сработал, метод возвращает управление до первого обращения к ``self.ctx``
и падать ему не с чего; если фильтр сломан, обращение к ``self.ctx.db``
на ``None`` кинет исключение."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from plugins.edited_messages.plugin import EditedMessagesCog


@dataclass
class FakeRawMessageUpdateEvent:
    guild_id: int | None
    data: dict[str, Any] = field(default_factory=dict)
    cached_message: Any = None


async def test_skips_own_edit_when_message_not_cached() -> None:
    """Точное воспроизведение бага: cached_message=None (как после
    fetch_message()), но сырой payload содержит author.bot=True."""
    cog = EditedMessagesCog(ctx=None)
    payload = FakeRawMessageUpdateEvent(
        guild_id=1,
        data={"content": "новый текст статуса", "author": {"id": "999", "bot": True}},
        cached_message=None,
    )
    await cog.on_raw_message_edit(payload)  # не должно упасть на self.ctx с ctx=None


async def test_skips_own_edit_when_cached() -> None:
    class FakeAuthor:
        bot = True
        id = 999

    class FakeCachedMessage:
        author = FakeAuthor()
        content = "старый текст"

    cog = EditedMessagesCog(ctx=None)
    payload = FakeRawMessageUpdateEvent(
        guild_id=1,
        data={"content": "новый текст", "author": {"id": "999", "bot": True}},
        cached_message=FakeCachedMessage(),
    )
    await cog.on_raw_message_edit(payload)


async def test_does_not_skip_human_edit_without_cache() -> None:
    """Убеждаемся, что фикс не стал чрезмерно широким: правка обычного
    участника без кэша по-прежнему должна дойти до записи в БД (и упасть
    на ctx=None, доказывая, что путь дошёл дальше фильтра)."""
    cog = EditedMessagesCog(ctx=None)
    payload = FakeRawMessageUpdateEvent(
        guild_id=1,
        data={"content": "новый текст", "author": {"id": "42", "bot": False}},
    )
    with pytest.raises(AttributeError):
        await cog.on_raw_message_edit(payload)
