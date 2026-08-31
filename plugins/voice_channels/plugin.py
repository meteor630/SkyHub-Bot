"""Плагин ``voice_channels``: временные приватные голосовые комнаты (ТЗ §15-18, §27)."""
from __future__ import annotations

import time

import discord
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from core.events import VoiceControlPanelChannelChanged, VoiceCreated, VoiceDeleted
from database.repositories.dashboard_repository import DashboardRepository
from plugins.voice_channels.commands import build_voice_cog
from plugins.voice_channels.views import CentralVoicePanelView, VoiceControlView
from services.voice_service import VoiceService

# Защита от спама созданием комнат -- быстрый выход-заход в канал-создатель
# иначе плодил бы новую комнату на каждый вход (ТЗ §37, найдено при аудите
# безопасности).
ROOM_CREATE_COOLDOWN_SECONDS = 15.0

PANEL_DASHBOARD_KIND = "voice_control_panel"


class VoiceEventsCog(commands.Cog):
    def __init__(self, ctx, service: VoiceService) -> None:
        self.ctx = ctx
        self.service = service
        self._last_created_at: dict[int, float] = {}  # user_id -> monotonic-время последнего создания

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        try:
            if after.channel is not None:
                user_limit = await self._creator_channel_limit(member.guild.id, after.channel.id)
                if user_limit is not None and self._check_and_bump_cooldown(member.id):
                    await self._create_room_for(member, user_limit=user_limit)

            if before.channel is not None:
                await self._delete_if_empty(before.channel)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="on_voice_state_update", guild_id=member.guild.id, user_id=member.id)

    def _check_and_bump_cooldown(self, user_id: int) -> bool:
        now = time.monotonic()
        last = self._last_created_at.get(user_id)
        if last is not None and (now - last) < ROOM_CREATE_COOLDOWN_SECONDS:
            return False
        self._last_created_at[user_id] = now
        return True

    async def _creator_channel_limit(self, guild_id: int, channel_id: int) -> int | None:
        """``None``, если этот канал -- не канал-создатель. Иначе -- лимит
        участников будущей комнаты (``0`` = без лимита, обычный
        ``/setup voice`` создатель; иначе -- один из доп. пресетов, напр.
        быстрые "на 2"/"на 4")."""
        creator_id = await self.ctx.guild_config().resolve_channel_id(guild_id, "temporary_voice_creator")
        if creator_id and channel_id == creator_id:
            return 0
        presets = await self.ctx.guild_config().voice_creator_presets(guild_id)
        return presets.get(channel_id)

    async def _capabilities_embed(self, guild_id: int, channel: discord.VoiceChannel, user_limit: int) -> discord.Embed:
        limit_note = (
            f"Лимит участников уже выставлен на **{user_limit}** (быстрый создатель) -- "
            "изменить его можно `/voice limit` или в настройках канала."
            if user_limit else
            "Лимита участников нет -- задать его можно `/voice limit <число>` или в настройках канала."
        )
        embed = discord.Embed(
            title=f"✈️ {channel.name}",
            description="Это ваша личная голосовая комната. Вот что вы можете с ней сделать:",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Кнопками ниже или командой /voice",
            value=(
                "🔒/🔓 закрыть/открыть для входа -- `/voice lock` / `/voice unlock`\n"
                "🙈/👁 скрыть/показать из списка каналов -- `/voice hide` / `/voice show`\n"
                "✏️ переименовать -- `/voice name <название>`\n"
                "👥 список участников -- кнопка «Пользователи»\n"
                "👤 передать владение -- `/voice transfer <участник>`\n"
                "🗑 удалить комнату немедленно -- кнопка «Удалить»"
            ),
            inline=False,
        )
        embed.add_field(
            name="Только командой /voice",
            value=(
                "`/voice limit <число>` -- лимит участников (0 = без лимита)\n"
                "`/voice kick <участник>` -- выгнать из комнаты один раз\n"
                "`/voice ban <участник>` -- выгнать и не пускать обратно\n"
                "`/voice allow <участник>` / `/voice deny <участник>` -- разрешить/запретить вход конкретному человеку"
            ),
            inline=False,
        )
        panel_channel_id = await self.ctx.guild_config().resolve_channel_id(guild_id, "voice_control_panel")
        panel_note = f" -- то же самое доступно и из <#{panel_channel_id}>, даже когда вы не в голосовом канале." if panel_channel_id else ""
        embed.add_field(
            name="Прямо в настройках канала Discord",
            value=(
                "⚙️ рядом с названием канала -> **Изменить канал** -> можно менять название и лимит "
                "участников, а также отключать людей от разговора -- без команд бота. Вкладку "
                "«Разрешения» и заглушение микрофона мы туда намеренно не выдаём: заглушение в Discord "
                "привязано к участнику на весь сервер и осталось бы с ним даже после выхода из этой "
                f"комнаты -- для похожей задачи используйте `/voice ban`, она безопасна.{panel_note}"
            ),
            inline=False,
        )
        embed.add_field(name="Лимит участников", value=limit_note, inline=False)
        embed.set_footer(text="Управлять комнатой может только её текущий владелец")
        return embed

    async def _create_room_for(self, member: discord.Member, *, user_limit: int = 0) -> None:
        category_id = await self.ctx.guild_config().resolve_category_id(member.guild.id)
        category = member.guild.get_channel(category_id) if category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None

        channel = await self.service.create_room(member=member, category=category, user_limit=user_limit)
        await member.move_to(channel, reason="Создана временная голосовая комната")
        self.ctx.emit(VoiceCreated(guild_id=member.guild.id, channel_id=channel.id, owner_id=member.id))

        view = VoiceControlView(self.service)
        embed = await self._capabilities_embed(member.guild.id, channel, user_limit)
        try:
            # silent=True -- пинг остаётся кликабельным упоминанием, но не
            # шлёт push-уведомление тому, кто и так только что сюда зашёл.
            await channel.send(f"{member.mention}, ваша комната готова!", embed=embed, view=view, silent=True)
        except discord.HTTPException as exc:
            await self.ctx.report_error(exc, event="post_voice_control_panel", guild_id=member.guild.id)

    async def _delete_if_empty(self, channel: discord.VoiceChannel) -> None:
        """Удаляет опустевшую временную комнату немедленно, без паузы."""
        owner_id = await self.service.get_owner_id(channel.id)
        if owner_id is None:
            return  # это не отслеживаемый временный канал
        if len(channel.members) > 0:
            return
        await self.service.delete_room(channel)
        self.ctx.emit(VoiceDeleted(guild_id=channel.guild.id, channel_id=channel.id, owner_id=owner_id))


class VoiceChannelsPlugin(BasePlugin):
    meta = PluginMeta(
        name="voice_channels", version="1.5.0",
        description="Временные приватные голосовые комнаты с управлением владельцем (кнопки + /voice + центральная панель)",
        dependencies=(),
    )

    async def setup(self) -> None:
        self.service = VoiceService(self.ctx.db)
        await self.ctx.add_cog(build_voice_cog(self.ctx, self.service))
        await self.ctx.add_cog(VoiceEventsCog(self.ctx, self.service))
        # Персистентная центральная панель -- custom_id не завязаны на
        # конкретную комнату (см. docstring views.py), поэтому один
        # зарегистрированный экземпляр обслуживает всех владельцев сразу.
        self.ctx.bot.add_view(CentralVoicePanelView(self.service))
        self.ctx.subscribe(VoiceControlPanelChannelChanged, self._on_panel_channel_changed)
        self.log.info("voice_channels готов к работе")

    async def start(self) -> None:
        if not self.ctx.bot.guilds:
            return  # см. tests/test_plugin_manager_smoke.py -- на нуле серверов БД может быть недоступна

        for guild in self.ctx.bot.guilds:
            try:
                removed, checked = await self.service.reconcile_guild(guild)
                if checked:
                    self.log.info("Проверка временных voice-каналов на сервере %s: удалено %d/%d", guild.name, removed, checked)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="reconcile_guild", guild_id=guild.id)

            try:
                await self._ensure_panel(guild)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="voice_panel_ensure", guild_id=guild.id)

    async def _on_panel_channel_changed(self, event: VoiceControlPanelChannelChanged) -> None:
        if event.guild_id is None:
            return
        guild = self.ctx.bot.get_guild(event.guild_id)
        if guild is not None:
            await self._ensure_panel(guild)

    async def _ensure_panel(self, guild: discord.Guild) -> None:
        """Гарантирует ровно одно постоянное сообщение с центральной
        панелью в настроенном канале -- как status_dashboard/radio, не
        плодит новые сообщения, если старое ещё живо, и само пересоздаёт
        его, если кто-то удалил вручную."""
        channel_id = await self.ctx.guild_config().resolve_channel_id(guild.id, "voice_control_panel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return

        async with self.ctx.db.session() as session:
            existing = await DashboardRepository(session).get(guild.id, PANEL_DASHBOARD_KIND)

        embed = discord.Embed(
            title="🎛 Управление вашей голосовой комнатой",
            description=(
                "Кнопки ниже применяются к вашей текущей активной временной голосовой комнате, "
                "даже если вы сейчас не в голосовом канале. Если у вас нет активной комнаты -- "
                "сначала создайте её, зайдя в канал-создатель."
            ),
            color=discord.Color.blue(),
        )

        message = None
        if existing is not None and existing.channel_id == channel_id:
            try:
                message = await channel.fetch_message(existing.message_id)
                await message.edit(embed=embed, view=CentralVoicePanelView(self.service))
            except discord.NotFound:
                message = None
            except discord.HTTPException as exc:
                await self.ctx.report_error(exc, event="voice_panel_edit", guild_id=guild.id)
                return

        if message is None:
            try:
                message = await channel.send(embed=embed, view=CentralVoicePanelView(self.service))
            except discord.HTTPException as exc:
                await self.ctx.report_error(exc, event="voice_panel_create", guild_id=guild.id)
                return
            async with self.ctx.db.session() as session:
                await DashboardRepository(session).upsert(
                    guild_id=guild.id, kind=PANEL_DASHBOARD_KIND, channel_id=channel_id, message_id=message.id
                )


PLUGIN_CLASS = VoiceChannelsPlugin
