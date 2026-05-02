from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.chat import ChatConversation, ChatMessage, MessageReadStatus
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository[ChatConversation]):
    model = ChatConversation

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def get_conversation_by_order_id(self, order_id: int) -> ChatConversation | None:
        stmt = (
            select(ChatConversation)
            .where(ChatConversation.order_id == order_id)
            .options(
                selectinload(ChatConversation.messages)
                .selectinload(ChatMessage.sender),
                selectinload(ChatConversation.messages)
                .selectinload(ChatMessage.read_statuses),
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create_conversation(self, order_id: int) -> ChatConversation:
        existing = await self.get_conversation_by_order_id(order_id)
        if existing:
            return existing
        convo = ChatConversation(order_id=order_id)
        self.session.add(convo)
        await self.session.flush()
        await self.session.refresh(convo)
        return convo

    async def list_conversations_for_user(
        self, customer_id: int | None, driver_user_id: int | None
    ) -> list[ChatConversation]:
        """Return all conversations where the user is the customer or the assigned driver."""
        from app.models.driver import Driver
        from app.models.order import Order

        opts = [
            selectinload(ChatConversation.messages).selectinload(ChatMessage.sender),
            selectinload(ChatConversation.messages).selectinload(ChatMessage.read_statuses),
        ]

        if customer_id is not None:
            stmt = (
                select(ChatConversation)
                .join(Order, Order.id == ChatConversation.order_id)
                .where(Order.customer_id == customer_id)
                .options(*opts)
                .order_by(ChatConversation.updated_at.desc())
            )
        else:
            # driver_user_id path: join through drivers table
            stmt = (
                select(ChatConversation)
                .join(Order, Order.id == ChatConversation.order_id)
                .join(Driver, Driver.id == Order.driver_id)
                .where(Driver.user_id == driver_user_id)
                .options(*opts)
                .order_by(ChatConversation.updated_at.desc())
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_messages(self, conversation_id: int) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .options(selectinload(ChatMessage.sender))
            .order_by(ChatMessage.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_message(
        self, conversation_id: int, sender_id: int, body: str
    ) -> ChatMessage:
        msg = ChatMessage(conversation_id=conversation_id, sender_id=sender_id, body=body)
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg, ["sender"])
        return msg

    # ------------------------------------------------------------------
    # Read receipts
    # ------------------------------------------------------------------

    async def get_read_user_ids_for_message(self, message_id: int) -> set[int]:
        stmt = select(MessageReadStatus.user_id).where(
            MessageReadStatus.message_id == message_id
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return set(rows)

    async def get_unread_message_ids(
        self, conversation_id: int, user_id: int
    ) -> list[int]:
        """Return IDs of messages in the conversation not yet read by user_id."""
        subq = select(MessageReadStatus.message_id).where(
            MessageReadStatus.user_id == user_id
        )
        stmt = (
            select(ChatMessage.id)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.id.not_in(subq))
            .where(ChatMessage.sender_id != user_id)  # don't count own messages
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_unread_count(self, conversation_id: int, user_id: int) -> int:
        ids = await self.get_unread_message_ids(conversation_id, user_id)
        return len(ids)

    async def mark_messages_read(
        self, message_ids: list[int], user_id: int
    ) -> list[int]:
        """Insert read receipts for all unread messages. Returns the ids actually marked."""
        already_stmt = select(MessageReadStatus.message_id).where(
            MessageReadStatus.message_id.in_(message_ids),
            MessageReadStatus.user_id == user_id,
        )
        already = set((await self.session.execute(already_stmt)).scalars().all())
        to_mark = [mid for mid in message_ids if mid not in already]
        for mid in to_mark:
            self.session.add(MessageReadStatus(message_id=mid, user_id=user_id))
        if to_mark:
            await self.session.flush()
        return to_mark
