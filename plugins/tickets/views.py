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

Создание обращения -- ТРИ отдельных взаимодействия Discord, не одно:
кнопка -> выбор темы (обычный ``discord.ui.Select``) -> модальное окно
с текстом обращения. Это не наш выбор усложнить UX -- у Discord модальные
окна умеют показывать ТОЛЬКО текстовые поля (``TextInput``), выпадающий
список внутри модального окна не работает (подтверждено официальным
трекером Discord: https://github.com/discord/discord-api-docs/discussions/5883
-- значение выбора там приходит пустым). Поэтому тема выбирается
ОТДЕЛЬНЫМ шагом до модального окна, а не полем в нём.
"""
from __future__ import annotations

import datetime as dt

import discord

from database.models.ticket import STATUS_CLOSED, STATUS_OPEN
from database.repositories.ticket_repository import TicketRepository
from plugins.tickets import forum as ticket_forum

MAX_OPEN_TICKETS_PER_USER = 3
# Пауза между созданием обращений одним участником -- защита от спама
# кнопкой (клиентский запрос). Считается от created_at последнего
# обращения (в т.ч. уже закрытого), не только открытых.
CREATE_COOLDOWN_SECONDS = 180

# Темы обращения -- показываются участнику выпадающим списком перед
# модальным окном с текстом, а выбранная тема попадает в заголовок
# поста форума для сапорта (см. _create_forum_post) и в сам текст
# обращения. Меняйте список свободно под свои нужды сервера -- (value,
# подпись с эмодзи).
TICKET_TOPICS: list[tuple[str, str]] = [
    ("general", "❓ Общий вопрос"),
    ("bug", "🐛 Проблема/баг"),
    ("report", "⚠️ Жалоба на участника"),
    ("suggestion", "💡 Предложение"),
    ("other", "📦 Другое"),
]


class TicketPanelView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx
        # Защита от гонки: пара быстрых повторных нажатий (двойной
        # клик, автокликер) иначе могла бы открыть выбор темы дважды
        # параллельно (найдено при аудите безопасности).
        self._creating: set[tuple[int, int]] = set()

    @discord.ui.button(label="Создать обращение", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="tickets:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        guild = interaction.guild
        if guild is None:
            return

        key = (guild.id, interaction.user.id)
        if key in self._creating:
            await interaction.response.send_message("⚠️ Обращение уже создаётся -- подождите пару секунд.", ephemeral=True)
            return
        self._creating.add(key)
        try:
            await self._start_ticket_flow(interaction, guild)
        finally:
            self._creating.discard(key)

    async def _start_ticket_flow(self, interaction: discord.Interaction, guild: discord.Guild) -> None:
        """Проверяет лимиты и, если всё в порядке, показывает выбор
        темы -- ДО модального окна с текстом, чтобы не заставлять
        человека печатать обращение, если ему всё равно откажут."""
        category_id = await self.ctx.guild_config().resolve_category_id(guild.id, "tickets")
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("⚠️ Категория для тикетов ещё не настроена -- обратитесь к администратору (`/setup tickets`).", ephemeral=True)
            return

        async with self.ctx.db.session() as session:
            repo = TicketRepository(session)
            open_count = await repo.open_count_for_user(guild.id, interaction.user.id)
            last_created = await repo.latest_created_at(guild.id, interaction.user.id)

        if open_count >= MAX_OPEN_TICKETS_PER_USER:
            await interaction.response.send_message(f"⚠️ У вас уже открыто {open_count} обращени(й) -- закройте старые, прежде чем создавать новые.", ephemeral=True)
            return

        if last_created is not None:
            elapsed = (dt.datetime.now(dt.UTC) - last_created).total_seconds()
            if elapsed < CREATE_COOLDOWN_SECONDS:
                remaining = int(CREATE_COOLDOWN_SECONDS - elapsed) + 1
                await interaction.response.send_message(f"⚠️ Подождите ещё {remaining} сек. перед созданием нового обращения.", ephemeral=True)
                return

        await interaction.response.send_message(
            "Выберите тему обращения:", view=TicketTopicSelectView(self.ctx), ephemeral=True,
        )


class TicketTopicSelectView(discord.ui.View):
    """Первый шаг создания тикета -- выбор темы. Короткоживущий,
    НЕ персистентный (в отличие от остальных View тут) -- это
    промежуточный экран одного разового ephemeral-взаимодействия, ему
    не нужно переживать перезапуск бота."""

    def __init__(self, ctx) -> None:
        super().__init__(timeout=300)
        self.ctx = ctx
        select = discord.ui.Select(
            placeholder="Тема обращения",
            options=[discord.SelectOption(label=label, value=value) for value, label in TICKET_TOPICS],
        )
        select.callback = self._callback(select)
        self.add_item(select)

    def _callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            topic_label = dict(TICKET_TOPICS).get(select.values[0], select.values[0])
            # send_modal ДОЛЖЕН быть первым ответом на это взаимодействие --
            # поэтому тут нельзя предварительно defer()/send_message().
            await interaction.response.send_modal(TicketDescriptionModal(self.ctx, topic=topic_label))

        return callback


class TicketDescriptionModal(discord.ui.Modal):
    """Второй (и последний) шаг -- собственно текст обращения. Модальные
    окна Discord поддерживают только текстовые поля, поэтому тема сюда
    не входит -- она уже выбрана предыдущим шагом и просто передаётся
    в конструктор."""

    def __init__(self, ctx, *, topic: str) -> None:
        super().__init__(title="Создать обращение"[:45])
        self.ctx = ctx
        self.topic = topic
        self.description_input = discord.ui.TextInput(
            label="Опишите вашу проблему", style=discord.TextStyle.paragraph,
            max_length=1000, required=True,
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return
        await _create_ticket(self.ctx, interaction, guild, topic=self.topic, description=str(self.description_input.value))


async def _create_ticket(ctx, interaction: discord.Interaction, guild: discord.Guild, *, topic: str, description: str) -> None:
    category_id = await ctx.guild_config().resolve_category_id(guild.id, "tickets")
    category = guild.get_channel(category_id) if category_id else None
    if not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send("⚠️ Категория для тикетов ещё не настроена -- обратитесь к администратору (`/setup tickets`).", ephemeral=True)
        return

    async with ctx.db.session() as session:
        # Повторная проверка лимита открытых обращений -- между показом
        # выбора темы и сабмитом модального окна проходит время живого
        # человеческого взаимодействия, за которое состояние могло
        # измениться (найдено при аудите безопасности).
        open_count = await TicketRepository(session).open_count_for_user(guild.id, interaction.user.id)
    if open_count >= MAX_OPEN_TICKETS_PER_USER:
        await interaction.followup.send(f"⚠️ У вас уже открыто {open_count} обращени(й) -- закройте старые, прежде чем создавать новые.", ephemeral=True)
        return

    # Одни и те же роли видят и приватный канал, и (если настроен)
    # форум-пост -- см. plugins/tickets/forum.py.
    staff_role_ids = await ticket_forum.viewer_role_ids(ctx, guild.id)

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

    async with ctx.db.session() as session:
        ticket = await TicketRepository(session).create(
            guild_id=guild.id, channel_id=channel.id, creator_id=interaction.user.id,
            reason=f"{topic}: {description}"[:500],
        )
        ticket_id = ticket.id

    embed = discord.Embed(
        title="🎫 Новое обращение",
        description=f"**Тема:** {topic}\n\n{description}",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="В ближайшее время подключится поддержка")
    await channel.send(content=interaction.user.mention, embed=embed, view=TicketControlView(ctx))

    await _create_forum_post(ctx, guild, channel=channel, creator=interaction.user, ticket_id=ticket_id, topic=topic, description=description)

    await interaction.followup.send(f"✅ Обращение создано: {channel.mention}", ephemeral=True)


async def _create_forum_post(
    ctx, guild: discord.Guild, *, channel: discord.TextChannel, creator: discord.abc.User,
    ticket_id: int, topic: str, description: str,
) -> None:
    """Создаёт пост в форуме сапорта, если ``/setup tickets-forum``
    настроен -- необязательный шаг: если форум не настроен или его не
    удалось создать, тикет всё равно полностью работает через приватный
    канал (просто без "витрины" для сапорта). Выбранная тема попадает
    прямо в НАЗВАНИЕ поста -- сапорт видит причину обращения в списке
    постов форума, не открывая каждый по отдельности."""
    forum_channel_id = await ctx.guild_config().resolve_channel_id(guild.id, "tickets_forum")
    forum = guild.get_channel(forum_channel_id) if forum_channel_id else None
    if not isinstance(forum, discord.ForumChannel):
        return

    try:
        tags = await ticket_forum.ensure_forum_tags(forum)
        starter = discord.Embed(
            title=f"🎫 {topic} -- {creator.display_name}",
            description=f"Автор: {creator.mention}\nКанал: {channel.mention}\n\n{description}",
            color=discord.Color.blurple(),
        )
        result = await forum.create_thread(
            name=f"{topic} -- {creator.display_name}"[:100],
            embed=starter,
            applied_tags=[tags[ticket_forum.TAG_OPEN]],
            view=TicketControlView(ctx),
            reason=f"Тикет #{ticket_id} от {creator}",
        )
        async with ctx.db.session() as session:
            await TicketRepository(session).set_forum_thread(ticket_id, result.thread.id)
    except Exception as exc:  # noqa: BLE001 -- форум необязателен, не должен ломать создание тикета
        await ctx.report_error(exc, event="ticket_forum_post", guild_id=guild.id, ticket_id=ticket_id)


class TicketControlView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="Закрыть обращение", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tickets:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await close_ticket(self.ctx, interaction)


class TicketDeleteView(discord.ui.View):
    """Кнопка ТОЛЬКО для приватного канала ЗАКРЫТОГО тикета -- автор
    (или сапорт) может сразу удалить свою копию, не дожидаясь
    автоудаления через ``CHANNEL_PURGE_AFTER_DAYS`` (см.
    plugins/tickets/plugin.py) -- чтобы список каналов не засорялся
    старыми закрытыми обращениями (клиентский запрос)."""

    def __init__(self, ctx) -> None:
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="Удалить чат", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="tickets:delete_channel")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self.ctx.db.session() as session:
            ticket = await TicketRepository(session).get_by_channel_id(interaction.channel_id)

        if ticket is None:
            await interaction.response.send_message("⚠️ Обращение не найдено.", ephemeral=True)
            return
        if ticket.status != STATUS_CLOSED:
            await interaction.response.send_message("⚠️ Сначала закройте обращение кнопкой «Закрыть» -- удалить можно только закрытый чат.", ephemeral=True)
            return

        is_author = interaction.user.id == ticket.creator_id
        is_staff = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_channels
        if not (is_author or is_staff):
            await interaction.response.send_message("⚠️ Удалить канал может только автор обращения (или сапорт).", ephemeral=True)
            return

        await interaction.response.send_message("🗑️ Канал удаляется...")
        try:
            await interaction.channel.delete(reason=f"Автор удалил свой закрытый тикет ({interaction.user})")
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="ticket_manual_delete", channel_id=interaction.channel_id)


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
    delete_view = TicketDeleteView(ctx)

    # Приватный канал НЕ удаляется сразу (в отличие от старого
    # поведения) -- только запрещаем автору писать дальше, чтобы
    # переписка осталась доступна для истории. Автоудаление -- через
    # сутки для канала / через месяц для поста форума, отдельной
    # фоновой задачей (см. plugins/tickets/plugin.py) -- либо раньше,
    # если автор сам нажмёт "Удалить чат" ниже.
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

    if closed_from_forum:
        # Автор кнопку/сообщение сапорта в форуме не видел (форум ему
        # не показывается вообще, см. plugins/tickets/forum.py) --
        # уведомление и кнопка удаления идут отдельным сообщением сразу
        # в его канал, а тут -- просто короткое подтверждение сапорту.
        await interaction.response.send_message("🔒 Обращение закрыто.")
        if isinstance(private_channel, discord.TextChannel):
            try:
                await private_channel.send(
                    f"🔒 Обращение закрыто сапортом ({interaction.user.mention}). "
                    f"Можете удалить этот канал кнопкой ниже, когда он больше не нужен.",
                    view=delete_view,
                )
            except discord.HTTPException:
                pass
    else:
        await interaction.response.send_message(
            "🔒 Обращение закрыто. Можете удалить этот канал кнопкой ниже, когда он больше не нужен.",
            view=delete_view,
        )

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
