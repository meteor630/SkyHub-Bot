"""Автоматическое исчезновение ephemeral-ответов бота через
``EPHEMERAL_AUTODELETE_SECONDS`` (клиентский запрос: "не только в
тикетах, а вообще везде такие уведомления вылезают").

Ephemeral-сообщение технически видно только тому, кто нажал кнопку/
вызвал команду -- но оно остаётся в его собственной истории, пока он не
уберёт его руками ("Нажмите здесь, чтобы убрать его"), и у активного
пользователя таких подсказок/подтверждений от бота накапливается много.

Патчим ДВЕ точки входа discord.py на уровне библиотеки, а не переписываем
каждый из сотен вызовов ``interaction.response.send_message(...,
ephemeral=True)``/``interaction.followup.send(..., ephemeral=True)`` по
всем плагинам -- это единственное место, где реально можно перехватить
"после ЛЮБОГО ephemeral-ответа" не трогая ни один плагин и не заставляя
каждый новый плагин помнить об этом отдельно:

* :meth:`discord.InteractionResponse.send_message` -- у него уже ЕСТЬ
  штатный параметр ``delete_after`` (см. discord/interactions.py) --
  просто подставляем его сами, когда вызывающий код передал
  ``ephemeral=True``, но не запрашивал ``delete_after`` явно.
* :meth:`discord.Webhook.send` -- то, через что реально уходит
  ``interaction.followup.send(...)`` (см. ``Interaction.followup``,
  возвращающий обычный ``Webhook``). У него штатного ``delete_after``
  нет, поэтому для ephemeral-ответов через followup planируем удаление
  вручную (``asyncio.sleep`` + ``message.delete()``), заодно
  подставляя ``wait=True``, если явно не задано иное -- иначе Discord
  не возвращает объект сообщения, и удалить будет нечего.

Ограничение: если вызывающий код САМ уже передал свой ``delete_after``
(send_message) -- уважаем его выбор и не перезаписываем. Не-ephemeral
сообщения (в т.ч. сообщения моста тикетов через веб-хук,
``plugins/tickets/bridge.py``) патч не трогает вообще.
"""
from __future__ import annotations

import asyncio
import logging

import discord

logger = logging.getLogger("skyhub.ephemeral_autodelete")

EPHEMERAL_AUTODELETE_SECONDS = 30.0

_installed = False
_original_response_send_message = discord.InteractionResponse.send_message
_original_webhook_send = discord.Webhook.send


async def _patched_response_send_message(self: discord.InteractionResponse, *args, **kwargs):
    if kwargs.get("ephemeral") and kwargs.get("delete_after") is None:
        kwargs["delete_after"] = EPHEMERAL_AUTODELETE_SECONDS
    return await _original_response_send_message(self, *args, **kwargs)


async def _patched_webhook_send(self: discord.Webhook, *args, **kwargs):
    schedule = bool(kwargs.get("ephemeral"))
    if schedule:
        kwargs.setdefault("wait", True)
    message = await _original_webhook_send(self, *args, **kwargs)
    if schedule and message is not None:
        async def _delayed_delete(target=message) -> None:
            await asyncio.sleep(EPHEMERAL_AUTODELETE_SECONDS)
            try:
                await target.delete()
            except discord.HTTPException:
                pass  # уже удалено вручную/сообщение протухло -- не ошибка

        asyncio.create_task(_delayed_delete())
    return message


def install() -> None:
    """Вызывается один раз при старте процесса (``app/main.py``),
    ДО того как бот начнёт обрабатывать интеракции."""
    global _installed
    if _installed:
        return
    discord.InteractionResponse.send_message = _patched_response_send_message
    discord.Webhook.send = _patched_webhook_send
    _installed = True
    logger.info("Автоудаление ephemeral-ответов включено (%.0f сек.)", EPHEMERAL_AUTODELETE_SECONDS)
