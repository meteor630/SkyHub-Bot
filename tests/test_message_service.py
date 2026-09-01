from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.message_service import DEFAULT_COLOR, MessageRenderer, build_message_spec
from utils.text import DISCORD_EMBED_TOTAL_LIMIT, split_text


def test_build_message_spec_from_plain_dict() -> None:
    spec = build_message_spec(
        {
            "title": "Добро пожаловать!",
            "author": {"enabled": True, "name": "SkyHub Aviation"},
            "sections": [
                {"title": "Правила", "content": "Текст правил"},
                {"title": "Навигация", "content": ["Каналы", "Voice"]},
            ],
        }
    )
    assert spec.title == "Добро пожаловать!"
    assert len(spec.sections) == 2
    assert spec.sections[1].rendered_content() == "- Каналы\n- Voice"


def test_invalid_spec_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        build_message_spec({"media": {"type": "not-a-real-type", "url": "https://example.com"}})


# -- настоящий markdown-список Discord (marker: bullet/none) и вложенные --

def test_marker_bullet_renders_native_dash_list() -> None:
    """content-список по умолчанию рендерится настоящим markdown-списком
    Discord ("- пункт") -- НЕ текстовым символом "•". Только так Discord
    сам рисует крупную точку списка и держит отступ у переноса строки
    внутри пункта (см. докстринг модуля -- сравнение со скриншотом)."""
    spec = build_message_spec({"sections": [{"content": ["Пункт"], "marker": "bullet"}]})
    assert spec.sections[0].rendered_content() == "- Пункт"


def test_marker_none_renders_plain_lines_without_dash() -> None:
    spec = build_message_spec({"sections": [{"content": ["Пункт"], "marker": "none"}]})
    assert spec.sections[0].rendered_content() == "Пункт"


def test_nested_items_use_two_space_indent_dash() -> None:
    """Вложенный пункт -- "  - подпункт" (отступ ровно 2 пробела перед
    "-") -- это требование парсера списков Discord, не наш выбор
    оформления. Форму самой точки (кружок/пустой кружок) для вложенного
    уровня рисует сам Discord по своим правилам вложенности."""
    spec = build_message_spec(
        {
            "sections": [
                {
                    "content": [
                        "Обычный пункт",
                        {"text": "Пункт со вложенными", "items": ["Подпункт А", "Подпункт Б"]},
                    ]
                }
            ]
        }
    )
    assert spec.sections[0].rendered_content() == (
        "- Обычный пункт\n- Пункт со вложенными\n  - Подпункт А\n  - Подпункт Б"
    )


def test_manual_line_break_inside_one_item_keeps_it_a_single_bullet() -> None:
    """Перенос строки ВНУТРИ одного пункта (не новый пункт списка) --
    просто "\\n" в тексте самого пункта; наружу это идёт как есть, без
    доп. префикса у второй строки -- отступ у неё держит сам Discord
    (это блочный элемент списка, а не наш текстовый трюк)."""
    spec = build_message_spec({"sections": [{"content": ["Первая часть.\nВторая часть."]}]})
    assert spec.sections[0].rendered_content() == "- Первая часть.\nВторая часть."


# -- заголовки разного размера (0 = жирным, 1/2/3 = #/##/###) --------------

def test_section_heading_zero_renders_bold_not_markdown_header() -> None:
    spec = build_message_spec({"sections": [{"title": "Обычный", "content": "текст", "heading": 0}]})
    assert spec.sections[0].rendered_block() == "**Обычный**\nтекст"


@pytest.mark.parametrize("level,prefix", [(1, "# "), (2, "## "), (3, "### ")])
def test_section_heading_levels_use_markdown_headers(level: int, prefix: str) -> None:
    spec = build_message_spec({"sections": [{"title": "Заголовок", "content": "текст", "heading": level}]})
    assert spec.sections[0].rendered_block() == f"{prefix}Заголовок\nтекст"


def test_mixed_heading_sizes_appear_in_authored_order() -> None:
    """Ключевой сценарий запроса: большой/маленький заголовки можно
    свободно чередовать в одном сообщении, порядок не переставляется.
    Разделы идут подряд без пустой строки между ними -- одна пустая
    строка в Discord визуально выглядит куда просторнее, чем в обычном
    тексте, а сам заголовок и так чётко отделяет разделы друг от друга."""
    spec = build_message_spec(
        {
            "sections": [
                {"title": "Большой", "content": "1", "heading": 1},
                {"title": "Маленький", "content": "2", "heading": 3},
                {"title": "Снова большой", "content": "3", "heading": 1},
            ]
        }
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    description = pages[0][0].description
    assert description == "# Большой\n1\n### Маленький\n2\n# Снова большой\n3"


def test_bold_heading_zero_gets_blank_line_before_it_since_it_has_no_own_margin() -> None:
    """Регрессия: heading 1/2/3 (#/##/###) рисует отступ сверху сам, а
    heading 0 (просто жирным) -- нет, поэтому перед НИМ (и перед ним
    самим, если следом идёт ещё один heading 0/обычный текст) нужна явная
    пустая строка, иначе он слипается с предыдущим текстом."""
    spec = build_message_spec(
        {
            "description": "Вступление",
            "sections": [
                {"title": "Жирный", "content": "1", "heading": 0},
                {"title": "Настоящий", "content": "2", "heading": 3},
            ],
        }
    )
    pages = MessageRenderer().render(spec)
    description = pages[0][0].description
    # Перед "**Жирный**" (heading 0, своего отступа нет) -- пустая строка.
    assert description.startswith("Вступление\n\n**Жирный**\n1")
    # Перед "### Настоящий" (heading 3, отступ рисует сам Discord) --
    # без лишней пустой строки, иначе получится двойной отступ.
    assert "1\n### Настоящий" in description


# -- вложенная цитата (сноска ВНУТРИ общей карточки, серая полоска) -------

def test_blockquote_section_prefixes_every_line() -> None:
    spec = build_message_spec(
        {"sections": [{"title": "Заметка", "content": "строка 1\nстрока 2", "blockquote": True}]}
    )
    assert spec.sections[0].rendered_block() == "> **Заметка**\n> строка 1\n> строка 2"


def test_blockquote_section_stays_in_same_embed_as_main_text() -> None:
    """В отличие от color, blockquote НЕ создаёт отдельный embed -- полоска
    остаётся общей на всё сообщение, а не отдельной у сноски."""
    spec = build_message_spec(
        {
            "description": "Основной текст",
            "sections": [{"title": "Сноска", "content": "детали", "blockquote": True}],
        }
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    embeds = pages[0]
    assert len(embeds) == 1  # один embed, не два
    assert "> **Сноска**\n> детали" in embeds[0].description


# -- цветные врезки-сноски (раздел со своим color -> отдельный embed) ------

def test_section_with_color_becomes_its_own_embed() -> None:
    spec = build_message_spec(
        {
            "description": "Основной текст",
            "sections": [{"title": "Важно", "content": "врезка", "color": 0xE74C3C}],
        }
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    embeds = pages[0]
    assert len(embeds) == 2
    assert embeds[0].description == "Основной текст"
    assert embeds[0].color.value == DEFAULT_COLOR
    assert embeds[1].description == "**Важно**\nврезка"
    assert embeds[1].color.value == 0xE74C3C


def test_new_card_splits_without_color_but_keeps_shared_default_color() -> None:
    """new_card -- та же "новая карточка", что и у color, но БЕЗ смены
    цвета: обе карточки красятся общим цветом сообщения (DEFAULT_COLOR),
    просто текст физически разбит на два embed'а подряд, чтобы одно
    сообщение не выглядело гигантской "простынёй"."""
    spec = build_message_spec(
        {
            "sections": [
                {"title": "Первая часть", "content": "текст 1"},
                {"title": "Вторая часть", "content": "текст 2", "new_card": True},
            ]
        }
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    embeds = pages[0]
    assert len(embeds) == 2
    assert "Первая часть" in embeds[0].description and "Вторая часть" not in embeds[0].description
    assert "Вторая часть" in embeds[1].description
    assert embeds[0].color.value == DEFAULT_COLOR
    assert embeds[1].color.value == DEFAULT_COLOR


def test_new_card_can_combine_with_own_color() -> None:
    spec = build_message_spec(
        {"sections": [{"content": "1"}, {"content": "2", "new_card": True, "color": 0xE74C3C}]}
    )
    pages = MessageRenderer().render(spec)
    embeds = pages[0]
    assert len(embeds) == 2
    assert embeds[1].color.value == 0xE74C3C


def test_callout_between_two_running_sections_splits_into_three_embeds() -> None:
    spec = build_message_spec(
        {
            "sections": [
                {"title": "До", "content": "текст до"},
                {"title": "Врезка", "content": "текст врезки", "color": 0x2ECC71},
                {"title": "После", "content": "текст после"},
            ]
        }
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    embeds = pages[0]
    assert len(embeds) == 3
    assert "До" in embeds[0].description and "После" not in embeds[0].description
    assert embeds[1].color.value == 0x2ECC71
    assert "После" in embeds[2].description


# -- базовый рендеринг / пагинация между сообщениями ------------------------

def test_renderer_produces_single_page_for_small_message() -> None:
    spec = build_message_spec({"title": "Hi", "description": "short text"})
    pages = MessageRenderer().render(spec)
    assert len(pages) == 1
    assert len(pages[0]) == 1
    assert pages[0][0].title == "Hi"
    assert pages[0][0].description == "short text"


def test_renderer_paginates_across_messages_when_content_too_long() -> None:
    # Каждый раздел -- отдельный "жирный" блок; суммарно далеко за лимитом
    # embed'а на одно сообщение (DISCORD_EMBED_TOTAL_LIMIT), поэтому
    # рендерер обязан уйти на вторую страницу (второе сообщение).
    long_content = "x" * 3000
    sections = [{"title": f"Раздел {i}", "content": long_content} for i in range(3)]
    spec = build_message_spec({"title": "Big", "sections": sections})
    pages = MessageRenderer().render(spec)

    assert len(pages) > 1
    for page in pages:
        total_chars = sum(len(e.description or "") for e in page)
        assert total_chars <= DISCORD_EMBED_TOTAL_LIMIT
    # подпись с нумерацией страниц появляется только при реальном разбиении
    assert "MESSAGE 1/" in pages[0][-1].footer.text


def test_author_hidden_on_followup_pages_when_configured() -> None:
    long_content = "x" * 3000
    sections = [{"title": f"Раздел {i}", "content": long_content} for i in range(3)]
    spec = build_message_spec(
        {"author": {"enabled": True, "name": "SkyHub"}, "sections": sections, "show_author_first_message_only": True}
    )
    pages = MessageRenderer().render(spec)
    assert len(pages) > 1
    assert pages[0][0].author.name == "SkyHub"
    assert pages[1][0].author.name is None


def test_split_text_prefers_paragraph_breaks() -> None:
    text = "A" * 50 + "\n\n" + "B" * 50
    chunks = split_text(text, 60)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 50
    assert chunks[1] == "B" * 50


def test_split_text_noop_when_under_limit() -> None:
    assert split_text("short", 100) == ["short"]
