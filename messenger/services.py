"""Business logic. The REST API, the MCP server and the realtime events are thin adapters over these
functions, so every capability (and every permission check) is identical on every surface."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from . import schemas, security
from .events import emit
from .models import (
    ApiToken,
    Contact,
    Conversation,
    ConversationMember,
    Message,
    TokenConversation,
    User,
    utcnow,
)

ALL_SCOPES = frozenset({"read", "write"})
SESSION_TTL = timedelta(days=30)
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
MESSAGE_MAX = 2000

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,30}")

_DUMMY_PASSWORD_HASH = security.hash_password("timing-equalizer")
_CONVERSATION_NOT_FOUND = "대화방을 찾을 수 없습니다"
_RESTRICTED_TOKEN = "이 토큰은 선택한 대화방에서만 사용할 수 있습니다"


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
    via: str | None  # label stored on messages sent through a personal token
    conversation_ids: frozenset[int] | None  # None: every conversation the user belongs to

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise Forbidden(f"이 토큰에는 '{scope}' 권한이 없습니다")

    def require_session(self) -> None:
        if self.kind != "session":
            raise Forbidden("토큰 관리는 웹 로그인 세션에서만 할 수 있습니다")

    def require_unrestricted(self) -> None:
        if self.conversation_ids is not None:
            raise Forbidden(_RESTRICTED_TOKEN)

    def can_access(self, conversation_id: int) -> bool:
        return self.conversation_ids is None or conversation_id in self.conversation_ids


# Helpers


def _clean(text: str | None, label: str, max_len: int) -> str:
    value = (text or "").strip()
    if not value:
        raise InvalidInput(f"{label}을(를) 입력하세요")
    if len(value) > max_len:
        raise InvalidInput(f"{label}은(는) {max_len}자 이하여야 합니다")
    return value


def _limit(limit: int | None, default: int = DEFAULT_LIMIT) -> int:
    if limit is None:
        return default
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit은 1~{MAX_LIMIT} 사이여야 합니다")
    return limit


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _brief(user: User) -> schemas.UserBrief:
    return schemas.UserBrief(id=user.id, username=user.username, display_name=user.display_name)


def _find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.strip().lstrip("@").lower()))


def _get_user(db: Session, username: str) -> User:
    user = _find_user(db, username)
    if user is None:
        raise NotFound(f"사용자 @{username.strip().lstrip('@')}을(를) 찾을 수 없습니다")
    return user


def _get_others(db: Session, actor: Actor, usernames: Sequence[str]) -> list[User]:
    users: dict[int, User] = {}
    for name in usernames:
        user = _get_user(db, name)
        if user.id != actor.user_id:
            users.setdefault(user.id, user)
    return list(users.values())


def _users_out(db: Session, users: Sequence[User], viewer_id: int) -> list[schemas.UserOut]:
    ids = [u.id for u in users]
    contacts = set(
        db.scalars(select(Contact.contact_id).where(Contact.owner_id == viewer_id, Contact.contact_id.in_(ids)))
    )
    return [
        schemas.UserOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            status_message=u.status_message,
            is_me=u.id == viewer_id,
            is_contact=u.id in contacts,
        )
        for u in users
    ]


def _membership(db: Session, actor: Actor, conversation_id: int) -> tuple[Conversation, ConversationMember]:
    member = db.get(ConversationMember, (conversation_id, actor.user_id))
    if member is None or not actor.can_access(conversation_id):
        raise NotFound(_CONVERSATION_NOT_FOUND)
    return db.get(Conversation, conversation_id), member


def _member_ids(conversation: Conversation) -> list[int]:
    return [m.user_id for m in conversation.members]


def _unread_counter(conversation: Conversation) -> Callable[[Message], int]:
    """Counts members other than the sender who can see a message but have not read it."""
    members = [(m.user_id, m.visible_after_message_id, m.last_read_message_id) for m in conversation.members]

    def count(message: Message) -> int:
        if message.kind != "text" or message.deleted_at is not None:
            return 0
        return sum(
            1
            for user_id, visible_after, last_read in members
            if user_id != message.sender_id and visible_after < message.id and last_read < message.id
        )

    return count


def _message_out(message: Message, unread: int, *, show_reply: bool = True) -> schemas.MessageOut:
    reply = None
    original = message.reply_to
    if original is not None and show_reply:
        reply = schemas.ReplyPreview(
            id=original.id,
            sender=_brief(original.sender) if original.sender else None,
            content="" if original.deleted_at else original.content[:200],
            deleted=original.deleted_at is not None,
        )
    deleted = message.deleted_at is not None
    return schemas.MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        kind=message.kind,
        sender=_brief(message.sender) if message.sender else None,
        content="" if deleted else message.content,
        via=message.via,
        reply_to=reply,
        created_at=message.created_at,
        edited_at=message.edited_at,
        deleted=deleted,
        unread_count=unread,
    )


def _messages_out(
    conversation: Conversation, messages: Sequence[Message], visible_after: int
) -> list[schemas.MessageOut]:
    count = _unread_counter(conversation)
    return [_message_out(m, count(m), show_reply=(m.reply_to_id or 0) > visible_after) for m in messages]


def _unread_counts(db: Session, user_id: int, conversation_ids: Sequence[int]) -> dict[int, int]:
    if not conversation_ids:
        return {}
    member = ConversationMember
    rows = db.execute(
        select(Message.conversation_id, func.count())
        .join(member, and_(member.conversation_id == Message.conversation_id, member.user_id == user_id))
        .where(
            Message.conversation_id.in_(conversation_ids),
            Message.id > member.last_read_message_id,
            Message.id > member.visible_after_message_id,
            Message.kind == "text",
            Message.deleted_at.is_(None),
            Message.sender_id != user_id,
        )
        .group_by(Message.conversation_id)
    ).all()
    return {conversation_id: count for conversation_id, count in rows}


def _title(conversation: Conversation, viewer_id: int) -> str:
    if conversation.title:
        return conversation.title
    others = [m.user.display_name for m in conversation.members if m.user_id != viewer_id]
    if conversation.kind == "direct":
        return others[0] if others else "알 수 없는 사용자"
    if not others:
        return "빈 그룹"
    return ", ".join(others[:4]) + (f" 외 {len(others) - 4}명" if len(others) > 4 else "")


def _conversations_out(
    db: Session, conversations: Sequence[Conversation], viewer_id: int
) -> list[schemas.ConversationOut]:
    last_ids = [c.last_message_id for c in conversations if c.last_message_id]
    last_messages = {m.id: m for m in db.scalars(select(Message).where(Message.id.in_(last_ids))).unique()}
    unread = _unread_counts(db, viewer_id, [c.id for c in conversations])
    result = []
    for c in conversations:
        me = next(m for m in c.members if m.user_id == viewer_id)
        last = last_messages.get(c.last_message_id)
        visible_last = last if last is not None and last.id > me.visible_after_message_id else None
        result.append(
            schemas.ConversationOut(
                id=c.id,
                kind=c.kind,
                title=_title(c, viewer_id),
                members=[
                    schemas.MemberOut(
                        id=m.user.id,
                        username=m.user.username,
                        display_name=m.user.display_name,
                        last_read_message_id=m.last_read_message_id,
                    )
                    for m in c.members
                ],
                last_message=_messages_out(c, [visible_last], me.visible_after_message_id)[0] if visible_last else None,
                unread_count=unread.get(c.id, 0),
                created_at=c.created_at,
            )
        )
    return result


def _emit_conversation(db: Session, user_ids: Sequence[int], conversation_id: int) -> None:
    emit(db, user_ids, {"type": "conversation", "conversation_id": conversation_id})


def _emit_message(db: Session, conversation: Conversation, message: Message, event_type: str = "message") -> None:
    """Sends a message event to every member who can see the message; members who joined after the
    replied-to message get the event without the reply preview."""
    unread = _unread_counter(conversation)(message)
    audiences: dict[bool, list[int]] = {}
    for member in conversation.members:
        if member.visible_after_message_id < message.id:
            show_reply = (message.reply_to_id or 0) > member.visible_after_message_id
            audiences.setdefault(show_reply, []).append(member.user_id)
    for show_reply, user_ids in audiences.items():
        payload = _message_out(message, unread, show_reply=show_reply).model_dump(mode="json")
        emit(db, user_ids, {"type": event_type, "conversation_id": conversation.id, "message": payload})


def _emit_read(db: Session, conversation: Conversation, member: ConversationMember) -> None:
    emit(
        db,
        _member_ids(conversation),
        {
            "type": "read",
            "conversation_id": conversation.id,
            "user_id": member.user_id,
            "last_read_message_id": member.last_read_message_id,
        },
    )


def _system_message(db: Session, conversation: Conversation, text: str) -> None:
    message = Message(conversation_id=conversation.id, kind="system", content=text)
    db.add(message)
    db.flush()
    conversation.last_message_id = message.id
    _emit_message(db, conversation, message)


def _post_message(
    db: Session,
    actor: Actor,
    conversation: Conversation,
    me: ConversationMember,
    content: str,
    reply_to_id: int | None,
) -> schemas.MessageOut:
    content = _clean(content, "메시지", MESSAGE_MAX)
    if reply_to_id is not None:
        target = db.get(Message, reply_to_id)
        if (
            target is None
            or target.conversation_id != conversation.id
            or target.id <= me.visible_after_message_id
            or target.kind != "text"
        ):
            raise NotFound("답장할 메시지를 찾을 수 없습니다")
    message = Message(
        conversation_id=conversation.id,
        sender_id=actor.user_id,
        content=content,
        via=actor.via,
        reply_to_id=reply_to_id,
    )
    db.add(message)
    db.flush()
    conversation.last_message_id = message.id
    # Replying shows you have seen the conversation, as in other messengers.
    me.last_read_message_id = message.id
    _emit_message(db, conversation, message)
    _emit_read(db, conversation, me)
    db.commit()
    return _message_out(message, _unread_counter(conversation)(message))


def _get_or_create_direct(db: Session, actor: Actor, other: User) -> tuple[Conversation, bool]:
    if other.id == actor.user_id:
        raise InvalidInput("자기 자신과는 대화할 수 없습니다")
    low, high = sorted((actor.user_id, other.id))
    key = f"{low}:{high}"
    conversation = db.scalar(select(Conversation).where(Conversation.direct_key == key))
    if conversation is not None:
        if not actor.can_access(conversation.id):
            raise Forbidden(_RESTRICTED_TOKEN)
        return conversation, False
    actor.require_unrestricted()
    conversation = Conversation(
        kind="direct",
        direct_key=key,
        members=[ConversationMember(user_id=actor.user_id), ConversationMember(user_id=other.id)],
    )
    db.add(conversation)
    db.flush()
    _emit_conversation(db, [actor.user_id, other.id], conversation.id)
    return conversation, True


def _issue_token(
    db: Session, user_id: int, *, kind: str, name: str, scopes, ttl: timedelta | None
) -> tuple[str, ApiToken]:
    raw = security.new_token()
    row = ApiToken(
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


def _token_out(row: ApiToken) -> schemas.TokenOut:
    return schemas.TokenOut(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=row.scopes.split(),
        conversation_ids=None if row.all_conversations else sorted(c.conversation_id for c in row.conversations),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
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
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == security.hash_token(raw_token)))
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
        conversation_ids=None if row.all_conversations else frozenset(c.conversation_id for c in row.conversations),
    )


def logout(db: Session, actor: Actor) -> schemas.ActionResult:
    db.execute(delete(ApiToken).where(ApiToken.id == actor.token_id))
    db.commit()
    return schemas.ActionResult(message="로그아웃했습니다")


# Personal API tokens (for AI assistants)


def list_tokens(db: Session, actor: Actor) -> list[schemas.TokenOut]:
    actor.require_session()
    rows = db.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == actor.user_id, ApiToken.kind == "personal")
        .order_by(ApiToken.id.desc())
    )
    return [_token_out(row) for row in rows]


def create_token(
    db: Session, actor: Actor, name: str, scopes: Sequence[str], conversation_ids: Sequence[int] | None = None
) -> schemas.TokenCreated:
    actor.require_session()
    name = _clean(name, "토큰 이름", 50)
    unknown = set(scopes) - ALL_SCOPES
    if unknown:
        raise InvalidInput(f"알 수 없는 권한: {', '.join(sorted(unknown))}")
    allowed: set[int] | None = None
    if conversation_ids is not None:
        allowed = set(conversation_ids)
        if not allowed:
            raise InvalidInput("대화방을 하나 이상 선택하세요")
        mine = set(
            db.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == actor.user_id, ConversationMember.conversation_id.in_(allowed)
                )
            )
        )
        if allowed - mine:
            raise NotFound(_CONVERSATION_NOT_FOUND)
    raw, row = _issue_token(db, actor.user_id, kind="personal", name=name, scopes={"read", *scopes}, ttl=None)
    if allowed is not None:
        row.all_conversations = False
        row.conversations = [TokenConversation(conversation_id=i) for i in sorted(allowed)]
    db.commit()
    return schemas.TokenCreated(token=raw, info=_token_out(row))


def revoke_token(db: Session, actor: Actor, token_id: int) -> schemas.ActionResult:
    actor.require_session()
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != actor.user_id or row.kind != "personal":
        raise NotFound("토큰을 찾을 수 없습니다")
    db.delete(row)
    db.commit()
    return schemas.ActionResult(message=f"토큰 '{row.name}'을(를) 폐기했습니다")


# Profile, users and contacts


def get_me(db: Session, actor: Actor) -> schemas.UserOut:
    actor.require("read")
    return _users_out(db, [db.get(User, actor.user_id)], actor.user_id)[0]


def update_profile(
    db: Session, actor: Actor, display_name: str | None = None, status_message: str | None = None
) -> schemas.UserOut:
    actor.require("write")
    user = db.get(User, actor.user_id)
    if display_name is not None:
        user.display_name = _clean(display_name, "이름", 50)
    if status_message is not None:
        status_message = status_message.strip()
        if len(status_message) > 100:
            raise InvalidInput("상태 메시지는 100자 이하여야 합니다")
        user.status_message = status_message
    db.commit()
    return _users_out(db, [user], actor.user_id)[0]


def get_user(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("read")
    return _users_out(db, [_get_user(db, username)], actor.user_id)[0]


def search_users(db: Session, actor: Actor, query: str, limit: int | None = None) -> list[schemas.UserOut]:
    actor.require("read")
    pattern = _like_pattern(_clean(query, "검색어", 100).lstrip("@"))
    users = db.scalars(
        select(User)
        .where(or_(User.username.ilike(pattern, escape="\\"), User.display_name.ilike(pattern, escape="\\")))
        .order_by(User.username)
        .limit(_limit(limit, 20))
    ).all()
    return _users_out(db, users, actor.user_id)


def list_contacts(db: Session, actor: Actor) -> list[schemas.UserOut]:
    actor.require("read")
    users = db.scalars(
        select(User)
        .join(Contact, Contact.contact_id == User.id)
        .where(Contact.owner_id == actor.user_id)
        .order_by(User.display_name, User.username)
    ).all()
    return _users_out(db, users, actor.user_id)


def add_contact(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("write")
    user = _get_user(db, username)
    if user.id == actor.user_id:
        raise InvalidInput("자기 자신은 친구로 추가할 수 없습니다")
    if db.get(Contact, (actor.user_id, user.id)) is None:
        db.add(Contact(owner_id=actor.user_id, contact_id=user.id))
        db.commit()
    return _users_out(db, [user], actor.user_id)[0]


def remove_contact(db: Session, actor: Actor, username: str) -> schemas.UserOut:
    actor.require("write")
    user = _get_user(db, username)
    db.execute(delete(Contact).where(Contact.owner_id == actor.user_id, Contact.contact_id == user.id))
    db.commit()
    return _users_out(db, [user], actor.user_id)[0]


# Conversations


def list_conversations(db: Session, actor: Actor, limit: int | None = None) -> list[schemas.ConversationOut]:
    """Most recently active first."""
    actor.require("read")
    stmt = select(Conversation).join(
        ConversationMember,
        and_(ConversationMember.conversation_id == Conversation.id, ConversationMember.user_id == actor.user_id),
    )
    if actor.conversation_ids is not None:
        stmt = stmt.where(Conversation.id.in_(actor.conversation_ids))
    conversations = db.scalars(
        stmt.order_by(func.coalesce(Conversation.last_message_id, 0).desc(), Conversation.id.desc()).limit(
            _limit(limit, 50)
        )
    ).all()
    return _conversations_out(db, conversations, actor.user_id)


def get_conversation(db: Session, actor: Actor, conversation_id: int) -> schemas.ConversationOut:
    actor.require("read")
    conversation, _ = _membership(db, actor, conversation_id)
    return _conversations_out(db, [conversation], actor.user_id)[0]


def open_direct_conversation(db: Session, actor: Actor, username: str) -> schemas.ConversationOut:
    actor.require("write")
    conversation, created = _get_or_create_direct(db, actor, _get_user(db, username))
    if created:
        db.commit()
    return _conversations_out(db, [conversation], actor.user_id)[0]


def create_group(db: Session, actor: Actor, title: str | None, usernames: Sequence[str]) -> schemas.ConversationOut:
    actor.require("write")
    actor.require_unrestricted()
    others = _get_others(db, actor, usernames)
    if not others:
        raise InvalidInput("초대할 사람을 한 명 이상 지정하세요")
    title = (title or "").strip()
    if len(title) > 100:
        raise InvalidInput("그룹 이름은 100자 이하여야 합니다")
    conversation = Conversation(
        kind="group",
        title=title or None,
        members=[ConversationMember(user_id=actor.user_id), *(ConversationMember(user_id=u.id) for u in others)],
    )
    db.add(conversation)
    db.flush()
    me = db.get(User, actor.user_id)
    names = ", ".join(u.display_name for u in others)
    _system_message(db, conversation, f"{me.display_name}님이 {names}님과 그룹을 만들었습니다")
    _emit_conversation(db, _member_ids(conversation), conversation.id)
    db.commit()
    return _conversations_out(db, [conversation], actor.user_id)[0]


def _get_group(db: Session, actor: Actor, conversation_id: int) -> tuple[Conversation, ConversationMember]:
    conversation, me = _membership(db, actor, conversation_id)
    if conversation.kind != "group":
        raise InvalidInput("1:1 대화방에서는 할 수 없는 작업입니다")
    return conversation, me


def rename_group(db: Session, actor: Actor, conversation_id: int, title: str) -> schemas.ConversationOut:
    actor.require("write")
    conversation, _ = _get_group(db, actor, conversation_id)
    conversation.title = _clean(title, "그룹 이름", 100)
    me = db.get(User, actor.user_id)
    _system_message(db, conversation, f"{me.display_name}님이 그룹 이름을 '{conversation.title}'(으)로 바꿨습니다")
    _emit_conversation(db, _member_ids(conversation), conversation.id)
    db.commit()
    return _conversations_out(db, [conversation], actor.user_id)[0]


def add_members(db: Session, actor: Actor, conversation_id: int, usernames: Sequence[str]) -> schemas.ConversationOut:
    actor.require("write")
    conversation, _ = _get_group(db, actor, conversation_id)
    current = set(_member_ids(conversation))
    invited = [u for u in _get_others(db, actor, usernames) if u.id not in current]
    if not invited:
        raise InvalidInput("초대할 새 사람이 없습니다")
    boundary = conversation.last_message_id or 0
    for user in invited:
        conversation.members.append(
            ConversationMember(user_id=user.id, visible_after_message_id=boundary, last_read_message_id=boundary)
        )
    db.flush()
    me = db.get(User, actor.user_id)
    names = ", ".join(u.display_name for u in invited)
    _system_message(db, conversation, f"{me.display_name}님이 {names}님을 초대했습니다")
    _emit_conversation(db, _member_ids(conversation), conversation.id)
    db.commit()
    return _conversations_out(db, [conversation], actor.user_id)[0]


def leave_conversation(db: Session, actor: Actor, conversation_id: int) -> schemas.ActionResult:
    actor.require("write")
    conversation, me = _get_group(db, actor, conversation_id)
    conversation.members.remove(me)
    db.flush()
    user = db.get(User, actor.user_id)
    _system_message(db, conversation, f"{user.display_name}님이 나갔습니다")
    _emit_conversation(db, [actor.user_id, *_member_ids(conversation)], conversation.id)
    db.commit()
    return schemas.ActionResult(message="대화방에서 나왔습니다")


# Messages


def read_messages(
    db: Session, actor: Actor, conversation_id: int, before: int | None = None, limit: int | None = None
) -> schemas.Page[schemas.MessageOut]:
    """A page of messages, oldest first; `next_cursor` fetches the page before it. Does not mark anything read."""
    actor.require("read")
    conversation, me = _membership(db, actor, conversation_id)
    limit = _limit(limit)
    stmt = select(Message).where(Message.conversation_id == conversation.id, Message.id > me.visible_after_message_id)
    if before is not None:
        stmt = stmt.where(Message.id < before)
    rows = list(db.scalars(stmt.order_by(Message.id.desc()).limit(limit + 1)).unique())
    page = rows[:limit]
    next_cursor = page[-1].id if len(rows) > limit else None
    page.reverse()
    return schemas.Page[schemas.MessageOut](
        items=_messages_out(conversation, page, me.visible_after_message_id), next_cursor=next_cursor
    )


def send_message(
    db: Session, actor: Actor, conversation_id: int, content: str, reply_to_id: int | None = None
) -> schemas.MessageOut:
    actor.require("write")
    conversation, me = _membership(db, actor, conversation_id)
    return _post_message(db, actor, conversation, me, content, reply_to_id)


def send_direct_message(db: Session, actor: Actor, username: str, content: str) -> schemas.MessageOut:
    """Sends to the 1:1 conversation with `username`, creating it if needed."""
    actor.require("write")
    conversation, _ = _get_or_create_direct(db, actor, _get_user(db, username))
    me = next(m for m in conversation.members if m.user_id == actor.user_id)
    return _post_message(db, actor, conversation, me, content, None)


def _own_message(db: Session, actor: Actor, message_id: int) -> tuple[Conversation, Message]:
    message = db.get(Message, message_id)
    if message is None:
        raise NotFound(f"메시지 #{message_id}을(를) 찾을 수 없습니다")
    conversation, me = _membership(db, actor, message.conversation_id)
    if message.id <= me.visible_after_message_id:
        raise NotFound(f"메시지 #{message_id}을(를) 찾을 수 없습니다")
    if message.sender_id != actor.user_id or message.kind != "text":
        raise Forbidden("본인이 보낸 메시지만 수정하거나 삭제할 수 있습니다")
    if message.deleted_at is not None:
        raise InvalidInput("이미 삭제된 메시지입니다")
    return conversation, message


def edit_message(db: Session, actor: Actor, message_id: int, content: str) -> schemas.MessageOut:
    actor.require("write")
    conversation, message = _own_message(db, actor, message_id)
    message.content = _clean(content, "메시지", MESSAGE_MAX)
    message.edited_at = utcnow()
    _emit_message(db, conversation, message, "message_updated")
    db.commit()
    return _message_out(message, _unread_counter(conversation)(message))


def delete_message(db: Session, actor: Actor, message_id: int) -> schemas.MessageOut:
    """Deletes for everyone; the message stays in the history as 'deleted' with its text removed."""
    actor.require("write")
    conversation, message = _own_message(db, actor, message_id)
    message.content = ""
    message.deleted_at = utcnow()
    _emit_message(db, conversation, message, "message_updated")
    db.commit()
    return _message_out(message, 0)


def mark_read(
    db: Session, actor: Actor, conversation_id: int, message_id: int | None = None
) -> schemas.ConversationOut:
    """Marks messages up to `message_id` (default: the latest) as read. Other members see the read receipt."""
    actor.require("write")
    conversation, me = _membership(db, actor, conversation_id)
    latest = conversation.last_message_id or 0
    target = latest if message_id is None else min(message_id, latest)
    if target > me.last_read_message_id:
        me.last_read_message_id = target
        _emit_read(db, conversation, me)
        db.commit()
    return _conversations_out(db, [conversation], actor.user_id)[0]


def list_unread(db: Session, actor: Actor, limit_per_conversation: int | None = None) -> list[schemas.UnreadThread]:
    """Conversations with unread messages and their most recent unread messages. Does not mark anything read."""
    actor.require("read")
    per_conversation = _limit(limit_per_conversation, 20)
    threads = []
    for summary in list_conversations(db, actor, MAX_LIMIT):
        if summary.unread_count == 0:
            continue
        conversation, me = _membership(db, actor, summary.id)
        start = max(me.last_read_message_id, me.visible_after_message_id)
        rows = list(
            db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.id > start,
                    Message.deleted_at.is_(None),
                    Message.sender_id.is_distinct_from(actor.user_id),
                )
                .order_by(Message.id.desc())
                .limit(per_conversation)
            ).unique()
        )
        rows.reverse()
        threads.append(
            schemas.UnreadThread(
                conversation=summary, messages=_messages_out(conversation, rows, me.visible_after_message_id)
            )
        )
    return threads


def search_messages(
    db: Session, actor: Actor, query: str, conversation_id: int | None = None, limit: int | None = None
) -> list[schemas.MessageOut]:
    """Text search across the conversations the token can access, newest first."""
    actor.require("read")
    pattern = _like_pattern(_clean(query, "검색어", 100))
    member = ConversationMember
    stmt = (
        select(Message)
        .join(member, and_(member.conversation_id == Message.conversation_id, member.user_id == actor.user_id))
        .where(
            Message.kind == "text",
            Message.deleted_at.is_(None),
            Message.id > member.visible_after_message_id,
            Message.content.ilike(pattern, escape="\\"),
        )
    )
    if conversation_id is not None:
        _membership(db, actor, conversation_id)
        stmt = stmt.where(Message.conversation_id == conversation_id)
    if actor.conversation_ids is not None:
        stmt = stmt.where(Message.conversation_id.in_(actor.conversation_ids))
    rows = db.scalars(stmt.order_by(Message.id.desc()).limit(_limit(limit, 20))).unique().all()
    results = []
    for message in rows:
        conversation, me = _membership(db, actor, message.conversation_id)
        results.extend(_messages_out(conversation, [message], me.visible_after_message_id))
    return results
