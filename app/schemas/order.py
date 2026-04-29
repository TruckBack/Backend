from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.order import OrderStatus
from app.schemas.common import ORMModel


class OrderCreate(ORMModel):
    pickup_address: str = Field(min_length=1, max_length=512)
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    dropoff_address: str = Field(min_length=1, max_length=512)
    dropoff_lat: float = Field(ge=-90, le=90)
    dropoff_lng: float = Field(ge=-180, le=180)
    cargo_description: str | None = Field(default=None, max_length=512)
    cargo_weight_kg: float | None = Field(default=None, gt=0)
    notes: str | None = None
    price_cents: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)


class OrderUpdate(ORMModel):
    """Partial update schema — all fields optional (PATCH semantics)."""

    pickup_address: str | None = Field(default=None, min_length=1, max_length=512)
    pickup_lat: float | None = Field(default=None, ge=-90, le=90)
    pickup_lng: float | None = Field(default=None, ge=-180, le=180)
    dropoff_address: str | None = Field(default=None, min_length=1, max_length=512)
    dropoff_lat: float | None = Field(default=None, ge=-90, le=90)
    dropoff_lng: float | None = Field(default=None, ge=-180, le=180)
    cargo_description: str | None = Field(default=None, max_length=512)
    cargo_weight_kg: float | None = Field(default=None, gt=0)
    notes: str | None = None
    price_cents: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)


class OrderCancel(ORMModel):
    reason: str | None = Field(default=None, max_length=512)


class OrderRead(ORMModel):
    id: int
    customer_id: int
    driver_id: int | None
    status: OrderStatus
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    dropoff_address: str
    dropoff_lat: float
    dropoff_lng: float
    cargo_description: str | None = None
    cargo_weight_kg: float | None = None
    notes: str | None = None
    price_cents: int
    currency: str
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    picked_up_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class OrderStatusEvent(ORMModel):
    order_id: int
    status: OrderStatus
    at: datetime
