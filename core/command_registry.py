"""Политика синхронизации дерева slash-команд (ТЗ §33).

Slash-команды Discord объявляются локально (через cog'и/команды,
добавленные через :class:`core.plugin_context.PluginContext`), но
вступают в силу только после *синхронизации* дерева команд. Глобальная
синхронизация распространяется до часа и ограничена по частоте, что
плохо сочетается с идеей горячей перезагрузки, вокруг которой построен
этот бот. Если задан ``dev_guild_id``, синхронизация идёт только в этот
один сервер -- мгновенно и без таких ограничений -- а глобальная
публикация остаётся отдельной, редкой операцией (`bot.tree.sync()` без
указания сервера).
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("skyhub.commands")


class CommandRegistry:
    def __init__(self, bot: commands.Bot, *, dev_guild_id: int | None = None) -> None:
        self.bot = bot
        self.dev_guild_id = dev_guild_id

    async def sync(self, *, global_sync: bool = False) -> int:
        """Синхронизирует дерево команд: глобально или в тестовый сервер разработки."""
        if global_sync or self.dev_guild_id is None:
            synced = await self.bot.tree.sync()
            logger.info("Синхронизировано %d глобальных команд", len(synced))
            return len(synced)

        guild = discord.Object(id=self.dev_guild_id)
        self.bot.tree.copy_global_to(guild=guild)
        synced = await self.bot.tree.sync(guild=guild)
        logger.info("Синхронизировано %d команд в тестовый сервер %s", len(synced), self.dev_guild_id)
        return len(synced)
