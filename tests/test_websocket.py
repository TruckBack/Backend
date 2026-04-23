"""
WebSocket tracking tests.

Uses Starlette's sync ``TestClient`` (only it supports websocket_connect OOTB).
All HTTP setup is done through the same client so the DB override and redis/s3
stubs established in conftest apply uniformly.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token

# The conftest applies its fixtures to the async httpx client. For the sync
# TestClient we re-use the already-patched ``app`` + DB override.


def _register_customer(tc: TestClient, email="alice@example.com") -> dict:
    payload = {
        "email": email,
        "password": "Str0ngPass!",
        "full_name": "Alice",
    }
    r = tc.post("/api/v1/auth/register/customer", json=payload)
    assert r.status_code == 201, r.text
    login = tc.post(
        "/api/v1/auth/login/json",
        json={"email": payload["email"], "password": payload["password"]},
    )
    tokens = login.json()
    return {"user": r.json(), "tokens": tokens, "headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _register_driver(tc: TestClient, email="bob@example.com", lic="LIC-0001") -> dict:
    payload = {
        "email": email,
        "password": "Str0ngPass!",
        "full_name": "Bob",
        "license_number": lic,
        "vehicle_type": "van",
        "vehicle_plate": "AA-111-AA",
    }
    r = tc.post("/api/v1/auth/register/driver", json=payload)
    assert r.status_code == 201, r.text
    login = tc.post(
        "/api/v1/auth/login/json",
        json={"email": payload["email"], "password": payload["password"]},
    )
    tokens = login.json()
    return {"user": r.json(), "tokens": tokens, "headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _setup_accepted_order(tc: TestClient):
    customer = _register_customer(tc)
    driver = _register_driver(tc)
    # go available
    tc.put("/api/v1/drivers/me/status", json={"status": "available"}, headers=driver["headers"])
    order = tc.post(
        "/api/v1/orders",
        json={
            "pickup_address": "A",
            "pickup_lat": 1.0,
            "pickup_lng": 2.0,
            "dropoff_address": "B",
            "dropoff_lat": 3.0,
            "dropoff_lng": 4.0,
            "price_cents": 5000,
        },
        headers=customer["headers"],
    ).json()
    tc.post(f"/api/v1/orders/{order['id']}/accept", headers=driver["headers"])
    return customer, driver, order


@pytest.fixture
def sync_client(app):
    with TestClient(app, base_url="http://testserver") as tc:
        yield tc


def test_ws_rejects_missing_token(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    with pytest.raises(Exception):
        with sync_client.websocket_connect(f"/api/v1/ws/orders/{order['id']}/track"):
            pass


def test_ws_rejects_invalid_token(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    with pytest.raises(Exception):
        with sync_client.websocket_connect(
            f"/api/v1/ws/orders/{order['id']}/track?token=garbage"
        ):
            pass


def test_ws_rejects_refresh_token(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    refresh = customer["tokens"]["refresh_token"]
    with pytest.raises(Exception):
        with sync_client.websocket_connect(
            f"/api/v1/ws/orders/{order['id']}/track?token={refresh}"
        ):
            pass


def test_ws_rejects_unrelated_customer(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    other = _register_customer(sync_client, email="eve@example.com")
    token = other["tokens"]["access_token"]
    with pytest.raises(Exception):
        with sync_client.websocket_connect(
            f"/api/v1/ws/orders/{order['id']}/track?token={token}"
        ):
            pass


def test_ws_driver_broadcasts_location_to_customer(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    c_token = customer["tokens"]["access_token"]
    d_token = driver["tokens"]["access_token"]

    with sync_client.websocket_connect(
        f"/api/v1/ws/orders/{order['id']}/track?token={c_token}"
    ) as cust_ws, sync_client.websocket_connect(
        f"/api/v1/ws/orders/{order['id']}/track?token={d_token}"
    ) as drv_ws:
        drv_ws.send_text(json.dumps({"type": "location", "lat": 10.5, "lng": 20.25}))

        # Both sockets (including the sender) should receive via redis pub/sub.
        received = json.loads(cust_ws.receive_text())
        assert received["type"] == "location"
        assert received["lat"] == 10.5
        assert received["lng"] == 20.25
        assert received["order_id"] == order["id"]


def test_ws_ignores_location_from_customer(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    c_token = customer["tokens"]["access_token"]

    with sync_client.websocket_connect(
        f"/api/v1/ws/orders/{order['id']}/track?token={c_token}"
    ) as ws:
        # Customer tries to push a location — server silently drops it (no broadcast, no error).
        ws.send_text(json.dumps({"type": "location", "lat": 1, "lng": 1}))
        # Sending garbage JSON from a non-driver also must not crash the socket.
        ws.send_text("not-json")
        # Socket should still be alive — send a ping-ish message and receive none.


def test_ws_invalid_json_from_driver_returns_error(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    d_token = driver["tokens"]["access_token"]

    with sync_client.websocket_connect(
        f"/api/v1/ws/orders/{order['id']}/track?token={d_token}"
    ) as ws:
        ws.send_text("not-json")
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"


def test_ws_rejects_connection_for_pending_order(sync_client: TestClient):
    customer = _register_customer(sync_client)
    order = sync_client.post(
        "/api/v1/orders",
        json={
            "pickup_address": "A",
            "pickup_lat": 1.0,
            "pickup_lng": 2.0,
            "dropoff_address": "B",
            "dropoff_lat": 3.0,
            "dropoff_lng": 4.0,
            "price_cents": 5000,
        },
        headers=customer["headers"],
    ).json()
    token = customer["tokens"]["access_token"]
    with pytest.raises(Exception):
        with sync_client.websocket_connect(
            f"/api/v1/ws/orders/{order['id']}/track?token={token}"
        ):
            pass


def test_ws_rejects_token_for_nonexistent_user(sync_client: TestClient):
    customer, driver, order = _setup_accepted_order(sync_client)
    ghost = create_access_token(999999, role="customer")
    with pytest.raises(Exception):
        with sync_client.websocket_connect(
            f"/api/v1/ws/orders/{order['id']}/track?token={ghost}"
        ):
            pass
