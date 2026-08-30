"""Плагин ``audit``: подписывается на остальной трафик Event Bus и строит
единый таймлайн по каждому пользователю (идея клиента №2), независимо
от любого плагина, который реально порождает события -- новый тип
события где-то ещё автоматически появится здесь, как только этот
плагин на него подпишется, без изменений в плагине-источнике.
"""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from core.events import MemberJoined, MemberLeft, ModerationAction, VoiceCreated, VoiceDeleted
from database.repositories.audit_repository import AuditRepository
from plugins.audit.commands import build_audit_cog


class AuditPlugin(BasePlugin):
    meta = PluginMeta(
        name="audit", version="1.0.0",
        description="Единый таймлайн событий пользователя (/audit), питается от Event Bus",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_audit_cog(self.ctx))
        self.ctx.subscribe(MemberJoined, self._on_member_joined)
        self.ctx.subscribe(MemberLeft, self._on_member_left)
        self.ctx.subscribe(ModerationAction, self._on_moderation_action)
        self.ctx.subscribe(VoiceCreated, self._on_voice_created)
        self.ctx.subscribe(VoiceDeleted, self._on_voice_deleted)
        self.log.info("audit готов к работе")

    async def _record(self, *, guild_id: int | None, user_id: int, action: str, summary: str, extra: dict | None = None) -> None:
        if guild_id is None:
            return
        async with self.ctx.db.session() as session:
            await AuditRepository(session).add(guild_id=guild_id, user_id=user_id, action=action, summary=summary, extra=extra or {})

    async def _on_member_joined(self, event: MemberJoined) -> None:
        await self._record(guild_id=event.guild_id, user_id=event.user_id, action="member_joined", summary="🟢 вошёл(-шла) на сервер")

    async def _on_member_left(self, event: MemberLeft) -> None:
        await self._record(guild_id=event.guild_id, user_id=event.user_id, action="member_left", summary="🔴 покинул(а) сервер")

    async def _on_moderation_action(self, event: ModerationAction) -> None:
        summary = f"получил(а) действие модерации: {event.action}"
        if event.reason:
            summary += f" ({event.reason})"
        await self._record(guild_id=event.guild_id, user_id=event.target_id, action=f"mod_{event.action}", summary=summary)

    async def _on_voice_created(self, event: VoiceCreated) -> None:
        await self._record(guild_id=event.guild_id, user_id=event.owner_id, action="voice_created", summary="🎙 создал(а) голосовую комнату")

    async def _on_voice_deleted(self, event: VoiceDeleted) -> None:
        if event.owner_id is None:
            return
        await self._record(guild_id=event.guild_id, user_id=event.owner_id, action="voice_deleted", summary="🎙 голосовая комната удалена")


PLUGIN_CLASS = AuditPlugin
