"""Группа команд ``/mod`` (ТЗ §11, §33-35)."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.events import ModerationAction
from core.permissions import Role, require
from services.moderation_service import ModerationService


class ModerationCog(commands.Cog):
    mod_group = app_commands.Group(name="mod", description="Команды модерации")

    def __init__(self, ctx, service: ModerationService) -> None:
        self.ctx = ctx
        self.service = service

    def _emit(self, guild_id: int, action: str, moderator: discord.Member, target_id: int, reason: str | None, **extra) -> None:
        self.ctx.emit(
            ModerationAction(
                guild_id=guild_id, action=action, moderator_id=moderator.id, target_id=target_id,
                reason=reason, extra=extra,
            )
        )

    async def _check_hierarchy(self, interaction: discord.Interaction, member: discord.Member) -> bool:
        """Запрещает модератору применять наказания к себе или к
        участнику с равным/более высоким уровнем доступа -- иначе более
        младший модератор мог бы забанить/замьютить старшего или другого
        модератора (найдено при аудите безопасности). Сам владелец
        сервера всё равно защищён от бана/кика на уровне API Discord --
        это дополнительный барьер именно для действий друг на друга."""
        if member.id == interaction.user.id:
            await interaction.followup.send("⚠️ Нельзя применить это к самому себе.", ephemeral=True)
            return False
        actor_role = self.ctx.permissions.resolve(interaction.user)
        target_role = self.ctx.permissions.resolve(member)
        if target_role >= actor_role:
            await interaction.followup.send(
                "⚠️ Недостаточно прав -- нельзя применить это к участнику с таким же или более высоким уровнем доступа.",
                ephemeral=True,
            )
            return False
        return True

    @mod_group.command(name="ban", description="Забанить участника")
    @app_commands.describe(member="Кого забанить", reason="Причина", delete_days="Удалить сообщения за N дней (0-7)")
    @require(Role.MODERATOR)
    @app_commands.checks.cooldown(3, 30.0)
    async def ban(
        self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None, delete_days: int = 0
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_hierarchy(interaction, member):
            return
        await self.service.ban(interaction.guild, member, interaction.user, reason, delete_message_days=max(0, min(delete_days, 7)))
        self._emit(interaction.guild_id, "ban", interaction.user, member.id, reason)
        await interaction.followup.send(f"🔨 {member.mention} забанен(а). Причина: {reason or '—'}", ephemeral=True)

    @mod_group.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.describe(user_id="ID пользователя", reason="Причина")
    @require(Role.MODERATOR)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            parsed_id = int(user_id)
        except ValueError:
            await interaction.followup.send("⚠️ ID должен быть числом.", ephemeral=True)
            return
        await self.service.unban(interaction.guild, parsed_id, interaction.user, reason)
        self._emit(interaction.guild_id, "unban", interaction.user, parsed_id, reason)
        await interaction.followup.send(f"✅ Пользователь `{parsed_id}` разбанен.", ephemeral=True)

    @mod_group.command(name="kick", description="Выгнать участника")
    @app_commands.describe(member="Кого выгнать", reason="Причина")
    @require(Role.MODERATOR)
    @app_commands.checks.cooldown(3, 30.0)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_hierarchy(interaction, member):
            return
        await self.service.kick(interaction.guild, member, interaction.user, reason)
        self._emit(interaction.guild_id, "kick", interaction.user, member.id, reason)
        await interaction.followup.send(f"👢 {member.mention} выгнан(а). Причина: {reason or '—'}", ephemeral=True)

    @mod_group.command(name="timeout", description="Выдать тайм-аут участнику")
    @app_commands.describe(member="Кому выдать", minutes="На сколько минут", reason="Причина")
    @require(Role.MODERATOR)
    @app_commands.checks.cooldown(5, 30.0)
    async def timeout(
        self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_hierarchy(interaction, member):
            return
        await self.service.timeout(member, interaction.user, minutes, reason)
        self._emit(interaction.guild_id, "timeout", interaction.user, member.id, reason, minutes=minutes)
        await interaction.followup.send(f"⏱ {member.mention} получил(а) тайм-аут на {minutes} мин.", ephemeral=True)

    @mod_group.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(member="Кому выдать", reason="Причина")
    @require(Role.SUPPORT)
    @app_commands.checks.cooldown(5, 30.0)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_hierarchy(interaction, member):
            return
        count = await self.service.warn(interaction.guild_id, member.id, interaction.user, reason)
        self._emit(interaction.guild_id, "warn", interaction.user, member.id, reason, total_warnings=count)
        await interaction.followup.send(f"⚠️ {member.mention} предупрежден(а) (всего: {count}).", ephemeral=True)

    @mod_group.command(name="history", description="История модерации участника")
    @app_commands.describe(member="Участник")
    @require(Role.SUPPORT)
    async def history(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        records = await self.service.history(interaction.guild_id, member.id)
        if not records:
            await interaction.followup.send("История пуста.", ephemeral=True)
            return
        lines = [f"`{r.created_at:%Y-%m-%d %H:%M}` **{r.action}** — {r.reason or '—'}" for r in records]
        embed = discord.Embed(
            title=f"История модерации: {member.display_name}",
            description="\n".join(lines)[:4000],
            color=discord.Color.orange(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_moderation_cog(ctx, service: ModerationService) -> ModerationCog:
    return ModerationCog(ctx, service)
