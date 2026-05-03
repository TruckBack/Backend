from __future__ import annotations

from sqlalchemy import func, select

from app.models.rating import DriverRating
from app.repositories.base import BaseRepository


class RatingRepository(BaseRepository[DriverRating]):
    model = DriverRating

    async def get_by_order_id(self, order_id: int) -> DriverRating | None:
        stmt = select(DriverRating).where(DriverRating.order_id == order_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_average_for_driver(self, driver_id: int) -> float:
        """Return the arithmetic average score for all ratings of a driver.
        Returns 0.0 if there are no ratings yet."""
        stmt = select(func.avg(DriverRating.score)).where(
            DriverRating.driver_id == driver_id
        )
        avg = await self.session.scalar(stmt)
        return round(float(avg), 2) if avg is not None else 0.0

    async def list_for_driver(
        self, driver_id: int, *, limit: int, offset: int
    ) -> tuple[list[DriverRating], int]:
        base = select(DriverRating).where(DriverRating.driver_id == driver_id)
        total = (
            await self.session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            or 0
        )
        stmt = base.order_by(DriverRating.created_at.desc()).limit(limit).offset(offset)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total
