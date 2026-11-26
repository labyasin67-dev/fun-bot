"""Creator Integration: parsing, de-dupe, formatting and per-guild isolation (no Discord, no network)."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs import creator_alerts as ca  # noqa: E402
from database import Database  # noqa: E402

CID = "UC" + "a" * 22
CID2 = "UC" + "b" * 22


def feed_xml(name: str, ids: list[str]) -> str:
    entries = "".join(
        f"""<entry><id>yt:video:{i}</id><yt:videoId>{i}</yt:videoId><title>Video {i} @everyone</title>
        <link rel="alternate" href="https://www.youtube.com/watch?v={i}"/><published>2026-11-2{n}T00:00:00+00:00</published></entry>"""
        for n, i in enumerate(ids)
    )
    return f"""<?xml version="1.0"?><feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
    xmlns="http://www.w3.org/2005/Atom"><title>{name}</title>{entries}</feed>"""


class FakeChannel(discord.TextChannel):
    def __init__(self, cid: int, name: str = "alerts") -> None:  # bypass discord.py state
        self.id = cid
        self.name = name
        self.sent: list[tuple[str, discord.AllowedMentions]] = []

    async def send(self, content=None, *, allowed_mentions=None, **kw):  # type: ignore[override]
        self.sent.append((content, allowed_mentions))


def fake_guild(gid: int, channel: FakeChannel, roles: dict[int, str] | None = None):
    roles = roles or {}
    return types.SimpleNamespace(
        id=gid,
        me=None,
        get_channel=lambda i: channel if i == channel.id else None,
        get_role=lambda i: types.SimpleNamespace(id=i, name=roles[i], mentionable=True) if i in roles else None,
    )


class ParsingTests(unittest.TestCase):
    def test_channel_input(self):
        self.assertEqual(ca.parse_channel_input(CID), (CID, None))
        self.assertEqual(ca.parse_channel_input(f"https://www.youtube.com/channel/{CID}/videos"), (CID, None))
        self.assertEqual(ca.parse_channel_input("@MrBeast"), (None, "https://www.youtube.com/@MrBeast"))
        self.assertEqual(ca.parse_channel_input("youtube.com/@MrBeast/featured"), (None, "https://www.youtube.com/@MrBeast"))
        self.assertEqual(ca.parse_channel_input("https://m.youtube.com/c/SomeName"), (None, "https://www.youtube.com/c/SomeName"))
        self.assertEqual(ca.parse_channel_input("https://evil.example/@x"), (None, None))
        self.assertEqual(ca.parse_channel_input("https://youtube.com.evil.example/@x"), (None, None))
        self.assertEqual(ca.parse_channel_input("   "), (None, None))

    def test_page_id(self):
        html = f'<link rel="canonical" href="https://www.youtube.com/channel/{CID}"><x>"channelId":"{CID2}"'
        self.assertEqual(ca.extract_channel_id_from_page(html), CID)
        self.assertIsNone(ca.extract_channel_id_from_page("<html></html>"))

    def test_feed_and_dedupe(self):
        feed = ca.parse_feed(feed_xml("Chan", ["v3", "v2", "v1", "v2"]))
        self.assertEqual(feed.channel_name, "Chan")
        self.assertEqual([v.video_id for v in feed.videos], ["v3", "v2", "v1", "v2"])
        fresh = ca.unseen_videos(feed.videos, {"v1"})
        self.assertEqual([v.video_id for v in fresh], ["v2", "v3"])  # oldest first, no duplicate
        with self.assertRaises(ca.CreatorError):
            ca.parse_feed("not xml")

    def test_message_format(self):
        kw = dict(title="T", url="https://y/1", channel="Chan")
        default = ca.format_message(None, ping_type="everyone", role_id=None, **kw)
        self.assertTrue(default.startswith("@everyone **Chan**"))
        self.assertTrue(default.endswith("https://y/1"))
        custom = ca.format_message("New: {title} by {channel}", ping_type="role", role_id=55, **kw)
        self.assertEqual(custom, "<@&55> New: T by Chan\nhttps://y/1")
        placed = ca.format_message("{title} {ping} {url}", ping_type="here", role_id=None, **kw)
        self.assertEqual(placed, "T @here https://y/1")
        self.assertEqual(ca.format_message("{ping} {title}", ping_type="none", role_id=None, **kw), "T\nhttps://y/1")
        long = ca.format_message("x" * 3000, ping_type="none", role_id=None, **kw)
        self.assertLessEqual(len(long), 2000)
        self.assertTrue(long.endswith("https://y/1"))

    def test_allowed_mentions(self):
        self.assertTrue(ca.allowed_mentions_for("everyone", None).everyone)
        self.assertTrue(ca.allowed_mentions_for("here", None).everyone)
        none = ca.allowed_mentions_for("none", None)
        self.assertFalse(none.everyone)
        self.assertFalse(none.roles)
        role = ca.allowed_mentions_for("role", 9)
        self.assertFalse(role.everyone)
        self.assertEqual([r.id for r in role.roles], [9])

    def test_permission_warnings(self):
        class Perms:
            view_channel = True
            send_messages = True
            embed_links = True
            mention_everyone = False

        chan = types.SimpleNamespace(name="alerts", permissions_for=lambda me: Perms())
        guild = types.SimpleNamespace(me=object())
        self.assertTrue(any("Mention Everyone" in w for w in ca.permission_warnings(guild, chan, "everyone", None)))
        self.assertEqual(ca.permission_warnings(guild, chan, "none", None), [])
        Perms.send_messages = False
        self.assertTrue(any("Send Messages" in w for w in ca.permission_warnings(guild, chan, "none", None)))
        self.assertTrue(ca.permission_warnings(guild, None, "none", None))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "t.db"))
        await self.db.setup()
        self.bot = types.SimpleNamespace(db=self.db)
        self.cog = ca.CreatorAlerts.__new__(ca.CreatorAlerts)
        self.cog.bot = self.bot
        self.cog._session = None
        await self.db.db.executescript(ca.SCHEMA)
        self.feeds = {CID: feed_xml("Chan One", ["v2", "v1"]), CID2: feed_xml("Chan Two", ["w1"])}

        async def fake_get(url, *, headers=None):
            for cid, xml in self.feeds.items():
                if cid in url:
                    return xml
            raise ca.CreatorError("I couldn't find that YouTube channel.")

        self.cog._get_text = fake_get
        self.ch1, self.ch2 = FakeChannel(111), FakeChannel(222)
        self.g1 = fake_guild(1, self.ch1, {7: "Subs"})
        self.g2 = fake_guild(2, self.ch2)
        self.bot.get_guild = lambda gid: {1: self.g1, 2: self.g2}.get(gid)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_add_records_existing_and_posts_only_new(self):
        alert, _ = await self.cog.add_alert(self.g1, CID, self.ch1, "everyone")
        self.assertEqual(alert["yt_name"], "Chan One")
        self.assertEqual(await self.cog._seen(alert["id"]), {"v1", "v2"})
        feed = await self.cog.fetch_feed(CID)
        await self.cog._process(alert, feed)
        self.assertEqual(self.ch1.sent, [])  # nothing old is posted
        self.feeds[CID] = feed_xml("Chan One", ["v3", "v2", "v1"])
        feed = await self.cog.fetch_feed(CID)
        await self.cog._process(alert, feed)
        await self.cog._process(alert, feed)  # polling again must not repeat it
        self.assertEqual(len(self.ch1.sent), 1)
        text, mentions = self.ch1.sent[0]
        self.assertIn("https://www.youtube.com/watch?v=v3", text)
        self.assertTrue(text.startswith("@everyone"))
        self.assertTrue(mentions.everyone)

    async def test_two_guilds_are_isolated(self):
        a1, _ = await self.cog.add_alert(self.g1, CID, self.ch1, "none")
        a2, _ = await self.cog.add_alert(self.g2, CID, self.ch2, "none")
        self.assertEqual((a1["num"], a2["num"]), (1, 1))  # numbering is per server
        self.assertEqual(len(await self.cog.list_alerts(1)), 1)
        self.assertEqual(len(await self.cog.list_alerts(2)), 1)
        await self.cog.update_alert(self.g1, 1, ping_type="role", ping_role_id=7, message="Hi {title}")
        self.assertEqual((await self.cog.get_alert(2, 1))["ping_type"], "none")
        self.assertIsNone((await self.cog.get_alert(2, 1))["message"])
        # Guild 2 cannot reach guild 1's alert through its own number lookup.
        with self.assertRaises(ca.CreatorError):
            await self.cog.find_alert(2, "#2")
        self.feeds[CID] = feed_xml("Chan One", ["v3", "v2", "v1"])
        feed = await self.cog.fetch_feed(CID)
        await self.cog._process(await self.cog.get_alert(1, 1), feed)
        await self.cog._process(await self.cog.get_alert(2, 1), feed)
        (t1, m1), (t2, m2) = self.ch1.sent[0], self.ch2.sent[0]
        self.assertEqual(t1, "<@&7> Hi Video v3 @everyone\nhttps://www.youtube.com/watch?v=v3")
        self.assertEqual([r.id for r in m1.roles], [7])
        self.assertFalse(m1.everyone)  # '@everyone' inside a title never pings
        self.assertFalse(m2.everyone)
        self.assertFalse(t2.startswith("<@&"))

    async def test_duplicate_limits_toggle_remove_and_test(self):
        await self.cog.add_alert(self.g1, CID, self.ch1)
        with self.assertRaises(ca.CreatorError):
            await self.cog.add_alert(self.g1, CID, self.ch1)
        with self.assertRaises(ca.CreatorError):
            await self.cog.add_alert(self.g1, "@missing", self.ch1)
        with self.assertRaises(ca.CreatorError):
            await self.cog.add_alert(self.g1, CID2, self.ch1, "role", 999)
        a = await self.cog.update_alert(self.g1, 1, enabled=0)
        self.assertEqual(a["enabled"], 0)
        await self.cog.update_alert(self.g1, 1, ping_type="everyone")
        video = await self.cog.send_test(self.g1, await self.cog.get_alert(1, 1))
        self.assertEqual(video.video_id, "v2")
        text, mentions = self.ch1.sent[-1]
        self.assertIn("Test alert", text)
        self.assertFalse(mentions.everyone)  # tests never ping
        self.assertTrue(await self.cog.remove_alert(1, 1))
        self.assertFalse(await self.cog.remove_alert(1, 1))
        self.assertEqual(await self.cog._seen(1), set())

    async def test_ping_parse(self):
        g = types.SimpleNamespace(get_role=lambda i: types.SimpleNamespace(id=i, is_default=lambda: False) if i == 7 * 10**16 else None, roles=[])
        P = ca.CreatorAlerts._parse_ping
        self.assertEqual(P(g, None), ("none", None))
        self.assertEqual(P(g, "@everyone"), ("everyone", None))
        self.assertEqual(P(g, "HERE"), ("here", None))
        self.assertEqual(P(g, f"<@&{7 * 10**16}>"), ("role", 7 * 10**16))
        with self.assertRaises(ca.CreatorError):
            P(g, "nonsense")


if __name__ == "__main__":
    unittest.main()
