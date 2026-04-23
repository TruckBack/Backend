from __future__ import annotations

from sqlalchemy import func, select

from app.models.order import ACTIVE_ORDER_STATUSES, Order, OrderStatus
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    async def get_by_id(self, order_id: int) -> Order | None:
        return await self.session.get(Order, order_id)

    async def get_by_id_for_update(self, order_id: int) -> Order | None:
        """Row-level lock to prevent races (e.g. two drivers accepting)."""
        stmt = select(Order).where(Order.id == order_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_available(self, limit: int, offset: int) -> tuple[list[Order], int]:
        base = select(Order).where(Order.status == OrderStatus.PENDING)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        stmt = base.order_by(Order.created_at.asc()).limit(limit).offset(offset)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def list_history_for_user(
        self, user_id: int, *, as_driver: bool, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        if as_driver:
            base = select(Order).where(Order.driver_id == user_id)
        else:
            base = select(Order).where(Order.customer_id == user_id)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        stmt = base.order_by(Order.created_at.desc()).limit(limit).offset(offset)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def get_active_for_customer(self, customer_id: int) -> list[Order]:
        stmt = (
            select(Order)
            .where(
                Order.customer_id == customer_id,
                Order.status.in_(ACTIVE_ORDER_STATUSES | {OrderStatus.PENDING}),
            )
            .order_by(Order.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_active_for_driver(self, driver_id: int) -> list[Order]:
        stmt = (
            select(Order)
            .where(
                Order.driver_id == driver_id,
                Order.status.in_(ACTIVE_ORDER_STATUSES),
            )
            .order_by(Order.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def driver_has_active_order(self, driver_id: int) -> bool:
        stmt = select(func.count(Order.id)).where(
            Order.driver_id == driver_id,
            Order.status.in_(ACTIVE_ORDER_STATUSES),
        )
        count = await self.session.scalar(stmt)
        return bool(count)
