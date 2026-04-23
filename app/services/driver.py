from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.driver import Driver, DriverStatus
from app.models.user import User
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.schemas.driver import (
    DriverLocationUpdate,
    DriverProfileUpdate,
    DriverStatusUpdate,
)


class DriverService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.drivers = DriverRepository(db)
        self.orders = OrderRepository(db)

    async def get_for_user(self, user: User) -> Driver:
        driver = await self.drivers.get_by_user_id(user.id)
        if not driver:
            raise NotFoundError("Driver profile not found")
        return driver

    async def update_profile(self, user: User, data: DriverProfileUpdate) -> Driver:
        driver = await self.get_for_user(user)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(driver, field, value)
        await self.db.commit()
        await self.db.refresh(driver)
        return driver

    async def update_status(self, user: User, data: DriverStatusUpdate) -> Driver:
        driver = await self.get_for_user(user)

        if data.status == DriverStatus.OFFLINE and await self.orders.driver_has_active_order(
            driver.id
        ):
            raise BadRequestError("Cannot go offline while having active orders")

        driver.status = data.status
        await self.db.commit()
        await self.db.refresh(driver)
        return driver

    async def update_location(self, user: User, data: DriverLocationUpdate) -> Driver:
        driver = await self.get_for_user(user)
        driver.current_lat = data.lat
        driver.current_lng = data.lng
        driver.last_location_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(driver)
        return driver
