"""Pricing, Stripe Checkout/portal, webhooks, and the owner admin panel."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from dashboard import dashboard_url
from site_pages import CONTACT_KEY, load_site_page, save_site_page
from premium import format_renewal, guild_access, owner_ids_from_env, status_label
from stripe_billing import (
    construct_event,
    create_checkout_session,
    create_portal_session,
    handle_stripe_event,
    stripe_configured,
)


def _owner_ids(bot) -> set[int]:
    ids = owner_ids_from_env()
    if bot is not None:
        ids |= set(getattr(bot, "app_owner_ids", None) or set())
        if getattr(bot, "owner_ids", None):
            ids |= set(bot.owner_ids)
        if getattr(bot, "owner_id", None):
            ids.add(int(bot.owner_id))
    return ids


def register_billing_routes(app) -> None:
    from dashboard.routes import (
        _bot,
        _form,
        _need_login,
        render,
        _nav,
        _guild_or_redirect,
    )
    from dashboard.auth import (
        current_user,
        flash,
        managed_guilds,
        require_user,
    )

    def _is_admin(request: Request) -> bool:
        user = current_user(request)
        if not user:
            return False
        return int(user["id"]) in _owner_ids(_bot(request))

    def _parse_until(raw: str | None) -> float | None:
        if not raw:
            return None
        raw = raw.strip()
        if not raw:
            return None
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()

    @app.get("/pricing", response_class=HTMLResponse)
    async def pricing(request: Request):
        return render(request, "pricing.html", payments_ready=stripe_configured())

    @app.get("/billing/success", response_class=HTMLResponse)
    async def billing_success(request: Request):
        return render(request, "billing_success.html")

    @app.get("/billing/cancel", response_class=HTMLResponse)
    async def billing_cancel(request: Request):
        return render(request, "billing_cancel.html")

    @app.get("/subscribe", response_class=HTMLResponse)
    async def subscribe_get(request: Request, plan: str = "monthly"):
        user = require_user(request)
        redir = _need_login(user)
        if redir:
            return redir
        if plan not in {"monthly", "yearly"}:
            plan = "monthly"
        if not stripe_configured():
            flash(request, "error", "Payments are not enabled yet.")
            return RedirectResponse("/pricing", status_code=303)
        bot = _bot(request)
        bot_ids = {g.id for g in bot.guilds} if bot is not None else set()
        servers = []
        for guild in managed_guilds(request):
            gid = int(guild["id"])
            if gid not in bot_ids:
                continue
            live = bot.get_guild(gid) if bot is not None else None
            servers.append({"id": gid, "name": (live.name if live else guild["name"])})
        return render(
            request,
            "subscribe.html",
            plan=plan,
            plan_label="Yearly" if plan == "yearly" else "Monthly",
            price="100" if plan == "yearly" else "10",
            servers=servers,
        )

    @app.post("/subscribe/checkout")
    async def subscribe_checkout(request: Request):
        user = require_user(request)
        redir = _need_login(user)
        if redir:
            return redir
        form = await _form(request)
        plan = str(form.get("plan") or "monthly")
        if plan not in {"monthly", "yearly"}:
            plan = "monthly"
        raw = str(form.get("guild_id") or "").strip()
        if not raw.isdigit():
            flash(request, "error", "Pick a server.")
            return RedirectResponse(f"/subscribe?plan={plan}", status_code=303)
        guild_id = int(raw)
        if not any(int(g["id"]) == guild_id for g in managed_guilds(request)):
            flash(request, "error", "You need Manage Server in that community.")
            return RedirectResponse(f"/subscribe?plan={plan}", status_code=303)
        bot = _bot(request)
        if bot is None or bot.get_guild(guild_id) is None:
            flash(request, "error", "The bot is not in that server yet.")
            return RedirectResponse(f"/subscribe?plan={plan}", status_code=303)
        if not stripe_configured():
            flash(request, "error", "Payments are not enabled yet.")
            return RedirectResponse("/pricing", status_code=303)
        prices = getattr(bot, "stripe_prices", None) or {}
        price_id = prices.get(plan)
        if not price_id:
            flash(request, "error", "Stripe prices are not ready yet. Try again in a moment.")
            return RedirectResponse("/pricing", status_code=303)
        base = dashboard_url(request)
        try:
            url = await asyncio.to_thread(
                create_checkout_session,
                price_id=price_id,
                guild_id=guild_id,
                payer_user_id=int(user["id"]),
                success_url=f"{base}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base}/billing/cancel",
            )
        except Exception:
            flash(request, "error", "Could not start Stripe Checkout. Check the Stripe configuration.")
            return RedirectResponse("/pricing", status_code=303)
        return RedirectResponse(url, status_code=303)

    @app.get("/servers/{guild_id}/billing", response_class=HTMLResponse)
    async def billing_get(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        bot = _bot(request)
        access = await guild_access(
            bot.db,
            guild.id,
            guild_owner_id=guild.owner_id,
            owner_ids=_owner_ids(bot),
        )
        sub = await bot.db.get_subscription_for_guild(guild.id)
        plan = access.plan or (sub["plan"] if sub else None)
        plan_text = {"monthly": "Monthly ($10 USD)", "yearly": "Yearly ($100 USD)"}.get(plan or "", "—")
        if access.reason in {"manual_grant", "user_grant", "owner_server"}:
            plan_text = access.detail or "Manual grant"
        return render(
            request,
            "billing.html",
            **_nav(guild, "billing"),
            access=access,
            status_text=status_label(access),
            plan_text=plan_text,
            renewal_text=format_renewal(access.renewal),
            payments_ready=stripe_configured(),
            customer_id=(sub["stripe_customer_id"] if sub and sub["stripe_customer_id"] else None),
        )

    @app.post("/servers/{guild_id}/billing/portal")
    async def billing_portal(request: Request, guild_id: int):
        redir, guild, _user = await _guild_or_redirect(request, guild_id)
        if redir:
            return redir
        assert guild
        await _form(request)
        bot = _bot(request)
        sub = await bot.db.get_subscription_for_guild(guild.id)
        if not stripe_configured() or not sub or not sub["stripe_customer_id"]:
            flash(request, "error", "There is no Stripe customer on file for this server.")
            return RedirectResponse(f"/servers/{guild.id}/billing", status_code=303)
        base = dashboard_url(request)
        try:
            url = await asyncio.to_thread(
                create_portal_session,
                customer_id=str(sub["stripe_customer_id"]),
                return_url=f"{base}/servers/{guild.id}/billing",
            )
        except Exception:
            flash(request, "error", "Could not open the billing portal.")
            return RedirectResponse(f"/servers/{guild.id}/billing", status_code=303)
        return RedirectResponse(url, status_code=303)

    @app.post("/stripe/webhook")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret or not signature:
            return JSONResponse({"error": "invalid signature"}, status_code=400)
        try:
            event = await asyncio.to_thread(construct_event, payload, signature)
        except Exception:
            return JSONResponse({"error": "invalid signature"}, status_code=400)
        bot = _bot(request)
        if bot is None or getattr(bot, "db", None) is None:
            return JSONResponse({"error": "bot is not ready"}, status_code=503)
        try:
            await handle_stripe_event(bot.db, event, prices=getattr(bot, "stripe_prices", None))
        except Exception:
            return JSONResponse({"error": "handler failed"}, status_code=500)
        return JSONResponse({"received": True})

    def _admin_or_redirect(request: Request):
        user = require_user(request)
        if _need_login(user):
            return _need_login(user)
        if not _is_admin(request):
            return HTMLResponse("You don't have access to this page.", status_code=403)
        return None

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_get(request: Request):
        denied = _admin_or_redirect(request)
        if denied:
            return denied
        bot = _bot(request)
        db = bot.db if bot is not None else None
        servers = []
        if bot is not None and db is not None:
            owners = _owner_ids(bot)
            for guild in bot.guilds:
                access = await guild_access(db, guild.id, guild_owner_id=guild.owner_id, owner_ids=owners)
                servers.append(
                    {
                        "id": guild.id,
                        "name": guild.name,
                        "access": access,
                        "status": status_label(access),
                        "renewal": format_renewal(access.renewal),
                    }
                )
            servers.sort(key=lambda r: r["name"].lower())
            grants = await db.list_premium_grants(active_only=True)
            subs = [
                s
                for s in await db.list_subscriptions()
                if s["status"] in {"active", "trialing", "past_due"}
            ]
        else:
            grants, subs = [], []
        return render(
            request,
            "admin.html",
            servers=servers,
            grants=grants,
            stripe_subs=subs,
            format_renewal=format_renewal,
            contact_body=await load_site_page(db, CONTACT_KEY),
        )

    @app.post("/admin")
    async def admin_post(request: Request):
        denied = _admin_or_redirect(request)
        if denied:
            return denied
        form = await _form(request)
        bot = _bot(request)
        if bot is None:
            flash(request, "error", "The bot is not ready.")
            return RedirectResponse("/admin", status_code=303)
        action = str(form.get("action") or "")
        user = current_user(request)
        granted_by = int(user["id"]) if user else None
        if action == "grant_guild":
            raw = str(form.get("guild_id") or "").strip()
            if not raw.isdigit():
                flash(request, "error", "Enter a numeric guild ID.")
            else:
                expires = _parse_until(str(form.get("until") or ""))
                note = str(form.get("note") or "").strip() or None
                await bot.db.add_premium_grant(
                    grant_type="guild",
                    guild_id=int(raw),
                    expires_at=expires,
                    note=note,
                    granted_by=granted_by,
                )
                flash(request, "ok", f"Granted Premium to guild {raw}.")
        elif action == "grant_user":
            raw = str(form.get("user_id") or "").strip()
            if not raw.isdigit():
                flash(request, "error", "Enter a numeric Discord user ID.")
            else:
                expires = _parse_until(str(form.get("until") or ""))
                note = str(form.get("note") or "").strip() or None
                await bot.db.add_premium_grant(
                    grant_type="user",
                    user_id=int(raw),
                    expires_at=expires,
                    note=note,
                    granted_by=granted_by,
                )
                flash(request, "ok", f"Granted Premium for servers owned by {raw}.")
        elif action == "revoke":
            try:
                grant_id = int(form.get("grant_id") or 0)
            except ValueError:
                grant_id = 0
            if grant_id and await bot.db.revoke_premium_grant(grant_id):
                flash(request, "ok", "Grant revoked.")
            else:
                flash(request, "error", "That grant was not found or was already revoked.")
        elif action == "save_page":
            key = str(form.get("page_key") or "").strip()
            body = str(form.get("body") or "")
            if key != CONTACT_KEY:
                flash(request, "error", "Unknown page.")
            elif not body.strip():
                flash(request, "error", "That page cannot be empty. Paste the text you want to publish.")
            else:
                await save_site_page(bot.db, key, body[:20000])
                flash(request, "ok", "Contact Us page saved and published.")
        return RedirectResponse("/admin", status_code=303)
