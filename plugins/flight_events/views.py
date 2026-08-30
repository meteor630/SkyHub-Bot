"""Персистентные кнопки "Участвовать"/"Не участвовать" под карточкой
вылета (ТЗ §41, "Flight events"). Как и в ``plugins/tickets``, для
переживания перезапуска бот заново регистрирует по одному экземпляру
этого View на каждое ещё не прошедшее событие при старте
(``plugins/flight_events/plugin.py::start()``), а не полагается на то,
что объект View "доживёт" в памяти до следующего нажатия."""
from __future__ import annotations

import discord

from database.models.flight import FlightEvent
from database.repositories.flight_repository import FlightEventRepository


def build_event_embed(event: FlightEvent, participant_count: int) -> discord.Embed:
    embed = discord.Embed(title=f"✈️ {event.title}", color=discord.Color.purple())
    embed.add_field(name="Маршрут", value=event.route, inline=True)
    embed.add_field(name="Самолёт", value=event.aircraft, inline=True)
    embed.add_field(name="Дата", value=f"<t:{int(event.event_time.timestamp())}:F>", inline=False)
    limit_text = str(event.max_participants) if event.max_participants else "∞"
    embed.add_field(name="Участники", value=f"{participant_count}/{limit_text}", inline=True)
    embed.set_footer(text="Нажмите кнопку ниже, чтобы записаться или отменить участие")
    return embed


class EventParticipationView(discord.ui.View):
    def __init__(self, ctx, event_id: int) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx
        self.event_id = event_id

        join_btn = discord.ui.Button(
            label="Участвовать", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"flight_event:join:{event_id}"
        )
        join_btn.callback = self._join
        self.add_item(join_btn)

        leave_btn = discord.ui.Button(
            label="Не участвовать", emoji="❌", style=discord.ButtonStyle.secondary, custom_id=f"flight_event:leave:{event_id}"
        )
        leave_btn.callback = self._leave
        self.add_item(leave_btn)

    async def _join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            repo = FlightEventRepository(session)
            event = await repo.get(self.event_id)
            if event is None:
                await interaction.followup.send("⚠️ Событие не найдено (возможно, удалено).", ephemeral=True)
                return
            count = await repo.participant_count(self.event_id)
            already_in = await repo.is_participant(self.event_id, interaction.user.id)
            if event.max_participants and count >= event.max_participants and not already_in:
                await interaction.followup.send("⚠️ Свободных мест больше нет.", ephemeral=True)
                return
            joined = await repo.join(self.event_id, interaction.user.id)

        if joined:
            await self._refresh_embed(interaction)
            await interaction.followup.send("✅ Вы записаны на вылет.", ephemeral=True)
        else:
            await interaction.followup.send("Вы уже записаны.", ephemeral=True)

    async def _leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            left = await FlightEventRepository(session).leave(self.event_id, interaction.user.id)

        if left:
            await self._refresh_embed(interaction)
            await interaction.followup.send("Вы больше не участвуете.", ephemeral=True)
        else:
            await interaction.followup.send("Вы и не были записаны.", ephemeral=True)

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        async with self.ctx.db.session() as session:
            repo = FlightEventRepository(session)
            event = await repo.get(self.event_id)
            count = await repo.participant_count(self.event_id)
        if event is None or interaction.message is None:
            return
        try:
            await interaction.message.edit(embed=build_event_embed(event, count))
        except discord.HTTPException:
            pass
