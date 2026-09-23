"""Тесты выбора картинки для превью в логе удалённого сообщения
(``plugins/deleted_messages/plugin.py::_first_image_url``) -- раньше
вложения показывались только ссылкой текстом, теперь первое подходящее
изображение ещё и рендерится настоящей картинкой (``embed.set_image``)."""
from __future__ import annotations

from plugins.deleted_messages.plugin import _first_image_url


def test_finds_first_image_among_mixed_attachments() -> None:
    urls = [
        "https://cdn.discordapp.com/attachments/1/2/document.pdf",
        "https://cdn.discordapp.com/attachments/1/2/photo.png?ex=1&is=2&hm=3",
        "https://cdn.discordapp.com/attachments/1/2/clip.gif",
    ]
    assert _first_image_url(urls) == urls[1]


def test_ignores_query_string_when_checking_extension() -> None:
    urls = ["https://cdn.discordapp.com/attachments/1/2/E170.png?ex=abc&is=def&hm=ghi"]
    assert _first_image_url(urls) == urls[0]


def test_returns_none_when_no_image_attachment() -> None:
    urls = ["https://cdn.discordapp.com/attachments/1/2/track.mp3", "https://cdn.discordapp.com/attachments/1/2/notes.txt"]
    assert _first_image_url(urls) is None


def test_returns_none_for_empty_list() -> None:
    assert _first_image_url([]) is None


def test_is_case_insensitive_for_extension() -> None:
    urls = ["https://cdn.discordapp.com/attachments/1/2/PHOTO.JPG"]
    assert _first_image_url(urls) == urls[0]
