from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentCustomer, CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.order import OrderCancel, OrderCreate, OrderRead, OrderStatusEvent, OrderUpdate
from app.services.order import OrderService
from app.services.ws_manager import tracking_manager

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_event(order) -> OrderStatusEvent:
    # Pick the most relevant timestamp for the current state
    ts = (
        order.completed_at
        or order.cancelled_at
        or order.picked_up_at
        or order.started_at
        or order.accepted_at
        or order.created_at
    )
    return OrderStatusEvent(order_id=order.id, status=order.status, at=ts)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate, current: CurrentCustomer, db: DbSession
) -> OrderRead:
    order = await OrderService(db).create(current, payload)
    return OrderRead.model_validate(order)


@router.get("/available", response_model=Page[OrderRead])
async def list_available(
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OrderRead]:
    items, total = await OrderService(db).list_available(limit=limit, offset=offset)
    return Page[OrderRead](
        items=[OrderRead.model_validate(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/history", response_model=Page[OrderRead])
async def list_history(
    db: DbSession,
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OrderRead]:
    items, total = await OrderService(db).list_history(current, limit=limit, offset=offset)
    return Page[OrderRead](
        items=[OrderRead.model_validate(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/me/active", response_model=list[OrderRead])
async def list_my_active(db: DbSession, current: CurrentUser) -> list[OrderRead]:
    items = await OrderService(db).list_active(current)
    return [OrderRead.model_validate(o) for o in items]


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: int, db: DbSession, current: CurrentUser) -> OrderRead:
    order = await OrderService(db).get_for_user(order_id, current)
    return OrderRead.model_validate(order)


@router.patch("/{order_id}", response_model=OrderRead)
async def update_order(
    order_id: int, payload: OrderUpdate, db: DbSession, current: CurrentUser
) -> OrderRead:
    order = await OrderService(db).update(order_id, current, payload)
    return OrderRead.model_validate(order)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int, db: DbSession, current: CurrentUser
) -> None:
    await OrderService(db).delete(order_id, current)


async def _broadcast(order) -> None:
    event = _to_event(order)
    await tracking_manager.publish(
        order.id, {"type": "status", **event.model_dump(mode="json")}
    )


@router.post("/{order_id}/accept", response_model=OrderRead)
async def accept_order(order_id: int, db: DbSession, current: CurrentUser) -> OrderRead:
    order = await OrderService(db).accept(order_id, current)
    await _broadcast(order)
    return OrderRead.model_validate(order)


@router.post("/{order_id}/start", response_model=OrderRead)
async def start_order(order_id: int, db: DbSession, current: CurrentUser) -> OrderRead:
    order = await OrderService(db).start(order_id, current)
    await _broadcast(order)
    return OrderRead.model_validate(order)


@router.post("/{order_id}/pickup", response_model=OrderRead)
async def pickup_order(order_id: int, db: DbSession, current: CurrentUser) -> OrderRead:
    order = await OrderService(db).pickup(order_id, current)
    await _broadcast(order)
    return OrderRead.model_validate(order)


@router.post("/{order_id}/complete", response_model=OrderRead)
async def complete_order(order_id: int, db: DbSession, current: CurrentUser) -> OrderRead:
    order = await OrderService(db).complete(order_id, current)
    await _broadcast(order)
    return OrderRead.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel_order(
    order_id: int, payload: OrderCancel, db: DbSession, current: CurrentUser
) -> OrderRead:
    order = await OrderService(db).cancel(order_id, current, payload)
    await _broadcast(order)
    return OrderRead.model_validate(order)
