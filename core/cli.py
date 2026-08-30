"""Интерактивная консоль управления ботом (ТЗ §4, §40).

Работает как фоновая asyncio-задача, читающая stdin через отдельный
поток-исполнитель (``input()`` блокирующий, поэтому его нельзя
запускать прямо в event loop). Это та же самая панель управления, что
и slash-команды ``/plugin`` в Discord -- оба варианта в итоге вызывают
:class:`core.plugin_manager.PluginManager`.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from core.exceptions import PluginLoadError, PluginNotFoundError
from core.plugin_manager import PluginManager, PluginStatus

logger = logging.getLogger("skyhub.cli")

STATUS_EMOJI = {
    PluginStatus.ONLINE: "🟢",
    PluginStatus.LOADING: "🟡",
    PluginStatus.DISABLED: "⚪",
    PluginStatus.ERROR: "🔴",
    PluginStatus.BLOCKED: "🟠",
}

HELP_TEXT = """
SkyHub Bot -- консоль управления

  bot start | stop | restart

  plugin list
  plugin info <plugin>
  plugin enable <plugin>
  plugin disable <plugin>
  plugin reload <plugin>
  plugin restart <plugin>
  plugin status

  sync            -- опубликовать slash-команды глобально
  status          -- снимок состояния бота
  health          -- то же самое, что status
  logs            -- путь к файлу JSON-логов
  clear           -- очистить терминал
  help            -- эта справка
  exit / quit     -- корректная остановка бота
""".strip("\n")


class ConsoleCLI:
    def __init__(self, bot, *, on_exit) -> None:
        self.bot = bot
        self._on_exit = on_exit
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="console-cli")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        loop = asyncio.get_event_loop()

        if not sys.stdin.isatty():
            # Под systemd (без StandardInput=tty), в фоновом Docker-контейнере
            # или при перенаправлении из /dev/null stdin никогда не даст ни
            # одной строки -- дальше просто нет смысла его читать. Управление
            # ботом в таком режиме идёт через /status и /plugin в Discord.
            logger.info(
                "stdin не является терминалом -- интерактивная консоль отключена. "
                "Используйте /status и /plugin в Discord для управления ботом."
            )
            return

        print(HELP_TEXT)
        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, RuntimeError):
                break
            if not line:
                # readline() блокирующий: пустая строка означает настоящий
                # EOF (Ctrl+D или закрытие stdin), а не "данных пока нет".
                # Раньше это условие трактовалось как "попробовать снова
                # позже" и уходило в бесконечный busy-poll каждые 0.2с.
                logger.info("Ввод консоли завершён (EOF) -- дальнейшие команды консоли недоступны.")
                break
            command = line.strip()
            if not command:
                continue
            try:
                await self._dispatch(command)
            except Exception:
                logger.exception("Команда консоли завершилась с ошибкой: %s", command)

    async def _dispatch(self, command: str) -> None:
        parts = command.split()
        head, *rest = parts

        if head in ("help", "?"):
            print(HELP_TEXT)
        elif head == "bot" and rest:
            await self._bot(rest[0])
        elif head == "plugin" and rest:
            await self._plugin(rest)
        elif head in ("status", "health"):
            await self._status()
        elif head == "sync":
            count = await self.bot.command_registry.sync(global_sync=True)
            print(f"Опубликовано {count} глобальных команд.")
        elif head == "logs":
            print(f"JSON-логи: {self.bot.settings.log_dir / 'skyhub.jsonl'}")
        elif head == "clear":
            print("\x1b[2J\x1b[H", end="")
        elif head in ("exit", "quit"):
            print("Остановка бота...")
            await self._on_exit()
        else:
            print(f"Неизвестная команда: {command!r}. Введите 'help'.")

    async def _bot(self, action: str) -> None:
        if action == "stop":
            await self._on_exit()
        elif action == "restart":
            print("Полный перезапуск процесса не управляется самим ботом -- используйте менеджер процессов (systemd/Docker).")
        elif action == "start":
            print("Бот уже запущен.")
        else:
            print(f"Неизвестное действие 'bot': {action}")

    async def _plugin(self, args: list[str]) -> None:
        pm: PluginManager = self.bot.plugin_manager
        action, *params = args

        if action == "list" or action == "status":
            self._print_plugin_table(pm)
            return

        if not params:
            print(f"Использование: plugin {action} <имя>")
            return
        name = params[0]

        try:
            if action == "info":
                self._print_plugin_info(pm, name)
            elif action == "enable":
                await pm.enable(name)
                print(f"Плагин '{name}' включен.")
            elif action == "disable":
                await pm.disable(name)
                print(f"Плагин '{name}' отключен.")
            elif action == "reload":
                start = time.monotonic()
                await pm.reload(name)
                print(f"Плагин '{name}' перезагружен за {time.monotonic() - start:.2f} сек.")
            elif action == "restart":
                await pm.restart(name)
                print(f"Плагин '{name}' перезапущен.")
            else:
                print(f"Неизвестное действие плагина: {action}")
        except PluginNotFoundError:
            print(f"Плагин '{name}' не найден. Используйте 'plugin list'.")
        except PluginLoadError as exc:
            print(f"❌ {exc}")

    def _print_plugin_table(self, pm: PluginManager) -> None:
        records = pm.list_plugins()
        if not records:
            print("Плагины не обнаружены.")
            return
        name_width = max(len(r.name) for r in records) + 2
        print(f"{'PLUGIN'.ljust(name_width)}VERSION     STATUS")
        print("─" * (name_width + 30))
        for record in records:
            version = record.meta.version if record.meta else "?"
            emoji = STATUS_EMOJI.get(record.status, "❔")
            print(f"{record.name.ljust(name_width)}{version.ljust(12)}{emoji} {record.status.value}")

    def _print_plugin_info(self, pm: PluginManager, name: str) -> None:
        record = pm.get(name)
        if record is None:
            raise PluginNotFoundError(name)
        meta = record.meta
        print(f"Плагин:        {record.name}")
        print(f"Версия:        {meta.version if meta else '?'}")
        print(f"Описание:      {meta.description if meta else '?'}")
        print(f"Автор:         {meta.author if meta else '?'}")
        print(f"Зависимости:   {', '.join(meta.dependencies) if meta and meta.dependencies else '—'}")
        print(f"Статус:        {STATUS_EMOJI.get(record.status, '❔')} {record.status.value}")
        if record.last_error:
            print(f"Последняя ошибка: {record.last_error}")
        dependents = pm.dependents_of(name)
        if dependents:
            print(f"От него зависят: {', '.join(dependents)}")

    async def _status(self) -> None:
        import psutil

        db_ok = await self.bot.db.ping()
        pm = self.bot.plugin_manager
        online = sum(1 for r in pm.list_plugins() if r.status is PluginStatus.ONLINE)
        total = len(pm.list_plugins())
        uptime = time.time() - self.bot.started_at

        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)
        cpu_percent = process.cpu_percent(interval=0.1)

        from utils.time import format_duration, format_latency_ms

        print("Бот:              ONLINE" if self.bot.is_ready() else "Бот:              ЗАПУСКАЕТСЯ")
        print(f"Задержка Discord: {format_latency_ms(self.bot.latency)}")
        print(f"База данных:      {'ONLINE' if db_ok else 'OFFLINE'}")
        print(f"Плагины:          {online}/{total}")
        print(f"Память:           {mem_mb:.1f} МБ")
        print(f"Загрузка CPU:     {cpu_percent:.1f} %")
        print(f"Аптайм:           {format_duration(uptime)}")
