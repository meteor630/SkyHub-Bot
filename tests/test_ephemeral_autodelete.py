"""Тесты patch-логики автоудаления ephemeral-ответов
(``utils/ephemeral_autodelete.py``) -- проверяем саму функцию-обёртку
на фейковых объектах, не поднимая настоящий discord.py Interaction/
Webhook (в проекте нет и не должно быть такой инфраструктуры -- см.
остальные тесты, все они на уровне репозиториев/сервисов)."""
from __future__ import annotations

import asyncio

import discord
import pytest

from utils import ephemeral_autodelete as mod


class _FakeInteractionResponse:
    pass


async def test_send_message_adds_delete_after_when_ephemeral_and_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_original(self, *args, **kwargs):
        captured.update(kwargs)
        return "sent"

    monkeypatch.setattr(mod, "_original_response_send_message", fake_original)
    result = await mod._patched_response_send_message(_FakeInteractionResponse(), "hi", ephemeral=True)

    assert result == "sent"
    assert captured["delete_after"] == mod.EPHEMERAL_AUTODELETE_SECONDS


async def test_send_message_respects_explicit_delete_after(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_original(self, *args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mod, "_original_response_send_message", fake_original)
    await mod._patched_response_send_message(_FakeInteractionResponse(), ephemeral=True, delete_after=5.0)

    assert captured["delete_after"] == 5.0  # выбор вызывающего кода не перезаписан


async def test_send_message_leaves_non_ephemeral_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_original(self, *args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mod, "_original_response_send_message", fake_original)
    await mod._patched_response_send_message(_FakeInteractionResponse(), "hi")

    assert "delete_after" not in captured


async def test_webhook_send_ephemeral_forces_wait_and_schedules_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "EPHEMERAL_AUTODELETE_SECONDS", 0.01)
    deleted: list[bool] = []

    class FakeMessage:
        async def delete(self) -> None:
            deleted.append(True)

    captured: dict = {}

    async def fake_original(self, *args, **kwargs):
        captured.update(kwargs)
        return FakeMessage()

    monkeypatch.setattr(mod, "_original_webhook_send", fake_original)
    message = await mod._patched_webhook_send(object(), "hi", ephemeral=True)

    assert captured["wait"] is True  # иначе Discord не вернёт объект сообщения для удаления
    assert isinstance(message, FakeMessage)
    await asyncio.sleep(0.05)
    assert deleted == [True]


async def test_webhook_send_non_ephemeral_is_never_scheduled_for_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не-ephemeral сообщения (в т.ч. мост тикетов через веб-хук,
    plugins/tickets/bridge.py) патч трогать не должен вообще."""
    monkeypatch.setattr(mod, "EPHEMERAL_AUTODELETE_SECONDS", 0.01)
    deleted: list[bool] = []

    class FakeMessage:
        async def delete(self) -> None:
            deleted.append(True)

    async def fake_original(self, *args, **kwargs):
        return FakeMessage()

    monkeypatch.setattr(mod, "_original_webhook_send", fake_original)
    await mod._patched_webhook_send(object(), "hi")

    await asyncio.sleep(0.05)
    assert deleted == []


def test_install_patches_discord_classes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_installed", False)
    try:
        mod.install()
        assert discord.InteractionResponse.send_message is mod._patched_response_send_message
        assert discord.Webhook.send is mod._patched_webhook_send

        # Повторный вызов -- не более чем no-op (не переустанавливает
        # и не роняет уже пропатченные методы).
        mod.install()
        assert discord.InteractionResponse.send_message is mod._patched_response_send_message
        assert discord.Webhook.send is mod._patched_webhook_send
    finally:
        discord.InteractionResponse.send_message = mod._original_response_send_message
        discord.Webhook.send = mod._original_webhook_send
