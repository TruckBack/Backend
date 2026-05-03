from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.order import OrderStatus
from app.models.rating import DriverRating
from app.models.user import User, UserRole
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.repositories.rating import RatingRepository
from app.schemas.rating import RatingCreate, RatingRead, RatingResponseCreate


class RatingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ratings = RatingRepository(db)
        self.orders = OrderRepository(db)
        self.drivers = DriverRepository(db)

    async def submit_rating(
        self, order_id: int, customer: User, data: RatingCreate
    ) -> RatingRead:
        if customer.role != UserRole.CUSTOMER:
            raise ForbiddenError("Only customers can submit ratings")

        order = await self.orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order not found")
        if order.customer_id != customer.id:
            raise ForbiddenError("You are not the customer for this order")
        if order.status != OrderStatus.COMPLETED:
            raise BadRequestError("Ratings can only be submitted for completed orders")
        if order.driver_id is None:
            raise BadRequestError("This order has no assigned driver")

        existing = await self.ratings.get_by_order_id(order_id)
        if existing is not None:
            raise ConflictError("This order has already been rated")

        rating = DriverRating(
            order_id=order_id,
            driver_id=order.driver_id,
            customer_id=customer.id,
            score=data.score,
            comment=data.comment,
        )
        await self.ratings.add(rating)

        # Recalculate the driver's aggregate rating after flushing the new row
        await self.db.flush()
        new_avg = await self.ratings.get_average_for_driver(order.driver_id)
        driver = await self.drivers.get_by_id(order.driver_id)
        if driver:
            driver.rating = new_avg

        await self.db.commit()
        await self.db.refresh(rating)
        return RatingRead.model_validate(rating)

    async def get_rating_for_order(self, order_id: int, user: User) -> RatingRead:
        order = await self.orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order not found")

        # Only the customer, the assigned driver, or an admin may view the rating
        if user.role == UserRole.CUSTOMER and order.customer_id != user.id:
            raise ForbiddenError("You do not have access to this order's rating")
        if user.role == UserRole.DRIVER:
            driver = await self.drivers.get_by_user_id(user.id)
            if not driver or order.driver_id != driver.id:
                raise ForbiddenError("You do not have access to this order's rating")

        rating = await self.ratings.get_by_order_id(order_id)
        if rating is None:
            raise NotFoundError("No rating found for this order")
        return RatingRead.model_validate(rating)

    async def list_driver_ratings(
        self, driver_id: int, *, limit: int, offset: int
    ) -> tuple[list[RatingRead], int]:
        driver = await self.drivers.get_by_id(driver_id)
        if not driver:
            raise NotFoundError("Driver not found")
        items, total = await self.ratings.list_for_driver(
            driver_id, limit=limit, offset=offset
        )
        return [RatingRead.model_validate(r) for r in items], total

    async def respond_to_rating(
        self, order_id: int, driver_user: User, data: RatingResponseCreate
    ) -> RatingRead:
        """Driver posts or updates their public response to a customer rating."""
        if driver_user.role != UserRole.DRIVER:
            raise ForbiddenError("Only drivers can respond to ratings")

        order = await self.orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order not found")

        driver = await self.drivers.get_by_user_id(driver_user.id)
        if not driver:
            raise NotFoundError("Driver profile not found")
        if order.driver_id != driver.id:
            raise ForbiddenError("You are not the driver for this order")

        rating = await self.ratings.get_by_order_id(order_id)
        if rating is None:
            raise NotFoundError("No rating found for this order — nothing to respond to")

        # Allow updating an existing response (overwrite)
        rating.driver_response = data.response
        rating.driver_responded_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(rating)
        return RatingRead.model_validate(rating)

    async def delete_response(
        self, order_id: int, driver_user: User
    ) -> RatingRead:
        """Driver removes their response from a rating."""
        if driver_user.role != UserRole.DRIVER:
            raise ForbiddenError("Only drivers can delete their responses")

        order = await self.orders.get_by_id(order_id)
        if not order:
            raise NotFoundError("Order not found")

        driver = await self.drivers.get_by_user_id(driver_user.id)
        if not driver:
            raise NotFoundError("Driver profile not found")
        if order.driver_id != driver.id:
            raise ForbiddenError("You are not the driver for this order")

        rating = await self.ratings.get_by_order_id(order_id)
        if rating is None:
            raise NotFoundError("No rating found for this order")
        if rating.driver_response is None:
            raise NotFoundError("No response to delete")

        rating.driver_response = None
        rating.driver_responded_at = None

        await self.db.commit()
        await self.db.refresh(rating)
        return RatingRead.model_validate(rating)
