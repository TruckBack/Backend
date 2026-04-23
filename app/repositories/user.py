from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_driver(self, user_id: int) -> User | None:
        stmt = select(User).options(selectinload(User.driver)).where(User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
