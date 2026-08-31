"""Движок рендеринга Message Builder (ТЗ §6-10).

Это переиспользуемое ядро, на котором работают и
``plugins/message_builder``, и ``plugins/welcome`` (и всё остальное,
что хочет отправить красиво оформленное, фирменное сообщение
Discord): на входе небольшая декларативная :class:`MessageSpec`, на
выходе -- список "страниц" (каждая страница -- один вызов
``channel.send(embeds=...)``, т.е. одно сообщение Discord; внутри
страницы может быть несколько embed'ов сразу, например основной текст
плюс цветная врезка-сноска).

Раньше каждый раздел (:class:`SectionSpec`) рисовался отдельным полем
embed'а (``embed.add_field``) -- у поля фиксированный "жирный" стиль
заголовка без возможности выбрать размер. Теперь разделы без
собственного цвета склеиваются в один текст-описание embed'а и
поддерживают настоящие Discord-заголовки разного размера (`#`/`##`/`###`
-- как заголовки в обычном сообщении), а раздел со своим ``color``
рисуется отдельным мини-embed'ом со своей цветной полоской слева --
получается "сноска"/врезка нужного цвета, не мешающая остальному тексту.

Discord-embed'ы уже сами рисуют цветную вертикальную полосу слева,
если задан ``color``, и нативно поддерживают блоки author/footer/
image -- поэтому мы опираемся на встроенные возможности Embed,
сохраняя при этом декларативный словарь section/author/footer/media,
который описывают собственные YAML-примеры из ТЗ.

Длинный контент разбивается на несколько embed'ов/сообщений (ТЗ §9),
а не обрезается, так как публичные объявления сообщества могут быть
длинными.
"""
from __future__ import annotations

from typing import Literal

import discord
from pydantic import BaseModel, Field

from utils.text import DISCORD_EMBED_DESCRIPTION_LIMIT, DISCORD_EMBED_TOTAL_LIMIT, paginate_label, split_text

DEFAULT_COLOR = 0x2B6CB0  # синий цвет SkyHub; переопределяется для каждого сообщения

# Markdown-заголовки Discord (работают в description/значениях полей embed'а,
# но НЕ в имени поля -- поэтому раздел с заголовком крупнее "мелкого"
# больше не рисуется как embed-поле, а склеивается в общий текст).
_HEADING_MARKDOWN = {1: "# ", 2: "## ", 3: "### "}

MAX_EMBEDS_PER_MESSAGE = 10  # жёсткий лимит Discord на embed'ы в одном сообщении


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
    # 0 (по умолчанию) -- заголовок жирным, как в обычном тексте
    # (примерно как раньше выглядело имя embed-поля). 1/2/3 -- настоящий
    # Discord-заголовок #/##/### -- крупный/средний/мелкий, можно
    # свободно чередовать между разделами одного сообщения.
    heading: Literal[0, 1, 2, 3] = 0
    # Если задан -- раздел рисуется ОТДЕЛЬНЫМ мини-embed'ом со своей
    # цветной полоской слева (сноска/врезка), а не сливается в общий
    # текст. Цвет -- как и у всего сообщения, hex-число (напр. 0xE74C3C).
    color: int | None = None

    def rendered_content(self) -> str:
        if self.content is None:
            return ""
        if isinstance(self.content, list):
            return "\n".join(f"• {item}" for item in self.content)
        return self.content

    def rendered_block(self) -> str:
        content = self.rendered_content()
        if not self.title:
            return content
        prefix = _HEADING_MARKDOWN.get(self.heading)
        heading_line = f"{prefix}{self.title}" if prefix else f"**{self.title}**"
        return f"{heading_line}\n{content}" if content else heading_line


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
    """Превращает :class:`MessageSpec` в список "страниц" -- список
    списков ``discord.Embed``, где внешний список -- отдельные сообщения
    (``MESSAGE i/N`` при переполнении), а внутренний -- embed'ы,
    отправляемые одним сообщением (основной текст + возможные цветные
    врезки)."""

    def render(self, spec: MessageSpec, *, bot_user: discord.abc.User | None = None) -> list[list[discord.Embed]]:
        blocks = self._build_blocks(spec)
        pages = self._paginate(blocks, spec)
        if not pages:
            pages = [[discord.Embed(color=spec.color if spec.color is not None else DEFAULT_COLOR)]]
        if spec.title:
            pages[0][0].title = spec.title
        if spec.media and spec.media.url:
            pages[0][0].set_image(url=spec.media.url)
        self._apply_author_and_footer(pages, spec, bot_user=bot_user)
        return pages

    def _build_blocks(self, spec: MessageSpec) -> list[tuple[str, int | None]]:
        """Собирает список ``(текст, цвет_или_None)`` -- обычные разделы
        подряд склеиваются в один блок (``color=None``), раздел со своим
        ``color`` образует отдельный блок, чтобы стать своим embed'ом."""
        blocks: list[tuple[str, int | None]] = []
        running: list[str] = []
        if spec.description:
            running.append(spec.description)

        def flush() -> None:
            if running:
                blocks.append(("\n\n".join(running), None))
                running.clear()

        for section in spec.sections:
            if section.color is not None:
                flush()
                blocks.append((section.rendered_block(), section.color))
            else:
                running.append(section.rendered_block())
        flush()
        return blocks

    def _paginate(self, blocks: list[tuple[str, int | None]], spec: MessageSpec) -> list[list[discord.Embed]]:
        pages: list[list[discord.Embed]] = []
        current_page: list[discord.Embed] = []
        current_chars = 0

        for text, color in blocks:
            for chunk in split_text(text, DISCORD_EMBED_DESCRIPTION_LIMIT) or [""]:
                if not chunk:
                    continue
                exceeds_message = (
                    len(current_page) >= MAX_EMBEDS_PER_MESSAGE
                    or current_chars + len(chunk) > DISCORD_EMBED_TOTAL_LIMIT
                )
                if exceeds_message and current_page:
                    pages.append(current_page)
                    current_page = []
                    current_chars = 0
                embed_color = color if color is not None else (spec.color if spec.color is not None else DEFAULT_COLOR)
                current_page.append(discord.Embed(color=embed_color, description=chunk))
                current_chars += len(chunk)

        if current_page:
            pages.append(current_page)
        return pages

    def _apply_author_and_footer(
        self, pages: list[list[discord.Embed]], spec: MessageSpec, *, bot_user: discord.abc.User | None
    ) -> None:
        total = len(pages)
        for index, page in enumerate(pages, start=1):
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
                    page[0].set_author(name=name, icon_url=icon_url)

            footer_parts = []
            if spec.footer and spec.footer.text:
                footer_parts.append(spec.footer.text)
            if total > 1:
                footer_parts.append(paginate_label(index, total))
            if footer_parts:
                page[-1].set_footer(text=" · ".join(footer_parts), icon_url=spec.footer.icon if spec.footer else None)


def build_message_spec(data: dict) -> MessageSpec:
    """Валидирует обычный словарь (разобранный из YAML или модального окна
    slash-команды) в :class:`MessageSpec`, выбрасывая
    ``pydantic.ValidationError`` при некорректном пользовательском вводе
    (ТЗ §35 -- проверять весь пользовательский ввод)."""
    return MessageSpec.model_validate(data)
