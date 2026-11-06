"""REST API. Each route that an AI assistant may use names its MCP tool counterpart in
`x-mcp-tool`; tests/test_mcp.py checks that the two surfaces stay in sync."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import schemas, services
from .services import Actor

router = APIRouter(prefix="/api")

_bearer = HTTPBearer(auto_error=False, description="웹 로그인 세션 토큰 또는 개인 API 토큰")


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def get_actor(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Actor:
    return services.authenticate(db, credentials.credentials if credentials else None)


CurrentActor = Annotated[Actor, Depends(get_actor)]
Limit = Annotated[int | None, Query(ge=1, le=services.MAX_LIMIT)]


def mcp_tool(name: str) -> dict:
    return {"x-mcp-tool": name}


# Auth


@router.post("/auth/register", tags=["auth"], status_code=201)
def register(body: schemas.RegisterIn, db: DB) -> schemas.AuthResult:
    return services.register(db, body.username, body.password, body.display_name)


@router.post("/auth/login", tags=["auth"])
def login(body: schemas.LoginIn, db: DB) -> schemas.AuthResult:
    return services.login(db, body.username, body.password)


@router.post("/auth/logout", tags=["auth"])
def logout(db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.logout(db, actor)


# Personal API tokens


@router.get("/tokens", tags=["ai"])
def list_tokens(db: DB, actor: CurrentActor) -> list[schemas.TokenOut]:
    return services.list_tokens(db, actor)


@router.post("/tokens", tags=["ai"], status_code=201)
def create_token(body: schemas.TokenIn, db: DB, actor: CurrentActor) -> schemas.TokenCreated:
    return services.create_token(db, actor, body.name, body.scopes, body.conversation_ids)


@router.delete("/tokens/{token_id}", tags=["ai"])
def revoke_token(token_id: int, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.revoke_token(db, actor, token_id)


@router.get("/ai/tools", tags=["ai"])
async def list_ai_tools(request: Request) -> list[schemas.ToolInfo]:
    """MCP tools an AI assistant can call, with the token scope each one needs."""
    tools = await request.app.state.mcp.list_tools()
    return [
        schemas.ToolInfo(name=t.name, title=t.title, description=t.description, scope=(t.meta or {})["kanbikang/scope"])
        for t in tools
    ]


# Profile, users and contacts


@router.get("/me", tags=["users"], openapi_extra=mcp_tool("get_me"))
def get_me(db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.get_me(db, actor)


@router.patch("/me", tags=["users"], openapi_extra=mcp_tool("update_profile"))
def update_profile(body: schemas.ProfileUpdate, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.update_profile(db, actor, body.display_name, body.status_message)


@router.get("/users", tags=["users"], openapi_extra=mcp_tool("search_users"))
def search_users(q: str, db: DB, actor: CurrentActor, limit: Limit = None) -> list[schemas.UserOut]:
    return services.search_users(db, actor, q, limit)


@router.get("/users/{username}", tags=["users"], openapi_extra=mcp_tool("get_user"))
def get_user(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.get_user(db, actor, username)


@router.post(
    "/users/{username}/messages", tags=["messages"], status_code=201, openapi_extra=mcp_tool("send_direct_message")
)
def send_direct_message(username: str, body: schemas.ContentIn, db: DB, actor: CurrentActor) -> schemas.MessageOut:
    return services.send_direct_message(db, actor, username, body.content)


@router.get("/contacts", tags=["contacts"], openapi_extra=mcp_tool("list_contacts"))
def list_contacts(db: DB, actor: CurrentActor) -> list[schemas.UserOut]:
    return services.list_contacts(db, actor)


@router.put("/contacts/{username}", tags=["contacts"], openapi_extra=mcp_tool("add_contact"))
def add_contact(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.add_contact(db, actor, username)


@router.delete("/contacts/{username}", tags=["contacts"], openapi_extra=mcp_tool("remove_contact"))
def remove_contact(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.remove_contact(db, actor, username)


# Conversations


@router.get("/conversations", tags=["conversations"], openapi_extra=mcp_tool("list_conversations"))
def list_conversations(db: DB, actor: CurrentActor, limit: Limit = None) -> list[schemas.ConversationOut]:
    return services.list_conversations(db, actor, limit)


@router.post("/conversations/direct", tags=["conversations"], openapi_extra=mcp_tool("open_direct_conversation"))
def open_direct_conversation(body: schemas.DirectIn, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.open_direct_conversation(db, actor, body.username)


@router.post("/conversations/group", tags=["conversations"], status_code=201, openapi_extra=mcp_tool("create_group"))
def create_group(body: schemas.GroupIn, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.create_group(db, actor, body.title, body.usernames)


@router.get("/conversations/{conversation_id}", tags=["conversations"], openapi_extra=mcp_tool("get_conversation"))
def get_conversation(conversation_id: int, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.get_conversation(db, actor, conversation_id)


@router.patch("/conversations/{conversation_id}", tags=["conversations"], openapi_extra=mcp_tool("rename_group"))
def rename_group(conversation_id: int, body: schemas.RenameIn, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.rename_group(db, actor, conversation_id, body.title)


@router.post("/conversations/{conversation_id}/members", tags=["conversations"], openapi_extra=mcp_tool("add_members"))
def add_members(conversation_id: int, body: schemas.MembersIn, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.add_members(db, actor, conversation_id, body.usernames)


@router.delete(
    "/conversations/{conversation_id}/members/me", tags=["conversations"], openapi_extra=mcp_tool("leave_conversation")
)
def leave_conversation(conversation_id: int, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.leave_conversation(db, actor, conversation_id)


@router.post("/conversations/{conversation_id}/read", tags=["conversations"], openapi_extra=mcp_tool("mark_read"))
def mark_read(conversation_id: int, body: schemas.ReadIn, db: DB, actor: CurrentActor) -> schemas.ConversationOut:
    return services.mark_read(db, actor, conversation_id, body.message_id)


# Messages


@router.get("/conversations/{conversation_id}/messages", tags=["messages"], openapi_extra=mcp_tool("read_messages"))
def read_messages(
    conversation_id: int,
    db: DB,
    actor: CurrentActor,
    before: Annotated[int | None, Query(description="이전 응답의 next_cursor")] = None,
    limit: Limit = None,
) -> schemas.Page[schemas.MessageOut]:
    return services.read_messages(db, actor, conversation_id, before, limit)


@router.post(
    "/conversations/{conversation_id}/messages",
    tags=["messages"],
    status_code=201,
    openapi_extra=mcp_tool("send_message"),
)
def send_message(conversation_id: int, body: schemas.MessageIn, db: DB, actor: CurrentActor) -> schemas.MessageOut:
    return services.send_message(db, actor, conversation_id, body.content, body.reply_to_id)


@router.get("/messages/unread", tags=["messages"], openapi_extra=mcp_tool("list_unread_messages"))
def list_unread_messages(
    db: DB, actor: CurrentActor, limit_per_conversation: Limit = None
) -> list[schemas.UnreadThread]:
    return services.list_unread(db, actor, limit_per_conversation)


@router.get("/messages/search", tags=["messages"], openapi_extra=mcp_tool("search_messages"))
def search_messages(
    q: str, db: DB, actor: CurrentActor, conversation_id: int | None = None, limit: Limit = None
) -> list[schemas.MessageOut]:
    return services.search_messages(db, actor, q, conversation_id, limit)


@router.patch("/messages/{message_id}", tags=["messages"], openapi_extra=mcp_tool("edit_message"))
def edit_message(message_id: int, body: schemas.ContentIn, db: DB, actor: CurrentActor) -> schemas.MessageOut:
    return services.edit_message(db, actor, message_id, body.content)


@router.delete("/messages/{message_id}", tags=["messages"], openapi_extra=mcp_tool("delete_message"))
def delete_message(message_id: int, db: DB, actor: CurrentActor) -> schemas.MessageOut:
    return services.delete_message(db, actor, message_id)
