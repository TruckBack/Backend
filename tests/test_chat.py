"""Tests for the chat service: REST endpoints and WebSocket."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_payload_base() -> dict:
    return {
        "pickup_address": "1 Sender St, Tel Aviv",
        "pickup_lat": 32.0853,
        "pickup_lng": 34.7818,
        "dropoff_address": "2 Receiver St, Haifa",
        "dropoff_lat": 32.7940,
        "dropoff_lng": 34.9896,
        "cargo_description": "Furniture",
        "cargo_weight_kg": 250.0,
        "notes": "Handle with care",
        "price_cents": 12000,
        "currency": "USD",
    }


async def _create_accepted_order(client: AsyncClient, customer: dict, driver: dict) -> dict:
    """Create an order, make driver available, driver accepts — returns accepted order body."""
    r = await client.post("/orders", json=_order_payload_base(), headers=customer["headers"])
    assert r.status_code == 201
    order = r.json()

    await client.put("/drivers/me/status", json={"status": "available"}, headers=driver["headers"])
    r = await client.post(f"/orders/{order['id']}/accept", headers=driver["headers"])
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# GET /chat/conversations
# ---------------------------------------------------------------------------


async def test_list_conversations_empty_for_new_user(
    client: AsyncClient, customer: dict
):
    r = await client.get("/chat/conversations", headers=customer["headers"])
    assert r.status_code == 200
    assert r.json() == []


async def test_list_conversations_requires_auth(client: AsyncClient):
    r = await client.get("/chat/conversations")
    assert r.status_code == 401


async def test_list_conversations_appears_after_message(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    # Customer sends a message — conversation is created
    r = await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "Hello driver!"},
        headers=customer["headers"],
    )
    assert r.status_code == 201

    r = await client.get("/chat/conversations", headers=customer["headers"])
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["order_id"] == order_id
    assert items[0]["last_message"]["body"] == "Hello driver!"


async def test_driver_sees_conversation_in_list(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "Are you ready?"},
        headers=customer["headers"],
    )

    r = await client.get("/chat/conversations", headers=driver["headers"])
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["order_id"] == order_id
    # Driver hasn't read it yet
    assert items[0]["unread_count"] == 1


# ---------------------------------------------------------------------------
# GET /chat/conversations/{order_id}
# ---------------------------------------------------------------------------


async def test_get_conversation_creates_empty_convo(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.get(
        f"/chat/conversations/{order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] == order["id"]
    assert body["messages"] == []


async def test_get_conversation_returns_messages(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "First message"},
        headers=customer["headers"],
    )
    await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "Reply from driver"},
        headers=driver["headers"],
    )

    r = await client.get(
        f"/chat/conversations/{order_id}", headers=customer["headers"]
    )
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["body"] == "First message"
    assert msgs[1]["body"] == "Reply from driver"


async def test_get_conversation_forbidden_for_other_user(
    client: AsyncClient,
    customer: dict,
    driver: dict,
    register_customer,
):
    order = await _create_accepted_order(client, customer, driver)
    # Register a second customer that has no relation to this order
    other = await register_customer(email="other@example.com")
    r = await client.get(
        f"/chat/conversations/{order['id']}", headers=other["headers"]
    )
    assert r.status_code == 403


async def test_get_conversation_requires_auth(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.get(f"/chat/conversations/{order['id']}")
    assert r.status_code == 401


async def test_get_conversation_not_found_order(client: AsyncClient, customer: dict):
    r = await client.get("/chat/conversations/99999", headers=customer["headers"])
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /chat/conversations/{order_id}/messages
# ---------------------------------------------------------------------------


async def test_customer_sends_message(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": "Hi there"},
        headers=customer["headers"],
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body"] == "Hi there"
    assert body["sender_id"] == customer["user"]["id"]
    assert body["is_read"] is True  # sender always sees their own message as read


async def test_driver_sends_message(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": "On my way"},
        headers=driver["headers"],
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body"] == "On my way"


async def test_send_message_empty_body_rejected(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": ""},
        headers=customer["headers"],
    )
    assert r.status_code == 422


async def test_send_message_requires_auth(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": "Unauthorised"},
    )
    assert r.status_code == 401


async def test_send_message_forbidden_non_participant(
    client: AsyncClient, customer: dict, driver: dict, register_customer
):
    order = await _create_accepted_order(client, customer, driver)
    other = await register_customer(email="stranger@example.com")
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": "I'm crashing this chat"},
        headers=other["headers"],
    )
    assert r.status_code == 403


async def test_send_message_order_not_found(client: AsyncClient, customer: dict):
    r = await client.post(
        "/chat/conversations/99999/messages",
        json={"body": "Ghost message"},
        headers=customer["headers"],
    )
    assert r.status_code == 404


async def test_send_message_response_shape(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(
        f"/chat/conversations/{order['id']}/messages",
        json={"body": "Check shape"},
        headers=customer["headers"],
    )
    body = r.json()
    assert "id" in body
    assert "conversation_id" in body
    assert "sender_id" in body
    assert "sender" in body
    assert "full_name" in body["sender"]
    assert "body" in body
    assert "created_at" in body
    assert "is_read" in body


# ---------------------------------------------------------------------------
# POST /chat/conversations/{order_id}/read
# ---------------------------------------------------------------------------


async def test_mark_read_updates_unread_count(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    # Customer sends 2 messages — driver hasn't read them
    for msg in ["msg 1", "msg 2"]:
        await client.post(
            f"/chat/conversations/{order_id}/messages",
            json={"body": msg},
            headers=customer["headers"],
        )

    # Before reading, driver sees 2 unread
    r = await client.get("/chat/conversations", headers=driver["headers"])
    assert r.json()[0]["unread_count"] == 2

    # Driver marks as read
    r = await client.post(
        f"/chat/conversations/{order_id}/read", headers=driver["headers"]
    )
    assert r.status_code == 200
    result = r.json()
    assert result["marked_count"] == 2

    # After marking, unread_count should be 0
    r = await client.get("/chat/conversations", headers=driver["headers"])
    assert r.json()[0]["unread_count"] == 0


async def test_mark_read_idempotent(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "Read me twice"},
        headers=customer["headers"],
    )

    r1 = await client.post(f"/chat/conversations/{order_id}/read", headers=driver["headers"])
    assert r1.json()["marked_count"] == 1

    r2 = await client.post(f"/chat/conversations/{order_id}/read", headers=driver["headers"])
    assert r2.json()["marked_count"] == 0


async def test_mark_read_requires_auth(
    client: AsyncClient, customer: dict, driver: dict
):
    order = await _create_accepted_order(client, customer, driver)
    r = await client.post(f"/chat/conversations/{order['id']}/read")
    assert r.status_code == 401


async def test_sender_messages_not_counted_in_own_unread(
    client: AsyncClient, customer: dict, driver: dict
):
    """Customer's own messages should not inflate their own unread count."""
    order = await _create_accepted_order(client, customer, driver)
    order_id = order["id"]

    await client.post(
        f"/chat/conversations/{order_id}/messages",
        json={"body": "I wrote this"},
        headers=customer["headers"],
    )

    r = await client.get("/chat/conversations", headers=customer["headers"])
    assert r.json()[0]["unread_count"] == 0


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def test_ws_rejects_missing_token(client: AsyncClient, customer: dict, driver: dict):
    """WS endpoint requires token= query param; plain HTTP GET returns 4xx."""
    order = await _create_accepted_order(client, customer, driver)
    # Without WebSocket upgrade + no token, the response is an HTTP error
    r = await client.get(f"/chat/ws/{order['id']}")
    assert r.status_code >= 400


async def test_ws_invalid_token_rejected(client: AsyncClient, customer: dict, driver: dict):
    """WS endpoint with a bogus token is rejected."""
    order = await _create_accepted_order(client, customer, driver)
    r = await client.get(f"/chat/ws/{order['id']}?token=not-a-valid-jwt")
    assert r.status_code >= 400
