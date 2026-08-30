"""Общий путь к хранилищу загруженных треков -- в отдельном модуле, чтобы
``plugin.py`` и ``commands.py`` могли оба на него ссылаться без
циклического импорта друг друга."""
from __future__ import annotations

from config.settings import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data" / "radio"
