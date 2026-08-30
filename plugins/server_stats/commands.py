"""``/server stats`` -- общая статистика сервера (ТЗ §41, "/server статистика").

Собирает воедино данные всех остальных фич Фазы 8: авиа-профили
(:mod:`plugins.aviation_profile`), бортжурнал (:mod:`plugins.flight_log`),
тикеты (:mod:`plugins.tickets`) и XP (:mod:`plugins.leveling`) --
намеренно не хранит собственных данных."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database.repositories.flight_repository import FlightLogRepository
from database.repositories.profile_repository import ProfileRepository
from database.repositories.stats_repository import StatsRepository
from database.repositories.ticket_repository import TicketRepository
from plugins.aviation_profile.commands import ROLE_TYPE_LABELS


class ServerStatsCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    server_group = app_commands.Group(name="server", description="Статистика сервера")

    @server_group.command(name="stats", description="Показать сводную статистику сервера")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        guild_id = interaction.guild_id

        async with self.ctx.db.session() as session:
            role_counts = await ProfileRepository(session).role_type_counts(guild_id)
            total_minutes, total_messages = await StatsRepository(session).guild_totals(guild_id)
            flight_count = await FlightLogRepository(session).count_for_guild(guild_id)
            open_tickets, closed_tickets = await TicketRepository(session).counts_for_guild(guild_id)

        embed = discord.Embed(title=f"📊 Статистика сервера {guild.name}", color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        members_online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        voice_members = sum(len(vc.members) for vc in guild.voice_channels)
        embed.add_field(name="Участников", value=f"{guild.member_count} (в сети: {members_online})", inline=True)
        embed.add_field(name="В голосовых каналах", value=str(voice_members), inline=True)
        embed.add_field(name="Каналов", value=str(len(guild.channels)), inline=True)

        hours, mins = divmod(total_minutes, 60)
        embed.add_field(name="Всего рейсов залогировано", value=str(flight_count), inline=True)
        embed.add_field(name="Суммарный налёт", value=f"{hours}ч {mins}м", inline=True)
        embed.add_field(name="Сообщений (учтено XP)", value=str(total_messages), inline=True)

        embed.add_field(name="Тикеты", value=f"открыто: {open_tickets} / закрыто: {closed_tickets}", inline=True)

        if role_counts:
            lines = [f"{ROLE_TYPE_LABELS.get(role_type, role_type)}: {count}" for role_type, count in role_counts.items()]
            embed.add_field(name="Авиа-профили участников", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Авиа-профили участников", value="Пока никто не заполнил профиль (`/profile set`)", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


def build_server_stats_cog(ctx) -> ServerStatsCog:
    return ServerStatsCog(ctx)
