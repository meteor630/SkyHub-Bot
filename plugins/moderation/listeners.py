"""Пассивный перехват модерации через собственный audit-log Discord (ТЗ §11).

Действия, выполненные через slash-команды (``/mod ban`` и т.д.), уже
публикуют событие :class:`ModerationAction` напрямую из ``commands.py``.
Этот модуль нужен для всего, что модератор делает *напрямую* в
интерфейсе Discord -- бан из списка участников, изменение ролей,
переименование канала -- о чём бот иначе никогда бы не узнал.
``on_audit_log_entry_create`` (discord.py 2.4+) бесплатно даёт нам
инициатора, цель и причину.

Записи, чьим инициатором является сам бот, пропускаются, так как они
уже прошли через ``commands.py`` и иначе были бы залогированы дважды.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from core.events import ChannelChanged, ModerationAction, RoleChanged
from database.repositories.moderation_repository import ModerationRepository


class ModerationAuditListener(commands.Cog):
    """Сохраняет напрямую выполненные (не через бота) действия модерации
    в обход ``ModerationService`` (который иначе заново выполнил бы вызов
    Discord API для уже случившегося события) и публикует то же самое
    событие :class:`ModerationAction`, что и команды бота, поэтому
    обработчик логирования в ``plugins/moderation/plugin.py`` обрабатывает
    оба источника одинаково."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def _skip(self, entry: discord.AuditLogEntry) -> bool:
        bot_user = self.ctx.bot.user
        return bot_user is not None and entry.user is not None and entry.user.id == bot_user.id

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        try:
            await self._handle(entry)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="on_audit_log_entry_create")

    async def _handle(self, entry: discord.AuditLogEntry) -> None:
        if self._skip(entry):
            return

        action = entry.action
        guild_id = entry.guild.id
        actor_id = entry.user.id if entry.user else None

        if action is discord.AuditLogAction.kick:
            self._emit_mod(guild_id, "kick", actor_id, entry.target.id, entry.reason)
        elif action is discord.AuditLogAction.ban:
            self._emit_mod(guild_id, "ban", actor_id, entry.target.id, entry.reason)
        elif action is discord.AuditLogAction.unban:
            self._emit_mod(guild_id, "unban", actor_id, entry.target.id, entry.reason)
        elif action is discord.AuditLogAction.member_role_update:
            await self._handle_role_update(entry, guild_id, actor_id)
        elif action is discord.AuditLogAction.member_update:
            await self._handle_member_update(entry, guild_id, actor_id)
        elif action in (
            discord.AuditLogAction.channel_create,
            discord.AuditLogAction.channel_delete,
            discord.AuditLogAction.channel_update,
        ):
            self.ctx.emit(
                ChannelChanged(
                    guild_id=guild_id,
                    action=action.name.split("_")[-1],
                    channel_id=entry.target.id,
                    actor_id=actor_id,
                    name=getattr(entry.target, "name", None),
                )
            )
        elif action in (
            discord.AuditLogAction.role_create,
            discord.AuditLogAction.role_delete,
            discord.AuditLogAction.role_update,
        ):
            self.ctx.emit(
                RoleChanged(
                    guild_id=guild_id,
                    action=action.name.split("_")[-1],
                    role_id=entry.target.id,
                    actor_id=actor_id,
                    name=getattr(entry.target, "name", None),
                )
            )
        elif action is discord.AuditLogAction.message_bulk_delete:
            self._emit_mod(
                guild_id, "bulk_delete", actor_id, getattr(entry.target, "id", 0), entry.reason,
                count=getattr(entry.extra, "count", None),
            )

    def _emit_mod(self, guild_id: int, action: str, actor_id: int | None, target_id: int, reason: str | None, **extra) -> None:
        self.ctx.emit(
            ModerationAction(guild_id=guild_id, action=action, moderator_id=actor_id, target_id=target_id, reason=reason, extra=extra)
        )
        self.ctx.create_task(
            self._persist(guild_id, action, actor_id, target_id, reason, extra), name="moderation-audit-persist"
        )

    async def _persist(self, guild_id: int, action: str, actor_id: int | None, target_id: int, reason: str | None, extra: dict) -> None:
        async with self.ctx.db.session() as session:
            await ModerationRepository(session).add(
                guild_id=guild_id, action=action, target_id=target_id, moderator_id=actor_id, reason=reason, extra=extra
            )

    async def _handle_role_update(self, entry: discord.AuditLogEntry, guild_id: int, actor_id: int | None) -> None:
        before_roles = set(getattr(entry.before, "roles", []) or [])
        after_roles = set(getattr(entry.after, "roles", []) or [])
        if before_roles == after_roles:
            return

        # Роли вроде "Pilot"/"MSFS" и т.п. самовыдаются сотнями в день и
        # заваливают лог модерации -- администратор может исключить их
        # из логирования через /setup ignored-roles, не теряя при этом
        # логирование значимых ролей (Модератор, Мут и т.п.).
        ignored = await self.ctx.guild_config().ignored_log_role_ids(guild_id)

        for role in after_roles - before_roles:
            if role.id in ignored:
                continue
            self._emit_mod(guild_id, "role_add", actor_id, entry.target.id, entry.reason, role=role.name)
        for role in before_roles - after_roles:
            if role.id in ignored:
                continue
            self._emit_mod(guild_id, "role_remove", actor_id, entry.target.id, entry.reason, role=role.name)

    async def _handle_member_update(self, entry: discord.AuditLogEntry, guild_id: int, actor_id: int | None) -> None:
        before_nick = getattr(entry.before, "nick", None)
        after_nick = getattr(entry.after, "nick", None)
        if before_nick != after_nick:
            self._emit_mod(
                guild_id, "nickname", actor_id, entry.target.id, entry.reason,
                before=before_nick, after=after_nick,
            )
            return

        before_timeout = getattr(entry.before, "timed_out_until", None)
        after_timeout = getattr(entry.after, "timed_out_until", None)
        if before_timeout != after_timeout and after_timeout is not None:
            self._emit_mod(guild_id, "timeout", actor_id, entry.target.id, entry.reason, until=str(after_timeout))
