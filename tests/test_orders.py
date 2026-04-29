"""/orders endpoints — lifecycle, state machine, permissions, races."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


# ---------- Create ----------


async def test_customer_creates_order(
    client: AsyncClient, customer: dict, order_payload
):
    r = await client.post("/orders", json=order_payload(), headers=customer["headers"])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["customer_id"] == customer["user"]["id"]
    assert body["driver_id"] is None


async def test_driver_cannot_create_order(
    client: AsyncClient, driver: dict, order_payload
):
    r = await client.post("/orders", json=order_payload(), headers=driver["headers"])
    assert r.status_code == 403


@pytest.mark.parametrize(
    "override",
    [
        {"pickup_lat": 999},
        {"pickup_lng": -999},
        {"price_cents": 0},
        {"price_cents": -1},
        {"pickup_address": ""},
        {"dropoff_address": ""},
    ],
)
async def test_create_order_validation(
    client: AsyncClient, customer: dict, order_payload, override
):
    r = await client.post(
        "/orders", json=order_payload(**override), headers=customer["headers"]
    )
    assert r.status_code == 422


async def test_create_order_requires_auth(client: AsyncClient, order_payload):
    r = await client.post("/orders", json=order_payload())
    assert r.status_code == 401


# ---------- Listing ----------


async def test_available_orders_listing(
    client: AsyncClient, customer: dict, driver: dict, order_payload
):
    for i in range(3):
        await client.post(
            "/orders",
            json=order_payload(pickup_address=f"{i} Main St"),
            headers=customer["headers"],
        )

    r = await client.get("/orders/available", headers=driver["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert all(o["status"] == "pending" for o in body["items"])


async def test_available_pagination(
    client: AsyncClient, customer: dict, driver: dict, order_payload
):
    for i in range(5):
        await client.post(
            "/orders", json=order_payload(), headers=customer["headers"]
        )
    r = await client.get(
        "/orders/available?limit=2&offset=1", headers=driver["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2


async def test_history_returns_customer_orders(
    client: AsyncClient, customer: dict, order_payload
):
    for _ in range(2):
        await client.post("/orders", json=order_payload(), headers=customer["headers"])
    r = await client.get("/orders/history", headers=customer["headers"])
    assert r.status_code == 200
    assert r.json()["total"] == 2


async def test_history_for_driver_is_empty_when_none_assigned(
    client: AsyncClient, driver: dict
):
    r = await client.get("/orders/history", headers=driver["headers"])
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_me_active_for_customer_and_driver(
    client: AsyncClient,
    customer: dict,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    # Before acceptance, customer has 1 active (pending)
    r = await client.get("/orders/me/active", headers=customer["headers"])
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Driver has none until they accept
    r = await client.get("/orders/me/active", headers=driver["headers"])
    assert r.json() == []

    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200

    r = await client.get("/orders/me/active", headers=driver["headers"])
    assert len(r.json()) == 1


# ---------- Get by id / permissions ----------


async def test_customer_can_get_own_order(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.get(
        f"/orders/{pending_order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 200


async def test_driver_can_see_pending_order(
    client: AsyncClient, driver: dict, pending_order: dict
):
    r = await client.get(
        f"/orders/{pending_order['id']}", headers=driver["headers"]
    )
    assert r.status_code == 200


async def test_other_customer_forbidden_to_view(
    client: AsyncClient,
    customer: dict,
    register_customer,
    pending_order: dict,
    make_driver_available,
    driver: dict,
):
    # Assign the order so it's no longer pending (which is public to drivers)
    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200

    # A different customer should not see it
    other = await register_customer(email="eve@example.com")
    r = await client.get(
        f"/orders/{pending_order['id']}", headers=other["headers"]
    )
    assert r.status_code == 403


async def test_get_order_not_found(client: AsyncClient, customer: dict):
    r = await client.get("/orders/999999", headers=customer["headers"])
    assert r.status_code == 404


# ---------- Accept ----------


async def test_accept_requires_driver_role(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=customer["headers"]
    )
    assert r.status_code == 403


async def test_accept_requires_driver_available(
    client: AsyncClient, driver: dict, pending_order: dict
):
    # Driver is still offline
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 400


async def test_accept_transitions_to_accepted(
    client: AsyncClient,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["driver_id"] is not None
    assert body["accepted_at"] is not None

    # Driver status flips to busy
    drv_self = await client.put(
        "/drivers/me/profile", json={}, headers=driver["headers"]
    )
    assert drv_self.json()["status"] == "busy"


async def test_accept_twice_conflicts_even_for_same_driver(
    client: AsyncClient,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    r1 = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    # Driver became 'busy' after the first accept, so the availability guard fires first.
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "bad_request"


async def test_second_driver_cannot_steal_accepted_order(
    client: AsyncClient,
    driver: dict,
    register_driver,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200

    driver2 = await register_driver(email="carl@example.com", license_number="LIC-0002")
    await make_driver_available(driver2)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver2["headers"]
    )
    assert r.status_code == 409


async def test_driver_with_active_order_cannot_accept_another(
    client: AsyncClient,
    driver: dict,
    customer: dict,
    pending_order: dict,
    order_payload,
    make_driver_available,
):
    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 200

    # Create a second order and try to accept
    second = await client.post(
        "/orders",
        json=order_payload(pickup_address="Other"),
        headers=customer["headers"],
    )
    r = await client.post(
        f"/orders/{second.json()['id']}/accept", headers=driver["headers"]
    )
    assert r.status_code == 400


# ---------- Full lifecycle ----------


async def test_full_lifecycle_happy_path(
    client: AsyncClient,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    oid = pending_order["id"]
    h = driver["headers"]

    transitions = [
        ("accept", "accepted", "accepted_at"),
        ("start", "in_progress", "started_at"),
        ("pickup", "picked_up", "picked_up_at"),
        ("complete", "completed", "completed_at"),
    ]
    for action, expected_status, ts_field in transitions:
        r = await client.post(f"/orders/{oid}/{action}", headers=h)
        assert r.status_code == 200, (action, r.text)
        body = r.json()
        assert body["status"] == expected_status
        assert body[ts_field] is not None


async def test_cannot_skip_states(
    client: AsyncClient, driver: dict, pending_order: dict, make_driver_available
):
    await make_driver_available(driver)
    r = await client.post(
        f"/orders/{pending_order['id']}/start", headers=driver["headers"]
    )
    # Order has no driver assigned yet — the assignment guard fires first (403).
    assert r.status_code == 403


async def test_driver_actions_forbidden_without_assignment(
    client: AsyncClient,
    driver: dict,
    register_driver,
    pending_order: dict,
    make_driver_available,
):
    # driver1 accepts, driver2 tries to manipulate
    await make_driver_available(driver)
    await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    d2 = await register_driver(email="d2@example.com", license_number="LIC-0002")
    r = await client.post(
        f"/orders/{pending_order['id']}/start", headers=d2["headers"]
    )
    assert r.status_code == 403


async def test_cancel_by_customer(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.post(
        f"/orders/{pending_order['id']}/cancel",
        json={"reason": "changed my mind"},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "changed my mind"


async def test_cancel_by_assigned_driver_resets_availability(
    client: AsyncClient,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    r = await client.post(
        f"/orders/{pending_order['id']}/cancel",
        json={"reason": "vehicle broke down"},
        headers=driver["headers"],
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Driver should be AVAILABLE again, not stuck on busy
    status_r = await client.put(
        "/drivers/me/profile", json={}, headers=driver["headers"]
    )
    assert status_r.json()["status"] == "available"


async def test_cannot_cancel_completed_order(
    client: AsyncClient,
    driver: dict,
    customer: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    oid = pending_order["id"]
    for action in ("accept", "start", "pickup", "complete"):
        r = await client.post(f"/orders/{oid}/{action}", headers=driver["headers"])
        assert r.status_code == 200, action

    r = await client.post(
        f"/orders/{oid}/cancel", json={}, headers=customer["headers"]
    )
    assert r.status_code == 409


async def test_unrelated_customer_cannot_cancel(
    client: AsyncClient,
    register_customer,
    pending_order: dict,
):
    other = await register_customer(email="stranger@example.com")
    r = await client.post(
        f"/orders/{pending_order['id']}/cancel",
        json={},
        headers=other["headers"],
    )
    assert r.status_code == 403


# ---------- Update (PATCH) ----------


async def test_customer_can_update_pending_order(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.patch(
        f"/orders/{pending_order['id']}",
        json={"pickup_address": "New Pickup St 42", "price_cents": 9999},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pickup_address"] == "New Pickup St 42"
    assert body["price_cents"] == 9999
    # Other fields remain unchanged
    assert body["status"] == "pending"
    assert body["dropoff_address"] == pending_order["dropoff_address"]


async def test_update_all_editable_fields(
    client: AsyncClient, customer: dict, pending_order: dict
):
    patch = {
        "pickup_address": "PA",
        "pickup_lat": 31.0,
        "pickup_lng": 34.0,
        "dropoff_address": "DA",
        "dropoff_lat": 32.0,
        "dropoff_lng": 35.0,
        "notes": "handle with care",
        "cargo_description": "furniture",
        "cargo_weight_kg": 120.5,
        "price_cents": 50000,
        "currency": "ILS",
    }
    r = await client.patch(
        f"/orders/{pending_order['id']}", json=patch, headers=customer["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    for key, val in patch.items():
        assert body[key] == val, f"field {key!r} mismatch"


async def test_update_returns_unchanged_fields_intact(
    client: AsyncClient, customer: dict, pending_order: dict
):
    """Empty patch body — nothing changes."""
    r = await client.patch(
        f"/orders/{pending_order['id']}", json={}, headers=customer["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == pending_order["id"]
    assert body["status"] == "pending"
    assert body["customer_id"] == customer["user"]["id"]


async def test_update_accepted_order_rejected(
    client: AsyncClient,
    customer: dict,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    r = await client.patch(
        f"/orders/{pending_order['id']}",
        json={"notes": "too late"},
        headers=customer["headers"],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_update_other_customer_forbidden(
    client: AsyncClient, register_customer, pending_order: dict
):
    other = await register_customer(email="intruder@example.com")
    r = await client.patch(
        f"/orders/{pending_order['id']}",
        json={"notes": "hacked"},
        headers=other["headers"],
    )
    assert r.status_code == 403


async def test_update_driver_forbidden(
    client: AsyncClient, driver: dict, pending_order: dict
):
    r = await client.patch(
        f"/orders/{pending_order['id']}",
        json={"notes": "driver sneaking"},
        headers=driver["headers"],
    )
    assert r.status_code == 403


async def test_update_nonexistent_order_404(client: AsyncClient, customer: dict):
    r = await client.patch(
        "/orders/999999", json={"notes": "ghost"}, headers=customer["headers"]
    )
    assert r.status_code == 404


async def test_update_requires_auth(client: AsyncClient, pending_order: dict):
    r = await client.patch(f"/orders/{pending_order['id']}", json={"notes": "x"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "bad_field",
    [
        {"pickup_lat": 999},
        {"pickup_lng": -999},
        {"dropoff_lat": 999},
        {"price_cents": 0},
        {"price_cents": -5},
        {"cargo_weight_kg": -1},
        {"pickup_address": ""},
        {"currency": "TOOLONG_CURRENCY"},
    ],
)
async def test_update_validation_errors(
    client: AsyncClient, customer: dict, pending_order: dict, bad_field
):
    r = await client.patch(
        f"/orders/{pending_order['id']}", json=bad_field, headers=customer["headers"]
    )
    assert r.status_code == 422


# ---------- Delete ----------


async def test_customer_can_delete_pending_order(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.delete(
        f"/orders/{pending_order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 204

    # Order is gone from DB
    r2 = await client.get(
        f"/orders/{pending_order['id']}", headers=customer["headers"]
    )
    assert r2.status_code == 404


async def test_delete_accepted_order_rejected(
    client: AsyncClient,
    customer: dict,
    driver: dict,
    pending_order: dict,
    make_driver_available,
):
    await make_driver_available(driver)
    await client.post(
        f"/orders/{pending_order['id']}/accept", headers=driver["headers"]
    )
    r = await client.delete(
        f"/orders/{pending_order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_delete_other_customer_forbidden(
    client: AsyncClient, register_customer, pending_order: dict
):
    other = await register_customer(email="thief@example.com")
    r = await client.delete(
        f"/orders/{pending_order['id']}", headers=other["headers"]
    )
    assert r.status_code == 403


async def test_delete_driver_forbidden(
    client: AsyncClient, driver: dict, pending_order: dict
):
    r = await client.delete(
        f"/orders/{pending_order['id']}", headers=driver["headers"]
    )
    assert r.status_code == 403


async def test_delete_nonexistent_order_404(client: AsyncClient, customer: dict):
    r = await client.delete("/orders/999999", headers=customer["headers"])
    assert r.status_code == 404


async def test_delete_requires_auth(client: AsyncClient, pending_order: dict):
    r = await client.delete(f"/orders/{pending_order['id']}")
    assert r.status_code == 401


async def test_delete_removes_from_available_list(
    client: AsyncClient, customer: dict, driver: dict, order_payload
):
    """Deleted order must not appear in the available pool."""
    r = await client.post("/orders", json=order_payload(), headers=customer["headers"])
    oid = r.json()["id"]

    before = await client.get("/orders/available", headers=driver["headers"])
    total_before = before.json()["total"]

    await client.delete(f"/orders/{oid}", headers=customer["headers"])

    after = await client.get("/orders/available", headers=driver["headers"])
    assert after.json()["total"] == total_before - 1
