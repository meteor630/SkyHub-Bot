"""Бизнес-логика временных голосовых каналов (ТЗ §15-18, §27).

Вынесена отдельно от ``plugins/voice_channels/plugin.py``, чтобы
обвязка событий Discord / slash-команды оставались тонкими, а эту
логику можно было unit-тестировать без поднятия подключения к шлюзу.
"""
from __future__ import annotations

import logging

import discord

from database.database import Database
from database.repositories.voice_repository import VoiceRepository

logger = logging.getLogger("skyhub.voice")


class VoiceService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- создание --------------------------------------------------------

    async def create_room(
        self,
        *,
        member: discord.Member,
        category: discord.CategoryChannel | None,
        name_template: str = "{name}",
        user_limit: int = 0,
    ) -> discord.VoiceChannel:
        guild = member.guild
        name = name_template.format(name=member.display_name)[:100]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            # ВАЖНО: НЕ выдавать здесь manage_permissions/mute_members/
            # deafen_members. mute_members/deafen_members в Discord -- это
            # не действие "внутри канала", а изменение guild-wide голосового
            # состояния участника (Member.voice.mute/deaf) -- если владелец
            # комнаты заглушит кого-то этим правом, заглушка останется с
            # человеком и после того, как он выйдет из этой комнаты и
            # зайдёт в любую другую (реальная уязвимость, была найдена на
            # практике). manage_permissions открывает вкладку "Разрешения"
            # и позволяет менять доступ РОЛЕЙ и других участников -- тоже
            # больше, чем нужно рядовому владельцу временной комнаты.
            # move_members ("отключить кого-то от войса") такой утечки не
            # создаёт -- это разовое действие без сохраняющегося состояния.
            member: discord.PermissionOverwrite(
                connect=True, view_channel=True, manage_channels=True, move_members=True,
            ),
        }
        channel = await guild.create_voice_channel(
            name=name, category=category, overwrites=overwrites, user_limit=max(0, min(user_limit, 99)),
        )

        async with self.db.session() as session:
            repo = VoiceRepository(session)
            await repo.create(guild_id=guild.id, channel_id=channel.id, owner_id=member.id, name=name, member_limit=user_limit)

        logger.info("Создан временный голосовой канал '%s' для %s", name, member, extra={"plugin": "voice_channels"})
        return channel

    async def delete_room(self, channel: discord.VoiceChannel) -> None:
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            await repo.delete(channel.id)
        try:
            await channel.delete(reason="Временный голосовой канал опустел")
        except discord.NotFound:
            pass

    # -- владение и режимы -------------------------------------------------

    async def is_owner(self, channel_id: int, user_id: int) -> bool:
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            record = await repo.get_by_channel_id(channel_id)
            return record is not None and record.owner_id == user_id

    async def get_owner_id(self, channel_id: int) -> int | None:
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            record = await repo.get_by_channel_id(channel_id)
            return record.owner_id if record else None

    async def get_room(self, channel_id: int):
        """Запись о комнате (закрыта/скрыта, лимит, владелец) -- для ``/voice info``."""
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            return await repo.get_by_channel_id(channel_id)

    async def get_rooms_for_owner(self, guild_id: int, owner_id: int):
        """Активные комнаты участника -- для центральной панели управления,
        которая работает не из чата конкретной комнаты (``/setup voice-panel``)."""
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            return await repo.all_for_owner(guild_id, owner_id)

    async def close_room(self, channel: discord.VoiceChannel) -> None:
        """Закрывает комнату для новых участников, но НЕ выгоняет и не
        мешает вернуться тем, кто уже внутри -- каждому из них выдаётся
        персональное разрешение на вход поверх общего запрета для
        @everyone. Видимость комнаты (`is_hidden`) не трогается."""
        default_role = channel.guild.default_role
        overwrite = channel.overwrites_for(default_role)
        overwrite.connect = False
        await channel.set_permissions(default_role, overwrite=overwrite)

        for existing_member in channel.members:
            member_overwrite = channel.overwrites_for(existing_member)
            member_overwrite.connect = True
            await channel.set_permissions(existing_member, overwrite=member_overwrite)

        async with self.db.session() as session:
            await VoiceRepository(session).set_locked(channel.id, True)

    async def open_room(self, channel: discord.VoiceChannel) -> None:
        """Снова разрешает вход всем -- персональные разрешения, выданные
        при закрытии (см. :meth:`close_room`), не отзываются: они просто
        становятся избыточными, раз @everyone и так может зайти."""
        default_role = channel.guild.default_role
        overwrite = channel.overwrites_for(default_role)
        overwrite.connect = True
        await channel.set_permissions(default_role, overwrite=overwrite)

        async with self.db.session() as session:
            await VoiceRepository(session).set_locked(channel.id, False)

    async def hide_room(self, channel: discord.VoiceChannel) -> None:
        """Прячет комнату из списка каналов. Независимо от того, закрыта
        ли она для входа -- это отдельный переключатель."""
        default_role = channel.guild.default_role
        overwrite = channel.overwrites_for(default_role)
        overwrite.view_channel = False
        await channel.set_permissions(default_role, overwrite=overwrite)

        async with self.db.session() as session:
            await VoiceRepository(session).set_hidden(channel.id, True)

    async def show_room(self, channel: discord.VoiceChannel) -> None:
        default_role = channel.guild.default_role
        overwrite = channel.overwrites_for(default_role)
        overwrite.view_channel = True
        await channel.set_permissions(default_role, overwrite=overwrite)

        async with self.db.session() as session:
            await VoiceRepository(session).set_hidden(channel.id, False)

    async def rename(self, channel: discord.VoiceChannel, name: str) -> None:
        await channel.edit(name=name[:100])
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            await repo.rename(channel.id, name[:100])

    async def set_limit(self, channel: discord.VoiceChannel, limit: int) -> None:
        await channel.edit(user_limit=max(0, min(limit, 99)))
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            await repo.set_limit(channel.id, limit)

    async def allow(self, channel: discord.VoiceChannel, member: discord.Member) -> None:
        await channel.set_permissions(member, connect=True, view_channel=True)

    async def deny(self, channel: discord.VoiceChannel, member: discord.Member) -> None:
        await channel.set_permissions(member, connect=False, view_channel=False)

    async def kick(self, channel: discord.VoiceChannel, member: discord.Member) -> None:
        if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
            await member.move_to(None, reason="Владелец исключил участника из временного голосового канала")

    async def transfer_owner(self, channel: discord.VoiceChannel, new_owner: discord.Member, old_owner: discord.Member) -> None:
        await channel.set_permissions(old_owner, overwrite=None)
        # См. комментарий в create_room -- намеренно без manage_permissions/
        # mute_members/deafen_members.
        await channel.set_permissions(
            new_owner, connect=True, view_channel=True, manage_channels=True, move_members=True,
        )
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            await repo.transfer_owner(channel.id, new_owner.id)

    # -- восстановление после перезапуска (ТЗ §27) ---------------------------

    async def reconcile_guild(self, guild: discord.Guild) -> tuple[int, int]:
        """Удаляет из БД записи о временных каналах, которых больше нет в
        Discord, и удаляет в Discord опустевшие временные каналы, которые
        бот не успел убрать до перезапуска. Возвращает (удалено, проверено)."""
        async with self.db.session() as session:
            repo = VoiceRepository(session)
            records = await repo.all_for_guild(guild.id)

        removed = 0
        for record in records:
            channel = guild.get_channel(record.channel_id)
            if channel is None:
                async with self.db.session() as session:
                    await VoiceRepository(session).delete(record.channel_id)
                removed += 1
                continue
            if isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0:
                await self.delete_room(channel)
                removed += 1

        return removed, len(records)
