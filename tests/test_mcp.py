from __future__ import annotations

import json

import anyio
import httpx2
import websockets
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from messenger.mcp_server import create_mcp_server

# REST routes that intentionally have no MCP tool: account and token management stay in the web UI.
REST_ONLY = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/tokens",
    "/api/tokens/{token_id}",
    "/api/ai/tools",
}


def http_client(url: str, token: str, mode: str = "auto") -> Client:
    headers = {"Authorization": f"Bearer {token}"}
    return Client(streamable_http_client(f"{url}/mcp", http_client=httpx2.AsyncClient(headers=headers)), mode=mode)


def register(url: str, username: str, display_name: str | None = None) -> str:
    body = {"username": username, "password": "password123", "display_name": display_name}
    response = httpx2.post(f"{url}/api/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()["token"]


def issue_token(url: str, session: str, scopes=("read", "write"), conversation_ids=None) -> str:
    body = {"name": "Claude", "scopes": list(scopes), "conversation_ids": conversation_ids}
    response = httpx2.post(f"{url}/api/tokens", json=body, headers={"Authorization": f"Bearer {session}"})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def rest(url: str, token: str, method: str, path: str, **kwargs):
    return httpx2.request(method, f"{url}/api{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs)


def test_every_rest_capability_has_an_mcp_tool(live_server):
    app, _url = live_server
    tools = {t.name for t in anyio.run(app.state.mcp.list_tools)}
    referenced = set()
    for path, operations in app.openapi()["paths"].items():
        if path in REST_ONLY:
            continue
        for method, operation in operations.items():
            tool = operation.get("x-mcp-tool")
            assert tool, f"{method.upper()} {path} has no MCP tool"
            assert tool in tools, f"{method.upper()} {path} names unknown MCP tool {tool!r}"
            referenced.add(tool)
    assert referenced == tools


def test_mcp_requires_a_valid_token(live_server):
    _app, url = live_server
    assert httpx2.post(f"{url}/mcp", json={}).status_code == 401
    assert httpx2.post(f"{url}/mcp", json={}, headers={"Authorization": "Bearer kbk_wrong"}).status_code == 401


def test_assistant_workflow_over_http(live_server):
    _app, url = live_server
    alice = register(url, "alice", "앨리스")
    bob = register(url, "bob", "밥")
    register(url, "carol", "캐럴")
    rest(url, bob, "POST", "/users/alice/messages", json={"content": "내일 점심 같이 먹을래?"})
    token = issue_token(url, alice)

    async def scenario(mode: str):
        async with http_client(url, token, mode) as mcp:
            tools = {t.name: t for t in (await mcp.list_tools()).tools}
            assert tools["delete_message"].annotations.destructive_hint is True
            assert tools["read_messages"].annotations.read_only_hint is True

            unread = (await mcp.call_tool("list_unread_messages", {})).structured_content["result"]
            if mode == "legacy":
                assert [m["content"] for m in unread[0]["messages"]] == ["내일 점심 같이 먹을래?"]
                conversation_id = unread[0]["conversation"]["id"]
                # Reading through the assistant must not mark the messages read.
                again = (await mcp.call_tool("list_unread_messages", {})).structured_content["result"]
                assert again[0]["conversation"]["unread_count"] == 1

                sent = await mcp.call_tool(
                    "send_message", {"conversation_id": conversation_id, "content": "좋아, 12시?"}
                )
                assert sent.structured_content["via"] == "Claude"
                assert sent.structured_content["sender"]["username"] == "alice"

            group = await mcp.call_tool("create_group", {"usernames": ["bob", "@carol"], "title": f"{mode} 모임"})
            group_id = group.structured_content["id"]
            assert len(group.structured_content["members"]) == 3
            await mcp.call_tool("send_message", {"conversation_id": group_id, "content": "다들 시간 괜찮아?"})

            missing = await mcp.call_tool("read_messages", {"conversation_id": 99999})
            assert missing.is_error is True
            assert "찾을 수 없습니다" in missing.content[0].text

    for mode in ("legacy", "auto"):
        anyio.run(scenario, mode)

    # Everything the assistant did is visible to the other people through the REST API.
    conversations = rest(url, bob, "GET", "/conversations").json()
    assert {c["title"] for c in conversations} == {"앨리스", "legacy 모임", "auto 모임"}
    dm = next(c for c in conversations if c["kind"] == "direct")
    assert dm["last_message"]["content"] == "좋아, 12시?" and dm["last_message"]["via"] == "Claude"


def test_assistant_message_reaches_websocket_clients(live_server):
    _app, url = live_server
    alice = register(url, "alice")
    bob = register(url, "bob")
    conversation_id = rest(url, alice, "POST", "/conversations/direct", json={"username": "bob"}).json()["id"]
    token = issue_token(url, alice)

    async def scenario():
        async with websockets.connect(url.replace("http", "ws") + "/ws") as ws:
            await ws.send(json.dumps({"token": bob}))
            assert json.loads(await ws.recv())["type"] == "ready"
            async with http_client(url, token) as mcp:
                await mcp.call_tool("send_message", {"conversation_id": conversation_id, "content": "MCP에서 보냄"})
            with anyio.fail_after(5):
                while True:
                    event = json.loads(await ws.recv())
                    if event["type"] == "message":
                        break
            assert event["message"]["content"] == "MCP에서 보냄"
            assert event["message"]["via"] == "Claude"

    anyio.run(scenario)


def test_tool_scopes_and_conversation_limits_are_enforced(live_server):
    _app, url = live_server
    alice = register(url, "alice")
    register(url, "bob")
    register(url, "carol")
    allowed = rest(url, alice, "POST", "/conversations/direct", json={"username": "bob"}).json()["id"]
    private = rest(url, alice, "POST", "/conversations/direct", json={"username": "carol"}).json()["id"]
    read_only = issue_token(url, alice, scopes=["read"])
    limited = issue_token(url, alice, conversation_ids=[allowed])

    async def scenario():
        async with http_client(url, read_only) as mcp:
            assert (await mcp.call_tool("list_conversations", {})).is_error is False
            denied = await mcp.call_tool("send_message", {"conversation_id": allowed, "content": "x"})
            assert denied.is_error is True and "'write'" in denied.content[0].text
            assert (await mcp.call_tool("mark_read", {"conversation_id": allowed})).is_error is True

        async with http_client(url, limited) as mcp:
            listed = (await mcp.call_tool("list_conversations", {})).structured_content["result"]
            assert [c["id"] for c in listed] == [allowed]
            assert (await mcp.call_tool("read_messages", {"conversation_id": private})).is_error is True
            assert (await mcp.call_tool("send_direct_message", {"username": "carol", "content": "x"})).is_error is True
            assert (await mcp.call_tool("send_direct_message", {"username": "bob", "content": "ok"})).is_error is False

    anyio.run(scenario)


def test_prompts_are_listed(live_server):
    _app, url = live_server
    token = issue_token(url, register(url, "alice"), scopes=["read"])

    async def scenario():
        async with http_client(url, token) as mcp:
            assert {p.name for p in (await mcp.list_prompts()).prompts} == {"catch_up", "draft_reply"}

    anyio.run(scenario)


def test_stdio_mode_uses_configured_token(live_server):
    """Without HTTP headers (stdio transport) the server authenticates with the configured token."""
    app, url = live_server
    alice = register(url, "alice")
    register(url, "bob")
    token = issue_token(url, alice)
    server = create_mcp_server(app.state.session_factory, stdio_token=token)

    async def scenario():
        async with Client(server) as mcp:
            sent = await mcp.call_tool("send_direct_message", {"username": "bob", "content": "stdio에서 보냄"})
            assert sent.structured_content["sender"]["username"] == "alice"

        async with Client(create_mcp_server(app.state.session_factory)) as anonymous:
            assert (await anonymous.call_tool("get_me", {})).is_error is True

    anyio.run(scenario)
