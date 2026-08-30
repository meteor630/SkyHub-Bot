"""Движок рендеринга Message Builder (ТЗ §6-10).

Это переиспользуемое ядро, на котором работают и
``plugins/message_builder``, и ``plugins/welcome`` (и всё остальное,
что хочет отправить красиво оформленное, фирменное сообщение
Discord): на входе небольшая декларативная :class:`MessageSpec`, на
выходе -- список готовых к отправке страниц ``(content, embeds)``.

Discord-embed'ы уже сами рисуют цветную вертикальную полосу слева,
если задан ``color``, и нативно поддерживают блоки author/footer/
image -- поэтому мы опираемся на встроенные возможности Embed
согласно ТЗ §6, а не рисуем рамки вручную символами, сохраняя при
этом словарь section/author/footer/media, который описывают
собственные YAML-примеры из ТЗ.

Длинный контент разбивается на несколько embed'ов/сообщений (ТЗ §9),
а не обрезается, так как публичные объявления сообщества могут быть
длинными.
"""
from __future__ import annotations

from typing import Literal

import discord
from pydantic import BaseModel, Field

from utils.text import DISCORD_EMBED_FIELD_VALUE_LIMIT, truncate

DEFAULT_COLOR = 0x2B6CB0  # синий цвет SkyHub; переопределяется для каждого сообщения


class AuthorSpec(BaseModel):
    enabled: bool = True
    name: str | None = None
    avatar: str | None = None  # "bot" | явный URL | None
    subtitle: str | None = None


class FooterSpec(BaseModel):
    text: str | None = None
    icon: str | None = None


class MediaSpec(BaseModel):
    type: Literal["image", "gif"] | None = None
    url: str | None = None


class SectionSpec(BaseModel):
    title: str | None = None
    content: str | list[str] | None = None

    def rendered_value(self) -> str:
        if self.content is None:
            return "\u200b"
        if isinstance(self.content, list):
            text = "\n".join(f"• {item}" for item in self.content)
        else:
            text = self.content
        return truncate(text, DISCORD_EMBED_FIELD_VALUE_LIMIT)


class MessageSpec(BaseModel):
    title: str | None = None
    description: str | None = None
    color: int | None = Field(default=DEFAULT_COLOR)
    author: AuthorSpec = Field(default_factory=AuthorSpec)
    sections: list[SectionSpec] = Field(default_factory=list)
    media: MediaSpec | None = None
    footer: FooterSpec | None = None
    show_author_first_message_only: bool = True


class MessageRenderer:
    """Превращает :class:`MessageSpec` в один или несколько ``discord.Embed``,
    разбивая на страницы ``MESSAGE i/N``, если контент иначе превысил бы
    лимиты Discord на один embed."""

    MAX_FIELDS_PER_EMBED = 20  # с запасом ниже лимита Discord в 25 полей

    def render(self, spec: MessageSpec, *, bot_user: discord.abc.User | None = None) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        current = self._new_embed(spec, is_first=True)
        current_fields = 0

        if spec.description:
            current.description = spec.description

        for section in spec.sections:
            if current_fields >= self.MAX_FIELDS_PER_EMBED:
                embeds.append(current)
                current = self._new_embed(spec, is_first=False)
                current_fields = 0
            current.add_field(
                name=truncate(section.title or "\u200b", 256),
                value=section.rendered_value(),
                inline=False,
            )
            current_fields += 1

        embeds.append(current)

        if spec.media and spec.media.url:
            embeds[0].set_image(url=spec.media.url)

        self._apply_author_and_footer(embeds, spec, bot_user=bot_user)
        return embeds

    def _new_embed(self, spec: MessageSpec, *, is_first: bool) -> discord.Embed:
        embed = discord.Embed(color=spec.color if spec.color is not None else DEFAULT_COLOR)
        if is_first and spec.title:
            embed.title = spec.title
        return embed

    def _apply_author_and_footer(
        self, embeds: list[discord.Embed], spec: MessageSpec, *, bot_user: discord.abc.User | None
    ) -> None:
        total = len(embeds)
        for index, embed in enumerate(embeds, start=1):
            show_author = spec.author.enabled and (index == 1 or not spec.show_author_first_message_only)
            if show_author:
                icon_url = None
                if spec.author.avatar == "bot" and bot_user is not None:
                    icon_url = bot_user.display_avatar.url
                elif spec.author.avatar:
                    icon_url = spec.author.avatar
                name = spec.author.name or (bot_user.display_name if bot_user else None)
                if spec.author.subtitle:
                    name = f"{name} · {spec.author.subtitle}" if name else spec.author.subtitle
                if name:
                    embed.set_author(name=name, icon_url=icon_url)

            footer_parts = []
            if spec.footer and spec.footer.text:
                footer_parts.append(spec.footer.text)
            if total > 1:
                footer_parts.append(f"MESSAGE {index}/{total}")
            if footer_parts:
                embed.set_footer(text=" · ".join(footer_parts), icon_url=spec.footer.icon if spec.footer else None)


def build_message_spec(data: dict) -> MessageSpec:
    """Валидирует обычный словарь (разобранный из YAML или модального окна
    slash-команды) в :class:`MessageSpec`, выбрасывая
    ``pydantic.ValidationError`` при некорректном пользовательском вводе
    (ТЗ §35 -- проверять весь пользовательский ввод)."""
    return MessageSpec.model_validate(data)
