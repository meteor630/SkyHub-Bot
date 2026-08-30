"""``/event create`` и ``/event list`` -- совместные вылеты (ТЗ §41, "Flight events")."""
from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from database.repositories.flight_repository import FlightEventRepository
from plugins.flight_events.views import EventParticipationView, build_event_embed

DATE_FORMAT = "%Y-%m-%d %H:%M"


class CreateEventModal(discord.ui.Modal, title="Новый совместный вылет"):
    event_title = discord.ui.TextInput(label="Название события", max_length=100, placeholder="Групповой перелёт выходного дня")
    route = discord.ui.TextInput(label="Маршрут", max_length=100, placeholder="UUEE-ULLI")
    aircraft = discord.ui.TextInput(label="Самолёт", max_length=100, placeholder="A320")
    event_time = discord.ui.TextInput(
        label="Дата и время (UTC)", max_length=32, placeholder="2026-09-05 20:00"
    )
    max_participants = discord.ui.TextInput(
        label="Лимит участников (0 = без лимита)", max_length=5, default="0", required=False
    )

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            event_dt = datetime.strptime(str(self.event_time), DATE_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            await interaction.response.send_message(
                "⚠️ Неверный формат даты. Используйте `ГГГГ-ММ-ДД ЧЧ:ММ` (UTC), например `2026-09-05 20:00`.",
                ephemeral=True,
            )
            return

        try:
            limit = int(str(self.max_participants) or "0")
        except ValueError:
            limit = 0

        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        if channel is None or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send("⚠️ Событие можно создать только в текстовом канале.", ephemeral=True)
            return

        async with self.ctx.db.session() as session:
            repo = FlightEventRepository(session)
            event = await repo.create(
                guild_id=interaction.guild_id,
                channel_id=channel.id,
                title=str(self.event_title),
                route=str(self.route),
                aircraft=str(self.aircraft),
                event_time=event_dt,
                max_participants=limit,
                created_by_id=interaction.user.id,
            )
            event_id = event.id

        embed = build_event_embed(event, participant_count=0)
        view = EventParticipationView(self.ctx, event_id)
        message = await channel.send(embed=embed, view=view)

        async with self.ctx.db.session() as session:
            await FlightEventRepository(session).set_message_id(event_id, message.id)

        await interaction.followup.send(f"✅ Событие создано: {message.jump_url}", ephemeral=True)


class FlightEventCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    event_group = app_commands.Group(name="event", description="Совместные вылеты")

    @event_group.command(name="create", description="Создать совместный вылет")
    async def create(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateEventModal(self.ctx))

    @event_group.command(name="list", description="Показать ближайшие совместные вылеты")
    async def list_events(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            repo = FlightEventRepository(session)
            events = await repo.upcoming_for_guild(interaction.guild_id)

        if not events:
            await interaction.followup.send("Ближайших вылетов не запланировано.", ephemeral=True)
            return

        lines = []
        for event in events:
            lines.append(f"**{event.title}** -- {event.route} ({event.aircraft}) -- <t:{int(event.event_time.timestamp())}:R>")

        embed = discord.Embed(title="✈️ Ближайшие совместные вылеты", description="\n".join(lines), color=discord.Color.purple())
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_flight_event_cog(ctx) -> FlightEventCog:
    return FlightEventCog(ctx)
