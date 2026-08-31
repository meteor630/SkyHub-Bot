"""Slash-команды плагина Message Builder (ТЗ §6-10).

Важно: у Discord всего 3 секунды на *первый* ответ на интеракцию.
Поэтому каждая команда сначала подтверждает интеракцию через
``defer()`` -- это единственное, что должно уложиться в те 3 секунды --
а уже вся остальная работа (отправка сообщений в канал, чтение
шаблонов и т.д.) идёт через ``followup``, у которого окно на порядок
шире (около 15 минут). Раньше некоторые команды сначала отправляли
все сообщения в канал и только потом отвечали на саму интеракцию --
при малейшей задержке (даже сетевой) это гарантированно приводило к
``discord.NotFound: Unknown interaction``.
"""
from __future__ import annotations

from pathlib import Path

import discord
import yaml
from discord import app_commands
from discord.ext import commands
from pydantic import ValidationError

from core.permissions import Role, require
from services.message_service import MessageRenderer, build_message_spec
from utils.text import DISCORD_MESSAGE_LIMIT, split_text

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.yaml"))


class AnnounceModal(discord.ui.Modal, title="Новое объявление"):
    announce_title = discord.ui.TextInput(label="Заголовок", max_length=256)
    body = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph, max_length=4000)
    image_url = discord.ui.TextInput(label="Изображение / GIF (URL, опционально)", required=False)

    def __init__(self, renderer: MessageRenderer, channel: discord.abc.Messageable) -> None:
        super().__init__()
        self._renderer = renderer
        self._channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        spec = build_message_spec(
            {
                "title": str(self.announce_title),
                "description": str(self.body),
                "media": {"type": "image", "url": str(self.image_url)} if self.image_url.value else None,
                "author": {"enabled": True, "name": interaction.guild.name if interaction.guild else "SkyHub", "avatar": "bot"},
            }
        )
        for page in self._renderer.render(spec, bot_user=interaction.client.user):
            await self._channel.send(embeds=page)
        await interaction.followup.send("✅ Объявление отправлено.", ephemeral=True)


class MessageBuilderCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.renderer = MessageRenderer()

    async def _template_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=name, value=name)
            for name in _list_templates()
            if current.lower() in name.lower()
        ][:25]

    @app_commands.command(name="message", description="Отправить текстовое сообщение (с авто-разбиением на части)")
    @app_commands.describe(text="Текст сообщения", channel="Куда отправить (по умолчанию -- текущий канал)")
    @require(Role.SUPPORT)
    @app_commands.checks.cooldown(1, 10.0)
    async def message(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        chunks = split_text(text, DISCORD_MESSAGE_LIMIT - 20)
        for index, chunk in enumerate(chunks, start=1):
            prefix = f"**MESSAGE {index}/{len(chunks)}**\n" if len(chunks) > 1 else ""
            await target.send(prefix + chunk)
        await interaction.followup.send(f"✅ Отправлено ({len(chunks)} сообщение(й)).", ephemeral=True)

    @app_commands.command(name="embed", description="Отправить оформленное embed-сообщение")
    @app_commands.describe(
        title="Заголовок", description="Текст", color="Цвет полосы слева (hex, напр. 2B6CB0)",
        image_url="URL изображения/GIF", channel="Куда отправить",
    )
    @require(Role.SUPPORT)
    @app_commands.checks.cooldown(1, 10.0)
    async def embed(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: str | None = None,
        image_url: str | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            parsed_color = int(color, 16) if color else None
        except ValueError:
            await interaction.followup.send("⚠️ Некорректный цвет, используйте hex, напр. `2B6CB0`.", ephemeral=True)
            return

        try:
            spec = build_message_spec(
                {
                    "title": title,
                    "description": description,
                    "color": parsed_color,
                    "media": {"type": "image", "url": image_url} if image_url else None,
                }
            )
        except ValidationError as exc:
            await interaction.followup.send(f"⚠️ Некорректные данные: {exc}", ephemeral=True)
            return

        target = channel or interaction.channel
        for page in self.renderer.render(spec, bot_user=interaction.client.user):
            await target.send(embeds=page)
        await interaction.followup.send("✅ Отправлено.", ephemeral=True)

    @app_commands.command(name="announce", description="Открыть форму для оформленного объявления")
    @app_commands.describe(channel="Куда отправить (по умолчанию -- текущий канал)")
    @require(Role.MODERATOR)
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        # send_modal -- это и есть подтверждение интеракции, defer() здесь
        # не нужен (и невозможен -- нельзя и то, и другое сразу).
        await interaction.response.send_modal(AnnounceModal(self.renderer, channel or interaction.channel))

    @app_commands.command(name="message_template", description="Отправить сообщение из готового шаблона")
    @app_commands.describe(template="Имя шаблона", channel="Куда отправить")
    @app_commands.autocomplete(template=_template_autocomplete)
    @require(Role.SUPPORT)
    async def message_template(
        self, interaction: discord.Interaction, template: str, channel: discord.TextChannel | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        path = TEMPLATES_DIR / f"{template}.yaml"
        if not path.exists():
            await interaction.followup.send("⚠️ Шаблон не найден.", ephemeral=True)
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            spec = build_message_spec(data)
        except (yaml.YAMLError, ValidationError) as exc:
            await interaction.followup.send(f"⚠️ Ошибка в шаблоне: {exc}", ephemeral=True)
            return

        target = channel or interaction.channel
        for page in self.renderer.render(spec, bot_user=interaction.client.user):
            await target.send(embeds=page)
        await interaction.followup.send("✅ Отправлено.", ephemeral=True)


def build_message_builder_cog(ctx) -> MessageBuilderCog:
    return MessageBuilderCog(ctx)
