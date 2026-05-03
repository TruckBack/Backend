from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentDriver, CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.driver import (
    DriverLocationUpdate,
    DriverProfile,
    DriverProfileUpdate,
    DriverStatusUpdate,
)
from app.schemas.rating import RatingRead
from app.services.driver import DriverService
from app.services.rating import RatingService

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.put("/me/profile", response_model=DriverProfile)
async def update_profile(
    payload: DriverProfileUpdate, current: CurrentDriver, db: DbSession
) -> DriverProfile:
    driver = await DriverService(db).update_profile(current, payload)
    return DriverProfile.model_validate(driver)


@router.put("/me/status", response_model=DriverProfile)
async def update_status(
    payload: DriverStatusUpdate, current: CurrentDriver, db: DbSession
) -> DriverProfile:
    driver = await DriverService(db).update_status(current, payload)
    return DriverProfile.model_validate(driver)


@router.post(
    "/me/location",
    response_model=DriverProfile,
    status_code=status.HTTP_200_OK,
)
async def update_location(
    payload: DriverLocationUpdate, current: CurrentDriver, db: DbSession
) -> DriverProfile:
    driver = await DriverService(db).update_location(current, payload)
    return DriverProfile.model_validate(driver)


@router.get(
    "/{driver_id}/ratings",
    response_model=Page[RatingRead],
    summary="List all ratings for a driver",
)
async def list_driver_ratings(
    driver_id: int,
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RatingRead]:
    items, total = await RatingService(db).list_driver_ratings(
        driver_id, limit=limit, offset=offset
    )
    return Page[RatingRead](items=items, total=total, limit=limit, offset=offset)
