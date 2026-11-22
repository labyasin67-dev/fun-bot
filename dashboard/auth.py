"""Discord OAuth2, sessions, and CSRF helpers."""

from __future__ import annotations

import os
import secrets
from typing import Any
from urllib.parse import urlencode

import aiohttp
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from dashboard import ADMINISTRATOR, MANAGE_GUILD, client_id, dashboard_url, oauth_configured

AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
API_BASE = "https://discord.com/api/v10"


def redirect_uri(request: Request) -> str:
    return f"{dashboard_url(request)}/callback"


def ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(form: Any, request: Request) -> None:
    token = form.get("csrf_token") if form is not None else None
    if not token or token != request.session.get("csrf_token"):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_user(request: Request) -> dict | RedirectResponse:
    user = current_user(request)
    if user:
        return user
    next_url = request.url.path
    return RedirectResponse(f"/login?next={next_url}", status_code=302)


def managed_guilds(request: Request) -> list[dict]:
    return list(request.session.get("guilds") or [])


def can_manage_guild(request: Request, guild_id: int) -> bool:
    return any(int(g["id"]) == guild_id for g in managed_guilds(request))


def has_manage_permission(permissions: int) -> bool:
    return bool(permissions & (MANAGE_GUILD | ADMINISTRATOR))


def oauth_authorize_url(request: Request, next_url: str | None = None) -> str:
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    if next_url:
        request.session["oauth_next"] = next_url
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(request: Request, code: str) -> dict:
    secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    data = {
        "client_id": client_id(),
        "client_secret": secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(request),
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post(TOKEN_URL, data=data, headers=headers) as resp:
            payload = await resp.json()
            if resp.status >= 400 or "access_token" not in payload:
                raise HTTPException(status_code=400, detail="Could not complete Discord login.")
            token = payload["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        async with session.get(f"{API_BASE}/users/@me", headers=auth) as resp:
            user = await resp.json()
            if resp.status >= 400:
                raise HTTPException(status_code=400, detail="Could not load your Discord profile.")
        async with session.get(f"{API_BASE}/users/@me/guilds", headers=auth) as resp:
            guilds = await resp.json()
            if resp.status >= 400 or not isinstance(guilds, list):
                guilds = []
    managed = []
    for guild in guilds:
        try:
            perms = int(guild.get("permissions") or 0)
        except (TypeError, ValueError):
            perms = 0
        if has_manage_permission(perms):
            managed.append(
                {
                    "id": str(guild["id"]),
                    "name": guild.get("name") or "Unknown server",
                    "icon": guild.get("icon"),
                }
            )
    request.session["user"] = {
        "id": str(user["id"]),
        "username": user.get("global_name") or user.get("username") or "User",
        "avatar": user.get("avatar"),
    }
    request.session["guilds"] = managed
    ensure_csrf(request)
    return request.session["user"]


def flash(request: Request, kind: str, message: str) -> None:
    items = list(request.session.get("flash") or [])
    items.append({"kind": kind, "message": message})
    request.session["flash"] = items


def pop_flash(request: Request) -> list[dict]:
    items = list(request.session.get("flash") or [])
    request.session["flash"] = []
    return items


def avatar_url(user: dict | None) -> str:
    if not user:
        return ""
    uid, avatar = user.get("id"), user.get("avatar")
    if uid and avatar:
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png?size=64"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def guild_icon_url(guild: dict) -> str:
    gid, icon = guild.get("id"), guild.get("icon")
    if gid and icon:
        return f"https://cdn.discordapp.com/icons/{gid}/{icon}.png?size=64"
    return ""
