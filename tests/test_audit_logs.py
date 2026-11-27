"""Audit logs: defaults, per-event gating, persistence, moderator attribution, loop protection (no Discord)."""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import audit_logs as al  # noqa: E402
from database import Database  # noqa: E402


class FakeChannel(discord.TextChannel):
    def __init__(self, cid: int) -> None:
        self.id = cid
        self.name = "audit"
        self.sent: list[discord.Embed] = []

    async def send(self, *, embed=None, allowed_mentions=None, **kw):  # type: ignore[override]
        assert allowed_mentions is not None and not allowed_mentions.everyone and not allowed_mentions.users
        self.sent.append(embed)


class FakeGuild:
    def __init__(self, gid: int, channel: FakeChannel, owner_id: int = 1) -> None:
        self.id = gid
        self._channel = channel
        self.owner_id = owner_id
        self.me = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(view_audit_log=False))
        self._members: dict[int, object] = {}

    def get_channel(self, cid):
        return self._channel if cid == self._channel.id else None

    def get_member(self, uid):
        return self._members.get(int(uid))


def user(uid: int, bot: bool = False, name: str | None = None, *, administrator: bool = False):
    uname = name or f"User{uid}"
    return types.SimpleNamespace(
        id=uid,
        mention=f"<@{uid}>",
        bot=bot,
        name=uname,
        display_name=uname,
        guild_permissions=types.SimpleNamespace(administrator=administrator),
        display_avatar=types.SimpleNamespace(url="http://x"),
    )


class AuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        await self.db.setup()
        self.bot = types.SimpleNamespace(db=self.db, get_guild=lambda gid: self.guild if gid == 1 else None)
        self.cog = al.AuditLogs(self.bot)
        await self.cog.cog_load()
        self.ch = FakeChannel(50)
        self.guild = FakeGuild(1, self.ch)

    async def asyncTearDown(self):
        await self.db.db.close()
        self.tmp.cleanup()

    async def test_everything_off_by_default(self):
        self.assertEqual(self.cog.get_config(1), (None, set()))
        await self.cog.on_member_ban(self.guild, user(9))
        self.assertEqual(self.ch.sent, [])

    async def test_channel_without_events_logs_nothing(self):
        await self.cog.set_channel(1, 50)
        await self.cog.on_member_ban(self.guild, user(9))
        self.assertEqual(self.ch.sent, [])

    async def test_only_ticked_events_post_and_moderator_comes_from_audit_log(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"ban"})

        async def fake_entry(guild, action, target_id=None, **kw):
            return types.SimpleNamespace(user=user(77), reason="spam", target=user(9))

        self.cog._audit_entry = fake_entry
        await self.cog.on_member_ban(self.guild, user(9))
        await self.cog.on_member_unban(self.guild, user(9))  # unticked
        self.assertEqual(len(self.ch.sent), 1)
        desc = self.ch.sent[0].description
        self.assertIn("<@9>", desc)
        self.assertIn("<@77>", desc)
        self.assertIn("User77", desc)
        self.assertIn("**By:**", desc)
        self.assertNotIn("**Moderator:**", desc)
        self.assertIn("spam", desc)

    async def test_moderator_unavailable_without_permission(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"unban"})
        await self.cog.on_member_unban(self.guild, user(9))
        self.assertIn("Unknown (needs View Audit Log permission)", self.ch.sent[0].description)
        self.assertIn("**By:**", self.ch.sent[0].description)

    async def test_log_channel_and_bots_are_ignored_for_messages(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"message_delete", "message_edit"})
        cached = types.SimpleNamespace(author=user(5), content="hi", attachments=[])
        # deleting a message inside the log channel itself must never recurse
        await self.cog.on_raw_message_delete(types.SimpleNamespace(guild_id=1, channel_id=50, message_id=1, cached_message=cached))
        # bot authored
        bot_msg = types.SimpleNamespace(author=user(6, bot=True), content="x", attachments=[])
        await self.cog.on_raw_message_delete(types.SimpleNamespace(guild_id=1, channel_id=7, message_id=2, cached_message=bot_msg))
        await self.cog.on_raw_message_edit(types.SimpleNamespace(guild_id=1, channel_id=7, message_id=3, cached_message=None, data={"content": "new", "author": {"id": "8", "bot": True}}))
        self.assertEqual(self.ch.sent, [])
        # a real user's delete is logged
        await self.cog.on_raw_message_delete(types.SimpleNamespace(guild_id=1, channel_id=7, message_id=4, cached_message=cached))
        self.assertEqual(len(self.ch.sent), 1)
        self.assertIn("hi", self.ch.sent[0].description)
        self.assertIn("**By:** author or unknown", self.ch.sent[0].description)

    async def test_edit_with_same_content_not_logged(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"message_edit"})
        before = types.SimpleNamespace(author=user(5), content="same")
        await self.cog.on_raw_message_edit(types.SimpleNamespace(guild_id=1, channel_id=7, message_id=3, cached_message=before, data={"content": "same", "author": {"id": "5"}}))
        self.assertEqual(self.ch.sent, [])
        await self.cog.on_raw_message_edit(types.SimpleNamespace(guild_id=1, channel_id=7, message_id=3, cached_message=before, data={"content": "different", "author": {"id": "5"}}))
        self.assertEqual(len(self.ch.sent), 1)

    async def test_other_guild_unaffected_and_persistence(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"ban", "voice"})
        again = al.AuditLogs(self.bot)
        await again.cog_load()
        self.assertEqual(again.get_config(1), (50, {"ban", "voice"}))
        self.assertEqual(again.get_config(2), (None, set()))
        await again.set_events(1, set())
        third = al.AuditLogs(self.bot)
        await third.cog_load()
        self.assertEqual(third.get_config(1), (50, set()))

    async def test_log_admins_defaults_on_and_persists(self):
        self.assertTrue(self.cog.log_admins(1))
        await self.cog.set_log_admins(1, False)
        self.assertFalse(self.cog.log_admins(1))
        again = al.AuditLogs(self.bot)
        await again.cog_load()
        self.assertFalse(again.log_admins(1))
        self.assertTrue(again.log_admins(2))

    async def test_skips_owner_and_administrator_when_disabled(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"ban", "unban"})
        await self.cog.set_log_admins(1, False)
        self.guild.owner_id = 77
        owner = user(77, name="Owner")
        admin = user(88, name="Admin", administrator=True)
        regular = user(99, name="Mod")
        self.guild._members[88] = admin

        async def fake_entry(guild, action, target_id=None, **kw):
            return types.SimpleNamespace(user=self._actor, reason=None, target=user(9))

        self.cog._audit_entry = fake_entry
        self._actor = owner
        await self.cog.on_member_ban(self.guild, user(9))
        self.assertEqual(self.ch.sent, [])
        self._actor = admin
        await self.cog.on_member_ban(self.guild, user(9))
        self.assertEqual(self.ch.sent, [])
        self._actor = regular
        await self.cog.on_member_unban(self.guild, user(9))
        self.assertEqual(len(self.ch.sent), 1)
        self.assertIn("Mod", self.ch.sent[0].description)
        self.assertIn("<@99>", self.ch.sent[0].description)

        # turning the setting back on logs the owner
        await self.cog.set_log_admins(1, True)
        self._actor = owner
        await self.cog.on_member_ban(self.guild, user(9))
        self.assertEqual(len(self.ch.sent), 2)
        self.assertIn("<@77>", self.ch.sent[1].description)

    async def test_legacy_settings_table_migrates_log_admins_on(self):
        # simulate a pre-migration database: drop the column by using a bare table
        await self.db.db.execute("DROP TABLE audit_settings")
        await self.db.db.execute("CREATE TABLE audit_settings (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
        await self.db.db.execute("INSERT INTO audit_settings (guild_id, channel_id) VALUES (1, 50)")
        await self.db.db.commit()
        again = al.AuditLogs(self.bot)
        await again.cog_load()
        self.assertTrue(again.log_admins(1))
        self.assertTrue(again.log_admin_deletes(1))
        self.assertEqual(again.get_config(1)[0], 50)

    async def test_log_admin_deletes_defaults_on_and_is_independent(self):
        self.assertTrue(self.cog.log_admin_deletes(1))
        await self.cog.set_log_admin_deletes(1, False)
        await self.cog.set_log_admins(1, True)
        self.assertFalse(self.cog.log_admin_deletes(1))
        self.assertTrue(self.cog.log_admins(1))
        again = al.AuditLogs(self.bot)
        await again.cog_load()
        self.assertFalse(again.log_admin_deletes(1))
        self.assertTrue(again.log_admins(1))

    async def test_skips_admin_and_owner_message_deletes_when_disabled(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"message_delete", "bulk_delete"})
        await self.cog.set_log_admin_deletes(1, False)
        await self.cog.set_log_admins(1, True)  # general toggle stays on
        self.guild.owner_id = 77
        owner = user(77, name="Owner")
        admin = user(88, name="Admin", administrator=True)
        regular = user(5, name="Member")
        self.guild._members[88] = admin

        # no audit entry: author is used
        await self.cog.on_raw_message_delete(types.SimpleNamespace(
            guild_id=1, channel_id=7, message_id=10, cached_message=types.SimpleNamespace(author=owner, content="o", attachments=[]),
        ))
        await self.cog.on_raw_message_delete(types.SimpleNamespace(
            guild_id=1, channel_id=7, message_id=11, cached_message=types.SimpleNamespace(author=admin, content="a", attachments=[]),
        ))
        self.assertEqual(self.ch.sent, [])
        await self.cog.on_raw_message_delete(types.SimpleNamespace(
            guild_id=1, channel_id=7, message_id=12, cached_message=types.SimpleNamespace(author=regular, content="m", attachments=[]),
        ))
        self.assertEqual(len(self.ch.sent), 1)
        self.assertIn("m", self.ch.sent[0].description)

        # audit entry names the deleter (admin deleted a regular user's message)
        async def fake_entry(guild, action, target_id=None, **kw):
            return types.SimpleNamespace(user=admin, reason=None, target=regular)
        self.cog._audit_entry = fake_entry
        self.ch.sent.clear()
        await self.cog.on_raw_message_delete(types.SimpleNamespace(
            guild_id=1, channel_id=7, message_id=13, cached_message=types.SimpleNamespace(author=regular, content="x", attachments=[]),
        ))
        self.assertEqual(self.ch.sent, [])
        await self.cog.on_raw_bulk_message_delete(types.SimpleNamespace(guild_id=1, channel_id=7, message_ids=[1, 2, 3]))
        self.assertEqual(self.ch.sent, [])

        # independent: general log_admins off must not by itself hide message deletes when this toggle is on
        await self.cog.set_log_admin_deletes(1, True)
        await self.cog.set_log_admins(1, False)
        self.ch.sent.clear()
        await self.cog.on_raw_message_delete(types.SimpleNamespace(
            guild_id=1, channel_id=7, message_id=14, cached_message=types.SimpleNamespace(author=regular, content="kept", attachments=[]),
        ))
        self.assertEqual(len(self.ch.sent), 1)
        self.assertIn("kept", self.ch.sent[0].description)

    async def test_event_catalogue_covers_requested_events(self):
        want = {"member_join", "member_leave", "ban", "unban", "kick", "timeout", "nickname", "member_roles", "role_create",
                "role_delete", "role_update", "channel_create", "channel_delete", "channel_update", "message_edit",
                "message_delete", "bulk_delete", "voice", "invite_create", "invite_delete", "emoji", "sticker",
                "server_update", "thread_create", "thread_delete"}
        self.assertEqual(want, set(al.EVENT_KEYS))


if __name__ == "__main__":
    unittest.main()
