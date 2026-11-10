"""FastAPI application entrypoint.

Run locally:   uvicorn backend.app.main:app --reload --port 8080   (from the repo root)
In container:  uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import audit as audit_api
from .api import auth as auth_api
from .api import htek as htek_api
from .api import ops as ops_api
from .api import pipeline as pipeline_api
from .api import system as system_api
from .api import tts as tts_api
from .config import settings
from .sessions import store

log = logging.getLogger("dpauto")

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "media-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("%s %s starting (frontend=%s)", settings.app_name, settings.version, settings.frontend_dir)
    yield
    store.purge()
    log.info("%s stopped", settings.app_name)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Deltapath PBX batch configuration over REST, browser edition.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
    app.include_router(system_api.router, prefix="/api", tags=["system"])
    app.include_router(pipeline_api.router, prefix="/api/pipeline", tags=["pipeline"])
    app.include_router(ops_api.router, prefix="/api/ops", tags=["ops"])
    app.include_router(audit_api.router, prefix="/api/audit", tags=["audit"])
    app.include_router(tts_api.router, prefix="/api/tts", tags=["tts"])
    app.include_router(htek_api.router, prefix="/api/htek", tags=["htek"])

    @app.middleware("http")
    async def hardening_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # Swagger UI pulls its assets from a CDN, so it gets no strict CSP.
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException):
        """Serve the SPA shell for unknown non-API paths typed by hand."""
        accepts_html = "text/html" in request.headers.get("accept", "")
        index = settings.frontend_dir / "index.html"
        if (
            exc.status_code == 404
            and accepts_html
            and not request.url.path.startswith("/api/")
            and index.is_file()
        ):
            return FileResponse(index)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail if isinstance(exc.detail, (dict, list, str)) else str(exc.detail)},
            headers=getattr(exc, "headers", None) or {},
        )

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
    else:  # pragma: no cover - deployment mistake
        log.error("frontend directory not found: %s", settings.frontend_dir)

        @app.get("/")
        def missing_frontend() -> dict:
            return {"error": "frontend not deployed", "expected": str(settings.frontend_dir)}

    return app


app = create_app()
