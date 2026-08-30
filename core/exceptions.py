"""Иерархия собственных исключений, используемая по всему боту SkyHub.

Централизация исключений позволяет ErrorHandler и консоли различать
их по типу вместо разбора текста строк, а плагинам -- выбрасывать
предсказуемые ошибки, которые ядро умеет красиво отобразить.
"""
from __future__ import annotations


class SkyHubError(Exception):
    """Базовый класс для всех специфичных для SkyHub ошибок."""


class PluginError(SkyHubError):
    """Выбрасывается при сбоях жизненного цикла плагина (setup/start/stop/reload)."""

    def __init__(self, plugin_name: str, message: str, *, original: BaseException | None = None) -> None:
        self.plugin_name = plugin_name
        self.original = original
        super().__init__(f"[{plugin_name}] {message}")


class PluginLoadError(PluginError):
    """Выбрасывается, если модуль плагина не удалось импортировать или создать его экземпляр."""


class PluginDependencyError(PluginError):
    """Выбрасывается, если объявленные зависимости плагина не могут быть удовлетворены."""


class PluginNotFoundError(SkyHubError):
    """Выбрасывается, если команда CLI/консоли ссылается на неизвестный плагин."""


class PluginAlreadyLoadedError(SkyHubError):
    """Выбрасывается при попытке загрузить плагин, который уже активен."""


class ConfigurationError(SkyHubError):
    """Выбрасывается, если конфигурация (env, YAML) отсутствует или некорректна."""


class PermissionDeniedError(SkyHubError):
    """Выбрасывается системой прав доступа, если пользователю не хватает требуемой роли."""

    def __init__(self, required: str, actual: str | None = None) -> None:
        self.required = required
        self.actual = actual
        super().__init__(f"Требуется роль >= {required} (текущая: {actual or 'неизвестно'})")


class VoiceChannelError(SkyHubError):
    """Выбрасывается при недопустимых операциях над временным голосовым каналом."""
