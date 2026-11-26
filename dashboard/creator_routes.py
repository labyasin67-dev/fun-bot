"""Creator Integration page: YouTube upload alerts (add, edit, toggle, test, remove)."""

from __future__ import annotations

from typing import Any

import discord
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from cogs.creator_alerts import DEFAULT_MESSAGE, PLACEHOLDERS, CreatorError


def _ping_label(guild: discord.Guild, row: Any) -> str:
    kind = row["ping_type"]
    if kind == "everyone":
        return "@everyone"
    if kind == "here":
        return "@here"
    if kind == "role":
        role = guild.get_role(int(row["ping_role_id"] or 0))
        return f"@{role.name}" if role else "a deleted role"
    return "No ping"


async def creator_context(request: Request, guild: discord.Guild) -> dict:
    """Extra template variables for the Creator Integration page."""
    from dashboard.routes import _bot, _grouped_channels

    cog = _bot(request).get_cog("CreatorAlerts")
    if cog is None:
        return {"creator_ready": False}
    cards = []
    for row in await cog.list_alerts(guild.id):
        channel = guild.get_channel(int(row["discord_channel_id"]))
        cards.append(
            {
                "num": int(row["num"]),
                "name": row["yt_name"] or row["yt_channel_id"],
                "yt_id": row["yt_channel_id"],
                "yt_url": f"https://www.youtube.com/channel/{row['yt_channel_id']}",
                "channel_id": int(row["discord_channel_id"]),
                "channel_name": channel.name if channel else None,
                "ping_type": row["ping_type"],
                "ping_label": _ping_label(guild, row),
                "role_id": int(row["ping_role_id"]) if row["ping_role_id"] else None,
                "message": row["message"] or "",
                "enabled": bool(row["enabled"]),
                "warnings": cog.warnings_for(guild, row),
            }
        )
    role_options = [r for r in reversed(guild.roles) if not r.is_default() and not r.managed]
    return {
        "creator_ready": True,
        "creator_cards": cards,
        "creator_grouped": _grouped_channels(guild),
        "creator_roles": role_options,
        "creator_default_message": DEFAULT_MESSAGE,
        "creator_placeholders": PLACEHOLDERS,
    }


def register_creator_routes(app: FastAPI) -> None:
    @app.post("/servers/{guild_id}/creator")
    async def creator_post(request: Request, guild_id: int):
        from dashboard.routes import _bot, _form, _guild_or_redirect, _text_channels, flash

        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        form = await _form(request)
        back = RedirectResponse(f"/servers/{guild_id}/youtube", status_code=303)
        cog = _bot(request).get_cog("CreatorAlerts")
        if cog is None:
            flash(request, "error", "Creator Integration is still starting. Try again in a moment.")
            return back
        action = str(form.get("action") or "")
        valid_channels = {c.id: c for c in _text_channels(guild)}

        def form_channel() -> discord.TextChannel:
            raw = str(form.get("discord_channel") or "")
            channel = valid_channels.get(int(raw)) if raw.isdigit() else None
            if channel is None:
                raise CreatorError("Pick a Discord channel to post in.")
            return channel

        def form_ping() -> tuple[str, int | None]:
            kind = str(form.get("ping_type") or "none")
            role_raw = str(form.get("ping_role") or "")
            role_id = int(role_raw) if role_raw.isdigit() else None
            if kind == "role" and (role_id is None or guild.get_role(role_id) is None):
                raise CreatorError("Pick the role to ping.")
            return kind, role_id

        try:
            if action == "add":
                channel = form_channel()
                kind, role_id = form_ping()
                alert, warns = await cog.add_alert(
                    guild, str(form.get("link") or ""), channel, kind, role_id, str(form.get("message") or "")
                )
                flash(request, "ok", f"Alert added for {alert['yt_name']}. Old videos won't be posted; new uploads appear within about 5 minutes.")
                for w in warns:
                    flash(request, "error", w)
                return back
            try:
                num = int(form.get("num") or 0)
            except ValueError:
                num = 0
            if action == "remove":
                if await cog.remove_alert(guild.id, num):
                    flash(request, "ok", "Alert removed.")
                else:
                    flash(request, "error", "That alert no longer exists.")
            elif action == "toggle":
                alert = await cog.get_alert(guild.id, num)
                if alert is None:
                    raise CreatorError("That alert no longer exists.")
                new_state = 0 if alert["enabled"] else 1
                await cog.update_alert(guild, num, enabled=new_state)
                flash(request, "ok", "Alert turned on." if new_state else "Alert turned off.")
            elif action == "edit":
                channel = form_channel()
                kind, role_id = form_ping()
                alert = await cog.update_alert(
                    guild,
                    num,
                    discord_channel_id=channel.id,
                    ping_type=kind,
                    ping_role_id=role_id,
                    message=str(form.get("message") or ""),
                )
                flash(request, "ok", "Alert saved.")
                for w in cog.warnings_for(guild, alert):
                    flash(request, "error", w)
            elif action == "test":
                alert = await cog.get_alert(guild.id, num)
                if alert is None:
                    raise CreatorError("That alert no longer exists.")
                video = await cog.send_test(guild, alert)
                flash(request, "ok", f"Test posted in #{guild.get_channel(int(alert['discord_channel_id'])).name} (no ping): {video.title}")
        except CreatorError as err:
            flash(request, "error", str(err))
        return back
