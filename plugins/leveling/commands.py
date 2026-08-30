"""``/level``, ``/leaderboard``, ``/rep`` -- XP и репутация (ТЗ §41, "XP / reputation")."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from database.repositories.stats_repository import StatsRepository

REP_COOLDOWN_SECONDS = 24 * 3600


class LevelingCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._rep_cooldowns: dict[tuple[int, int], float] = {}  # (guild_id, giver_id) -> last timestamp

    @app_commands.command(name="level", description="Показать уровень/опыт/налёт участника")
    @app_commands.describe(member="Участник (по умолчанию -- вы)")
    async def level(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        async with self.ctx.db.session() as session:
            stats = await StatsRepository(session).get_or_create(interaction.guild_id, target.id)

        xp_for_next = (stats.level + 1) ** 2 * 100
        embed = discord.Embed(title=f"⭐ {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Уровень", value=str(stats.level), inline=True)
        embed.add_field(name="Опыт", value=f"{stats.xp} / {xp_for_next}", inline=True)
        embed.add_field(name="Репутация", value=str(stats.reputation), inline=True)
        embed.add_field(name="Сообщений", value=str(stats.messages_count), inline=True)
        hours, mins = divmod(stats.flight_minutes, 60)
        embed.add_field(name="Налёт", value=f"{hours}ч {mins}м", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Топ участников сервера по опыту")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            top = await StatsRepository(session).leaderboard(interaction.guild_id, limit=10)

        if not top:
            await interaction.followup.send("Пока никто не набрал опыт.", ephemeral=True)
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, stats in enumerate(top):
            member = interaction.guild.get_member(stats.user_id)
            name = member.display_name if member else f"`{stats.user_id}`"
            prefix = medals[i] if i < len(medals) else f"`{i + 1}.`"
            lines.append(f"{prefix} {name} -- уровень {stats.level} ({stats.xp} XP)")

        embed = discord.Embed(title="🏆 Топ сервера", description="\n".join(lines), color=discord.Color.gold())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="rep", description="Выдать репутацию участнику (раз в 24 часа)")
    @app_commands.describe(member="Кому выдать репутацию")
    async def rep(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if member.id == interaction.user.id:
            await interaction.response.send_message("⚠️ Нельзя выдать репутацию самому себе.", ephemeral=True)
            return

        key = (interaction.guild_id, interaction.user.id)
        last = self._rep_cooldowns.get(key)
        now = time.monotonic()
        if last is not None and (now - last) < REP_COOLDOWN_SECONDS:
            remaining = REP_COOLDOWN_SECONDS - (now - last)
            await interaction.response.send_message(f"⏳ Вы сможете выдать репутацию снова через {remaining / 3600:.1f} ч.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            stats = await StatsRepository(session).add_reputation(interaction.guild_id, member.id)
        self._rep_cooldowns[key] = now
        await interaction.followup.send(f"✅ {member.mention} теперь имеет {stats.reputation} репутации.", ephemeral=True)


def build_leveling_cog(ctx) -> LevelingCog:
    return LevelingCog(ctx)
