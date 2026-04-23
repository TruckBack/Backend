from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.exceptions import AppException, UnauthorizedError
from app.core.security import TokenType, decode_token
from app.db.session import AsyncSessionLocal
from app.models.driver import DriverStatus
from app.models.order import ACTIVE_ORDER_STATUSES, OrderStatus
from app.models.user import UserRole
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.repositories.user import UserRepository
from app.services.ws_manager import tracking_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websockets"])


async def _authenticate_ws(token: str):
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token subject") from exc
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or inactive")
        return user


async def _authorize_order(user, order_id: int) -> tuple[object, object | None]:
    """Return (order, driver_or_none). Raises on missing/forbidden."""
    async with AsyncSessionLocal() as session:
        order = await OrderRepository(session).get_by_id(order_id)
        if not order:
            raise UnauthorizedError("Order not found")
        if user.role == UserRole.CUSTOMER:
            if order.customer_id != user.id:
                raise UnauthorizedError("Forbidden")
            return order, None
        if user.role == UserRole.DRIVER:
            driver = await DriverRepository(session).get_by_user_id(user.id)
            if not driver or order.driver_id != driver.id:
                raise UnauthorizedError("Forbidden")
            return order, driver
        if user.role == UserRole.ADMIN:
            return order, None
        raise UnauthorizedError("Forbidden")


async def _persist_driver_location(driver_id: int, lat: float, lng: float) -> None:
    async with AsyncSessionLocal() as session:
        driver = await DriverRepository(session).get_by_id(driver_id)
        if driver and driver.status != DriverStatus.OFFLINE:
            driver.current_lat = lat
            driver.current_lng = lng
            driver.last_location_at = datetime.now(timezone.utc)
            await session.commit()


@router.websocket("/orders/{order_id}/track")
async def track_order(
    websocket: WebSocket,
    order_id: int,
    token: str = Query(..., description="Access token"),
) -> None:
    try:
        user = await _authenticate_ws(token)
        order, driver = await _authorize_order(user, order_id)
    except (AppException, Exception) as exc:  # noqa: BLE001
        logger.info("WS auth rejected: %s", exc)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if order.status not in ACTIVE_ORDER_STATUSES and order.status != OrderStatus.ACCEPTED:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Order not active")
        return

    await tracking_manager.connect(order_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()

            # Only the assigned driver may push location updates.
            if user.role != UserRole.DRIVER or driver is None:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            if msg.get("type") != "location":
                continue
            try:
                lat = float(msg["lat"])
                lng = float(msg["lng"])
            except (KeyError, TypeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "message": "lat/lng required"}
                )
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                await websocket.send_json(
                    {"type": "error", "message": "lat/lng out of range"}
                )
                continue

            now = datetime.now(timezone.utc).isoformat()
            await tracking_manager.publish(
                order_id,
                {
                    "type": "location",
                    "order_id": order_id,
                    "driver_id": driver.id,
                    "lat": lat,
                    "lng": lng,
                    "at": now,
                },
            )
            # Best-effort persistence; failures shouldn't drop the socket.
            try:
                await _persist_driver_location(driver.id, lat, lng)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to persist driver location")
    except WebSocketDisconnect:
        pass
    finally:
        await tracking_manager.disconnect(order_id, websocket)
