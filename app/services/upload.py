from __future__ import annotations

import re
import uuid

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.models.user import User
from app.schemas.upload import PresignedUploadRequest, PresignedUploadResponse
from app.utils.s3 import generate_presigned_put_url, public_object_url

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = _SAFE_NAME_RE.sub("", name)
    if not name or name in {".", ".."}:
        raise BadRequestError("Invalid filename")
    return name[:120]


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
