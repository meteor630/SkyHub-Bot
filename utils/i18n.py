"""Минимальный загрузчик локализации (ТЗ §42).

Строки хранятся в ``locales/<lang>.json`` в виде плоских ключей с
точками (``"voice.locked": "Комната закрыта"``). ``en`` всегда
загружается как запасной слой, чтобы отсутствующий перевод в ``ru``
(или в будущих ``de``, ``fr``, ``es``) не ронял команду, а мягко
деградировал.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("skyhub.i18n")

DEFAULT_LOCALE = "ru"
FALLBACK_LOCALE = "en"


class I18n:
    def __init__(self, locales_dir: Path, default_locale: str = DEFAULT_LOCALE) -> None:
        self._dir = locales_dir
        self._default = default_locale
        self._catalogs: dict[str, dict[str, str]] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._dir.exists():
            logger.warning("Директория локализации %s не существует", self._dir)
            return
        for path in self._dir.glob("*.json"):
            try:
                self._catalogs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.exception("Не удалось разобрать файл локализации %s", path)

    def available_locales(self) -> list[str]:
        return sorted(self._catalogs.keys())

    def t(self, key: str, locale: str | None = None, **kwargs) -> str:
        locale = locale or self._default
        text = (
            self._catalogs.get(locale, {}).get(key)
            or self._catalogs.get(FALLBACK_LOCALE, {}).get(key)
            or key
        )
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                return text
        return text
