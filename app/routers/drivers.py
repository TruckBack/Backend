from __future__ import annotations

from fastapi import APIRouter, status

from app.core.dependencies import CurrentDriver, DbSession
from app.schemas.driver import (
    DriverLocationUpdate,
    DriverProfile,
    DriverProfileUpdate,
    DriverStatusUpdate,
)
from app.services.driver import DriverService

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
