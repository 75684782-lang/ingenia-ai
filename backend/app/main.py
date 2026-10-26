from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import routes_chat, routes_system, routes_tools, ws
from .connectors.civil3d_client import Civil3DClient
from .core.config import Settings, get_settings
from .core.logging import configure_logging, get_logger
from .services.chat_service import ChatService
from .services.ollama_client import OllamaClient
from .services.operation_store import OperationStore
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    log = get_logger("app")
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Ingenia AI iniciado en http://%s:%s", settings.host, settings.port)
        yield
        app.state.store.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    store = OperationStore(settings.db_path)
    ollama = OllamaClient(settings.ollama_url, timeout=settings.ollama_timeout)
    connector = Civil3DClient(
        settings.civil3d_bridge_url,
        token=settings.civil3d_token,
        timeout=settings.civil3d_timeout,
        fallback_to_mock=settings.civil3d_fallback_to_mock,
    )
    registry = ToolRegistry()
    executor = ToolExecutor(registry, connector, store)
    chat = ChatService(
        ollama,
        registry,
        executor,
        store,
        connector,
        max_steps=settings.max_tool_steps,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.ollama = ollama
    app.state.connector = connector
    app.state.registry = registry
    app.state.executor = executor
    app.state.chat = chat

    app.include_router(routes_system.public_router)
    app.include_router(routes_system.router)
    app.include_router(routes_tools.router)
    app.include_router(routes_chat.router)
    app.include_router(ws.router)

    frontend = settings.frontend_dir
    assets = frontend / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        index_file = frontend / "index.html"
        if not index_file.is_file():
            return JSONResponse(
                {"error": "Frontend no encontrado", "path": str(index_file)},
                status_code=500,
            )
        response = FileResponse(index_file)
        if settings.auth_token:
            response.set_cookie(
                "ingenia_token",
                settings.auth_token,
                httponly=True,
                samesite="strict",
                secure=settings.cookie_secure,
                max_age=60 * 60 * 12,
            )
        return response

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        icon = assets / "icons" / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon, media_type="image/svg+xml")
        return JSONResponse({}, status_code=204)

    return app


app = create_app()
