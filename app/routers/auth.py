from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.dependencies import DbSession
from app.schemas.auth import (
    CustomerRegister,
    DriverRegister,
    GoogleAuthUrlResponse,
    GoogleCallbackRequest,
    GoogleIdTokenRequest,
    GoogleTokenRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.user import UserMe
from app.services.auth import AuthService
from app.services.google_auth import GoogleAuthService, get_authorization_url
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


# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------


@router.get("/google", response_model=GoogleAuthUrlResponse)
async def google_auth_url(
    role: str = "customer",
) -> GoogleAuthUrlResponse:
    """Return the Google consent-screen URL.

    The frontend should redirect the user to ``url``.
    After consent, Google redirects back to ``/auth/google/callback``.
    """
    url = get_authorization_url(role)
    return GoogleAuthUrlResponse(url=url)


@router.post("/google", response_model=TokenResponse)
async def google_login(
    payload: GoogleIdTokenRequest, db: DbSession
) -> TokenResponse:
    """Verify a Google ID token and return TruckBack JWT tokens.

    Accepts ``{ id_token: string }`` — the token obtained from Google
    client-side (One Tap, JS SDK, or mobile SDKs).
    ``role`` is optional and defaults to ``'customer'``.
    """
    user = await GoogleAuthService(db).login_with_id_token(
        id_token=payload.id_token, role=payload.role.value
    )
    return AuthService(db).issue_tokens(user)


@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    code: str,
    state: str,
    db: DbSession,
) -> TokenResponse:
    """Handle Google's authorization-code redirect.

    Google calls this URL after the user grants consent.
    Returns JWT tokens directly (suitable for SPAs that open the callback
    in a popup/redirect and read the JSON response).
    """
    user = await GoogleAuthService(db).handle_callback(code=code, state=state)
    return AuthService(db).issue_tokens(user)


@router.post("/google/token", response_model=TokenResponse)
async def google_token(
    payload: GoogleTokenRequest, db: DbSession
) -> TokenResponse:
    """Verify a Google ID token and return TruckBack JWT tokens.

    Suitable for mobile apps / SPAs that handle Google sign-in client-side
    (e.g. via Google One Tap or the JS SDK) and send the resulting ID token
    to the backend.
    """
    user = await GoogleAuthService(db).login_with_id_token(
        id_token=payload.id_token, role=payload.role.value
    )
    return AuthService(db).issue_tokens(user)
