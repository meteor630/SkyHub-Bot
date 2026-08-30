"""Выполнение и сохранение действий модерации (ТЗ §11, §26).

Выполняет реальное действие в Discord (ban/kick/timeout/unban) и
записывает его в ``moderation_actions``. У "warn" (предупреждения) нет
нативного аналога в Discord, поэтому это просто запись в БД.
Публикация итогового события :class:`core.events.ModerationAction`
оставлена на совести вызывающего кода (обработчик команды плагина /
слушатель audit-log), чтобы самому сервису не требовалась зависимость
от EventBus -- так его проще тестировать.
"""
from __future__ import annotations

import datetime as dt
import logging

import discord

from database.database import Database
from database.repositories.moderation_repository import ModerationRepository

logger = logging.getLogger("skyhub.moderation")


class ModerationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def _record(self, *, guild_id: int, action: str, target_id: int, moderator_id: int | None,
                       reason: str | None, extra: dict | None = None) -> None:
        async with self.db.session() as session:
            repo = ModerationRepository(session)
            await repo.add(
                guild_id=guild_id, action=action, target_id=target_id,
                moderator_id=moderator_id, reason=reason, extra=extra or {},
            )

    async def ban(self, guild: discord.Guild, target: discord.abc.Snowflake, moderator: discord.Member,
                  reason: str | None, delete_message_days: int = 0) -> None:
        await guild.ban(target, reason=reason, delete_message_seconds=delete_message_days * 86400)
        await self._record(guild_id=guild.id, action="ban", target_id=target.id, moderator_id=moderator.id, reason=reason)

    async def unban(self, guild: discord.Guild, user_id: int, moderator: discord.Member, reason: str | None) -> None:
        await guild.unban(discord.Object(id=user_id), reason=reason)
        await self._record(guild_id=guild.id, action="unban", target_id=user_id, moderator_id=moderator.id, reason=reason)

    async def kick(self, guild: discord.Guild, target: discord.Member, moderator: discord.Member, reason: str | None) -> None:
        await guild.kick(target, reason=reason)
        await self._record(guild_id=guild.id, action="kick", target_id=target.id, moderator_id=moderator.id, reason=reason)

    async def timeout(self, target: discord.Member, moderator: discord.Member, duration_minutes: int,
                       reason: str | None) -> None:
        until = discord.utils.utcnow() + dt.timedelta(minutes=duration_minutes)
        await target.timeout(until, reason=reason)
        await self._record(
            guild_id=target.guild.id, action="timeout", target_id=target.id, moderator_id=moderator.id,
            reason=reason, extra={"minutes": duration_minutes},
        )

    async def warn(self, guild_id: int, target_id: int, moderator: discord.Member, reason: str | None) -> int:
        await self._record(guild_id=guild_id, action="warn", target_id=target_id, moderator_id=moderator.id, reason=reason)
        async with self.db.session() as session:
            repo = ModerationRepository(session)
            return await repo.count_warnings(guild_id, target_id)

    async def history(self, guild_id: int, target_id: int, limit: int = 20):
        async with self.db.session() as session:
            repo = ModerationRepository(session)
            return await repo.history_for(guild_id, target_id, limit=limit)
