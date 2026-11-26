"""Tests for custom roles and the report system."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database


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
        self.assertTrue(await self.db.delete_report_ticket(ticket_id, 7))
        self.assertIsNone(await self.db.get_report_ticket(ticket_id, 7))
        self.assertEqual(await self.db.list_report_notes(ticket_id), [])
        self.assertFalse(await self.db.delete_report_ticket(ticket_id, 7))

    async def test_block_and_cooldown_helpers(self):
        self.assertFalse(await self.db.is_report_blocked(7, 11))
        await self.db.block_reporter(7, 11, reason="abuse", by=1)
        self.assertTrue(await self.db.is_report_blocked(7, 11))
        self.assertTrue(await self.db.unblock_reporter(7, 11))
        self.assertFalse(await self.db.is_report_blocked(7, 11))


class ReportNameTests(unittest.TestCase):
    def test_embed_uses_mention_and_username(self):
        import types
        from cogs.reports import build_report_embed, format_claimer, format_report_user

        guild = types.SimpleNamespace(id=7, name="Test", get_member=lambda uid: None, _state=None)
        member = types.SimpleNamespace(id=11, name="alice", display_name="Alice")
        guild.get_member = lambda uid, m=member: m if int(uid) == 11 else None
        self.assertEqual(format_report_user(guild, 11, "Stored"), "<@11> @alice (11)")
        self.assertEqual(format_report_user(guild, 22, "Bob"), "<@22> @Bob (22)")
        self.assertEqual(format_report_user(guild, 33, None), "<@33> (33)")
        self.assertEqual(format_claimer(guild, 11, "Stored"), "@alice (11)")
        self.assertEqual(format_claimer(guild, 44, None), "44")

        row = {
            "id": 1, "status": "open", "reporter_id": 11, "reporter_name": "Stored",
            "reported_user_id": 22, "reported_name": "Bob", "reason": "spam",
            "message_preview": None, "message_link": None, "claimed_by": 11,
            "claimed_by_name": "Stored", "claimed_at": None, "decided_by": None,
        }
        emb = build_report_embed(guild, row)
        self.assertIn("<@11> @alice (11)", emb.description)
        self.assertIn("<@22> @Bob (22)", emb.description)
        self.assertNotIn("ID 11", emb.description)
        self.assertNotIn("(`11`)", emb.description)
        self.assertEqual(emb.fields[0].name, "Claimed by")
        self.assertEqual(emb.fields[0].value, "@alice (11)")


if __name__ == "__main__":
    unittest.main()
