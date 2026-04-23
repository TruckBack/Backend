"""Smaller meta checks: health, docs, CORS, error shape."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health(app):
    # /health is outside the /api/v1 prefix
    from httpx import ASGITransport, AsyncClient as AC

    async with AC(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        r = await ac.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


async def test_openapi_schema_served(app):
    from httpx import ASGITransport, AsyncClient as AC

    async with AC(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        r = await ac.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        # All core paths must be present
        paths = schema["paths"]
        for p in (
            "/api/v1/auth/register/customer",
            "/api/v1/auth/register/driver",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/users/me",
            "/api/v1/drivers/me/profile",
            "/api/v1/drivers/me/status",
            "/api/v1/drivers/me/location",
            "/api/v1/uploads/image/profile",
            "/api/v1/orders",
            "/api/v1/orders/available",
            "/api/v1/orders/history",
            "/api/v1/orders/me/active",
            "/api/v1/orders/{order_id}",
            "/api/v1/orders/{order_id}/accept",
            "/api/v1/orders/{order_id}/start",
            "/api/v1/orders/{order_id}/pickup",
            "/api/v1/orders/{order_id}/complete",
            "/api/v1/orders/{order_id}/cancel",
        ):
            assert p in paths, f"missing {p}"


async def test_error_envelope_shape_on_404(client: AsyncClient, customer: dict):
    r = await client.get("/orders/424242", headers=customer["headers"])
    assert r.status_code == 404
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


async def test_error_envelope_on_validation(client: AsyncClient):
    r = await client.post("/auth/register/customer", json={"email": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["details"], list)
