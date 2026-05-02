from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class MessageSenderSchema(ORMModel):
    id: int
    full_name: str


class ChatMessageSchema(ORMModel):
    id: int
    conversation_id: int
    sender_id: int
    sender: MessageSenderSchema
    body: str
    created_at: datetime
    is_read: bool = False  # populated by service layer, not from ORM directly


class SendMessageRequest(ORMModel):
    body: str = Field(min_length=1, max_length=4000)


class ConversationSummarySchema(ORMModel):
    id: int
    order_id: int
    last_message: ChatMessageSchema | None = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationDetailSchema(ORMModel):
    id: int
    order_id: int
    messages: list[ChatMessageSchema]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# WebSocket event envelopes
# ---------------------------------------------------------------------------

class WSNewMessagePayload(ORMModel):
    message: ChatMessageSchema


class WSMessagesReadPayload(ORMModel):
    conversation_id: int
    read_by_user_id: int
    message_ids: list[int]


class WSEvent(ORMModel):
    event_type: str  # "new_message" | "messages_read"
    payload: dict
