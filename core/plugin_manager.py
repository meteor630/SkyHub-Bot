"""Обнаружение плагинов, разрешение зависимостей и безопасная горячая
перезагрузка (ТЗ §3-5, §30-32).

Контракт плагина см. в :mod:`core.base_plugin`, а то, к чему плагин
имеет доступ — в :mod:`core.plugin_context`. Этот модуль — единственное
место, где создаются и уничтожаются экземпляры плагинов.

Алгоритм горячей перезагрузки (ТЗ §5)
--------------------------------------
``reload(name)`` никогда не делает наивный ``importlib.reload``.
Вместо этого:

1. **Фаза импорта** — удаляем из ``sys.modules`` все записи под
   ``plugins.<name>`` и заново импортируем ``plugins.<name>.plugin``
   "с нуля". Любая ошибка импорта/синтаксиса перехватывается *до*
   того, как мы хоть как-то тронули работающий плагин — поэтому
   опечатка в файле, который вы редактируете, никогда не положит
   старую рабочую версию.
2. **Фаза конструирования** — создаём экземпляр нового класса плагина.
   Исключение в конструкторе точно так же полностью изолировано.
3. **Фаза замены** — только теперь мы останавливаем старый экземпляр
   (отменяем его задачи, отписываем его слушателей event bus, удаляем
   его cog'и/команды) и поднимаем новый (`setup()` + `start()`).
   Если шаг 3 не удался — откатываемся, заново запуская `setup()`/
   `start()` *старого* экземпляра со свежим контекстом, чтобы плагин
   оказался в том же состоянии, как будто перезагрузки и не было.
"""
from __future__ import annotations

import dataclasses
import enum
import importlib
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.base_plugin import BasePlugin, PluginMeta
from core.events import PluginLoaded, PluginReloaded
from core.exceptions import (
    PluginDependencyError,
    PluginLoadError,
    PluginNotFoundError,
)
from core.plugin_context import PluginContext

if TYPE_CHECKING:
    from discord.ext import commands

    from core.error_handler import ErrorHandler
    from core.event_bus import EventBus
    from core.permissions import PermissionService
    from database.database import Database
    from utils.cache import TTLCache
    from utils.i18n import I18n

logger = logging.getLogger("skyhub.plugin_manager")


class PluginStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    LOADING = "LOADING"
    DISABLED = "DISABLED"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"


@dataclasses.dataclass
class PluginRecord:
    """Текущее состояние одного плагина внутри PluginManager."""

    name: str
    module_path: str
    plugin_class: type[BasePlugin] | None = None
    instance: BasePlugin | None = None
    ctx: PluginContext | None = None
    status: PluginStatus = PluginStatus.DISABLED
    last_error: str | None = None
    loaded_at: float | None = None

    @property
    def meta(self) -> PluginMeta | None:
        if self.plugin_class is not None:
            return self.plugin_class.meta
        if self.instance is not None:
            return self.instance.meta
        return None


class PluginManager:
    def __init__(
        self,
        *,
        bot: commands.Bot,
        event_bus: EventBus,
        db: Database,
        permissions: PermissionService,
        error_handler: ErrorHandler,
        i18n: I18n,
        cache: TTLCache,
        global_config: dict[str, Any],
        plugins_root: Path,
    ) -> None:
        self.bot = bot
        self.event_bus = event_bus
        self.db = db
        self.permissions = permissions
        self.error_handler = error_handler
        self.i18n = i18n
        self.cache = cache
        self.global_config = global_config
        self.plugins_root = plugins_root
        self._plugins: dict[str, PluginRecord] = {}
        self._bot_ready = False

    # -- обнаружение плагинов (ТЗ §30) ------------------------------------

    def discover(self) -> list[str]:
        """Находит все папки в plugins/, содержащие plugin.py."""
        if not self.plugins_root.exists():
            return []
        return sorted(
            entry.name
            for entry in self.plugins_root.iterdir()
            if entry.is_dir() and not entry.name.startswith("_") and (entry / "plugin.py").exists()
        )

    def _plugin_enabled_in_config(self, name: str) -> bool:
        entry = self.global_config.get("plugins", {}).get(name, {})
        return bool(entry.get("enabled", True))

    def _plugin_config(self, name: str) -> dict[str, Any]:
        return dict(self.global_config.get("plugins", {}).get(name, {}))

    # -- вспомогательные функции импорта -----------------------------------

    @staticmethod
    def _module_path(name: str) -> str:
        return f"plugins.{name}.plugin"

    @staticmethod
    def _purge_modules(name: str) -> None:
        """Удаляет из кэша импорта (sys.modules) все подмодули плагина,
        чтобы следующий import действительно перечитал файлы с диска."""
        prefix = f"plugins.{name}"
        for mod_name in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
            del sys.modules[mod_name]

    def _import_plugin_class(self, name: str) -> type[BasePlugin]:
        try:
            module = importlib.import_module(self._module_path(name))
        except Exception as exc:
            raise PluginLoadError(name, f"ошибка импорта: {exc}", original=exc) from exc

        plugin_class = getattr(module, "PLUGIN_CLASS", None)
        if not (isinstance(plugin_class, type) and issubclass(plugin_class, BasePlugin)):
            raise PluginLoadError(name, "plugin.py должен определять PLUGIN_CLASS: type[BasePlugin]")
        return plugin_class

    # -- граф зависимостей (ТЗ §32) ----------------------------------------

    def _topological_order(self, names: list[str], classes: dict[str, type[BasePlugin]]) -> list[str]:
        """Сортирует плагины так, чтобы зависимости загружались раньше зависящих от них."""
        order: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(n: str) -> None:
            if n in visited or n not in classes:
                return
            if n in visiting:
                raise PluginDependencyError(n, f"циклическая зависимость с участием '{n}'")
            visiting.add(n)
            for dep in classes[n].meta.dependencies:
                visit(dep)
            visiting.discard(n)
            visited.add(n)
            order.append(n)

        for n in names:
            visit(n)
        return order

    def _dependencies_satisfied(self, plugin_class: type[BasePlugin]) -> tuple[bool, str | None]:
        for dep in plugin_class.meta.dependencies:
            dep_record = self._plugins.get(dep)
            if dep_record is None or dep_record.status != PluginStatus.ONLINE:
                return False, dep
        return True, None

    # -- запуск плагинов ------------------------------------------------------

    def _new_context(self, name: str) -> PluginContext:
        return PluginContext(
            plugin_name=name,
            bot=self.bot,
            event_bus=self.event_bus,
            db=self.db,
            config=self._plugin_config(name),
            global_config=self.global_config,
            permissions=self.permissions,
            error_handler=self.error_handler,
            i18n=self.i18n,
            cache=self.cache,
        )

    async def load_all(self) -> None:
        """Загружает все обнаруженные и включённые плагины в правильном порядке."""
        names = self.discover()
        classes: dict[str, type[BasePlugin]] = {}
        for name in names:
            record = self._plugins.setdefault(name, PluginRecord(name=name, module_path=self._module_path(name)))
            if not self._plugin_enabled_in_config(name):
                record.status = PluginStatus.DISABLED
                continue
            try:
                classes[name] = self._import_plugin_class(name)
                record.plugin_class = classes[name]
            except PluginLoadError as exc:
                record.status = PluginStatus.ERROR
                record.last_error = str(exc)
                logger.error("Не удалось импортировать плагин '%s': %s", name, exc)

        try:
            order = self._topological_order(list(classes.keys()), classes)
        except PluginDependencyError as exc:
            logger.error("Ошибка в графе зависимостей: %s", exc)
            order = list(classes.keys())

        for name in order:
            await self._load_one(name, classes[name])

    async def _load_one(self, name: str, plugin_class: type[BasePlugin]) -> None:
        record = self._plugins[name]
        ok, missing_dep = self._dependencies_satisfied(plugin_class)
        if not ok:
            record.status = PluginStatus.BLOCKED
            record.last_error = f"отсутствует зависимость: {missing_dep}"
            logger.warning("Плагин '%s' заблокирован: отсутствует зависимость '%s'", name, missing_dep)
            return

        record.status = PluginStatus.LOADING
        ctx = self._new_context(name)
        instance = plugin_class(ctx)
        try:
            await instance.setup()
            if self._bot_ready:
                await instance.start()
        except Exception as exc:  # noqa: BLE001
            await self._safe_release(ctx)
            error_id = await self.error_handler.handle(exc, plugin=name, event="load")
            record.status = PluginStatus.ERROR
            record.last_error = f"{type(exc).__name__}: {exc} (error_id={error_id})"
            logger.error("Плагин '%s' не удалось загрузить (error_id=%s)", name, error_id)
            return

        record.plugin_class = plugin_class
        record.instance = instance
        record.ctx = ctx
        record.status = PluginStatus.ONLINE
        record.loaded_at = time.time()
        record.last_error = None
        self.event_bus.emit(PluginLoaded(plugin=name, version=plugin_class.meta.version))
        logger.info("Плагин загружен: %s v%s", name, plugin_class.meta.version)

    async def start_all(self) -> None:
        """Запускает ``start()`` у всех уже загруженных плагинов после подключения к шлюзу."""
        self._bot_ready = True
        for record in list(self._plugins.values()):
            if record.status is PluginStatus.ONLINE and record.instance is not None:
                try:
                    await record.instance.start()
                except Exception as exc:  # noqa: BLE001
                    error_id = await self.error_handler.handle(exc, plugin=record.name, event="start")
                    record.status = PluginStatus.ERROR
                    record.last_error = f"ошибка запуска (error_id={error_id})"

    async def _safe_release(self, ctx: PluginContext) -> None:
        try:
            await ctx.release()
        except Exception:
            logger.exception("Ошибка при освобождении контекста плагина '%s'", ctx.plugin_name)

    async def _teardown(self, record: PluginRecord) -> None:
        """Останавливает плагин и освобождает все отслеживаемые ресурсы."""
        if record.instance is not None:
            try:
                await record.instance.stop()
            except Exception:
                logger.exception("Плагин '%s' выбросил исключение внутри stop()", record.name)
        if record.ctx is not None:
            await self._safe_release(record.ctx)
        record.instance = None
        record.ctx = None

    # -- публичный API управления (ТЗ §4, §40) ----------------------------

    async def unload(self, name: str) -> None:
        record = self._plugins.get(name)
        if record is None:
            raise PluginNotFoundError(name)
        if record.instance is None:
            record.status = PluginStatus.DISABLED
            return
        await self._teardown(record)
        record.status = PluginStatus.DISABLED

    async def enable(self, name: str) -> None:
        """Загружает (или включает заново) плагин по имени. В отличие от
        :meth:`reload`, не требует, чтобы плагин уже был обнаружен/загружен —
        можно безопасно вызывать для папки плагина, которая только что
        появилась на диске (ТЗ §30)."""
        record = self._plugins.get(name)
        if record is not None and record.status is PluginStatus.ONLINE:
            return
        if record is None:
            record = PluginRecord(name=name, module_path=self._module_path(name))
            self._plugins[name] = record

        self._purge_modules(name)
        plugin_class = self._import_plugin_class(name)
        await self._load_one(name, plugin_class)
        if record.status not in (PluginStatus.ONLINE, PluginStatus.BLOCKED):
            raise PluginLoadError(name, record.last_error or "не удалось включить плагин")

    async def disable(self, name: str) -> None:
        await self.unload(name)

    async def restart(self, name: str) -> None:
        """Останавливает и снова запускает плагин, используя код, уже
        находящийся в памяти (без повторного импорта с диска)."""
        record = self._plugins.get(name)
        if record is None or record.plugin_class is None:
            raise PluginNotFoundError(name)
        plugin_class = record.plugin_class
        await self.unload(name)
        await self._load_one(name, plugin_class)

    async def reload(self, name: str) -> None:
        """Безопасная горячая перезагрузка плагина. См. описание алгоритма
        в докстринге модуля."""
        record = self._plugins.get(name)
        if record is None:
            raise PluginNotFoundError(name)

        old_instance = record.instance

        # Фаза 1: импортируем и конструируем новый код, не трогая старый.
        self._purge_modules(name)
        try:
            new_class = self._import_plugin_class(name)
        except PluginLoadError as exc:
            record.last_error = str(exc)
            logger.error("Перезагрузка '%s' прервана на этапе импорта: %s", name, exc)
            raise

        new_ctx = self._new_context(name)
        try:
            new_instance = new_class(new_ctx)
        except Exception as exc:
            logger.error("Перезагрузка '%s' прервана: исключение в конструкторе: %s", name, exc)
            raise PluginLoadError(name, f"исключение в конструкторе: {exc}", original=exc) from exc

        # Фаза 2: замена -- останавливаем старый, поднимаем новый,
        # откатываемся при неудаче.
        if old_instance is not None:
            await self._teardown(record)

        try:
            await new_instance.setup()
            if self._bot_ready:
                await new_instance.start()
        except Exception as exc:
            error_id = await self.error_handler.handle(exc, plugin=name, event="reload")
            await self._safe_release(new_ctx)
            logger.error("Перезагрузка '%s' не удалась (error_id=%s); пробуем откат", name, error_id)

            if old_instance is not None:
                rollback_ctx = self._new_context(name)
                old_instance.ctx = rollback_ctx
                try:
                    await old_instance.setup()
                    if self._bot_ready:
                        await old_instance.start()
                    record.instance = old_instance
                    record.ctx = rollback_ctx
                    record.status = PluginStatus.ONLINE
                    record.last_error = f"перезагрузка не удалась, выполнен откат к прошлой версии (error_id={error_id})"
                    logger.warning("Плагин '%s' откачен к прошлой версии после неудачной перезагрузки", name)
                except Exception:  # noqa: BLE001
                    record.status = PluginStatus.ERROR
                    record.last_error = f"перезагрузка И откат не удались (error_id={error_id})"
                    logger.critical("Откат плагина '%s' тоже не удался -- плагин теперь offline", name)
            else:
                record.status = PluginStatus.ERROR
                record.last_error = f"перезагрузка не удалась (error_id={error_id})"
            raise PluginLoadError(name, f"перезагрузка не удалась (error_id={error_id})") from exc

        record.plugin_class = new_class
        record.instance = new_instance
        record.ctx = new_ctx
        record.status = PluginStatus.ONLINE
        record.loaded_at = time.time()
        record.last_error = None
        self.event_bus.emit(PluginReloaded(plugin=name, version=new_class.meta.version))
        logger.info("Плагин перезагружен: %s v%s", name, new_class.meta.version)

    async def shutdown_all(self) -> None:
        """Останавливает все загруженные плагины (используется при graceful shutdown)."""
        for record in list(self._plugins.values()):
            if record.instance is not None:
                await self._teardown(record)
                record.status = PluginStatus.DISABLED

    # -- интроспекция -----------------------------------------------------

    def list_plugins(self) -> list[PluginRecord]:
        return sorted(self._plugins.values(), key=lambda r: r.name)

    def get(self, name: str) -> PluginRecord | None:
        return self._plugins.get(name)

    def dependents_of(self, name: str) -> list[str]:
        """Возвращает имена плагинов, которые зависят от указанного."""
        return [
            record.name
            for record in self._plugins.values()
            if record.plugin_class and name in record.plugin_class.meta.dependencies
        ]
