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

``channel`` здесь -- ОБЫЧНАЯ строка с автодополнением из ``guild.channels``
(собственный кэш бота, который discord.py обновляет мгновенно по
гейтвей-событиям), а НЕ нативный channel-тип параметра slash-команды
(``discord.TextChannel | discord.ForumChannel``, как было раньше). У
нативного параметра та же проблема, что и у ``discord.ui.ChannelSelect``/
``RoleSelect`` (см. подробное расследование в docstring
``plugins/server_setup/commands.py``): список вариантов в выпадающем
списке строит и отдаёт сервер Discord через свой отдельный внутренний
механизм автозаполнения -- он на практике иногда показывает не все
каналы, которые реально есть на сервере (в т.ч. форум-каналы, из-за
чего в /embed их вообще не было видно в списке). Собственное
автодополнение, построенное из кэша бота, от этого недостатка не
страдает -- ровно тот же принцип, что и у ``ManualChannelSelect`` в
``/setup``.

Пинги ролей/участников (``mentions``, у ``/embed``/``/announce``/
``/message_template``) отправляются ОБЫЧНЫМ текстом сообщения
(``content=``), а не внутри embed'а -- по той же причине, что и в
``plugins/welcome/plugin.py``: упоминание внутри embed'а не присылает
реальный пуш-пинг и иногда не резолвится в цветное имя на некоторых
клиентах (см. историю правки приветствия). Только упоминание в
``content`` гарантированно красится в цвет роли и реально пингует.
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

_TEXT_CHANNEL_TYPES = (discord.ChannelType.text, discord.ChannelType.news)
_TEXT_OR_FORUM_CHANNEL_TYPES = (
    discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.forum, discord.ChannelType.media,
)


def _list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.yaml"))


def _guild_channel_choices(
    guild: discord.Guild, current: str, *, channel_types: tuple[discord.ChannelType, ...],
) -> list[app_commands.Choice[str]]:
    """Варианты автодополнения ``channel`` -- построены вручную из
    ``guild.channels`` (см. подробности в docstring модуля)."""
    channels = sorted(
        (c for c in guild.channels if c.type in channel_types),
        key=lambda c: (c.position, c.name.lower()),
    )
    current_lower = current.lower()
    if current_lower:
        channels = [c for c in channels if current_lower in c.name.lower()]
    return [app_commands.Choice(name=f"#{c.name}", value=str(c.id)) for c in channels[:25]]


def _resolve_channel_choice(
    guild: discord.Guild | None, raw: str | None, *, channel_types: tuple[discord.ChannelType, ...],
) -> discord.abc.GuildChannel | None:
    """Резолвит значение параметра ``channel``: либо ID из автодополнения,
    либо ID/``<#id>``-упоминание, введённое вручную. ``None``, если
    ``raw`` пуст или ничего подходящего не нашлось (вызывающий код в
    этом случае сам решает, что подставить по умолчанию)."""
    if not raw or guild is None:
        return None
    cleaned = raw.strip().removeprefix("<#").removesuffix(">")
    if not cleaned.isdigit():
        return None
    channel = guild.get_channel(int(cleaned))
    if channel is not None and channel.type in channel_types:
        return channel
    return None


def _resolve_mentions(guild: discord.Guild | None, raw: str | list[str] | None) -> tuple[str | None, list[str]]:
    """Резолвит роли/участников (по имени, ID или ``@``/``<@...>``-
    упоминанию) в НАСТОЯЩИЕ Discord-упоминания -- их нужно отправить
    обычным текстом сообщения (``content=``), а не внутрь embed'а (см.
    docstring модуля). Возвращает (готовая строка упоминаний через
    пробел, или None -- список НЕ найденных токенов, чтобы предупредить
    автора об опечатке, а не молча её проглотить)."""
    if not raw or guild is None:
        return None, []
    tokens = raw if isinstance(raw, list) else raw.split(",")
    tokens = [t.strip() for t in tokens if t.strip()]

    mentions: list[str] = []
    unresolved: list[str] = []
    for token in tokens:
        cleaned = token.lstrip("@").removeprefix("<@&").removeprefix("<@").removesuffix(">")
        role = discord.utils.get(guild.roles, id=int(cleaned)) if cleaned.isdigit() else None
        role = role or discord.utils.find(lambda r, c=cleaned: r.name.lower() == c.lower(), guild.roles)
        if role is not None:
            mentions.append(role.mention)
            continue

        member = guild.get_member(int(cleaned)) if cleaned.isdigit() else None
        member = member or discord.utils.find(
            lambda m, c=cleaned: c.lower() in {m.name.lower(), (m.global_name or "").lower(), m.display_name.lower()},
            guild.members,
        )
        if member is not None:
            mentions.append(member.mention)
            continue

        unresolved.append(token)

    return (" ".join(mentions) if mentions else None), unresolved


async def _deliver_pages(
    target: discord.abc.GuildChannel, pages: list[list[discord.Embed]], *, topic: str | None, content: str | None = None,
) -> discord.abc.Messageable:
    """Отправляет отрендеренные страницы (см. ``MessageRenderer.render``)
    в обычный канал -- как раньше, по одному сообщению на страницу. Если
    ``target`` -- форум-канал, вместо этого создаёт НОВЫЙ пост: первая
    страница целиком (эмбеды + картинка) становится стартовым сообщением
    поста, остальные страницы (если контент не влез в одно сообщение)
    уходят следом уже в сам созданный тред. ``content`` (готовые
    Discord-упоминания, см. :func:`_resolve_mentions`) идёт ТОЛЬКО у
    самого первого сообщения -- дублировать пинг на каждой странице
    длинного объявления незачем. Возвращает канал/тред, куда реально
    ушло сообщение -- пригодится для финального "✅ Отправлено"."""
    first, *rest = pages
    if isinstance(target, discord.ForumChannel):
        result = await target.create_thread(name=(topic or "Без темы")[:100], content=content, embeds=first)
        for page in rest:
            await result.thread.send(embeds=page)
        return result.thread
    await target.send(content=content, embeds=first)
    for page in rest:
        await target.send(embeds=page)
    return target


def _forum_missing_topic_error() -> str:
    return "⚠️ Для форум-канала укажите `topic` -- название поста (у форума нет обычного текста, только посты)."


def _channel_not_found_error() -> str:
    return "⚠️ Канал не найден -- выберите его из автодополнения (начните печатать название) или укажите #упоминание/ID."


class AnnounceModal(discord.ui.Modal, title="Новое объявление"):
    announce_title = discord.ui.TextInput(label="Заголовок", max_length=256)
    body = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph, max_length=4000)
    image_url = discord.ui.TextInput(label="Изображение / GIF (URL, опционально)", required=False)
    topic = discord.ui.TextInput(label="Тема поста (только для форум-канала)", required=False, max_length=100)
    mentions = discord.ui.TextInput(
        label="Роли/участники для пинга (через запятую)", required=False, max_length=300,
    )

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
        mention_content, unresolved = _resolve_mentions(interaction.guild, str(self.mentions.value) or None)

        pages = self._renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(
            self._channel, pages, topic=str(self.topic.value) if self.topic.value else None, content=mention_content,
        )
        note = f" Пост: {destination.mention}" if isinstance(self._channel, discord.ForumChannel) else ""
        if unresolved:
            note += f" ⚠️ Не нашёл: {', '.join(unresolved)}."
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

    async def _text_channel_autocomplete(self, interaction: discord.Interaction, current: str):
        if interaction.guild is None:
            return []
        return _guild_channel_choices(interaction.guild, current, channel_types=_TEXT_CHANNEL_TYPES)

    async def _text_or_forum_channel_autocomplete(self, interaction: discord.Interaction, current: str):
        if interaction.guild is None:
            return []
        return _guild_channel_choices(interaction.guild, current, channel_types=_TEXT_OR_FORUM_CHANNEL_TYPES)

    @app_commands.command(name="message", description="Отправить текстовое сообщение (с авто-разбиением на части)")
    @app_commands.describe(text="Текст сообщения", channel="Куда отправить (начните печатать название; по умолчанию -- текущий канал)")
    @app_commands.autocomplete(channel=_text_channel_autocomplete)
    @require(Role.SUPPORT)
    @app_commands.checks.cooldown(1, 10.0)
    async def message(self, interaction: discord.Interaction, text: str, channel: str | None = None) -> None:
        # У форум-канала нет обычного текста (только посты с темой) --
        # для "красивого" поста с заголовком/картинкой используйте
        # /embed или /message_template, они умеют создавать посты форума.
        await interaction.response.defer(ephemeral=True)
        resolved = _resolve_channel_choice(interaction.guild, channel, channel_types=_TEXT_CHANNEL_TYPES)
        if channel and resolved is None:
            await interaction.followup.send(_channel_not_found_error(), ephemeral=True)
            return

        target = resolved or interaction.channel
        chunks = split_text(text, DISCORD_MESSAGE_LIMIT - 20)
        for index, chunk in enumerate(chunks, start=1):
            prefix = f"**MESSAGE {index}/{len(chunks)}**\n" if len(chunks) > 1 else ""
            await target.send(prefix + chunk)
        await interaction.followup.send(f"✅ Отправлено ({len(chunks)} сообщение(й)).", ephemeral=True)

    @app_commands.command(name="embed", description="Отправить оформленное embed-сообщение (или создать пост в форуме)")
    @app_commands.describe(
        title="Заголовок", description="Текст", color="Цвет полосы слева (hex, напр. 2B6CB0)",
        image_url="URL изображения/GIF", channel="Куда отправить -- обычный канал ИЛИ форум-канал (начните печатать название)",
        topic="Название поста -- нужно, ТОЛЬКО если channel -- форум-канал",
        mentions="Роли/участники для пинга через запятую (по имени, ID или упоминанию) -- пингуются и красятся по-настоящему",
    )
    @app_commands.autocomplete(channel=_text_or_forum_channel_autocomplete)
    @require(Role.SUPPORT)
    @app_commands.checks.cooldown(1, 10.0)
    async def embed(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: str | None = None,
        image_url: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        mentions: str | None = None,
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

        resolved = _resolve_channel_choice(interaction.guild, channel, channel_types=_TEXT_OR_FORUM_CHANNEL_TYPES)
        if channel and resolved is None:
            await interaction.followup.send(_channel_not_found_error(), ephemeral=True)
            return

        target = resolved or interaction.channel
        if isinstance(target, discord.ForumChannel) and not topic:
            await interaction.followup.send(_forum_missing_topic_error(), ephemeral=True)
            return

        mention_content, unresolved = _resolve_mentions(interaction.guild, mentions)

        pages = self.renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(target, pages, topic=topic, content=mention_content)
        note = f" Пост: {destination.mention}" if isinstance(target, discord.ForumChannel) else ""
        if unresolved:
            note += f" ⚠️ Не нашёл: {', '.join(unresolved)}."
        await interaction.followup.send(f"✅ Отправлено.{note}", ephemeral=True)

    @app_commands.command(name="announce", description="Открыть форму для оформленного объявления")
    @app_commands.describe(channel="Куда отправить -- обычный канал ИЛИ форум-канал (по умолчанию -- текущий канал)")
    @app_commands.autocomplete(channel=_text_or_forum_channel_autocomplete)
    @require(Role.MODERATOR)
    async def announce(self, interaction: discord.Interaction, channel: str | None = None) -> None:
        resolved = _resolve_channel_choice(interaction.guild, channel, channel_types=_TEXT_OR_FORUM_CHANNEL_TYPES)
        if channel and resolved is None:
            await interaction.response.send_message(_channel_not_found_error(), ephemeral=True)
            return

        target = resolved or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.ForumChannel)):
            await interaction.response.send_message("⚠️ Объявление можно отправить только в текстовый или форум-канал.", ephemeral=True)
            return
        # send_modal -- это и есть подтверждение интеракции, defer() здесь
        # не нужен (и невозможен -- нельзя и то, и другое сразу).
        await interaction.response.send_modal(AnnounceModal(self.renderer, target))

    @app_commands.command(name="message_template", description="Отправить сообщение из готового шаблона (или создать пост в форуме)")
    @app_commands.describe(
        template="Имя шаблона", channel="Куда отправить -- обычный канал ИЛИ форум-канал (начните печатать название)",
        topic="Название поста -- нужно, ТОЛЬКО если channel -- форум-канал",
    )
    @app_commands.autocomplete(template=_template_autocomplete, channel=_text_or_forum_channel_autocomplete)
    @require(Role.SUPPORT)
    async def message_template(
        self, interaction: discord.Interaction, template: str, channel: str | None = None, topic: str | None = None,
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

        resolved = _resolve_channel_choice(interaction.guild, channel, channel_types=_TEXT_OR_FORUM_CHANNEL_TYPES)
        if channel and resolved is None:
            await interaction.followup.send(_channel_not_found_error(), ephemeral=True)
            return

        target = resolved or interaction.channel
        if isinstance(target, discord.ForumChannel) and not topic:
            await interaction.followup.send(_forum_missing_topic_error(), ephemeral=True)
            return

        # "mentions" -- необязательный ключ ВЕРХНЕГО уровня YAML (список
        # имён/ID ролей или участников), не часть MessageSpec -- пинг
        # должен уйти обычным текстом (content=), а не внутрь embed'а
        # (см. docstring модуля), поэтому резолвится отдельно от рендера.
        mention_content, unresolved = _resolve_mentions(interaction.guild, data.get("mentions"))

        pages = self.renderer.render(spec, bot_user=interaction.client.user)
        destination = await _deliver_pages(target, pages, topic=topic, content=mention_content)
        note = f" Пост: {destination.mention}" if isinstance(target, discord.ForumChannel) else ""
        if unresolved:
            note += f" ⚠️ Не нашёл: {', '.join(unresolved)}."
        await interaction.followup.send(f"✅ Отправлено.{note}", ephemeral=True)


def build_message_builder_cog(ctx) -> MessageBuilderCog:
    return MessageBuilderCog(ctx)
