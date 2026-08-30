"""``/flight`` -- личный бортжурнал пилота (ТЗ §41, "Flight logging")."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.events import FlightLogged
from database.repositories.flight_repository import FlightLogRepository
from utils.text import truncate


def _parse_duration(text: str) -> int | None:
    """Принимает ``"2:15"``, ``"2ч15м"`` или просто число минут -- всё, что
    реально могут набрать руками, не заставляя гадать формат."""
    text = text.strip().lower().replace(" ", "")
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return int(parts[0]) * 60 + int(parts[1])
        return None
    if "ч" in text or "h" in text:
        for sep in ("ч", "h"):
            if sep in text:
                hours_part, _, rest = text.partition(sep)
                minutes_part = rest.replace("м", "").replace("m", "")
                try:
                    hours = int(hours_part) if hours_part else 0
                    minutes = int(minutes_part) if minutes_part else 0
                    return hours * 60 + minutes
                except ValueError:
                    return None
    if text.isdigit():
        return int(text)
    return None


class LogFlightModal(discord.ui.Modal, title="Новый рейс"):
    aircraft = discord.ui.TextInput(label="Самолёт", placeholder="напр. A320, B738, PMDG 777")
    route = discord.ui.TextInput(label="Маршрут (вылет-прилёт, ICAO)", placeholder="напр. ULLI-EFHK")
    duration = discord.ui.TextInput(label="Время в полёте", placeholder="напр. 1:45 или 105")
    network = discord.ui.TextInput(label="Сеть (VATSIM/IVAO/offline)", required=False)
    vatsim_id = discord.ui.TextInput(label="VATSIM ID (опционально)", required=False)

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        route_text = str(self.route).upper().replace(" ", "")
        if "-" not in route_text:
            await interaction.followup.send("⚠️ Маршрут укажите как ВЫЛЕТ-ПРИЛЁТ, например `ULLI-EFHK`.", ephemeral=True)
            return
        departure, _, arrival = route_text.partition("-")

        minutes = _parse_duration(str(self.duration))
        if minutes is None or minutes <= 0:
            await interaction.followup.send("⚠️ Не удалось разобрать время полёта -- используйте `1:45` или число минут.", ephemeral=True)
            return

        async with self.ctx.db.session() as session:
            record = await FlightLogRepository(session).add(
                guild_id=interaction.guild_id, user_id=interaction.user.id, aircraft=str(self.aircraft),
                departure_icao=departure, arrival_icao=arrival, flight_minutes=minutes,
                network=str(self.network) or None, vatsim_id=str(self.vatsim_id) or None,
            )

        self.ctx.emit(
            FlightLogged(
                guild_id=interaction.guild_id, user_id=interaction.user.id, aircraft=record.aircraft,
                departure_icao=record.departure_icao, arrival_icao=record.arrival_icao, flight_minutes=minutes,
            )
        )

        await self._post_flight_card(interaction, record, minutes)
        await interaction.followup.send("✅ Рейс записан в бортжурнал.", ephemeral=True)

    async def _post_flight_card(self, interaction: discord.Interaction, record, minutes: int) -> None:
        channel_id = await self.ctx.guild_config().resolve_channel_id(interaction.guild_id, "flight_log")
        if not channel_id:
            return
        channel = self.ctx.bot.get_channel(channel_id)
        if channel is None:
            return

        hours, mins = divmod(minutes, 60)
        embed = discord.Embed(title="✈️ Новый рейс", color=discord.Color.teal(), timestamp=discord.utils.utcnow())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Маршрут", value=f"{record.departure_icao} → {record.arrival_icao}", inline=True)
        embed.add_field(name="Самолёт", value=record.aircraft, inline=True)
        embed.add_field(name="Время в полёте", value=f"{hours}ч {mins}м", inline=True)
        if record.network:
            embed.add_field(name="Сеть", value=record.network, inline=True)
        if record.vatsim_id:
            embed.add_field(name="VATSIM ID", value=record.vatsim_id, inline=True)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_flight_card", guild_id=interaction.guild_id)


class FlightLogCog(commands.Cog):
    flight_group = app_commands.Group(name="flight", description="Личный бортжурнал", guild_only=True)

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @flight_group.command(name="log", description="Записать в бортжурнал завершённый рейс")
    async def log(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LogFlightModal(self.ctx))

    @flight_group.command(name="history", description="История рейсов участника")
    @app_commands.describe(member="Участник (по умолчанию -- вы)")
    async def history(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        async with self.ctx.db.session() as session:
            flights = await FlightLogRepository(session).history_for(interaction.guild_id, target.id)

        if not flights:
            await interaction.followup.send(f"У {target.mention} пока нет рейсов в бортжурнале.", ephemeral=True)
            return

        lines = []
        for f in flights:
            hours, mins = divmod(f.flight_minutes, 60)
            lines.append(f"`{f.created_at:%Y-%m-%d}` {f.departure_icao} → {f.arrival_icao} · {f.aircraft} · {hours}ч{mins}м")
        embed = discord.Embed(
            title=f"✈️ Бортжурнал: {target.display_name}", description=truncate("\n".join(lines), 4000),
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @flight_group.command(name="stats", description="Суммарная статистика налёта участника")
    @app_commands.describe(member="Участник (по умолчанию -- вы)")
    async def stats(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        async with self.ctx.db.session() as session:
            count, total_minutes = await FlightLogRepository(session).stats_for(interaction.guild_id, target.id)

        hours, mins = divmod(total_minutes, 60)
        embed = discord.Embed(title=f"📊 Налёт: {target.display_name}", color=discord.Color.teal())
        embed.add_field(name="Рейсов", value=str(count))
        embed.add_field(name="Общий налёт", value=f"{hours}ч {mins}м")
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_flight_log_cog(ctx) -> FlightLogCog:
    return FlightLogCog(ctx)
