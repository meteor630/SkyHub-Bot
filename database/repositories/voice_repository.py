from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models.voice import TemporaryVoiceChannel, VoiceChannelOwner
from database.repositories.base import BaseRepository


class VoiceRepository(BaseRepository[TemporaryVoiceChannel]):
    async def create(
        self, *, guild_id: int, channel_id: int, owner_id: int, name: str, member_limit: int = 0
    ) -> TemporaryVoiceChannel:
        record = TemporaryVoiceChannel(
            guild_id=guild_id, channel_id=channel_id, owner_id=owner_id, name=name, member_limit=member_limit
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add(
            VoiceChannelOwner(temp_channel_id=record.id, user_id=owner_id, became_owner_at=dt.datetime.now(dt.UTC))
        )
        await self.session.flush()
        return record

    async def get_by_channel_id(self, channel_id: int) -> TemporaryVoiceChannel | None:
        # Заранее подгружаем `owners` (selectinload), чтобы вызывающий код мог
        # безопасно прочитать это поле после возврата из корутины -- доступ к
        # ленивой связи вне активного async/greenlet-контекста вызывает MissingGreenlet.
        stmt = (
            select(TemporaryVoiceChannel)
            .options(selectinload(TemporaryVoiceChannel.owners))
            .where(TemporaryVoiceChannel.channel_id == channel_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def all_for_guild(self, guild_id: int) -> list[TemporaryVoiceChannel]:
        stmt = select(TemporaryVoiceChannel).where(TemporaryVoiceChannel.guild_id == guild_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def all_for_owner(self, guild_id: int, owner_id: int) -> list[TemporaryVoiceChannel]:
        """Активные комнаты, которыми сейчас владеет участник -- для
        центральной панели управления (``/setup voice-panel``), которая
        работает не из чата конкретной комнаты, а сама находит, чем
        управлять."""
        # Сортировка по id, а не created_at -- несколько комнат, созданных
        # в быстрой последовательности (как в тестах, да и не только),
        # вполне могут получить одинаковый created_at (в Postgres --
        # если оказались в одной транзакции; func.now() фиксирован на
        # уровне транзакции, а не вызова). id всегда монотонно растёт.
        stmt = select(TemporaryVoiceChannel).where(
            TemporaryVoiceChannel.guild_id == guild_id, TemporaryVoiceChannel.owner_id == owner_id
        ).order_by(TemporaryVoiceChannel.id.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_locked(self, channel_id: int, locked: bool) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is not None:
            record.is_locked = locked
            await self.session.flush()

    async def set_hidden(self, channel_id: int, hidden: bool) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is not None:
            record.is_hidden = hidden
            await self.session.flush()

    async def rename(self, channel_id: int, name: str) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is not None:
            record.name = name
            await self.session.flush()

    async def set_limit(self, channel_id: int, limit: int) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is not None:
            record.member_limit = limit
            await self.session.flush()

    async def transfer_owner(self, channel_id: int, new_owner_id: int) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is None:
            return
        now = dt.datetime.now(dt.UTC)
        stmt = select(VoiceChannelOwner).where(
            VoiceChannelOwner.temp_channel_id == record.id, VoiceChannelOwner.left_owner_at.is_(None)
        )
        result = await self.session.execute(stmt)
        current = result.scalar_one_or_none()
        if current is not None:
            current.left_owner_at = now
        record.owner_id = new_owner_id
        self.session.add(VoiceChannelOwner(temp_channel_id=record.id, user_id=new_owner_id, became_owner_at=now))
        await self.session.flush()

    async def delete(self, channel_id: int) -> None:
        record = await self.get_by_channel_id(channel_id)
        if record is not None:
            await self.session.delete(record)
            await self.session.flush()
