from __future__ import annotations

from sqlalchemy import func, select

from database.models.stats import UserStats
from database.repositories.base import BaseRepository


def level_for_xp(xp: int) -> int:
    """Простая, но предсказуемая кривая уровней: level = floor(sqrt(xp / 100))."""
    return int((xp / 100) ** 0.5)


class StatsRepository(BaseRepository[UserStats]):
    async def get(self, guild_id: int, user_id: int) -> UserStats | None:
        return await self.session.get(UserStats, {"guild_id": guild_id, "user_id": user_id})

    async def get_or_create(self, guild_id: int, user_id: int) -> UserStats:
        record = await self.get(guild_id, user_id)
        if record is None:
            record = UserStats(guild_id=guild_id, user_id=user_id)
            self.session.add(record)
            await self.session.flush()
        return record

    async def add_message_xp(self, guild_id: int, user_id: int, xp_amount: int) -> tuple[UserStats, bool]:
        """Начисляет XP за сообщение. Возвращает (запись, повысился_ли_уровень)."""
        record = await self.get_or_create(guild_id, user_id)
        record.xp += xp_amount
        record.messages_count += 1
        new_level = level_for_xp(record.xp)
        leveled_up = new_level > record.level
        record.level = new_level
        await self.session.flush()
        return record, leveled_up

    async def add_flight_minutes(self, guild_id: int, user_id: int, minutes: int) -> UserStats:
        record = await self.get_or_create(guild_id, user_id)
        record.flight_minutes += minutes
        await self.session.flush()
        return record

    async def add_reputation(self, guild_id: int, user_id: int, amount: int = 1) -> UserStats:
        record = await self.get_or_create(guild_id, user_id)
        record.reputation += amount
        await self.session.flush()
        return record

    async def leaderboard(self, guild_id: int, *, limit: int = 10) -> list[UserStats]:
        stmt = select(UserStats).where(UserStats.guild_id == guild_id).order_by(UserStats.xp.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def guild_totals(self, guild_id: int) -> tuple[int, int]:
        """Возвращает (суммарный налёт в минутах, суммарное число сообщений) по всему серверу."""
        stmt = select(
            func.coalesce(func.sum(UserStats.flight_minutes), 0),
            func.coalesce(func.sum(UserStats.messages_count), 0),
        ).where(UserStats.guild_id == guild_id)
        result = await self.session.execute(stmt)
        total_minutes, total_messages = result.one()
        return int(total_minutes), int(total_messages)
