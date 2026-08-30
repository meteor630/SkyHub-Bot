"""Персистентные кнопки тикетов (ТЗ §41, "Support / Tickets", ТЗ §34).

В отличие от панели `/voice` (живёт, пока жив процесс бота), кнопки
тикетов регистрируются через ``bot.add_view()`` с фиксированными
``custom_id`` при загрузке плагина -- они продолжают работать даже
после перезапуска процесса, потому что discord.py сопоставляет нажатие
кнопки с обработчиком по ``custom_id``, а не по тому, что вью-объект
всё ещё "жив" в памяти той же сессии.
"""
from __future__ import annotations

import asyncio

import discord

from database.models.ticket import STATUS_OPEN
from database.repositories.ticket_repository import TicketRepository

MAX_OPEN_TICKETS_PER_USER = 3


class TicketPanelView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="Создать обращение", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="tickets:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return

        category_id = await self.ctx.guild_config().resolve_category_id(guild.id, "tickets")
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("⚠️ Категория для тикетов ещё не настроена -- обратитесь к администратору (`/setup tickets`).", ephemeral=True)
            return

        async with self.ctx.db.session() as session:
            repo = TicketRepository(session)
            open_count = await repo.open_count_for_user(guild.id, interaction.user.id)
            if open_count >= MAX_OPEN_TICKETS_PER_USER:
                await interaction.followup.send(f"⚠️ У вас уже открыто {open_count} обращени(й) -- закройте старые, прежде чем создавать новые.", ephemeral=True)
                return

        support_role_id = await self.ctx.guild_config().resolve_role_id(guild.id, "support")
        moderator_role_id = await self.ctx.guild_config().resolve_role_id(guild.id, "moderator")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        for role_id in {support_role_id, moderator_role_id} - {None}:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        safe_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:90]
        channel = await guild.create_text_channel(name=safe_name, category=category, overwrites=overwrites)

        async with self.ctx.db.session() as session:
            await TicketRepository(session).create(guild_id=guild.id, channel_id=channel.id, creator_id=interaction.user.id, reason=None)

        embed = discord.Embed(
            title="🎫 Новое обращение",
            description=f"{interaction.user.mention}, опишите вашу проблему -- в ближайшее время подключится поддержка.",
            color=discord.Color.blurple(),
        )
        await channel.send(embed=embed, view=TicketControlView(self.ctx))
        await interaction.followup.send(f"✅ Обращение создано: {channel.mention}", ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="Закрыть обращение", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tickets:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await close_ticket(self.ctx, interaction)


async def close_ticket(ctx, interaction: discord.Interaction) -> None:
    async with ctx.db.session() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_by_channel_id(interaction.channel_id)
        if ticket is None or ticket.status != STATUS_OPEN:
            await interaction.response.send_message("⚠️ Это не открытое обращение.", ephemeral=True)
            return
        await repo.close(interaction.channel_id, interaction.user.id)

    await interaction.response.send_message("🔒 Обращение закрывается через 5 секунд...")
    await asyncio.sleep(5)
    try:
        await interaction.channel.delete(reason=f"Тикет закрыт {interaction.user}")
    except discord.HTTPException:
        pass
