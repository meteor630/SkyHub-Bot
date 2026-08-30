"""Определяет конфигурацию для конкретного сервера: сначала БД
(``guild_settings``, задаётся вживую через ``/setup``), затем -- запасной
вариант из ``config.yaml`` (ТЗ §24, §27, идея клиента №1). Используется
всеми плагинами, которым нужно знать "в какой канал мне писать логи" /
"какая роль считается модераторской", чтобы каждому плагину не
приходилось заново реализовывать одну и ту же схему "сначала БД, потом YAML".
"""
from __future__ import annotations

from typing import Any

from database.database import Database
from database.models.guild import GuildSettings
from database.repositories.guild_repository import GuildRepository
from utils.cache import TTLCache

_CHANNEL_ATTR = {
    "welcome": "welcome_channel_id",
    "moderation_logs": "moderation_logs_channel_id",
    "deleted_messages": "deleted_messages_channel_id",
    "edited_messages": "edited_messages_channel_id",
    "member_logs": "member_logs_channel_id",
    "error_logs": "error_logs_channel_id",
    "audit_logs": "audit_logs_channel_id",
    "status": "status_channel_id",
    "temporary_voice_creator": "temporary_voice_creator_channel_id",
    "radio_voice": "radio_voice_channel_id",
    "radio_text": "radio_text_channel_id",
    "flight_log": "flight_log_channel_id",
}

_CATEGORY_ATTR = {
    "temporary_voice": "temporary_voice_category_id",
    "tickets": "tickets_category_id",
}

_ROLE_ATTR = {
    "moderator": "moderator_role_id",
    "admin": "admin_role_id",
    "support": "support_role_id",
    "owner": "owner_role_id",
}


class GuildConfigService:
    def __init__(self, db: Database, global_config: dict[str, Any], cache: TTLCache) -> None:
        self.db = db
        self.global_config = global_config
        self.cache = cache

    async def get_settings(self, guild_id: int) -> GuildSettings | None:
        cache_key = ("guild_settings", guild_id)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        async with self.db.session() as session:
            settings = await GuildRepository(session).get_settings(guild_id)
        if settings is not None:
            self.cache.set(cache_key, settings)
        return settings

    def invalidate(self, guild_id: int) -> None:
        self.cache.invalidate(("guild_settings", guild_id))

    async def resolve_channel_id(self, guild_id: int | None, key: str) -> int | None:
        if guild_id is not None:
            settings = await self.get_settings(guild_id)
            attr = _CHANNEL_ATTR.get(key)
            if settings is not None and attr is not None:
                value = getattr(settings, attr, None)
                if value:
                    return value
        return self.global_config.get("channels", {}).get(key)

    async def resolve_category_id(self, guild_id: int | None, key: str = "temporary_voice") -> int | None:
        if guild_id is not None:
            settings = await self.get_settings(guild_id)
            attr = _CATEGORY_ATTR.get(key)
            if settings is not None and attr is not None:
                value = getattr(settings, attr, None)
                if value:
                    return value
        return self.global_config.get("categories", {}).get(key)

    async def resolve_role_id(self, guild_id: int | None, key: str) -> int | None:
        if guild_id is not None:
            settings = await self.get_settings(guild_id)
            attr = _ROLE_ATTR.get(key)
            if settings is not None and attr is not None:
                value = getattr(settings, attr, None)
                if value:
                    return value
        return self.global_config.get("roles", {}).get(key)

    async def role_map_for(self, guild_id: int) -> dict[str, int]:
        result: dict[str, int] = {}
        for key in _ROLE_ATTR:
            value = await self.resolve_role_id(guild_id, key)
            if value:
                result[key] = value
        return result

    async def ignored_log_role_ids(self, guild_id: int) -> set[int]:
        """Роли, изменения которых (выдача/снятие) не нужно писать в лог
        модерации -- см. ``/setup ignored-roles``."""
        settings = await self.get_settings(guild_id)
        if settings is None or not settings.ignored_log_role_ids:
            return set()
        return {int(role_id) for role_id in settings.ignored_log_role_ids}

    async def voice_creator_presets(self, guild_id: int) -> dict[int, int]:
        """Доп. каналы-создатели временных voice с фиксированным лимитом
        мест (напр. быстрые "на 2"/"на 4") -- см. ``/setup voice``.
        Возвращает {ID канала-создателя: лимит участников}."""
        settings = await self.get_settings(guild_id)
        if settings is None or not settings.voice_creator_presets:
            return {}
        return {int(channel_id): int(limit) for channel_id, limit in settings.voice_creator_presets.items()}

    async def resolve_profile_role_id(self, guild_id: int, role_type: str) -> int | None:
        """Discord-роль, соответствующая типу авиационного профиля
        (pilot/atc/...) -- см. ``/setup profile-roles``."""
        settings = await self.get_settings(guild_id)
        if settings is None or not settings.profile_role_ids:
            return None
        value = settings.profile_role_ids.get(role_type)
        return int(value) if value else None
