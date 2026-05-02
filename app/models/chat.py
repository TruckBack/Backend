from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


class ChatConversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "chat_conversations"

    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    order: Mapped["Order"] = relationship("Order")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="conversation",
        order_by="ChatMessage.created_at",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base, IdMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["ChatConversation"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship("User")
    read_statuses: Mapped[list["MessageReadStatus"]] = relationship(
        "MessageReadStatus",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageReadStatus(Base, IdMixin, TimestampMixin):
    __tablename__ = "message_read_statuses"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_read_message_user"),)

    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    message: Mapped["ChatMessage"] = relationship(back_populates="read_statuses")
    user: Mapped["User"] = relationship("User")
