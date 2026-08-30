"""Контекст текущей операции, пробрасываемый через логирование.

Каждый раз, когда мы обрабатываем событие Discord или slash-команду,
мы кладём короткоживущий ``RequestContext`` в ContextVar. Фильтр
логирования (``logging_config.setup``) читает его обратно и добавляет
guild_id/channel_id/user_id/plugin/event/request_id к *каждой*
лог-записи, созданной при обработке этого запроса — включая записи,
написанные глубоко внутри репозитория или сервиса, без необходимости
протаскивать параметры через всю цепочку вызовов. Именно это позволяет
связать embed с ошибкой в Discord с точными строками в консольном/JSON
логе через один общий ``request_id`` (ТЗ §43).
"""
from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    plugin: str | None = None
    event: str | None = None
    guild_id: int | None = None
    channel_id: int | None = None
    user_id: int | None = None

    @classmethod
    def new(cls, **kwargs) -> RequestContext:
        return cls(request_id=uuid.uuid4().hex[:12], **kwargs)


_current: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "skyhub_request_context", default=None
)


def current() -> RequestContext | None:
    return _current.get()


@contextmanager
def use(ctx: RequestContext) -> Iterator[RequestContext]:
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextmanager
def start(*, plugin: str | None = None, event: str | None = None, guild_id: int | None = None,
          channel_id: int | None = None, user_id: int | None = None) -> Iterator[RequestContext]:
    """Начинает новый контекст запроса, наследуя незаданные поля из текущего (если он есть)."""
    parent = current()
    if parent is not None:
        ctx = replace(
            parent,
            request_id=uuid.uuid4().hex[:12],
            plugin=plugin or parent.plugin,
            event=event or parent.event,
            guild_id=guild_id if guild_id is not None else parent.guild_id,
            channel_id=channel_id if channel_id is not None else parent.channel_id,
            user_id=user_id if user_id is not None else parent.user_id,
        )
    else:
        ctx = RequestContext.new(
            plugin=plugin, event=event, guild_id=guild_id, channel_id=channel_id, user_id=user_id
        )
    with use(ctx) as active:
        yield active
