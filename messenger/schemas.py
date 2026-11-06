"""Request and response models shared by the REST API, the MCP tools and the realtime events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, Field


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
Scope = Literal["read", "write"]

T = TypeVar("T")


class UserBrief(BaseModel):
    id: int
    username: str
    display_name: str


class UserOut(UserBrief):
    status_message: str
    is_me: bool
    is_contact: bool


class MemberOut(UserBrief):
    last_read_message_id: int


class ReplyPreview(BaseModel):
    id: int
    sender: UserBrief | None
    content: str = Field(description="Empty when the original message was deleted")
    deleted: bool


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    kind: Literal["text", "system"]
    sender: UserBrief | None = Field(description="null for system messages")
    content: str = Field(description="Empty when the message was deleted")
    via: str | None = Field(description="AI assistant / API token that sent it; null when sent from the web")
    reply_to: ReplyPreview | None
    created_at: UtcDatetime
    edited_at: UtcDatetime | None
    deleted: bool
    unread_count: int = Field(description="Members other than the sender who have not read it yet")


class ConversationOut(BaseModel):
    id: int
    kind: Literal["direct", "group"]
    title: str = Field(description="Group title, or the other person's name for direct conversations")
    members: list[MemberOut]
    last_message: MessageOut | None
    unread_count: int
    created_at: UtcDatetime


class UnreadThread(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut] = Field(description="Most recent unread messages, oldest first")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: int | None = Field(
        default=None, description="Pass as `before` to fetch older items; null when there are no more"
    )


class ActionResult(BaseModel):
    ok: bool = True
    message: str


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[Scope]
    conversation_ids: list[int] | None = Field(description="Conversations the token may access; null means all")
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None


class TokenCreated(BaseModel):
    token: str = Field(description="Shown only once. Store it in the AI assistant's MCP configuration.")
    info: TokenOut


class AuthResult(BaseModel):
    token: str
    user: UserOut


class ToolInfo(BaseModel):
    name: str
    title: str | None
    description: str | None
    scope: Scope


# Request bodies

Usernames = Annotated[list[str], Field(min_length=1, max_length=50)]


class RegisterIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,30}$", description="3-30 letters, digits or underscores")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=50)


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=50)
    status_message: str | None = Field(default=None, max_length=100)


class DirectIn(BaseModel):
    username: str


class GroupIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    usernames: Usernames


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MembersIn(BaseModel):
    usernames: Usernames


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    reply_to_id: int | None = None


class ContentIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReadIn(BaseModel):
    message_id: int | None = Field(default=None, description="Last message read; omit to mark everything read")


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="Shown as 'via <name>' on messages the token sends")
    scopes: list[Scope] = Field(default_factory=lambda: ["read", "write"])
    conversation_ids: list[int] | None = Field(
        default=None, description="Limit the token to these conversations; omit for all"
    )
