"""Персистентные кнопки тикетов (ТЗ §41, "Support / Tickets", ТЗ §34).

В отличие от панели `/voice` (живёт, пока жив процесс бота), кнопки
тикетов регистрируются через ``bot.add_view()`` с фиксированными
``custom_id`` при загрузке плагина -- они продолжают работать даже
после перезапуска процесса, потому что discord.py сопоставляет нажатие
кнопки с обработчиком по ``custom_id``, а не по тому, что вью-объект
всё ещё "жив" в памяти той же сессии.

Каждый тикет живёт в ДВУХ местах одновременно (см. модуль-докстринг
``database/models/ticket.py`` и ``plugins/tickets/forum.py`` -- почему
именно так, а не одним общим форумом): приватный текстовый канал для
автора и, если настроен ``tickets_forum_channel_id``, пост в приватном
форуме для сапорта. ``plugins/tickets/bridge.py`` зеркалит сообщения
между ними -- этот модуль отвечает только за сам жизненный цикл тикета
(создание/закрытие), не за пересылку сообщений.
"""
from __future__ import annotations

import discord

from database.models.ticket import STATUS_OPEN
from database.repositories.ticket_repository import TicketRepository
from plugins.tickets import forum as ticket_forum

MAX_OPEN_TICKETS_PER_USER = 3


class TicketPanelView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx
        # Защита от гонки: между проверкой open_count_for_user и вставкой
        # новой записи в БД есть асинхронный промежуток -- пара быстрых
        # повторных нажатий (двойной клик, автокликер) иначе могла бы
        # пройти проверку лимита одновременно и создать больше каналов,
        # чем MAX_OPEN_TICKETS_PER_USER (найдено при аудите безопасности).
        self._creating: set[tuple[int, int]] = set()

    @discord.ui.button(label="Создать обращение", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="tickets:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return

        key = (guild.id, interaction.user.id)
        if key in self._creating:
            await interaction.followup.send("⚠️ Обращение уже создаётся -- подождите пару секунд.", ephemeral=True)
            return
        self._creating.add(key)
        try:
            await self._create_ticket(interaction, guild)
        finally:
            self._creating.discard(key)

    async def _create_ticket(self, interaction: discord.Interaction, guild: discord.Guild) -> None:
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

        # Одни и те же роли видят и приватный канал, и (если настроен)
        # форум-пост -- см. plugins/tickets/forum.py.
        staff_role_ids = await ticket_forum.viewer_role_ids(self.ctx, guild.id)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        for role_id in staff_role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        safe_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:90]
        channel = await guild.create_text_channel(name=safe_name, category=category, overwrites=overwrites)

        async with self.ctx.db.session() as session:
            ticket = await TicketRepository(session).create(
                guild_id=guild.id, channel_id=channel.id, creator_id=interaction.user.id, reason=None,
            )
            ticket_id = ticket.id

        embed = discord.Embed(
            title="🎫 Новое обращение",
            description=f"{interaction.user.mention}, опишите вашу проблему -- в ближайшее время подключится поддержка.",
            color=discord.Color.blurple(),
        )
        await channel.send(embed=embed, view=TicketControlView(self.ctx))

        await self._create_forum_post(guild, channel=channel, creator=interaction.user, ticket_id=ticket_id)

        await interaction.followup.send(f"✅ Обращение создано: {channel.mention}", ephemeral=True)

    async def _create_forum_post(
        self, guild: discord.Guild, *, channel: discord.TextChannel, creator: discord.abc.User, ticket_id: int,
    ) -> None:
        """Создаёт пост в форуме сапорта, если ``/setup tickets-forum``
        настроен -- необязательный шаг: если форум не настроен или его
        не удалось создать, тикет всё равно полностью работает через
        приватный канал (просто без "витрины" для сапорта)."""
        forum_channel_id = await self.ctx.guild_config().resolve_channel_id(guild.id, "tickets_forum")
        forum = guild.get_channel(forum_channel_id) if forum_channel_id else None
        if not isinstance(forum, discord.ForumChannel):
            return

        try:
            tags = await ticket_forum.ensure_forum_tags(forum)
            starter = discord.Embed(
                title=f"🎫 Обращение -- {creator.display_name}",
                description=f"Автор: {creator.mention}\nКанал: {channel.mention}",
                color=discord.Color.blurple(),
            )
            result = await forum.create_thread(
                name=f"{creator.display_name} -- #{ticket_id}"[:100],
                embed=starter,
                applied_tags=[tags[ticket_forum.TAG_OPEN]],
                view=TicketControlView(self.ctx),
                reason=f"Тикет #{ticket_id} от {creator}",
            )
            async with self.ctx.db.session() as session:
                await TicketRepository(session).set_forum_thread(ticket_id, result.thread.id)
        except Exception as exc:  # noqa: BLE001 -- форум необязателен, не должен ломать создание тикета
            await self.ctx.report_error(exc, event="ticket_forum_post", guild_id=guild.id, ticket_id=ticket_id)


class TicketControlView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="Закрыть обращение", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tickets:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await close_ticket(self.ctx, interaction)


async def close_ticket(ctx, interaction: discord.Interaction) -> None:
    """Закрывает тикет -- кнопка/команда работают ОДИНАКОВО что из
    приватного канала автора, что из поста форума сапорта (у обоих один
    и тот же custom_id "tickets:close", см. :class:`TicketControlView`),
    поэтому здесь нужно определить, откуда именно нажали."""
    async with ctx.db.session() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_by_channel_id(interaction.channel_id)
        if ticket is None:
            ticket = await repo.get_by_forum_thread_id(interaction.channel_id)
        if ticket is None or ticket.status != STATUS_OPEN:
            await interaction.response.send_message("⚠️ Это не открытое обращение.", ephemeral=True)
            return
        channel_id = ticket.channel_id
        forum_thread_id = ticket.forum_thread_id
        creator_id = ticket.creator_id
        await repo.close(channel_id, interaction.user.id)

    closed_from_forum = interaction.channel_id == forum_thread_id
    await interaction.response.send_message("🔒 Обращение закрыто.")

    # Приватный канал НЕ удаляется сразу (в отличие от старого
    # поведения) -- только запрещаем автору писать дальше, чтобы
    # переписка осталась доступна для истории. Автоудаление -- через
    # сутки для канала / через месяц для поста форума, отдельной
    # фоновой задачей (см. plugins/tickets/plugin.py).
    guild = interaction.guild
    creator = guild.get_member(creator_id) if guild else None
    private_channel = guild.get_channel(channel_id) if guild else None
    if creator is not None and isinstance(private_channel, discord.TextChannel):
        try:
            await private_channel.set_permissions(
                creator, view_channel=True, send_messages=False, read_message_history=True,
                reason="Обращение закрыто",
            )
        except discord.HTTPException:
            pass

    # Если закрыли из форума -- автор кнопку/сообщение сапорта не
    # видел (форум ему не показывается вообще, см. plugins/tickets/forum.py),
    # поэтому дублируем уведомление в его собственный канал.
    if closed_from_forum and isinstance(private_channel, discord.TextChannel):
        try:
            await private_channel.send(f"🔒 Обращение закрыто сапортом ({interaction.user.mention}).")
        except discord.HTTPException:
            pass

    if forum_thread_id:
        await _archive_forum_thread(ctx, forum_thread_id)


async def _archive_forum_thread(ctx, forum_thread_id: int) -> None:
    try:
        thread = ctx.bot.get_channel(forum_thread_id) or await ctx.bot.fetch_channel(forum_thread_id)
        if not isinstance(thread, discord.Thread) or not isinstance(thread.parent, discord.ForumChannel):
            return
        tags = await ticket_forum.ensure_forum_tags(thread.parent)
        applied = [tag for tag in thread.applied_tags if tag.name != ticket_forum.TAG_OPEN]
        applied.append(tags[ticket_forum.TAG_CLOSED])
        await thread.edit(applied_tags=applied, archived=True, locked=True, reason="Обращение закрыто")
    except (discord.HTTPException, discord.NotFound, KeyError) as exc:
        await ctx.report_error(exc, event="ticket_forum_archive", forum_thread_id=forum_thread_id)
