from __future__ import annotations

from sqlalchemy import func, select

from database.models.profile import UserProfile
from database.repositories.base import BaseRepository


class ProfileRepository(BaseRepository[UserProfile]):
    async def get(self, guild_id: int, user_id: int) -> UserProfile | None:
        return await self.session.get(UserProfile, {"guild_id": guild_id, "user_id": user_id})

    async def role_type_counts(self, guild_id: int) -> dict[str, int]:
        """Число участников по каждому типу профиля (для ``/server stats``)."""
        stmt = (
            select(UserProfile.role_type, func.count(UserProfile.user_id))
            .where(UserProfile.guild_id == guild_id)
            .group_by(UserProfile.role_type)
        )
        result = await self.session.execute(stmt)
        return {role_type: count for role_type, count in result.all()}

    async def upsert(
        self,
        *,
        guild_id: int,
        user_id: int,
        role_type: str,
        simulator: str | None,
        network: str | None,
        vatsim_id: str | None,
    ) -> UserProfile:
        record = await self.get(guild_id, user_id)
        if record is None:
            record = UserProfile(guild_id=guild_id, user_id=user_id, role_type=role_type)
            self.session.add(record)
        record.role_type = role_type
        record.simulator = simulator
        record.network = network
        record.vatsim_id = vatsim_id
        await self.session.flush()
        return record
