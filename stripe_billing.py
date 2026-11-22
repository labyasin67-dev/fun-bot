"""Stripe Checkout, Customer Portal, price bootstrap, and webhook handling."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("socialize")

LOOKUP_MONTHLY = "bot_monthly_usd"
LOOKUP_YEARLY = "bot_yearly_usd"


def stripe_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip())


def _stripe():
    import stripe

    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    stripe.api_key = key
    return stripe


def plan_from_price_id(price_id: str | None, prices: dict[str, str] | None = None) -> str | None:
    if not price_id:
        return None
    prices = prices or {}
    if price_id == prices.get("monthly") or price_id.endswith("monthly"):
        return "monthly"
    if price_id == prices.get("yearly") or price_id.endswith("yearly"):
        return "yearly"
    return None


def _price_id_from_subscription(sub: dict) -> str | None:
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    if isinstance(price, str):
        return price
    return price.get("id")


def _period_end(sub: dict) -> float | None:
    raw = sub.get("current_period_end")
    if raw:
        return float(raw)
    items = (sub.get("items") or {}).get("data") or []
    if items and items[0].get("current_period_end"):
        return float(items[0]["current_period_end"])
    return None


def _lookup_or_create_price(stripe: Any, lookup_key: str, *, unit_amount: int, interval: str, product_name: str) -> str:
    found = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    data = list(found.data or [])
    if data:
        return str(data[0].id)
    product = stripe.Product.create(name=product_name, metadata={"lookup_key": lookup_key})
    price = stripe.Price.create(
        lookup_key=lookup_key,
        unit_amount=unit_amount,
        currency="usd",
        recurring={"interval": interval},
        product=product.id,
    )
    return str(price.id)


def ensure_stripe_prices() -> dict[str, str]:
    """Return {monthly, yearly} price ids, creating them idempotently if needed."""
    monthly_env = os.getenv("STRIPE_PRICE_MONTHLY", "").strip()
    yearly_env = os.getenv("STRIPE_PRICE_YEARLY", "").strip()
    if monthly_env and yearly_env:
        return {"monthly": monthly_env, "yearly": yearly_env}
    stripe = _stripe()
    monthly = monthly_env or _lookup_or_create_price(
        stripe,
        LOOKUP_MONTHLY,
        unit_amount=1000,
        interval="month",
        product_name="Fun bot Premium (Monthly)",
    )
    yearly = yearly_env or _lookup_or_create_price(
        stripe,
        LOOKUP_YEARLY,
        unit_amount=10000,
        interval="year",
        product_name="Fun bot Premium (Yearly)",
    )
    return {"monthly": monthly, "yearly": yearly}


def create_checkout_session(
    *,
    price_id: str,
    guild_id: int,
    payer_user_id: int,
    success_url: str,
    cancel_url: str,
) -> str:
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(guild_id),
        metadata={"guild_id": str(guild_id), "payer_user_id": str(payer_user_id)},
        subscription_data={"metadata": {"guild_id": str(guild_id), "payer_user_id": str(payer_user_id)}},
    )
    url = session.url
    if not url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return str(url)


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    if not session.url:
        raise RuntimeError("Stripe did not return a portal URL")
    return str(session.url)


def construct_event(payload: bytes, signature: str) -> dict:
    import stripe as stripe_mod
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise ValueError("webhook secret missing")
    event = stripe_mod.Webhook.construct_event(payload, signature, secret)
    if hasattr(event, "to_dict"):
        return event.to_dict()
    return dict(event)


def _plan_for_sub(sub: dict, prices: dict[str, str] | None) -> str | None:
    price_id = _price_id_from_subscription(sub)
    plan = plan_from_price_id(price_id, prices)
    if plan:
        return plan
    interval = None
    items = (sub.get("items") or {}).get("data") or []
    if items:
        rec = (items[0].get("price") or {}).get("recurring") or {}
        interval = rec.get("interval")
    if interval == "year":
        return "yearly"
    if interval == "month":
        return "monthly"
    return None


async def apply_subscription_payload(db: Any, sub: dict, *, prices: dict[str, str] | None = None, default_guild_id: int | None = None, default_payer: int | None = None) -> None:
    metadata = sub.get("metadata") or {}
    guild_raw = metadata.get("guild_id") or default_guild_id
    payer_raw = metadata.get("payer_user_id") or default_payer
    if guild_raw is None:
        existing = await db.get_subscription_by_stripe_id(str(sub.get("id") or "")) if sub.get("id") else None
        if existing is not None:
            guild_raw = existing["guild_id"]
            payer_raw = payer_raw or existing["payer_user_id"]
    if guild_raw is None:
        log.warning("Stripe subscription %s has no guild_id metadata", sub.get("id"))
        return
    await db.upsert_subscription(
        guild_id=int(guild_raw),
        payer_user_id=int(payer_raw) if payer_raw else None,
        stripe_customer_id=str(sub["customer"]) if sub.get("customer") else None,
        stripe_subscription_id=str(sub["id"]) if sub.get("id") else None,
        plan=_plan_for_sub(sub, prices),
        status=str(sub.get("status") or "unknown"),
        current_period_end=_period_end(sub),
    )


async def handle_stripe_event(db: Any, event: dict, *, prices: dict[str, str] | None = None) -> None:
    etype = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    if etype == "checkout.session.completed":
        guild_id = (obj.get("metadata") or {}).get("guild_id") or obj.get("client_reference_id")
        payer = (obj.get("metadata") or {}).get("payer_user_id")
        sub_id = obj.get("subscription")
        customer = obj.get("customer")
        if sub_id:
            stripe = _stripe()
            sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
            payload = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            await apply_subscription_payload(
                db,
                payload,
                prices=prices,
                default_guild_id=int(guild_id) if guild_id else None,
                default_payer=int(payer) if payer else None,
            )
        elif guild_id:
            await db.upsert_subscription(
                guild_id=int(guild_id),
                payer_user_id=int(payer) if payer else None,
                stripe_customer_id=str(customer) if customer else None,
                stripe_subscription_id=None,
                plan=None,
                status="active",
                current_period_end=None,
            )
        return
    if etype in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        if etype == "customer.subscription.deleted" and not obj.get("status"):
            obj = dict(obj)
            obj["status"] = "canceled"
        await apply_subscription_payload(db, obj, prices=prices)
        return
    if etype == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        if not sub_id:
            return
        existing = await db.get_subscription_by_stripe_id(str(sub_id))
        if existing is not None:
            await db.upsert_subscription(
                guild_id=int(existing["guild_id"]),
                payer_user_id=int(existing["payer_user_id"]) if existing["payer_user_id"] else None,
                stripe_customer_id=existing["stripe_customer_id"],
                stripe_subscription_id=str(sub_id),
                plan=existing["plan"],
                status="past_due",
                current_period_end=existing["current_period_end"],
            )
