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

# Маркеры списка -- ровно те же 4 варианта, что в стандартной "Библиотеке
# маркеров" Word (нет / закрашенный кружок / пустой кружок / квадрат).
# У Discord нет понятия "маркированный список" со своим стилем -- это
# просто символ, который мы сами приписываем перед строкой.
_MARKERS = {"bullet": "•", "circle": "◦", "square": "▪", "none": ""}

# Отступ вложенного подпункта. Discord схлопывает несколько подряд идущих
# ОБЫЧНЫХ пробелов в один (как обычный HTML), поэтому для реального
# визуального отступа используются неразрывные пробелы (U+00A0) -- их
# Discord не схлопывает.
_SUB_INDENT = " " * 4


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


class ListItemSpec(BaseModel):
    """Пункт списка со своим вложенным подсписком (один уровень
    вложенности -- этого достаточно для структуры вида "пункт, а под ним
    А./Б./В."). Обычная строка вместо этого объекта -- пункт без вложенных."""

    text: str
    items: list[str] = Field(default_factory=list)


class SectionSpec(BaseModel):
    title: str | None = None
    content: str | list[str | ListItemSpec] | None = None
    # 0 (по умолчанию) -- заголовок жирным, как в обычном тексте
    # (примерно как раньше выглядело имя embed-поля). 1/2/3 -- настоящий
    # Discord-заголовок #/##/### -- крупный/средний/мелкий, можно
    # свободно чередовать между разделами одного сообщения.
    heading: Literal[0, 1, 2, 3] = 0
    # Маркер верхнего уровня списка и маркер вложенных подпунктов -- те же
    # 4 варианта, что в "Библиотеке маркеров" Word: bullet (•, по
    # умолчанию для верхнего уровня) / circle (◦, по умолчанию для
    # вложенных) / square (▪) / none (без маркера, просто текст).
    marker: Literal["bullet", "circle", "square", "none"] = "bullet"
    sub_marker: Literal["bullet", "circle", "square", "none"] = "circle"
    # Вложенная цитата (Discord "> текст") -- тонкая полоска ВНУТРИ той
    # же карточки, что и весь остальной текст (общий цвет один на всё
    # сообщение). Именно так выглядит сноска на скриншотах у крупных
    # ботов -- не отдельная карточка, а акцент внутри общей.
    # Ограничение Discord: у цитаты нет своего цвета, только серый.
    blockquote: bool = False
    # Если нужен ИМЕННО свой цвет у сноски -- задайте color (hex, напр.
    # 0xE74C3C). Раздел тогда рисуется ОТДЕЛЬНЫМ мини-embed'ом со своей
    # полоской слева, отдельной от основной карточки (это единственный
    # способ дать сноске нестандартный цвет -- Discord не позволяет
    # красить что-либо внутри одной карточки в разные цвета).
    color: int | None = None

    def rendered_content(self) -> str:
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            # YAML-блоки "|" всегда добавляют один завершающий перенос
            # строки -- без rstrip между разделами накапливались бы
            # лишние пустые строки при склейке через "\n\n".join(...).
            return self.content.rstrip("\n")

        marker = _MARKERS.get(self.marker, "•")
        sub_marker = _MARKERS.get(self.sub_marker, "◦")
        top_prefix = f"{marker} " if marker else ""
        sub_prefix = f"{sub_marker} " if sub_marker else ""

        lines: list[str] = []
        for entry in self.content:
            if isinstance(entry, str):
                lines.append(f"{top_prefix}{entry}")
            else:
                lines.append(f"{top_prefix}{entry.text}")
                for sub in entry.items:
                    lines.append(f"{_SUB_INDENT}{sub_prefix}{sub}")
        return "\n".join(lines)

    def rendered_block(self) -> str:
        content = self.rendered_content()
        if not self.title:
            block = content
        else:
            prefix = _HEADING_MARKDOWN.get(self.heading)
            heading_line = f"{prefix}{self.title}" if prefix else f"**{self.title}**"
            block = f"{heading_line}\n{content}" if content else heading_line

        if self.blockquote and block:
            # "> " перед каждой строкой -- иначе цитата Discord
            # обрывается на первом же переносе строки.
            block = "\n".join(f"> {line}" if line else ">" for line in block.split("\n"))
        return block


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
            running.append(spec.description.rstrip("\n"))

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
