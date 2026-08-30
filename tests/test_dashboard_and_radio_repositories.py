"""Тесты слоя хранения для дашборда статуса и плейлиста радио, на
in-memory SQLite (без необходимости в реальном Postgres)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models.base import Base
from database.models.guild import Guild
from database.repositories.dashboard_repository import DashboardRepository
from database.repositories.radio_repository import RadioRepository

GUILD_ID = 1


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Guild(id=GUILD_ID, name="Test Guild"))
        await session.flush()
        yield session

    await engine.dispose()


async def test_dashboard_upsert_creates_then_updates(session) -> None:
    repo = DashboardRepository(session)
    await repo.upsert(guild_id=GUILD_ID, kind="status", channel_id=100, message_id=200)
    first = await repo.get(GUILD_ID, "status")
    assert first is not None
    assert (first.channel_id, first.message_id) == (100, 200)

    await repo.upsert(guild_id=GUILD_ID, kind="status", channel_id=100, message_id=999)
    second = await repo.get(GUILD_ID, "status")
    assert second.message_id == 999
    assert second.id == first.id  # тот же ряд, а не новый


async def test_dashboard_kinds_are_independent(session) -> None:
    repo = DashboardRepository(session)
    await repo.upsert(guild_id=GUILD_ID, kind="status", channel_id=1, message_id=1)
    await repo.upsert(guild_id=GUILD_ID, kind="radio_now_playing", channel_id=2, message_id=2)

    assert (await repo.get(GUILD_ID, "status")).message_id == 1
    assert (await repo.get(GUILD_ID, "radio_now_playing")).message_id == 2


async def test_radio_add_assigns_incrementing_position(session) -> None:
    repo = RadioRepository(session)
    first = await repo.add(guild_id=GUILD_ID, title="Track A", file_path="a.mp3", added_by_id=1)
    second = await repo.add(guild_id=GUILD_ID, title="Track B", file_path="b.mp3", added_by_id=1)

    assert first.position == 0
    assert second.position == 1


async def test_radio_list_is_ordered_by_position(session) -> None:
    repo = RadioRepository(session)
    await repo.add(guild_id=GUILD_ID, title="First", file_path="1.mp3", added_by_id=1)
    await repo.add(guild_id=GUILD_ID, title="Second", file_path="2.mp3", added_by_id=1)

    tracks = await repo.list_for_guild(GUILD_ID)
    assert [t.title for t in tracks] == ["First", "Second"]


async def test_radio_remove_deletes_track(session) -> None:
    repo = RadioRepository(session)
    track = await repo.add(guild_id=GUILD_ID, title="Track", file_path="t.mp3", added_by_id=1)

    removed = await repo.remove(track.id)
    assert removed is not None
    assert await repo.get(track.id) is None
