from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.message_service import MessageRenderer, build_message_spec
from utils.text import split_text


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
    assert spec.sections[1].rendered_value() == "• Каналы\n• Voice"


def test_invalid_spec_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        build_message_spec({"media": {"type": "not-a-real-type", "url": "https://example.com"}})


def test_renderer_produces_single_embed_for_small_message() -> None:
    spec = build_message_spec({"title": "Hi", "description": "short text"})
    embeds = MessageRenderer().render(spec)
    assert len(embeds) == 1
    assert embeds[0].title == "Hi"
    assert embeds[0].description == "short text"


def test_renderer_paginates_when_many_sections_exceed_field_cap() -> None:
    sections = [{"title": f"Section {i}", "content": "text"} for i in range(25)]
    spec = build_message_spec({"title": "Big", "sections": sections})
    embeds = MessageRenderer().render(spec)

    assert len(embeds) > 1
    total_fields = sum(len(e.fields) for e in embeds)
    assert total_fields == 25
    # подпись с нумерацией страниц появляется только при реальном разбиении
    assert "MESSAGE 1/" in embeds[0].footer.text


def test_author_hidden_on_followup_pages_when_configured() -> None:
    sections = [{"title": f"Section {i}", "content": "text"} for i in range(25)]
    spec = build_message_spec(
        {"author": {"enabled": True, "name": "SkyHub"}, "sections": sections, "show_author_first_message_only": True}
    )
    embeds = MessageRenderer().render(spec)
    assert len(embeds) > 1
    assert embeds[0].author.name == "SkyHub"
    assert embeds[1].author.name is None


def test_split_text_prefers_paragraph_breaks() -> None:
    text = "A" * 50 + "\n\n" + "B" * 50
    chunks = split_text(text, 60)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 50
    assert chunks[1] == "B" * 50


def test_split_text_noop_when_under_limit() -> None:
    assert split_text("short", 100) == ["short"]
