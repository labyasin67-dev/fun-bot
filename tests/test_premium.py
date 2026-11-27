"""Unit tests for per-server Premium gating with fake guild ids."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

# Tests should not pick up a real .env requirement flag unexpectedly.
os.environ.setdefault("PREMIUM_REQUIRED", "true")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from premium import command_is_exempt, guild_access, subscription_is_effective


class PremiumAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()
        self.now = 1_700_000_000.0
        self.owner_ids = {111}

    async def asyncTearDown(self) -> None:
        await self.db.close()
        Path(self.path).unlink(missing_ok=True)

    async def test_gating_off_allows_any_guild(self):
        access = await guild_access(self.db, 999, required=False, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(access.allowed)
        self.assertEqual(access.reason, "not_required")

    async def test_unknown_guild_is_blocked_when_required(self):
        access = await guild_access(self.db, 999, guild_owner_id=222, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertFalse(access.allowed)
        self.assertEqual(access.reason, "none")

    async def test_owner_server_always_allowed(self):
        access = await guild_access(
            self.db, 555, guild_owner_id=111, required=True, owner_ids=self.owner_ids, now=self.now
        )
        self.assertTrue(access.allowed)
        self.assertEqual(access.reason, "owner_server")

    async def test_lifetime_guild_grant(self):
        await self.db.add_premium_grant(grant_type="guild", guild_id=200, note="comp", granted_by=111)
        access = await guild_access(self.db, 200, guild_owner_id=222, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(access.allowed)
        self.assertEqual(access.reason, "manual_grant")

    async def test_expired_and_revoked_grants_do_not_count(self):
        await self.db.add_premium_grant(
            grant_type="guild", guild_id=201, expires_at=self.now - 10, note="expired"
        )
        access = await guild_access(self.db, 201, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertFalse(access.allowed)

        gid = await self.db.add_premium_grant(grant_type="guild", guild_id=202, note="bye")
        await self.db.revoke_premium_grant(gid)
        access = await guild_access(self.db, 202, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertFalse(access.allowed)

    async def test_dated_guild_grant_still_valid(self):
        await self.db.add_premium_grant(
            grant_type="guild", guild_id=203, expires_at=self.now + 86400, note="week"
        )
        access = await guild_access(self.db, 203, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(access.allowed)

    async def test_user_grant_applies_to_owned_guild(self):
        await self.db.add_premium_grant(grant_type="user", user_id=444, note="friend")
        yes = await guild_access(self.db, 300, guild_owner_id=444, required=True, owner_ids=self.owner_ids, now=self.now)
        no = await guild_access(self.db, 301, guild_owner_id=445, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(yes.allowed)
        self.assertEqual(yes.reason, "user_grant")
        self.assertFalse(no.allowed)

    async def test_active_subscription(self):
        await self.db.upsert_subscription(
            guild_id=400,
            payer_user_id=7,
            stripe_customer_id="cus_x",
            stripe_subscription_id="sub_x",
            plan="monthly",
            status="active",
            current_period_end=self.now + 86400,
        )
        access = await guild_access(self.db, 400, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(access.allowed)
        self.assertEqual(access.reason, "subscription")

    async def test_past_due_grace_window(self):
        # Period ended 2 days ago — still in the 3-day grace.
        await self.db.upsert_subscription(
            guild_id=401,
            stripe_subscription_id="sub_grace",
            plan="yearly",
            status="past_due",
            current_period_end=self.now - 2 * 86400,
        )
        access = await guild_access(self.db, 401, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertTrue(access.allowed)
        self.assertEqual(access.reason, "past_due_grace")

        await self.db.upsert_subscription(
            guild_id=402,
            stripe_subscription_id="sub_late",
            plan="yearly",
            status="past_due",
            current_period_end=self.now - 4 * 86400,
        )
        late = await guild_access(self.db, 402, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertFalse(late.allowed)

    async def test_canceled_subscription_blocked(self):
        await self.db.upsert_subscription(
            guild_id=403,
            stripe_subscription_id="sub_c",
            plan="monthly",
            status="canceled",
            current_period_end=self.now + 86400,
        )
        access = await guild_access(self.db, 403, required=True, owner_ids=self.owner_ids, now=self.now)
        self.assertFalse(access.allowed)

    def test_exempt_commands(self):
        self.assertTrue(command_is_exempt("help"))
        self.assertTrue(command_is_exempt("ping"))
        self.assertTrue(command_is_exempt("premium"))
        self.assertTrue(command_is_exempt("premium status"))
        self.assertTrue(command_is_exempt("premium grant"))
        self.assertFalse(command_is_exempt("games"))
        self.assertFalse(command_is_exempt("ban"))

    def test_subscription_effective_helper(self):
        now = time.time()
        self.assertTrue(subscription_is_effective("active", now - 10, now=now))
        self.assertTrue(subscription_is_effective("past_due", now - 86400, now=now))
        self.assertFalse(subscription_is_effective("past_due", now - 4 * 86400, now=now))
        self.assertFalse(subscription_is_effective("canceled", now + 86400, now=now))


if __name__ == "__main__":
    unittest.main()
