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

Все команды, кроме ``/message``, умеют отправлять не только в обычный
канал, но и создавать НОВЫЙ пост в форум-канале (``channel`` принимает
и то, и другое) -- см. :func:`_deliver_pages`. У форум-канала нет
``.send()`` (Discord не позволяет писать в сам канал форума, только в
его посты-треды), поэтому раньше единственным способом получить в
форуме "красивое" сообщение от бота было создать пустой пост руками
и отдельно попросить бота отправить embed уже ВНУТРЬ него -- отсюда и
"Оригинальное сообщение удалено" у плейсхолдера. Теперь бот создаёт
пост целиком сам, embed сразу становится стартовым сообщением.
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


async def _deliver_pages(
    target: discord.abc.GuildChannel, pages: list[list[discord.Embed]], *, topic: str | None,
) -> discord.abc.Messageable:
    """Отправляет отрендеренные страницы (см. ``MessageRenderer.render``)
    в обычный канал -- как раньше, по одному сообщению на страницу. Если
    ``target`` -- форум-канал, вместо этого создаёт НОВЫЙ пост: первая
    страница целиком (эмбеды + картинка) становится стартовым сообщением
    поста, остальные страницы (если контент не влез в одно сообщение)
    уходят следом уже в сам созданный тред. Возвращает канал/тред, куда
    реально ушло сообщение -- пригодится для финального "✅ Отправлено"."""
    if isinstance(target, discord.ForumChannel):
        first, *rest = pages
        result = await target.create_thread(name=(topic or "Без темы")[:100], embeds=first)
        for page in rest:
            await result.thread.send(embeds=page)
        return result.thread
    for page in pages:
        await target.send(embeds=page)
    return target


def _forum_missing_topic_error() -> str:
    return "⚠️ Для форум-канала укажите `topic` -- название поста (у форума нет обычного текста, только посты)."


class AnnounceModal(discord.ui.Modal, title="Новое объявление"):
    announce_title = discord.ui.TextInput(label="Заголовок", max_length=256)
    body = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph, max_length=4000)
    image_url = discord.ui.TextInput(label="Изображение / GIF (URL, опционально)", required=False)
    topic = discord.ui.TextInput(label="Тема поста (только для форум-канала)", required=False, max_length=100)

    def __init__(self, renderer: MessageRenderer, channel: discord.abc.GuildChannel) -> None:
        super().__init__()
        self._renderer = renderer
        self._channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if isinstance(self._channel, discord.ForumChannel) and not self.topic.value:
            await interaction.followup.send(_forum_missing_topic_error(), ephemeral=True)
            return

        spec = build_message_spec(
            {
                "title": str(self.announce_title),
                "description": str(self.body),
                "media": {"type": "image", "url": str(self.image_url)} if self.image_url.value else None,
                "author": {"enabled": True, "name": interaction.guild.name if interaction.guild else "SkyHub", "avatar": "bot"},
            }
        )
        pages = self._renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(self._channel, pages, topic=str(self.topic.value) if self.topic.value else None)
        note = f" Пост: {destination.mention}" if isinstance(self._channel, discord.ForumChannel) else ""
        await interaction.followup.send(f"✅ Объявление отправлено.{note}", ephemeral=True)


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
        # У форум-канала нет обычного текста (только посты с темой) --
        # для "красивого" поста с заголовком/картинкой используйте
        # /embed или /message_template, они умеют создавать посты форума.
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        chunks = split_text(text, DISCORD_MESSAGE_LIMIT - 20)
        for index, chunk in enumerate(chunks, start=1):
            prefix = f"**MESSAGE {index}/{len(chunks)}**\n" if len(chunks) > 1 else ""
            await target.send(prefix + chunk)
        await interaction.followup.send(f"✅ Отправлено ({len(chunks)} сообщение(й)).", ephemeral=True)

    @app_commands.command(name="embed", description="Отправить оформленное embed-сообщение (или создать пост в форуме)")
    @app_commands.describe(
        title="Заголовок", description="Текст", color="Цвет полосы слева (hex, напр. 2B6CB0)",
        image_url="URL изображения/GIF", channel="Куда отправить (обычный канал ИЛИ форум-канал)",
        topic="Название поста -- нужно, ТОЛЬКО если channel -- форум-канал",
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
        channel: discord.TextChannel | discord.ForumChannel | None = None,
        topic: str | None = None,
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
        if isinstance(target, discord.ForumChannel) and not topic:
            await interaction.followup.send(_forum_missing_topic_error(), ephemeral=True)
            return

        pages = self.renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(target, pages, topic=topic)
        note = f" Пост: {destination.mention}" if isinstance(target, discord.ForumChannel) else ""
        await interaction.followup.send(f"✅ Отправлено.{note}", ephemeral=True)

    @app_commands.command(name="announce", description="Открыть форму для оформленного объявления")
    @app_commands.describe(channel="Куда отправить (по умолчанию -- текущий канал; можно и форум-канал)")
    @require(Role.MODERATOR)
    async def announce(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.ForumChannel | None = None,
    ) -> None:
        # send_modal -- это и есть подтверждение интеракции, defer() здесь
        # не нужен (и невозможен -- нельзя и то, и другое сразу).
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.ForumChannel)):
            await interaction.response.send_message("⚠️ Объявление можно отправить только в текстовый или форум-канал.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnounceModal(self.renderer, target))

    @app_commands.command(name="message_template", description="Отправить сообщение из готового шаблона (или создать пост в форуме)")
    @app_commands.describe(
        template="Имя шаблона", channel="Куда отправить (обычный канал ИЛИ форум-канал)",
        topic="Название поста -- нужно, ТОЛЬКО если channel -- форум-канал",
    )
    @app_commands.autocomplete(template=_template_autocomplete)
    @require(Role.SUPPORT)
    async def message_template(
        self, interaction: discord.Interaction, template: str,
        channel: discord.TextChannel | discord.ForumChannel | None = None, topic: str | None = None,
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
        if isinstance(target, discord.ForumChannel) and not topic:
            await interaction.followup.send(_forum_missing_topic_error(), ephemeral=True)
            return

        pages = self.renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(target, pages, topic=topic)
        note = f" Пост: {destination.mention}" if isinstance(target, discord.ForumChannel) else ""
        await interaction.followup.send(f"✅ Отправлено.{note}", ephemeral=True)


def build_message_builder_cog(ctx) -> MessageBuilderCog:
    return MessageBuilderCog(ctx)
