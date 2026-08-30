from __future__ import annotations

from database.models.user import User
from database.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    async def upsert(self, user_id: int, username: str, *, discriminator: str | None = None) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            user = User(id=user_id, username=username, discriminator=discriminator)
            self.session.add(user)
        else:
            user.username = username
            user.discriminator = discriminator
        await self.session.flush()
        return user
