from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from . import __version__, api, events, services
from .config import Settings
from .db import make_engine, make_session_factory
from .mcp_server import McpAuthGate, create_mcp_server

STATIC_DIR = Path(__file__).parent / "static"
WS_AUTH_TIMEOUT = 10
WS_RECHECK_SECONDS = 30

DESCRIPTION = """\
Kanbikang 메신저의 REST API입니다. 같은 기능이 `/mcp` 엔드포인트에서 MCP 도구로도 제공되며,
각 엔드포인트의 `x-mcp-tool` 항목이 대응하는 도구 이름입니다.

인증: `Authorization: Bearer <token>` (웹 로그인 세션 토큰 또는 개인 API 토큰)

실시간 이벤트: `/ws` WebSocket에 연결한 뒤 첫 메시지로 `{"token": "<token>"}`을 보내면
`message`, `message_updated`, `read`, `conversation` 이벤트를 받습니다.
"""


async def _service_error(_request: Request, exc: services.ServiceError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code, headers=headers)


def _authenticate(session_factory: sessionmaker[Session], token: object) -> services.Actor | None:
    if not isinstance(token, str):
        return None
    with session_factory() as db:
        try:
            return services.authenticate(db, token)
        except services.Unauthorized:
            return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    bus = events.EventBus()
    events.install(session_factory, bus)

    mcp = create_mcp_server(session_factory)
    # Called for its side effect: it creates `mcp.session_manager`, which is routed below at /mcp
    # (behind the auth gate) instead of mounting the separate Starlette app it returns.
    mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=settings.transport_security())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        bus.bind(asyncio.get_running_loop())
        async with mcp.session_manager.run():
            yield
        bus.bind(None)
        engine.dispose()

    app = FastAPI(title="Kanbikang Messenger API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.mcp = mcp
    app.state.bus = bus
    app.add_exception_handler(services.ServiceError, _service_error)
    app.include_router(api.router)
    app.add_route("/mcp", McpAuthGate(mcp.session_manager.handle_request, session_factory), include_in_schema=False)

    @app.websocket("/ws")
    async def realtime(websocket: WebSocket) -> None:
        """Browsers cannot set headers on WebSockets, so the token arrives as the first message."""
        await websocket.accept()
        try:
            hello = await asyncio.wait_for(websocket.receive_json(), WS_AUTH_TIMEOUT)
        except (TimeoutError, ValueError, WebSocketDisconnect):
            await websocket.close(code=4401)
            return
        token = hello.get("token") if isinstance(hello, dict) else None
        actor = await anyio.to_thread.run_sync(_authenticate, session_factory, token)
        if actor is None or "read" not in actor.scopes:
            await websocket.close(code=4401)
            return

        queue = bus.subscribe(actor.user_id)
        try:
            await websocket.send_json({"type": "ready", "user_id": actor.user_id})
            async with anyio.create_task_group() as tg:

                async def forward() -> None:
                    checked_at = time.monotonic()
                    while True:
                        payload = await queue.get()
                        if time.monotonic() - checked_at > WS_RECHECK_SECONDS:
                            # A revoked or expired token must stop receiving messages.
                            if await anyio.to_thread.run_sync(_authenticate, session_factory, token) is None:
                                await websocket.close(code=4401)
                                tg.cancel_scope.cancel()
                                return
                            checked_at = time.monotonic()
                        if actor.can_access(payload["conversation_id"]):
                            await websocket.send_json(payload)

                tg.start_soon(forward)
                try:
                    while True:  # Client messages are ignored; this loop just notices the disconnect.
                        await websocket.receive_text()
                except WebSocketDisconnect:
                    pass
                tg.cancel_scope.cancel()
        finally:
            bus.unsubscribe(actor.user_id, queue)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(
        "messenger.main:create_app",
        factory=True,
        host=os.environ.get("KANBIKANG_HOST", "127.0.0.1"),
        port=int(os.environ.get("KANBIKANG_PORT", "8000")),
    )
