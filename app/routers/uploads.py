from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser
from app.schemas.upload import PresignedUploadRequest, PresignedUploadResponse
from app.services.upload import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/image/profile", response_model=PresignedUploadResponse)
async def presign_profile_image(
    payload: PresignedUploadRequest, current_user: CurrentUser
) -> PresignedUploadResponse:
    return await UploadService.presign_profile_image(current_user, payload)
