"""Google OAuth2 routes — end-to-end tests with mocked Google API calls.

All external HTTP calls are patched at the module-function level so no real
network requests are made during the test run.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.security import TokenType, decode_token

# ---------------------------------------------------------------------------
# Shared fake data
# ---------------------------------------------------------------------------
FAKE_GOOGLE_CLIENT_ID = "test-google-client-id-12345"

FAKE_TOKENINFO_CUSTOMER = {
    "sub": "google-uid-customer-001",
    "email": "google.customer@gmail.com",
    "name": "Google Customer",
    "email_verified": "true",
    "aud": FAKE_GOOGLE_CLIENT_ID,
}

FAKE_TOKENINFO_DRIVER = {
    "sub": "google-uid-driver-001",
    "email": "google.driver@gmail.com",
    "name": "Google Driver",
    "email_verified": "true",
    "aud": FAKE_GOOGLE_CLIENT_ID,
}

FAKE_ACCESS_TOKEN = "ya29.fake_google_access_token"

FAKE_TOKEN_EXCHANGE = {
    "access_token": FAKE_ACCESS_TOKEN,
    "token_type": "Bearer",
    "expires_in": 3600,
}

FAKE_USERINFO_CUSTOMER = {
    "id": "google-uid-cust-callback-001",
    "email": "callback.customer@gmail.com",
    "name": "Callback Customer",
    "verified_email": True,
}

FAKE_USERINFO_DRIVER = {
    "id": "google-uid-drv-callback-001",
    "email": "callback.driver@gmail.com",
    "name": "Callback Driver",
    "verified_email": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_settings_google(monkeypatch):
    """Inject fake Google credentials into Settings (via lru_cache bypass)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", FAKE_GOOGLE_CLIENT_ID)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(
        settings,
        "GOOGLE_REDIRECT_URI",
        "http://testserver/api/v1/auth/google/callback",
    )


def _mock_tokeninfo(tokeninfo_dict: dict):
    """Return an async mock for _fetch_tokeninfo that succeeds."""
    return AsyncMock(return_value=(200, tokeninfo_dict))


def _mock_exchange_code(token_dict: dict | None = None):
    return AsyncMock(return_value=(200, token_dict or FAKE_TOKEN_EXCHANGE))


def _mock_userinfo(userinfo_dict: dict):
    return AsyncMock(return_value=(200, userinfo_dict))


# ---------------------------------------------------------------------------
# GET /auth/google — authorization URL
# ---------------------------------------------------------------------------


async def test_google_auth_url_returned(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    r = await client.get("/auth/google?role=customer")
    assert r.status_code == 200
    body = r.json()
    assert "url" in body
    url = body["url"]
    assert "accounts.google.com" in url
    assert "response_type=code" in url
    assert "state=customer" in url
    assert FAKE_GOOGLE_CLIENT_ID in url


async def test_google_auth_url_driver_role(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    r = await client.get("/auth/google?role=driver")
    assert r.status_code == 200
    assert "state=driver" in r.json()["url"]


async def test_google_auth_url_invalid_role(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    r = await client.get("/auth/google?role=admin")
    assert r.status_code == 400


async def test_google_auth_url_not_configured(client: AsyncClient):
    """When GOOGLE_CLIENT_ID is empty the endpoint should return 400."""
    r = await client.get("/auth/google?role=customer")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# POST /auth/google/token — ID-token exchange (mobile / SPA flow)
# ---------------------------------------------------------------------------


async def test_google_token_creates_new_customer(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with patch(
        "app.services.google_auth._fetch_tokeninfo",
        _mock_tokeninfo(FAKE_TOKENINFO_CUSTOMER),
    ):
        r = await client.post(
            "/auth/google/token",
            json={"id_token": "fake.id.token", "role": "customer"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    decoded = decode_token(body["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "customer"


async def test_google_token_creates_new_driver(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with patch(
        "app.services.google_auth._fetch_tokeninfo",
        _mock_tokeninfo(FAKE_TOKENINFO_DRIVER),
    ):
        r = await client.post(
            "/auth/google/token",
            json={"id_token": "fake.id.token", "role": "driver"},
        )
    assert r.status_code == 200
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "driver"


async def test_google_token_idempotent_for_returning_user(client: AsyncClient, monkeypatch):
    """Second login with same google_id returns same user, not a duplicate."""
    _patch_settings_google(monkeypatch)
    tokeninfo = {**FAKE_TOKENINFO_CUSTOMER, "sub": "google-uid-returning-001", "email": "returning@gmail.com"}
    mock = _mock_tokeninfo(tokeninfo)
    with patch("app.services.google_auth._fetch_tokeninfo", mock):
        r1 = await client.post("/auth/google/token", json={"id_token": "t", "role": "customer"})
        r2 = await client.post("/auth/google/token", json={"id_token": "t", "role": "customer"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both tokens decode to the same user
    sub1 = decode_token(r1.json()["access_token"], expected_type=TokenType.ACCESS)["sub"]
    sub2 = decode_token(r2.json()["access_token"], expected_type=TokenType.ACCESS)["sub"]
    assert sub1 == sub2


async def test_google_token_links_existing_password_account(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Google login with the same email as an existing password account links them."""
    _patch_settings_google(monkeypatch)
    existing_email = customer["user"]["email"]
    tokeninfo = {
        **FAKE_TOKENINFO_CUSTOMER,
        "sub": "google-uid-link-001",
        "email": existing_email,
    }
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(tokeninfo)):
        r = await client.post("/auth/google/token", json={"id_token": "t", "role": "customer"})

    assert r.status_code == 200
    # User id in token should match the existing user
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert int(decoded["sub"]) == customer["user"]["id"]


async def test_google_token_wrong_role_for_existing_email(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Customer email cannot log in via Google with role=driver."""
    _patch_settings_google(monkeypatch)
    existing_email = customer["user"]["email"]
    tokeninfo = {
        **FAKE_TOKENINFO_CUSTOMER,
        "sub": "google-uid-role-mismatch-001",
        "email": existing_email,
    }
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(tokeninfo)):
        r = await client.post("/auth/google/token", json={"id_token": "t", "role": "driver"})

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_google_token_rejects_invalid_token(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with patch(
        "app.services.google_auth._fetch_tokeninfo",
        AsyncMock(return_value=(400, {"error": "invalid_token"})),
    ):
        r = await client.post(
            "/auth/google/token",
            json={"id_token": "garbage.token", "role": "customer"},
        )
    assert r.status_code == 401


async def test_google_token_rejects_wrong_audience(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    tokeninfo = {**FAKE_TOKENINFO_CUSTOMER, "aud": "different-client-id"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(tokeninfo)):
        r = await client.post(
            "/auth/google/token",
            json={"id_token": "fake.id.token", "role": "customer"},
        )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_google_token_rejects_unverified_email(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    tokeninfo = {**FAKE_TOKENINFO_CUSTOMER, "email_verified": "false"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(tokeninfo)):
        r = await client.post(
            "/auth/google/token",
            json={"id_token": "fake.id.token", "role": "customer"},
        )
    assert r.status_code == 401


async def test_google_token_missing_role_rejected(client: AsyncClient, monkeypatch):
    """role is required — omitting it returns 422."""
    _patch_settings_google(monkeypatch)
    r = await client.post("/auth/google/token", json={"id_token": "fake.id.token"})
    assert r.status_code == 422


async def test_google_token_not_configured(client: AsyncClient):
    """Returns 400 when GOOGLE_CLIENT_ID is not set."""
    r = await client.post(
        "/auth/google/token",
        json={"id_token": "fake.id.token", "role": "customer"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /auth/google/callback — authorization-code callback
# ---------------------------------------------------------------------------


async def test_google_callback_creates_customer(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with (
        patch("app.services.google_auth._exchange_code", _mock_exchange_code()),
        patch(
            "app.services.google_auth._fetch_userinfo",
            _mock_userinfo(FAKE_USERINFO_CUSTOMER),
        ),
    ):
        r = await client.get("/auth/google/callback?code=auth_code_123&state=customer")

    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    decoded = decode_token(body["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "customer"


async def test_google_callback_creates_driver(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with (
        patch("app.services.google_auth._exchange_code", _mock_exchange_code()),
        patch(
            "app.services.google_auth._fetch_userinfo",
            _mock_userinfo(FAKE_USERINFO_DRIVER),
        ),
    ):
        r = await client.get("/auth/google/callback?code=auth_code_456&state=driver")

    assert r.status_code == 200
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "driver"


async def test_google_callback_invalid_code(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with patch(
        "app.services.google_auth._exchange_code",
        AsyncMock(return_value=(400, {"error": "invalid_grant", "error_description": "Code expired"})),
    ):
        r = await client.get("/auth/google/callback?code=expired_code&state=customer")

    assert r.status_code == 401


async def test_google_callback_invalid_state(client: AsyncClient, monkeypatch):
    """state must be a valid role string."""
    _patch_settings_google(monkeypatch)
    r = await client.get("/auth/google/callback?code=some_code&state=superadmin")
    assert r.status_code == 400


async def test_google_callback_not_configured(client: AsyncClient):
    r = await client.get("/auth/google/callback?code=abc&state=customer")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Token returned by Google login works for protected endpoints
# ---------------------------------------------------------------------------


async def test_google_user_can_access_protected_endpoint(client: AsyncClient, monkeypatch):
    """A user created via Google login can call authenticated endpoints."""
    _patch_settings_google(monkeypatch)
    unique_info = {
        **FAKE_TOKENINFO_CUSTOMER,
        "sub": "google-uid-protected-001",
        "email": "protected_access@gmail.com",
    }
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(unique_info)):
        login_r = await client.post(
            "/auth/google/token",
            json={"id_token": "fake.id.token", "role": "customer"},
        )
    assert login_r.status_code == 200

    access_token = login_r.json()["access_token"]
    me_r = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_r.status_code == 200
    assert me_r.json()["email"] == "protected_access@gmail.com"


# ---------------------------------------------------------------------------
# POST /auth/google  — simplified endpoint (id_token only, role optional)
# ---------------------------------------------------------------------------


async def test_post_google_creates_customer_default_role(client: AsyncClient, monkeypatch):
    """POST /auth/google with only id_token defaults to role='customer'."""
    _patch_settings_google(monkeypatch)
    info = {**FAKE_TOKENINFO_CUSTOMER, "sub": "pg-uid-001", "email": "pg_default@gmail.com"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(info)):
        r = await client.post("/auth/google", json={"id_token": "fake.id.token"})
    assert r.status_code == 200
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "customer"


async def test_post_google_driver_role(client: AsyncClient, monkeypatch):
    """POST /auth/google with role='driver' creates a driver account."""
    _patch_settings_google(monkeypatch)
    info = {**FAKE_TOKENINFO_DRIVER, "sub": "pg-uid-drv-001", "email": "pg_driver@gmail.com"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(info)):
        r = await client.post("/auth/google", json={"id_token": "fake.id.token", "role": "driver"})
    assert r.status_code == 200
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "driver"


async def test_post_google_returns_standard_token_response(client: AsyncClient, monkeypatch):
    """Response shape must match TokenResponse (access_token, refresh_token, token_type, expires_in)."""
    _patch_settings_google(monkeypatch)
    info = {**FAKE_TOKENINFO_CUSTOMER, "sub": "pg-uid-shape-001", "email": "pg_shape@gmail.com"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(info)):
        r = await client.post("/auth/google", json={"id_token": "fake.id.token"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_post_google_invalid_token(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    with patch(
        "app.services.google_auth._fetch_tokeninfo",
        AsyncMock(return_value=(400, {"error": "invalid_token"})),
    ):
        r = await client.post("/auth/google", json={"id_token": "bad_token"})
    assert r.status_code == 401


async def test_post_google_not_configured(client: AsyncClient):
    """Returns 400 when GOOGLE_CLIENT_ID is not set in env."""
    r = await client.post("/auth/google", json={"id_token": "fake.id.token"})
    assert r.status_code == 400


async def test_post_google_idempotent(client: AsyncClient, monkeypatch):
    """Two calls with the same google sub return the same user."""
    _patch_settings_google(monkeypatch)
    info = {**FAKE_TOKENINFO_CUSTOMER, "sub": "pg-uid-idem-001", "email": "pg_idem@gmail.com"}
    mock = _mock_tokeninfo(info)
    with patch("app.services.google_auth._fetch_tokeninfo", mock):
        r1 = await client.post("/auth/google", json={"id_token": "t"})
        r2 = await client.post("/auth/google", json={"id_token": "t"})
    sub1 = decode_token(r1.json()["access_token"], expected_type=TokenType.ACCESS)["sub"]
    sub2 = decode_token(r2.json()["access_token"], expected_type=TokenType.ACCESS)["sub"]
    assert sub1 == sub2


async def test_post_google_user_accesses_protected_endpoint(client: AsyncClient, monkeypatch):
    _patch_settings_google(monkeypatch)
    info = {**FAKE_TOKENINFO_CUSTOMER, "sub": "pg-uid-prot-001", "email": "pg_prot@gmail.com"}
    with patch("app.services.google_auth._fetch_tokeninfo", _mock_tokeninfo(info)):
        login_r = await client.post("/auth/google", json={"id_token": "fake.id.token"})
    assert login_r.status_code == 200
    token = login_r.json()["access_token"]
    me_r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_r.status_code == 200
    assert me_r.json()["email"] == "pg_prot@gmail.com"
