"""Slash-команды ``/radio`` -- загрузка треков и управление непрерывным
воспроизведением."""
from __future__ import annotations

import secrets
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.permissions import Role, require
from database.repositories.radio_repository import RadioRepository
from plugins.radio.metadata import extract_metadata
from plugins.radio.paths import DATA_DIR

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # обычный лимит вложений Discord без буста сервера
ALLOWED_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".webm"}


class RadioCog(commands.Cog):
    radio_group = app_commands.Group(
        name="radio", description="Управление непрерывным радио сервера", guild_only=True
    )

    def __init__(self, ctx, plugin) -> None:
        self.ctx = ctx
        self.plugin = plugin

    @radio_group.command(name="add", description="Добавить трек в плейлист радио (прикрепите аудиофайл)")
    @app_commands.describe(track="Аудиофайл (mp3/ogg/wav/m4a/flac/webm), до 25 МБ")
    @require(Role.MODERATOR)
    async def add(self, interaction: discord.Interaction, track: discord.Attachment) -> None:
        await interaction.response.defer(ephemeral=True)

        ext = Path(track.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            await interaction.followup.send(
                f"⚠️ Неподдерживаемый формат: `{ext or '(нет расширения)'}`. "
                f"Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
                ephemeral=True,
            )
            return
        if track.size > MAX_FILE_SIZE_BYTES:
            await interaction.followup.send("⚠️ Файл слишком большой (лимит вложений Discord -- 25 МБ).", ephemeral=True)
            return

        guild_dir = DATA_DIR / str(interaction.guild_id)
        guild_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{secrets.token_hex(4)}_{Path(track.filename).name}"
        dest = guild_dir / safe_name
        await track.save(dest)

        # Читаем теги/обложку прямо из только что сохранённого файла --
        # если их нет или файл повреждён, extract_metadata тихо вернёт
        # пустые поля, а не бросит исключение (трек всё равно добавится,
        # просто с именем файла вместо тегов).
        meta = extract_metadata(dest)
        cover_relpath = None
        if meta.cover_bytes:
            cover_name = f"{Path(safe_name).stem}_cover.{meta.cover_ext or 'jpg'}"
            (guild_dir / cover_name).write_bytes(meta.cover_bytes)
            cover_relpath = f"{interaction.guild_id}/{cover_name}"

        async with self.ctx.db.session() as session:
            record = await RadioRepository(session).add(
                guild_id=interaction.guild_id,
                title=meta.title or Path(track.filename).stem,
                file_path=f"{interaction.guild_id}/{safe_name}",
                added_by_id=interaction.user.id,
                artist=meta.artist,
                album=meta.album,
                composer=meta.composer,
                duration_seconds=meta.duration_seconds,
                bitrate_kbps=meta.bitrate_kbps,
                cover_path=cover_relpath,
            )

        player = self.plugin.player_for(interaction.guild_id)
        await player.refresh_tracks()

        details = f"**{record.title}**"
        if record.artist:
            details += f" -- {record.artist}"
        await interaction.followup.send(
            f"✅ Добавлено в плейлист: {details} (позиция {record.position + 1}).", ephemeral=True
        )

    @radio_group.command(name="list", description="Показать плейлист радио")
    async def list_tracks(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            tracks = await RadioRepository(session).list_for_guild(interaction.guild_id)
        if not tracks:
            await interaction.followup.send("Плейлист пуст. Добавьте треки через `/radio add`.", ephemeral=True)
            return

        player = self.plugin.player_for(interaction.guild_id)
        current_id = player.current.id if player.current else None
        lines = [
            f"{'▶️' if t.id == current_id else '　　'} `{i + 1}.` {t.title}" + (f" -- {t.artist}" if t.artist else "")
            for i, t in enumerate(tracks)
        ]
        embed = discord.Embed(title="📻 Плейлист радио", description="\n".join(lines)[:4000], color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @radio_group.command(name="remove", description="Удалить трек из плейлиста по номеру из /radio list")
    @app_commands.describe(index="Номер трека (см. /radio list)")
    @require(Role.MODERATOR)
    async def remove(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, 500]) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.ctx.db.session() as session:
            repo = RadioRepository(session)
            tracks = await repo.list_for_guild(interaction.guild_id)
            if index > len(tracks):
                await interaction.followup.send("⚠️ Нет трека с таким номером.", ephemeral=True)
                return
            track = tracks[index - 1]
            await repo.remove(track.id)

        (DATA_DIR / track.file_path).unlink(missing_ok=True)

        player = self.plugin.player_for(interaction.guild_id)
        await player.refresh_tracks()
        await interaction.followup.send(f"🗑 Удалено: **{track.title}**.", ephemeral=True)

    @radio_group.command(name="play", description="Запустить радио в голосовом канале (см. /setup radio)")
    @require(Role.MODERATOR)
    async def play(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        voice_channel_id = await self.ctx.guild_config().resolve_channel_id(interaction.guild_id, "radio_voice")
        if not voice_channel_id:
            await interaction.followup.send("⚠️ Голосовой канал для радио не настроен -- используйте `/setup radio`.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(voice_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.followup.send("⚠️ Настроенный канал больше не существует или не является голосовым.", ephemeral=True)
            return

        player = self.plugin.player_for(interaction.guild_id)
        try:
            await player.start(channel)
        except RuntimeError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
            return
        except discord.ClientException as exc:
            await interaction.followup.send(f"⚠️ Не удалось подключиться к голосовому каналу: {exc}", ephemeral=True)
            return
        await interaction.followup.send(f"▶️ Радио запущено в {channel.mention}.", ephemeral=True)

    @radio_group.command(name="stop", description="Остановить радио и отключиться от голосового канала")
    @require(Role.MODERATOR)
    async def stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        player = self.plugin.player_for(interaction.guild_id)
        await player.stop()
        await interaction.followup.send("⏹ Радио остановлено.", ephemeral=True)

    @radio_group.command(name="skip", description="Переключить на следующий трек")
    @require(Role.MODERATOR)
    async def skip(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        player = self.plugin.player_for(interaction.guild_id)
        if player.current is None:
            await interaction.followup.send("⚠️ Плейлист пуст.", ephemeral=True)
            return
        await player.skip()
        await interaction.followup.send("⏭ Переключено на следующий трек.", ephemeral=True)


def build_radio_cog(ctx, plugin) -> RadioCog:
    return RadioCog(ctx, plugin)
