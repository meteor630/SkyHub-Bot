"""``/setup`` -- настройка бота полностью из Discord (идея клиента №1).

Ни каналы, ни роли здесь **не** выбираются через нативные
``discord.ui.ChannelSelect``/``discord.ui.RoleSelect`` -- у обоих
компонентов на практике обнаружилась одна и та же проблема: список
вариантов иногда показывает не всё, что реально есть на сервере.

Расследование (по жалобе на каналы: новый канал `#ккк` виден боту через
API, права в порядке, `#`-упоминание в чате находит его мгновенно -- но
`discord.ui.ChannelSelect` в `/setup` его не показывает даже при новом
вызове команды; позже та же картина повторилась с ролями в
`discord.ui.RoleSelect` -- показывались не все существующие роли):

* discord.py (2.7.1, см. ``discord/ui/select.py::BaseSelect``) для
  ``ChannelSelect``/``RoleSelect`` отправляет Discord только
  ``channel_types``/тип компонента -- никакого списка каналов или
  ролей бот не передаёт и никак не кэширует, т.е. версия/код библиотеки
  тут ни при чём -- баг не в discord.py.
* Список вариантов для этих типов компонентов (auto-populated select,
  типы 6/8) целиком строит и отдаёт сервер Discord в момент открытия
  выпадающего списка -- через свой отдельный внутренний механизм,
  который не совпадает с тем, что используется для обычного
  `#`/`@`-упоминания в поле ввода сообщения. У этого механизма
  подтверждённая на практике задержка/неполнота индексации -- как для
  свежесозданных каналов, так и (как выяснилось позже) для части ролей
  сервера -- независимо от прав доступа и кэша бота.
* Единственный код, которым мы управляем, -- это ЧТО отправляется в
  Discord при создании компонента; самим списком вариантов внутри
  выпадающего меню мы не управляем вообще. Поэтому чинить нужно не
  фильтр/права/custom_id (они были в порядке), а сам способ выбора.

Решение: и канал, и роль теперь выбираются через собственные
``discord.ui.Select`` (``ManualChannelSelect``/``ManualRoleSelect``
ниже), варианты которых строятся вручную из ``guild.channels``/
``guild.roles`` -- то есть из **собственного** кэша бота, который
discord.py обновляет мгновенно по гейтвей-событиям
``CHANNEL_CREATE``/``GUILD_ROLE_CREATE`` и т.п., без какой-либо
зависимости от отдельного индекса Discord для auto-populated
компонентов. Внешний вид и порядок команд `/setup` не изменились;
сохранение выбора в ``guild_settings`` и инвалидация кэша (TTL-кэш
конфигурации сервера, карта ролей для прав доступа) -- как и раньше.

У обычного `discord.ui.Select` жёсткий лимит в 25 опций -- если
подходящих каналов/ролей на сервере больше, показываются первые 24 (по
позиции) плюс последний пункт-подсказка со ссылкой на запасные команды
``/setup channel`` и ``/setup role``/``/setup ignore-role`` (принимают
канал/роль как обычный параметр команды -- тот же способ резолвинга,
что и `#`/`@`-упоминание, поэтому не ограничены 25 пунктами и не
подвержены задержке/неполноте индексации).
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import Role, require
from database.repositories.guild_repository import GuildRepository

# key -> (атрибут GuildSettings, ожидаемый тип канала, подпись для сообщений)
CHANNEL_SETTINGS: dict[str, tuple[str, type[discord.abc.GuildChannel], str]] = {
    "moderation-logs": ("moderation_logs_channel_id", discord.TextChannel, "Логи модерации"),
    "deleted-messages": ("deleted_messages_channel_id", discord.TextChannel, "Удалённые сообщения"),
    "edited-messages": ("edited_messages_channel_id", discord.TextChannel, "Изменённые сообщения"),
    "member-logs": ("member_logs_channel_id", discord.TextChannel, "Вход/выход участников"),
    "error-logs": ("error_logs_channel_id", discord.TextChannel, "Ошибки бота"),
    "welcome": ("welcome_channel_id", discord.TextChannel, "Приветствие"),
    "status": ("status_channel_id", discord.TextChannel, "Статус бота"),
    "flight-log": ("flight_log_channel_id", discord.TextChannel, "Журнал рейсов"),
    "radio-text": ("radio_text_channel_id", discord.TextChannel, "Радио: \"сейчас играет\""),
    "radio-voice": ("radio_voice_channel_id", discord.VoiceChannel, "Радио: голосовой канал"),
    "temp-voice-creator": ("temporary_voice_creator_channel_id", discord.VoiceChannel, "Создание временного voice"),
    "temp-voice-category": ("temporary_voice_category_id", discord.CategoryChannel, "Категория временных voice"),
    "tickets-category": ("tickets_category_id", discord.CategoryChannel, "Категория тикетов"),
}

# key -> (атрибут GuildSettings, подпись для сообщений) -- роли модерации.
ROLE_SETTINGS: dict[str, tuple[str, str]] = {
    "admin": ("admin_role_id", "Администратор"),
    "moderator": ("moderator_role_id", "Модератор"),
    "support": ("support_role_id", "Поддержка"),
}

_CHANNEL_TYPE_EMOJI = {
    discord.ChannelType.text: "💬",
    discord.ChannelType.voice: "🔊",
    discord.ChannelType.category: "📁",
    discord.ChannelType.stage_voice: "🎙️",
}

_OVERFLOW_VALUE = "__overflow__"
_MAX_OPTIONS = 25


class ManualChannelSelect(discord.ui.Select):
    """Замена ``discord.ui.ChannelSelect`` -- варианты строятся вручную из
    ``guild.channels`` (см. обоснование в docstring модуля), поэтому не
    зависят от отдельного, иногда запаздывающего механизма Discord для
    авто-заполняемых компонентов выбора канала."""

    def __init__(self, *, guild: discord.Guild, channel_types: tuple[discord.ChannelType, ...], placeholder: str) -> None:
        channels = sorted(
            (c for c in guild.channels if c.type in channel_types),
            key=lambda c: (c.position, c.name.lower()),
        )
        truncated = len(channels) > _MAX_OPTIONS

        options: list[discord.SelectOption] = []
        for channel in channels[: _MAX_OPTIONS - 1 if truncated else _MAX_OPTIONS]:
            options.append(discord.SelectOption(
                label=channel.name[:100], value=str(channel.id), description=f"ID: {channel.id}",
                emoji=_CHANNEL_TYPE_EMOJI.get(channel.type),
            ))

        if truncated:
            options.append(discord.SelectOption(
                label=f"…ещё {len(channels) - (_MAX_OPTIONS - 1)} -- используйте /setup channel",
                value=_OVERFLOW_VALUE, description="Слишком много каналов для одного списка", emoji="⚠️",
            ))
        elif not options:
            options.append(discord.SelectOption(label="Подходящих каналов не найдено", value=_OVERFLOW_VALUE))

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, disabled=not channels)


async def _resolve_selected_channel(interaction: discord.Interaction, select: discord.ui.Select) -> discord.abc.GuildChannel | None:
    """Достаёт выбранный канал из значения :class:`ManualChannelSelect`.
    При переполнении списка или исчезновении канала между показом и
    нажатием сама отвечает на интеракцию и возвращает ``None``."""
    value = select.values[0]
    if value == _OVERFLOW_VALUE:
        await interaction.response.send_message(
            "⚠️ В списке слишком много подходящих каналов, чтобы показать все -- "
            "укажите нужный напрямую: `/setup channel`.", ephemeral=True,
        )
        return None

    channel = interaction.guild.get_channel(int(value)) if interaction.guild else None
    if channel is None:
        await interaction.response.send_message(
            "⚠️ Канал не найден (возможно, был удалён) -- откройте команду заново.", ephemeral=True,
        )
        return None
    return channel


class ManualRoleSelect(discord.ui.Select):
    """Замена ``discord.ui.RoleSelect`` -- варианты строятся вручную из
    ``guild.roles`` по тем же причинам, что и у :class:`ManualChannelSelect`
    (см. docstring модуля): нативный ``RoleSelect`` на практике показывал
    не все существующие на сервере роли."""

    def __init__(
        self, *, guild: discord.Guild, placeholder: str,
        min_values: int = 1, max_values: int = 1, default_role_ids: tuple[int, ...] = (),
    ) -> None:
        roles = sorted(
            (r for r in guild.roles if not r.is_default()),
            key=lambda r: r.position, reverse=True,  # как в настройках сервера Discord -- сверху самая старшая
        )
        truncated = len(roles) > _MAX_OPTIONS
        default_ids = set(default_role_ids)

        options: list[discord.SelectOption] = []
        for role in roles[: _MAX_OPTIONS - 1 if truncated else _MAX_OPTIONS]:
            options.append(discord.SelectOption(
                label=role.name[:100], value=str(role.id), description=f"ID: {role.id}",
                default=role.id in default_ids,
            ))

        if truncated:
            options.append(discord.SelectOption(
                label=f"…ещё {len(roles) - (_MAX_OPTIONS - 1)} -- используйте /setup role",
                value=_OVERFLOW_VALUE, description="Слишком много ролей для одного списка", emoji="⚠️",
            ))
        elif not options:
            options.append(discord.SelectOption(label="Ролей не найдено", value=_OVERFLOW_VALUE))

        super().__init__(
            placeholder=placeholder, min_values=min_values, max_values=min(max_values, len(options)),
            options=options, disabled=not roles,
        )


async def _resolve_selected_role(interaction: discord.Interaction, select: discord.ui.Select) -> discord.Role | None:
    """Аналог :func:`_resolve_selected_channel` для одиночного выбора роли."""
    value = select.values[0]
    if value == _OVERFLOW_VALUE:
        await interaction.response.send_message(
            "⚠️ В списке слишком много ролей, чтобы показать все -- укажите нужную напрямую: `/setup role`.",
            ephemeral=True,
        )
        return None

    role = interaction.guild.get_role(int(value)) if interaction.guild else None
    if role is None:
        await interaction.response.send_message(
            "⚠️ Роль не найдена (возможно, была удалена) -- откройте команду заново.", ephemeral=True,
        )
        return None
    return role


async def _resolve_selected_roles(interaction: discord.Interaction, select: discord.ui.Select) -> list[discord.Role]:
    """Аналог :func:`_resolve_selected_channel` для мультивыбора ролей
    (:class:`IgnoredRolesSetupView`). Пункт-переполнение просто
    отфильтровывается -- остальной выбор всё равно сохраняется, а не
    отбрасывается целиком."""
    guild = interaction.guild
    roles: list[discord.Role] = []
    for value in select.values:
        if value == _OVERFLOW_VALUE:
            continue
        role = guild.get_role(int(value)) if guild else None
        if role is not None:
            roles.append(role)
    return roles


class ChannelsSetupView(discord.ui.View):
    FIELDS = [
        ("moderation_logs_channel_id", "Логи модерации", discord.ChannelType.text),
        ("deleted_messages_channel_id", "Удалённые сообщения", discord.ChannelType.text),
        ("edited_messages_channel_id", "Изменённые сообщения", discord.ChannelType.text),
        ("member_logs_channel_id", "Вход/выход участников", discord.ChannelType.text),
        ("error_logs_channel_id", "Ошибки бота", discord.ChannelType.text),
    ]

    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        for attr, label, channel_type in self.FIELDS:
            select = ManualChannelSelect(guild=guild, channel_types=(channel_type,), placeholder=f"Канал: {label}")
            select.callback = self._make_callback(select, attr, label)
            self.add_item(select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: channel.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(f"✅ {label} -> {channel.mention}", ephemeral=True)

        return callback


class MiscChannelsSetupView(discord.ui.View):
    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx

        welcome_select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="Канал: Приветствие")
        welcome_select.callback = self._make_callback(welcome_select, "welcome_channel_id", "Приветствие")
        self.add_item(welcome_select)

        creator_select = ManualChannelSelect(
            guild=guild, channel_types=(discord.ChannelType.voice,), placeholder="Канал: Создать временный голосовой"
        )
        creator_select.callback = self._make_callback(
            creator_select, "temporary_voice_creator_channel_id", "Создание временного voice"
        )
        self.add_item(creator_select)

        category_select = ManualChannelSelect(
            guild=guild, channel_types=(discord.ChannelType.category,), placeholder="Категория: Временные voice"
        )
        category_select.callback = self._make_callback(category_select, "temporary_voice_category_id", "Категория временных voice")
        self.add_item(category_select)

        # Доп. быстрые создатели с фиксированным лимитом мест -- в
        # отличие от основного (без лимита), заходя сюда участник сразу
        # получает комнату на 2/4 места, без необходимости выставлять
        # лимит вручную командой /voice limit.
        for limit in (2, 4):
            preset_select = ManualChannelSelect(
                guild=guild, channel_types=(discord.ChannelType.voice,),
                placeholder=f"Быстрый создатель: комната на {limit}",
            )
            preset_select.callback = self._make_preset_callback(preset_select, limit)
            self.add_item(preset_select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: channel.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(f"✅ {label} -> {channel.mention}", ephemeral=True)

        return callback

    def _make_preset_callback(self, select: discord.ui.Select, limit: int):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                settings = await repo.get_or_create_settings(interaction.guild_id)
                presets = dict(settings.voice_creator_presets or {})
                presets[str(channel.id)] = limit
                await repo.update_settings(interaction.guild_id, voice_creator_presets=presets)
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(
                f"✅ Быстрый создатель на {limit} мест -> {channel.mention}", ephemeral=True
            )

        return callback


class StatusSetupView(discord.ui.View):
    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="Канал: Статус бота")
        select.callback = self._make_callback(select, "status_channel_id", "Канал статуса")
        self.add_item(select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: channel.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(
                f"✅ {label} -> {channel.mention}. Живой дашборд появится там в течение минуты.", ephemeral=True
            )

        return callback


class RadioSetupView(discord.ui.View):
    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx

        voice_select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.voice,), placeholder="Голосовой канал для радио")
        voice_select.callback = self._make_callback(voice_select, "radio_voice_channel_id", "Голосовой канал радио")
        self.add_item(voice_select)

        text_select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="Канал \"сейчас играет\"")
        text_select.callback = self._make_callback(text_select, "radio_text_channel_id", "Канал \"сейчас играет\"")
        self.add_item(text_select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: channel.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(f"✅ {label} -> {channel.mention}", ephemeral=True)

        return callback


class FlightsSetupView(discord.ui.View):
    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.text,), placeholder="Канал: журнал рейсов")
        select.callback = self._make_callback(select, "flight_log_channel_id", "Журнал рейсов")
        self.add_item(select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            channel = await _resolve_selected_channel(interaction, select)
            if channel is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: channel.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(f"✅ {label} -> {channel.mention}", ephemeral=True)

        return callback


class TicketsSetupView(discord.ui.View):
    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        select = ManualChannelSelect(guild=guild, channel_types=(discord.ChannelType.category,), placeholder="Категория для тикетов")
        select.callback = self._make_callback(select, "tickets_category_id", "Категория тикетов")
        self.add_item(select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            category = await _resolve_selected_channel(interaction, select)
            if category is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: category.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            await interaction.response.send_message(f"✅ {label} -> **{category.name}**", ephemeral=True)

        return callback


class IgnoredRolesSetupView(discord.ui.View):
    """Мультивыбор ролей, изменения которых НЕ нужно писать в лог
    модерации -- удобно для самовыдаваемых ролей (авиасимулятор, регион
    и т.п.), которых у активного сервера могут быть сотни в день."""

    def __init__(self, ctx, guild: discord.Guild, current_role_ids: list[int]) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        select = ManualRoleSelect(
            guild=guild, placeholder="Роли, которые НЕ логировать (можно несколько, можно пусто)",
            min_values=0, max_values=25, default_role_ids=tuple(current_role_ids),
        )
        select.callback = self._callback(select)
        self.add_item(select)

    def _callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            role_ids = [role.id for role in await _resolve_selected_roles(interaction, select)]
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, ignored_log_role_ids=role_ids)
            self.ctx.guild_config().invalidate(interaction.guild_id)
            if role_ids:
                mentions = ", ".join(f"<@&{rid}>" for rid in role_ids)
                message = f"✅ Больше не логируем выдачу/снятие: {mentions}"
            else:
                message = "✅ Список исключений очищен -- снова логируем выдачу всех ролей."
            await interaction.response.send_message(message, ephemeral=True)

        return callback


class RolesSetupView(discord.ui.View):
    FIELDS = [
        ("admin_role_id", "Администратор"),
        ("moderator_role_id", "Модератор"),
        ("support_role_id", "Поддержка"),
    ]

    def __init__(self, ctx, guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        for attr, label in self.FIELDS:
            select = ManualRoleSelect(guild=guild, placeholder=f"Роль: {label}")
            select.callback = self._make_callback(select, attr, label)
            self.add_item(select)

    def _make_callback(self, select: discord.ui.Select, attr: str, label: str):
        async def callback(interaction: discord.Interaction) -> None:
            role = await _resolve_selected_role(interaction, select)
            if role is None:
                return
            async with self.ctx.db.session() as session:
                repo = GuildRepository(session)
                await repo.get_or_create(interaction.guild_id, interaction.guild.name)
                await repo.update_settings(interaction.guild_id, **{attr: role.id})
            self.ctx.guild_config().invalidate(interaction.guild_id)
            role_map = await self.ctx.guild_config().role_map_for(interaction.guild_id)
            self.ctx.permissions.configure_guild(
                interaction.guild_id,
                {Role.from_name(k): v for k, v in role_map.items()},
            )
            await interaction.response.send_message(f"✅ Роль «{label}» -> {role.mention}", ephemeral=True)

        return callback


class ServerSetupCog(commands.Cog):
    setup_group = app_commands.Group(name="setup", description="Настройка сервера (только для администраторов)")

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @setup_group.command(name="channels", description="Настроить каналы логов")
    @require(Role.ADMIN)
    async def channels(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите каналы для каждого типа логов:", view=ChannelsSetupView(self.ctx, interaction.guild), ephemeral=True
        )

    @setup_group.command(name="voice", description="Настроить временные голосовые каналы")
    @require(Role.ADMIN)
    async def voice(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Настройте приветственный канал, обычный (без лимита) и быстрые (на 2/на 4 места) "
            "создатели временных голосовых комнат:",
            view=MiscChannelsSetupView(self.ctx, interaction.guild), ephemeral=True,
        )

    @setup_group.command(name="roles", description="Настроить роли модерации")
    @require(Role.ADMIN)
    async def roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите роли:", view=RolesSetupView(self.ctx, interaction.guild), ephemeral=True
        )

    @setup_group.command(name="status", description="Настроить канал живого статуса бота")
    @require(Role.ADMIN)
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите канал, в котором бот будет держать постоянно обновляемое сообщение со своим статусом:",
            view=StatusSetupView(self.ctx, interaction.guild), ephemeral=True,
        )

    @setup_group.command(name="radio", description="Настроить каналы для непрерывного радио")
    @require(Role.ADMIN)
    async def radio(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите голосовой канал, где будет играть радио, и текстовый канал для сообщения \"сейчас играет\":",
            view=RadioSetupView(self.ctx, interaction.guild), ephemeral=True,
        )

    @setup_group.command(name="flights", description="Настроить канал журнала рейсов")
    @require(Role.ADMIN)
    async def flights(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите канал, куда бот будет публиковать залогированные рейсы (/flight log):",
            view=FlightsSetupView(self.ctx, interaction.guild), ephemeral=True,
        )

    @setup_group.command(name="tickets", description="Настроить категорию для тикетов поддержки")
    @require(Role.ADMIN)
    async def tickets(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Выберите категорию, в которой будут создаваться каналы тикетов:",
            view=TicketsSetupView(self.ctx, interaction.guild), ephemeral=True,
        )

    @setup_group.command(name="profile-roles", description="Настроить роли Discord для авиационных профилей")
    @app_commands.describe(
        pilot="Роль для Pilot", atc="Роль для ATC", virtual_airline="Роль для Virtual Airline",
        flight_simmer="Роль для Flight Simmer", spotter="Роль для Spotter", enthusiast="Роль для Aviation Enthusiast",
    )
    @require(Role.ADMIN)
    async def profile_roles(
        self, interaction: discord.Interaction,
        pilot: discord.Role | None = None, atc: discord.Role | None = None,
        virtual_airline: discord.Role | None = None, flight_simmer: discord.Role | None = None,
        spotter: discord.Role | None = None, enthusiast: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        updates = {
            "pilot": pilot, "atc": atc, "virtual_airline": virtual_airline,
            "flight_simmer": flight_simmer, "spotter": spotter, "enthusiast": enthusiast,
        }
        provided = {key: role.id for key, role in updates.items() if role is not None}
        if not provided:
            await interaction.followup.send(
                "⚠️ Укажите хотя бы одну роль -- например `/setup profile-roles pilot:@Pilot`.", ephemeral=True
            )
            return

        async with self.ctx.db.session() as session:
            repo = GuildRepository(session)
            await repo.get_or_create(interaction.guild_id, interaction.guild.name)
            settings = await repo.get_or_create_settings(interaction.guild_id)
            role_map = dict(settings.profile_role_ids or {})
            role_map.update(provided)
            await repo.update_settings(interaction.guild_id, profile_role_ids=role_map)
        self.ctx.guild_config().invalidate(interaction.guild_id)

        summary = ", ".join(f"{key} -> {role.mention}" for key, role in updates.items() if role is not None)
        await interaction.followup.send(f"✅ Обновлено: {summary}", ephemeral=True)

    @setup_group.command(name="ignored-roles", description="Роли, выдачу/снятие которых НЕ логировать в модерации")
    @require(Role.ADMIN)
    async def ignored_roles(self, interaction: discord.Interaction) -> None:
        settings = await self.ctx.guild_config().get_settings(interaction.guild_id)
        current = list(settings.ignored_log_role_ids) if settings else []
        await interaction.response.send_message(
            "Выберите роли, изменения которых у участников не нужно писать в лог модерации "
            "(например, самовыдаваемые роли симулятора/региона):",
            view=IgnoredRolesSetupView(self.ctx, interaction.guild, current), ephemeral=True,
        )

    @setup_group.command(name="role", description="Указать роль модерации напрямую по упоминанию (для больших списков)")
    @app_commands.describe(key="Что настраивается", role="Роль (можно вставить @упоминание)")
    @app_commands.choices(key=[
        app_commands.Choice(name=label, value=k) for k, (_, label) in ROLE_SETTINGS.items()
    ])
    @require(Role.ADMIN)
    async def role_by_mention(self, interaction: discord.Interaction, key: app_commands.Choice[str], role: discord.Role) -> None:
        attr, label = ROLE_SETTINGS[key.value]
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            repo = GuildRepository(session)
            await repo.get_or_create(interaction.guild_id, interaction.guild.name)
            await repo.update_settings(interaction.guild_id, **{attr: role.id})
        self.ctx.guild_config().invalidate(interaction.guild_id)
        role_map = await self.ctx.guild_config().role_map_for(interaction.guild_id)
        self.ctx.permissions.configure_guild(
            interaction.guild_id, {Role.from_name(k): v for k, v in role_map.items()},
        )
        await interaction.followup.send(f"✅ Роль «{label}» -> {role.mention}", ephemeral=True)

    @setup_group.command(name="ignore-role", description="Добавить/убрать одну роль из списка исключений лога (для больших списков)")
    @app_commands.describe(role="Роль", ignored="True -- не логировать выдачу/снятие, False -- логировать снова")
    @require(Role.ADMIN)
    async def ignore_role(self, interaction: discord.Interaction, role: discord.Role, ignored: bool) -> None:
        await interaction.response.defer(ephemeral=True)
        settings = await self.ctx.guild_config().get_settings(interaction.guild_id)
        current = set(settings.ignored_log_role_ids) if settings else set()
        if ignored:
            current.add(role.id)
        else:
            current.discard(role.id)
        role_ids = list(current)

        async with self.ctx.db.session() as session:
            repo = GuildRepository(session)
            await repo.get_or_create(interaction.guild_id, interaction.guild.name)
            await repo.update_settings(interaction.guild_id, ignored_log_role_ids=role_ids)
        self.ctx.guild_config().invalidate(interaction.guild_id)

        verb = "больше не логируем" if ignored else "снова логируем"
        await interaction.followup.send(f"✅ {role.mention} -- {verb} выдачу/снятие.", ephemeral=True)

    @setup_group.command(name="channel", description="Указать канал/категорию напрямую по ID/упоминанию (для больших списков)")
    @app_commands.describe(key="Что настраивается", channel="Канал или категория (можно вставить #упоминание или ID)")
    @app_commands.choices(key=[
        app_commands.Choice(name=label, value=k) for k, (_, _, label) in CHANNEL_SETTINGS.items()
    ])
    @require(Role.ADMIN)
    async def channel_by_mention(
        self, interaction: discord.Interaction, key: app_commands.Choice[str],
        channel: discord.TextChannel | discord.VoiceChannel | discord.CategoryChannel | discord.StageChannel,
    ) -> None:
        attr, expected_type, label = CHANNEL_SETTINGS[key.value]
        if not isinstance(channel, expected_type):
            await interaction.response.send_message(
                f"⚠️ Для «{label}» нужен канал типа {expected_type.__name__}, а указан {type(channel).__name__}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            repo = GuildRepository(session)
            await repo.get_or_create(interaction.guild_id, interaction.guild.name)
            await repo.update_settings(interaction.guild_id, **{attr: channel.id})
        self.ctx.guild_config().invalidate(interaction.guild_id)
        await interaction.followup.send(f"✅ {label} -> {channel.mention}", ephemeral=True)

    @setup_group.command(name="show", description="Показать текущую конфигурацию сервера")
    @require(Role.ADMIN)
    async def show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        settings = await self.ctx.guild_config().get_settings(interaction.guild_id)
        if settings is None:
            await interaction.followup.send("Конфигурация ещё не задана -- используйте /setup channels, /setup voice, /setup roles.", ephemeral=True)
            return

        def fmt_channel(channel_id: int | None) -> str:
            return f"<#{channel_id}>" if channel_id else "—"

        def fmt_role(role_id: int | None) -> str:
            return f"<@&{role_id}>" if role_id else "—"

        embed = discord.Embed(title="⚙️ Конфигурация сервера", color=discord.Color.blurple())
        embed.add_field(name="Логи модерации", value=fmt_channel(settings.moderation_logs_channel_id))
        embed.add_field(name="Удалённые сообщения", value=fmt_channel(settings.deleted_messages_channel_id))
        embed.add_field(name="Изменённые сообщения", value=fmt_channel(settings.edited_messages_channel_id))
        embed.add_field(name="Вход/выход", value=fmt_channel(settings.member_logs_channel_id))
        embed.add_field(name="Ошибки бота", value=fmt_channel(settings.error_logs_channel_id))
        embed.add_field(name="Приветствие", value=fmt_channel(settings.welcome_channel_id))
        embed.add_field(name="Создание voice", value=fmt_channel(settings.temporary_voice_creator_channel_id))
        embed.add_field(name="Категория voice", value=fmt_channel(settings.temporary_voice_category_id))
        if settings.voice_creator_presets:
            presets = ", ".join(f"{fmt_channel(int(cid))} (на {limit})" for cid, limit in settings.voice_creator_presets.items())
        else:
            presets = "—"
        embed.add_field(name="Быстрые создатели voice", value=presets, inline=False)
        embed.add_field(name="Статус бота", value=fmt_channel(settings.status_channel_id))
        embed.add_field(name="Радио: голосовой канал", value=fmt_channel(settings.radio_voice_channel_id))
        embed.add_field(name="Радио: \"сейчас играет\"", value=fmt_channel(settings.radio_text_channel_id))
        embed.add_field(name="Журнал рейсов", value=fmt_channel(settings.flight_log_channel_id))

        category_name = "—"
        if settings.tickets_category_id and interaction.guild:
            category = interaction.guild.get_channel(settings.tickets_category_id)
            category_name = category.name if category else f"`{settings.tickets_category_id}`"
        embed.add_field(name="Категория тикетов", value=category_name)

        embed.add_field(name="Роль администратора", value=fmt_role(settings.admin_role_id))
        embed.add_field(name="Роль модератора", value=fmt_role(settings.moderator_role_id))
        embed.add_field(name="Роль Поддержки", value=fmt_role(settings.support_role_id))

        if settings.ignored_log_role_ids:
            ignored = ", ".join(f"<@&{rid}>" for rid in settings.ignored_log_role_ids)
        else:
            ignored = "—"
        embed.add_field(name="Роли без логирования", value=ignored[:1024], inline=False)

        if settings.profile_role_ids:
            profile_roles = ", ".join(f"{key}: <@&{rid}>" for key, rid in settings.profile_role_ids.items())
        else:
            profile_roles = "—"
        embed.add_field(name="Роли авиапрофилей", value=profile_roles[:1024], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


def build_server_setup_cog(ctx) -> ServerSetupCog:
    return ServerSetupCog(ctx)
