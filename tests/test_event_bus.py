from __future__ import annotations

from dataclasses import dataclass

from core.event_bus import EventBus
from core.events import Event


@dataclass(frozen=True, kw_only=True)
class Ping(Event):
    value: int = 0


async def test_subscriber_receives_event(event_bus: EventBus) -> None:
    received = []

    async def handler(event: Ping) -> None:
        received.append(event.value)

    event_bus.subscribe(Ping, handler, owner="test")
    await event_bus.emit_and_wait(Ping(value=42))

    assert received == [42]


async def test_unrelated_event_type_is_not_delivered(event_bus: EventBus) -> None:
    @dataclass(frozen=True, kw_only=True)
    class OtherEvent(Event):
        pass

    received = []

    async def handler(event: Ping) -> None:
        received.append(event)

    event_bus.subscribe(Ping, handler, owner="test")
    await event_bus.emit_and_wait(OtherEvent())

    assert received == []


async def test_one_handler_exception_does_not_stop_others(event_bus: EventBus) -> None:
    calls = []

    async def broken(event: Ping) -> None:
        raise RuntimeError("boom")

    async def healthy(event: Ping) -> None:
        calls.append(event.value)

    event_bus.subscribe(Ping, broken, owner="plugin-a")
    event_bus.subscribe(Ping, healthy, owner="plugin-b")

    await event_bus.emit_and_wait(Ping(value=1))

    assert calls == [1]


async def test_error_sink_is_invoked_with_owner(event_bus: EventBus) -> None:
    reported = []

    async def sink(exc: BaseException, owner: str, event_name: str) -> None:
        reported.append((owner, event_name, str(exc)))

    event_bus.set_error_sink(sink)

    async def broken(event: Ping) -> None:
        raise ValueError("nope")

    event_bus.subscribe(Ping, broken, owner="plugin-a")
    await event_bus.emit_and_wait(Ping())

    assert reported == [("plugin-a", "Ping", "nope")]


async def test_unsubscribe_all_removes_only_owner_handlers(event_bus: EventBus) -> None:
    async def handler(event: Ping) -> None:
        return None

    event_bus.subscribe(Ping, handler, owner="plugin-a")
    event_bus.subscribe(Ping, handler, owner="plugin-b")

    removed = event_bus.unsubscribe_all(owner="plugin-a")
    assert removed == 1
    assert event_bus.subscriber_count(Ping) == 1
