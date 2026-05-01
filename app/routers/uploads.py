from __future__ import annotations

from fastapi import APIRouter, UploadFile

from app.core.dependencies import CurrentCustomer, DbSession
from app.schemas.order import OrderRead
from app.schemas.upload import PresignedUploadRequest, PresignedUploadResponse
from app.services.order import OrderService
from app.services.upload import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/image/profile", response_model=PresignedUploadResponse)
async def presign_profile_image(
    payload: PresignedUploadRequest, current_user: CurrentCustomer
) -> PresignedUploadResponse:
    return await UploadService.presign_profile_image(current_user, payload)


@router.post("/image/order/{order_id}")
async def upload_order_image(
    order_id: int,
    file: UploadFile,
    db: DbSession,
    current: CurrentCustomer,
) -> dict[str, str]:
    order = await OrderService(db).get_for_user(order_id, current)
    if order.customer_id != current.id:
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("You can only upload images to your own orders")

    content = await file.read()
    if not content:
        from app.core.exceptions import BadRequestError

        raise BadRequestError("File is empty")

    filename = file.filename or "image"
    image_url = UploadService.save_order_image(order_id, filename, content)

    return {"cargo_image_url": image_url}
