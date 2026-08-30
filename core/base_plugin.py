"""Единственный интерфейс, который реализует каждый плагин (ТЗ §3, §31, §45).

Плагин обнаруживается :class:`core.plugin_manager.PluginManager`
в файле ``plugins/<name>/plugin.py``, который обязан предоставить
модульную переменную ``PLUGIN_CLASS``, указывающую на подкласс
:class:`BasePlugin`::

    class WeatherPlugin(BasePlugin):
        meta = PluginMeta(name="weather", version="1.0.0")

        async def setup(self) -> None:
            self.ctx.add_command(weather_group)

    PLUGIN_CLASS = WeatherPlugin

Контракт жизненного цикла
--------------------------
``setup()``
    Регистрирует slash-команды, cog'и и подписки на event bus через
    ``self.ctx`` (никогда не трогайте ``self.ctx.bot`` напрямую для
    регистрации — это обходит систему учёта и ломает очистку при
    горячей перезагрузке). Не должен зависеть от подключения к шлюзу
    Discord (gateway).

``start()``
    Вызывается один раз после того, как бот получил событие
    ``on_ready`` (или сразу же при перезагрузке, если бот уже
    запущен). Здесь уже можно безопасно обращаться к Discord API и
    базе данных, запускать фоновые задачи через
    ``self.ctx.create_task`` и восстанавливать нужное состояние.

``stop()``
    Освобождает всё, что плагин получил *сам*, в обход хелперов
    ``self.ctx`` (например, свою собственную сессию aiohttp).
    Должен быть идемпотентным — PluginManager может вызвать его как
    часть отката (rollback), а затем снова вызвать ``setup``/``start``.
    Отслеживаемые ресурсы (cog'и, задачи, подписки на event bus)
    очищаются автоматически менеджером плагинов после возврата из
    ``stop()``, даже если ``stop()`` выбросил исключение.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.plugin_context import PluginContext


@dataclass(frozen=True)
class PluginMeta:
    """Метаданные плагина: имя, версия, зависимости и т.д. (ТЗ §31)."""

    name: str
    version: str
    description: str = ""
    author: str = "SkyHub Aviation"
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    requires_db: bool = True


class BasePlugin(ABC):
    meta: PluginMeta

    def __init__(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.log = ctx.get_logger()

    @abstractmethod
    async def setup(self) -> None:
        """Регистрирует команды/слушатели. Не должен требовать подключения к шлюзу."""

    async def start(self) -> None:  # noqa: B027 - метод намеренно необязателен
        return None

    async def stop(self) -> None:  # noqa: B027 - метод намеренно необязателен
        return None

    async def health(self) -> dict:
        return {"status": "ok"}

    def __repr__(self) -> str:  # pragma: no cover - только для удобства чтения
        return f"<Plugin {self.meta.name} v{self.meta.version}>"
