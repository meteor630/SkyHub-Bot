"""``/weather`` -- METAR/TAF по коду ICAO (ТЗ §41)."""
from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from plugins.weather.service import WeatherError, fetch_raw, parse_metar, strip_report_prefix
from utils.text import truncate

# Настоящие ICAO-коды аэропортов -- ровно 4 латинские буквы/цифры
# (напр. ULLI, KJFK). Проверяем формат до похода во внешний API --
# отклоняем мусор сразу, а не по ответу стороннего сервиса (найдено
# при аудите безопасности: без проверки в запрос уходила бы любая
# строка произвольной длины, введённая пользователем).
_ICAO_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


class WeatherCog(commands.Cog):
    weather_group = app_commands.Group(name="weather", description="Авиационная погода (METAR/TAF)")

    def __init__(self, ctx, plugin) -> None:
        self.ctx = ctx
        self.plugin = plugin

    @weather_group.command(name="metar", description="Текущий METAR аэропорта")
    @app_commands.describe(icao="Код ICAO аэропорта, напр. ULLI")
    async def metar(self, interaction: discord.Interaction, icao: str) -> None:
        await interaction.response.defer()
        icao = icao.strip().upper()
        if not _ICAO_PATTERN.match(icao):
            await interaction.followup.send("⚠️ Код ICAO должен состоять ровно из 4 латинских букв/цифр, напр. `ULLI`.")
            return
        try:
            raw = await fetch_raw(self.plugin.session, "metar", icao)
            obs = parse_metar(raw)
        except WeatherError as exc:
            await interaction.followup.send(f"⚠️ {exc}")
            return

        embed = discord.Embed(title=f"✈️ {icao} -- METAR", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Ветер", value=obs.wind() or "—", inline=True)
        embed.add_field(name="Видимость", value=obs.visibility() or "—", inline=True)
        embed.add_field(name="Облачность", value=obs.sky_conditions("\n") or "Ясно", inline=False)
        if obs.press is not None:
            embed.add_field(name="QNH", value=f"{obs.press.value('hPa'):.0f} гПа", inline=True)
        if obs.temp is not None:
            embed.add_field(name="Температура", value=f"{obs.temp.value('C'):.0f}°C", inline=True)
        if obs.dewpt is not None:
            embed.add_field(name="Точка росы", value=f"{obs.dewpt.value('C'):.0f}°C", inline=True)
        embed.add_field(name="Raw METAR", value=f"```{truncate(raw, 1000)}```", inline=False)
        embed.set_footer(text="Источник: aviationweather.gov (NOAA)")
        await interaction.followup.send(embed=embed)

    @weather_group.command(name="taf", description="Прогноз TAF аэропорта")
    @app_commands.describe(icao="Код ICAO аэропорта, напр. ULLI")
    async def taf(self, interaction: discord.Interaction, icao: str) -> None:
        await interaction.response.defer()
        icao = icao.strip().upper()
        if not _ICAO_PATTERN.match(icao):
            await interaction.followup.send("⚠️ Код ICAO должен состоять ровно из 4 латинских букв/цифр, напр. `ULLI`.")
            return
        try:
            raw = await fetch_raw(self.plugin.session, "taf", icao)
        except WeatherError as exc:
            await interaction.followup.send(f"⚠️ {exc}")
            return

        body = strip_report_prefix(raw, "taf")
        embed = discord.Embed(
            title=f"✈️ {icao} -- TAF", description=f"```{truncate(body, 4000)}```",
            color=discord.Color.blue(), timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Источник: aviationweather.gov (NOAA)")
        await interaction.followup.send(embed=embed)


def build_weather_cog(ctx, plugin) -> WeatherCog:
    return WeatherCog(ctx, plugin)
