"""Восстановление состояния при запуске и корректная остановка (ТЗ §27, §29)."""
from __future__ import annotations

import logging

import discord

from database.repositories.guild_repository import GuildRepository

logger = logging.getLogger("skyhub.lifecycle")


async def on_ready(bot) -> None:
    logger.info("Подключено к Discord как %s (серверов: %d)", bot.user, len(bot.guilds))

    async with bot.db.session() as session:
        repo = GuildRepository(session)
        for guild in bot.guilds:
            await repo.get_or_create(guild.id, guild.name)

    for guild in bot.guilds:
        role_map_raw = await _load_role_map(bot, guild.id)
        if role_map_raw:
            from core.permissions import Role

            bot.permissions.configure_guild(guild.id, {Role.from_name(k): v for k, v in role_map_raw.items()})

    await bot.plugin_manager.start_all()

    total = len(bot.plugin_manager.list_plugins())
    online = sum(1 for r in bot.plugin_manager.list_plugins() if r.status.value == "ONLINE")

    await _announce_online(bot, online, total)
    logger.info("SkyHub Bot полностью запущен -- загружено плагинов: %d/%d", online, total)


async def _load_role_map(bot, guild_id: int) -> dict[str, int]:
    from services.guild_config_service import GuildConfigService

    service = GuildConfigService(bot.db, bot.config, bot.cache)
    return await service.role_map_for(guild_id)


async def _announce_online(bot, online: int, total: int) -> None:
    home_guild_id = bot.config.get("discord", {}).get("home_guild_id")
    channel = None
    if home_guild_id:
        from services.guild_config_service import GuildConfigService

        service = GuildConfigService(bot.db, bot.config, bot.cache)
        channel_id = await service.resolve_channel_id(home_guild_id, "status")
        if channel_id:
            channel = bot.get_channel(channel_id)

    embed = discord.Embed(title="🟢 SkyHub Bot онлайн", color=discord.Color.green())
    embed.add_field(name="Версия", value=bot.config.get("bot", {}).get("version", "1.0.0"))
    embed.add_field(name="Плагины", value=f"{online}/{total}")
    embed.add_field(name="База данных", value="Подключена" if bot.db.connected else "Отключена")
    embed.add_field(name="Discord", value="Подключен")

    logger.info(
        "SkyHub Bot онлайн | version=%s plugins=%d/%d",
        bot.config.get("bot", {}).get("version", "1.0.0"), online, total,
    )

    if channel is not None:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Не удалось отправить сообщение о запуске бота")


async def graceful_shutdown(bot) -> None:
    """Прекращает принимать новую работу, аккуратно останавливает плагины и
    закрывает ресурсы (ТЗ §29): сначала плагины (чтобы прекратилось
    использование их задач/БД), затем база данных, затем само соединение с Discord."""
    logger.info("Инициирована корректная остановка бота")
    try:
        await bot.plugin_manager.shutdown_all()
    except Exception:
        logger.exception("Ошибка при остановке плагинов")

    try:
        await bot.db.close()
    except Exception:
        logger.exception("Ошибка при закрытии базы данных")

    if not bot.is_closed():
        await bot.close()

    logger.info("Остановка завершена")
