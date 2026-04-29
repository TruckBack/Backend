from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.dependencies import DbSession
from app.schemas.auth import (
    CustomerRegister,
    DriverRegister,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.user import UserMe
from app.services.auth import AuthService
from typing import Annotated

from fastapi import Depends

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register/customer",
    response_model=UserMe,
    status_code=status.HTTP_201_CREATED,
)
async def register_customer(payload: CustomerRegister, db: DbSession) -> UserMe:
    user = await AuthService(db).register_customer(payload)
    return UserMe.model_validate(user)


@router.post(
    "/register/driver",
    response_model=UserMe,
    status_code=status.HTTP_201_CREATED,
)
async def register_driver(payload: DriverRegister, db: DbSession) -> UserMe:
    user = await AuthService(db).register_driver(payload)
    return UserMe.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    db: DbSession,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """OAuth2-compatible login (form fields: username=email, password)."""
    service = AuthService(db)
    user = await service.authenticate(form.username, form.password)
    return service.issue_tokens(user)


@router.post("/login/json", response_model=TokenResponse)
async def login_json(payload: LoginRequest, db: DbSession) -> TokenResponse:
    service = AuthService(db)
    user = await service.authenticate(payload.email, payload.password, role=payload.role)
    return service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    return await AuthService(db).refresh(payload.refresh_token)
