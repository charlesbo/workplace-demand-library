"""FastAPI application setup for the workplace demand library.

Creates the FastAPI app with CORS, static files, and API routes.
Provides a ``start_server`` convenience function for launching via uvicorn.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.storage.database import init_db
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise the database on startup."""
    settings = get_settings()
    data_dir: str = settings.get("app", {}).get("data_dir", "./data")
    db_path = os.path.join(data_dir, "workplace_demand.db")
    logger.info("Initialising database at %s", db_path)
    init_db(db_path)
    yield


app = FastAPI(
    title="职场需求库 API",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS ---
settings = get_settings()
cors_origins = settings.get("server", {}).get("cors_origins", ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---
from src.api.routes import router  # noqa: E402

app.include_router(router)

# --- Static files (frontend) ---
web_dir = os.path.join(os.path.dirname(__file__), "..", "..", "web")
if os.path.isdir(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")


def start_server(
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Start the API server with uvicorn.

    Args:
        host: Bind address. Defaults to config ``server.host`` or ``0.0.0.0``.
        port: Bind port. Defaults to config ``server.port`` or ``8000``.
    """
    settings = get_settings()
    server_cfg = settings.get("server", {})
    _host = host or server_cfg.get("host", "0.0.0.0")
    _port = port or server_cfg.get("port", 8000)

    logger.info("Starting server on %s:%s", _host, _port)
    uvicorn.run(app, host=_host, port=int(_port))
