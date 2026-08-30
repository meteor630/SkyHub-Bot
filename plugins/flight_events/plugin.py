"""Плагин ``flight_events``: совместные вылеты сообщества (ТЗ §41, "Flight events").

Персистентные кнопки "Участвовать"/"Не участвовать" у каждого события
завязаны на свой уникальный ``custom_id`` (см. ``views.py``), поэтому при
перезапуске бота регистрируем по одному экземпляру View на каждое ещё не
прошедшее событие -- это восстанавливает работоспособность кнопок под
уже отправленными сообщениями без повторной их отправки."""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from database.repositories.flight_repository import FlightEventRepository
from plugins.flight_events.commands import build_flight_event_cog
from plugins.flight_events.views import EventParticipationView


class FlightEventsPlugin(BasePlugin):
    meta = PluginMeta(
        name="flight_events", version="1.0.0",
        description="/event create, /event list -- совместные вылеты сообщества",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_flight_event_cog(self.ctx))
        self.log.info("flight_events готов к работе")

    async def start(self) -> None:
        # На нулевом числе подключённых серверов (например, в smoke-тестах
        # PluginManager) БД может быть недоступна/заглушкой -- пропускаем
        # регистрацию, восстанавливать там всё равно нечего.
        if not self.ctx.bot.guilds:
            return

        async with self.ctx.db.session() as session:
            events = await FlightEventRepository(session).all_upcoming()

        for event in events:
            self.ctx.bot.add_view(EventParticipationView(self.ctx, event.id))
        self.log.info("Зарегистрировано персистентных View для %d предстоящих событий", len(events))


PLUGIN_CLASS = FlightEventsPlugin
