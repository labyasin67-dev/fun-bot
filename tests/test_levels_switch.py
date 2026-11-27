"""Levels master switch: default ON, guards stop XP / level-ups / commands only for servers that turned it off."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.leveling import Leveling  # noqa: E402
from cogs.levels_switch import LevelsSwitch  # noqa: E402
from database import Database  # noqa: E402


class Sent:
    def __init__(self):
        self.embeds = []

    async def send(self, content=None, *, embed=None, **kw):
        self.embeds.append(embed)


def make_ctx(gid):
    ctx = Sent()
    ctx.guild = types.SimpleNamespace(id=gid)
    return ctx


def make_message(gid, chan_id=5):
    return types.SimpleNamespace(
        author=types.SimpleNamespace(bot=False, id=77, mention="<@77>"),
        guild=types.SimpleNamespace(id=gid),
        content="hello",
        channel=types.SimpleNamespace(id=chan_id),
    )


class LevelsSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        await self.db.setup()
        self.bot = types.SimpleNamespace(db=self.db)
        self.switch = LevelsSwitch(self.bot)
        await self.switch.cog_load()
        self.lv = Leveling(self.bot)

    async def asyncTearDown(self):
        await self.db.db.close()
        self.tmp.cleanup()

    async def test_default_on_and_xp_flows(self):
        self.assertTrue(self.switch.is_enabled(1))
        await self.lv.on_message(make_message(1))
        row = await self.db.ensure_member(1, 77)
        self.assertGreater(int(row["xp"]), 0)

    async def test_off_blocks_xp_only_for_that_guild(self):
        await self.switch.set_enabled(1, False)
        self.assertFalse(self.switch.is_enabled(1))
        self.assertTrue(self.switch.is_enabled(2))
        await self.lv.on_message(make_message(1))
        await self.lv.on_message(make_message(2))
        self.assertEqual(int((await self.db.ensure_member(1, 77))["xp"]), 0)
        self.assertGreater(int((await self.db.ensure_member(2, 77))["xp"]), 0)

    async def test_off_suppresses_level_up_message(self):
        class Chan:
            sent = 0

            async def send(self, **kw):
                Chan.sent += 1

        guild = types.SimpleNamespace(id=1, get_member=lambda i: None, get_channel=lambda i: None)
        await self.lv._handle_level_up(guild, types.SimpleNamespace(id=1, mention="x"), Chan(), 0, 10_000)
        self.assertEqual(Chan.sent, 1)  # on: announces (isinstance check bypassed by origin channel)
        await self.switch.set_enabled(1, False)
        await self.lv._handle_level_up(guild, types.SimpleNamespace(id=1, mention="x"), Chan(), 0, 10_000)
        self.assertEqual(Chan.sent, 1)  # off: nothing more

    async def test_commands_reply_off(self):
        await self.switch.set_enabled(1, False)
        for cmd in (self.lv.rank, self.lv.leaderboard, self.lv.voicetime, self.lv.voiceleaderboard):
            ctx = make_ctx(1)
            await cmd.callback(self.lv, ctx)
            self.assertEqual(len(ctx.embeds), 1)
            self.assertIn("off", ctx.embeds[0].title.lower())

    async def test_setting_persists_across_restart_and_back_on(self):
        await self.switch.set_enabled(3, False)
        other = LevelsSwitch(types.SimpleNamespace(db=self.db))
        await other.cog_load()
        self.assertFalse(other.is_enabled(3))
        await other.set_enabled(3, True)
        self.assertTrue(other.is_enabled(3))
        again = LevelsSwitch(types.SimpleNamespace(db=self.db))
        await again.cog_load()
        self.assertTrue(again.is_enabled(3))


if __name__ == "__main__":
    unittest.main()
