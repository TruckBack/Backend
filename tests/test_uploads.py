"""/uploads endpoints. S3 is stubbed in conftest."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_presign_profile_image_returns_fake_url(
    client: AsyncClient, customer: dict
):
    r = await client.post(
        "/uploads/image/profile",
        json={"filename": "avatar.png", "content_type": "image/png"},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "PUT"
    assert body["upload_url"].startswith("https://fake-s3.example/")
    assert body["headers"]["Content-Type"] == "image/png"
    assert f"profile-images/{customer['user']['id']}/" in body["key"]
    assert body["public_url"].endswith(body["key"])
    assert body["expires_in"] > 0


async def test_presign_requires_auth(client: AsyncClient):
    r = await client.post(
        "/uploads/image/profile",
        json={"filename": "x.png", "content_type": "image/png"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize("ct", ["text/plain", "application/pdf", "image/svg+xml"])
async def test_presign_rejects_bad_content_type(
    client: AsyncClient, customer: dict, ct: str
):
    r = await client.post(
        "/uploads/image/profile",
        json={"filename": "x.png", "content_type": ct},
        headers=customer["headers"],
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_presign_sanitizes_filename(client: AsyncClient, customer: dict):
    r = await client.post(
        "/uploads/image/profile",
        json={"filename": "../../etc/passwd.png", "content_type": "image/png"},
        headers=customer["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    # No traversal segments in the stored key
    assert "../" not in body["key"]
    assert "/etc/" not in body["key"]


async def test_presign_keys_are_unique(client: AsyncClient, customer: dict):
    keys = set()
    for _ in range(5):
        r = await client.post(
            "/uploads/image/profile",
            json={"filename": "a.png", "content_type": "image/png"},
            headers=customer["headers"],
        )
        assert r.status_code == 200
        keys.add(r.json()["key"])
    assert len(keys) == 5
