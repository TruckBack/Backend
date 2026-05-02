from __future__ import annotations

from fastapi import APIRouter, UploadFile, status

from app.core.dependencies import CurrentCustomer, CurrentUser, DbSession
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.repositories.user import UserRepository
from app.services.order import OrderService
from app.services.upload import MAX_IMAGE_BYTES, _ALLOWED_IMAGE_TYPES, UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _validate_upload(file: UploadFile, content: bytes) -> None:
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise BadRequestError(
            f"Unsupported content type. Allowed: {sorted(_ALLOWED_IMAGE_TYPES)}"
        )
    if not content:
        raise BadRequestError("File is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise BadRequestError("File exceeds the 10 MB size limit")


# ---------------------------------------------------------------------------
# Profile image
# ---------------------------------------------------------------------------

@router.post("/image/profile")
async def upload_profile_image(
    file: UploadFile,
    current_user: CurrentUser,
    db: DbSession,
) -> dict[str, str | None]:
    content = await file.read()
    _validate_upload(file, content)

    if current_user.profile_image_url:
        UploadService.delete_file_by_url(current_user.profile_image_url)

    url = UploadService.save_profile_image(current_user.id, file.filename or "image", content)
    current_user.profile_image_url = url
    await db.commit()

    return {"profile_image_url": url}


@router.put("/image/profile")
async def replace_profile_image(
    file: UploadFile,
    current_user: CurrentUser,
    db: DbSession,
) -> dict[str, str | None]:
    content = await file.read()
    _validate_upload(file, content)

    if current_user.profile_image_url:
        UploadService.delete_file_by_url(current_user.profile_image_url)

    url = UploadService.save_profile_image(current_user.id, file.filename or "image", content)
    current_user.profile_image_url = url
    await db.commit()

    return {"profile_image_url": url}


@router.delete("/image/profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_image(
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    if current_user.profile_image_url:
        UploadService.delete_file_by_url(current_user.profile_image_url)
        current_user.profile_image_url = None
        await db.commit()


# ---------------------------------------------------------------------------
# Order cargo image
# ---------------------------------------------------------------------------

@router.post("/image/order/{order_id}")
async def upload_order_image(
    order_id: int,
    file: UploadFile,
    db: DbSession,
    current: CurrentCustomer,
) -> dict[str, str]:
    order = await OrderService(db).get_for_user(order_id, current)
    if order.customer_id != current.id:
        raise ForbiddenError("You can only upload images to your own orders")

    content = await file.read()
    _validate_upload(file, content)

    url = UploadService.save_order_image(order_id, file.filename or "image", content)
    order.cargo_image_url = url
    await db.commit()

    return {"cargo_image_url": url}


@router.put("/image/order/{order_id}")
async def replace_order_image(
    order_id: int,
    file: UploadFile,
    db: DbSession,
    current: CurrentCustomer,
) -> dict[str, str]:
    order = await OrderService(db).get_for_user(order_id, current)
    if order.customer_id != current.id:
        raise ForbiddenError("You can only upload images to your own orders")

    content = await file.read()
    _validate_upload(file, content)

    if order.cargo_image_url:
        UploadService.delete_file_by_url(order.cargo_image_url)

    url = UploadService.save_order_image(order_id, file.filename or "image", content)
    order.cargo_image_url = url
    await db.commit()

    return {"cargo_image_url": url}


@router.delete("/image/order/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_image(
    order_id: int,
    db: DbSession,
    current: CurrentCustomer,
) -> None:
    order = await OrderService(db).get_for_user(order_id, current)
    if order.customer_id != current.id:
        raise ForbiddenError("You can only upload images to your own orders")

    if order.cargo_image_url:
        UploadService.delete_file_by_url(order.cargo_image_url)
        order.cargo_image_url = None
        await db.commit()


# ---------------------------------------------------------------------------
# GET — fetch image URLs (for frontend display)
# ---------------------------------------------------------------------------

@router.get("/image/profile")
async def get_my_profile_image(
    current_user: CurrentUser,
) -> dict[str, str | None]:
    """Return the authenticated user's current profile image URL."""
    return {"profile_image_url": current_user.profile_image_url}


@router.get("/image/profile/{user_id}")
async def get_user_profile_image(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
) -> dict[str, str | None]:
    """Return a specific user's profile image URL (auth required)."""
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found")
    return {"profile_image_url": user.profile_image_url}


@router.get("/image/order/{order_id}")
async def get_order_image(
    order_id: int,
    db: DbSession,
    current: CurrentUser,
) -> dict[str, str | None]:
    """Return an order's current cargo image URL (auth + ownership check)."""
    order = await OrderService(db).get_for_user(order_id, current)
    return {"cargo_image_url": order.cargo_image_url}

