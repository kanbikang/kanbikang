from __future__ import annotations

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from sns.mcp_server import create_mcp_server

# REST routes that intentionally have no MCP tool: account and token management stay in the web UI.
REST_ONLY = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/tokens",
    "/api/tokens/{token_id}",
    "/api/ai/tools",
}


def http_client(url: str, token: str | None, mode: str = "auto") -> Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Client(streamable_http_client(f"{url}/mcp", http_client=httpx2.AsyncClient(headers=headers)), mode=mode)


def register(url: str, username: str) -> str:
    response = httpx2.post(f"{url}/api/auth/register", json={"username": username, "password": "password123"})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def issue_token(url: str, session: str, scopes: list[str], name: str = "Claude") -> str:
    response = httpx2.post(
        f"{url}/api/tokens", json={"name": name, "scopes": scopes}, headers={"Authorization": f"Bearer {session}"}
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


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
    assert httpx2.post(f"{url}/mcp", json={}, headers={"Authorization": "Bearer sns_wrong"}).status_code == 401


def test_assistant_workflow_over_http(live_server):
    _app, url = live_server
    alice = register(url, "alice")
    bob = register(url, "bob")
    httpx2.post(
        f"{url}/api/posts", json={"content": "오늘 날씨 좋네요 #날씨"}, headers={"Authorization": f"Bearer {bob}"}
    )
    token = issue_token(url, alice, ["read", "write", "dm"])

    async def scenario(mode: str):
        async with http_client(url, token, mode) as mcp:
            listed = await mcp.list_tools()
            tools = {t.name: t for t in listed.tools}
            assert tools["delete_post"].annotations.destructive_hint is True
            assert tools["get_home_feed"].annotations.read_only_hint is True

            me = await mcp.call_tool("get_me", {})
            assert me.structured_content["username"] == "alice"

            await mcp.call_tool("follow_user", {"username": "@bob"})
            feed = await mcp.call_tool("get_home_feed", {"limit": 5})
            post = next(p for p in feed.structured_content["items"] if p["author"]["username"] == "bob")

            await mcp.call_tool("like_post", {"post_id": post["id"]})
            comment = await mcp.call_tool("add_comment", {"post_id": post["id"], "content": "그러게요"})
            assert comment.structured_content["via"] == "Claude"

            created = await mcp.call_tool("create_post", {"content": f"{mode} 모드에서 AI가 쓴 글 #mcp"})
            assert created.is_error is False
            assert created.structured_content["via"] == "Claude"

            sent = await mcp.call_tool("send_message", {"username": "bob", "content": "안녕하세요"})
            assert sent.structured_content["recipient"]["username"] == "bob"

            missing = await mcp.call_tool("get_post", {"post_id": 99999})
            assert missing.is_error is True
            assert "찾을 수 없습니다" in missing.content[0].text

    for mode in ("legacy", "auto"):
        anyio.run(scenario, mode)

    # Everything the assistant did is visible through the REST API.
    bob_headers = {"Authorization": f"Bearer {bob}"}
    notifications = httpx2.get(f"{url}/api/notifications", headers=bob_headers).json()["items"]
    assert {n["type"] for n in notifications} >= {"follow", "like", "comment"}
    explore = httpx2.get(f"{url}/api/posts", params={"tag": "mcp"}, headers=bob_headers).json()["items"]
    assert [p["via"] for p in explore] == ["Claude", "Claude"]
    assert httpx2.get(f"{url}/api/me/unread", headers=bob_headers).json()["messages"] == 2


def test_tool_scopes_are_enforced(live_server):
    _app, url = live_server
    alice = register(url, "alice")
    register(url, "bob")
    token = issue_token(url, alice, ["read"])

    async def scenario():
        async with http_client(url, token) as mcp:
            assert (await mcp.call_tool("get_home_feed", {})).is_error is False
            denied = await mcp.call_tool("create_post", {"content": "x"})
            assert denied.is_error is True
            assert "'write'" in denied.content[0].text
            assert (await mcp.call_tool("list_conversations", {})).is_error is True
            unread = await mcp.call_tool("get_unread_counts", {})
            assert unread.structured_content["messages"] is None

    anyio.run(scenario)


def test_prompts_are_listed(live_server):
    _app, url = live_server
    token = issue_token(url, register(url, "alice"), ["read"])

    async def scenario():
        async with http_client(url, token) as mcp:
            names = {p.name for p in (await mcp.list_prompts()).prompts}
            assert names == {"catch_up", "draft_post"}

    anyio.run(scenario)


def test_stdio_mode_uses_configured_token(live_server):
    """Without HTTP headers (stdio transport) the server authenticates with the configured token."""
    app, url = live_server
    token = issue_token(url, register(url, "alice"), ["read", "write"])
    server = create_mcp_server(app.state.session_factory, stdio_token=token)

    async def scenario():
        async with Client(server) as mcp:
            created = await mcp.call_tool("create_post", {"content": "stdio에서 쓴 글"})
            assert created.structured_content["author"]["username"] == "alice"

        async with Client(create_mcp_server(app.state.session_factory)) as anonymous:
            assert (await anonymous.call_tool("get_me", {})).is_error is True

    anyio.run(scenario)
