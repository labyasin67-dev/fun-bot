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
    def __init__(self, gid: int, channel: FakeChannel) -> None:
        self.id = gid
        self._channel = channel
        self.me = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(view_audit_log=False))

    def get_channel(self, cid):
        return self._channel if cid == self._channel.id else None


def user(uid: int, bot: bool = False):
    return types.SimpleNamespace(id=uid, mention=f"<@{uid}>", bot=bot, display_avatar=types.SimpleNamespace(url="http://x"))


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
        self.assertIn("spam", desc)

    async def test_moderator_unavailable_without_permission(self):
        await self.cog.set_channel(1, 50)
        await self.cog.set_events(1, {"unban"})
        await self.cog.on_member_unban(self.guild, user(9))
        self.assertIn("View Audit Log", self.ch.sent[0].description)

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

    async def test_event_catalogue_covers_requested_events(self):
        want = {"member_join", "member_leave", "ban", "unban", "kick", "timeout", "nickname", "member_roles", "role_create",
                "role_delete", "role_update", "channel_create", "channel_delete", "channel_update", "message_edit",
                "message_delete", "bulk_delete", "voice", "invite_create", "invite_delete", "emoji", "sticker",
                "server_update", "thread_create", "thread_delete"}
        self.assertEqual(want, set(al.EVENT_KEYS))


if __name__ == "__main__":
    unittest.main()
