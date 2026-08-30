"""Структурированное + красивое консольное логирование (ТЗ §22, §43).

В корневой логгер устанавливаются два обработчика:

* Консольный обработчик на базе :class:`PrettyConsoleFormatter`,
  выводящий строки вида::

      17:42:31 │ INFO  │ VOICE        │ Created temporary channel "..."

* Ротируемый файловый обработчик JSON-строк (по одному объекту на
  строку), несущий все поля корреляции (timestamp, guild_id,
  channel_id, user_id, plugin, event, request_id), чтобы по
  ``error_id`` из embed'а ошибки в Discord можно было сразу найти
  точную строку лога, которая её породила.

Замечание про имя пакета: ТЗ предлагает пакет верхнего уровня
``logging/``, но это перекрыло бы стандартный модуль ``logging`` для
каждого ``import logging`` в проекте, как только эта директория
попадёт в ``sys.path`` -- настоящая мина замедленного действия. Мы
сохраняем ту же ответственность под именем ``logging_config/`` (ТЗ §2
явно разрешает переименование при наличии архитектурной причины).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path

from core import context as request_context

RESET = "\x1b[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\x1b[90m",
    logging.INFO: "\x1b[36m",
    logging.WARNING: "\x1b[33m",
    logging.ERROR: "\x1b[31m",
    logging.CRITICAL: "\x1b[41m\x1b[97m",
}
LEVEL_LABELS = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO ",
    logging.WARNING: "WARN ",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRIT ",
}


class RequestContextFilter(logging.Filter):
    """Заполняет plugin/event/guild_id/... из активного RequestContext
    (или из собственного `extra` LoggerAdapter'а плагина), если эти поля
    ещё не заданы."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.current()
        for field in ("plugin", "event", "guild_id", "channel_id", "user_id", "request_id"):
            if getattr(record, field, None) is None:
                setattr(record, field, getattr(ctx, field, None) if ctx else None)
        return True


class PrettyConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        time_str = self.formatTime(record, "%H:%M:%S")
        level_color = LEVEL_COLORS.get(record.levelno, "")
        level_label = LEVEL_LABELS.get(record.levelno, record.levelname[:5].ljust(5))
        component = str(getattr(record, "plugin", None) or record.name.split(".")[-1]).upper()[:13].ljust(13)
        message = record.getMessage()
        line = f"{time_str} │ {level_color}{level_label}{RESET} │ {component} │ {message}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class JsonFileFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "plugin": getattr(record, "plugin", None),
            "event": getattr(record, "event", None),
            "guild_id": getattr(record, "guild_id", None),
            "channel_id": getattr(record, "channel_id", None),
            "user_id": getattr(record, "user_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, level: str = "INFO", log_dir: Path | None = None, json_file: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    context_filter = RequestContextFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(PrettyConsoleFormatter())
    console_handler.addFilter(context_filter)
    root.addHandler(console_handler)

    if json_file and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "skyhub.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFileFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)

    # сам discord.py довольно многословен на уровне INFO; держим WARNING,
    # если явно не отлаживаем работу шлюза.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
