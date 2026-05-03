"""Tests for /uploads image endpoints (filesystem-based)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture(autouse=True)
def use_tmp_uploads(tmp_path, monkeypatch):
    """Redirect all file I/O to a per-test temp directory."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


def _img(name: str = "photo.jpg", ct: str = "image/jpeg"):
    return {"file": (name, io.BytesIO(b"fake-image-data"), ct)}


# ---------------------------------------------------------------------------
# Profile image — POST (upload / replace-on-first-call)
# ---------------------------------------------------------------------------

async def test_upload_profile_success(client: AsyncClient, customer: dict):
    r = await client.post(
        "/uploads/image/profile", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["profile_image_url"]
    assert url.startswith("/uploads/profile-images/")
    assert "photo.jpg" in url


async def test_upload_profile_persists_to_db(client: AsyncClient, customer: dict):
    r = await client.post(
        "/uploads/image/profile", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["profile_image_url"]
    me = await client.get("/users/me", headers=customer["headers"])
    assert me.json()["profile_image_url"] == url


async def test_upload_profile_requires_auth(client: AsyncClient):
    r = await client.post("/uploads/image/profile", files=_img())
    assert r.status_code == 401


@pytest.mark.parametrize("ct", ["text/plain", "application/pdf", "image/svg+xml"])
async def test_upload_profile_rejects_bad_content_type(
    client: AsyncClient, customer: dict, ct: str
):
    r = await client.post(
        "/uploads/image/profile", files=_img(ct=ct), headers=customer["headers"]
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_upload_profile_empty_file_rejected(client: AsyncClient, customer: dict):
    r = await client.post(
        "/uploads/image/profile",
        files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
        headers=customer["headers"],
    )
    assert r.status_code == 400


async def test_upload_profile_replaces_old_file(
    client: AsyncClient, customer: dict, tmp_path: Path
):
    r1 = await client.post(
        "/uploads/image/profile", files=_img("first.jpg"), headers=customer["headers"]
    )
    assert r1.status_code == 200
    first_url = r1.json()["profile_image_url"]
    first_path = tmp_path / first_url.removeprefix("/uploads/")
    assert first_path.exists()

    r2 = await client.post(
        "/uploads/image/profile", files=_img("second.jpg"), headers=customer["headers"]
    )
    assert r2.status_code == 200
    second_url = r2.json()["profile_image_url"]
    assert second_url != first_url
    assert not first_path.exists()
    assert (tmp_path / second_url.removeprefix("/uploads/")).exists()


# ---------------------------------------------------------------------------
# Profile image — PUT (explicit replace)
# ---------------------------------------------------------------------------

async def test_replace_profile_success(
    client: AsyncClient, customer: dict, tmp_path: Path
):
    r1 = await client.post(
        "/uploads/image/profile", files=_img("v1.jpg"), headers=customer["headers"]
    )
    assert r1.status_code == 200
    old_url = r1.json()["profile_image_url"]
    old_path = tmp_path / old_url.removeprefix("/uploads/")

    r2 = await client.put(
        "/uploads/image/profile", files=_img("v2.jpg"), headers=customer["headers"]
    )
    assert r2.status_code == 200
    new_url = r2.json()["profile_image_url"]
    assert new_url != old_url
    assert not old_path.exists()
    assert (tmp_path / new_url.removeprefix("/uploads/")).exists()


async def test_replace_profile_requires_auth(client: AsyncClient):
    r = await client.put("/uploads/image/profile", files=_img())
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Profile image — DELETE
# ---------------------------------------------------------------------------

async def test_delete_profile_success(
    client: AsyncClient, customer: dict, tmp_path: Path
):
    r = await client.post(
        "/uploads/image/profile", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["profile_image_url"]
    file_path = tmp_path / url.removeprefix("/uploads/")
    assert file_path.exists()

    rd = await client.delete("/uploads/image/profile", headers=customer["headers"])
    assert rd.status_code == 204
    assert not file_path.exists()

    me = await client.get("/users/me", headers=customer["headers"])
    assert me.json()["profile_image_url"] is None


async def test_delete_profile_no_image_is_noop(client: AsyncClient, customer: dict):
    r = await client.delete("/uploads/image/profile", headers=customer["headers"])
    assert r.status_code == 204


async def test_delete_profile_requires_auth(client: AsyncClient):
    r = await client.delete("/uploads/image/profile")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Order cargo image — POST
# ---------------------------------------------------------------------------

async def test_upload_order_image_success(
    client: AsyncClient, customer: dict, pending_order: dict
):
    order_id = pending_order["id"]
    r = await client.post(
        f"/uploads/image/order/{order_id}", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["cargo_image_url"]
    assert f"/uploads/order-images/{order_id}/" in url


async def test_upload_order_image_persists_to_db(
    client: AsyncClient, customer: dict, pending_order: dict
):
    order_id = pending_order["id"]
    r = await client.post(
        f"/uploads/image/order/{order_id}", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["cargo_image_url"]

    order_r = await client.get(f"/orders/{order_id}", headers=customer["headers"])
    assert order_r.json()["cargo_image_url"] == url


async def test_upload_order_image_requires_auth(
    client: AsyncClient, pending_order: dict
):
    r = await client.post(
        f"/uploads/image/order/{pending_order['id']}", files=_img()
    )
    assert r.status_code == 401


async def test_upload_order_image_wrong_customer_denied(
    client: AsyncClient, pending_order: dict, register_customer
):
    other = await register_customer(email="other2@example.com")
    r = await client.post(
        f"/uploads/image/order/{pending_order['id']}",
        files=_img(),
        headers=other["headers"],
    )
    assert r.status_code in {403, 404}


@pytest.mark.parametrize("ct", ["text/plain", "application/pdf"])
async def test_upload_order_image_rejects_bad_content_type(
    client: AsyncClient, customer: dict, pending_order: dict, ct: str
):
    r = await client.post(
        f"/uploads/image/order/{pending_order['id']}",
        files=_img(ct=ct),
        headers=customer["headers"],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# Order cargo image — PUT (replace)
# ---------------------------------------------------------------------------

async def test_replace_order_image_success(
    client: AsyncClient, customer: dict, pending_order: dict, tmp_path: Path
):
    order_id = pending_order["id"]

    r1 = await client.post(
        f"/uploads/image/order/{order_id}", files=_img("first.jpg"), headers=customer["headers"]
    )
    assert r1.status_code == 200
    first_url = r1.json()["cargo_image_url"]
    first_path = tmp_path / first_url.removeprefix("/uploads/")
    assert first_path.exists()

    r2 = await client.put(
        f"/uploads/image/order/{order_id}", files=_img("second.jpg"), headers=customer["headers"]
    )
    assert r2.status_code == 200
    second_url = r2.json()["cargo_image_url"]
    assert second_url != first_url
    assert not first_path.exists()
    assert (tmp_path / second_url.removeprefix("/uploads/")).exists()


async def test_replace_order_image_requires_auth(
    client: AsyncClient, pending_order: dict
):
    r = await client.put(
        f"/uploads/image/order/{pending_order['id']}", files=_img()
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Order cargo image — DELETE
# ---------------------------------------------------------------------------

async def test_delete_order_image_success(
    client: AsyncClient, customer: dict, pending_order: dict, tmp_path: Path
):
    order_id = pending_order["id"]

    r = await client.post(
        f"/uploads/image/order/{order_id}", files=_img(), headers=customer["headers"]
    )
    assert r.status_code == 200
    url = r.json()["cargo_image_url"]
    file_path = tmp_path / url.removeprefix("/uploads/")
    assert file_path.exists()

    rd = await client.delete(
        f"/uploads/image/order/{order_id}", headers=customer["headers"]
    )
    assert rd.status_code == 204
    assert not file_path.exists()

    order_r = await client.get(f"/orders/{order_id}", headers=customer["headers"])
    assert order_r.json()["cargo_image_url"] is None


async def test_delete_order_image_no_image_is_noop(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.delete(
        f"/uploads/image/order/{pending_order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 204


async def test_delete_order_image_requires_auth(
    client: AsyncClient, pending_order: dict
):
    r = await client.delete(f"/uploads/image/order/{pending_order['id']}")
    assert r.status_code == 401


async def test_delete_order_image_wrong_customer_denied(
    client: AsyncClient, pending_order: dict, register_customer
):
    other = await register_customer(email="other3@example.com")
    r = await client.delete(
        f"/uploads/image/order/{pending_order['id']}", headers=other["headers"]
    )
    assert r.status_code in {403, 404}


# ---------------------------------------------------------------------------
# GET — fetch image URLs
# ---------------------------------------------------------------------------

async def test_get_my_profile_image_no_image(client: AsyncClient, customer: dict):
    r = await client.get("/uploads/image/profile", headers=customer["headers"])
    assert r.status_code == 200
    assert r.json()["profile_image_url"] is None


async def test_get_my_profile_image_after_upload(client: AsyncClient, customer: dict):
    up = await client.post(
        "/uploads/image/profile", files=_img(), headers=customer["headers"]
    )
    assert up.status_code == 200
    expected_url = up.json()["profile_image_url"]

    r = await client.get("/uploads/image/profile", headers=customer["headers"])
    assert r.status_code == 200
    assert r.json()["profile_image_url"] == expected_url


async def test_get_my_profile_image_requires_auth(client: AsyncClient):
    r = await client.get("/uploads/image/profile")
    assert r.status_code == 401


async def test_get_user_profile_image_by_id(
    client: AsyncClient, customer: dict, register_customer
):
    other = await register_customer(email="other4@example.com")
    up = await client.post(
        "/uploads/image/profile", files=_img("other.jpg"), headers=other["headers"]
    )
    assert up.status_code == 200
    expected_url = up.json()["profile_image_url"]

    r = await client.get(
        f"/uploads/image/profile/{other['user']['id']}", headers=customer["headers"]
    )
    assert r.status_code == 200
    assert r.json()["profile_image_url"] == expected_url


async def test_get_user_profile_image_not_found(client: AsyncClient, customer: dict):
    r = await client.get("/uploads/image/profile/999999", headers=customer["headers"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_get_user_profile_image_requires_auth(client: AsyncClient, customer: dict):
    r = await client.get(f"/uploads/image/profile/{customer['user']['id']}")
    assert r.status_code == 401


async def test_get_order_image_no_image(
    client: AsyncClient, customer: dict, pending_order: dict
):
    r = await client.get(
        f"/uploads/image/order/{pending_order['id']}", headers=customer["headers"]
    )
    assert r.status_code == 200
    assert r.json()["cargo_image_url"] is None


async def test_get_order_image_after_upload(
    client: AsyncClient, customer: dict, pending_order: dict
):
    order_id = pending_order["id"]
    up = await client.post(
        f"/uploads/image/order/{order_id}", files=_img(), headers=customer["headers"]
    )
    assert up.status_code == 200
    expected_url = up.json()["cargo_image_url"]

    r = await client.get(
        f"/uploads/image/order/{order_id}", headers=customer["headers"]
    )
    assert r.status_code == 200
    assert r.json()["cargo_image_url"] == expected_url


async def test_get_order_image_requires_auth(
    client: AsyncClient, pending_order: dict
):
    r = await client.get(f"/uploads/image/order/{pending_order['id']}")
    assert r.status_code == 401


async def test_get_order_image_wrong_customer_denied(
    client: AsyncClient, pending_order: dict, register_customer
):
    other = await register_customer(email="other5@example.com")
    r = await client.get(
        f"/uploads/image/order/{pending_order['id']}", headers=other["headers"]
    )
    assert r.status_code in {403, 404}

