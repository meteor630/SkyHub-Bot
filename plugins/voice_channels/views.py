"""Панель управления временной голосовой комнатой в интерфейсе Discord
(ТЗ §16, §34).

View прикрепляется к сообщению, которое бот отправляет в собственный
текстовый чат комнаты сразу после её создания. Она живёт, пока работает
процесс бота (``timeout=None``) -- перезапуск сбрасывает старые панели,
но slash-команды ``/voice`` дают доступ к тем же самым действиям,
поэтому ничего не теряется.
"""
from __future__ import annotations

import discord

from services.voice_service import MODE_LOCKED, MODE_PUBLIC, VoiceService


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


class VoiceControlView(discord.ui.View):
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
        if channel is None:
            return
        await self.service.set_mode(channel, MODE_LOCKED)
        await interaction.response.send_message("🔒 Комната закрыта.", ephemeral=True)

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="voice:unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is None:
            return
        await self.service.set_mode(channel, MODE_PUBLIC)
        await interaction.response.send_message("🔓 Комната открыта.", ephemeral=True)

    @discord.ui.button(label="Пользователи", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="voice:users")
    async def users(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("Вы должны находиться в голосовом канале.", ephemeral=True)
            return
        names = "\n".join(f"• {m.display_name}" for m in member.voice.channel.members) or "—"
        await interaction.response.send_message(f"👥 **Участники комнаты:**\n{names}", ephemeral=True)

    @discord.ui.button(label="Название", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="voice:rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is None:
            return
        await interaction.response.send_modal(RenameModal(self.service, channel))

    @discord.ui.button(label="Передать владельца", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="voice:transfer")
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is None:
            return
        await interaction.response.send_message(
            "Выберите нового владельца:", view=TransferOwnerView(self.service, channel, interaction.user.id), ephemeral=True
        )

    @discord.ui.button(label="Удалить", emoji="🗑", style=discord.ButtonStyle.danger, custom_id="voice:delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = await self._channel_and_owner_check(interaction)
        if channel is None:
            return
        await interaction.response.send_message("🗑 Комната будет удалена...", ephemeral=True)
        await self.service.delete_room(channel)
