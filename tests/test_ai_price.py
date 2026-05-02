"""Tests for POST /api/v1/aiprice.

All Gemini HTTP calls are patched at the module-level ``_call_gemini``
function so no real network requests are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

FAKE_GEMINI_RESPONSE = {
    "candidates": [
        {
            "content": {
                "parts": [{"text": "Estimated price: $35–$55 USD. Based on size and fragile cargo."}],
                "role": "model",
            }
        }
    ]
}

SAMPLE_MESSAGE = (
    "Please estimate a fair delivery price (in USD) for the following shipment:\n"
    "- Package Type: Box\n"
    "- Delivery Date: 2026-05-01\n"
    "- Pickup Time: 10:00\n"
    "- Dimensions: 40x30x20 cm\n"
    "- Description: Fragile glassware\n"
    "Based on these details, provide a concise price estimation with a brief explanation."
)


def _mock_gemini(response_dict: dict | None = None, status: int = 200):
    return AsyncMock(return_value=(status, response_dict or FAKE_GEMINI_RESPONSE))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_gemini_key(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-gemini-key")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_aiprice_returns_result(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Happy path: authenticated user gets a price estimate."""
    _patch_gemini_key(monkeypatch)
    with patch("app.services.ai_price._call_gemini", _mock_gemini()):
        r = await client.post(
            "/aiprice",
            json={"message": SAMPLE_MESSAGE},
            headers=customer["headers"],
        )
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert "$35" in body["result"]


async def test_aiprice_driver_can_call(
    client: AsyncClient, driver: dict, monkeypatch
):
    """Drivers are also allowed to use the AI pricing endpoint."""
    _patch_gemini_key(monkeypatch)
    with patch("app.services.ai_price._call_gemini", _mock_gemini()):
        r = await client.post(
            "/aiprice",
            json={"message": SAMPLE_MESSAGE},
            headers=driver["headers"],
        )
    assert r.status_code == 200
    assert "result" in r.json()


async def test_aiprice_requires_auth(client: AsyncClient, monkeypatch):
    """Unauthenticated request must be rejected with 401."""
    _patch_gemini_key(monkeypatch)
    r = await client.post("/aiprice", json={"message": SAMPLE_MESSAGE})
    assert r.status_code == 401


async def test_aiprice_not_configured(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Returns 400 when GEMINI_API_KEY is empty."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    r = await client.post(
        "/aiprice",
        json={"message": SAMPLE_MESSAGE},
        headers=customer["headers"],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_aiprice_gemini_api_error(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Gemini returning a non-200 maps to 500 InternalServerError."""
    _patch_gemini_key(monkeypatch)
    with patch(
        "app.services.ai_price._call_gemini",
        _mock_gemini({"error": {"message": "quota exceeded"}}, status=429),
    ):
        r = await client.post(
            "/aiprice",
            json={"message": SAMPLE_MESSAGE},
            headers=customer["headers"],
        )
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_server_error"


async def test_aiprice_empty_message_rejected(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Empty message string must fail Pydantic validation (422)."""
    _patch_gemini_key(monkeypatch)
    r = await client.post(
        "/aiprice",
        json={"message": ""},
        headers=customer["headers"],
    )
    assert r.status_code == 422


async def test_aiprice_missing_message_rejected(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Missing message field must fail Pydantic validation (422)."""
    _patch_gemini_key(monkeypatch)
    r = await client.post(
        "/aiprice",
        json={},
        headers=customer["headers"],
    )
    assert r.status_code == 422


async def test_aiprice_response_shape(
    client: AsyncClient, customer: dict, monkeypatch
):
    """Response must be exactly { result: string }."""
    _patch_gemini_key(monkeypatch)
    with patch("app.services.ai_price._call_gemini", _mock_gemini()):
        r = await client.post(
            "/aiprice",
            json={"message": SAMPLE_MESSAGE},
            headers=customer["headers"],
        )
    assert r.status_code == 200
    body = r.json()
    assert list(body.keys()) == ["result"]
    assert isinstance(body["result"], str)
    assert len(body["result"]) > 0
