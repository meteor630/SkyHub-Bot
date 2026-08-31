"""Группа команд ``/voice`` для управления личной временной голосовой комнатой
(ТЗ §16).

Как и в ``message_builder``, каждая команда сначала подтверждает
интеракцию через ``defer()`` -- прежде чем делать что-либо ещё,
включая проверку владения комнатой (она стучится в базу данных). У
Discord всего 3 секунды на первый ответ; всё остальное идёт через
``followup``, у которого запас на порядок больше.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.exceptions import VoiceChannelError
from services.voice_service import VoiceService


class VoiceCog(commands.Cog):
    voice_group = app_commands.Group(name="voice", description="Управление вашей временной голосовой комнатой")

    def __init__(self, ctx, service: VoiceService) -> None:
        self.ctx = ctx
        self.service = service

    async def _owned_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            raise VoiceChannelError("Вы должны находиться в своей голосовой комнате.")
        channel = member.voice.channel
        if not await self.service.is_owner(channel.id, member.id):
            raise VoiceChannelError("Вы не являетесь владельцем этой комнаты.")
        return channel

    async def _owned_channel_or_error(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        """Подтверждает интеракцию и возвращает комнату вызывающего, либо
        сама отправляет сообщение об ошибке и возвращает None."""
        await interaction.response.defer(ephemeral=True)
        try:
            return await self._owned_channel(interaction)
        except VoiceChannelError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
            return None

    @voice_group.command(name="info", description="Показать текущие настройки вашей комнаты")
    async def info(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return

        record = await self.service.get_room(channel.id)
        locked_label = "🔒 Закрыта для входа" if record and record.is_locked else "🔓 Открыта для входа"
        hidden_label = "🙈 Скрыта из списка" if record and record.is_hidden else "👁 Видна в списке"
        limit_label = str(record.member_limit) if record and record.member_limit else "без лимита"

        allowed, denied = [], []
        for target, overwrite in channel.overwrites.items():
            if target in (channel.guild.default_role, interaction.user):
                continue
            if overwrite.connect is True:
                allowed.append(target.mention if hasattr(target, "mention") else str(target))
            elif overwrite.connect is False:
                denied.append(target.mention if hasattr(target, "mention") else str(target))

        embed = discord.Embed(title=f"ℹ️ {channel.name}", color=discord.Color.blue())
        embed.add_field(name="Вход", value=locked_label, inline=True)
        embed.add_field(name="Видимость", value=hidden_label, inline=True)
        embed.add_field(name="Лимит участников", value=limit_label, inline=True)
        embed.add_field(name="Сейчас в комнате", value=str(len(channel.members)), inline=True)
        embed.add_field(
            name="Индивидуально разрешён вход", value=", ".join(allowed) or "—", inline=False,
        )
        embed.set_footer(text="Сюда попадают и те, кому разрешили при закрытии комнаты, и /voice allow")
        embed.add_field(name="Запрещён вход (/voice deny/ban)", value=", ".join(denied) or "—", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @voice_group.command(name="name", description="Переименовать комнату")
    async def name(self, interaction: discord.Interaction, name: str) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.rename(channel, name)
        await interaction.followup.send(f"✏️ Название изменено: **{name}**", ephemeral=True)

    @voice_group.command(name="limit", description="Установить лимит участников (0 = без лимита)")
    async def limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.set_limit(channel, limit)
        await interaction.followup.send(f"👥 Лимит участников: **{limit or '∞'}**", ephemeral=True)

    @voice_group.command(name="lock", description="Закрыть комнату для входа (кто уже внутри -- может заходить свободно)")
    async def lock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.close_room(channel)
        await interaction.followup.send(
            "🔒 Комната закрыта для входа -- те, кто уже внутри, могут заходить обратно свободно.", ephemeral=True
        )

    @voice_group.command(name="unlock", description="Снова открыть комнату для входа всем")
    async def unlock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.open_room(channel)
        await interaction.followup.send("🔓 Комната открыта для входа всем.", ephemeral=True)

    @voice_group.command(name="hide", description="Скрыть комнату из списка каналов")
    async def hide(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.hide_room(channel)
        await interaction.followup.send("🙈 Комната скрыта из списка каналов.", ephemeral=True)

    @voice_group.command(name="show", description="Сделать комнату видимой в списке каналов")
    async def show(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.show_room(channel)
        await interaction.followup.send("👁 Комната видна в списке каналов.", ephemeral=True)

    @voice_group.command(name="kick", description="Выгнать пользователя из комнаты")
    async def kick(self, interaction: discord.Interaction, member: discord.Member) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.kick(channel, member)
        await interaction.followup.send(f"👢 {member.display_name} исключен(а) из комнаты.", ephemeral=True)

    @voice_group.command(name="ban", description="Заблокировать пользователю доступ к комнате")
    async def ban(self, interaction: discord.Interaction, member: discord.Member) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.deny(channel, member)
        await self.service.kick(channel, member)
        await interaction.followup.send(f"🚫 {member.display_name} заблокирован(а) в этой комнате.", ephemeral=True)

    @voice_group.command(name="allow", description="Разрешить пользователю заходить в комнату")
    async def allow(self, interaction: discord.Interaction, member: discord.Member) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.allow(channel, member)
        await interaction.followup.send(f"✅ {member.display_name} теперь может заходить.", ephemeral=True)

    @voice_group.command(name="deny", description="Запретить пользователю заходить в комнату")
    async def deny(self, interaction: discord.Interaction, member: discord.Member) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        await self.service.deny(channel, member)
        await interaction.followup.send(f"⛔ {member.display_name} больше не может заходить.", ephemeral=True)

    @voice_group.command(name="transfer", description="Передать владение комнатой")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member) -> None:
        channel = await self._owned_channel_or_error(interaction)
        if channel is None:
            return
        if member.voice is None or member.voice.channel is None or member.voice.channel.id != channel.id:
            await interaction.followup.send("⚠️ Новый владелец должен находиться в комнате.", ephemeral=True)
            return
        await self.service.transfer_owner(channel, member, interaction.user)
        # Объявляем смену владельца прямо в чате комнаты (видно всем, кто в
        # ней есть), а вызывающему -- отдельное короткое подтверждение,
        # чтобы не сталкивать эфемерный defer с публичным followup-сообщением.
        await channel.send(f"👤 Владелец комнаты теперь {member.mention}.")
        await interaction.followup.send("✅ Владение передано.", ephemeral=True)


def build_voice_cog(ctx, service: VoiceService) -> VoiceCog:
    return VoiceCog(ctx, service)
