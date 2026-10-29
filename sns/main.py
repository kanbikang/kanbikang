from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, api, services
from .config import Settings
from .db import make_engine, make_session_factory
from .mcp_server import McpAuthGate, create_mcp_server

STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """\
Kanbikang SNS의 REST API입니다. 같은 기능이 `/mcp` 엔드포인트에서 MCP 도구로도 제공되며,
각 엔드포인트의 `x-mcp-tool` 항목이 대응하는 도구 이름입니다.

인증: `Authorization: Bearer <token>` (웹 로그인 세션 토큰 또는 개인 API 토큰)
"""


async def _service_error(_request: Request, exc: services.ServiceError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    mcp = create_mcp_server(session_factory)
    # Called for its side effect: it creates `mcp.session_manager`, which is routed below at /mcp
    # (behind the auth gate) instead of mounting the separate Starlette app it returns.
    mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=settings.transport_security())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield
        engine.dispose()

    app = FastAPI(title="Kanbikang SNS API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.mcp = mcp
    app.add_exception_handler(services.ServiceError, _service_error)
    app.include_router(api.router)
    app.add_route("/mcp", McpAuthGate(mcp.session_manager.handle_request, session_factory), include_in_schema=False)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(
        "sns.main:create_app",
        factory=True,
        host=os.environ.get("SNS_HOST", "127.0.0.1"),
        port=int(os.environ.get("SNS_PORT", "8000")),
    )
