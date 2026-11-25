"""Tests for XP adjustments, legal page rendering, and dashboard routes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("PREMIUM_REQUIRED", "true")
os.environ["SESSION_SECRET"] = "test-session-secret-not-for-production"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from site_pages import (
    CONTACT_KEY,
    DEFAULT_CONTACT,
    DEFAULT_PRIVACY,
    DEFAULT_TERMS,
    PRIVACY_KEY,
    TERMS_KEY,
    load_site_page,
    render_page_body,
)
from utils import level_from_xp, parse_user_id
from cogs.moderation import DEFAULT_BAN_ANNOUNCE, DEFAULT_BAN_DM, render_ban_message
from cogs.welcome import DEFAULT_LEAVE, render_leave


class AdjustXpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        Path(self.path).unlink(missing_ok=True)

    async def test_adjust_xp_adds_and_clamps_at_zero(self):
        old, new = await self.db.adjust_xp(1, 2, 250)
        self.assertEqual(old, 0)
        self.assertEqual(new, 250)
        old, new = await self.db.adjust_xp(1, 2, -50)
        self.assertEqual(old, 250)
        self.assertEqual(new, 200)
        old, new = await self.db.adjust_xp(1, 2, -10_000)
        self.assertEqual(old, 200)
        self.assertEqual(new, 0)
        self.assertGreaterEqual(new, 0)

    async def test_add_xp_also_clamps(self):
        await self.db.adjust_xp(1, 3, 10)
        old, new = await self.db.add_xp(1, 3, -50)
        self.assertEqual(old, 10)
        self.assertEqual(new, 0)

    async def test_level_from_xp(self):
        self.assertEqual(level_from_xp(0), 0)
        self.assertGreaterEqual(level_from_xp(500), 1)



    async def test_levelup_mode_default_and_off(self):
        mode = await self.db.get_levelup_mode(5)
        self.assertEqual(mode, "off")
        await self.db.set_levelup_mode(5, "off")
        self.assertEqual(await self.db.get_levelup_mode(5), "off")
        await self.db.set_levelup_mode(5, "dm")
        self.assertEqual(await self.db.get_levelup_mode(5), "off")
        await self.db.set_levelup_mode(5, "channel", 99)
        self.assertEqual(await self.db.get_levelup_mode(5), "channel")
        self.assertEqual(await self.db.get_feature_channel(5, "levelups"), 99)
        await self.db.set_levelup_mode(5, "off")
        self.assertEqual(await self.db.get_levelup_mode(5), "off")
        # Turning off keeps the previous channel so it can be restored.
        self.assertEqual(await self.db.get_feature_channel(5, "levelups"), 99)

class MessageRenderTests(unittest.TestCase):
    def test_parse_user_id(self):
        self.assertEqual(parse_user_id("123456789012345678"), 123456789012345678)
        self.assertEqual(parse_user_id("<@123456789012345678>"), 123456789012345678)
        self.assertEqual(parse_user_id("<@!123456789012345678>"), 123456789012345678)
        self.assertIsNone(parse_user_id("not-an-id"))
        self.assertIsNone(parse_user_id(""))

    def test_render_leave_and_ban_placeholders(self):
        class User:
            id = 42
            name = "Sam"
            mention = "<@42>"

        class Guild:
            name = "Example Server"
            member_count = 10
            members = []

        leave = render_leave("{user} / {username} left {server} ({membercount})", User(), Guild())
        self.assertIn("<@42>", leave)
        self.assertIn("Sam", leave)
        self.assertIn("Example Server", leave)
        self.assertIn("10", leave)

        class Mod:
            mention = "<@99>"

        ban = render_ban_message(
            "{user} banned from {server} by {moderator}: {reason} ({username})",
            user=User(),
            guild=Guild(),
            reason="spam",
            moderator=Mod(),
            default=DEFAULT_BAN_DM,
        )
        self.assertIn("<@42>", ban)
        self.assertIn("Example Server", ban)
        self.assertIn("<@99>", ban)
        self.assertIn("spam", ban)
        self.assertIn("Sam", ban)
        self.assertTrue(DEFAULT_BAN_ANNOUNCE)
        self.assertTrue(DEFAULT_LEAVE)


class SitePageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        Path(self.path).unlink(missing_ok=True)

    def test_renderer_escapes_and_headings(self):
        html = render_page_body("# Hello\n\nVisit <script>alert(1)</script>\n\n**Bold** text")
        self.assertIn("<h1>Hello</h1>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("<strong>Bold</strong>", html)

    async def test_defaults_then_override(self):
        text = await load_site_page(self.db, TERMS_KEY)
        self.assertIn("Last updated: 26 November 2026", text)
        self.assertIn("Australian Consumer Law", text)
        self.assertIn("Whiskey/WarRaven", text)
        self.assertIn("Victoria", text)
        self.assertNotIn("lawyer-reviewed", text.lower())
        self.assertIn("[Add your contact email here]", await load_site_page(self.db, CONTACT_KEY))
        privacy = await load_site_page(self.db, PRIVACY_KEY)
        self.assertIn("Privacy Policy", privacy)
        self.assertIn("Stripe", privacy)
        await self.db.set_site_page(CONTACT_KEY, "# Contact Us\n\nHello from tests")
        stored = await load_site_page(self.db, CONTACT_KEY)
        self.assertEqual(stored, "# Contact Us\n\nHello from tests")
        self.assertTrue(DEFAULT_TERMS.startswith("# Terms"))
        self.assertTrue(DEFAULT_CONTACT)
        self.assertTrue(DEFAULT_PRIVACY)


class DashboardSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import create_app

        cls.app = create_app(bot=None)
        cls.client = TestClient(cls.app)

    def test_public_pages_ok(self):
        for path in ("/", "/pricing", "/contact", "/terms", "/privacy"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 200, msg=path)
            body = response.text
            self.assertNotIn("Internal Server Error", body)
            self.assertIn("space-bg", body)
            self.assertIn("/contact", body)
            self.assertIn("/terms", body)
            self.assertIn("/privacy", body)

    def test_terms_and_privacy_content(self):
        terms = self.client.get("/terms")
        self.assertIn("Last updated: 26 November 2026", terms.text)
        self.assertIn("Victoria", terms.text)
        self.assertIn("US$10", terms.text)
        privacy = self.client.get("/privacy")
        self.assertIn("Privacy Policy", privacy.text)
        self.assertIn("Stripe", privacy.text)
        contact = self.client.get("/contact")
        self.assertIn("[Add your contact email here]", contact.text)

    def test_guild_pages_require_login(self):
        for path in (
            "/servers/1/levels",
            "/servers/1/moderation",
            "/servers/1/welcome",
            "/servers/1/customroles",
            "/servers/1/reports",
            "/admin",
        ):
            response = self.client.get(path, follow_redirects=False)
            self.assertIn(response.status_code, (302, 303), msg=path)
            location = response.headers.get("location", "")
            self.assertTrue("/login" in location or location.startswith("/"), msg=location)




class CustomRoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        Path(self.path).unlink(missing_ok=True)

    def test_name_validation(self):
        from cogs.customroles import parse_hex_colour, validate_custom_role_name

        self.assertIsNone(validate_custom_role_name("Starlight"))
        self.assertIsNotNone(validate_custom_role_name(""))
        self.assertIsNotNone(validate_custom_role_name("x" * 33))
        self.assertIsNotNone(validate_custom_role_name("@everyone"))
        self.assertIsNotNone(validate_custom_role_name("Admin"))
        self.assertIsNotNone(validate_custom_role_name("server staff"))
        self.assertIsNotNone(validate_custom_role_name("here"))
        self.assertIsNone(parse_hex_colour("not-a-colour"))
        self.assertEqual(parse_hex_colour("#ff0000").value, 0xFF0000)
        self.assertEqual(parse_hex_colour("00AAff").value, 0x00AAFF)
        self.assertIsNone(parse_hex_colour("#fff"))
        from cogs.customroles import format_colour_pair
        self.assertIn("→", format_colour_pair(0xFF0000, 0x0000FF))
        self.assertNotIn("→", format_colour_pair(0xFF0000))

    async def test_settings_and_restriction_roundtrip(self):
        settings = await self.db.get_customrole_settings(11)
        self.assertEqual(int(settings["enabled"] or 0), 0)
        self.assertEqual(int(settings["min_level"] or 0), 10)
        await self.db.set_customrole_settings(11, enabled=1, min_level=20)
        settings = await self.db.get_customrole_settings(11)
        self.assertEqual(int(settings["enabled"]), 1)
        self.assertEqual(int(settings["min_level"]), 20)
        await self.db.add_custom_role(11, 22, 33, secondary_colour=0x00FFAA)
        row = await self.db.get_custom_role(11, 22)
        self.assertEqual(int(row["role_id"]), 33)
        self.assertEqual(int(row["secondary_colour"]), 0x00FFAA)
        await self.db.set_custom_role_secondary(11, 22, None)
        row = await self.db.get_custom_role(11, 22)
        self.assertIsNone(row["secondary_colour"])
        await self.db.set_custom_role_secondary(11, 22, 0x0000FF)
        row = await self.db.get_custom_role(11, 22)
        self.assertEqual(int(row["secondary_colour"]), 0x0000FF)
        self.assertFalse(await self.db.is_custom_role_restricted(11, 22))
        await self.db.restrict_custom_role_user(11, 22, reason="abuse", by=99)
        self.assertTrue(await self.db.is_custom_role_restricted(11, 22))
        await self.db.delete_custom_role(11, 22)
        self.assertIsNone(await self.db.get_custom_role(11, 22))
        self.assertTrue(await self.db.unrestrict_custom_role_user(11, 22))
        self.assertFalse(await self.db.is_custom_role_restricted(11, 22))
        settings = await self.db.get_customrole_settings(11)
        self.assertEqual(int(settings["give_enabled"] or 0), 1)
        await self.db.set_customrole_settings(11, give_enabled=0)
        settings = await self.db.get_customrole_settings(11)
        self.assertEqual(int(settings["give_enabled"]), 0)
        await self.db.add_custom_role(11, 22, 33, secondary_colour=0x00FFAA)
        row = await self.db.get_custom_role(11, 22)
        self.assertEqual(int(row["holder_id"] or row["user_id"]), 22)
        await self.db.set_custom_role_holder(11, 22, 44)
        held = await self.db.get_custom_role_held(11, 44)
        self.assertIsNotNone(held)
        self.assertEqual(int(held["user_id"]), 22)
        self.assertFalse(await self.db.is_custom_role_give_blocked(11, 22))
        await self.db.block_custom_role_give(11, 22, reason="abuse", by=99)
        self.assertTrue(await self.db.is_custom_role_give_blocked(11, 22))
        self.assertTrue(await self.db.unblock_custom_role_give(11, 22))
        self.assertFalse(await self.db.is_custom_role_give_blocked(11, 22))



class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        Path(self.path).unlink(missing_ok=True)

    async def test_settings_default_channel_mode(self):
        settings = await self.db.get_report_settings(7)
        self.assertEqual(int(settings["enabled"] or 0), 0)
        self.assertEqual(str(settings["mode"] or "channel"), "channel")
        await self.db.set_report_settings(7, enabled=1, mode="ticket")
        settings = await self.db.get_report_settings(7)
        self.assertEqual(int(settings["enabled"]), 1)
        self.assertEqual(settings["mode"], "ticket")
        await self.db.set_report_settings(7, alert_channel_id=100, closed_channel_id=200)
        settings = await self.db.get_report_settings(7)
        self.assertEqual(int(settings["alert_channel_id"]), 100)
        self.assertEqual(int(settings["closed_channel_id"]), 200)


    async def test_ticket_decision_names_and_owner_notes(self):
        ticket_id = await self.db.create_report_ticket(
            7,
            reporter_id=11,
            reporter_name="Reporter",
            reporter_avatar="https://example.com/r.png",
            reported_user_id=22,
            reported_name="Reported",
            reported_avatar="https://example.com/t.png",
            message_link="https://discord.com/channels/1/2/3",
            message_preview="hello",
            reason="spam",
        )
        await self.db.claim_report_ticket(ticket_id, 99, name="Mod Alice", avatar="https://example.com/a.png")
        await self.db.decide_report_ticket(
            ticket_id, status="approved", decided_by=99, decided_by_name="Mod Alice",
            decided_by_avatar="https://example.com/a.png", decision_reason="Looks valid",
        )
        row = await self.db.get_report_ticket(ticket_id, 7)
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["claimed_by_name"], "Mod Alice")
        self.assertEqual(row["decided_by_name"], "Mod Alice")
        self.assertEqual(row["decision_reason"], "Looks valid")
        self.assertEqual(row["reporter_name"], "Reporter")
        await self.db.add_report_note(
            ticket_id, 7, author_id=1, author_name="Owner", author_avatar="https://example.com/o.png", body="Private note"
        )
        notes = await self.db.list_report_notes(ticket_id)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["author_name"], "Owner")
        self.assertEqual(notes[0]["body"], "Private note")
        self.assertEqual(await self.db.count_reports(7, "approved"), 1)
        self.assertEqual(await self.db.count_open_reports(7, 11), 0)

    async def test_block_and_cooldown_helpers(self):
        self.assertFalse(await self.db.is_report_blocked(7, 11))
        await self.db.block_reporter(7, 11, reason="abuse", by=1)
        self.assertTrue(await self.db.is_report_blocked(7, 11))
        self.assertTrue(await self.db.unblock_reporter(7, 11))
        self.assertFalse(await self.db.is_report_blocked(7, 11))

if __name__ == "__main__":
    unittest.main()
