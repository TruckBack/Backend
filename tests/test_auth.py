"""Authentication: register, login, refresh, token edge cases."""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

from app.core.security import TokenType, create_access_token, create_refresh_token, decode_token


# ---------- Registration ----------


async def test_register_customer_returns_201_and_user(client: AsyncClient, customer_payload):
    r = await client.post("/auth/register/customer", json=customer_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "customer"
    assert body["is_active"] is True
    assert "id" in body
    # Never leak the password hash
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_customer_rejects_duplicate_email(
    client: AsyncClient, customer_payload
):
    await client.post("/auth/register/customer", json=customer_payload())
    r = await client.post("/auth/register/customer", json=customer_payload())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "overrides,expected_field",
    [
        ({"email": "not-an-email"}, "email"),
        ({"password": "short"}, "password"),
        ({"full_name": ""}, "full_name"),
    ],
)
async def test_register_customer_validation(
    client: AsyncClient, customer_payload, overrides, expected_field
):
    r = await client.post("/auth/register/customer", json=customer_payload(**overrides))
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert any(expected_field in ".".join(str(p) for p in err["loc"]) for err in body["error"]["details"])


async def test_register_driver_creates_driver_profile(
    client: AsyncClient, driver_payload, register_driver
):
    session = await register_driver()
    assert session["user"]["role"] == "driver"
    # Driver is offline by default — confirm via the protected profile update route
    r = await client.put(
        "/drivers/me/profile",
        json={"vehicle_type": "truck"},
        headers=session["headers"],
    )
    assert r.status_code == 200
    assert r.json()["vehicle_type"] == "truck"


async def test_register_driver_rejects_duplicate_license(
    client: AsyncClient, driver_payload
):
    await client.post("/auth/register/driver", json=driver_payload())
    # Same license, different email
    r = await client.post(
        "/auth/register/driver",
        json=driver_payload(email="other@example.com"),
    )
    assert r.status_code == 409


async def test_register_driver_rejects_duplicate_email(
    client: AsyncClient, driver_payload
):
    await client.post("/auth/register/driver", json=driver_payload())
    r = await client.post(
        "/auth/register/driver",
        json=driver_payload(license_number="LIC-9999"),
    )
    assert r.status_code == 409


# ---------- Login ----------


async def test_login_json_returns_tokens(client: AsyncClient, customer_payload):
    payload = customer_payload()
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": payload["password"], "role": "customer"},
    )
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0
    for key in ("access_token", "refresh_token"):
        assert tokens[key]

    # Access token has the proper claims
    decoded = decode_token(tokens["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "customer"
    assert decoded["sub"]


async def test_login_oauth2_form(client: AsyncClient, customer_payload):
    payload = customer_payload()
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


async def test_login_wrong_password(client: AsyncClient, customer_payload):
    payload = customer_payload()
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": "wrong-password", "role": "customer"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_login_unknown_email(client: AsyncClient):
    r = await client.post(
        "/auth/login/json",
        json={"email": "ghost@example.com", "password": "whatever123", "role": "customer"},
    )
    assert r.status_code == 401


async def test_login_is_case_insensitive_for_email(client: AsyncClient, customer_payload):
    payload = customer_payload(email="MIXED@Example.com")
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": "mixed@example.com", "password": payload["password"], "role": "customer"},
    )
    assert r.status_code == 200


# ---------- Refresh ----------


async def test_refresh_returns_new_tokens(client: AsyncClient, customer: dict):
    time.sleep(1)  # ensure a different iat on the new token
    r = await client.post(
        "/auth/refresh", json={"refresh_token": customer["tokens"]["refresh_token"]}
    )
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]


async def test_refresh_rejects_access_token_as_refresh(client: AsyncClient, customer: dict):
    r = await client.post(
        "/auth/refresh", json={"refresh_token": customer["tokens"]["access_token"]}
    )
    assert r.status_code == 401


async def test_refresh_rejects_garbage(client: AsyncClient):
    r = await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


# ---------- Access token enforcement ----------


async def test_missing_token_is_unauthorized(client: AsyncClient):
    r = await client.get("/users/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_invalid_token_is_unauthorized(client: AsyncClient):
    r = await client.get("/users/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_refresh_token_cannot_be_used_as_access(client: AsyncClient, customer: dict):
    r = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {customer['tokens']['refresh_token']}"},
    )
    assert r.status_code == 401


async def test_token_for_nonexistent_user_rejected(client: AsyncClient):
    # Forge a token for a user id that never existed in this DB
    token = create_access_token(999999, role="customer")
    r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_refresh_for_nonexistent_user_rejected(client: AsyncClient):
    rt = create_refresh_token(999999)
    r = await client.post("/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401


# ---------- Role-based login ----------


async def test_login_wrong_role_customer_as_driver(
    client: AsyncClient, customer_payload
):
    """A customer account cannot log in with role='driver'."""
    payload = customer_payload()
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": payload["password"], "role": "driver"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_login_wrong_role_driver_as_customer(
    client: AsyncClient, driver_payload
):
    """A driver account cannot log in with role='customer'."""
    payload = driver_payload()
    await client.post("/auth/register/driver", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": payload["password"], "role": "customer"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_login_correct_role_driver(
    client: AsyncClient, driver_payload
):
    """A driver can log in with role='driver'."""
    payload = driver_payload()
    await client.post("/auth/register/driver", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": payload["password"], "role": "driver"},
    )
    assert r.status_code == 200
    decoded = decode_token(r.json()["access_token"], expected_type=TokenType.ACCESS)
    assert decoded["role"] == "driver"


async def test_login_missing_role_rejected(client: AsyncClient, customer_payload):
    """role is required — omitting it returns 422."""
    payload = customer_payload()
    await client.post("/auth/register/customer", json=payload)
    r = await client.post(
        "/auth/login/json",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert r.status_code == 422
