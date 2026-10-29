"""Request and response models shared by the REST API and the MCP tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, Field


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
Scope = Literal["read", "write", "dm"]
NotificationType = Literal["like", "comment", "follow", "mention"]

T = TypeVar("T")


class UserBrief(BaseModel):
    id: int
    username: str
    display_name: str


class UserOut(UserBrief):
    bio: str
    created_at: UtcDatetime
    posts_count: int
    followers_count: int
    following_count: int
    is_me: bool
    is_following: bool = Field(description="The current user follows this user")
    follows_you: bool = Field(description="This user follows the current user")


class PostOut(BaseModel):
    id: int
    author: UserBrief
    content: str
    tags: list[str]
    via: str | None = Field(description="AI assistant / API token that created it; null when posted from the web")
    created_at: UtcDatetime
    edited_at: UtcDatetime | None
    like_count: int
    comment_count: int
    liked_by_me: bool


class CommentOut(BaseModel):
    id: int
    post_id: int
    author: UserBrief
    content: str
    via: str | None
    created_at: UtcDatetime


class NotificationOut(BaseModel):
    id: int
    type: NotificationType
    actor: UserBrief
    post_id: int | None
    comment_id: int | None
    summary: str
    read: bool
    created_at: UtcDatetime


class MessageOut(BaseModel):
    id: int
    sender: UserBrief
    recipient: UserBrief
    content: str
    via: str | None
    created_at: UtcDatetime
    read: bool


class ConversationOut(BaseModel):
    user: UserBrief
    last_message: MessageOut
    unread_count: int


class TagCount(BaseModel):
    tag: str
    count: int


class UnreadCounts(BaseModel):
    notifications: int
    messages: int | None = Field(description="null when the token has no 'dm' scope")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: int | None = Field(
        default=None, description="Pass as `cursor` to fetch the next page; null when there are no more items"
    )


class NotificationPage(Page[NotificationOut]):
    unread_count: int


class ActionResult(BaseModel):
    ok: bool = True
    message: str


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[Scope]
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None
    expires_at: UtcDatetime | None


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


class RegisterIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,30}$", description="3-30 letters, digits or underscores")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=50)


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=50)
    bio: str | None = Field(default=None, max_length=300)


class PostIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="Shown as 'via <name>' on content the token creates")
    scopes: list[Scope] = Field(default_factory=lambda: ["read", "write"])


class MarkReadIn(BaseModel):
    ids: list[int] | None = Field(default=None, description="Notification ids to mark read; omit to mark all")
