"""
Test fixtures for the TruckBack backend.

Strategy:
- Replace the configured database with an in-memory SQLite (aiosqlite) per test,
  so every test gets a clean schema via ``Base.metadata.create_all``.
- Replace Redis with fakeredis (used by the WebSocket pub/sub manager).
- Replace the S3 presign helper with a deterministic fake.
- Override the FastAPI ``get_db`` dependency + monkeypatch the ``AsyncSessionLocal``
  referenced inside the WebSocket router (it does not use Depends).
"""

from __future__ import annotations

import asyncio
import os

# ---------------------------------------------------------------------------
# Environment must be set BEFORE importing the app, because ``app.core.config``
# is evaluated at import time (it constructs a singleton ``Settings``).
# ---------------------------------------------------------------------------
os.environ["SECRET_KEY"] = "test-secret-key-for-tests-only-xxxxxxxxxxxxxx"
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "true"
# The app's session module creates a pooled async engine at import time;
# SQLite rejects pool_size/max_overflow, so we point DATABASE_URL at a postgres
# URL (no connection is ever established — we override get_db everywhere).
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/unused"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"  # fakeredis is swapped in below
os.environ["CORS_ORIGINS"] = ""
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "14"

from typing import AsyncIterator, Callable

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Swap Redis BEFORE importing anything that might call get_redis().
import app.core.redis as redis_module  # noqa: E402

_fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
redis_module._redis = _fake_redis  # singleton slot, used by get_redis()


def _always_fake_redis():
    return _fake_redis


async def _noop_close_redis() -> None:
    return None


# Replace get_redis + close_redis in every module that already imported them
# (modules bind the symbol at import time, so patching app.core.redis alone
# is not enough once downstream modules are loaded).
redis_module.get_redis = _always_fake_redis
redis_module.close_redis = _noop_close_redis

from app.core.dependencies import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import session as db_session_module  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import Driver, DriverStatus, User, UserRole  # noqa: E402
from app.routers import ws as ws_router_module  # noqa: E402
from app.services import upload as upload_service_module  # noqa: E402
from app.services import ws_manager as ws_manager_module  # noqa: E402
import app.main as main_module  # noqa: E402

# Re-patch downstream bindings that captured the originals at import time.
ws_manager_module.get_redis = _always_fake_redis
main_module.get_redis = _always_fake_redis
main_module.close_redis = _noop_close_redis


# SQLite does NOT autoincrement BIGINT primary keys — only plain INTEGER.
# Remap BigInteger -> INTEGER at compile time for the sqlite dialect only.
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


# ---------------------------------------------------------------------------
# Fake S3: deterministic presigned URL (no network, no boto3 credentials).
# ---------------------------------------------------------------------------
async def _fake_presign(*, key: str, content_type: str, expires_in: int | None = None) -> str:
    return f"https://fake-s3.example/{key}?ct={content_type}"


upload_service_module.generate_presigned_put_url = _fake_presign


# ---------------------------------------------------------------------------
# Database: function-scoped in-memory SQLite with a shared connection.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_sessionmaker(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db(db_sessionmaker) -> AsyncIterator[AsyncSession]:
    async with db_sessionmaker() as session:
        yield session


# ---------------------------------------------------------------------------
# Wire the app to the per-test DB: dependency override + patch the
# ``AsyncSessionLocal`` used directly by the WebSocket router.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def app(db_sessionmaker):
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db

    # Patch module-level references so code paths that don't use Depends still hit the test DB.
    original_ws_sm = ws_router_module.AsyncSessionLocal
    original_db_sm = db_session_module.AsyncSessionLocal
    ws_router_module.AsyncSessionLocal = db_sessionmaker
    db_session_module.AsyncSessionLocal = db_sessionmaker

    # Flush fake redis between tests to isolate pub/sub state.
    await _fake_redis.flushdb()

    try:
        yield fastapi_app
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        ws_router_module.AsyncSessionLocal = original_ws_sm
        db_session_module.AsyncSessionLocal = original_db_sm


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver/api/v1") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth / user factories
# ---------------------------------------------------------------------------
def _customer_payload(**overrides):
    base = {
        "email": "alice@example.com",
        "password": "Str0ngPass!",
        "full_name": "Alice Customer",
        "phone": "+15551112222",
    }
    base.update(overrides)
    return base


def _driver_payload(**overrides):
    base = {
        "email": "bob@example.com",
        "password": "Str0ngPass!",
        "full_name": "Bob Driver",
        "phone": "+15553334444",
        "license_number": "LIC-0001",
        "vehicle_type": "van",
        "vehicle_plate": "AA-111-AA",
        "vehicle_capacity_kg": 1000,
    }
    base.update(overrides)
    return base


@pytest.fixture
def customer_payload():
    return _customer_payload


@pytest.fixture
def driver_payload():
    return _driver_payload


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def register_customer(client: AsyncClient):
    async def _register(**overrides) -> dict:
        payload = _customer_payload(**overrides)
        r = await client.post("/auth/register/customer", json=payload)
        assert r.status_code == 201, r.text
        login = await client.post(
            "/auth/login/json",
            json={"email": payload["email"], "password": payload["password"], "role": "customer"},
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        return {
            "user": r.json(),
            "tokens": tokens,
            "headers": _auth_headers(tokens["access_token"]),
            "password": payload["password"],
        }

    return _register


@pytest_asyncio.fixture
async def register_driver(client: AsyncClient):
    async def _register(**overrides) -> dict:
        payload = _driver_payload(**overrides)
        r = await client.post("/auth/register/driver", json=payload)
        assert r.status_code == 201, r.text
        login = await client.post(
            "/auth/login/json",
            json={"email": payload["email"], "password": payload["password"], "role": "driver"},
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        return {
            "user": r.json(),
            "tokens": tokens,
            "headers": _auth_headers(tokens["access_token"]),
            "password": payload["password"],
        }

    return _register


@pytest_asyncio.fixture
async def customer(register_customer) -> dict:
    return await register_customer()


@pytest_asyncio.fixture
async def driver(register_driver) -> dict:
    return await register_driver()


@pytest.fixture
def auth_headers() -> Callable[[str], dict[str, str]]:
    return _auth_headers


# ---------------------------------------------------------------------------
# Order helpers
# ---------------------------------------------------------------------------
def _order_payload(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return base


@pytest.fixture
def order_payload():
    return _order_payload


@pytest_asyncio.fixture
async def make_driver_available(client: AsyncClient):
    """Shortcut: flip a driver's status to 'available'."""

    async def _go_available(driver_session: dict) -> None:
        r = await client.put(
            "/drivers/me/status",
            json={"status": "available"},
            headers=driver_session["headers"],
        )
        assert r.status_code == 200, r.text

    return _go_available


@pytest_asyncio.fixture
async def pending_order(client: AsyncClient, customer: dict) -> dict:
    r = await client.post("/orders", json=_order_payload(), headers=customer["headers"])
    assert r.status_code == 201, r.text
    return r.json()


__all__ = [
    "User",
    "UserRole",
    "Driver",
    "DriverStatus",
]
