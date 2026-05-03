from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.rating import DriverRating
    from app.models.user import User


class DriverStatus(StrEnum):
    OFFLINE = "offline"
    AVAILABLE = "available"
    BUSY = "busy"


class Driver(Base, IdMixin, TimestampMixin):
    __tablename__ = "drivers"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    license_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(String(32), nullable=False)
    vehicle_capacity_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[DriverStatus] = mapped_column(
        Enum(DriverStatus, name="driver_status", values_callable=lambda e: [m.value for m in e]),
        default=DriverStatus.OFFLINE,
        nullable=False,
        index=True,
    )

    current_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="driver")
    orders: Mapped[list["Order"]] = relationship(back_populates="driver")
    ratings: Mapped[list["DriverRating"]] = relationship(back_populates="driver")
