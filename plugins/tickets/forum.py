"""Общая логика приватного форума для сапорта (см. модуль-докстринг
``database/models/ticket.py``) -- используется и самим ``plugins/tickets``,
и командами ``/setup tickets-forum``/``/setup ticket-viewer-roles`` в
``plugins/server_setup`` (обе меняют состав ролей-просмотрщиков, поэтому
обеим нужно уметь пересобрать права форума заново).

Жёсткое ограничение платформы Discord: форум-канал поддерживает ТОЛЬКО
публичные посты -- приватных постов внутри одного форума не бывает,
все, кто видит канал форума, видят ВСЕ посты в нём (подтверждено
поддержкой Discord: https://support.discord.com/hc/en-us/community/posts/18859490226455).
Поэтому автор обращения форум вообще не получает -- у него свой
приватный текстовый канал (``tickets_category_id``), а форум целиком
закрыт для всех, кроме admin/moderator/support и
``ticket_viewer_role_ids`` -- бот сам держит эти права в синхроне,
чтобы админу не пришлось настраивать их в Discord руками.
"""
from __future__ import annotations

import discord

TAG_OPEN = "🆕 Открыт"
TAG_CLOSED = "🔒 Закрыт"

BRIDGE_WEBHOOK_NAME = "SkyHub Tickets Bridge"


async def viewer_role_ids(ctx, guild_id: int) -> set[int]:
    """Все роли, которым положен доступ ко ВСЕМ тикетам сразу: admin +
    moderator + support (из ``/setup roles``) + доп. роли из
    ``/setup ticket-viewer-roles``."""
    config = ctx.guild_config()
    role_ids: set[int] = set()
    for key in ("admin", "moderator", "support"):
        value = await config.resolve_role_id(guild_id, key)
        if value:
            role_ids.add(value)
    role_ids |= await config.ticket_viewer_role_ids(guild_id)
    return role_ids


async def sync_forum_permissions(ctx, guild: discord.Guild, forum: discord.ForumChannel) -> None:
    """Держит форум приватным: закрыт для @everyone, открыт только
    ролям из :func:`viewer_role_ids`. Вызывайте это после ЛЮБОГО
    изменения ``/setup tickets-forum`` или ``/setup ticket-viewer-roles``,
    чтобы не заставлять админа вручную настраивать права канала."""
    overwrites = dict(forum.overwrites)
    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
    for role_id in await viewer_role_ids(ctx, guild.id):
        role = guild.get_role(role_id)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages_in_threads=True,
                create_public_threads=True, read_message_history=True, manage_threads=True,
            )
    await forum.edit(overwrites=overwrites, reason="Синхронизация прав приватного форума тикетов")


async def ensure_forum_tags(forum: discord.ForumChannel) -> dict[str, discord.ForumTag]:
    """Гарантирует, что на форуме есть теги "Открыт"/"Закрыт" -- создаёт
    недостающие (первый вызов на новом форуме). Возвращает {имя: тег}."""
    existing = {tag.name: tag for tag in forum.available_tags}
    missing_names = [name for name in (TAG_OPEN, TAG_CLOSED) if name not in existing]
    if not missing_names:
        return existing
    new_tags = list(forum.available_tags) + [discord.ForumTag(name=name) for name in missing_names]
    updated = await forum.edit(available_tags=new_tags, reason="Автосоздание тегов статуса тикета")
    return {tag.name: tag for tag in (updated or forum).available_tags}


async def get_or_create_bridge_webhook(channel: discord.abc.GuildChannel) -> discord.Webhook:
    """Веб-хук, которым бот пересылает сообщения между приватным каналом
    тикета и постом форума -- через него сообщение приходит от имени
    исходного автора (его ник/аватар), а не от лица самого бота, что
    было бы куда менее читаемо в переписке. Отдельный веб-хук на канал
    форума одновременно обслуживает ВСЕ его посты (Discord поддерживает
    отправку в конкретный тред через параметр ``thread=``), поэтому
    создаётся не при каждом сообщении, а один раз и переиспользуется."""
    for webhook in await channel.webhooks():
        if webhook.name == BRIDGE_WEBHOOK_NAME:
            return webhook
    return await channel.create_webhook(name=BRIDGE_WEBHOOK_NAME, reason="Мост сообщений тикетов")
