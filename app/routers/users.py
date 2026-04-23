from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.user import UserMe, UserPublic, UserUpdate
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMe)
async def get_me(current_user: CurrentUser) -> UserMe:
    return UserMe.model_validate(current_user)


@router.put("/me", response_model=UserMe)
async def update_me(
    payload: UserUpdate, current_user: CurrentUser, db: DbSession
) -> UserMe:
    updated = await UserService(db).update_me(current_user, payload)
    return UserMe.model_validate(updated)


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: int, db: DbSession, _: CurrentUser) -> UserPublic:
    user = await UserService(db).get_by_id(user_id)
    return UserPublic.model_validate(user)
