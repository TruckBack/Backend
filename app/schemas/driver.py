from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.driver import DriverStatus
from app.schemas.common import ORMModel


class DriverProfile(ORMModel):
    id: int
    user_id: int
    license_number: str
    vehicle_type: str
    vehicle_plate: str
    vehicle_capacity_kg: float | None = None
    status: DriverStatus
    current_lat: float | None = None
    current_lng: float | None = None
    last_location_at: datetime | None = None
    rating: float


class DriverProfileUpdate(ORMModel):
    vehicle_type: str | None = Field(default=None, min_length=1, max_length=64)
    vehicle_plate: str | None = Field(default=None, min_length=1, max_length=32)
    vehicle_capacity_kg: float | None = Field(default=None, gt=0)


class DriverStatusUpdate(ORMModel):
    status: DriverStatus


class DriverLocationUpdate(ORMModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class DriverLocationBroadcast(ORMModel):
    driver_id: int
    order_id: int
    lat: float
    lng: float
    at: datetime
