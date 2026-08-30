"""Генераторы ID для связывания ошибок/запросов между консолью и Discord."""
from __future__ import annotations

import datetime as dt
import secrets


def new_error_id() -> str:
    """Идентификатор в формате ``ERR-20260829-4f9a2c``."""
    date = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    return f"ERR-{date}-{secrets.token_hex(3)}"


def new_request_id() -> str:
    return secrets.token_hex(6)
