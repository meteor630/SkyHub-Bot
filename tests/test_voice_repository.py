"""Тесты слоя хранения для временных голосовых каналов (ТЗ §37) с
использованием SQLite в памяти -- без необходимости в реальном Postgres."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models.base import Base
from database.models.guild import Guild
from database.repositories.voice_repository import VoiceRepository

GUILD_ID = 1
OWNER_ID = 100
NEW_OWNER_ID = 200
CHANNEL_ID = 5000


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


async def test_create_room_persists_and_records_owner(session) -> None:
    repo = VoiceRepository(session)
    room = await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID, owner_id=OWNER_ID, name="Test Room")

    assert room.mode == "public"
    fetched = await repo.get_by_channel_id(CHANNEL_ID)
    assert fetched is not None
    assert fetched.owner_id == OWNER_ID
    assert len(fetched.owners) == 1
    assert fetched.owners[0].user_id == OWNER_ID
    assert fetched.owners[0].left_owner_at is None


async def test_set_mode_and_rename(session) -> None:
    repo = VoiceRepository(session)
    await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID, owner_id=OWNER_ID, name="Test Room")

    await repo.set_mode(CHANNEL_ID, "locked")
    await repo.rename(CHANNEL_ID, "New Name")

    fetched = await repo.get_by_channel_id(CHANNEL_ID)
    assert fetched.mode == "locked"
    assert fetched.name == "New Name"


async def test_transfer_owner_closes_old_ownership_record(session) -> None:
    repo = VoiceRepository(session)
    await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID, owner_id=OWNER_ID, name="Test Room")

    await repo.transfer_owner(CHANNEL_ID, NEW_OWNER_ID)

    fetched = await repo.get_by_channel_id(CHANNEL_ID)
    assert fetched.owner_id == NEW_OWNER_ID
    assert len(fetched.owners) == 2
    old_ownership = next(o for o in fetched.owners if o.user_id == OWNER_ID)
    new_ownership = next(o for o in fetched.owners if o.user_id == NEW_OWNER_ID)
    assert old_ownership.left_owner_at is not None
    assert new_ownership.left_owner_at is None


async def test_delete_removes_channel_and_owner_history(session) -> None:
    repo = VoiceRepository(session)
    await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID, owner_id=OWNER_ID, name="Test Room")

    await repo.delete(CHANNEL_ID)

    assert await repo.get_by_channel_id(CHANNEL_ID) is None


async def test_all_for_guild_lists_only_that_guild(session) -> None:
    repo = VoiceRepository(session)
    await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID, owner_id=OWNER_ID, name="Room A")
    await repo.create(guild_id=GUILD_ID, channel_id=CHANNEL_ID + 1, owner_id=OWNER_ID, name="Room B")

    rooms = await repo.all_for_guild(GUILD_ID)
    assert {r.channel_id for r in rooms} == {CHANNEL_ID, CHANNEL_ID + 1}
