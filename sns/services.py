"""Business logic. The REST API and the MCP server are thin adapters over these functions,
so every capability (and every permission check) is identical on both surfaces."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Select, and_, case, delete, func, or_, select, update
from sqlalchemy.orm import Session

from . import models, schemas, security
from .models import Comment, Follow, Like, Message, Notification, Post, PostTag, User, utcnow

ALL_SCOPES = frozenset({"read", "write", "dm"})
SESSION_TTL = timedelta(days=30)
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
POST_MAX = 500
COMMENT_MAX = 500
MESSAGE_MAX = 1000

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,30}")
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,30})")
TAG_RE = re.compile(r"(?<![\w#])#(\w{1,50})")

_DUMMY_PASSWORD_HASH = security.hash_password("timing-equalizer")


class ServiceError(Exception):
    status_code = 400


class InvalidInput(ServiceError):
    status_code = 422


class Unauthorized(ServiceError):
    status_code = 401


class Forbidden(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


@dataclass(frozen=True)
class Actor:
    """Who is calling, and with which token."""

    user_id: int
    token_id: int
    kind: str  # "session" (web login) or "personal" (API / AI assistant token)
    scopes: frozenset[str]
    via: str | None  # label stored on content created through a personal token

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise Forbidden(f"이 토큰에는 '{scope}' 권한이 없습니다")

    def require_session(self) -> None:
        if self.kind != "session":
            raise Forbidden("토큰 관리는 웹 로그인 세션에서만 할 수 있습니다")


# Helpers


def _clean(text: str | None, label: str, max_len: int) -> str:
    value = (text or "").strip()
    if not value:
        raise InvalidInput(f"{label}을(를) 입력하세요")
    if len(value) > max_len:
        raise InvalidInput(f"{label}은(는) {max_len}자 이하여야 합니다")
    return value


def _limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit은 1~{MAX_LIMIT} 사이여야 합니다")
    return limit


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def extract_tags(content: str) -> list[str]:
    return _unique([tag.lower() for tag in TAG_RE.findall(content)])


def extract_mentions(content: str) -> list[str]:
    return _unique([name.lower() for name in MENTION_RE.findall(content)])


def _brief(user: User) -> schemas.UserBrief:
    return schemas.UserBrief(id=user.id, username=user.username, display_name=user.display_name)


def _find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.strip().lstrip("@").lower()))


def _get_user(db: Session, username: str) -> User:
    user = _find_user(db, username)
    if user is None:
        raise NotFound(f"사용자 @{username.lstrip('@')}을(를) 찾을 수 없습니다")
    return user


def _get_post(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise NotFound(f"게시물 #{post_id}을(를) 찾을 수 없습니다")
    return post


def _counts(db: Session, column, ids: Sequence[int]) -> dict[int, int]:
    rows = db.execute(select(column, func.count()).where(column.in_(ids)).group_by(column)).all()
    return {key: count for key, count in rows}


def _users_out(db: Session, users: Sequence[User], viewer_id: int) -> list[schemas.UserOut]:
    ids = [u.id for u in users]
    if not ids:
        return []
    posts = _counts(db, Post.author_id, ids)
    followers = _counts(db, Follow.followee_id, ids)
    following = _counts(db, Follow.follower_id, ids)
    i_follow = set(
        db.scalars(select(Follow.followee_id).where(Follow.follower_id == viewer_id, Follow.followee_id.in_(ids)))
    )
    follow_me = set(
        db.scalars(select(Follow.follower_id).where(Follow.followee_id == viewer_id, Follow.follower_id.in_(ids)))
    )
    return [
        schemas.UserOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            bio=u.bio,
            created_at=u.created_at,
            posts_count=posts.get(u.id, 0),
            followers_count=followers.get(u.id, 0),
            following_count=following.get(u.id, 0),
            is_me=u.id == viewer_id,
            is_following=u.id in i_follow,
            follows_you=u.id in follow_me,
        )
        for u in users
    ]


def _posts_out(db: Session, posts: Sequence[Post], viewer_id: int) -> list[schemas.PostOut]:
    ids = [p.id for p in posts]
    if not ids:
        return []
    likes = _counts(db, Like.post_id, ids)
    comments = _counts(db, Comment.post_id, ids)
    liked = set(db.scalars(select(Like.post_id).where(Like.user_id == viewer_id, Like.post_id.in_(ids))))
    return [
        schemas.PostOut(
            id=p.id,
            author=_brief(p.author),
            content=p.content,
            tags=[t.tag for t in p.tags],
            via=p.via,
            created_at=p.created_at,
            edited_at=p.edited_at,
            like_count=likes.get(p.id, 0),
            comment_count=comments.get(p.id, 0),
            liked_by_me=p.id in liked,
        )
        for p in posts
    ]


def _comment_out(comment: Comment) -> schemas.CommentOut:
    return schemas.CommentOut(
        id=comment.id,
        post_id=comment.post_id,
        author=_brief(comment.author),
        content=comment.content,
        via=comment.via,
        created_at=comment.created_at,
    )


def _message_out(message: Message) -> schemas.MessageOut:
    return schemas.MessageOut(
        id=message.id,
        sender=_brief(message.sender),
        recipient=_brief(message.recipient),
        content=message.content,
        via=message.via,
        created_at=message.created_at,
        read=message.read_at is not None,
    )


_NOTIFICATION_TEXT = {
    "like": "{name}님이 회원님의 게시물을 좋아합니다",
    "comment": "{name}님이 회원님의 게시물에 댓글을 남겼습니다",
    "follow": "{name}님이 회원님을 팔로우합니다",
    "mention": "{name}님이 회원님을 언급했습니다",
}


def _notification_out(n: Notification) -> schemas.NotificationOut:
    return schemas.NotificationOut(
        id=n.id,
        type=n.type,
        actor=_brief(n.actor),
        post_id=n.post_id,
        comment_id=n.comment_id,
        summary=_NOTIFICATION_TEXT[n.type].format(name=n.actor.display_name),
        read=n.read,
        created_at=n.created_at,
    )


def _notify(db: Session, user_id: int, actor_id: int, kind: str, *, post_id=None, comment_id=None) -> None:
    if user_id != actor_id:
        db.add(Notification(user_id=user_id, actor_id=actor_id, type=kind, post_id=post_id, comment_id=comment_id))


def _notify_mentions(db: Session, actor_id: int, names: list[str], *, post_id: int, comment_id=None) -> None:
    for name in names:
        user = _find_user(db, name)
        if user is not None:
            _notify(db, user.id, actor_id, "mention", post_id=post_id, comment_id=comment_id)


def _post_page(db: Session, actor: Actor, stmt: Select, cursor: int | None, limit: int | None):
    limit = _limit(limit)
    if cursor is not None:
        stmt = stmt.where(Post.id < cursor)
    rows = list(db.scalars(stmt.order_by(Post.id.desc()).limit(limit + 1)).unique())
    page = rows[:limit]
    next_cursor = page[-1].id if len(rows) > limit else None
    return schemas.Page[schemas.PostOut](items=_posts_out(db, page, actor.user_id), next_cursor=next_cursor)


def _issue_token(
    db: Session, user_id: int, *, kind: str, name: str, scopes, ttl: timedelta | None
) -> tuple[str, models.ApiToken]:
    raw = security.new_token()
    row = models.ApiToken(
        user_id=user_id,
        kind=kind,
        name=name,
        token_hash=security.hash_token(raw),
        prefix=raw[: len(security.TOKEN_PREFIX) + 6],
        scopes=" ".join(sorted(scopes)),
        expires_at=utcnow() + ttl if ttl else None,
    )
    db.add(row)
    db.flush()
    return raw, row


def _token_out(row: models.ApiToken) -> schemas.TokenOut:
    return schemas.TokenOut(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=row.scopes.split(),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
    )


# Authentication


def register(db: Session, username: str, password: str, display_name: str | None = None) -> schemas.AuthResult:
    if not USERNAME_RE.fullmatch(username or ""):
        raise InvalidInput("아이디는 영문, 숫자, _ 조합 3~30자여야 합니다")
    if len(password or "") < 8:
        raise InvalidInput("비밀번호는 8자 이상이어야 합니다")
    if _find_user(db, username) is not None:
        raise Conflict("이미 사용 중인 아이디입니다")
    name = (display_name or "").strip()[:50] or username
    user = User(username=username, display_name=name, password_hash=security.hash_password(password))
    db.add(user)
    db.flush()
    token, _ = _issue_token(db, user.id, kind="session", name="web", scopes=ALL_SCOPES, ttl=SESSION_TTL)
    db.commit()
    return schemas.AuthResult(token=token, user=_users_out(db, [user], user.id)[0])


def login(db: Session, username: str, password: str) -> schemas.AuthResult:
    user = _find_user(db, username or "")
    if user is None:
        security.verify_password(password or "", _DUMMY_PASSWORD_HASH)
        raise Unauthorized("아이디 또는 비밀번호가 올바르지 않습니다")
    if not security.verify_password(password or "", user.password_hash):
        raise Unauthorized("아이디 또는 비밀번호가 올바르지 않습니다")
    token, _ = _issue_token(db, user.id, kind="session", name="web", scopes=ALL_SCOPES, ttl=SESSION_TTL)
    db.commit()
    return schemas.AuthResult(token=token, user=_users_out(db, [user], user.id)[0])


def authenticate(db: Session, raw_token: str | None) -> Actor:
    if not raw_token:
        raise Unauthorized("인증이 필요합니다 (Authorization: Bearer <token>)")
    row = db.scalar(select(models.ApiToken).where(models.ApiToken.token_hash == security.hash_token(raw_token)))
    now = utcnow()
    if row is None or (row.expires_at is not None and row.expires_at <= now):
        raise Unauthorized("유효하지 않거나 만료된 토큰입니다")
    if row.last_used_at is None or now - row.last_used_at > timedelta(minutes=1):
        row.last_used_at = now
        db.commit()
    return Actor(
        user_id=row.user_id,
        token_id=row.id,
        kind=row.kind,
        scopes=frozenset(row.scopes.split()),
        via=row.name if row.kind == "personal" else None,
    )


def logout(db: Session, actor: Actor) -> schemas.ActionResult:
    db.execute(delete(models.ApiToken).where(models.ApiToken.id == actor.token_id))
    db.commit()
    return schemas.ActionResult(message="로그아웃했습니다")


# Personal API tokens (for AI assistants)


def list_tokens(db: Session, actor: Actor) -> list[schemas.TokenOut]:
    actor.require_session()
    rows = db.scalars(
        select(models.ApiToken)
        .where(models.ApiToken.user_id == actor.user_id, models.ApiToken.kind == "personal")
        .order_by(models.ApiToken.id.desc())
    )
    return [_token_out(row) for row in rows]


def create_token(db: Session, actor: Actor, name: str, scopes: Sequence[str]) -> schemas.TokenCreated:
    actor.require_session()
    name = _clean(name, "토큰 이름", 50)
    unknown = set(scopes) - ALL_SCOPES
    if unknown:
        raise InvalidInput(f"알 수 없는 권한: {', '.join(sorted(unknown))}")
    raw, row = _issue_token(db, actor.user_id, kind="personal", name=name, scopes={"read", *scopes}, ttl=None)
    db.commit()
    return schemas.TokenCreated(token=raw, info=_token_out(row))


def revoke_token(db: Session, actor: Actor, token_id: int) -> schemas.ActionResult:
    actor.require_session()
    row = db.get(models.ApiToken, token_id)
    if row is None or row.user_id != actor.user_id or row.kind != "personal":
        raise NotFound("토큰을 찾을 수 없습니다")
    db.delete(row)
    db.commit()
    return schemas.ActionResult(message=f"토큰 '{row.name}'을(를) 폐기했습니다")


# Users and follows


def get_me(db: Session, actor: Actor) -> schemas.UserOut:
    actor.require("read")
    return _users_out(db, [db.get(User, actor.user_id)], actor.user_id)[0]


def get_unread_counts(db: Session, actor: Actor) -> schemas.UnreadCounts:
    actor.require("read")
    notifications = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == actor.user_id, Notification.read.is_(False))
    )
    messages = None
    if "dm" in actor.scopes:
        messages = db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.recipient_id == actor.user_id, Message.read_at.is_(None))
        )
    return schemas.UnreadCounts(notifications=notifications, messages=messages)


def update_profile(
    db: Session, actor: Actor, display_name: str | None = None, bio: str | None = None
) -> schemas.UserOut:
    actor.require("write")
    user = db.get(User, actor.user_id)
    if display_name is not None:
        user.display_name = _clean(display_name, "이름", 50)
    if bio is not None:
        bio = bio.strip()
        if len(bio) > 300:
            raise InvalidInput("소개는 300자 이하여야 합니다")
        user.bio = bio
    db.commit()
    return _users_out(db, [user], actor.user_id)[0]


def get_user(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("read")
    return _users_out(db, [_get_user(db, username)], actor.user_id)[0]


def search_users(db: Session, actor: Actor, query: str, limit: int | None = None) -> list[schemas.UserOut]:
    actor.require("read")
    query = _clean(query, "검색어", 100).lstrip("@")
    pattern = _like_pattern(query)
    users = db.scalars(
        select(User)
        .where(or_(User.username.ilike(pattern, escape="\\"), User.display_name.ilike(pattern, escape="\\")))
        .order_by(User.username)
        .limit(_limit(limit))
    ).all()
    return _users_out(db, users, actor.user_id)


def follow_user(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("write")
    target = _get_user(db, username)
    if target.id == actor.user_id:
        raise InvalidInput("자기 자신은 팔로우할 수 없습니다")
    exists = db.scalar(select(Follow.id).where(Follow.follower_id == actor.user_id, Follow.followee_id == target.id))
    if exists is None:
        db.add(Follow(follower_id=actor.user_id, followee_id=target.id))
        _notify(db, target.id, actor.user_id, "follow")
        db.commit()
    return _users_out(db, [target], actor.user_id)[0]


def unfollow_user(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("write")
    target = _get_user(db, username)
    db.execute(delete(Follow).where(Follow.follower_id == actor.user_id, Follow.followee_id == target.id))
    db.commit()
    return _users_out(db, [target], actor.user_id)[0]


def _follow_page(
    db: Session, actor: Actor, username: str, cursor, limit, *, followers: bool
) -> schemas.Page[schemas.UserOut]:
    actor.require("read")
    user = _get_user(db, username)
    limit = _limit(limit)
    match_col, other_col = (
        (Follow.followee_id, Follow.follower_id) if followers else (Follow.follower_id, Follow.followee_id)
    )
    stmt = select(Follow.id, User).join(User, User.id == other_col).where(match_col == user.id)
    if cursor is not None:
        stmt = stmt.where(Follow.id < cursor)
    rows = db.execute(stmt.order_by(Follow.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return schemas.Page[schemas.UserOut](
        items=_users_out(db, [row.User for row in page], actor.user_id),
        next_cursor=page[-1].id if len(rows) > limit else None,
    )


def list_followers(db: Session, actor: Actor, username: str, cursor: int | None = None, limit: int | None = None):
    return _follow_page(db, actor, username, cursor, limit, followers=True)


def list_following(db: Session, actor: Actor, username: str, cursor: int | None = None, limit: int | None = None):
    return _follow_page(db, actor, username, cursor, limit, followers=False)


# Posts


def create_post(db: Session, actor: Actor, content: str) -> schemas.PostOut:
    actor.require("write")
    content = _clean(content, "내용", POST_MAX)
    post = Post(
        author_id=actor.user_id,
        content=content,
        via=actor.via,
        tags=[PostTag(tag=tag, position=i) for i, tag in enumerate(extract_tags(content))],
    )
    db.add(post)
    db.flush()
    _notify_mentions(db, actor.user_id, extract_mentions(content), post_id=post.id)
    db.commit()
    return _posts_out(db, [post], actor.user_id)[0]


def get_post(db: Session, actor: Actor, post_id: int) -> schemas.PostOut:
    actor.require("read")
    return _posts_out(db, [_get_post(db, post_id)], actor.user_id)[0]


def edit_post(db: Session, actor: Actor, post_id: int, content: str) -> schemas.PostOut:
    actor.require("write")
    post = _get_post(db, post_id)
    if post.author_id != actor.user_id:
        raise Forbidden("본인 게시물만 수정할 수 있습니다")
    content = _clean(content, "내용", POST_MAX)
    new_mentions = [m for m in extract_mentions(content) if m not in extract_mentions(post.content)]
    post.content = content
    post.edited_at = utcnow()
    post.tags = [PostTag(tag=tag, position=i) for i, tag in enumerate(extract_tags(content))]
    db.flush()
    _notify_mentions(db, actor.user_id, new_mentions, post_id=post.id)
    db.commit()
    return _posts_out(db, [post], actor.user_id)[0]


def delete_post(db: Session, actor: Actor, post_id: int) -> schemas.ActionResult:
    actor.require("write")
    post = _get_post(db, post_id)
    if post.author_id != actor.user_id:
        raise Forbidden("본인 게시물만 삭제할 수 있습니다")
    db.delete(post)
    db.commit()
    return schemas.ActionResult(message=f"게시물 #{post_id}을(를) 삭제했습니다")


def home_feed(db: Session, actor: Actor, cursor: int | None = None, limit: int | None = None):
    actor.require("read")
    following = select(Follow.followee_id).where(Follow.follower_id == actor.user_id)
    stmt = select(Post).where(or_(Post.author_id == actor.user_id, Post.author_id.in_(following)))
    return _post_page(db, actor, stmt, cursor, limit)


def browse_posts(
    db: Session,
    actor: Actor,
    query: str | None = None,
    tag: str | None = None,
    cursor: int | None = None,
    limit: int | None = None,
):
    actor.require("read")
    stmt = select(Post)
    if query and query.strip():
        stmt = stmt.where(Post.content.ilike(_like_pattern(query.strip()), escape="\\"))
    if tag and tag.strip():
        normalized = tag.strip().lstrip("#").lower()
        stmt = stmt.where(Post.id.in_(select(PostTag.post_id).where(PostTag.tag == normalized)))
    return _post_page(db, actor, stmt, cursor, limit)


def user_posts(db: Session, actor: Actor, username: str, cursor: int | None = None, limit: int | None = None):
    actor.require("read")
    user = _get_user(db, username)
    return _post_page(db, actor, select(Post).where(Post.author_id == user.id), cursor, limit)


def like_post(db: Session, actor: Actor, post_id: int) -> schemas.PostOut:
    actor.require("write")
    post = _get_post(db, post_id)
    if db.get(Like, (actor.user_id, post.id)) is None:
        db.add(Like(user_id=actor.user_id, post_id=post.id))
        _notify(db, post.author_id, actor.user_id, "like", post_id=post.id)
        db.commit()
    return _posts_out(db, [post], actor.user_id)[0]


def unlike_post(db: Session, actor: Actor, post_id: int) -> schemas.PostOut:
    actor.require("write")
    post = _get_post(db, post_id)
    db.execute(delete(Like).where(Like.user_id == actor.user_id, Like.post_id == post.id))
    db.commit()
    return _posts_out(db, [post], actor.user_id)[0]


def trending_tags(db: Session, actor: Actor, days: int = 7, limit: int = 10) -> list[schemas.TagCount]:
    actor.require("read")
    if not 1 <= days <= 365:
        raise InvalidInput("days는 1~365 사이여야 합니다")
    since = utcnow() - timedelta(days=days)
    count = func.count().label("count")
    rows = db.execute(
        select(PostTag.tag, count)
        .join(Post, Post.id == PostTag.post_id)
        .where(Post.created_at >= since)
        .group_by(PostTag.tag)
        .order_by(count.desc(), PostTag.tag)
        .limit(_limit(limit))
    ).all()
    return [schemas.TagCount(tag=tag, count=n) for tag, n in rows]


# Comments


def list_comments(db: Session, actor: Actor, post_id: int, cursor: int | None = None, limit: int | None = None):
    """Oldest first; `cursor` continues after the last comment of the previous page."""
    actor.require("read")
    post = _get_post(db, post_id)
    limit = _limit(limit)
    stmt = select(Comment).where(Comment.post_id == post.id)
    if cursor is not None:
        stmt = stmt.where(Comment.id > cursor)
    rows = list(db.scalars(stmt.order_by(Comment.id).limit(limit + 1)))
    page = rows[:limit]
    return schemas.Page[schemas.CommentOut](
        items=[_comment_out(c) for c in page], next_cursor=page[-1].id if len(rows) > limit else None
    )


def add_comment(db: Session, actor: Actor, post_id: int, content: str) -> schemas.CommentOut:
    actor.require("write")
    post = _get_post(db, post_id)
    content = _clean(content, "댓글", COMMENT_MAX)
    comment = Comment(post_id=post.id, author_id=actor.user_id, content=content, via=actor.via)
    db.add(comment)
    db.flush()
    _notify(db, post.author_id, actor.user_id, "comment", post_id=post.id, comment_id=comment.id)
    mentions = [m for m in extract_mentions(content) if m != post.author.username.lower()]
    _notify_mentions(db, actor.user_id, mentions, post_id=post.id, comment_id=comment.id)
    db.commit()
    return _comment_out(comment)


def delete_comment(db: Session, actor: Actor, comment_id: int) -> schemas.ActionResult:
    actor.require("write")
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise NotFound(f"댓글 #{comment_id}을(를) 찾을 수 없습니다")
    post_author_id = db.scalar(select(Post.author_id).where(Post.id == comment.post_id))
    if actor.user_id not in (comment.author_id, post_author_id):
        raise Forbidden("본인 댓글이나 본인 게시물의 댓글만 삭제할 수 있습니다")
    db.delete(comment)
    db.commit()
    return schemas.ActionResult(message=f"댓글 #{comment_id}을(를) 삭제했습니다")


# Notifications


def list_notifications(
    db: Session, actor: Actor, unread_only: bool = False, cursor: int | None = None, limit: int | None = None
) -> schemas.NotificationPage:
    actor.require("read")
    limit = _limit(limit)
    stmt = select(Notification).where(Notification.user_id == actor.user_id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    if cursor is not None:
        stmt = stmt.where(Notification.id < cursor)
    rows = list(db.scalars(stmt.order_by(Notification.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    return schemas.NotificationPage(
        items=[_notification_out(n) for n in page],
        next_cursor=page[-1].id if len(rows) > limit else None,
        unread_count=get_unread_counts(db, actor).notifications,
    )


def mark_notifications_read(db: Session, actor: Actor, ids: Sequence[int] | None = None) -> schemas.ActionResult:
    actor.require("write")
    stmt = update(Notification).where(Notification.user_id == actor.user_id, Notification.read.is_(False))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = db.execute(stmt.values(read=True))
    db.commit()
    return schemas.ActionResult(message=f"알림 {result.rowcount}개를 읽음으로 표시했습니다")


# Direct messages


def send_message(db: Session, actor: Actor, username: str, content: str) -> schemas.MessageOut:
    actor.require("dm")
    target = _get_user(db, username)
    if target.id == actor.user_id:
        raise InvalidInput("자기 자신에게는 메시지를 보낼 수 없습니다")
    message = Message(
        sender_id=actor.user_id,
        recipient_id=target.id,
        content=_clean(content, "메시지", MESSAGE_MAX),
        via=actor.via,
    )
    db.add(message)
    db.commit()
    return _message_out(message)


def list_conversations(db: Session, actor: Actor) -> list[schemas.ConversationOut]:
    actor.require("dm")
    me = actor.user_id
    partner = case((Message.sender_id == me, Message.recipient_id), else_=Message.sender_id).label("partner")
    latest = (
        select(partner, func.max(Message.id).label("last_id"))
        .where(or_(Message.sender_id == me, Message.recipient_id == me))
        .group_by(partner)
        .subquery()
    )
    messages = db.scalars(
        select(Message).join(latest, Message.id == latest.c.last_id).order_by(Message.id.desc()).limit(MAX_LIMIT)
    ).all()
    unread = dict(
        db.execute(
            select(Message.sender_id, func.count())
            .where(Message.recipient_id == me, Message.read_at.is_(None))
            .group_by(Message.sender_id)
        ).all()
    )
    conversations = []
    for m in messages:
        other = m.recipient if m.sender_id == me else m.sender
        conversations.append(
            schemas.ConversationOut(
                user=_brief(other), last_message=_message_out(m), unread_count=unread.get(other.id, 0)
            )
        )
    return conversations


def read_conversation(
    db: Session, actor: Actor, username: str, cursor: int | None = None, limit: int | None = None
) -> schemas.Page[schemas.MessageOut]:
    """Newest first. Marks the other user's messages in this conversation as read."""
    actor.require("dm")
    other = _get_user(db, username)
    me = actor.user_id
    limit = _limit(limit)
    stmt = select(Message).where(
        or_(
            and_(Message.sender_id == me, Message.recipient_id == other.id),
            and_(Message.sender_id == other.id, Message.recipient_id == me),
        )
    )
    if cursor is not None:
        stmt = stmt.where(Message.id < cursor)
    rows = list(db.scalars(stmt.order_by(Message.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    # The ORM-enabled UPDATE also refreshes `read_at` on the messages already loaded into `page`.
    db.execute(
        update(Message)
        .where(Message.sender_id == other.id, Message.recipient_id == me, Message.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return schemas.Page[schemas.MessageOut](
        items=[_message_out(m) for m in page], next_cursor=page[-1].id if len(rows) > limit else None
    )
