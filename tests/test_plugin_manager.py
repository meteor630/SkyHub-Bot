"""Тесты жизненного цикла плагинов и безопасной горячей перезагрузки
(ТЗ §37) -- самые важные тесты в этом наборе. Синтетические плагины
записываются как настоящие файлы под ``plugins/`` (механизм импорта
требует именно такого пути пакета) и удаляются в конце теста через фикстуру.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.exceptions import PluginLoadError
from core.plugin_manager import PluginManager, PluginStatus

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = PROJECT_ROOT / "plugins"

V1_SOURCE = '''
import asyncio
import sys

from core.base_plugin import BasePlugin, PluginMeta

RECORD = sys.__dict__.setdefault("_skyhub_test_record", [])


class DummyPlugin(BasePlugin):
    meta = PluginMeta(name="{name}", version="1.0.0", dependencies={deps!r})

    async def setup(self) -> None:
        RECORD.append(("setup", "v1"))

    async def start(self) -> None:
        RECORD.append(("start", "v1"))
        self.ctx.create_task(self._tick())

    async def _tick(self) -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            RECORD.append(("task_cancelled", "v1"))
            raise

    async def stop(self) -> None:
        RECORD.append(("stop", "v1"))


PLUGIN_CLASS = DummyPlugin
'''

V2_SOURCE = '''
import sys

from core.base_plugin import BasePlugin, PluginMeta

RECORD = sys.__dict__.setdefault("_skyhub_test_record", [])


class DummyPlugin(BasePlugin):
    meta = PluginMeta(name="{name}", version="2.0.0", dependencies={deps!r})

    async def setup(self) -> None:
        RECORD.append(("setup", "v2"))

    async def start(self) -> None:
        RECORD.append(("start", "v2"))

    async def stop(self) -> None:
        RECORD.append(("stop", "v2"))


PLUGIN_CLASS = DummyPlugin
'''

BROKEN_SOURCE = "this is not valid python syntax :::\n"

CONSTRUCTOR_FAILS_SOURCE = '''
from core.base_plugin import BasePlugin, PluginMeta


class DummyPlugin(BasePlugin):
    meta = PluginMeta(name="{name}", version="3.0.0", dependencies={deps!r})

    def __init__(self, ctx):
        super().__init__(ctx)
        raise RuntimeError("constructor boom")

    async def setup(self) -> None:
        pass


PLUGIN_CLASS = DummyPlugin
'''

SETUP_FAILS_SOURCE = '''
from core.base_plugin import BasePlugin, PluginMeta


class DummyPlugin(BasePlugin):
    meta = PluginMeta(name="{name}", version="4.0.0", dependencies={deps!r})

    async def setup(self) -> None:
        raise RuntimeError("setup boom")


PLUGIN_CLASS = DummyPlugin
'''


def write_plugin(name: str, source_template: str, *, deps: tuple[str, ...] = ()) -> None:
    plugin_dir = PLUGINS_ROOT / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(source_template.format(name=name, deps=deps), encoding="utf-8")


def remove_plugin(name: str) -> None:
    shutil.rmtree(PLUGINS_ROOT / name, ignore_errors=True)
    for mod_name in [m for m in sys.modules if m == f"plugins.{name}" or m.startswith(f"plugins.{name}.")]:
        del sys.modules[mod_name]


@pytest.fixture
def record():
    sys.__dict__["_skyhub_test_record"] = []
    yield sys.__dict__["_skyhub_test_record"]
    sys.__dict__.pop("_skyhub_test_record", None)


@pytest.fixture
def manager(bot, event_bus: EventBus, permissions, error_handler, i18n, cache):
    pm = PluginManager(
        bot=bot,
        event_bus=event_bus,
        db=object(),
        permissions=permissions,
        error_handler=error_handler,
        i18n=i18n,
        cache=cache,
        global_config={"plugins": {}},
        plugins_root=PLUGINS_ROOT,
    )
    pm._bot_ready = True  # пропускаем ожидание on_ready, чтобы start() запускался сразу в тестах
    yield pm


@pytest.fixture
def cleanup_plugins():
    created: list[str] = []
    yield created
    for name in created:
        remove_plugin(name)


async def test_enable_loads_and_starts_plugin(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_basic_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)

    await manager.enable(name)

    plugin_record = manager.get(name)
    assert plugin_record.status is PluginStatus.ONLINE
    assert plugin_record.meta.version == "1.0.0"
    assert ("setup", "v1") in record
    assert ("start", "v1") in record


async def test_reload_swaps_in_new_version_cleanly(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_reload_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)
    await manager.enable(name)
    await asyncio.sleep(0)  # даём фоновой задаче реально стартовать (дойти до своего await)
    record.clear()

    write_plugin(name, V2_SOURCE)
    await manager.reload(name)

    plugin_record = manager.get(name)
    assert plugin_record.status is PluginStatus.ONLINE
    assert plugin_record.meta.version == "2.0.0"
    # старый экземпляр должен быть остановлен ровно один раз, новый -- запущен ровно один раз
    assert record.count(("stop", "v1")) == 1
    assert record.count(("task_cancelled", "v1")) == 1
    assert record.count(("setup", "v2")) == 1
    assert record.count(("start", "v2")) == 1


async def test_reload_with_broken_syntax_rolls_back_to_working_version(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_rollback_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)
    await manager.enable(name)
    record.clear()

    (PLUGINS_ROOT / name / "plugin.py").write_text(BROKEN_SOURCE, encoding="utf-8")

    with pytest.raises(PluginLoadError):
        await manager.reload(name)

    plugin_record = manager.get(name)
    # старый плагин вообще не трогали -- ошибка импорта произошла до какой-либо остановки
    assert plugin_record.status is PluginStatus.ONLINE
    assert plugin_record.meta.version == "1.0.0"
    assert ("stop", "v1") not in record


async def test_reload_with_failing_setup_rolls_back_after_teardown(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_setup_fail_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)
    await manager.enable(name)
    record.clear()

    write_plugin(name, SETUP_FAILS_SOURCE)

    with pytest.raises(PluginLoadError):
        await manager.reload(name)

    plugin_record = manager.get(name)
    # откат выполнен: снова работает старый (v1) экземпляр
    assert plugin_record.status is PluginStatus.ONLINE
    assert plugin_record.meta.version == "1.0.0"
    assert "откат" in (plugin_record.last_error or "")
    # старый экземпляр был остановлен один раз и поднят заново один раз
    assert record.count(("stop", "v1")) == 1
    assert record.count(("setup", "v1")) == 1  # повторный setup при откате (запись от изначального enable() была очищена выше)


async def test_reload_with_broken_constructor_is_contained(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_ctor_fail_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)
    await manager.enable(name)
    record.clear()

    write_plugin(name, CONSTRUCTOR_FAILS_SOURCE)

    with pytest.raises(PluginLoadError):
        await manager.reload(name)

    plugin_record = manager.get(name)
    assert plugin_record.status is PluginStatus.ONLINE
    assert plugin_record.meta.version == "1.0.0"
    assert ("stop", "v1") not in record  # не трогали -- ошибка произошла до какой-либо остановки


async def test_unload_cancels_tasks_and_removes_cog(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_unload_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE)
    await manager.enable(name)
    await asyncio.sleep(0)  # даём фоновой задаче реально стартовать (дойти до своего await)

    await manager.unload(name)

    plugin_record = manager.get(name)
    assert plugin_record.status is PluginStatus.DISABLED
    assert plugin_record.instance is None
    assert ("task_cancelled", "v1") in record
    assert ("stop", "v1") in record


async def test_dependent_plugin_is_blocked_when_dependency_missing(manager: PluginManager, record, cleanup_plugins) -> None:
    name = "test_dependent_plugin"
    cleanup_plugins.append(name)
    write_plugin(name, V1_SOURCE, deps=("nonexistent_dependency",))

    await manager.enable(name)

    plugin_record = manager.get(name)
    assert plugin_record.status is PluginStatus.BLOCKED
    assert "nonexistent_dependency" in (plugin_record.last_error or "")
