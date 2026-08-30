"""Хелперы для текста: безопасное усечение и разбиение сообщений Discord (ТЗ §9)."""
from __future__ import annotations

DISCORD_MESSAGE_LIMIT = 2000
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_TOTAL_LIMIT = 6000


def truncate(text: str, limit: int, *, suffix: str = "…") -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


def split_text(text: str, limit: int) -> list[str]:
    """Разбивает ``text`` на части не длиннее ``limit`` символов, отдавая
    предпочтение разрывам абзацев и строк перед разрезанием слов
    пополам, чтобы длинные объявления оставались читаемыми при разбиении
    на несколько сообщений Discord (ТЗ §9)."""
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n ")
    if remaining:
        chunks.append(remaining)
    return chunks


def paginate_label(index: int, total: int) -> str:
    return f"MESSAGE {index}/{total}"
