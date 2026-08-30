"""``/audit`` -- единый таймлайн событий по каждому пользователю (идея клиента №2)."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import Role, require
from database.repositories.audit_repository import AuditRepository
from utils.time import discord_full


class AuditCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @app_commands.command(name="audit", description="Показать таймлайн событий участника")
    @app_commands.describe(member="Участник")
    @require(Role.SUPPORT)
    async def audit(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            entries = await AuditRepository(session).timeline_for(interaction.guild_id, member.id)

        if not entries:
            await interaction.followup.send("Событий не найдено.", ephemeral=True)
            return

        lines = [f"{discord_full(e.created_at)} — {e.summary}" for e in entries]
        embed = discord.Embed(
            title=f"🕓 Таймлайн: {member.display_name}",
            description="\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_audit_cog(ctx) -> AuditCog:
    return AuditCog(ctx)
