from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from sns.config import Settings
from sns.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def register(client):
    """Registers a user and returns auth headers for its web session."""

    def _register(username: str, display_name: str | None = None) -> dict[str, str]:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "password123", "display_name": display_name},
        )
        assert response.status_code == 201, response.text
        return auth(response.json()["token"])

    return _register


@pytest.fixture
def personal_token(client):
    def _issue(session_headers: dict[str, str], scopes=("read", "write"), name: str = "Claude") -> str:
        response = client.post("/api/tokens", json={"name": name, "scopes": list(scopes)}, headers=session_headers)
        assert response.status_code == 201, response.text
        return response.json()["token"]

    return _issue


@pytest.fixture
def live_server(settings):
    """Runs the app on a real port so MCP clients can connect over Streamable HTTP."""
    app = create_app(settings)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.02)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
