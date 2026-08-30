"""Плагин ``radio``: непрерывное циклическое воспроизведение загруженных
треков в голосовом канале, как радиостанция -- плейлист играет по кругу,
пока его не остановят.

Требования к окружению (см. README, раздел «Радио»):

* пакет ``PyNaCl`` (шифрование голосового соединения Discord);
* установленный в системе ``ffmpeg`` (discord.py декодирует аудио,
  запуская его как внешний процесс).

Если чего-то из этого нет, попытка запустить радио (``/radio play`` или
автозапуск при старте бота) завершится понятной ошибкой через
:class:`core.error_handler.ErrorHandler`, а не уронит весь процесс --
остальные плагины при этом продолжают работать как ни в чём не бывало
(ТЗ §23, изоляция ошибок).
"""
from __future__ import annotations

import asyncio
import logging

import discord

from core.base_plugin import BasePlugin, PluginMeta
from database.models.radio import RadioTrack
from database.repositories.dashboard_repository import DashboardRepository
from database.repositories.radio_repository import RadioRepository
from plugins.radio.commands import build_radio_cog
from plugins.radio.metadata import format_duration_long
from plugins.radio.paths import DATA_DIR

logger = logging.getLogger("skyhub.radio")

DASHBOARD_KIND = "radio_now_playing"


class RadioPlayer:
    """Состояние воспроизведения радио для одного сервера: подключение к
    голосовому каналу, плейлист и позиция в нём."""

    def __init__(self, plugin: RadioPlugin, guild_id: int) -> None:
        self.plugin = plugin
        self.guild_id = guild_id
        self.voice_client: discord.VoiceClient | None = None
        self.tracks: list[RadioTrack] = []
        self.index: int = 0
        self.volume: float = 1.0  # 1.0 = 100%, регулируется /radio volume
        self._source: discord.PCMVolumeTransformer | None = None

    @property
    def current(self) -> RadioTrack | None:
        if not self.tracks:
            return None
        return self.tracks[self.index % len(self.tracks)]

    async def refresh_tracks(self) -> None:
        async with self.plugin.ctx.db.session() as session:
            self.tracks = await RadioRepository(session).list_for_guild(self.guild_id)

    async def start(self, voice_channel: discord.VoiceChannel) -> None:
        await self.refresh_tracks()
        if not self.tracks:
            raise RuntimeError("Плейлист пуст -- сначала добавьте треки через /radio add.")

        if self.voice_client is not None and self.voice_client.is_connected():
            if self.voice_client.channel.id != voice_channel.id:
                await self.voice_client.move_to(voice_channel)
        else:
            self.voice_client = await voice_channel.connect(reconnect=True)

        if not self.voice_client.is_playing():
            await self._play_current()

    async def stop(self) -> None:
        if self.voice_client is None:
            return
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
        if self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
        self.voice_client = None
        self._source = None

    async def skip(self) -> None:
        if self.voice_client is not None and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            # stop() сам вызовет _on_finished -> переход к следующему треку
            self.voice_client.stop()
        else:
            self._advance()
            await self._play_current()

    def _advance(self) -> None:
        if self.tracks:
            self.index = (self.index + 1) % len(self.tracks)

    def set_volume(self, volume: float) -> None:
        """Меняет громкость на лету, без перезапуска трека -- ``PCMVolumeTransformer``
        читает ``.volume`` перед каждым аудио-пакетом."""
        self.volume = volume
        if self._source is not None:
            self._source.volume = volume

    async def _play_current(self) -> None:
        track = self.current
        if track is None or self.voice_client is None:
            return
        path = DATA_DIR / track.file_path
        if not path.exists():
            logger.error("Файл трека не найден на диске: %s (id=%s) -- пропускаю его в плейлисте", path, track.id)
            self._advance()
            if self.tracks and self.current is not None and self.current.id != track.id:
                await self._play_current()
            return

        try:
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(path)), volume=self.volume)
            self._source = source
            self.voice_client.play(source, after=self._on_finished)
        except discord.ClientException:
            logger.exception(
                "Не удалось запустить воспроизведение (возможно, не установлен ffmpeg) для трека %s", track.title
            )
            return
        await self.plugin.update_now_playing(self.guild_id, track)

    def _on_finished(self, error: Exception | None) -> None:
        # Вызывается discord.py из отдельного (не asyncio) потока
        # проигрывателя -- обратно в event loop переходим безопасно через
        # run_coroutine_threadsafe, а не await'им отсюда напрямую.
        if error:
            logger.error("Ошибка воспроизведения трека на сервере %s: %s", self.guild_id, error)
        self._advance()
        try:
            loop = self.plugin.ctx.bot.loop
            asyncio.run_coroutine_threadsafe(self._play_current(), loop)
        except Exception:
            logger.exception("Не удалось запланировать следующий трек радио")


class RadioPlugin(BasePlugin):
    meta = PluginMeta(
        name="radio", version="1.0.0",
        description="Непрерывное радио из загруженных треков в голосовом канале (/radio ...)",
        dependencies=(),
    )

    async def setup(self) -> None:
        self.players: dict[int, RadioPlayer] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        await self.ctx.add_cog(build_radio_cog(self.ctx, self))
        self.log.info("radio готов к работе")

    def player_for(self, guild_id: int) -> RadioPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = RadioPlayer(self, guild_id)
        return self.players[guild_id]

    async def start(self) -> None:
        for guild in self.ctx.bot.guilds:
            try:
                await self._auto_start(guild)
            except Exception as exc:  # noqa: BLE001
                await self.ctx.report_error(exc, event="radio_auto_start", guild_id=guild.id)

    async def _auto_start(self, guild: discord.Guild) -> None:
        voice_channel_id = await self.ctx.guild_config().resolve_channel_id(guild.id, "radio_voice")
        if not voice_channel_id:
            return
        channel = guild.get_channel(voice_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            return

        player = self.player_for(guild.id)
        await player.refresh_tracks()
        if not player.tracks:
            self.log.info("Радио на сервере %s настроено, но плейлист пуст -- ждём /radio add", guild.name)
            return
        await player.start(channel)

    async def update_now_playing(self, guild_id: int, track: RadioTrack) -> None:
        channel_id = await self.ctx.guild_config().resolve_channel_id(guild_id, "radio_text")
        if not channel_id:
            return
        channel = self.ctx.bot.get_channel(channel_id)
        if channel is None:
            return

        player = self.player_for(guild_id)
        embed, cover_file = self.build_now_playing_embed(track, player)

        async with self.ctx.db.session() as session:
            existing = await DashboardRepository(session).get(guild_id, DASHBOARD_KIND)

        message = None
        if existing is not None:
            existing_channel = self.ctx.bot.get_channel(existing.channel_id)
            if existing_channel is not None:
                try:
                    message = await existing_channel.fetch_message(existing.message_id)
                    # attachments=[...] обязателен, иначе edit() оставит
                    # обложку предыдущего трека висеть на новом сообщении.
                    await message.edit(embed=embed, attachments=[cover_file] if cover_file else [])
                except discord.HTTPException:
                    message = None

        if message is None:
            try:
                message = await channel.send(embed=embed, file=cover_file)
            except discord.HTTPException as exc:
                await self.ctx.report_error(exc, event="radio_now_playing", guild_id=guild_id)
                return
            async with self.ctx.db.session() as session:
                await DashboardRepository(session).upsert(
                    guild_id=guild_id, kind=DASHBOARD_KIND, channel_id=channel_id, message_id=message.id
                )

    def build_now_playing_embed(self, track: RadioTrack, player: RadioPlayer) -> tuple[discord.Embed, discord.File | None]:
        """Собирает карточку в стиле "DJ Paimon": крупный заголовок
        (альбом/OST), жирное название трека и список технических полей,
        плюс обложка, извлечённая из тегов файла при добавлении."""
        title = track.album or "📻 Сейчас играет"

        lines = [f"**{track.title}**", ""]
        duration_text = format_duration_long(track.duration_seconds)
        if duration_text:
            lines.append(f"• **Длительность:** {duration_text}")
        if track.artist:
            lines.append(f"• **Исполнитель:** {track.artist}")
        if track.composer:
            lines.append(f"• **Композитор:** {track.composer}")
        if track.bitrate_kbps:
            lines.append(f"• **Битрейт:** {track.bitrate_kbps} kbps")

        embed = discord.Embed(title=title[:256], description="\n".join(lines), color=discord.Color.blurple())
        embed.add_field(name="Трек в плейлисте", value=f"{player.index + 1} / {len(player.tracks)}")
        embed.set_footer(text="Плейлист играет по кругу -- добавить трек: /radio add")

        cover_file = None
        if track.cover_path:
            cover_path = DATA_DIR / track.cover_path
            if cover_path.exists():
                cover_file = discord.File(cover_path, filename=cover_path.name)
                embed.set_image(url=f"attachment://{cover_path.name}")

        return embed, cover_file

    async def stop(self) -> None:
        for player in list(self.players.values()):
            try:
                await player.stop()
            except Exception:
                logger.exception("Ошибка при остановке радио на сервере %s", player.guild_id)


PLUGIN_CLASS = RadioPlugin
