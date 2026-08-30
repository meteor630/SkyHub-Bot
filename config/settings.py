"""Настройки, читаемые из окружения (ТЗ §1, §24, §35).

Секреты (токен, URL базы данных) приходят *только* из переменных
окружения / ``.env`` через ``pydantic-settings`` -- никогда из
``config.yaml`` и никогда не хардкодятся. ``config.yaml`` хранит всё,
что не является секретом: ID каналов, ID ролей, переключатели плагинов,
флаги функциональности.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # env_file привязан к PROJECT_ROOT, а не к текущей рабочей директории:
    # иначе `python -m app`, запущенный не из корня проекта (другой cwd в
    # systemd/cron/IDE), молча не находил .env и падал с непонятной
    # ошибкой "Field required" вместо явной подсказки, в чём дело.
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    discord_token: str = Field(alias="DISCORD_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")

    dev_guild_id: int | None = Field(default=None, alias="DEV_GUILD_ID")
    config_path: Path = Field(default=PROJECT_ROOT / "config" / "config.yaml", alias="CONFIG_PATH")
    locales_dir: Path = Field(default=PROJECT_ROOT / "locales", alias="LOCALES_DIR")
    plugins_dir: Path = Field(default=PROJECT_ROOT / "plugins", alias="PLUGINS_DIR")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: Path = Field(default=PROJECT_ROOT / "logs", alias="LOG_DIR")
    log_json: bool = Field(default=True, alias="LOG_JSON")

    default_locale: str = Field(default="ru", alias="DEFAULT_LOCALE")

    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    @field_validator("dev_guild_id", mode="before")
    @classmethod
    def _blank_dev_guild_id_is_none(cls, value: object) -> object:
        # .env.example документирует DEV_GUILD_ID как "оставьте пустым,
        # чтобы синхронизировать только глобально" -- но пустая строка из
        # .env, дойдя до pydantic как значение поля int | None, до этой
        # проверки падала с ValidationError вместо того, чтобы стать None.
        # Именно это ломало запуск у любого, кто просто не заполнил это
        # необязательное поле, как и советует инструкция.
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
