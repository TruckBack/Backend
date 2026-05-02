from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.dependencies import CurrentUser, DbSession
from app.core.exceptions import AppException, UnauthorizedError
from app.core.security import TokenType, decode_token
from app.db.session import AsyncSessionLocal
from app.models.user import UserRole
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.repositories.user import UserRepository
from app.schemas.chat import (
    ConversationDetailSchema,
    ConversationSummarySchema,
    SendMessageRequest,
)
from app.services import chat as chat_service
from app.services.chat_ws import chat_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationSummarySchema])
async def list_conversations(
    session: DbSession,
    current_user: CurrentUser,
):
    return await chat_service.list_conversations(session, current_user)


@router.get("/conversations/{order_id}", response_model=ConversationDetailSchema)
async def get_conversation(
    order_id: int,
    session: DbSession,
    current_user: CurrentUser,
):
    return await chat_service.get_conversation_detail(session, order_id, current_user)


@router.post("/conversations/{order_id}/messages", response_model=dict, status_code=201)
async def send_message(
    order_id: int,
    payload: SendMessageRequest,
    session: DbSession,
    current_user: CurrentUser,
):
    msg = await chat_service.send_message(session, order_id, current_user, payload.body)
    return msg.model_dump(mode="json")


@router.post("/conversations/{order_id}/read", response_model=dict)
async def mark_read(
    order_id: int,
    session: DbSession,
    current_user: CurrentUser,
):
    marked = await chat_service.mark_conversation_read(session, order_id, current_user)
    return {"marked_count": len(marked), "message_ids": marked}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


async def _ws_authenticate(token: str):
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


async def _ws_authorize_order(user, order_id: int) -> None:
    """Raise UnauthorizedError if user is not a participant of the order's conversation."""
    async with AsyncSessionLocal() as session:
        order = await OrderRepository(session).get_by_id(order_id)
        if not order:
            raise UnauthorizedError("Order not found")
        if user.role == UserRole.CUSTOMER:
            if order.customer_id != user.id:
                raise UnauthorizedError("Forbidden")
        elif user.role == UserRole.DRIVER:
            driver = await DriverRepository(session).get_by_user_id(user.id)
            if not driver or order.driver_id != driver.id:
                raise UnauthorizedError("Forbidden")
        # ADMIN passes through


@router.websocket("/ws/{order_id}")
async def chat_websocket(
    websocket: WebSocket,
    order_id: int,
    token: str = Query(...),
):
    try:
        user = await _ws_authenticate(token)
        await _ws_authorize_order(user, order_id)
    except (AppException, Exception) as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await chat_manager.connect(order_id, websocket)
    try:
        while True:
            # We only push messages; clients don't need to send data over WS.
            # But we keep the loop alive to detect disconnects.
            data = await websocket.receive_text()
            # Optionally handle ping/pong
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, AttributeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await chat_manager.disconnect(order_id, websocket)
