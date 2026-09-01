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

Списки (``content`` как список пунктов) рендерятся НАСТОЯЩИМ markdown-
списком Discord (``- пункт`` / вложенный ``  - подпункт``, с отступом в
2 пробела на уровень -- именно так, как требует парсер Discord), а не
текстовым символом "•", вручную приписанным перед строкой. Так Discord
сам рисует точку списка -- она заметно крупнее и аккуратнее, чем символ
"•" как обычный текст, и перенос длинной строки внутри ОДНОГО пункта
Discord сам держит с отступом под текст (а не как обычный абзац, который
при переносе съезжает к левому краю). Раньше это делалось руками через
символ-маркер + неразрывные пробелы для отступа -- именно тот подход
давал "текстовые" мелкие точки и перенос без отступа, на который
жаловались после сравнения со скриншотом-эталоном.
"""
from __future__ import annotations

from typing import Literal

import discord
from pydantic import BaseModel, Field, model_validator

from utils.text import DISCORD_EMBED_DESCRIPTION_LIMIT, DISCORD_EMBED_TOTAL_LIMIT, paginate_label, split_text

DEFAULT_COLOR = 0x2B6CB0  # синий цвет SkyHub; переопределяется для каждого сообщения

# Markdown-заголовки Discord (работают в description/значениях полей embed'а,
# но НЕ в имени поля -- поэтому раздел с заголовком крупнее "мелкого"
# больше не рисуется как embed-поле, а склеивается в общий текст).
_HEADING_MARKDOWN = {1: "# ", 2: "## ", 3: "### "}

MAX_EMBEDS_PER_MESSAGE = 10  # жёсткий лимит Discord на embed'ы в одном сообщении

# Отступ вложенного пункта настоящего markdown-списка Discord -- ровно 2
# пробела на уровень (это требование парсера Discord, не наш выбор
# оформления; больше или меньше -- вложенность не распознается).
_NESTED_INDENT = "  "


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
    А./Б./В."). Обычная строка вместо этого объекта -- пункт без вложенных.

    Перенос строки ВНУТРИ одного пункта (не новый пункт списка, а просто
    вторая строка того же пункта) -- вставьте символ ``\\n`` прямо в
    текст, например в YAML: ``"Первая часть.\\nВторая часть."`` (именно
    в двойных кавычках -- тогда ``\\n`` распознаётся как перенос строки).
    Discord сам сохранит отступ под этой строкой, как под первой."""

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
    # bullet (по умолчанию) -- content-список рендерится настоящим
    # markdown-списком Discord (см. модуль-докстринг): точку и форму
    # вложенного маркера (обычно пустой кружок вместо кружка) рисует сам
    # Discord по своим правилам вложенности -- это его отрисовка, не наш
    # текстовый символ, и мы не можем задать конкретную форму (кружок/
    # квадрат) вместо неё, у Discord нет такой настройки.
    # none -- список без маркеров вообще, просто строки друг под другом.
    marker: Literal["bullet", "none"] = "bullet"
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
    # Начать с ЭТОГО раздела новую карточку (embed) в том же сообщении,
    # без смены цвета -- просто чтобы разбить один огромный embed на
    # несколько визуально отдельных блоков подряд (как у крупных ботов:
    # несколько карточек друг под другом одним сообщением). В отличие от
    # color, цвет остаётся общий (или свой, если задать color вместе с
    # new_card) -- только сам факт "новая карточка" включается отдельно.
    new_card: bool = False
    # Мелкий серый текст -- родная фича Discord "subtext" (добавлена в
    # июле 2024), не наша выдумка: строка с префиксом "-# " рисуется в
    # 13px и серым вместо обычных 16px белым. Именно так выглядят
    # приписки/дисклеймеры под правилами у крупных ботов. Работает
    # только по ОДНОЙ строке за раз (Discord требует "-# " в начале
    # КАЖДОЙ строки) -- поэтому, как и blockquote, применяется ко всему
    # блоку раздела целиком. Несовместимо с blockquote -- у Discord это
    # взаимоисключающие форматы начала строки (см. валидацию ниже).
    subtext: bool = False

    @model_validator(mode="after")
    def _blockquote_and_subtext_are_mutually_exclusive(self) -> "SectionSpec":
        if self.blockquote and self.subtext:
            raise ValueError(
                "blockquote и subtext нельзя сочетать в одном разделе -- у Discord это два разных "
                "формата начала строки ('> ' и '-# '), она распознаёт только один из них за раз."
            )
        return self

    def rendered_content(self) -> str:
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            # YAML-блоки "|" всегда добавляют один завершающий перенос
            # строки -- без rstrip между разделами накапливались бы
            # лишние пустые строки при склейке через "\n\n".join(...).
            return self.content.rstrip("\n")

        top_prefix = "- " if self.marker == "bullet" else ""
        sub_prefix = f"{_NESTED_INDENT}- " if self.marker == "bullet" else _NESTED_INDENT

        lines: list[str] = []
        for entry in self.content:
            if isinstance(entry, str):
                lines.append(f"{top_prefix}{entry}")
            else:
                lines.append(f"{top_prefix}{entry.text}")
                for sub in entry.items:
                    lines.append(f"{sub_prefix}{sub}")
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
        if self.subtext and block:
            # "-# " перед каждой строкой -- Discord распознаёт subtext
            # только в начале строки, на каждую строку заново.
            block = "\n".join(f"-# {line}" if line else "-#" for line in block.split("\n"))
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
        подряд склеиваются в один блок (``color=None``), а раздел со
        своим ``color`` ИЛИ с ``new_card=True`` образует отдельный блок,
        чтобы стать своим (следующим по счёту) embed'ом -- несколько
        карточек подряд одним сообщением вместо одной длинной "простыни".

        Отступ перед разделом ставится не всегда одинаково: настоящий
        Discord-заголовок (``heading`` 1/2/3, `#`/`##`/`###`) сам рисует
        отступ сверху -- лишняя пустая строка перед ним смотрится
        избыточно. А вот у "жирного" псевдозаголовка (``heading: 0``,
        по умолчанию) и у обычного текста собственного отступа нет --
        без пустой строки разделы слипаются друг с другом."""
        blocks: list[tuple[str, int | None]] = []
        running = ""

        def append_running(rendered: str, *, has_own_top_margin: bool) -> None:
            nonlocal running
            if not running:
                running = rendered
                return
            separator = "\n" if has_own_top_margin else "\n\n"
            running = f"{running}{separator}{rendered}"

        def flush() -> None:
            nonlocal running
            if running:
                blocks.append((running, None))
                running = ""

        if spec.description:
            running = spec.description.rstrip("\n")

        for section in spec.sections:
            if section.color is not None:
                # Свой цвет -- ВСЕГДА отдельная карточка (иначе Discord
                # не даёт покрасить кусок текста в другой цвет внутри
                # одной карточки).
                flush()
                blocks.append((section.rendered_block(), section.color))
                continue
            if section.new_card:
                # Явно попросили новую карточку без смены цвета -- просто
                # разбивка длинного embed'а, дальше текст снова копится
                # в НОВЫЙ running-блок общего (или дефолтного) цвета.
                flush()
            append_running(section.rendered_block(), has_own_top_margin=section.heading in (1, 2, 3))
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
