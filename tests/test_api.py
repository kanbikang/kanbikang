from __future__ import annotations

from conftest import auth


def test_register_login_logout(client, register):
    headers = register("alice", "앨리스")
    me = client.get("/api/me", headers=headers).json()
    assert me["username"] == "alice"
    assert me["display_name"] == "앨리스"

    duplicate = client.post("/api/auth/register", json={"username": "ALICE", "password": "password123"})
    assert duplicate.status_code == 409

    wrong = client.post("/api/auth/login", json={"username": "alice", "password": "nope-nope"})
    assert wrong.status_code == 401

    login = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert login.status_code == 200
    session = auth(login.json()["token"])
    assert client.post("/api/auth/logout", headers=session).status_code == 200
    assert client.get("/api/me", headers=session).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_posts_feed_tags_and_mentions(client, register):
    alice = register("alice")
    bob = register("bob")

    post = client.post("/api/posts", json={"content": "첫 글 #Hello #일상 @alice"}, headers=bob).json()
    assert post["tags"] == ["hello", "일상"]
    assert post["via"] is None

    # Alice only sees Bob's post in her home feed after following him.
    assert client.get("/api/feed", headers=alice).json()["items"] == []
    client.put("/api/users/bob/follow", headers=alice)
    assert [p["id"] for p in client.get("/api/feed", headers=alice).json()["items"]] == [post["id"]]

    by_tag = client.get("/api/posts", params={"tag": "#HELLO"}, headers=alice).json()["items"]
    assert [p["id"] for p in by_tag] == [post["id"]]
    by_text = client.get("/api/posts", params={"q": "첫 글"}, headers=alice).json()["items"]
    assert [p["id"] for p in by_text] == [post["id"]]
    assert client.get("/api/tags/trending", headers=alice).json() == [
        {"tag": "hello", "count": 1},
        {"tag": "일상", "count": 1},
    ]

    types = [n["type"] for n in client.get("/api/notifications", headers=alice).json()["items"]]
    assert types == ["mention"]


def test_like_comment_and_notifications(client, register):
    alice = register("alice")
    bob = register("bob")
    post_id = client.post("/api/posts", json={"content": "hello"}, headers=bob).json()["id"]

    liked = client.put(f"/api/posts/{post_id}/like", headers=alice).json()
    assert liked["like_count"] == 1 and liked["liked_by_me"]
    # Liking twice is a no-op.
    assert client.put(f"/api/posts/{post_id}/like", headers=alice).json()["like_count"] == 1

    comment = client.post(f"/api/posts/{post_id}/comments", json={"content": "좋네요"}, headers=alice).json()
    comments = client.get(f"/api/posts/{post_id}/comments", headers=bob).json()["items"]
    assert [c["id"] for c in comments] == [comment["id"]]

    page = client.get("/api/notifications", headers=bob).json()
    assert [n["type"] for n in page["items"]] == ["comment", "like"]
    assert page["unread_count"] == 2
    client.post("/api/notifications/read", json={}, headers=bob)
    assert client.get("/api/me/unread", headers=bob).json()["notifications"] == 0

    # The post author may delete comments on their post; others may not.
    carol = register("carol")
    assert client.delete(f"/api/comments/{comment['id']}", headers=carol).status_code == 403
    assert client.delete(f"/api/comments/{comment['id']}", headers=bob).status_code == 200


def test_edit_and_delete_require_ownership(client, register):
    alice = register("alice")
    bob = register("bob")
    post_id = client.post("/api/posts", json={"content": "원본 #a"}, headers=alice).json()["id"]

    assert client.patch(f"/api/posts/{post_id}", json={"content": "x"}, headers=bob).status_code == 403
    edited = client.patch(f"/api/posts/{post_id}", json={"content": "수정본 #b"}, headers=alice).json()
    assert edited["content"] == "수정본 #b"
    assert edited["tags"] == ["b"]
    assert edited["edited_at"] is not None

    assert client.delete(f"/api/posts/{post_id}", headers=bob).status_code == 403
    assert client.delete(f"/api/posts/{post_id}", headers=alice).status_code == 200
    assert client.get(f"/api/posts/{post_id}", headers=alice).status_code == 404


def test_pagination(client, register):
    alice = register("alice")
    ids = [client.post("/api/posts", json={"content": f"post {i}"}, headers=alice).json()["id"] for i in range(5)]

    first = client.get("/api/feed", params={"limit": 2}, headers=alice).json()
    second = client.get("/api/feed", params={"limit": 2, "cursor": first["next_cursor"]}, headers=alice).json()
    third = client.get("/api/feed", params={"limit": 2, "cursor": second["next_cursor"]}, headers=alice).json()
    seen = [p["id"] for page in (first, second, third) for p in page["items"]]
    assert seen == list(reversed(ids))
    assert third["next_cursor"] is None


def test_follow_lists_and_profile_counts(client, register):
    alice = register("alice")
    register("bob")
    assert client.put("/api/users/alice/follow", headers=alice).status_code == 422

    bob = client.put("/api/users/bob/follow", headers=alice).json()
    assert bob["is_following"] and bob["followers_count"] == 1
    followers = client.get("/api/users/bob/followers", headers=alice).json()["items"]
    assert [u["username"] for u in followers] == ["alice"]
    following = client.get("/api/users/alice/following", headers=alice).json()["items"]
    assert [u["username"] for u in following] == ["bob"]

    assert client.get("/api/users", params={"q": "bo"}, headers=alice).json()[0]["username"] == "bob"
    assert client.delete("/api/users/bob/follow", headers=alice).json()["followers_count"] == 0


def test_direct_messages(client, register):
    alice = register("alice")
    bob = register("bob")
    client.post("/api/messages/bob", json={"content": "안녕"}, headers=alice)
    client.post("/api/messages/bob", json={"content": "잘 지내?"}, headers=alice)

    conversations = client.get("/api/messages", headers=bob).json()
    assert len(conversations) == 1
    assert conversations[0]["user"]["username"] == "alice"
    assert conversations[0]["last_message"]["content"] == "잘 지내?"
    assert conversations[0]["unread_count"] == 2
    assert client.get("/api/me/unread", headers=bob).json()["messages"] == 2

    thread = client.get("/api/messages/alice", headers=bob).json()["items"]
    assert [m["content"] for m in thread] == ["잘 지내?", "안녕"]
    assert all(m["read"] for m in thread)
    assert client.get("/api/me/unread", headers=bob).json()["messages"] == 0
    assert client.post("/api/messages/alice", json={"content": "me"}, headers=alice).status_code == 422


def test_personal_tokens_scopes_and_via_label(client, register, personal_token):
    alice = register("alice")
    register("bob")

    read_only = auth(personal_token(alice, scopes=["read"], name="Reader"))
    assert client.get("/api/feed", headers=read_only).status_code == 200
    assert client.post("/api/posts", json={"content": "x"}, headers=read_only).status_code == 403
    assert client.get("/api/messages", headers=read_only).status_code == 403

    writer = auth(personal_token(alice, scopes=["write"], name="Claude"))
    post = client.post("/api/posts", json={"content": "AI가 쓴 글"}, headers=writer).json()
    assert post["via"] == "Claude"
    assert client.post("/api/messages/bob", json={"content": "x"}, headers=writer).status_code == 403

    # A personal token can never mint or list tokens, so an assistant cannot escalate its own access.
    assert client.get("/api/tokens", headers=writer).status_code == 403
    assert client.post("/api/tokens", json={"name": "x", "scopes": ["dm"]}, headers=writer).status_code == 403

    tokens = client.get("/api/tokens", headers=alice).json()
    assert [t["name"] for t in tokens] == ["Claude", "Reader"]
    assert tokens[0]["scopes"] == ["read", "write"]
    assert client.delete(f"/api/tokens/{tokens[0]['id']}", headers=alice).status_code == 200
    assert client.get("/api/feed", headers=writer).status_code == 401


def test_validation_errors(client, register):
    alice = register("alice")
    assert client.post("/api/posts", json={"content": ""}, headers=alice).status_code == 422
    assert client.post("/api/posts", json={"content": "   "}, headers=alice).status_code == 422
    assert client.post("/api/posts", json={"content": "x" * 501}, headers=alice).status_code == 422
    assert client.post("/api/auth/register", json={"username": "a b", "password": "password123"}).status_code == 422
    assert client.get("/api/users/nobody", headers=alice).status_code == 404


def test_web_ui_is_served(client):
    assert "Kanbikang" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
