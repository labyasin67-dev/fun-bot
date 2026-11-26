"""Audit Logs page: pick a log channel and which events are logged."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from cogs.audit_logs import EVENT_KEYS, grouped_events


def register_audit_routes(app: FastAPI) -> None:
    @app.get("/servers/{guild_id}/auditlogs", response_class=HTMLResponse)
    async def auditlogs_get(request: Request, guild_id: int):
        from dashboard.routes import _bot, _grouped_channels, _guild_or_redirect, _nav, render

        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        cog = _bot(request).get_cog("AuditLogs")
        channel_id, events = cog.get_config(guild.id) if cog else (None, set())
        me = guild.me
        return render(
            request,
            "auditlogs.html",
            **_nav(guild, "auditlogs"),
            audit_ready=cog is not None,
            audit_channel_id=channel_id,
            audit_events=events,
            audit_groups=grouped_events(),
            grouped=_grouped_channels(guild),
            can_view_audit=bool(me and me.guild_permissions.view_audit_log),
        )

    @app.post("/servers/{guild_id}/auditlogs")
    async def auditlogs_post(request: Request, guild_id: int):
        from dashboard.routes import _bot, _form, _guild_or_redirect, _text_channels, flash

        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        back = RedirectResponse(f"/servers/{guild_id}/auditlogs", status_code=303)
        cog = _bot(request).get_cog("AuditLogs")
        if cog is None:
            flash(request, "error", "Audit logs are still starting. Try again in a moment.")
            return back
        action = str(form.get("action") or "save")
        if action == "save":
            raw = str(form.get("channel_id") or "").strip()
            valid = {c.id for c in _text_channels(guild)}
            channel_id = int(raw) if raw.isdigit() and int(raw) in valid else None
            chosen = {k for k in EVENT_KEYS if form.get(f"ev_{k}") == "1"}
            await cog.set_channel(guild.id, channel_id)
            await cog.set_events(guild.id, chosen)
            if channel_id is None:
                flash(request, "ok", "Saved. No log channel is set, so nothing is logged yet.")
            elif not chosen:
                flash(request, "ok", "Log channel saved. Tick the events you want to log.")
            else:
                flash(request, "ok", f"Saved. {len(chosen)} event{'s' if len(chosen) != 1 else ''} will be logged.")
        elif action == "all":
            await cog.set_events(guild.id, set(EVENT_KEYS))
            flash(request, "ok", "All events turned on.")
        elif action == "none":
            await cog.set_events(guild.id, set())
            flash(request, "ok", "All events turned off.")
        elif action == "test":
            if await cog.send_test(guild):
                flash(request, "ok", "Test message sent to the log channel.")
            else:
                flash(request, "error", "Pick and save a log channel first (the bot needs Send Messages and Embed Links there).")
        return back
