from __future__ import annotations

from pydantic import BaseModel, Field


_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PresignedUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)

    def validate_content_type(self) -> None:
        from app.core.exceptions import BadRequestError

        if self.content_type not in _ALLOWED_IMAGE_TYPES:
            raise BadRequestError(
                f"Unsupported content type. Allowed: {sorted(_ALLOWED_IMAGE_TYPES)}"
            )


class PresignedUploadResponse(BaseModel):
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str]
    key: str
    public_url: str
    expires_in: int
