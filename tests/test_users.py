"""/users endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_get_me_returns_current_user(client: AsyncClient, customer: dict):
    r = await client.get("/users/me", headers=customer["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == customer["user"]["email"]
    assert body["role"] == "customer"
    assert body["is_active"] is True


async def test_update_me_patches_allowed_fields(client: AsyncClient, customer: dict):
    r = await client.put(
        "/users/me",
        json={"full_name": "Alice The Great", "phone": "+15559998888"},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Alice The Great"
    assert body["phone"] == "+15559998888"


async def test_update_me_ignores_unknown_fields(client: AsyncClient, customer: dict):
    r = await client.put(
        "/users/me",
        json={"role": "admin", "is_active": False, "full_name": "Renamed"},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    # Role / is_active are not in UserUpdate and must not change
    assert body["role"] == "customer"
    assert body["is_active"] is True
    assert body["full_name"] == "Renamed"


async def test_update_me_validation(client: AsyncClient, customer: dict):
    r = await client.put(
        "/users/me", json={"full_name": ""}, headers=customer["headers"]
    )
    assert r.status_code == 422


async def test_get_user_public_by_id(
    client: AsyncClient, customer: dict, driver: dict
):
    r = await client.get(f"/users/{driver['user']['id']}", headers=customer["headers"])
    assert r.status_code == 200
    body = r.json()
    # Public view only
    assert body["id"] == driver["user"]["id"]
    assert body["full_name"] == driver["user"]["full_name"]
    assert body["role"] == "driver"
    assert "email" not in body
    assert "phone" not in body


async def test_get_user_by_id_not_found(client: AsyncClient, customer: dict):
    r = await client.get("/users/999999", headers=customer["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_get_user_requires_auth(client: AsyncClient, customer: dict):
    r = await client.get(f"/users/{customer['user']['id']}")
    assert r.status_code == 401
