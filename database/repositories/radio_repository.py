from __future__ import annotations

from sqlalchemy import select

from database.models.radio import RadioTrack
from database.repositories.base import BaseRepository


class RadioRepository(BaseRepository[RadioTrack]):
    async def add(
        self,
        *,
        guild_id: int,
        title: str,
        file_path: str,
        added_by_id: int,
        artist: str | None = None,
        album: str | None = None,
        composer: str | None = None,
        duration_seconds: float | None = None,
        bitrate_kbps: int | None = None,
        cover_path: str | None = None,
    ) -> RadioTrack:
        stmt = select(RadioTrack).where(RadioTrack.guild_id == guild_id)
        result = await self.session.execute(stmt)
        max_position = max((t.position for t in result.scalars().all()), default=-1)
        record = RadioTrack(
            guild_id=guild_id, title=title, file_path=file_path, added_by_id=added_by_id, position=max_position + 1,
            artist=artist, album=album, composer=composer,
            duration_seconds=duration_seconds, bitrate_kbps=bitrate_kbps, cover_path=cover_path,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_for_guild(self, guild_id: int) -> list[RadioTrack]:
        stmt = select(RadioTrack).where(RadioTrack.guild_id == guild_id).order_by(RadioTrack.position)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, track_id: int) -> RadioTrack | None:
        return await self.session.get(RadioTrack, track_id)

    async def remove(self, track_id: int) -> RadioTrack | None:
        record = await self.get(track_id)
        if record is not None:
            await self.session.delete(record)
            await self.session.flush()
        return record
