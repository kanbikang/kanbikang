from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def token_of(headers: dict[str, str]) -> str:
    return headers["Authorization"].split()[1]


def next_event(ws, event_type: str) -> dict:
    while True:
        event = ws.receive_json()
        if event["type"] == event_type:
            return event


def test_websocket_rejects_bad_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": "kbk_wrong"})
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
    assert excinfo.value.code == 4401


def test_message_and_read_events(client, register):
    alice = register("alice")
    bob = register("bob")
    conversation_id = client.post("/api/conversations/direct", json={"username": "bob"}, headers=alice).json()["id"]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": token_of(bob)})
        assert ws.receive_json()["type"] == "ready"

        sent = client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "실시간"}, headers=alice)
        event = next_event(ws, "message")
        assert event["message"]["id"] == sent.json()["id"]
        assert event["message"]["content"] == "실시간"

        client.patch(f"/api/messages/{sent.json()['id']}", json={"content": "수정됨"}, headers=alice)
        assert next_event(ws, "message_updated")["message"]["content"] == "수정됨"

        client.post(f"/api/conversations/{conversation_id}/read", json={}, headers=bob)
        read = next_event(ws, "read")
        assert read["last_read_message_id"] == sent.json()["id"]


def test_restricted_token_only_receives_allowed_conversations(client, register, personal_token):
    alice = register("alice")
    bob = register("bob")
    carol = register("carol")
    allowed = client.post("/api/conversations/direct", json={"username": "bob"}, headers=alice).json()["id"]
    private = client.post("/api/conversations/direct", json={"username": "carol"}, headers=alice).json()["id"]
    token = personal_token(alice, conversation_ids=[allowed])

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": token})
        ws.receive_json()
        client.post(f"/api/conversations/{private}/messages", json={"content": "비공개"}, headers=carol)
        client.post(f"/api/conversations/{allowed}/messages", json={"content": "공개"}, headers=bob)
        event = next_event(ws, "message")
        assert event["conversation_id"] == allowed
        assert event["message"]["content"] == "공개"


def test_revoked_token_stops_receiving_events(client, register, personal_token, monkeypatch):
    monkeypatch.setattr("messenger.main.WS_RECHECK_SECONDS", 0)
    alice = register("alice")
    bob = register("bob")
    conversation_id = client.post("/api/conversations/direct", json={"username": "bob"}, headers=alice).json()["id"]
    token = personal_token(alice)
    token_id = client.get("/api/tokens", headers=alice).json()[0]["id"]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": token})
        ws.receive_json()
        client.delete(f"/api/tokens/{token_id}", headers=alice)
        client.post(f"/api/conversations/{conversation_id}/messages", json={"content": "폐기 후"}, headers=bob)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
    assert excinfo.value.code == 4401
