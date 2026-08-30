from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from database.models.flight import FlightEvent, FlightEventParticipant, FlightLog
from database.repositories.base import BaseRepository


class FlightLogRepository(BaseRepository[FlightLog]):
    async def add(
        self, *, guild_id: int, user_id: int, aircraft: str, departure_icao: str, arrival_icao: str,
        flight_minutes: int, network: str | None = None, vatsim_id: str | None = None, remarks: str | None = None,
    ) -> FlightLog:
        record = FlightLog(
            guild_id=guild_id, user_id=user_id, aircraft=aircraft,
            departure_icao=departure_icao.upper(), arrival_icao=arrival_icao.upper(),
            flight_minutes=flight_minutes, network=network, vatsim_id=vatsim_id, remarks=remarks,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def history_for(self, guild_id: int, user_id: int, *, limit: int = 10) -> list[FlightLog]:
        stmt = (
            select(FlightLog)
            .where(FlightLog.guild_id == guild_id, FlightLog.user_id == user_id)
            .order_by(FlightLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_guild(self, guild_id: int) -> int:
        """Общее число рейсов, залогированных на сервере (для ``/server stats``)."""
        stmt = select(func.count(FlightLog.id)).where(FlightLog.guild_id == guild_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def stats_for(self, guild_id: int, user_id: int) -> tuple[int, int]:
        """Возвращает (число рейсов, суммарный налёт в минутах)."""
        stmt = select(func.count(FlightLog.id), func.coalesce(func.sum(FlightLog.flight_minutes), 0)).where(
            FlightLog.guild_id == guild_id, FlightLog.user_id == user_id
        )
        result = await self.session.execute(stmt)
        count, total_minutes = result.one()
        return int(count), int(total_minutes)


class FlightEventRepository(BaseRepository[FlightEvent]):
    async def create(
        self, *, guild_id: int, channel_id: int, title: str, route: str, aircraft: str,
        event_time: dt.datetime, max_participants: int, created_by_id: int,
    ) -> FlightEvent:
        record = FlightEvent(
            guild_id=guild_id, channel_id=channel_id, title=title, route=route, aircraft=aircraft,
            event_time=event_time, max_participants=max_participants, created_by_id=created_by_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def set_message_id(self, event_id: int, message_id: int) -> None:
        record = await self.get(event_id)
        if record is not None:
            record.message_id = message_id
            await self.session.flush()

    async def get(self, event_id: int) -> FlightEvent | None:
        return await self.session.get(FlightEvent, event_id)

    async def upcoming_for_guild(self, guild_id: int) -> list[FlightEvent]:
        now = dt.datetime.now(dt.UTC)
        stmt = (
            select(FlightEvent)
            .where(FlightEvent.guild_id == guild_id, FlightEvent.event_time >= now)
            .order_by(FlightEvent.event_time)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def all_upcoming(self) -> list[FlightEvent]:
        """Для регистрации персистентных View при старте бота -- по всем серверам."""
        now = dt.datetime.now(dt.UTC)
        stmt = select(FlightEvent).where(FlightEvent.event_time >= now)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def participant_count(self, event_id: int) -> int:
        stmt = select(func.count(FlightEventParticipant.id)).where(FlightEventParticipant.event_id == event_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def is_participant(self, event_id: int, user_id: int) -> bool:
        stmt = select(FlightEventParticipant).where(
            FlightEventParticipant.event_id == event_id, FlightEventParticipant.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def join(self, event_id: int, user_id: int) -> bool:
        """Возвращает False, если участник уже был записан (ничего не изменилось)."""
        if await self.is_participant(event_id, user_id):
            return False
        self.session.add(FlightEventParticipant(event_id=event_id, user_id=user_id))
        await self.session.flush()
        return True

    async def leave(self, event_id: int, user_id: int) -> bool:
        stmt = select(FlightEventParticipant).where(
            FlightEventParticipant.event_id == event_id, FlightEventParticipant.user_id == user_id
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return False
        await self.session.delete(record)
        await self.session.flush()
        return True
