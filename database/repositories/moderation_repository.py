from __future__ import annotations

from sqlalchemy import select

from database.models.moderation import ModerationAction
from database.repositories.base import BaseRepository


class ModerationRepository(BaseRepository[ModerationAction]):
    async def add(
        self,
        *,
        guild_id: int,
        action: str,
        target_id: int,
        moderator_id: int | None,
        reason: str | None = None,
        extra: dict | None = None,
    ) -> ModerationAction:
        record = ModerationAction(
            guild_id=guild_id,
            action=action,
            target_id=target_id,
            moderator_id=moderator_id,
            reason=reason,
            extra=extra or {},
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def history_for(self, guild_id: int, target_id: int, *, limit: int = 20) -> list[ModerationAction]:
        stmt = (
            select(ModerationAction)
            .where(ModerationAction.guild_id == guild_id, ModerationAction.target_id == target_id)
            .order_by(ModerationAction.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_warnings(self, guild_id: int, target_id: int) -> int:
        history = await self.history_for(guild_id, target_id, limit=1000)
        return sum(1 for row in history if row.action == "warn")
