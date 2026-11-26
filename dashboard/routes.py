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
from cogs.moderation import (
    DEFAULT_BAN_ANNOUNCE,
    DEFAULT_BAN_DM,
    ModerationActionError,
    perform_ban,
    perform_clearwarns,
    perform_kick,
    perform_timeout,
    perform_unban,
    perform_warn,
)
from cogs.welcome import DEFAULT_LEAVE, DEFAULT_WELCOME
from cogs.customroles import colour_hex, colour_hex_optional, edit_role_colours, guild_has_gradients, parse_hex_colour, remove_stored_custom_role, restrict_user
from dashboard.creator_routes import creator_context
from dashboard import DEFAULT_CLIENT_ID, INVITE_PERMISSIONS, ROOT, client_id, oauth_configured
from site_pages import CONTACT_KEY, load_site_page, render_page_body
from utils import level_from_xp, parse_user_id, resolve_member
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


def _row_get(row, key: str, default=None):
    if row is None:
        return default
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None else val


def _form_channel(form, name: str, valid: set[int]) -> int | None:
    value = str(form.get(name) or "").strip()
    return int(value) if value.isdigit() and int(value) in valid else None


def _form_flag(form, name: str) -> int:
    return 1 if str(form.get(name) or "") in {"1", "on", "true", "yes"} else 0


def _resolve_target(guild: discord.Guild, raw: str) -> tuple[discord.Member | None, int | None]:
    member = resolve_member(guild, raw)
    if member is not None:
        return member, member.id
    return None, parse_user_id(raw)


async def _dashboard_xp_change(bot, cog, guild: discord.Guild, user: dict, user_id: int, delta: int) -> dict:
    """Dashboard XP add/remove using the same database calls and limits as .addxp / .removexp."""
    amount = abs(int(delta))
    if amount <= 0 or amount > 1_000_000:
        raise ValueError("Amount must be between 1 and 1,000,000.")
    member = guild.get_member(user_id)
    if member is not None and member.bot:
        raise ValueError("Bots don't earn XP.")
    if delta > 0:
        old, new = await bot.db.add_xp(guild.id, user_id, amount)
        if new > old and member is not None:
            await cog._handle_level_up(guild, member, None, old, new)
        title, colour_name = "XP added", "SUCCESS"
    else:
        old_xp = int((await bot.db.ensure_member(guild.id, user_id))["xp"])
        old, new = await bot.db.set_xp(guild.id, user_id, max(0, old_xp - amount))
        title, colour_name = "XP removed", "WARNING"
    from cogs.channels import post_modlog
    import utils as _utils
    target = member.mention if member is not None else f"<@{user_id}>"
    await post_modlog(
        bot,
        guild,
        title,
        f"**Staff:** Dashboard ({user.get('username', user.get('id'))})\n**Target:** {target} (`{user_id}`)\n**Old:** {old:,} → **New:** {new:,}",
        color=getattr(_utils, colour_name),
    )
    return {"old_xp": old, "new_xp": new, "level": level_from_xp(new)}


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



def _is_owner(request: Request, user) -> bool:
    bot = _bot(request)
    from premium import owner_ids_from_env
    ids = owner_ids_from_env()
    if bot is not None:
        ids |= set(getattr(bot, "app_owner_ids", None) or set())
    try:
        return bool(user and int(user["id"]) in ids)
    except (TypeError, ValueError):
        return False


def _categories(guild: discord.Guild) -> list[discord.CategoryChannel]:
    return sorted(guild.categories, key=lambda c: (c.position, c.id))


def _staff_person(name: str | None, avatar: str | None, user_id: int | None, guild: discord.Guild | None = None) -> dict | None:
    if not user_id and not name:
        return None
    label = name or (guild and _member_name(guild, user_id) if guild else None) or (f"ID {user_id}" if user_id else "Unknown")
    return {"name": label, "avatar": avatar or "", "id": user_id}


def _fmt_ts(ts) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))


def register_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if current_user(request):
            return RedirectResponse("/servers", status_code=302)
        return render(request, "home.html")

    async def _public_page(request: Request, key: str, title: str):
        bot = _bot(request)
        db = getattr(bot, "db", None) if bot is not None else None
        body = await load_site_page(db, key)
        return render(
            request,
            "site_page.html",
            page_title=title,
            body_html=render_page_body(body),
        )

    @app.get("/contact", response_class=HTMLResponse)
    async def contact_page(request: Request):
        return await _public_page(request, CONTACT_KEY, "Contact Us")

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
            xp = int(row["xp"])
            board.append({
                "rank": i,
                "name": str(member) if member else f"ID {row['user_id']}",
                "xp": xp,
                "level": level_from_xp(xp),
            })
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
        elif action == "xp":
            raw = str(form.get("member") or "")
            op = str(form.get("xp_op") or "add")
            try:
                amount = int(form.get("amount") or 0)
            except ValueError:
                amount = 0
            if amount <= 0:
                flash(request, "error", "Enter a positive XP amount.")
            else:
                member, user_id = _resolve_target(guild, raw)
                if user_id is None:
                    flash(request, "error", "I couldn't find that member. Use a user ID, mention, or a unique username.")
                else:
                    delta = amount if op != "remove" else -amount
                    cog = _bot(request).get_cog("Leveling")
                    if cog is None:
                        flash(request, "error", "The leveling module is still starting. Try again in a moment.")
                    else:
                        try:
                            result = await _dashboard_xp_change(_bot(request), cog, guild, _user, user_id, delta)
                        except ValueError as err:
                            flash(request, "error", str(err))
                        else:
                            label = member.display_name if member else f"ID {user_id}"
                            verb = "Added" if delta > 0 else "Removed"
                            flash(
                                request,
                                "ok",
                                f"{verb} {abs(delta):,} XP {'to' if delta > 0 else 'from'} {label}. "
                                f"They now have {result['new_xp']:,} XP (level {result['level']}).",
                            )
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
            leave_enabled=int(_row_get(settings, "leave_enabled", 0) or 0),
            leave_channel_id=_row_get(settings, "leave_channel_id"),
            leave_message=_row_get(settings, "leave_message") or DEFAULT_LEAVE,
            ban_dm_enabled=int(_row_get(settings, "ban_dm_enabled", 0) or 0),
            ban_dm_message=_row_get(settings, "ban_dm_message") or DEFAULT_BAN_DM,
            ban_announce_enabled=int(_row_get(settings, "ban_announce_enabled", 0) or 0),
            ban_announce_channel_id=_row_get(settings, "ban_announce_channel_id"),
            ban_announce_message=_row_get(settings, "ban_announce_message") or DEFAULT_BAN_ANNOUNCE,
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
            valid = {c.id for c in _text_channels(guild)}
            channel_id = _form_channel(form, "channel_id", valid)
            message = (str(form.get("message") or "").strip() or DEFAULT_WELCOME)[:1800]
            await db.set_feature_channel(guild.id, "welcome", channel_id)
            await db.update_settings(
                guild.id,
                welcome_message=message,
                leave_enabled=_form_flag(form, "leave_enabled"),
                leave_channel_id=_form_channel(form, "leave_channel_id", valid),
                leave_message=(str(form.get("leave_message") or "").strip() or DEFAULT_LEAVE)[:1800],
                ban_dm_enabled=_form_flag(form, "ban_dm_enabled"),
                ban_dm_message=(str(form.get("ban_dm_message") or "").strip() or DEFAULT_BAN_DM)[:1800],
                ban_announce_enabled=_form_flag(form, "ban_announce_enabled"),
                ban_announce_channel_id=_form_channel(form, "ban_announce_channel_id", valid),
                ban_announce_message=(str(form.get("ban_announce_message") or "").strip() or DEFAULT_BAN_ANNOUNCE)[:1800],
            )
            flash(request, "ok", "Welcome, leave and ban messages saved. They apply to the next event.")
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

    @app.get("/servers/{guild_id}/youtube", response_class=HTMLResponse)
    async def youtube_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        settings = await db.get_youtube_settings(guild.id)
        return render(
            request,
            "youtube.html",
            **_nav(guild, "youtube"),
            enabled=int(settings["enabled"] or 0),
            channel_id=settings["channel_id"],
            **await creator_context(request, guild),
        )

    @app.post("/servers/{guild_id}/youtube")
    async def youtube_post(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        redirect = f"/servers/{guild_id}/youtube"
        if action == "settings":
            enabled = 1 if str(form.get("enabled") or "") == "1" else 0
            await db.set_youtube_settings(guild.id, enabled=enabled)
            flash(request, "ok", "YouTube settings saved.")
        return RedirectResponse(redirect, status_code=303)

    async def _moderation_page(request: Request, guild, warns_query: str = ""):
        db = _bot(request).db
        logs = await db.recent_mod_log(guild.id, 40)
        warns = await db.recent_warnings_guild(guild.id, 40)
        member_warns = []
        warns_target = ""
        warns_user_id = None
        if warns_query:
            member, user_id = _resolve_target(guild, warns_query)
            if user_id is None:
                flash(request, "error", "I couldn't find that member. Use a user ID, mention, or a unique username.")
            else:
                warns_user_id = user_id
                warns_target = member.display_name if member else f"ID {user_id}"
                member_warns = await db.get_warnings(guild.id, user_id)
        return render(
            request,
            "moderation.html",
            **_nav(guild, "moderation"),
            logs=logs,
            warns=warns,
            member_warns=member_warns,
            warns_query=warns_query,
            warns_target=warns_target,
            warns_user_id=warns_user_id,
            modlog_id=await db.get_feature_channel(guild.id, "modlog"),
            grouped=_grouped_channels(guild),
            member_name=lambda uid: _member_name(guild, uid),
            fmt_time=lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts or 0))),
        )

    @app.get("/servers/{guild_id}/moderation", response_class=HTMLResponse)
    async def moderation(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        return await _moderation_page(request, guild, str(request.query_params.get("warns") or ""))

    @app.post("/servers/{guild_id}/moderation")
    async def moderation_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild and user
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        redirect = f"/servers/{guild_id}/moderation"
        if action == "settings":
            valid = {c.id for c in _text_channels(guild)}
            await db.set_feature_channel(guild.id, "modlog", _form_channel(form, "modlog_channel", valid))
            flash(request, "ok", "Mod-log channel updated.")
            return RedirectResponse(redirect, status_code=303)
        actor = guild.get_member(int(user["id"]))
        if actor is None:
            flash(request, "error", "I can't see you in this server, so I can't check the role list.")
            return RedirectResponse(redirect, status_code=303)
        if action == "clearwarns":
            try:
                user_id = int(form.get("user_id") or 0)
            except ValueError:
                user_id = 0
            if not user_id:
                flash(request, "error", "Missing member ID.")
            else:
                label = _member_name(guild, user_id)
                summary = await perform_clearwarns(_bot(request), guild, label, user_id)
                flash(request, "ok", summary)
            return RedirectResponse(f"{redirect}?warns={user_id}", status_code=303)
        if action == "act":
            raw = str(form.get("member") or "")
            member, user_id = _resolve_target(guild, raw)
            reason = str(form.get("reason") or "").strip() or None
            mod_action = str(form.get("mod_action") or "")
            duration = str(form.get("duration") or "").strip()
            try:
                if mod_action == "unban":
                    if user_id is None:
                        raise ModerationActionError("Unban needs a numeric Discord user ID.")
                    summary = await perform_unban(_bot(request), guild, actor, user_id)
                else:
                    if member is None:
                        raise ModerationActionError("I couldn't find that member in this server. Use a user ID, mention, or a unique username.")
                    if mod_action == "ban":
                        cog = _bot(request).get_cog("Moderation")
                        recent = getattr(cog, "_recent_bot_bans", None)
                        _dm_ok, summary = await perform_ban(
                            _bot(request), guild, actor, member, reason, recent_bot_bans=recent
                        )
                    elif mod_action == "kick":
                        summary = await perform_kick(_bot(request), guild, actor, member, reason)
                    elif mod_action == "timeout":
                        summary = await perform_timeout(_bot(request), guild, actor, member, duration, reason)
                    elif mod_action == "warn":
                        summary = await perform_warn(_bot(request), guild, actor, member, reason)
                    else:
                        raise ModerationActionError("Choose a valid action.")
            except ModerationActionError as err:
                flash(request, "error", str(err))
            except discord.HTTPException:
                flash(request, "error", "Discord rejected that action. Check my permissions and try again.")
            else:
                flash(request, "ok", summary)
            return RedirectResponse(redirect, status_code=303)
        return RedirectResponse(redirect, status_code=303)


    @app.get("/servers/{guild_id}/customroles", response_class=HTMLResponse)
    async def customroles_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        settings = await db.get_customrole_settings(guild.id)
        role_rows = []
        for row in await db.list_custom_roles(guild.id):
            role = guild.get_role(int(row["role_id"]))
            created = float(row["created_at"] or 0)
            holder_id = int(row["holder_id"]) if row["holder_id"] else int(row["user_id"])
            role_rows.append(
                {
                    "user_id": int(row["user_id"]),
                    "holder_id": holder_id,
                    "holder_name": _member_name(guild, holder_id),
                    "role_id": int(row["role_id"]),
                    "role": role,
                    "member_name": _member_name(guild, int(row["user_id"])),
                    "colour": colour_hex(role.colour) if role else "",
                    "colour2": (
                        colour_hex(role.secondary_colour)
                        if role and getattr(role, "secondary_colour", None) is not None
                        else colour_hex_optional(row["secondary_colour"])
                    ),
                    "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(created)) if created else "—",
                }
            )
        restrictions = []
        for row in await db.list_custom_role_restrictions(guild.id):
            when = float(row["at"] or 0)
            by_id = int(row["by"]) if row["by"] else None
            restrictions.append(
                {
                    "user_id": int(row["user_id"]),
                    "member_name": _member_name(guild, int(row["user_id"])),
                    "reason": row["reason"] or "",
                    "by_name": _member_name(guild, by_id) if by_id else "Automatic",
                    "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "—",
                }
            )
        give_blocks = []
        for row in await db.list_custom_role_give_blocks(guild.id):
            when = float(row["at"] or 0)
            by_id = int(row["by"]) if row["by"] else None
            give_blocks.append(
                {
                    "user_id": int(row["user_id"]),
                    "member_name": _member_name(guild, int(row["user_id"])),
                    "reason": row["reason"] or "",
                    "by_name": _member_name(guild, by_id) if by_id else "Automatic",
                    "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "—",
                }
            )
        anchor_id = int(settings["anchor_role_id"]) if settings["anchor_role_id"] else None
        return render(
            request,
            "customroles.html",
            **_nav(guild, "customroles"),
            enabled=int(settings["enabled"] or 0),
            min_level=int(settings["min_level"] or 0),
            give_enabled=int(settings["give_enabled"] if "give_enabled" in settings.keys() else 1),
            anchor_role_id=anchor_id,
            assignable=_roles(guild),
            roles=role_rows,
            restrictions=restrictions,
            give_blocks=give_blocks,
            gradients_supported=guild_has_gradients(guild),
        )

    @app.post("/servers/{guild_id}/customroles")
    async def customroles_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        redirect = f"/servers/{guild_id}/customroles"
        actor_id = int(user["id"]) if user and user.get("id") else None
        if action == "settings":
            enabled = 1 if str(form.get("enabled") or "") == "1" else 0
            try:
                min_level = int(str(form.get("min_level") or "10"))
            except ValueError:
                flash(request, "error", "Minimum level must be a number.")
                return RedirectResponse(redirect, status_code=303)
            if min_level < 0 or min_level > 1000:
                flash(request, "error", "Minimum level must be between 0 and 1000.")
                return RedirectResponse(redirect, status_code=303)
            valid_roles = {r.id for r in _roles(guild)}
            raw_anchor = str(form.get("anchor_role_id") or "").strip()
            anchor = int(raw_anchor) if raw_anchor.isdigit() and int(raw_anchor) in valid_roles else None
            give_enabled = 1 if str(form.get("give_enabled") or "") == "1" else 0
            await db.set_customrole_settings(
                guild.id, enabled=enabled, min_level=min_level, anchor_role_id=anchor, give_enabled=give_enabled
            )
            flash(request, "ok", "Custom role settings saved.")
            return RedirectResponse(redirect, status_code=303)
        raw = str(form.get("user_id") or "")
        user_id = parse_user_id(raw)
        if user_id is None and raw.strip().isdigit() and len(raw.strip()) >= 15:
            user_id = int(raw.strip())
        if action in {"remove", "restrict", "unrestrict", "give_block", "give_unblock"} and not user_id:
            flash(request, "error", "Enter a valid Discord user ID.")
            return RedirectResponse(redirect, status_code=303)
        if action == "remove":
            removed = await remove_stored_custom_role(
                _bot(request), guild, user_id, reason=f"Removed from dashboard by {actor_id}"
            )
            if removed is None:
                flash(request, "error", "That member doesn't have a custom role.")
            else:
                flash(request, "ok", f"Removed the custom role from {_member_name(guild, user_id)}.")
            return RedirectResponse(redirect, status_code=303)
        if action == "restrict":
            reason = str(form.get("reason") or "").strip() or "Restricted from the dashboard"
            await restrict_user(
                _bot(request),
                guild,
                user_id,
                reason=reason,
                by=actor_id,
                delete_role=True,
            )
            flash(request, "ok", f"{_member_name(guild, user_id)} is restricted from custom roles.")
            return RedirectResponse(redirect, status_code=303)
        if action == "unrestrict":
            ok = await db.unrestrict_custom_role_user(guild.id, user_id)
            if ok:
                flash(request, "ok", f"{_member_name(guild, user_id)} can create a custom role again.")
            else:
                flash(request, "error", "That member isn't restricted.")
            return RedirectResponse(redirect, status_code=303)
        if action == "give_block":
            reason = str(form.get("reason") or "").strip() or None
            await db.block_custom_role_give(guild.id, user_id, reason=reason, by=actor_id)
            flash(request, "ok", f"{_member_name(guild, user_id)} is blocked from .role give.")
            return RedirectResponse(redirect, status_code=303)
        if action == "give_unblock":
            ok = await db.unblock_custom_role_give(guild.id, user_id)
            if ok:
                flash(request, "ok", f"{_member_name(guild, user_id)} can use .role give again.")
            else:
                flash(request, "error", "That member isn't blocked from .role give.")
            return RedirectResponse(redirect, status_code=303)
        if action == "colours":
            if not user_id:
                flash(request, "error", "Missing member for colour edit.")
                return RedirectResponse(redirect, status_code=303)
            row = await db.get_custom_role(guild.id, user_id)
            if row is None:
                flash(request, "error", "That member doesn't have a custom role.")
                return RedirectResponse(redirect, status_code=303)
            role = guild.get_role(int(row["role_id"]))
            if role is None:
                flash(request, "error", "That custom role no longer exists.")
                return RedirectResponse(redirect, status_code=303)
            primary = parse_hex_colour(str(form.get("colour") or ""))
            raw2 = str(form.get("colour2") or "").strip()
            secondary = parse_hex_colour(raw2) if raw2 else None
            if primary is None:
                flash(request, "error", "Enter a valid 6-digit hex colour, such as #ff0000.")
                return RedirectResponse(redirect, status_code=303)
            if raw2 and secondary is None:
                flash(request, "error", "The second colour must also be a 6-digit hex, such as #0000ff, or left blank.")
                return RedirectResponse(redirect, status_code=303)
            try:
                used = await edit_role_colours(
                    role,
                    primary=primary,
                    secondary=secondary,
                    reason=f"Colours edited from the dashboard by {actor_id}",
                )
            except Exception:
                flash(request, "error", "Couldn't update that role's colours. Check the bot's Manage Roles permission and role order.")
                return RedirectResponse(redirect, status_code=303)
            await db.set_custom_role_secondary(
                guild.id, user_id, secondary.value if used and secondary is not None else None
            )
            if secondary is not None and not used:
                flash(request, "ok", f"Updated the colour of {_member_name(guild, user_id)}'s role. This server doesn't have enhanced role colours, so only the first colour was applied.")
            elif used and secondary is not None:
                flash(request, "ok", f"Updated the gradient on {_member_name(guild, user_id)}'s role.")
            else:
                flash(request, "ok", f"Updated the colour of {_member_name(guild, user_id)}'s role.")
            return RedirectResponse(redirect, status_code=303)
        return RedirectResponse(redirect, status_code=303)


    @app.get("/servers/{guild_id}/reports", response_class=HTMLResponse)
    async def reports_get(request: Request, guild_id: int, open: int = 1, approved: int = 1, denied: int = 1, closed: int = 1):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        db = _bot(request).db
        settings = await db.get_report_settings(guild.id)
        owner_view = _is_owner(request, user)
        per = 50

        async def section(status: str, page: int):
            page = max(1, int(page or 1))
            total = await db.count_reports(guild.id, status)
            pages = max(1, (total + per - 1) // per)
            page = min(page, pages)
            rows = await db.list_report_tickets(guild.id, status=status, limit=per, offset=(page - 1) * per)
            notes_map = {}
            if owner_view:
                notes_map = await db.list_report_notes_for([int(r["id"]) for r in rows])
            items = []
            for row in rows:
                notes = []
                for note in notes_map.get(int(row["id"]), []):
                    notes.append(
                        {
                            "author": _staff_person(note["author_name"], note["author_avatar"], note["author_id"], guild),
                            "body": note["body"],
                            "at": _fmt_ts(note["created_at"]),
                        }
                    )
                items.append(
                    {
                        "id": int(row["id"]),
                        "reason": row["reason"] or "",
                        "message_link": row["message_link"] or "",
                        "created": _fmt_ts(row["created_at"]),
                        "reporter": _staff_person(row["reporter_name"], row["reporter_avatar"], row["reporter_id"], guild),
                        "reported": _staff_person(row["reported_name"], row["reported_avatar"], row["reported_user_id"], guild) if row["reported_user_id"] or row["reported_name"] else None,
                        "claimed": _staff_person(row["claimed_by_name"], row["claimed_by_avatar"], row["claimed_by"], guild) if row["claimed_by"] else None,
                        "claimed_at": _fmt_ts(row["claimed_at"]),
                        "decided": _staff_person(row["decided_by_name"], row["decided_by_avatar"], row["decided_by"], guild) if row["decided_by"] else None,
                        "decided_at": _fmt_ts(row["decided_at"]),
                        "decision_reason": row["decision_reason"] or "",
                        "notes": notes,
                    }
                )
            return items, total, page, pages

        open_items, open_count, open_page, open_pages = await section("open", open)
        approved_items, approved_count, approved_page, approved_pages = await section("approved", approved)
        denied_items, denied_count, denied_page, denied_pages = await section("denied", denied)
        closed_items, closed_count, closed_page, closed_pages = await section("closed", closed)
        blocks = []
        for row in await db.list_report_blocks(guild.id):
            blocks.append(
                {
                    "user_id": int(row["user_id"]),
                    "name": _member_name(guild, int(row["user_id"])),
                    "reason": row["reason"] or "",
                }
            )
        return render(
            request,
            "reports.html",
            **_nav(guild, "reports"),
            enabled=int(settings["enabled"] or 0),
            mode=str(settings["mode"] or "channel"),
            alert_channel_id=int(settings["alert_channel_id"]) if settings["alert_channel_id"] else None,
            closed_channel_id=int(settings["closed_channel_id"]) if settings["closed_channel_id"] else None,
            category_id=int(settings["category_id"]) if settings["category_id"] else None,
            staff_role_id=int(settings["staff_role_id"]) if settings["staff_role_id"] else None,
            grouped=_grouped_channels(guild),
            categories=_categories(guild),
            assignable=_roles(guild),
            owner_view=owner_view,
            open_items=open_items, open_count=open_count, open_page=open_page, open_pages=open_pages,
            approved_items=approved_items, approved_count=approved_count, approved_page=approved_page, approved_pages=approved_pages,
            denied_items=denied_items, denied_count=denied_count, denied_page=denied_page, denied_pages=denied_pages,
            closed_items=closed_items, closed_count=closed_count, closed_page=closed_page, closed_pages=closed_pages,
            blocks=blocks,
        )

    @app.post("/servers/{guild_id}/reports")
    async def reports_post(request: Request, guild_id: int):
        redir, guild, user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        db = _bot(request).db
        action = str(form.get("action") or "")
        redirect = f"/servers/{guild_id}/reports"
        if action == "settings":
            enabled = 1 if str(form.get("enabled") or "") == "1" else 0
            mode = str(form.get("mode") or "channel")
            if mode not in {"channel", "ticket"}:
                mode = "channel"
            valid_ch = {c.id for c in _text_channels(guild)}
            valid_cats = {c.id for c in _categories(guild)}
            valid_roles = {r.id for r in _roles(guild)}
            raw_alert = str(form.get("alert_channel_id") or "").strip()
            raw_closed = str(form.get("closed_channel_id") or "").strip()
            raw_cat = str(form.get("category_id") or "").strip()
            raw_role = str(form.get("staff_role_id") or "").strip()
            alert = int(raw_alert) if raw_alert.isdigit() and int(raw_alert) in valid_ch else None
            closed = int(raw_closed) if raw_closed.isdigit() and int(raw_closed) in valid_ch else None
            category = int(raw_cat) if raw_cat.isdigit() and int(raw_cat) in valid_cats else None
            role = int(raw_role) if raw_role.isdigit() and int(raw_role) in valid_roles else None
            await db.set_report_settings(
                guild.id,
                enabled=enabled,
                mode=mode,
                alert_channel_id=alert,
                closed_channel_id=closed,
                category_id=category,
                staff_role_id=role,
            )
            flash(request, "ok", "Report settings saved.")
            return RedirectResponse(redirect, status_code=303)
        raw_tid = str(form.get("ticket_id") or "").strip()
        ticket_id = int(raw_tid) if raw_tid.isdigit() else 0
        actor_id = int(user["id"]) if user and user.get("id") else 0
        actor_name = (user or {}).get("username") or (f"ID {actor_id}" if actor_id else "Staff")
        actor_avatar = avatar_url(user) if user else ""
        if action in {"approve", "deny"}:
            if not ticket_id:
                flash(request, "error", "Missing report ID.")
                return RedirectResponse(redirect, status_code=303)
            reason = str(form.get("reason") or "").strip() or None
            cog = _bot(request).get_cog("Reports")
            if cog is None:
                flash(request, "error", "The reports module isn't loaded.")
                return RedirectResponse(redirect, status_code=303)
            err = await cog.apply_decision(
                guild,
                ticket_id,
                status="approved" if action == "approve" else "denied",
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar=actor_avatar,
                reason=reason,
            )
            if err:
                flash(request, "error", err)
            else:
                flash(request, "ok", f"Report #{ticket_id} was {action}d. The reporter was notified if I could reach them.")
            return RedirectResponse(redirect, status_code=303)
        if action == "note":
            if not _is_owner(request, user):
                flash(request, "error", "Only the bot owner can add or view private comments.")
                return RedirectResponse(redirect, status_code=303)
            if not ticket_id:
                flash(request, "error", "Missing report ID.")
                return RedirectResponse(redirect, status_code=303)
            body = str(form.get("body") or "").strip()
            cog = _bot(request).get_cog("Reports")
            if cog is None:
                err = await db.add_report_note(
                    ticket_id, guild.id, author_id=actor_id, author_name=actor_name, author_avatar=actor_avatar, body=body
                )
                flash(request, "ok" if body else "error", "Comment saved." if body else "Write a comment first.")
            else:
                err = await cog.add_private_note(
                    guild, ticket_id, author_id=actor_id, author_name=actor_name, author_avatar=actor_avatar, body=body
                )
                if err:
                    flash(request, "error", err)
                else:
                    flash(request, "ok", "Private comment saved. Only you can see it on this page.")
            return RedirectResponse(redirect, status_code=303)
        if action in {"block", "unblock"}:
            raw = str(form.get("user_id") or "")
            user_id = parse_user_id(raw)
            if not user_id:
                flash(request, "error", "Enter a valid Discord user ID.")
                return RedirectResponse(redirect, status_code=303)
            if action == "block":
                reason = str(form.get("reason") or "").strip() or None
                await db.block_reporter(guild.id, user_id, reason=reason, by=actor_id)
                flash(request, "ok", f"{_member_name(guild, user_id)} is blocked from sending reports.")
            else:
                ok = await db.unblock_reporter(guild.id, user_id)
                flash(request, "ok" if ok else "error", f"{_member_name(guild, user_id)} can report again." if ok else "That member isn't blocked.")
            return RedirectResponse(redirect, status_code=303)
        return RedirectResponse(redirect, status_code=303)

    from dashboard.billing_routes import register_billing_routes
    register_billing_routes(app)

    from dashboard.creator_routes import register_creator_routes
    register_creator_routes(app)

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy(request: Request):
        return render(request, "privacy.html")

    @app.get("/terms", response_class=HTMLResponse)
    async def terms(request: Request):
        return render(request, "terms.html")
