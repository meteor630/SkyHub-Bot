from __future__ import annotations

from sqlalchemy import select

from database.models.guild import Guild, GuildSettings
from database.repositories.base import BaseRepository


class GuildRepository(BaseRepository[Guild]):
    async def get_or_create(self, guild_id: int, name: str, *, locale: str = "ru") -> Guild:
        guild = await self.session.get(Guild, guild_id)
        if guild is None:
            guild = Guild(id=guild_id, name=name, locale=locale)
            self.session.add(guild)
            await self.session.flush()
            settings = GuildSettings(guild_id=guild_id)
            self.session.add(settings)
            await self.session.flush()
        return guild

    async def get_settings(self, guild_id: int) -> GuildSettings | None:
        return await self.session.get(GuildSettings, guild_id)

    async def get_or_create_settings(self, guild_id: int) -> GuildSettings:
        settings = await self.get_settings(guild_id)
        if settings is None:
            await self.get_or_create(guild_id, name="unknown")
            settings = await self.get_settings(guild_id)
        assert settings is not None
        return settings

    async def update_settings(self, guild_id: int, **fields) -> GuildSettings:
        settings = await self.get_or_create_settings(guild_id)
        for key, value in fields.items():
            setattr(settings, key, value)
        await self.session.flush()
        return settings

    async def all_guilds(self) -> list[Guild]:
        result = await self.session.execute(select(Guild))
        return list(result.scalars().all())
