from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.order import Order
from app.models.user import User, UserRole
from app.repositories.chat import ChatRepository
from app.repositories.driver import DriverRepository
from app.repositories.order import OrderRepository
from app.schemas.chat import (
    ChatMessageSchema,
    ConversationDetailSchema,
    ConversationSummarySchema,
)
from app.services.chat_ws import chat_manager


async def _get_order_and_check_participant(
    session: AsyncSession, order_id: int, user: User
) -> Order:
    """Return the Order if user is a participant (customer or assigned driver). Else raise."""
    order = await OrderRepository(session).get_by_id(order_id)
    if not order:
        raise NotFoundError("Order not found")

    if user.role == UserRole.CUSTOMER:
        if order.customer_id != user.id:
            raise ForbiddenError("Not a participant of this conversation")
        return order

    if user.role == UserRole.DRIVER:
        driver = await DriverRepository(session).get_by_user_id(user.id)
        if not driver or order.driver_id != driver.id:
            raise ForbiddenError("Not a participant of this conversation")
        return order

    if user.role == UserRole.ADMIN:
        return order

    raise ForbiddenError("Not a participant of this conversation")


def _enrich_message(msg, reader_id: int) -> ChatMessageSchema:
    """Attach is_read flag based on read_statuses already loaded on the message."""
    read_user_ids = {rs.user_id for rs in msg.read_statuses}
    schema = ChatMessageSchema.model_validate(msg)
    schema.is_read = reader_id in read_user_ids or msg.sender_id == reader_id
    return schema


async def list_conversations(session: AsyncSession, user: User) -> list[ConversationSummarySchema]:
    repo = ChatRepository(session)

    if user.role == UserRole.CUSTOMER:
        convos = await repo.list_conversations_for_user(customer_id=user.id, driver_user_id=None)
    elif user.role == UserRole.DRIVER:
        driver = await DriverRepository(session).get_by_user_id(user.id)
        if not driver:
            return []
        convos = await repo.list_conversations_for_user(customer_id=None, driver_user_id=user.id)
    else:
        # admin — not supported in listing; return empty
        return []

    summaries = []
    for convo in convos:
        unread = await repo.get_unread_count(convo.id, user.id)
        last_msg = convo.messages[-1] if convo.messages else None
        last_msg_schema = _enrich_message(last_msg, user.id) if last_msg else None
        summaries.append(
            ConversationSummarySchema(
                id=convo.id,
                order_id=convo.order_id,
                last_message=last_msg_schema,
                unread_count=unread,
                created_at=convo.created_at,
                updated_at=convo.updated_at,
            )
        )
    return summaries


async def get_conversation_detail(
    session: AsyncSession, order_id: int, user: User
) -> ConversationDetailSchema:
    await _get_order_and_check_participant(session, order_id, user)
    repo = ChatRepository(session)
    convo = await repo.get_or_create_conversation(order_id)
    # Reload with messages+senders+read_statuses
    convo = await repo.get_conversation_by_order_id(order_id)

    messages = [_enrich_message(msg, user.id) for msg in (convo.messages or [])]

    return ConversationDetailSchema(
        id=convo.id,
        order_id=convo.order_id,
        messages=messages,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
    )


async def send_message(
    session: AsyncSession, order_id: int, user: User, body: str
) -> ChatMessageSchema:
    await _get_order_and_check_participant(session, order_id, user)
    repo = ChatRepository(session)
    convo = await repo.get_or_create_conversation(order_id)
    msg = await repo.create_message(
        conversation_id=convo.id, sender_id=user.id, body=body
    )
    # Auto-mark as read for the sender
    await repo.mark_messages_read([msg.id], user.id)
    await session.commit()

    msg_schema = ChatMessageSchema(
        id=msg.id,
        conversation_id=convo.id,
        sender_id=msg.sender_id,
        sender={"id": msg.sender.id, "full_name": msg.sender.full_name},
        body=msg.body,
        created_at=msg.created_at,
        is_read=True,
    )

    # Broadcast over WebSocket/Redis
    await chat_manager.publish(
        order_id,
        {
            "event_type": "new_message",
            "payload": msg_schema.model_dump(mode="json"),
        },
    )
    return msg_schema


async def mark_conversation_read(
    session: AsyncSession, order_id: int, user: User
) -> list[int]:
    """Mark all unread messages in the conversation as read by this user."""
    await _get_order_and_check_participant(session, order_id, user)
    repo = ChatRepository(session)
    convo = await repo.get_or_create_conversation(order_id)
    unread_ids = await repo.get_unread_message_ids(convo.id, user.id)
    if not unread_ids:
        return []
    marked = await repo.mark_messages_read(unread_ids, user.id)
    await session.commit()

    if marked:
        await chat_manager.publish(
            order_id,
            {
                "event_type": "messages_read",
                "payload": {
                    "conversation_id": convo.id,
                    "read_by_user_id": user.id,
                    "message_ids": marked,
                },
            },
        )
    return marked
