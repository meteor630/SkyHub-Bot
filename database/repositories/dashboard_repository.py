from __future__ import annotations

from sqlalchemy import select

from database.models.dashboard import DashboardMessage
from database.repositories.base import BaseRepository


class DashboardRepository(BaseRepository[DashboardMessage]):
    async def get(self, guild_id: int, kind: str) -> DashboardMessage | None:
        stmt = select(DashboardMessage).where(DashboardMessage.guild_id == guild_id, DashboardMessage.kind == kind)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, *, guild_id: int, kind: str, channel_id: int, message_id: int) -> DashboardMessage:
        record = await self.get(guild_id, kind)
        if record is None:
            record = DashboardMessage(guild_id=guild_id, kind=kind, channel_id=channel_id, message_id=message_id)
            self.session.add(record)
        else:
            record.channel_id = channel_id
            record.message_id = message_id
        await self.session.flush()
        return record

    async def clear(self, guild_id: int, kind: str) -> None:
        record = await self.get(guild_id, kind)
        if record is not None:
            await self.session.delete(record)
            await self.session.flush()
