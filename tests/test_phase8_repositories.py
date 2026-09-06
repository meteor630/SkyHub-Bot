"""Тесты слоя хранения для фич Фазы 8 (ТЗ §41: авиа-профиль, бортжурнал,
совместные вылеты, тикеты, XP/репутация) с использованием SQLite в
памяти -- без необходимости в реальном Postgres."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models.base import Base
from database.models.guild import Guild
from database.repositories.flight_repository import FlightEventRepository, FlightLogRepository
from database.repositories.profile_repository import ProfileRepository
from database.repositories.stats_repository import StatsRepository, level_for_xp
from database.repositories.ticket_repository import TicketRepository

GUILD_ID = 1
USER_ID = 100
OTHER_USER_ID = 200


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


# -- ProfileRepository --------------------------------------------------

async def test_profile_upsert_creates_then_updates(session) -> None:
    repo = ProfileRepository(session)
    assert await repo.get(GUILD_ID, USER_ID) is None

    created = await repo.upsert(
        guild_id=GUILD_ID, user_id=USER_ID, role_type="pilot", simulator="msfs", network="vatsim", vatsim_id="123456"
    )
    assert created.role_type == "pilot"

    updated = await repo.upsert(
        guild_id=GUILD_ID, user_id=USER_ID, role_type="atc", simulator=None, network=None, vatsim_id=None
    )
    assert updated.role_type == "atc"
    assert await repo.get(GUILD_ID, USER_ID) is not None


async def test_profile_role_type_counts(session) -> None:
    repo = ProfileRepository(session)
    await repo.upsert(guild_id=GUILD_ID, user_id=USER_ID, role_type="pilot", simulator=None, network=None, vatsim_id=None)
    await repo.upsert(guild_id=GUILD_ID, user_id=OTHER_USER_ID, role_type="pilot", simulator=None, network=None, vatsim_id=None)

    counts = await repo.role_type_counts(GUILD_ID)
    assert counts == {"pilot": 2}


# -- FlightLogRepository --------------------------------------------------

async def test_flight_log_add_and_stats(session) -> None:
    repo = FlightLogRepository(session)
    await repo.add(
        guild_id=GUILD_ID, user_id=USER_ID, aircraft="A320", departure_icao="uuee", arrival_icao="ulli",
        flight_minutes=90, network="vatsim", vatsim_id="123456",
    )
    await repo.add(
        guild_id=GUILD_ID, user_id=USER_ID, aircraft="B738", departure_icao="ulli", arrival_icao="uuee",
        flight_minutes=85,
    )

    history = await repo.history_for(GUILD_ID, USER_ID)
    assert len(history) == 2
    assert {h.departure_icao for h in history} == {"UUEE", "ULLI"}  # ICAO приводится к верхнему регистру

    count, total_minutes = await repo.stats_for(GUILD_ID, USER_ID)
    assert count == 2
    assert total_minutes == 175

    assert await repo.count_for_guild(GUILD_ID) == 2


# -- FlightEventRepository --------------------------------------------------

async def test_flight_event_lifecycle(session) -> None:
    repo = FlightEventRepository(session)
    event = await repo.create(
        guild_id=GUILD_ID, channel_id=1000, title="Групповой вылет", route="UUEE-ULLI",
        aircraft="A320", event_time=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        max_participants=2, created_by_id=USER_ID,
    )

    await repo.set_message_id(event.id, 555)
    fetched = await repo.get(event.id)
    assert fetched.message_id == 555

    assert await repo.join(event.id, USER_ID) is True
    assert await repo.join(event.id, USER_ID) is False  # повторная запись игнорируется
    assert await repo.participant_count(event.id) == 1
    assert await repo.is_participant(event.id, USER_ID) is True

    upcoming = await repo.upcoming_for_guild(GUILD_ID)
    assert len(upcoming) == 1
    assert await repo.all_upcoming() == upcoming

    assert await repo.leave(event.id, USER_ID) is True
    assert await repo.leave(event.id, USER_ID) is False  # уже не записан
    assert await repo.participant_count(event.id) == 0


# -- TicketRepository --------------------------------------------------

async def test_ticket_lifecycle_and_counts(session) -> None:
    repo = TicketRepository(session)
    ticket = await repo.create(guild_id=GUILD_ID, channel_id=2000, creator_id=USER_ID, reason="Вопрос по рейсу")

    assert await repo.get_by_channel_id(2000) is ticket
    assert await repo.open_count_for_user(GUILD_ID, USER_ID) == 1

    open_count, closed_count = await repo.counts_for_guild(GUILD_ID)
    assert (open_count, closed_count) == (1, 0)

    closed = await repo.close(2000, closed_by_id=OTHER_USER_ID)
    assert closed.status == "closed"
    assert closed.closed_by_id == OTHER_USER_ID

    assert await repo.open_count_for_user(GUILD_ID, USER_ID) == 0
    open_count, closed_count = await repo.counts_for_guild(GUILD_ID)
    assert (open_count, closed_count) == (0, 1)


async def test_latest_created_at_tracks_most_recent_ticket_regardless_of_status(session) -> None:
    """См. plugins/tickets/views.py -- CREATE_COOLDOWN_SECONDS считается
    от последнего обращения участника, ОТКРЫТОГО или уже закрытого."""
    repo = TicketRepository(session)
    assert await repo.latest_created_at(GUILD_ID, USER_ID) is None

    first = await repo.create(guild_id=GUILD_ID, channel_id=2010, creator_id=USER_ID, reason=None)
    assert await repo.latest_created_at(GUILD_ID, USER_ID) == first.created_at

    await repo.close(2010, closed_by_id=OTHER_USER_ID)
    # Закрытие не должно "сбрасывать" -- по-прежнему это самое свежее.
    assert await repo.latest_created_at(GUILD_ID, USER_ID) == first.created_at

    # Другой участник на этом сервере не влияет на результат для USER_ID.
    await repo.create(guild_id=GUILD_ID, channel_id=2011, creator_id=OTHER_USER_ID, reason=None)
    assert await repo.latest_created_at(GUILD_ID, USER_ID) == first.created_at


async def test_ticket_forum_thread_linking_and_reverse_lookup(session) -> None:
    """См. plugins/tickets/forum.py -- у тикета опционально есть пост в
    форуме сапорта, привязываемый ПОСЛЕ создания записи (пост создаётся
    вторым шагом, уже зная ID тикета)."""
    repo = TicketRepository(session)
    ticket = await repo.create(guild_id=GUILD_ID, channel_id=2001, creator_id=USER_ID, reason=None)
    assert ticket.forum_thread_id is None
    assert await repo.get_by_forum_thread_id(9999) is None

    await repo.set_forum_thread(ticket.id, 9999)
    assert ticket.forum_thread_id == 9999
    linked = await repo.get_by_forum_thread_id(9999)
    assert linked is not None and linked.channel_id == 2001


async def test_ticket_closed_before_cutoff_and_delete(session) -> None:
    """См. plugins/tickets/plugin.py -- закрытые тикеты старше месяца
    удаляются автоматически фоновой задачей."""
    repo = TicketRepository(session)
    old_ticket = await repo.create(guild_id=GUILD_ID, channel_id=2002, creator_id=USER_ID, reason=None)
    recent_ticket = await repo.create(guild_id=GUILD_ID, channel_id=2003, creator_id=USER_ID, reason=None)

    await repo.close(2002, closed_by_id=OTHER_USER_ID)
    await repo.close(2003, closed_by_id=OTHER_USER_ID)
    # Искусственно состариваем один из двух закрытых тикетов.
    old_ticket.closed_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=40)
    await session.flush()

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)
    stale = await repo.closed_before(GUILD_ID, cutoff)
    assert [t.channel_id for t in stale] == [2002]

    await repo.delete(old_ticket.id)
    assert await repo.get_by_channel_id(2002) is None
    assert await repo.get_by_channel_id(2003) is not None  # свежий тикет не тронут


# -- StatsRepository --------------------------------------------------

def test_level_for_xp_curve() -> None:
    assert level_for_xp(0) == 0
    assert level_for_xp(100) == 1
    assert level_for_xp(400) == 2


async def test_stats_message_xp_and_level_up(session) -> None:
    repo = StatsRepository(session)
    stats, leveled_up = await repo.add_message_xp(GUILD_ID, USER_ID, 50)
    assert stats.xp == 50
    assert leveled_up is False

    stats, leveled_up = await repo.add_message_xp(GUILD_ID, USER_ID, 60)
    assert stats.xp == 110
    assert leveled_up is True
    assert stats.level == 1


async def test_stats_flight_minutes_reputation_and_leaderboard(session) -> None:
    repo = StatsRepository(session)
    await repo.add_flight_minutes(GUILD_ID, USER_ID, 120)
    await repo.add_reputation(GUILD_ID, USER_ID)
    await repo.add_message_xp(GUILD_ID, OTHER_USER_ID, 500)

    top = await repo.leaderboard(GUILD_ID, limit=10)
    assert [s.user_id for s in top] == [OTHER_USER_ID, USER_ID]

    total_minutes, total_messages = await repo.guild_totals(GUILD_ID)
    assert total_minutes == 120
    assert total_messages == 1

    user_stats = await repo.get(GUILD_ID, USER_ID)
    assert user_stats.reputation == 1
