from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.models.user import User
from app.schemas.upload import PresignedUploadRequest, PresignedUploadResponse
from app.utils.s3 import generate_presigned_put_url, public_object_url

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _sanitize_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = _SAFE_NAME_RE.sub("", name)
    if not name or name in {".", ".."}:
        raise BadRequestError("Invalid filename")
    return name[:120]


_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class UploadService:
    @staticmethod
    async def presign_profile_image(
        user: User, data: PresignedUploadRequest
    ) -> PresignedUploadResponse:
        data.validate_content_type()
        if not settings.S3_BUCKET:
            raise BadRequestError("S3 is not configured")

        safe_name = _sanitize_filename(data.filename)
        key = f"profile-images/{user.id}/{uuid.uuid4().hex}_{safe_name}"

        url = await generate_presigned_put_url(key=key, content_type=data.content_type)
        return PresignedUploadResponse(
            upload_url=url,
            headers={"Content-Type": data.content_type},
            key=key,
            public_url=public_object_url(key),
            expires_in=settings.S3_PRESIGNED_EXPIRE_SECONDS,
        )

    @staticmethod
    def save_order_image(order_id: int, file_name: str, content: bytes) -> str:
        safe_name = _sanitize_filename(file_name)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        rel_dir = Path(settings.UPLOADS_DIR) / "order-images" / str(order_id)
        target_path = rel_dir / unique_name

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        return f"/uploads/order-images/{order_id}/{unique_name}"

    @staticmethod
    def save_profile_image(user_id: int, file_name: str, content: bytes) -> str:
        safe_name = _sanitize_filename(file_name)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        rel_dir = Path(settings.UPLOADS_DIR) / "profile-images" / str(user_id)
        target_path = rel_dir / unique_name

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        return f"/uploads/profile-images/{user_id}/{unique_name}"

    @staticmethod
    def delete_file_by_url(url: str) -> None:
        """Delete the file pointed to by a stored /uploads/... URL. Silent if absent."""
        prefix = "/uploads/"
        relative = url[len(prefix):] if url.startswith(prefix) else url.lstrip("/")
        path = Path(settings.UPLOADS_DIR) / relative
        try:
            path.unlink()
        except FileNotFoundError:
            pass
