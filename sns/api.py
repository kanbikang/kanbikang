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
Cursor = Annotated[int | None, Query(description="이전 응답의 next_cursor")]
Limit = Annotated[int, Query(ge=1, le=services.MAX_LIMIT)]


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
    return services.create_token(db, actor, body.name, body.scopes)


@router.delete("/tokens/{token_id}", tags=["ai"])
def revoke_token(token_id: int, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.revoke_token(db, actor, token_id)


@router.get("/ai/tools", tags=["ai"])
async def list_ai_tools(request: Request) -> list[schemas.ToolInfo]:
    """MCP tools an AI assistant can call, with the token scope each one needs."""
    tools = await request.app.state.mcp.list_tools()
    return [
        schemas.ToolInfo(name=t.name, title=t.title, description=t.description, scope=(t.meta or {})["sns/scope"])
        for t in tools
    ]


# Me


@router.get("/me", tags=["users"], openapi_extra=mcp_tool("get_me"))
def get_me(db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.get_me(db, actor)


@router.patch("/me", tags=["users"], openapi_extra=mcp_tool("update_profile"))
def update_profile(body: schemas.ProfileUpdate, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.update_profile(db, actor, body.display_name, body.bio)


@router.get("/me/unread", tags=["users"], openapi_extra=mcp_tool("get_unread_counts"))
def get_unread_counts(db: DB, actor: CurrentActor) -> schemas.UnreadCounts:
    return services.get_unread_counts(db, actor)


# Users


@router.get("/users", tags=["users"], openapi_extra=mcp_tool("search_users"))
def search_users(q: str, db: DB, actor: CurrentActor, limit: Limit = 20) -> list[schemas.UserOut]:
    return services.search_users(db, actor, q, limit)


@router.get("/users/{username}", tags=["users"], openapi_extra=mcp_tool("get_user"))
def get_user(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.get_user(db, actor, username)


@router.get("/users/{username}/posts", tags=["posts"], openapi_extra=mcp_tool("list_user_posts"))
def list_user_posts(
    username: str, db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.PostOut]:
    return services.user_posts(db, actor, username, cursor, limit)


@router.get("/users/{username}/followers", tags=["users"], openapi_extra=mcp_tool("list_followers"))
def list_followers(
    username: str, db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.UserOut]:
    return services.list_followers(db, actor, username, cursor, limit)


@router.get("/users/{username}/following", tags=["users"], openapi_extra=mcp_tool("list_following"))
def list_following(
    username: str, db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.UserOut]:
    return services.list_following(db, actor, username, cursor, limit)


@router.put("/users/{username}/follow", tags=["users"], openapi_extra=mcp_tool("follow_user"))
def follow_user(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.follow_user(db, actor, username)


@router.delete("/users/{username}/follow", tags=["users"], openapi_extra=mcp_tool("unfollow_user"))
def unfollow_user(username: str, db: DB, actor: CurrentActor) -> schemas.UserOut:
    return services.unfollow_user(db, actor, username)


# Posts


@router.get("/feed", tags=["posts"], openapi_extra=mcp_tool("get_home_feed"))
def get_home_feed(
    db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.PostOut]:
    return services.home_feed(db, actor, cursor, limit)


@router.get("/posts", tags=["posts"], openapi_extra=mcp_tool("browse_posts"))
def browse_posts(
    db: DB,
    actor: CurrentActor,
    q: Annotated[str | None, Query(description="본문 검색어")] = None,
    tag: Annotated[str | None, Query(description="해시태그 (# 없이)")] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> schemas.Page[schemas.PostOut]:
    return services.browse_posts(db, actor, q, tag, cursor, limit)


@router.post("/posts", tags=["posts"], status_code=201, openapi_extra=mcp_tool("create_post"))
def create_post(body: schemas.PostIn, db: DB, actor: CurrentActor) -> schemas.PostOut:
    return services.create_post(db, actor, body.content)


@router.get("/posts/{post_id}", tags=["posts"], openapi_extra=mcp_tool("get_post"))
def get_post(post_id: int, db: DB, actor: CurrentActor) -> schemas.PostOut:
    return services.get_post(db, actor, post_id)


@router.patch("/posts/{post_id}", tags=["posts"], openapi_extra=mcp_tool("edit_post"))
def edit_post(post_id: int, body: schemas.PostIn, db: DB, actor: CurrentActor) -> schemas.PostOut:
    return services.edit_post(db, actor, post_id, body.content)


@router.delete("/posts/{post_id}", tags=["posts"], openapi_extra=mcp_tool("delete_post"))
def delete_post(post_id: int, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.delete_post(db, actor, post_id)


@router.put("/posts/{post_id}/like", tags=["posts"], openapi_extra=mcp_tool("like_post"))
def like_post(post_id: int, db: DB, actor: CurrentActor) -> schemas.PostOut:
    return services.like_post(db, actor, post_id)


@router.delete("/posts/{post_id}/like", tags=["posts"], openapi_extra=mcp_tool("unlike_post"))
def unlike_post(post_id: int, db: DB, actor: CurrentActor) -> schemas.PostOut:
    return services.unlike_post(db, actor, post_id)


@router.get("/posts/{post_id}/comments", tags=["comments"], openapi_extra=mcp_tool("list_comments"))
def list_comments(
    post_id: int, db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.CommentOut]:
    return services.list_comments(db, actor, post_id, cursor, limit)


@router.post("/posts/{post_id}/comments", tags=["comments"], status_code=201, openapi_extra=mcp_tool("add_comment"))
def add_comment(post_id: int, body: schemas.CommentIn, db: DB, actor: CurrentActor) -> schemas.CommentOut:
    return services.add_comment(db, actor, post_id, body.content)


@router.delete("/comments/{comment_id}", tags=["comments"], openapi_extra=mcp_tool("delete_comment"))
def delete_comment(comment_id: int, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.delete_comment(db, actor, comment_id)


@router.get("/tags/trending", tags=["posts"], openapi_extra=mcp_tool("trending_tags"))
def trending_tags(
    db: DB, actor: CurrentActor, days: Annotated[int, Query(ge=1, le=365)] = 7, limit: Limit = 10
) -> list[schemas.TagCount]:
    return services.trending_tags(db, actor, days, limit)


# Notifications


@router.get("/notifications", tags=["notifications"], openapi_extra=mcp_tool("list_notifications"))
def list_notifications(
    db: DB, actor: CurrentActor, unread_only: bool = False, cursor: Cursor = None, limit: Limit = 20
) -> schemas.NotificationPage:
    return services.list_notifications(db, actor, unread_only, cursor, limit)


@router.post("/notifications/read", tags=["notifications"], openapi_extra=mcp_tool("mark_notifications_read"))
def mark_notifications_read(body: schemas.MarkReadIn, db: DB, actor: CurrentActor) -> schemas.ActionResult:
    return services.mark_notifications_read(db, actor, body.ids)


# Direct messages


@router.get("/messages", tags=["messages"], openapi_extra=mcp_tool("list_conversations"))
def list_conversations(db: DB, actor: CurrentActor) -> list[schemas.ConversationOut]:
    return services.list_conversations(db, actor)


@router.get("/messages/{username}", tags=["messages"], openapi_extra=mcp_tool("read_conversation"))
def read_conversation(
    username: str, db: DB, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 20
) -> schemas.Page[schemas.MessageOut]:
    return services.read_conversation(db, actor, username, cursor, limit)


@router.post("/messages/{username}", tags=["messages"], status_code=201, openapi_extra=mcp_tool("send_message"))
def send_message(username: str, body: schemas.MessageIn, db: DB, actor: CurrentActor) -> schemas.MessageOut:
    return services.send_message(db, actor, username, body.content)
