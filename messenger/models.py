from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp; every datetime column stores naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(50))
    status_message: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiToken(Base):
    """A bearer token. `session` tokens come from web login; `personal` tokens are issued for AI assistants."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[str] = mapped_column(String(100))
    # False: the token may only touch the conversations listed in `conversations`.
    all_conversations: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversations: Mapped[list[TokenConversation]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class TokenConversation(Base):
    __tablename__ = "token_conversations"

    token_id: Mapped[int] = mapped_column(ForeignKey("api_tokens.id", ondelete="CASCADE"), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)


class Contact(Base):
    __tablename__ = "contacts"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    contact: Mapped[User] = relationship(lazy="joined", foreign_keys=[contact_id])


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # "direct" or "group"
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # "<smaller user id>:<larger user id>" for direct conversations, so each pair has exactly one.
    direct_key: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    members: Mapped[list[ConversationMember]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="ConversationMember.joined_at"
    )


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Members see only messages after this id (history before they were invited stays hidden).
    visible_after_message_id: Mapped[int] = mapped_column(Integer, default=0)
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(lazy="joined")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="text")  # "text" or "system"
    content: Mapped[str] = mapped_column(Text)
    via: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sender: Mapped[User | None] = relationship(lazy="joined")
    reply_to: Mapped[Message | None] = relationship(lazy="joined", remote_side=[id], join_depth=1)
