"""Интеграционный smoke-тест: каждый реальный плагин из ``plugins/`` должен
импортироваться, создаваться и выполнять ``setup()``/``start()`` без ошибок,
через тот же самый :class:`PluginManager`, что использует запущенный бот.
Это ловит опечатку или плохой импорт в любом плагине ещё до того, как он
попадёт в Discord.

База данных здесь намеренно является заглушкой, которая падает при
обращении: ни одному плагину не должна требоваться БД просто для
регистрации команд/слушателей при нуле подключённых серверов, а у этого
теста нет настоящего Postgres, с которым можно было бы поговорить.
"""
from __future__ import annotations

from config.loader import load_config
from config.settings import PROJECT_ROOT
from core.plugin_manager import PluginManager, PluginStatus


class _UnusedDatabase:
    def session(self):  # pragma: no cover - в этом тесте вызываться не должно
        raise AssertionError("ни один плагин не должен обращаться к БД при нуле подключённых серверов")


async def test_all_real_plugins_load_cleanly(bot, event_bus, permissions, error_handler, i18n, cache) -> None:
    config = load_config(PROJECT_ROOT / "config" / "config.yaml", PROJECT_ROOT / "plugins")

    manager = PluginManager(
        bot=bot,
        event_bus=event_bus,
        db=_UnusedDatabase(),
        permissions=permissions,
        error_handler=error_handler,
        i18n=i18n,
        cache=cache,
        global_config=config,
        plugins_root=PROJECT_ROOT / "plugins",
    )
    manager._bot_ready = True

    await manager.load_all()

    broken = [r for r in manager.list_plugins() if r.status is PluginStatus.ERROR]
    assert not broken, "\n".join(f"{r.name}: {r.last_error}" for r in broken)

    online_names = {r.name for r in manager.list_plugins() if r.status is PluginStatus.ONLINE}
    expected = {
        "message_builder", "moderation", "deleted_messages", "edited_messages",
        "member_logs", "voice_channels", "welcome", "audit", "server_setup",
        "status_dashboard", "radio",
        "aviation_profile", "flight_log", "weather", "tickets", "leveling",
        "flight_events", "server_stats",
    }
    assert expected <= online_names

    await manager.shutdown_all()
    assert all(r.status is PluginStatus.DISABLED for r in manager.list_plugins())
