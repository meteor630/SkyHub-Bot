"""Плагин ``flight_log``: личный бортжурнал пилота (ТЗ §41, "Flight logging").

Публикует :class:`core.events.FlightLogged` при каждой записи -- на это
подписан ``plugins/leveling``, который прибавляет налёт к статистике
участника, не будучи связанным с этим плагином напрямую (Event Bus,
ТЗ §19).
"""
from __future__ import annotations

from core.base_plugin import BasePlugin, PluginMeta
from plugins.flight_log.commands import build_flight_log_cog


class FlightLogPlugin(BasePlugin):
    meta = PluginMeta(
        name="flight_log", version="1.0.0",
        description="/flight log|history|stats -- личный бортжурнал пилота",
        dependencies=(),
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(build_flight_log_cog(self.ctx))
        self.log.info("flight_log готов к работе")


PLUGIN_CLASS = FlightLogPlugin
