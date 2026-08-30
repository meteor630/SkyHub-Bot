from __future__ import annotations

from database.models.messages import DeletedMessage, EditedMessage
from database.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    async def log_deleted(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        author_id: int | None,
        content: str,
        attachments: list[str] | None = None,
        bulk: bool = False,
    ) -> DeletedMessage:
        record = DeletedMessage(
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            author_id=author_id,
            content=content,
            attachments=attachments or [],
            bulk=bulk,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def log_edited(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        author_id: int,
        before: str,
        after: str,
    ) -> EditedMessage:
        record = EditedMessage(
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            author_id=author_id,
            before=before,
            after=after,
        )
        self.session.add(record)
        await self.session.flush()
        return record
