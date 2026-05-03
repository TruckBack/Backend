from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.driver import Driver
    from app.models.order import Order
    from app.models.user import User


class DriverRating(Base, IdMixin, TimestampMixin):
    """One rating per completed order, submitted by the customer.

    The driver may post a single public response (driver_response) after the
    rating is created.  The timestamp driver_responded_at records when the
    response was first submitted.
    """

    __tablename__ = "driver_ratings"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="ck_driver_ratings_score"),
    )

    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("drivers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Driver's public response to the review
    driver_response: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    driver_responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    order: Mapped["Order"] = relationship(back_populates="rating")
    driver: Mapped["Driver"] = relationship(back_populates="ratings")
    customer: Mapped["User"] = relationship(back_populates="given_ratings")
