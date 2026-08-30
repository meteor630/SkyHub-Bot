"""Точка входа процесса: ``python -m app`` (ТЗ §39).

Связывает между собой все базовые синглтоны, запускает подключение к
шлюзу Discord и консольный CLI параллельно, а также устанавливает
обработчики SIGINT/SIGTERM для корректной остановки (ТЗ §29).
"""
from __future__ import annotations

import asyncio
import logging
import signal

from config.loader import load_config
from config.settings import get_settings
from core.cli import ConsoleCLI
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.permissions import PermissionService
from database.database import Database
from logging_config import configure_logging
from utils.cache import TTLCache
from utils.i18n import I18n

logger = logging.getLogger("skyhub.main")

#: Сколько ждать первого on_ready, прежде чем заподозрить проблему с
#: подключением и подсказать пользователю, где искать причину.
STARTUP_WATCHDOG_TIMEOUT_SECONDS = 30.0


async def _startup_watchdog(bot) -> None:
    """Если бот застрял в цикле переподключений, discord.py не всегда
    выбрасывает исключение, которое можно было бы поймать в
    ``async_main`` -- иногда (в частности, при запрещённых privileged
    intents) шлюз просто разрывает соединение кодом 4014 и уходит на
    бесконечный retry, ничего не логируя как ошибку. Этот сторож не
    трогает и не останавливает бота (он может ещё подключиться, если
    причина временная), а только один раз подсказывает, где искать
    проблему, если подключение подозрительно долго не завершается."""
    await asyncio.sleep(STARTUP_WATCHDOG_TIMEOUT_SECONDS)
    if not bot.is_ready() and not bot.is_closed():
        logger.warning(
            "Бот всё ещё не подключился к Discord спустя %.0f сек. после запуска. "
            "Самая частая причина -- в Discord Developer Portal (вкладка Bot) не включены "
            "'Server Members Intent' и/или 'Message Content Intent' (шлюз в этом случае "
            "молча уходит в бесконечный цикл переподключений, не выбрасывая ошибку). "
            "Также проверьте сетевое подключение к discord.com. Бот продолжит попытки сам.",
            STARTUP_WATCHDOG_TIMEOUT_SECONDS,
        )


async def async_main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_dir=settings.log_dir, json_file=settings.log_json)

    config = load_config(settings.config_path, settings.plugins_dir)

    event_bus = EventBus()
    db = Database(settings.database_url, echo=settings.db_echo, pool_size=settings.db_pool_size)
    permissions = PermissionService()
    i18n = I18n(settings.locales_dir, default_locale=settings.default_locale)
    cache = TTLCache(ttl_seconds=30.0)
    error_handler = ErrorHandler(event_bus=event_bus)

    logger.info("Подключение к базе данных...")
    await db.connect()

    from app.bot import SkyHubBot
    from app.lifecycle import graceful_shutdown

    bot = SkyHubBot(
        settings=settings, config=config, event_bus=event_bus, db=db,
        permissions=permissions, error_handler=error_handler, i18n=i18n, cache=cache,
    )

    async def resolve_error_channel(guild_id: int | None):
        if guild_id is None:
            guild_id = config.get("discord", {}).get("home_guild_id")
        if guild_id is None:
            return None
        from services.guild_config_service import GuildConfigService

        service = GuildConfigService(db, config, cache)
        channel_id = await service.resolve_channel_id(guild_id, "error_logs")
        return bot.get_channel(channel_id) if channel_id else None

    error_handler.set_channel_resolver(resolve_error_channel)

    shutdown_event = asyncio.Event()

    async def request_shutdown() -> None:
        shutdown_event.set()

    cli = ConsoleCLI(bot, on_exit=request_shutdown)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(request_shutdown()))
        except NotImplementedError:
            pass  # Windows не поддерживает add_signal_handler для этих сигналов

    async with bot:
        bot_task = asyncio.create_task(bot.start(settings.discord_token), name="discord-gateway")
        cli.start()
        watchdog_task = asyncio.create_task(_startup_watchdog(bot), name="startup-watchdog")

        shutdown_waiter = asyncio.create_task(shutdown_event.wait(), name="shutdown-waiter")
        done, _pending = await asyncio.wait(
            {bot_task, shutdown_waiter}, return_when=asyncio.FIRST_COMPLETED
        )
        shutdown_waiter.cancel()

        if bot_task in done and not shutdown_event.is_set():
            # Подключение к Discord завершилось само по себе (упало с
            # ошибкой -- неверный токен, нет сети и т.п. -- или просто
            # неожиданно закрылось) раньше, чем кто-либо попросил бота
            # остановиться. Раньше это проходило совершенно незаметно:
            # процесс продолжал крутить консоль, будто всё в порядке, а
            # бот при этом даже не пытался подключиться повторно. Явно
            # логируем причину и переходим к остановке, а не зависаем
            # молча в ожидании shutdown_event, который никто не установит.
            exc = bot_task.exception()
            if exc is not None:
                logger.critical("Подключение к Discord завершилось с ошибкой: %s", exc, exc_info=exc)
            else:
                logger.critical("Подключение к Discord неожиданно завершилось без ошибки")

        logger.info("Запрошена остановка бота")
        watchdog_task.cancel()
        await graceful_shutdown(bot)
        await cli.stop()
        if not bot_task.done():
            bot_task.cancel()
        try:
            await bot_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
