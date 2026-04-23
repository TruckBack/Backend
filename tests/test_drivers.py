"""/drivers endpoints (driver-only)."""

from __future__ import annotations

from httpx import AsyncClient


async def test_customer_cannot_access_driver_routes(
    client: AsyncClient, customer: dict
):
    r = await client.put(
        "/drivers/me/profile",
        json={"vehicle_type": "truck"},
        headers=customer["headers"],
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


async def test_update_profile(client: AsyncClient, driver: dict):
    r = await client.put(
        "/drivers/me/profile",
        json={
            "vehicle_type": "pickup",
            "vehicle_plate": "ZZ-999-ZZ",
            "vehicle_capacity_kg": 750,
        },
        headers=driver["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["vehicle_type"] == "pickup"
    assert body["vehicle_plate"] == "ZZ-999-ZZ"
    assert body["vehicle_capacity_kg"] == 750


async def test_update_profile_partial(client: AsyncClient, driver: dict):
    r = await client.put(
        "/drivers/me/profile",
        json={"vehicle_type": "van"},
        headers=driver["headers"],
    )
    assert r.status_code == 200
    assert r.json()["vehicle_type"] == "van"


async def test_update_status_flow(client: AsyncClient, driver: dict):
    for status in ("available", "offline", "available"):
        r = await client.put(
            "/drivers/me/status",
            json={"status": status},
            headers=driver["headers"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status


async def test_update_status_rejects_invalid_value(client: AsyncClient, driver: dict):
    r = await client.put(
        "/drivers/me/status",
        json={"status": "flying"},
        headers=driver["headers"],
    )
    assert r.status_code == 422


async def test_post_location_updates_fields(client: AsyncClient, driver: dict):
    r = await client.post(
        "/drivers/me/location",
        json={"lat": 32.0853, "lng": 34.7818},
        headers=driver["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["current_lat"] == 32.0853
    assert body["current_lng"] == 34.7818
    assert body["last_location_at"] is not None


async def test_post_location_validates_range(client: AsyncClient, driver: dict):
    r = await client.post(
        "/drivers/me/location",
        json={"lat": 999, "lng": 0},
        headers=driver["headers"],
    )
    assert r.status_code == 422


async def test_driver_cannot_go_offline_with_active_order(
    client: AsyncClient,
    driver: dict,
    customer: dict,
    make_driver_available,
    order_payload,
):
    # Driver becomes available and accepts an order
    await make_driver_available(driver)
    order = (
        await client.post("/orders", json=order_payload(), headers=customer["headers"])
    ).json()
    r = await client.post(
        f"/orders/{order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200, r.text

    # Now attempting to go offline must fail
    r = await client.put(
        "/drivers/me/status",
        json={"status": "offline"},
        headers=driver["headers"],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"
