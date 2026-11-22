"""Web dashboard served from the bot process."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent
DEFAULT_CLIENT_ID = "1573391890227925002"
INVITE_PERMISSIONS = "1099945077846"
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3


def client_id() -> str:
    return os.getenv("DISCORD_CLIENT_ID", DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID


def oauth_configured() -> bool:
    return bool(os.getenv("DISCORD_CLIENT_SECRET", "").strip())


def dashboard_url(request: Any | None = None) -> str:
    explicit = os.getenv("DASHBOARD_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    if request is not None:
        return str(request.base_url).rstrip("/")
    port = os.getenv("PORT", "8080")
    return f"http://127.0.0.1:{port}"


def https_only() -> bool:
    return dashboard_url().startswith("https://")


def create_app(bot: Any | None = None) -> FastAPI:
    from dashboard.routes import register_routes

    secret = os.getenv("SESSION_SECRET", "").strip() or secrets.token_hex(32)
    app = FastAPI(title="Fun bot dashboard", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="funbot_session",
        same_site="lax",
        https_only=https_only(),
        max_age=60 * 60 * 24 * 7,
    )
    app.state.bot = bot
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    register_routes(app)
    return app
