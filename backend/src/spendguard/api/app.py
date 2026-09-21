"""The FastAPI application - ``spendguard serve``, or ``uvicorn spendguard.api.app:create_app --factory``.

Thin by design (docs/API-CONTRACT.md): it reads what the batch runs produced and
writes one thing, a reviewer's decision. It never runs a detector or the LLM
inside a request (D-10) - an investigation takes minutes and spends quota, which
is a batch job's business, not a page load's.

Every error leaves as ``{"detail": {"code", "message"}}``; a stack trace never
reaches the browser.

When the React build exists (``frontend/dist``) the same process serves it, so
the whole dashboard runs from one command. During development the Vite server
serves the frontend instead and proxies ``/api`` here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from spendguard.api import cases, overview
from spendguard.api.deps import AppStores
from spendguard.api.schemas import ErrorResponse
from spendguard.config import settings
from spendguard.db.store import get_engine

API_PREFIX = "/api/v1"
log = logging.getLogger(__name__)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})


def create_app(
    *,
    duckdb_path: Path | None = None,
    database_url: str | None = None,
    eval_dir: Path | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="SpendGuard API",
        version="1.0.0",
        description=(
            "Procurement cases, verified audit notes, evidence and review. Reads batch "
            "results; the only writes are a reviewer's status change and the demo."
        ),
        responses={422: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    app.state.stores = AppStores(
        duckdb_path=Path(duckdb_path or settings.duckdb_path),
        engine=get_engine(database_url),
        eval_dir=Path(eval_dir or settings.processed_data_dir / "eval"),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["GET", "PATCH", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()
        )
        return _error(422, "validation_error", problems)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s", request.url.path)
        return _error(500, "internal_error", "Something went wrong on the server; see its log.")

    app.include_router(cases.router, prefix=API_PREFIX)
    app.include_router(overview.router, prefix=API_PREFIX)

    dist = Path(frontend_dist or settings.frontend_dist)
    if (dist / "index.html").exists():
        _serve_frontend(app, dist)
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """The built single-page app. Any path that is not the API gets index.html."""
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, detail={"code": "not_found", "message": f"No route /{path}."})
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
