"""``/ticket`` -- панель создания обращений и закрытие тикета командой."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import Role, require
from plugins.tickets.views import TicketPanelView, close_ticket


class TicketCog(commands.Cog):
    ticket_group = app_commands.Group(name="ticket", description="Система обращений в поддержку", guild_only=True)

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @ticket_group.command(name="panel", description="Опубликовать кнопку создания обращения в этом канале")
    @require(Role.ADMIN)
    async def panel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎫 Поддержка",
            description="Нажмите кнопку ниже, чтобы создать приватное обращение - с вами свяжется специалист.",
            color=discord.Color.blurple(),
        )
        # Панель отправляется ОБЫЧНЫМ сообщением в канал, а не прямым
        # ответом на интеракцию -- у прямого ответа Discord всегда
        # добавляет сверху строку "Имя использует /ticket panel", что
        # для постоянной панели (не разового ответа) смотрится лишним.
        # Подтверждение админу, наоборот, ephemeral -- его никто, кроме
        # нажавшего, не увидит.
        await interaction.channel.send(embed=embed, view=TicketPanelView(self.ctx))
        await interaction.response.send_message("✅ Панель опубликована.", ephemeral=True)

    @ticket_group.command(name="close", description="Закрыть текущее обращение (внутри канала тикета)")
    async def close(self, interaction: discord.Interaction) -> None:
        await close_ticket(self.ctx, interaction)


def build_ticket_cog(ctx) -> TicketCog:
    return TicketCog(ctx)
