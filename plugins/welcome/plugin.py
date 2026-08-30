"""Плагин ``welcome``: отправляет приветствие через Message Builder при входе участника.

Демонстрирует задуманный паттерн переиспользования: плагин не
реализует вёрстку embed'а заново, а просто предоставляет YAML-шаблон и
опирается на :mod:`services.message_service` (тот же движок, что
работает под капотом ``plugins/message_builder``).
"""
from __future__ import annotations

from pathlib import Path

import discord
import yaml
from discord.ext import commands

from core.base_plugin import BasePlugin, PluginMeta
from services.message_service import MessageRenderer, build_message_spec

TEMPLATE_PATH = Path(__file__).parent / "templates" / "welcome.yaml"


class WelcomeCog(commands.Cog):
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.renderer = MessageRenderer()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        try:
            await self._send_welcome(member)
        except Exception as exc:  # noqa: BLE001
            await self.ctx.report_error(exc, event="on_member_join", guild_id=member.guild.id, user_id=member.id)

    async def _send_welcome(self, member: discord.Member) -> None:
        channel_id = await self.ctx.guild_config().resolve_channel_id(member.guild.id, "welcome")
        if not channel_id:
            return
        channel = self.ctx.bot.get_channel(channel_id)
        if channel is None:
            return

        if not TEMPLATE_PATH.exists():
            return
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        raw = raw.replace("{mention}", member.mention).replace("{name}", member.display_name)
        data = yaml.safe_load(raw) or {}
        spec = build_message_spec(data)

        for embed in self.renderer.render(spec, bot_user=self.ctx.bot.user):
            await channel.send(embed=embed)


class WelcomePlugin(BasePlugin):
    meta = PluginMeta(
        name="welcome", version="1.0.2",
        description="Отправляет красивое приветственное сообщение (через message_service) при входе участника",
        dependencies=(),
        requires_db=False,
    )

    async def setup(self) -> None:
        await self.ctx.add_cog(WelcomeCog(self.ctx))
        self.log.info("welcome готов к работе")


PLUGIN_CLASS = WelcomePlugin
