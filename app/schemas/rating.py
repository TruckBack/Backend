from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class RatingCreate(ORMModel):
    score: int = Field(ge=1, le=5, description="Rating score from 1 (worst) to 5 (best)")
    comment: str | None = Field(default=None, max_length=1000)


class RatingResponseCreate(ORMModel):
    response: str = Field(min_length=1, max_length=2000)


class RatingRead(ORMModel):
    id: int
    order_id: int
    driver_id: int
    customer_id: int
    score: int
    comment: str | None
    created_at: datetime
    driver_response: str | None = None
    driver_responded_at: datetime | None = None
