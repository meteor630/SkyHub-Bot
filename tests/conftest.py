from __future__ import annotations

from pathlib import Path

import discord
import pytest
from discord.ext import commands

from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.permissions import PermissionService
from utils.cache import TTLCache
from utils.i18n import I18n

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def permissions() -> PermissionService:
    return PermissionService()


@pytest.fixture
def error_handler(event_bus: EventBus) -> ErrorHandler:
    return ErrorHandler(event_bus=event_bus)


@pytest.fixture
def i18n() -> I18n:
    return I18n(PROJECT_ROOT / "locales")


@pytest.fixture
def cache() -> TTLCache:
    return TTLCache(ttl_seconds=30.0)


@pytest.fixture
def bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    intents.voice_states = True
    return commands.Bot(command_prefix="!", intents=intents)
