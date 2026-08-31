"""Панели управления временной голосовой комнатой (ТЗ §16, §34).

Два способа добраться до одних и тех же действий:

* :class:`VoiceControlView` -- в текстовом чате самой комнаты. Владелец
  должен физически находиться в своём голосовом канале (определяем его
  через ``member.voice.channel``). Прикрепляется к сообщению, которое
  бот отправляет туда сразу после создания комнаты; живёт, пока жив
  процесс бота (``timeout=None``) -- после перезапуска старые панели
  переставали бы отвечать, но slash-команды ``/voice`` дают доступ к
  тем же самым действиям, так что ничего не теряется.
* :class:`CentralVoicePanelView` -- единственное постоянное сообщение в
  канале, настроенном через ``/setup voice-panel`` (см.
  ``plugins/voice_channels/plugin.py``). Работает для владельца ЛЮБОЙ
  его активной комнаты, даже если он сейчас не сидит в голосовом канале
  вообще -- комната находится через БД (``VoiceService.get_rooms_for_owner``),
  а не через физическое присутствие. Регистрируется как персистентный
  View через ``bot.add_view()`` при загрузке плагина -- custom_id не
  завязаны на конкретную комнату (её всегда находим заново), поэтому
  один и тот же зарегистрированный экземпляр обслуживает вообще всех
  владельцев на всех серверах сразу, как и панель тикетов.

Собственно действия (закрыть/открыть/скрыть/показать/переименовать/...)
вынесены в отдельные функции ``_do_*``, чтобы не дублировать логику
между двумя панелями -- разница между ними только в том, "как найти
голосовой канал, которым управляем".
"""
from __future__ import annotations

import discord

from services.voice_service import VoiceService


class RenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(label="Новое название", max_length=100)

    def __init__(self, service: VoiceService, channel: discord.VoiceChannel) -> None:
        super().__init__()
        self._service = service
        self._channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._service.rename(self._channel, str(self.new_name))
        await interaction.response.send_message(f"✏️ Название изменено: **{self.new_name}**", ephemeral=True)


class TransferOwnerSelect(discord.ui.Select):
    def __init__(self, service: VoiceService, channel: discord.VoiceChannel, current_owner_id: int) -> None:
        options = [
            discord.SelectOption(label=member.display_name, value=str(member.id))
            for member in channel.members
            if member.id != current_owner_id
        ][:25]
        super().__init__(placeholder="Выберите нового владельца", options=options or [discord.SelectOption(label="Нет доступных участников", value="0")])
        self._service = service
        self._channel = channel

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "0":
            await interaction.response.send_message("В комнате нет других участников.", ephemeral=True)
            return
        new_owner = interaction.guild.get_member(int(self.values[0]))
        if new_owner is None:
            await interaction.response.send_message("Участник не найден.", ephemeral=True)
            return
        await self._service.transfer_owner(self._channel, new_owner, interaction.user)
        await interaction.response.send_message(f"👤 Владелец комнаты теперь {new_owner.mention}.", ephemeral=False)


class TransferOwnerView(discord.ui.View):
    def __init__(self, service: VoiceService, channel: discord.VoiceChannel, current_owner_id: int) -> None:
        super().__init__(timeout=60)
        self.add_item(TransferOwnerSelect(service, channel, current_owner_id))


# -- общие действия, используются обеими панелями ---------------------------

async def _do_close(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await service.close_room(channel)
    await interaction.response.send_message(
        f"🔒 Комната закрыта для входа -- те, кто уже внутри, могут заходить обратно свободно.{note}", ephemeral=True
    )


async def _do_open(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await service.open_room(channel)
    await interaction.response.send_message(f"🔓 Комната открыта для входа всем.{note}", ephemeral=True)


async def _do_hide(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await service.hide_room(channel)
    await interaction.response.send_message(f"🙈 Комната скрыта из списка каналов.{note}", ephemeral=True)


async def _do_show(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await service.show_room(channel)
    await interaction.response.send_message(f"👁 Комната видна в списке каналов.{note}", ephemeral=True)


async def _do_users(interaction: discord.Interaction, channel: discord.VoiceChannel, note: str) -> None:
    names = "\n".join(f"• {m.display_name}" for m in channel.members) or "—"
    await interaction.response.send_message(f"👥 **Участники комнаты:**\n{names}{note}", ephemeral=True)


async def _do_rename(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await interaction.response.send_modal(RenameModal(service, channel))


async def _do_transfer(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await interaction.response.send_message(
        f"Выберите нового владельца:{note}", view=TransferOwnerView(service, channel, interaction.user.id), ephemeral=True
    )


async def _do_delete(interaction: discord.Interaction, service: VoiceService, channel: discord.VoiceChannel, note: str) -> None:
    await interaction.response.send_message(f"🗑 Комната будет удалена...{note}", ephemeral=True)
    await service.delete_room(channel)


class VoiceControlView(discord.ui.View):
    """Панель в чате самой комнаты -- владелец должен физически в ней находиться."""

    def __init__(self, service: VoiceService) -> None:
        super().__init__(timeout=None)
        self.service = service

    async def _channel_and_owner_check(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("Вы должны находиться в голосовом канале.", ephemeral=True)
            return None
        channel = member.voice.channel
        if not await self.service.is_owner(channel.id, member.id):
            await interaction.response.send_message("Только владелец комнаты может это сделать.", ephemeral=True)
            return None
        return channel

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="voice:lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_close(interaction, self.service, channel, "")

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="voice:unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_open(interaction, self.service, channel, "")

    @discord.ui.button(label="Скрыть", emoji="🙈", style=discord.ButtonStyle.secondary, custom_id="voice:hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_hide(interaction, self.service, channel, "")

    @discord.ui.button(label="Показать", emoji="👁", style=discord.ButtonStyle.secondary, custom_id="voice:show")
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_show(interaction, self.service, channel, "")

    @discord.ui.button(label="Пользователи", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="voice:users")
    async def users(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("Вы должны находиться в голосовом канале.", ephemeral=True)
            return
        await _do_users(interaction, member.voice.channel, "")

    @discord.ui.button(label="Название", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="voice:rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_rename(interaction, self.service, channel, "")

    @discord.ui.button(label="Передать владельца", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="voice:transfer")
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_transfer(interaction, self.service, channel, "")

    @discord.ui.button(label="Удалить", emoji="🗑", style=discord.ButtonStyle.danger, custom_id="voice:delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is not None:
            await _do_delete(interaction, self.service, channel, "")


class CentralVoicePanelView(discord.ui.View):
    """Единственная постоянная панель в канале из ``/setup voice-panel``.
    Владелец не обязан физически находиться в своей комнате -- она
    находится через БД по тому, кто нажал кнопку."""

    def __init__(self, service: VoiceService) -> None:
        super().__init__(timeout=None)
        self.service = service

    async def _resolve(self, interaction: discord.Interaction) -> tuple[discord.VoiceChannel, str] | tuple[None, None]:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Эта панель работает только на сервере.", ephemeral=True)
            return None, None

        rooms = await self.service.get_rooms_for_owner(guild.id, interaction.user.id)
        if not rooms:
            await interaction.response.send_message("⚠️ У вас сейчас нет активной голосовой комнаты.", ephemeral=True)
            return None, None

        record = rooms[0]  # отсортировано по id, новые первыми
        channel = guild.get_channel(record.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message("⚠️ Комната не найдена (возможно, уже удалена).", ephemeral=True)
            return None, None

        note = ""
        if len(rooms) > 1:
            note = f"\n-- у вас несколько активных комнат, применено к последней созданной: **{channel.name}**"
        return channel, note

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="voice_panel:lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_close(interaction, self.service, channel, note)

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="voice_panel:unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_open(interaction, self.service, channel, note)

    @discord.ui.button(label="Скрыть", emoji="🙈", style=discord.ButtonStyle.secondary, custom_id="voice_panel:hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_hide(interaction, self.service, channel, note)

    @discord.ui.button(label="Показать", emoji="👁", style=discord.ButtonStyle.secondary, custom_id="voice_panel:show")
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_show(interaction, self.service, channel, note)

    @discord.ui.button(label="Пользователи", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="voice_panel:users")
    async def users(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_users(interaction, channel, note)

    @discord.ui.button(label="Название", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="voice_panel:rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_rename(interaction, self.service, channel, note)

    @discord.ui.button(label="Передать владельца", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="voice_panel:transfer")
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_transfer(interaction, self.service, channel, note)

    @discord.ui.button(label="Удалить", emoji="🗑", style=discord.ButtonStyle.danger, custom_id="voice_panel:delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel, note = await self._resolve(interaction)
        if channel is not None:
            await _do_delete(interaction, self.service, channel, note)
