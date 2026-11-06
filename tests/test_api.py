from __future__ import annotations

from conftest import auth


def direct(client, headers, username: str) -> int:
    return client.post("/api/conversations/direct", json={"username": username}, headers=headers).json()["id"]


def send(client, headers, conversation_id: int, content: str, **extra) -> dict:
    response = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content, **extra}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_register_login_logout(client, register):
    headers = register("alice", "앨리스")
    me = client.get("/api/me", headers=headers).json()
    assert (me["username"], me["display_name"]) == ("alice", "앨리스")

    assert client.post("/api/auth/register", json={"username": "ALICE", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401

    login = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    session = auth(login.json()["token"])
    assert client.post("/api/auth/logout", headers=session).status_code == 200
    assert client.get("/api/me", headers=session).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_direct_conversation_is_unique_per_pair(client, register):
    alice = register("alice")
    bob = register("bob")
    first = direct(client, alice, "bob")
    assert direct(client, bob, "@alice") == first
    assert client.post("/api/conversations/direct", json={"username": "alice"}, headers=alice).status_code == 422

    titles = {c["id"]: c["title"] for c in client.get("/api/conversations", headers=alice).json()}
    assert titles == {first: "bob"}


def test_messages_unread_counts_and_read_receipts(client, register):
    alice = register("alice")
    bob = register("bob")
    conversation_id = direct(client, alice, "bob")
    first = send(client, alice, conversation_id, "안녕")
    send(client, alice, conversation_id, "잘 지내?")
    assert first["unread_count"] == 1

    summary = client.get(f"/api/conversations/{conversation_id}", headers=bob).json()
    assert summary["unread_count"] == 2
    assert summary["last_message"]["content"] == "잘 지내?"

    # Reading does not mark anything read; only mark_read (or replying) does.
    page = client.get(f"/api/conversations/{conversation_id}/messages", headers=bob).json()
    assert [m["content"] for m in page["items"]] == ["안녕", "잘 지내?"]
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).json()["unread_count"] == 2

    client.post(f"/api/conversations/{conversation_id}/read", json={"message_id": first["id"]}, headers=bob)
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).json()["unread_count"] == 1
    unread_by = [
        m["unread_count"]
        for m in client.get(f"/api/conversations/{conversation_id}/messages", headers=alice).json()["items"]
    ]
    assert unread_by == [0, 1]

    reply = send(client, bob, conversation_id, "응", reply_to_id=first["id"])
    assert reply["reply_to"]["content"] == "안녕"
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).json()["unread_count"] == 0


def test_unread_overview_and_search(client, register):
    alice = register("alice")
    bob = register("bob")
    conversation_id = direct(client, alice, "bob")
    send(client, alice, conversation_id, "내일 회의 10시")
    send(client, alice, conversation_id, "자료는 메일로 보냈어")

    threads = client.get("/api/messages/unread", headers=bob).json()
    assert len(threads) == 1
    assert [m["content"] for m in threads[0]["messages"]] == ["내일 회의 10시", "자료는 메일로 보냈어"]
    assert client.get("/api/messages/unread", headers=alice).json() == []

    hits = client.get("/api/messages/search", params={"q": "회의"}, headers=bob).json()
    assert [m["content"] for m in hits] == ["내일 회의 10시"]
    carol = register("carol")
    assert client.get("/api/messages/search", params={"q": "회의"}, headers=carol).json() == []


def test_edit_and_delete_own_messages_only(client, register):
    alice = register("alice")
    bob = register("bob")
    conversation_id = direct(client, alice, "bob")
    message = send(client, alice, conversation_id, "오타 있음")

    assert client.patch(f"/api/messages/{message['id']}", json={"content": "x"}, headers=bob).status_code == 403
    edited = client.patch(f"/api/messages/{message['id']}", json={"content": "오타 없음"}, headers=alice).json()
    assert edited["content"] == "오타 없음" and edited["edited_at"] is not None

    assert client.delete(f"/api/messages/{message['id']}", headers=bob).status_code == 403
    deleted = client.delete(f"/api/messages/{message['id']}", headers=alice).json()
    assert deleted["deleted"] and deleted["content"] == ""
    seen_by_bob = client.get(f"/api/conversations/{conversation_id}/messages", headers=bob).json()["items"]
    assert seen_by_bob[0]["deleted"] and seen_by_bob[0]["content"] == ""
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).json()["unread_count"] == 0


def test_groups_invites_hide_earlier_history(client, register):
    alice = register("alice", "앨리스")
    bob = register("bob", "밥")
    carol = register("carol", "캐럴")
    group = client.post("/api/conversations/group", json={"title": "주말", "usernames": ["bob"]}, headers=alice).json()
    assert group["title"] == "주말"
    assert [m["username"] for m in group["members"]] == ["alice", "bob"]
    secret = send(client, alice, group["id"], "캐럴 생일 선물 뭐 살까")

    client.post(f"/api/conversations/{group['id']}/members", json={"usernames": ["carol"]}, headers=bob)
    carol_view = client.get(f"/api/conversations/{group['id']}/messages", headers=carol).json()["items"]
    assert [m["content"] for m in carol_view] == ["밥님이 캐럴님을 초대했습니다"]
    assert client.get("/api/messages/search", params={"q": "선물"}, headers=carol).json() == []
    reply = send(client, alice, group["id"], "케이크로 하자", reply_to_id=secret["id"])
    assert reply["reply_to"] is not None
    latest = client.get(f"/api/conversations/{group['id']}/messages", headers=carol).json()["items"][-1]
    assert latest["content"] == "케이크로 하자" and latest["reply_to"] is None

    renamed = client.patch(f"/api/conversations/{group['id']}", json={"title": "주말 계획"}, headers=carol).json()
    assert renamed["title"] == "주말 계획"
    assert client.delete(f"/api/conversations/{group['id']}/members/me", headers=carol).status_code == 200
    assert client.get(f"/api/conversations/{group['id']}", headers=carol).status_code == 404
    last = client.get(f"/api/conversations/{group['id']}", headers=alice).json()["last_message"]
    assert last["content"] == "캐럴님이 나갔습니다"

    dm = direct(client, alice, "bob")
    assert client.delete(f"/api/conversations/{dm}/members/me", headers=alice).status_code == 422


def test_contacts(client, register):
    alice = register("alice")
    register("bob", "밥")
    assert client.put("/api/contacts/alice", headers=alice).status_code == 422
    assert client.put("/api/contacts/bob", headers=alice).json()["is_contact"] is True
    assert [u["username"] for u in client.get("/api/contacts", headers=alice).json()] == ["bob"]
    assert client.get("/api/users", params={"q": "밥"}, headers=alice).json()[0]["is_contact"] is True
    client.delete("/api/contacts/bob", headers=alice)
    assert client.get("/api/contacts", headers=alice).json() == []


def test_personal_tokens_scopes_and_via_label(client, register, personal_token):
    alice = register("alice")
    register("bob")
    conversation_id = direct(client, alice, "bob")

    read_only = auth(personal_token(alice, scopes=["read"], name="Reader"))
    assert client.get("/api/conversations", headers=read_only).status_code == 200
    denied = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "x"}, headers=read_only)
    assert denied.status_code == 403
    assert client.post(f"/api/conversations/{conversation_id}/read", json={}, headers=read_only).status_code == 403

    writer = auth(personal_token(alice, name="Claude"))
    assert send(client, writer, conversation_id, "AI가 보낸 메시지")["via"] == "Claude"

    # A personal token can never mint or list tokens, so an assistant cannot widen its own access.
    assert client.get("/api/tokens", headers=writer).status_code == 403
    assert client.post("/api/tokens", json={"name": "x"}, headers=writer).status_code == 403

    tokens = client.get("/api/tokens", headers=alice).json()
    assert [t["name"] for t in tokens] == ["Claude", "Reader"]
    assert client.delete(f"/api/tokens/{tokens[0]['id']}", headers=alice).status_code == 200
    assert client.get("/api/conversations", headers=writer).status_code == 401


def test_token_limited_to_selected_conversations(client, register, personal_token):
    alice = register("alice")
    register("bob")
    register("carol")
    allowed = direct(client, alice, "bob")
    private = direct(client, alice, "carol")
    send(client, alice, private, "비밀 이야기")

    token = auth(personal_token(alice, conversation_ids=[allowed]))
    assert [c["id"] for c in client.get("/api/conversations", headers=token).json()] == [allowed]
    assert client.get(f"/api/conversations/{private}/messages", headers=token).status_code == 404
    assert client.get("/api/messages/search", params={"q": "비밀"}, headers=token).json() == []
    assert client.post("/api/users/carol/messages", json={"content": "x"}, headers=token).status_code == 403
    assert client.post("/api/conversations/group", json={"usernames": ["bob"]}, headers=token).status_code == 403
    assert client.post("/api/users/bob/messages", json={"content": "허용된 대화"}, headers=token).status_code == 201

    other = register("dave")
    other_dm = direct(client, other, "bob")
    response = client.post("/api/tokens", json={"name": "x", "conversation_ids": [other_dm]}, headers=alice)
    assert response.status_code == 404


def test_validation_errors(client, register):
    alice = register("alice")
    register("bob")
    conversation_id = direct(client, alice, "bob")
    url = f"/api/conversations/{conversation_id}/messages"
    assert client.post(url, json={"content": ""}, headers=alice).status_code == 422
    assert client.post(url, json={"content": "   "}, headers=alice).status_code == 422
    assert client.post(url, json={"content": "x" * 2001}, headers=alice).status_code == 422
    assert client.post(url, json={"content": "x", "reply_to_id": 999}, headers=alice).status_code == 404
    assert client.get("/api/conversations/999", headers=alice).status_code == 404
    assert client.get("/api/users/nobody", headers=alice).status_code == 404


def test_pagination(client, register):
    alice = register("alice")
    register("bob")
    conversation_id = direct(client, alice, "bob")
    ids = [send(client, alice, conversation_id, f"m{i}")["id"] for i in range(5)]
    url = f"/api/conversations/{conversation_id}/messages"
    newest = client.get(url, params={"limit": 2}, headers=alice).json()
    middle = client.get(url, params={"limit": 2, "before": newest["next_cursor"]}, headers=alice).json()
    oldest = client.get(url, params={"limit": 2, "before": middle["next_cursor"]}, headers=alice).json()
    assert [m["id"] for page in (oldest, middle, newest) for m in page["items"]] == ids
    assert oldest["next_cursor"] is None


def test_web_ui_is_served(client):
    assert "Kanbikang" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
