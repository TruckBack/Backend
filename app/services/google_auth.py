"""Google OAuth2 authentication service.

Supports two flows:
  1. Authorization Code flow  — GET /auth/google  → redirect → GET /auth/google/callback
  2. ID-token exchange flow   — POST /auth/google/token  (mobile / SPA)

The module-level HTTP helpers (_fetch_tokeninfo, _exchange_code, _fetch_userinfo)
are intentionally importable so they can be patched in tests without mocking
the entire httpx.AsyncClient machinery.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

# ---------------------------------------------------------------------------
# Google endpoint constants
# ---------------------------------------------------------------------------
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


# ---------------------------------------------------------------------------
# Low-level HTTP helpers (patch these in tests)
# ---------------------------------------------------------------------------

async def _fetch_tokeninfo(id_token: str) -> tuple[int, dict]:
    """Call Google's tokeninfo endpoint to verify an ID token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(_GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
        return r.status_code, r.json()


async def _exchange_code(code: str, redirect_uri: str) -> tuple[int, dict]:
    """Exchange an authorization code for Google tokens."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return r.status_code, r.json()


async def _fetch_userinfo(access_token: str) -> tuple[int, dict]:
    """Fetch the authenticated user's profile from Google."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return r.status_code, r.json()


# ---------------------------------------------------------------------------
# Authorization URL helper (stateless, no DB needed)
# ---------------------------------------------------------------------------

def get_authorization_url(role: str) -> str:
    """Return the Google OAuth2 consent-screen URL.

    *role* is embedded in the ``state`` parameter so the callback knows which
    role to assign on first sign-up.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise BadRequestError("Google OAuth is not configured on this server")
    if role not in (UserRole.CUSTOMER.value, UserRole.DRIVER.value):
        raise BadRequestError(f"Invalid role '{role}'. Must be 'customer' or 'driver'")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": role,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class GoogleAuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_configured(self) -> None:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise BadRequestError("Google OAuth is not configured on this server")

    async def _find_or_create_user(
        self,
        google_id: str,
        email: str,
        full_name: str,
        role: UserRole,
    ) -> User:
        """Return an existing user or create a new one linked to a Google account.

        Lookup order:
        1. By ``google_id``  → fast path for returning users.
        2. By ``email``      → link an existing password account to Google.
        3. Create new user   → first-time Google sign-up.
        """
        # 1. Returning Google user
        user = await self.users.get_by_google_id(google_id)
        if user:
            if not user.is_active:
                raise UnauthorizedError("Account is disabled")
            return user

        # 2. Existing email account — link Google ID
        user = await self.users.get_by_email(email)
        if user:
            if not user.is_active:
                raise UnauthorizedError("Account is disabled")
            if user.role != role:
                raise UnauthorizedError(
                    f"This email is already registered as '{user.role.value}', "
                    f"not '{role.value}'"
                )
            user.google_id = google_id
            await self.db.commit()
            await self.db.refresh(user)
            return user

        # 3. Brand-new user
        user = User(
            email=email.lower(),
            # Random unguessable password — the user can never log in via password
            # unless they explicitly set one through a future "set password" flow.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=full_name or email.split("@")[0],
            role=role,
            google_id=google_id,
            is_active=True,
        )
        await self.users.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def login_with_id_token(self, id_token: str, role: str) -> User:
        """Verify a Google ID token received from the frontend and return the user.

        Suitable for mobile apps and SPAs that handle the Google sign-in
        client-side and send the resulting ID token to the backend.
        """
        self._require_configured()
        if role not in (UserRole.CUSTOMER.value, UserRole.DRIVER.value):
            raise BadRequestError(f"Invalid role '{role}'")
        try:
            role_enum = UserRole(role)
        except ValueError:
            raise BadRequestError(f"Invalid role '{role}'")

        status_code, info = await _fetch_tokeninfo(id_token)
        if status_code != 200:
            raise UnauthorizedError("Invalid or expired Google ID token")

        # Validate audience (must match our client ID)
        if info.get("aud") != settings.GOOGLE_CLIENT_ID:
            raise UnauthorizedError("Google token audience mismatch")

        if info.get("email_verified") not in ("true", True):
            raise UnauthorizedError("Google account email is not verified")

        google_id: str | None = info.get("sub")
        email: str | None = info.get("email")
        full_name: str = info.get("name") or ""

        if not google_id or not email:
            raise UnauthorizedError("Incomplete profile returned by Google")

        return await self._find_or_create_user(google_id, email, full_name, role_enum)

    async def handle_callback(self, code: str, state: str) -> User:
        """Exchange an authorization code (from Google's redirect) for a user.

        *state* must contain the role string that was passed to
        :func:`get_authorization_url`.
        """
        self._require_configured()
        if state not in (UserRole.CUSTOMER.value, UserRole.DRIVER.value):
            raise BadRequestError(f"Invalid role in OAuth state: '{state}'")
        try:
            role_enum = UserRole(state)
        except ValueError:
            raise BadRequestError(f"Invalid role in OAuth state: '{state}'")
        # Exchange auth code → Google tokens
        token_status, token_data = await _exchange_code(code, settings.GOOGLE_REDIRECT_URI)
        if token_status != 200:
            error_desc = token_data.get("error_description", token_data.get("error", "unknown"))
            raise UnauthorizedError(f"Google code exchange failed: {error_desc}")

        access_token: str | None = token_data.get("access_token")
        if not access_token:
            raise UnauthorizedError("No access token in Google response")

        # Fetch user profile
        info_status, user_info = await _fetch_userinfo(access_token)
        if info_status != 200:
            raise UnauthorizedError("Failed to fetch user profile from Google")

        google_id: str | None = user_info.get("id")
        email: str | None = user_info.get("email")
        full_name: str = user_info.get("name") or ""

        if not google_id or not email:
            raise UnauthorizedError("Incomplete profile returned by Google")

        return await self._find_or_create_user(google_id, email, full_name, role_enum)
