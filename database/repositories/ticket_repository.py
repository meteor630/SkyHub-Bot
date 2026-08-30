from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from database.models.ticket import STATUS_CLOSED, STATUS_OPEN, Ticket
from database.repositories.base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    async def create(self, *, guild_id: int, channel_id: int, creator_id: int, reason: str | None) -> Ticket:
        record = Ticket(guild_id=guild_id, channel_id=channel_id, creator_id=creator_id, reason=reason)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_channel_id(self, channel_id: int) -> Ticket | None:
        stmt = select(Ticket).where(Ticket.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def open_count_for_user(self, guild_id: int, creator_id: int) -> int:
        stmt = select(Ticket).where(
            Ticket.guild_id == guild_id, Ticket.creator_id == creator_id, Ticket.status == STATUS_OPEN
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def counts_for_guild(self, guild_id: int) -> tuple[int, int]:
        """Возвращает (открытых, закрытых) тикетов (для ``/server stats``)."""
        stmt = select(Ticket.status, func.count(Ticket.id)).where(Ticket.guild_id == guild_id).group_by(Ticket.status)
        result = await self.session.execute(stmt)
        counts = dict(result.all())
        return counts.get(STATUS_OPEN, 0), counts.get(STATUS_CLOSED, 0)

    async def close(self, channel_id: int, closed_by_id: int) -> Ticket | None:
        record = await self.get_by_channel_id(channel_id)
        if record is None:
            return None
        record.status = STATUS_CLOSED
        record.closed_at = dt.datetime.now(dt.UTC)
        record.closed_by_id = closed_by_id
        await self.session.flush()
        return record
