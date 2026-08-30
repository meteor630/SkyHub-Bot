"""``/profile`` -- авиационный профиль участника: роль (пилот/диспетчер/...),
симулятор, сеть (ТЗ §41 "Авиационные роли", заметка клиента про "систему
контекста пользователя")."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.events import ProfileUpdated
from database.repositories.profile_repository import ProfileRepository

ROLE_TYPE_LABELS = {
    "pilot": "✈️ Pilot",
    "atc": "🎧 ATC",
    "virtual_airline": "🏢 Virtual Airline",
    "flight_simmer": "🕹 Flight Simmer",
    "spotter": "📷 Spotter",
    "enthusiast": "❤️ Aviation Enthusiast",
}
SIMULATOR_LABELS = {"msfs": "MSFS", "xplane": "X-Plane", "prepar3d": "Prepar3D", "dcs": "DCS"}
NETWORK_LABELS = {"vatsim": "VATSIM", "ivao": "IVAO", "pilotedge": "PilotEdge"}


class RoleTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [discord.SelectOption(label=label, value=key) for key, label in ROLE_TYPE_LABELS.items()]
        super().__init__(placeholder="Кто вы? (обязательно)", options=options, min_values=1, max_values=1)


class SimulatorSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [discord.SelectOption(label=label, value=key) for key, label in SIMULATOR_LABELS.items()]
        options.append(discord.SelectOption(label="Не указывать", value="none"))
        super().__init__(placeholder="Симулятор (опционально)", options=options, min_values=0, max_values=1)


class NetworkSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [discord.SelectOption(label=label, value=key) for key, label in NETWORK_LABELS.items()]
        options.append(discord.SelectOption(label="Не указывать", value="none"))
        super().__init__(placeholder="Сеть (опционально)", options=options, min_values=0, max_values=1)


class ProfileSetupView(discord.ui.View):
    def __init__(self, ctx) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.role_select = RoleTypeSelect()
        self.simulator_select = SimulatorSelect()
        self.network_select = NetworkSelect()
        self.add_item(self.role_select)
        self.add_item(self.simulator_select)
        self.add_item(self.network_select)

        confirm = discord.ui.Button(label="Сохранить", emoji="✅", style=discord.ButtonStyle.success, row=3)
        confirm.callback = self._save
        self.add_item(confirm)

    async def _save(self, interaction: discord.Interaction) -> None:
        if not self.role_select.values:
            await interaction.response.send_message("⚠️ Выберите, кто вы -- это обязательное поле.", ephemeral=True)
            return

        role_type = self.role_select.values[0]
        simulator = self.simulator_select.values[0] if self.simulator_select.values else None
        simulator = None if simulator == "none" else simulator
        network = self.network_select.values[0] if self.network_select.values else None
        network = None if network == "none" else network

        await interaction.response.defer(ephemeral=True)

        async with self.ctx.db.session() as session:
            await ProfileRepository(session).upsert(
                guild_id=interaction.guild_id, user_id=interaction.user.id,
                role_type=role_type, simulator=simulator, network=network, vatsim_id=None,
            )

        await self._sync_discord_role(interaction, role_type)

        self.ctx.emit(
            ProfileUpdated(guild_id=interaction.guild_id, user_id=interaction.user.id, role_type=role_type, simulator=simulator, network=network)
        )

        summary = ROLE_TYPE_LABELS[role_type]
        if simulator:
            summary += f" · {SIMULATOR_LABELS.get(simulator, simulator)}"
        if network:
            summary += f" · {NETWORK_LABELS.get(network, network)}"
        await interaction.followup.send(f"✅ Профиль сохранён: {summary}", ephemeral=True)

    async def _sync_discord_role(self, interaction: discord.Interaction, new_role_type: str) -> None:
        """Снимает роль предыдущего типа профиля (если была) и выдаёт роль
        нового типа -- если администратор их настроил через
        `/setup profile-roles`. Если не настроил -- просто пропускаем,
        профиль всё равно сохранён в базе."""
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        role_map = {}
        for role_type in ROLE_TYPE_LABELS:
            role_id = await self.ctx.guild_config().resolve_profile_role_id(interaction.guild_id, role_type)
            if role_id:
                role_map[role_type] = role_id

        to_remove = [
            discord.Object(id=rid) for rtype, rid in role_map.items()
            if rtype != new_role_type and member.get_role(rid) is not None
        ]
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="Смена авиационного профиля")
            except discord.HTTPException:
                pass

        new_role_id = role_map.get(new_role_type)
        if new_role_id and member.get_role(new_role_id) is None:
            try:
                await member.add_roles(discord.Object(id=new_role_id), reason="Авиационный профиль: " + new_role_type)
            except discord.HTTPException:
                pass


class ProfileCog(commands.Cog):
    profile_group = app_commands.Group(name="profile", description="Авиационный профиль участника", guild_only=True)

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @profile_group.command(name="set", description="Указать/изменить свой авиационный профиль")
    async def set_profile(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Расскажите о себе:", view=ProfileSetupView(self.ctx), ephemeral=True
        )

    @profile_group.command(name="show", description="Показать авиационный профиль участника")
    @app_commands.describe(member="Участник (по умолчанию -- вы)")
    async def show_profile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        async with self.ctx.db.session() as session:
            profile = await ProfileRepository(session).get(interaction.guild_id, target.id)

        if profile is None:
            await interaction.followup.send(f"У {target.mention} ещё нет профиля -- `/profile set`.", ephemeral=True)
            return

        embed = discord.Embed(title=f"✈️ Профиль: {target.display_name}", color=discord.Color.blue())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Роль", value=ROLE_TYPE_LABELS.get(profile.role_type, profile.role_type))
        embed.add_field(name="Симулятор", value=SIMULATOR_LABELS.get(profile.simulator, "—") if profile.simulator else "—")
        embed.add_field(name="Сеть", value=NETWORK_LABELS.get(profile.network, "—") if profile.network else "—")
        await interaction.followup.send(embed=embed, ephemeral=True)


def build_profile_cog(ctx) -> ProfileCog:
    return ProfileCog(ctx)
