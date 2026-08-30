"""Внутренние доменные события, публикуемые в EventBus.

Плагины никогда не вызывают друг друга напрямую. Вместо этого плагин,
заметивший что-то важное, публикует один из этих датаклассов, а любой
другой плагин, которому это интересно, подписывается на него. Это
сохраняет плагины независимыми, так что любой из них можно отключить/
перезагрузить/удалить, не трогая остальные.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class Event:
    """Базовый класс для любого внутреннего события."""

    timestamp: float = field(default_factory=time.time)
    guild_id: int | None = None
    request_id: str | None = None


# --- Участники сервера --------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class MemberJoined(Event):
    user_id: int
    display_name: str
    account_created_at: float


@dataclass(frozen=True, kw_only=True)
class MemberLeft(Event):
    user_id: int
    display_name: str
    joined_at: float | None = None


# --- Сообщения -----------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class MessageDeleted(Event):
    message_id: int
    channel_id: int
    author_id: int | None
    content: str
    attachments: tuple[str, ...] = ()
    bulk: bool = False


@dataclass(frozen=True, kw_only=True)
class MessageEdited(Event):
    message_id: int
    channel_id: int
    author_id: int
    before: str
    after: str


# --- Модерация -----------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class ModerationAction(Event):
    action: str  # ban / unban / kick / timeout / mute / warn / role_add / role_remove / nickname / permissions
    moderator_id: int | None
    target_id: int
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ChannelChanged(Event):
    action: str  # created / deleted / updated
    channel_id: int
    actor_id: int | None
    name: str | None = None


@dataclass(frozen=True, kw_only=True)
class RoleChanged(Event):
    action: str  # created / deleted / updated
    role_id: int
    actor_id: int | None
    name: str | None = None


# --- Голосовые каналы -----------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class VoiceCreated(Event):
    channel_id: int
    owner_id: int


@dataclass(frozen=True, kw_only=True)
class VoiceDeleted(Event):
    channel_id: int
    owner_id: int | None


# --- Жизненный цикл плагинов -----------------------------------------------

@dataclass(frozen=True, kw_only=True)
class PluginLoaded(Event):
    plugin: str
    version: str


@dataclass(frozen=True, kw_only=True)
class PluginReloaded(Event):
    plugin: str
    version: str


@dataclass(frozen=True, kw_only=True)
class PluginError(Event):
    plugin: str
    error_id: str
    message: str


@dataclass(frozen=True, kw_only=True)
class AuditEntry(Event):
    """Универсальное событие для наполнения таймлайна /audit."""

    user_id: int
    action: str
    summary: str
    extra: dict[str, Any] = field(default_factory=dict)


# --- Авиация (ТЗ §41, идея клиента о "системе контекста пользователя") ------

@dataclass(frozen=True, kw_only=True)
class ProfileUpdated(Event):
    """Публикуется ``plugins/aviation_profile`` при сохранении/изменении
    авиационного профиля участника."""

    user_id: int
    role_type: str
    simulator: str | None = None
    network: str | None = None


@dataclass(frozen=True, kw_only=True)
class FlightLogged(Event):
    """Публикуется ``plugins/flight_log`` -- на это подписывается
    ``plugins/leveling``, чтобы прибавлять налёт к статистике участника,
    не будучи связанным с plugins/flight_log напрямую."""

    user_id: int
    aircraft: str
    departure_icao: str
    arrival_icao: str
    flight_minutes: int
