"""Per-server Fun bot Premium access (Stripe subscriptions and manual grants)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from discord.ext import commands

GRACE_SECONDS = 3 * 24 * 60 * 60
CREDIT = "Made by Whiskey/WarRaven"
MONTHLY_CENTS = 1000
YEARLY_CENTS = 10000
LOOKUP_MONTHLY = "bot_monthly_usd"
LOOKUP_YEARLY = "bot_yearly_usd"

# Commands that still work on a server without Premium.
EXEMPT_ROOTS = frozenset({"help", "ping", "premium"})

ACTIVE_STATUSES = frozenset({"active", "trialing"})


class PremiumRequired(commands.CheckFailure):
    """Raised when a command is blocked because the server has no Premium."""


@dataclass(frozen=True)
class Access:
    allowed: bool
    reason: str
    status: str
    plan: str | None = None
    renewal: float | None = None
    source: str | None = None
    detail: str | None = None


def premium_required() -> bool:
    raw = os.getenv("PREMIUM_REQUIRED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def owner_ids_from_env() -> set[int]:
    ids: set[int] = set()
    for part in os.getenv("OWNER_IDS", "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def pricing_url() -> str:
    from dashboard import dashboard_url

    return f"{dashboard_url()}/pricing"


def premium_needed_message() -> str:
    return f"This server needs Meowchi Cafe Premium — subscribe at {pricing_url()}"


def command_is_exempt(name: str | None) -> bool:
    if not name:
        return False
    root = name.strip().lstrip(".").split()[0].split(":")[0].lower()
    return root in EXEMPT_ROOTS


def subscription_is_effective(status: str | None, period_end: float | None, *, now: float, grace: int = GRACE_SECONDS) -> bool:
    """Whether a stored Stripe subscription currently unlocks the server."""
    if not status:
        return False
    if status in ACTIVE_STATUSES:
        return True
    if status == "past_due":
        if period_end is None:
            return False
        return now <= float(period_end) + grace
    return False


async def guild_access(
    db: Any,
    guild_id: int,
    *,
    guild_owner_id: int | None = None,
    owner_ids: set[int] | frozenset[int] | None = None,
    now: float | None = None,
    required: bool | None = None,
) -> Access:
    """Decide whether a guild currently has Fun bot Premium.

    `required` and `owner_ids` can be passed in so tests do not depend on env.
    """
    if now is None:
        now = time.time()
    if required is None:
        required = premium_required()
    if owner_ids is None:
        owner_ids = owner_ids_from_env()

    if not required:
        return Access(True, "not_required", "not_required", detail="Gating is off")

    if guild_owner_id is not None and int(guild_owner_id) in owner_ids:
        return Access(True, "owner_server", "granted", source="owner", detail="Application owner's server")

    grants = await db.list_active_guild_grants(guild_id, now=now)
    if grants:
        row = grants[0]
        expires = row["expires_at"]
        return Access(
            True,
            "manual_grant",
            "granted",
            renewal=float(expires) if expires else None,
            source="grant",
            detail=row["note"] or "Manual grant",
        )

    if guild_owner_id is not None:
        user_grants = await db.list_active_user_grants(int(guild_owner_id), now=now)
        if user_grants:
            row = user_grants[0]
            expires = row["expires_at"]
            return Access(
                True,
                "user_grant",
                "granted",
                renewal=float(expires) if expires else None,
                source="user_grant",
                detail=row["note"] or "User grant (server owner)",
            )

    sub = await db.get_subscription_for_guild(guild_id)
    if sub is not None and subscription_is_effective(sub["status"], sub["current_period_end"], now=now):
        reason = "subscription" if sub["status"] in ACTIVE_STATUSES else "past_due_grace"
        status = sub["status"] or "active"
        return Access(
            True,
            reason,
            status,
            plan=sub["plan"],
            renewal=float(sub["current_period_end"]) if sub["current_period_end"] else None,
            source="stripe",
        )

    if sub is not None:
        return Access(
            False,
            "inactive_subscription",
            sub["status"] or "inactive",
            plan=sub["plan"],
            renewal=float(sub["current_period_end"]) if sub["current_period_end"] else None,
            source="stripe",
        )
    return Access(False, "none", "none")


async def guild_has_premium(db: Any, guild_id: int, **kwargs: Any) -> bool:
    access = await guild_access(db, guild_id, **kwargs)
    return access.allowed


def status_label(access: Access) -> str:
    if access.reason == "not_required":
        return "Not required"
    if not access.allowed:
        if access.status == "past_due":
            return "Past due"
        if access.status == "canceled":
            return "Canceled"
        return "Inactive"
    if access.reason == "owner_server":
        return "Owner server"
    if access.reason in {"manual_grant", "user_grant"}:
        return "Granted" if access.renewal is None else "Granted until renewal"
    if access.reason == "past_due_grace":
        return "Past due (grace)"
    if access.plan == "yearly":
        return "Active · Yearly"
    if access.plan == "monthly":
        return "Active · Monthly"
    return "Active"


def format_renewal(ts: float | None) -> str:
    if not ts:
        return "Lifetime"
    return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
