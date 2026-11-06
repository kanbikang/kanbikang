"""MCP server: exposes the messenger to AI assistants (Claude Code, Claude Desktop, ...).

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
Kanbikang is a messenger. You act on behalf of the user who issued your API token.
Messages you send are shown to everyone in the conversation labeled "via <token name>".
Before sending, editing or deleting a message, or changing a group, confirm the exact action with the
user unless they already asked for that specific action. Reading messages never marks them read; call
mark_read only when the user wants the other people to see their messages as read (sending a message
marks the conversation read, as in other messengers). Message pages are oldest first; pass `next_cursor`
back as `before` to read older messages."""

R = TypeVar("R")

ConversationId = Annotated[int, Field(description="Conversation id from list_conversations")]
MessageId = Annotated[int, Field(description="Message id")]
Username = Annotated[str, Field(description="Username, with or without a leading @")]
Usernames = Annotated[list[str], Field(min_length=1, max_length=50, description="Usernames to include")]
MessageText = Annotated[str, Field(min_length=1, max_length=services.MESSAGE_MAX)]
Limit = Annotated[int | None, Field(ge=1, le=services.MAX_LIMIT, description="Max items to return")]


def create_mcp_server(session_factory: sessionmaker[Session], *, stdio_token: str | None = None) -> MCPServer:
    """`stdio_token` authenticates calls that arrive without HTTP headers (stdio transport)."""
    mcp = MCPServer("kanbikang", title="Kanbikang Messenger", instructions=INSTRUCTIONS, version=__version__)

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
            mcp.add_tool(fn, title=title, annotations=annotations, meta={"kanbikang/scope": scope})
            return fn

        return register

    # Profile, users and contacts

    @tool("read", "내 프로필 보기")
    def get_me(ctx: Context) -> schemas.UserOut:
        """Get the profile of the user this token belongs to."""
        return call(ctx, services.get_me)

    @tool("write", "내 프로필 수정", idempotent=True)
    def update_profile(
        ctx: Context,
        display_name: Annotated[str | None, Field(max_length=50)] = None,
        status_message: Annotated[str | None, Field(max_length=100)] = None,
    ) -> schemas.UserOut:
        """Update the user's display name and/or status message. Omitted fields stay unchanged."""
        return call(ctx, services.update_profile, display_name, status_message)

    @tool("read", "사용자 검색")
    def search_users(ctx: Context, query: str, limit: Limit = None) -> list[schemas.UserOut]:
        """Find users whose username or display name contains `query`."""
        return call(ctx, services.search_users, query, limit)

    @tool("read", "사용자 정보 보기")
    def get_user(ctx: Context, username: Username) -> schemas.UserOut:
        """Get a user's profile and whether they are in the user's contacts."""
        return call(ctx, services.get_user, username)

    @tool("read", "친구 목록")
    def list_contacts(ctx: Context) -> list[schemas.UserOut]:
        """The user's contacts (friends list), sorted by name."""
        return call(ctx, services.list_contacts)

    @tool("write", "친구 추가", idempotent=True)
    def add_contact(ctx: Context, username: Username) -> schemas.UserOut:
        """Add a user to the user's contacts."""
        return call(ctx, services.add_contact, username)

    @tool("write", "친구 삭제", idempotent=True)
    def remove_contact(ctx: Context, username: Username) -> schemas.UserOut:
        """Remove a user from the user's contacts. Existing conversations are kept."""
        return call(ctx, services.remove_contact, username)

    # Conversations

    @tool("read", "대화방 목록")
    def list_conversations(ctx: Context, limit: Limit = None) -> list[schemas.ConversationOut]:
        """Conversations with their members, latest message and unread count, most recently active first."""
        return call(ctx, services.list_conversations, limit)

    @tool("read", "대화방 정보")
    def get_conversation(ctx: Context, conversation_id: ConversationId) -> schemas.ConversationOut:
        """One conversation with its members, how far each has read, latest message and unread count."""
        return call(ctx, services.get_conversation, conversation_id)

    @tool("write", "1:1 대화방 열기", idempotent=True)
    def open_direct_conversation(ctx: Context, username: Username) -> schemas.ConversationOut:
        """Get the 1:1 conversation with a user, creating it if it does not exist yet."""
        return call(ctx, services.open_direct_conversation, username)

    @tool("write", "그룹 대화방 만들기")
    def create_group(
        ctx: Context,
        usernames: Usernames,
        title: Annotated[str | None, Field(max_length=100, description="Optional group name")] = None,
    ) -> schemas.ConversationOut:
        """Create a group conversation with the given users."""
        return call(ctx, services.create_group, title, usernames)

    @tool("write", "그룹 이름 바꾸기", idempotent=True)
    def rename_group(
        ctx: Context, conversation_id: ConversationId, title: Annotated[str, Field(min_length=1, max_length=100)]
    ) -> schemas.ConversationOut:
        """Rename a group conversation. Members see a notice in the conversation."""
        return call(ctx, services.rename_group, conversation_id, title)

    @tool("write", "그룹에 초대")
    def add_members(ctx: Context, conversation_id: ConversationId, usernames: Usernames) -> schemas.ConversationOut:
        """Invite users to a group conversation. They see only messages sent after they join."""
        return call(ctx, services.add_members, conversation_id, usernames)

    @tool("write", "그룹 나가기", destructive=True, idempotent=True)
    def leave_conversation(ctx: Context, conversation_id: ConversationId) -> schemas.ActionResult:
        """Leave a group conversation. The user loses access to its messages."""
        return call(ctx, services.leave_conversation, conversation_id)

    @tool("write", "읽음 처리", idempotent=True)
    def mark_read(
        ctx: Context,
        conversation_id: ConversationId,
        message_id: Annotated[int | None, Field(description="Last message read; omit to mark everything")] = None,
    ) -> schemas.ConversationOut:
        """Mark messages as read. Other members then see them as read by the user."""
        return call(ctx, services.mark_read, conversation_id, message_id)

    # Messages

    @tool("read", "메시지 읽기")
    def read_messages(
        ctx: Context,
        conversation_id: ConversationId,
        before: Annotated[int | None, Field(description="`next_cursor` from the previous page")] = None,
        limit: Limit = None,
    ) -> schemas.Page[schemas.MessageOut]:
        """Messages in a conversation, oldest first (default: the latest 30). Does not mark them read."""
        return call(ctx, services.read_messages, conversation_id, before, limit)

    @tool("read", "안 읽은 메시지 모아보기")
    def list_unread_messages(ctx: Context, limit_per_conversation: Limit = None) -> list[schemas.UnreadThread]:
        """Every conversation with unread messages, with its most recent unread messages. Does not mark them read."""
        return call(ctx, services.list_unread, limit_per_conversation)

    @tool("read", "메시지 검색")
    def search_messages(
        ctx: Context,
        query: str,
        conversation_id: Annotated[int | None, Field(description="Search only this conversation")] = None,
        limit: Limit = None,
    ) -> list[schemas.MessageOut]:
        """Find messages containing `query`, newest first."""
        return call(ctx, services.search_messages, query, conversation_id, limit)

    @tool("write", "메시지 보내기")
    def send_message(
        ctx: Context,
        conversation_id: ConversationId,
        content: MessageText,
        reply_to_id: Annotated[int | None, Field(description="Message id to reply to")] = None,
    ) -> schemas.MessageOut:
        """Send a message to a conversation as the user."""
        return call(ctx, services.send_message, conversation_id, content, reply_to_id)

    @tool("write", "1:1 메시지 보내기")
    def send_direct_message(ctx: Context, username: Username, content: MessageText) -> schemas.MessageOut:
        """Send a message to a user's 1:1 conversation, creating the conversation if needed."""
        return call(ctx, services.send_direct_message, username, content)

    @tool("write", "메시지 수정", idempotent=True)
    def edit_message(ctx: Context, message_id: MessageId, content: MessageText) -> schemas.MessageOut:
        """Replace the text of a message the user sent. Members see it marked as edited."""
        return call(ctx, services.edit_message, message_id, content)

    @tool("write", "메시지 삭제", destructive=True, idempotent=True)
    def delete_message(ctx: Context, message_id: MessageId) -> schemas.MessageOut:
        """Delete a message the user sent, for everyone in the conversation."""
        return call(ctx, services.delete_message, message_id)

    # Prompts (shown as slash commands in MCP clients)

    @mcp.prompt(title="안 읽은 대화 정리")
    def catch_up() -> str:
        """Summarize unread conversations without marking them read."""
        return (
            "Kanbikang 메신저에서 내가 아직 읽지 않은 대화를 정리해줘. list_unread_messages로 확인하고, "
            "대화방별로 누가 무엇을 말했는지와 내가 답해야 할 것을 짧게 요약해줘. "
            "읽음 처리나 답장은 내가 요청하기 전에는 하지 마."
        )

    @mcp.prompt(title="답장 초안 쓰기")
    def draft_reply(conversation: str) -> str:
        """Draft a reply for a conversation and send it only after approval."""
        return (
            f"Kanbikang 메신저의 '{conversation}' 대화방(이름이나 상대방 아이디)을 list_conversations로 찾고, "
            "read_messages로 최근 대화를 읽은 뒤 내가 보낼 답장 초안을 써줘. "
            "초안을 보여주고 내가 승인하면 send_message로 보내."
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
    token = os.environ.get("KANBIKANG_API_TOKEN")
    if not token:
        raise SystemExit("KANBIKANG_API_TOKEN 환경 변수에 개인 API 토큰을 설정하세요")
    settings = Settings.from_env()
    session_factory = make_session_factory(make_engine(settings.database_url))
    create_mcp_server(session_factory, stdio_token=token).run("stdio")
