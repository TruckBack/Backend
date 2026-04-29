from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ForbiddenError,
    InvalidStateError,
    NotFoundError,
)
from app.models.driver import DriverStatus
from app.models.order import ORDER_TRANSITIONS, Order, OrderStatus
from app.models.user import User, UserRole
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.schemas.order import OrderCancel, OrderCreate, OrderUpdate


class OrderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.orders = OrderRepository(db)
        self.drivers = DriverRepository(db)

    @staticmethod
    def _ensure_transition(current: OrderStatus, target: OrderStatus) -> None:
        if target not in ORDER_TRANSITIONS[current]:
            raise InvalidStateError(
                f"Cannot transition from {current.value} to {target.value}"
            )

    async def get_for_user(self, order_id: int, user: User) -> Order:
        order = await self.orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order not found")
        if user.role == UserRole.ADMIN:
            return order
        if user.role == UserRole.CUSTOMER and order.customer_id == user.id:
            return order
        if user.role == UserRole.DRIVER:
            driver = await self.drivers.get_by_user_id(user.id)
            if driver and order.driver_id == driver.id:
                return order
            # Drivers can also view pending orders (the available pool)
            if order.status == OrderStatus.PENDING:
                return order
        raise ForbiddenError("You do not have access to this order")

    async def create(self, customer: User, data: OrderCreate) -> Order:
        if customer.role != UserRole.CUSTOMER:
            raise ForbiddenError("Only customers can create orders")
        order = Order(customer_id=customer.id, **data.model_dump())
        await self.orders.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def list_available(self, limit: int, offset: int):
        return await self.orders.list_available(limit=limit, offset=offset)

    async def list_history(self, user: User, *, limit: int, offset: int):
        if user.role == UserRole.DRIVER:
            driver = await self.drivers.get_by_user_id(user.id)
            if not driver:
                return [], 0
            return await self.orders.list_history_for_user(
                driver.id, as_driver=True, limit=limit, offset=offset
            )
        return await self.orders.list_history_for_user(
            user.id, as_driver=False, limit=limit, offset=offset
        )

    async def list_active(self, user: User) -> list[Order]:
        if user.role == UserRole.DRIVER:
            driver = await self.drivers.get_by_user_id(user.id)
            if not driver:
                return []
            return await self.orders.get_active_for_driver(driver.id)
        return await self.orders.get_active_for_customer(user.id)

    async def accept(self, order_id: int, user: User) -> Order:
        if user.role != UserRole.DRIVER:
            raise ForbiddenError("Only drivers can accept orders")
        driver = await self.drivers.get_by_user_id(user.id)
        if not driver:
            raise NotFoundError("Driver profile not found")
        if driver.status != DriverStatus.AVAILABLE:
            raise BadRequestError("Driver must be available to accept orders")
        if await self.orders.driver_has_active_order(driver.id):
            raise BadRequestError("Driver already has an active order")

        # Lock the row to avoid two drivers grabbing the same order
        order = await self.orders.get_by_id_for_update(order_id)
        if not order:
            raise NotFoundError("Order not found")
        self._ensure_transition(order.status, OrderStatus.ACCEPTED)

        order.status = OrderStatus.ACCEPTED
        order.driver_id = driver.id
        order.accepted_at = datetime.now(timezone.utc)
        driver.status = DriverStatus.BUSY

        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def _driver_action(
        self,
        order_id: int,
        user: User,
        target: OrderStatus,
        timestamp_field: str,
    ) -> Order:
        if user.role != UserRole.DRIVER:
            raise ForbiddenError("Only drivers can perform this action")
        driver = await self.drivers.get_by_user_id(user.id)
        if not driver:
            raise NotFoundError("Driver profile not found")

        order = await self.orders.get_by_id_for_update(order_id)
        if not order:
            raise NotFoundError("Order not found")
        if order.driver_id != driver.id:
            raise ForbiddenError("This order is not assigned to you")

        self._ensure_transition(order.status, target)
        order.status = target
        setattr(order, timestamp_field, datetime.now(timezone.utc))

        if target == OrderStatus.COMPLETED:
            driver.status = DriverStatus.AVAILABLE

        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def start(self, order_id: int, user: User) -> Order:
        return await self._driver_action(order_id, user, OrderStatus.IN_PROGRESS, "started_at")

    async def pickup(self, order_id: int, user: User) -> Order:
        return await self._driver_action(order_id, user, OrderStatus.PICKED_UP, "picked_up_at")

    async def complete(self, order_id: int, user: User) -> Order:
        return await self._driver_action(order_id, user, OrderStatus.COMPLETED, "completed_at")

    async def update(self, order_id: int, user: User, data: OrderUpdate) -> Order:
        order = await self.orders.get_by_id_for_update(order_id)
        if not order:
            raise NotFoundError("Order not found")
        is_owner = user.role == UserRole.CUSTOMER and order.customer_id == user.id
        if not (is_owner or user.role == UserRole.ADMIN):
            raise ForbiddenError("Only the customer who created this order can edit it")
        if order.status != OrderStatus.PENDING:
            raise BadRequestError("Only pending orders can be edited")
        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(order, field, value)
        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def delete(self, order_id: int, user: User) -> None:
        order = await self.orders.get_by_id_for_update(order_id)
        if not order:
            raise NotFoundError("Order not found")
        is_owner = user.role == UserRole.CUSTOMER and order.customer_id == user.id
        if not (is_owner or user.role == UserRole.ADMIN):
            raise ForbiddenError("Only the customer who created this order can delete it")
        if order.status != OrderStatus.PENDING:
            raise BadRequestError("Only pending orders can be deleted; cancel active orders instead")
        await self.orders.delete(order)
        await self.db.commit()

    async def cancel(self, order_id: int, user: User, data: OrderCancel) -> Order:
        order = await self.orders.get_by_id_for_update(order_id)
        if not order:
            raise NotFoundError("Order not found")

        # Permission: customer (own) or assigned driver or admin
        is_owner = user.role == UserRole.CUSTOMER and order.customer_id == user.id
        is_admin = user.role == UserRole.ADMIN
        is_assigned_driver = False
        driver = None
        if user.role == UserRole.DRIVER:
            driver = await self.drivers.get_by_user_id(user.id)
            is_assigned_driver = bool(driver and order.driver_id == driver.id)
        if not (is_owner or is_admin or is_assigned_driver):
            raise ForbiddenError("You cannot cancel this order")

        self._ensure_transition(order.status, OrderStatus.CANCELLED)

        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancellation_reason = data.reason

        if driver and order.driver_id == driver.id:
            driver.status = DriverStatus.AVAILABLE

        await self.db.commit()
        await self.db.refresh(order)
        return order
