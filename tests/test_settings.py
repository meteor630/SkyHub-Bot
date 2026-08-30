"""Регрессионные тесты для config/settings.py.

Эти сценарии не ловятся остальным тестовым набором, потому что там
``Settings`` никогда не строится напрямую -- а именно на этом шаге бот
падал при реальном запуске (ТЗ §1, §24)."""
from __future__ import annotations

from pathlib import Path

from config.settings import PROJECT_ROOT, Settings


def _make_settings(monkeypatch, **extra_env: str) -> Settings:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    # _env_file=None -- не читать реальный .env проекта, использовать
    # только переменные окружения, заданные в этом тесте.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_blank_dev_guild_id_becomes_none(monkeypatch) -> None:
    settings = _make_settings(monkeypatch, DEV_GUILD_ID="")
    assert settings.dev_guild_id is None


def test_missing_dev_guild_id_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)
    settings = _make_settings(monkeypatch)
    assert settings.dev_guild_id is None


def test_numeric_dev_guild_id_parses_correctly(monkeypatch) -> None:
    settings = _make_settings(monkeypatch, DEV_GUILD_ID="123456789012345678")
    assert settings.dev_guild_id == 123456789012345678


def test_env_file_is_anchored_to_project_root() -> None:
    """``env_file`` должен быть абсолютным путём под ``PROJECT_ROOT``, а не
    относительным ``".env"`` -- иначе он резолвится относительно текущей
    рабочей директории процесса, и `python -m app`, запущенный не из
    корня проекта (другой cwd в systemd/cron/IDE), молча не находил
    секреты и падал с непонятной ошибкой валидации вместо явной подсказки."""
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()
    assert Path(env_file) == PROJECT_ROOT / ".env"
