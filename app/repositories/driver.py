from __future__ import annotations

from sqlalchemy import select

from app.models.driver import Driver
from app.repositories.base import BaseRepository


class DriverRepository(BaseRepository[Driver]):
    model = Driver

    async def get_by_id(self, driver_id: int) -> Driver | None:
        return await self.session.get(Driver, driver_id)

    async def get_by_user_id(self, user_id: int) -> Driver | None:
        stmt = select(Driver).where(Driver.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_license(self, license_number: str) -> Driver | None:
        stmt = select(Driver).where(Driver.license_number == license_number)
        return (await self.session.execute(stmt)).scalar_one_or_none()
