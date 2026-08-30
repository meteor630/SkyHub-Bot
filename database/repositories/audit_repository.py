from __future__ import annotations

from sqlalchemy import select

from database.models.audit import AuditLog
from database.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    async def add(self, *, guild_id: int, user_id: int, action: str, summary: str, extra: dict | None = None) -> AuditLog:
        record = AuditLog(guild_id=guild_id, user_id=user_id, action=action, summary=summary, extra=extra or {})
        self.session.add(record)
        await self.session.flush()
        return record

    async def timeline_for(self, guild_id: int, user_id: int, *, limit: int = 25) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.guild_id == guild_id, AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
