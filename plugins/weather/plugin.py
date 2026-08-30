"""Плагин ``weather``: METAR/TAF по коду ICAO (ТЗ §41, "Авиационная информация")."""
from __future__ import annotations

import aiohttp

from core.base_plugin import BasePlugin, PluginMeta
from plugins.weather.commands import build_weather_cog


class WeatherPlugin(BasePlugin):
    meta = PluginMeta(
        name="weather", version="1.0.0",
        description="/weather metar|taf -- авиационная погода по коду ICAO",
        dependencies=(), requires_db=False,
    )

    async def setup(self) -> None:
        # Собственная aiohttp-сессия, а не общая сессия discord.py -- чтобы
        # жизненный цикл HTTP-соединений к внешнему API погоды был явно
        # привязан к жизненному циклу именно этого плагина (создаётся в
        # setup, закрывается в stop -- переживёт горячую перезагрузку
        # без утечки соединений).
        self.session = aiohttp.ClientSession()
        await self.ctx.add_cog(build_weather_cog(self.ctx, self))
        self.log.info("weather готов к работе")

    async def stop(self) -> None:
        await self.session.close()


PLUGIN_CLASS = WeatherPlugin
