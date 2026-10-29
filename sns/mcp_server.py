"""MCP server: exposes the SNS to AI assistants (Claude Code, Claude Desktop, ...).

Every tool runs as the user who owns the bearer token, through the same service functions
as the REST API, so permissions and validation are identical on both surfaces."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__, schemas, security, services
from .config import Settings
from .db import make_engine, make_session_factory

INSTRUCTIONS = """\
Kanbikang is a social network. You act on behalf of the user who issued your API token.
Posts, comments and messages you create are publicly labeled "via <token name>".
Before publishing, deleting, or sending a direct message, confirm the exact text with the user
unless they already asked for that specific action. Lists are paginated: pass `next_cursor`
back as `cursor` to read further."""

R = TypeVar("R")

Username = Annotated[str, Field(description="Username, with or without a leading @")]
PostId = Annotated[int, Field(description="Post id")]
Cursor = Annotated[int | None, Field(description="`next_cursor` from the previous page")]
Limit = Annotated[int, Field(ge=1, le=services.MAX_LIMIT, description="Max items to return")]
PostText = Annotated[
    str, Field(min_length=1, max_length=services.POST_MAX, description="Text; #tags and @mentions are parsed")
]


def create_mcp_server(session_factory: sessionmaker[Session], *, stdio_token: str | None = None) -> MCPServer:
    """`stdio_token` authenticates calls that arrive without HTTP headers (stdio transport)."""
    mcp = MCPServer("kanbikang", title="Kanbikang SNS", instructions=INSTRUCTIONS, version=__version__)

    def call(ctx: Context, fn: Callable[..., R], *args: Any) -> R:
        headers = ctx.headers
        token = security.parse_bearer(headers.get("authorization")) if headers is not None else stdio_token
        with session_factory() as db:
            try:
                return fn(db, services.authenticate(db, token), *args)
            except services.ServiceError as exc:
                raise ToolError(str(exc)) from exc

    def tool(scope: str, title: str, *, destructive: bool = False, idempotent: bool = False):
        read_only = scope == "read"
        annotations = ToolAnnotations(
            title=title,
            read_only_hint=read_only,
            destructive_hint=None if read_only else destructive,
            idempotent_hint=None if read_only else idempotent,
            open_world_hint=False,
        )

        def register(fn: Callable[..., R]) -> Callable[..., R]:
            mcp.add_tool(fn, title=title, annotations=annotations, meta={"sns/scope": scope})
            return fn

        return register

    # Profile

    @tool("read", "내 프로필 보기")
    def get_me(ctx: Context) -> schemas.UserOut:
        """Get the profile of the user this token belongs to."""
        return call(ctx, services.get_me)

    @tool("read", "읽지 않은 알림/메시지 수")
    def get_unread_counts(ctx: Context) -> schemas.UnreadCounts:
        """Count unread notifications and (with the 'dm' scope) unread direct messages."""
        return call(ctx, services.get_unread_counts)

    @tool("write", "내 프로필 수정", idempotent=True)
    def update_profile(
        ctx: Context,
        display_name: Annotated[str | None, Field(max_length=50)] = None,
        bio: Annotated[str | None, Field(max_length=300)] = None,
    ) -> schemas.UserOut:
        """Update the user's display name and/or bio. Omitted fields stay unchanged."""
        return call(ctx, services.update_profile, display_name, bio)

    # Users

    @tool("read", "사용자 검색")
    def search_users(ctx: Context, query: str, limit: Limit = 20) -> list[schemas.UserOut]:
        """Find users whose username or display name contains `query`."""
        return call(ctx, services.search_users, query, limit)

    @tool("read", "사용자 프로필 보기")
    def get_user(ctx: Context, username: Username) -> schemas.UserOut:
        """Get a user's profile, counts, and whether you follow each other."""
        return call(ctx, services.get_user, username)

    @tool("read", "사용자 게시물 보기")
    def list_user_posts(
        ctx: Context, username: Username, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.Page[schemas.PostOut]:
        """List a user's posts, newest first."""
        return call(ctx, services.user_posts, username, cursor, limit)

    @tool("read", "팔로워 목록")
    def list_followers(
        ctx: Context, username: Username, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.Page[schemas.UserOut]:
        """List users who follow `username`, most recent first."""
        return call(ctx, services.list_followers, username, cursor, limit)

    @tool("read", "팔로잉 목록")
    def list_following(
        ctx: Context, username: Username, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.Page[schemas.UserOut]:
        """List users that `username` follows, most recent first."""
        return call(ctx, services.list_following, username, cursor, limit)

    @tool("write", "팔로우", idempotent=True)
    def follow_user(ctx: Context, username: Username) -> schemas.UserOut:
        """Follow a user. Their posts then appear in the home feed."""
        return call(ctx, services.follow_user, username)

    @tool("write", "언팔로우", idempotent=True)
    def unfollow_user(ctx: Context, username: Username) -> schemas.UserOut:
        """Stop following a user."""
        return call(ctx, services.unfollow_user, username)

    # Posts

    @tool("read", "홈 피드 보기")
    def get_home_feed(ctx: Context, cursor: Cursor = None, limit: Limit = 20) -> schemas.Page[schemas.PostOut]:
        """Posts by the user and everyone they follow, newest first."""
        return call(ctx, services.home_feed, cursor, limit)

    @tool("read", "게시물 탐색/검색")
    def browse_posts(
        ctx: Context,
        query: Annotated[str | None, Field(description="Text to search for in post content")] = None,
        tag: Annotated[str | None, Field(description="Hashtag to filter by, with or without #")] = None,
        cursor: Cursor = None,
        limit: Limit = 20,
    ) -> schemas.Page[schemas.PostOut]:
        """All public posts, newest first, optionally filtered by text and/or hashtag."""
        return call(ctx, services.browse_posts, query, tag, cursor, limit)

    @tool("read", "게시물 보기")
    def get_post(ctx: Context, post_id: PostId) -> schemas.PostOut:
        """Get one post with its like and comment counts. Use list_comments for the comments."""
        return call(ctx, services.get_post, post_id)

    @tool("read", "인기 해시태그")
    def trending_tags(
        ctx: Context, days: Annotated[int, Field(ge=1, le=365)] = 7, limit: Limit = 10
    ) -> list[schemas.TagCount]:
        """Most used hashtags in posts from the last `days` days."""
        return call(ctx, services.trending_tags, days, limit)

    @tool("write", "글 작성")
    def create_post(ctx: Context, content: PostText) -> schemas.PostOut:
        """Publish a new post as the user. It is labeled with this token's name."""
        return call(ctx, services.create_post, content)

    @tool("write", "글 수정", idempotent=True)
    def edit_post(ctx: Context, post_id: PostId, content: PostText) -> schemas.PostOut:
        """Replace the text of one of the user's own posts."""
        return call(ctx, services.edit_post, post_id, content)

    @tool("write", "글 삭제", destructive=True, idempotent=True)
    def delete_post(ctx: Context, post_id: PostId) -> schemas.ActionResult:
        """Permanently delete one of the user's own posts, with its comments and likes."""
        return call(ctx, services.delete_post, post_id)

    @tool("write", "좋아요", idempotent=True)
    def like_post(ctx: Context, post_id: PostId) -> schemas.PostOut:
        """Like a post."""
        return call(ctx, services.like_post, post_id)

    @tool("write", "좋아요 취소", idempotent=True)
    def unlike_post(ctx: Context, post_id: PostId) -> schemas.PostOut:
        """Remove the user's like from a post."""
        return call(ctx, services.unlike_post, post_id)

    # Comments

    @tool("read", "댓글 보기")
    def list_comments(
        ctx: Context, post_id: PostId, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.Page[schemas.CommentOut]:
        """List a post's comments, oldest first."""
        return call(ctx, services.list_comments, post_id, cursor, limit)

    @tool("write", "댓글 작성")
    def add_comment(
        ctx: Context,
        post_id: PostId,
        content: Annotated[str, Field(min_length=1, max_length=services.COMMENT_MAX)],
    ) -> schemas.CommentOut:
        """Comment on a post as the user."""
        return call(ctx, services.add_comment, post_id, content)

    @tool("write", "댓글 삭제", destructive=True, idempotent=True)
    def delete_comment(ctx: Context, comment_id: int) -> schemas.ActionResult:
        """Delete a comment written by the user, or any comment on the user's own post."""
        return call(ctx, services.delete_comment, comment_id)

    # Notifications

    @tool("read", "알림 보기")
    def list_notifications(
        ctx: Context, unread_only: bool = False, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.NotificationPage:
        """Likes, comments, follows and mentions directed at the user, newest first. Does not mark them read."""
        return call(ctx, services.list_notifications, unread_only, cursor, limit)

    @tool("write", "알림 읽음 처리", idempotent=True)
    def mark_notifications_read(
        ctx: Context, ids: Annotated[list[int] | None, Field(description="Ids to mark; omit to mark all")] = None
    ) -> schemas.ActionResult:
        """Mark notifications as read."""
        return call(ctx, services.mark_notifications_read, ids)

    # Direct messages

    @tool("dm", "대화 목록")
    def list_conversations(ctx: Context) -> list[schemas.ConversationOut]:
        """Direct message conversations with their latest message and unread count."""
        return call(ctx, services.list_conversations)

    @tool("dm", "대화 읽기")
    def read_conversation(
        ctx: Context, username: Username, cursor: Cursor = None, limit: Limit = 20
    ) -> schemas.Page[schemas.MessageOut]:
        """Messages exchanged with `username`, newest first. Marks their messages as read."""
        return call(ctx, services.read_conversation, username, cursor, limit)

    @tool("dm", "메시지 보내기")
    def send_message(
        ctx: Context,
        username: Username,
        content: Annotated[str, Field(min_length=1, max_length=services.MESSAGE_MAX)],
    ) -> schemas.MessageOut:
        """Send a private direct message to `username` as the user."""
        return call(ctx, services.send_message, username, content)

    # Prompts (shown as slash commands in MCP clients)

    @mcp.prompt(title="피드 따라잡기")
    def catch_up() -> str:
        """Summarize what happened on Kanbikang since you last checked."""
        return (
            "Kanbikang에서 내가 놓친 것을 정리해줘. list_notifications(unread_only=true)로 읽지 않은 알림을, "
            "get_home_feed로 최근 피드를 확인하고, 중요한 글과 답장이 필요한 항목을 짧게 요약해줘. "
            "알림을 읽음 처리하거나 글을 쓰기 전에는 나에게 먼저 확인해."
        )

    @mcp.prompt(title="글 초안 쓰기")
    def draft_post(topic: str) -> str:
        """Draft a post about a topic and publish it only after approval."""
        return (
            f"'{topic}'에 대한 Kanbikang 게시물 초안을 {services.POST_MAX}자 이내로 써줘. "
            "trending_tags로 관련 해시태그가 있는지 확인해서 어울리면 넣어줘. "
            "초안을 보여주고 내가 승인하면 create_post로 게시해."
        )

    return mcp


class McpAuthGate:
    """Answers 401 before the MCP transport runs when the bearer token is missing or invalid,
    so clients fail at connect time with a clear error instead of on every tool call."""

    def __init__(self, app: ASGIApp, session_factory: sessionmaker[Session]):
        self._app = app
        self._session_factory = session_factory

    def _is_valid(self, token: str) -> bool:
        with self._session_factory() as db:
            try:
                services.authenticate(db, token)
            except services.Unauthorized:
                return False
            return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            token = security.parse_bearer(Headers(scope=scope).get("authorization"))
            if token is None or not await anyio.to_thread.run_sync(self._is_valid, token):
                response = JSONResponse(
                    {"detail": "유효한 API 토큰이 필요합니다 (Authorization: Bearer <token>)"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def run_stdio() -> None:
    """Entry point for MCP clients that launch a local stdio server (same machine as the database)."""
    token = os.environ.get("SNS_API_TOKEN")
    if not token:
        raise SystemExit("SNS_API_TOKEN 환경 변수에 개인 API 토큰을 설정하세요")
    settings = Settings.from_env()
    session_factory = make_session_factory(make_engine(settings.database_url))
    create_mcp_server(session_factory, stdio_token=token).run("stdio")
