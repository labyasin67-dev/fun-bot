"""HTTP routes for the dashboard."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import discord
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cogs.channels import FEATURES as FEATURE_LABELS
from cogs.welcome import DEFAULT_WELCOME
from dashboard import DEFAULT_CLIENT_ID, INVITE_PERMISSIONS, ROOT, client_id, oauth_configured
from dashboard.auth import (
    avatar_url,
    can_manage_guild,
    current_user,
    ensure_csrf,
    exchange_code,
    flash,
    guild_icon_url,
    managed_guilds,
    oauth_authorize_url,
    pop_flash,
    require_csrf,
    require_user,
)

TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
ALT_ACTIONS = ("none", "log", "timeout", "kick", "quarantine")


def _bot(request: Request):
    return getattr(request.app.state, "bot", None)


def _invite_url(guild_id: int | None = None) -> str:
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={client_id()}&permissions={INVITE_PERMISSIONS}"
        "&scope=bot%20applications.commands"
    )
    if guild_id is not None:
        url += f"&guild_id={guild_id}&disable_guild_select=true"
    return url


def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    user = current_user(request)
    bot = _bot(request)
    owner_ids = set(getattr(bot, "app_owner_ids", None) or set()) if bot is not None else set()
    is_admin = bool(user and int(user["id"]) in owner_ids)
    access = getattr(request.state, "premium_access", None)
    from premium import premium_required as _prem_required
    ctx.update(
        {
            "request": request,
            "csrf_token": ensure_csrf(request),
            "user": user,
            "avatar_url": avatar_url(user),
            "flash": pop_flash(request),
            "oauth_ready": oauth_configured(),
            "invite_url": _invite_url(ctx.get("guild_id")),
            "is_admin": is_admin,
            "premium_required_flag": _prem_required(),
            "premium_ok": True if access is None else access.allowed,
            "pricing_url": "/pricing",
        }
    )
    return TEMPLATES.TemplateResponse(request, name, ctx)


async def _form(request: Request):
    form = await request.form()
    require_csrf(form, request)
    return form


def _need_login(user) -> RedirectResponse | None:
    if isinstance(user, RedirectResponse):
        return user
    return None


async def _guild_or_redirect(request: Request, guild_id: int):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user, None, None
    if not can_manage_guild(request, guild_id):
        flash(request, "error", "You need Manage Server in that community.")
        return RedirectResponse("/servers", status_code=302), None, None
    bot = _bot(request)
    guild = bot.get_guild(guild_id) if bot is not None else None
    if guild is None:
        flash(request, "error", "The bot is not in that server, or it is still starting.")
        return RedirectResponse("/servers", status_code=302), None, None
    try:
        from premium import guild_access, owner_ids_from_env
        ids = owner_ids_from_env()
        ids |= set(getattr(bot, "app_owner_ids", None) or set())
        request.state.premium_access = await guild_access(
            bot.db, guild.id, guild_owner_id=guild.owner_id, owner_ids=ids
        )
    except Exception:
        request.state.premium_access = None
    return None, guild, user


def _text_channels(guild: discord.Guild) -> list[discord.TextChannel]:
    channels = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel]
    return sorted(channels, key=lambda c: ((c.category.position if c.category else -1), c.position, c.id))


def _grouped_channels(guild: discord.Guild) -> list[tuple[str, list[discord.TextChannel]]]:
    groups: dict[str, list[discord.TextChannel]] = {}
    order: list[str] = []
    for channel in _text_channels(guild):
        label = channel.category.name if channel.category else "No category"
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(channel)
    return [(label, groups[label]) for label in order]


def _roles(guild: discord.Guild) -> list[discord.Role]:
    me = guild.me
    out = []
    for role in reversed(guild.roles):
        if role.is_default() or role.managed:
            continue
        if me and role >= me.top_role:
            continue
        out.append(role)
    return out


def _nav(guild: discord.Guild, active: str) -> dict:
    return {"guild": guild, "guild_id": guild.id, "active": active}


def _member_name(guild: discord.Guild, user_id: int | None) -> str:
    if not user_id:
        return "—"
    member = guild.get_member(int(user_id))
    return str(member) if member else f"ID {user_id}"



def _age_label(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    secs = int(seconds)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


ACTION_LABELS = {
    "none": "None",
    "logged": "Logged",
    "timeout": "Timeout 1h",
    "kick": "Kicked",
    "ban": "Banned",
    "quarantine": "Quarantined",
    "safe": "Marked safe",
}


def _flag_display(guild: discord.Guild, row, whitelist_ids: set[int], quarantine_role_id: int | None) -> dict:
    import json
    from cogs.altdetect import STATUS_LABELS
    uid = int(row["user_id"])
    member = guild.get_member(uid)
    if uid in whitelist_ids:
        status = "whitelisted"
    elif member is not None:
        if member.is_timed_out():
            status = "timed_out"
        elif quarantine_role_id and any(r.id == quarantine_role_id for r in member.roles):
            status = "quarantined"
        else:
            status = "in_server"
    else:
        status = row["status"] or "left"
        if status == "in_server":
            status = "left"
    try:
        reasons = json.loads(row["reasons"] or "[]")
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
    except Exception:
        reasons = [str(row["reasons"] or "")]
    created = row["account_created_at"]
    joined = row["joined_at"] or row["created_at"]
    age = None
    if created and joined:
        age = float(joined) - float(created)
    elif created:
        age = None
    username = row["display_name"] or row["username"] or (str(member) if member else f"ID {uid}")
    handle = row["username"] or (str(member) if member else "")
    avatar = row["avatar_url"] or (member.display_avatar.url if member and member.display_avatar else "")
    return {
        "row": row,
        "id": int(row["id"]),
        "user_id": uid,
        "username": username,
        "handle": handle,
        "avatar": avatar,
        "age": _age_label(age),
        "joined": joined,
        "score": int(row["score"]),
        "verdict": row["verdict"],
        "reasons": reasons,
        "action": ACTION_LABELS.get(row["action_taken"] or "logged", row["action_taken"] or "Logged"),
        "action_key": row["action_taken"] or "logged",
        "status": STATUS_LABELS.get(status, status.replace("_", " ").title()),
        "status_key": status,
        "can_act": status != "banned",
    }


def register_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if current_user(request):
            return RedirectResponse("/servers", status_code=302)
        return render(request, "home.html")

    @app.get("/login")
    async def login(request: Request, next: str = "/servers"):
        if not oauth_configured():
            return render(request, "home.html", login_disabled=True)
        if current_user(request):
            return RedirectResponse(next or "/servers", status_code=302)
        return RedirectResponse(oauth_authorize_url(request, next), status_code=302)

    @app.get("/callback")
    async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        if error:
            flash(request, "error", "Discord login was cancelled.")
            return RedirectResponse("/", status_code=302)
        expected = request.session.pop("oauth_state", None)
        if not code or not state or not expected or state != expected:
            flash(request, "error", "Login state did not match. Please try again.")
            return RedirectResponse("/", status_code=302)
        if not oauth_configured():
            flash(request, "error", "Login is not configured on this dashboard.")
            return RedirectResponse("/", status_code=302)
        try:
            await exchange_code(request, code)
        except Exception:
            flash(request, "error", "Could not complete Discord login.")
            return RedirectResponse("/", status_code=302)
        next_url = request.session.pop("oauth_next", None) or "/servers"
        if not next_url.startswith("/"):
            next_url = "/servers"
        return RedirectResponse(next_url, status_code=302)

    @app.post("/logout")
    async def logout(request: Request):
        await _form(request)
        request.session.clear()
        return RedirectResponse("/", status_code=302)

    @app.get("/servers", response_class=HTMLResponse)
    async def servers(request: Request):
        user = require_user(request)
        redir = _need_login(user)
        if redir:
            return redir
        bot = _bot(request)
        bot_ids = {g.id for g in bot.guilds} if bot is not None else set()
        rows = []
        for guild in managed_guilds(request):
            gid = int(guild["id"])
            present = gid in bot_ids
            live = bot.get_guild(gid) if bot is not None else None
            rows.append(
                {
                    "id": gid,
                    "name": (live.name if live else guild["name"]),
                    "icon": guild_icon_url(guild) or (live.icon.url if live and live.icon else ""),
                    "present": present,
                    "members": (live.member_count if live else None),
                    "invite": _invite_url(gid),
                }
            )
        rows.sort(key=lambda r: (not r["present"], r["name"].lower()))
        return render(request, "servers.html", servers=rows, bot_ready=bool(bot and bot.is_ready()))

    @app.get("/servers/{guild_id}", response_class=HTMLResponse)
    async def overview(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        online = sum(1 for m in guild.members if not m.bot and m.status is not discord.Status.offline) if guild.members else 0
        assigned = await _bot(request).db.list_feature_channels(guild.id)
        return render(
            request,
            "overview.html",
            **_nav(guild, "overview"),
            member_count=guild.member_count or len(guild.members),
            online_count=online,
            bot_status="Online" if _bot(request) and _bot(request).is_ready() and guild.me else "Starting",
            latency_ms=round((_bot(request).latency or 0) * 1000),
            assigned=assigned,
            grouped=_grouped_channels(guild),
        )

    @app.get("/servers/{guild_id}/channels", response_class=HTMLResponse)
    async def channels_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        assigned = await _bot(request).db.list_feature_channels(guild.id)
        return render(
            request,
            "channels.html",
            **_nav(guild, "channels"),
            features=FEATURE_LABELS,
            assigned=assigned,
            grouped=_grouped_channels(guild),
        )

    @app.post("/servers/{guild_id}/channels")
    async def channels_post(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        db = _bot(request).db
        valid = {c.id for c in _text_channels(guild)}
        for key in FEATURE_LABELS:
            if key == "games":
                raw = form.getlist("games")
                ids = [int(v) for v in raw if str(v).isdigit() and int(v) in valid]
                await db.set_feature_channels(guild.id, "games", ids)
                continue
            value = str(form.get(key) or "").strip()
            channel_id = int(value) if value.isdigit() and int(value) in valid else None
            if key == "counting" and channel_id is None:
                await db.update_settings(guild.id, counting_next=1, counting_last_user=None)
            await db.set_feature_channel(guild.id, key, channel_id)
        flash(request, "ok", "Channel assignments saved. They apply immediately.")
        return RedirectResponse(f"/servers/{guild_id}/channels", status_code=303)

    @app.get("/servers/{guild_id}/levels", response_class=HTMLResponse)
    async def levels_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        roles = await db.level_roles(guild.id)
        role_rows = []
        for row in roles:
            role = guild.get_role(int(row["role_id"]))
            role_rows.append({"level": int(row["level"]), "role": role, "role_id": int(row["role_id"])})
        board = []
        for i, row in enumerate(await db.top_xp(guild.id, 15), start=1):
            member = guild.get_member(int(row["user_id"]))
            board.append({"rank": i, "name": str(member) if member else f"ID {row['user_id']}", "xp": int(row["xp"])})
        levelup_id = await db.get_feature_channel(guild.id, "levelups")
        return render(
            request,
            "levels.html",
            **_nav(guild, "levels"),
            role_rows=role_rows,
            assignable=_roles(guild),
            board=board,
            levelup_id=levelup_id,
            grouped=_grouped_channels(guild),
        )

    @app.post("/servers/{guild_id}/levels")
    async def levels_post(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        if action == "add":
            try:
                level = int(form.get("level") or 0)
                role_id = int(form.get("role_id") or 0)
            except ValueError:
                flash(request, "error", "Enter a valid level and role.")
                return RedirectResponse(f"/servers/{guild_id}/levels", status_code=303)
            role = guild.get_role(role_id)
            if level < 1 or level > 1000 or role is None or role not in _roles(guild):
                flash(request, "error", "That level or role isn't valid.")
            else:
                await db.set_level_role(guild.id, level, role.id)
                flash(request, "ok", f"Members will receive @{role.name} at level {level}.")
        elif action == "remove":
            try:
                level = int(form.get("level") or 0)
            except ValueError:
                level = 0
            if await db.remove_level_role(guild.id, level):
                flash(request, "ok", f"Removed the reward for level {level}.")
            else:
                flash(request, "error", "That level role was not set.")
        elif action == "channel":
            value = str(form.get("levelup_channel") or "").strip()
            valid = {c.id for c in _text_channels(guild)}
            channel_id = int(value) if value.isdigit() and int(value) in valid else None
            await db.set_feature_channel(guild.id, "levelups", channel_id)
            flash(request, "ok", "Level-up channel updated.")
        return RedirectResponse(f"/servers/{guild_id}/levels", status_code=303)

    @app.get("/servers/{guild_id}/selfroles", response_class=HTMLResponse)
    async def selfroles_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        rows = await _bot(request).db.self_roles(guild.id)
        items = []
        for row in rows:
            role = guild.get_role(int(row["role_id"]))
            items.append({"row": row, "role": role, "role_id": int(row["role_id"])})
        return render(
            request,
            "selfroles.html",
            **_nav(guild, "selfroles"),
            items=items,
            assignable=_roles(guild),
            grouped=_grouped_channels(guild),
        )

    @app.post("/servers/{guild_id}/selfroles")
    async def selfroles_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild and user
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        if action == "add":
            try:
                role_id = int(form.get("role_id") or 0)
            except ValueError:
                role_id = 0
            role = guild.get_role(role_id)
            existing = await db.self_roles(guild.id)
            if role is None or role not in _roles(guild):
                flash(request, "error", "Pick a role the bot can assign.")
            elif len(existing) >= 25 and all(int(r["role_id"]) != role.id for r in existing):
                flash(request, "error", "You can have at most 25 self-roles.")
            else:
                label = (str(form.get("label") or "").strip() or role.name)[:80]
                emoji = (str(form.get("emoji") or "").strip() or None)
                await db.add_self_role(guild.id, role.id, label, emoji)
                flash(request, "ok", f"Added @{role.name} to the self-role panel.")
        elif action == "remove":
            try:
                role_id = int(form.get("role_id") or 0)
            except ValueError:
                role_id = 0
            if await db.remove_self_role(guild.id, role_id):
                flash(request, "ok", "Removed that self-role.")
            else:
                flash(request, "error", "That role was not on the panel.")
        elif action == "post":
            try:
                channel_id = int(form.get("channel_id") or 0)
            except ValueError:
                channel_id = 0
            channel = guild.get_channel(channel_id)
            cog = _bot(request).get_cog("Roles")
            if not isinstance(channel, discord.TextChannel) or cog is None:
                flash(request, "error", "Pick a text channel I can post in.")
            else:
                try:
                    await cog.post_panel(channel)
                    flash(request, "ok", f"Posted the self-role panel in #{channel.name}.")
                except ValueError as err:
                    flash(request, "error", str(err))
                except discord.HTTPException:
                    flash(request, "error", "I couldn't post in that channel. Check my permissions.")
        return RedirectResponse(f"/servers/{guild_id}/selfroles", status_code=303)

    @app.get("/servers/{guild_id}/alts", response_class=HTMLResponse)
    async def alts_get(request: Request, guild_id: int, q: str = "", risk: str = "", page: int = 1):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        cfg = await db.get_alt_config(guild.id)
        log_id = await db.get_feature_channel(guild.id, "alts")
        whitelist = await db.list_alt_whitelist(guild.id)
        whitelist_ids = {int(r["user_id"]) for r in whitelist}
        q_role = int(cfg["quarantine_role_id"]) if cfg and cfg["quarantine_role_id"] else None
        verdict = risk if risk in {"High risk", "Medium risk", "Low risk"} else None
        per_page = 20
        page = max(1, int(page or 1))
        rows, total = await db.search_alt_flags(
            guild.id, verdict=verdict, query=(q.strip() or None), limit=per_page, offset=(page - 1) * per_page
        )
        flags = [_flag_display(guild, row, whitelist_ids, q_role) for row in rows]
        pages = max(1, (total + per_page - 1) // per_page)
        return render(
            request,
            "alts.html",
            **_nav(guild, "alts"),
            cfg=cfg,
            log_id=log_id,
            actions=ALT_ACTIONS,
            assignable=_roles(guild),
            grouped=_grouped_channels(guild),
            whitelist=whitelist,
            flags=flags,
            log_q=q,
            log_risk=risk,
            page=page,
            pages=pages,
            total_flags=total,
            member_name=lambda uid: _member_name(guild, uid),
            fmt_time=lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts or 0))) if ts else "—",
        )

    @app.post("/servers/{guild_id}/alts")
    async def alts_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild and user
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "save")
        if action == "save":
            enabled = 1 if form.get("enabled") == "1" else 0
            try:
                min_age = int(form.get("min_age_days") or 7)
            except ValueError:
                min_age = 7
            min_age = max(0, min(365, min_age))
            act = str(form.get("alt_action") or "log")
            if act not in ALT_ACTIONS:
                act = "log"
            role_raw = str(form.get("quarantine_role_id") or "").strip()
            role_id = int(role_raw) if role_raw.isdigit() else None
            if role_id and guild.get_role(role_id) not in _roles(guild) and role_id:
                role_id = None
            log_raw = str(form.get("log_channel_id") or "").strip()
            log_id = int(log_raw) if log_raw.isdigit() else None
            valid = {c.id for c in _text_channels(guild)}
            if log_id not in valid:
                log_id = None
            await db.set_alt_config(
                guild.id,
                enabled=enabled,
                min_age_days=min_age,
                action=act,
                quarantine_role_id=role_id,
            )
            await db.set_feature_channel(guild.id, "alts", log_id)
            flash(request, "ok", "Alt detection settings saved. They apply to new joins immediately.")
        elif action == "whitelist_add":
            raw = str(form.get("user_id") or "").strip()
            if not raw.isdigit():
                flash(request, "error", "Enter a numeric Discord user ID.")
            elif await db.add_alt_whitelist(guild.id, int(raw), int(user["id"])):
                flash(request, "ok", f"Whitelisted {raw}.")
            else:
                flash(request, "error", "That user is already whitelisted.")
        elif action == "whitelist_remove":
            raw = str(form.get("user_id") or "").strip()
            if raw.isdigit() and await db.remove_alt_whitelist(guild.id, int(raw)):
                flash(request, "ok", "Removed from the whitelist.")
            else:
                flash(request, "error", "That user was not on the whitelist.")
        elif action == "log_action":
            review = str(form.get("review") or "")
            try:
                flag_id = int(form.get("flag_id") or 0)
            except ValueError:
                flag_id = 0
            flag = await db.get_alt_flag(flag_id, guild.id) if flag_id else None
            actor = guild.get_member(int(user["id"]))
            if actor is None:
                try:
                    actor = await guild.fetch_member(int(user["id"]))
                except discord.HTTPException:
                    actor = None
            if flag is None:
                flash(request, "error", "That log entry was not found.")
            elif actor is None:
                flash(request, "error", "I couldn't find you in this server, so I can't apply that action.")
            else:
                from cogs.altdetect import apply_alt_review
                ok, summary, _status = await apply_alt_review(
                    _bot(request),
                    guild,
                    review,
                    int(flag["user_id"]),
                    actor=actor,
                    flag_id=int(flag["id"]),
                )
                flash(request, "ok" if ok else "error", summary)
            q = str(form.get("q") or "")
            risk = str(form.get("risk") or "")
            page = str(form.get("page") or "1")
            return RedirectResponse(
                f"/servers/{guild_id}/alts?q={quote(q)}&risk={quote(risk)}&page={quote(page)}",
                status_code=303,
            )
        return RedirectResponse(f"/servers/{guild_id}/alts", status_code=303)

    @app.get("/servers/{guild_id}/welcome", response_class=HTMLResponse)
    async def welcome_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        settings = await db.get_settings(guild.id)
        channel_id = await db.get_feature_channel(guild.id, "welcome")
        message = (settings["welcome_message"] if settings and settings["welcome_message"] else DEFAULT_WELCOME)
        return render(
            request,
            "welcome.html",
            **_nav(guild, "welcome"),
            channel_id=channel_id,
            message=message,
            grouped=_grouped_channels(guild),
        )

    @app.post("/servers/{guild_id}/welcome")
    async def welcome_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild and user
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "save")
        if action == "save":
            raw = str(form.get("channel_id") or "").strip()
            valid = {c.id for c in _text_channels(guild)}
            channel_id = int(raw) if raw.isdigit() and int(raw) in valid else None
            message = (str(form.get("message") or "").strip() or DEFAULT_WELCOME)[:1800]
            await db.set_feature_channel(guild.id, "welcome", channel_id)
            await db.update_settings(guild.id, welcome_message=message)
            flash(request, "ok", "Welcome settings saved. They apply to the next join.")
        elif action == "test":
            member = guild.get_member(int(user["id"])) or guild.me
            cog = _bot(request).get_cog("Welcome")
            if member is None or cog is None:
                flash(request, "error", "I couldn't find a member to preview as.")
            else:
                try:
                    channel = await cog.post_test(guild, member)
                    flash(request, "ok", f"Posted a test welcome in #{channel.name}.")
                except ValueError as err:
                    flash(request, "error", str(err))
                except discord.HTTPException:
                    flash(request, "error", "I couldn't post the test welcome. Check my permissions.")
        return RedirectResponse(f"/servers/{guild_id}/welcome", status_code=303)

    @app.get("/servers/{guild_id}/games", response_class=HTMLResponse)
    async def games_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        from cogs.arcade import MENU_GAMES
        db = _bot(request).db
        disabled = await db.disabled_game_keys(guild.id)
        channels = await db.get_feature_channels(guild.id, "games")
        return render(
            request,
            "games.html",
            **_nav(guild, "games"),
            menu_games=MENU_GAMES,
            disabled=disabled,
            game_channels=set(channels),
            grouped=_grouped_channels(guild),
        )

    @app.post("/servers/{guild_id}/games")
    async def games_post(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        from cogs.arcade import MENU_GAMES
        form = await _form(request)
        db = _bot(request).db
        enabled = {str(v) for v in form.getlist("enabled")}
        for key, _emoji, _title, _blurb in MENU_GAMES:
            await db.set_game_enabled(guild.id, key, key in enabled)
        valid = {c.id for c in _text_channels(guild)}
        ids = [int(v) for v in form.getlist("games_channel") if str(v).isdigit() and int(v) in valid]
        await db.set_feature_channels(guild.id, "games", ids)
        flash(request, "ok", "Game settings saved. They apply to the next game start.")
        return RedirectResponse(f"/servers/{guild_id}/games", status_code=303)

    @app.get("/servers/{guild_id}/moderation", response_class=HTMLResponse)
    async def moderation(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        logs = await db.recent_mod_log(guild.id, 40)
        warns = await db.recent_warnings_guild(guild.id, 40)
        return render(
            request,
            "moderation.html",
            **_nav(guild, "moderation"),
            logs=logs,
            warns=warns,
            member_name=lambda uid: _member_name(guild, uid),
            fmt_time=lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts or 0))),
        )

    from dashboard.billing_routes import register_billing_routes
    register_billing_routes(app)
