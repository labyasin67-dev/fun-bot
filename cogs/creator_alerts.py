"""Creator Integration: YouTube upload alerts per server (no API key, no logins).

Admins paste a channel link, @handle or channel ID, pick a Discord channel and an
optional ping. The bot polls the public RSS feed and posts new uploads.
Works from both the dashboard (Creator Integration page) and the `.creator` commands.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

log = logging.getLogger("socialize.creator")

POLL_MINUTES = 5
MAX_ALERTS_PER_GUILD = 25
MAX_POSTS_PER_POLL = 3
MAX_BODY = 3_000_000
DEFAULT_MESSAGE = "{ping} **{channel}** just posted a new video: **{title}**\n{url}"
PING_TYPES = ("none", "everyone", "here", "role")
PLACEHOLDERS = "{title} {url} {channel} {ping}"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PAGE_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI"}

CHANNEL_ID_RE = re.compile(r"UC[0-9A-Za-z_-]{22}")
HANDLE_RE = re.compile(r"[A-Za-z0-9._-]{3,30}")
PAGE_ID_PATTERNS = (
    re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{22})"'),
    re.compile(r'"externalId":"(UC[0-9A-Za-z_-]{22})"'),
    re.compile(r'<meta itemprop="(?:identifier|channelId)" content="(UC[0-9A-Za-z_-]{22})"'),
)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    num INTEGER NOT NULL,
    yt_channel_id TEXT NOT NULL,
    yt_name TEXT NOT NULL DEFAULT '',
    discord_channel_id INTEGER NOT NULL,
    ping_type TEXT NOT NULL DEFAULT 'none',
    ping_role_id INTEGER,
    message TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    UNIQUE (guild_id, num),
    UNIQUE (guild_id, yt_channel_id)
);
CREATE TABLE IF NOT EXISTS creator_seen (
    alert_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    PRIMARY KEY (alert_id, video_id)
);
"""


class CreatorError(Exception):
    """A message that is safe to show to the person who ran the command or form."""


@dataclass
class Video:
    video_id: str
    title: str
    url: str
    published: str


@dataclass
class Feed:
    channel_name: str
    videos: list[Video]  # newest first, as YouTube lists them


# ---------------------------------------------------------------- pure helpers

def parse_channel_input(text: str) -> tuple[str | None, str | None]:
    """Return (channel_id, page_url). Exactly one is set, or both None if unusable."""
    raw = (text or "").strip().strip("<>").strip()
    if not raw:
        return None, None
    if CHANNEL_ID_RE.fullmatch(raw):
        return raw, None
    if raw.startswith("@"):
        handle = raw[1:]
        return (None, f"https://www.youtube.com/@{handle}") if HANDLE_RE.fullmatch(handle) else (None, None)
    if "." not in raw and "/" not in raw and HANDLE_RE.fullmatch(raw):
        return None, f"https://www.youtube.com/@{raw}"
    candidate = raw if "://" in raw else "https://" + raw
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None, None
    host = (parsed.hostname or "").lower()
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return None, None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None, None
    first = parts[0]
    if first == "channel" and len(parts) > 1:
        return (parts[1], None) if CHANNEL_ID_RE.fullmatch(parts[1]) else (None, None)
    if first.startswith("@") and HANDLE_RE.fullmatch(first[1:]):
        return None, f"https://www.youtube.com/{first}"
    if first in {"c", "user"} and len(parts) > 1 and HANDLE_RE.fullmatch(parts[1]):
        return None, f"https://www.youtube.com/{first}/{parts[1]}"
    return None, None


def extract_channel_id_from_page(html: str) -> str | None:
    for pattern in PAGE_ID_PATTERNS:
        m = pattern.search(html)
        if m:
            return m.group(1)
    return None


def parse_feed(xml_text: str) -> Feed:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise CreatorError("YouTube sent back a feed I couldn't read.") from err
    title_el = root.find("a:title", NS)
    name = (title_el.text or "").strip() if title_el is not None else ""
    videos: list[Video] = []
    for entry in root.findall("a:entry", NS):
        vid_el = entry.find("yt:videoId", NS)
        if vid_el is None or not (vid_el.text or "").strip():
            continue
        vid = vid_el.text.strip()
        t = entry.find("a:title", NS)
        link = entry.find("a:link[@rel='alternate']", NS)
        pub = entry.find("a:published", NS)
        videos.append(
            Video(
                video_id=vid,
                title=((t.text or "").strip() if t is not None else "") or "New video",
                url=(link.get("href") if link is not None and link.get("href") else f"https://www.youtube.com/watch?v={vid}"),
                published=(pub.text or "").strip() if pub is not None else "",
            )
        )
    return Feed(channel_name=name, videos=videos)


def unseen_videos(videos: list[Video], seen: set[str]) -> list[Video]:
    """Videos not seen before, oldest first, de-duplicated by video id."""
    out: list[Video] = []
    ids: set[str] = set()
    for v in reversed(videos):
        if v.video_id in seen or v.video_id in ids:
            continue
        ids.add(v.video_id)
        out.append(v)
    return out


def ping_text(ping_type: str, role_id: int | None) -> str:
    if ping_type == "everyone":
        return "@everyone"
    if ping_type == "here":
        return "@here"
    if ping_type == "role" and role_id:
        return f"<@&{int(role_id)}>"
    return ""


def format_message(template: str | None, *, title: str, url: str, channel: str, ping_type: str, role_id: int | None) -> str:
    """Fill in the placeholders. The ping and link are always included once."""
    text = (template or "").strip() or DEFAULT_MESSAGE
    ping = ping_text(ping_type, role_id)
    has_ping = "{ping}" in text
    has_url = "{url}" in text
    text = text.replace("{title}", title).replace("{channel}", channel).replace("{url}", url).replace("{ping}", ping)
    if ping and not has_ping:
        text = f"{ping} {text}"
    if not has_url:
        text = f"{text}\n{url}"
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    text = re.sub(r"^[ \t]+", "", text)
    if len(text) > 2000:
        # Keep the link: trim the wording before it.
        text = text[: 2000 - len(url) - 1].rstrip() + "\n" + url
    return text


def allowed_mentions_for(ping_type: str, role_id: int | None) -> discord.AllowedMentions:
    if ping_type in {"everyone", "here"}:
        return discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)
    if ping_type == "role" and role_id:
        return discord.AllowedMentions(everyone=False, users=False, roles=[discord.Object(id=int(role_id))], replied_user=False)
    return discord.AllowedMentions.none()


def permission_warnings(guild: discord.Guild, channel: Any, ping_type: str, role: discord.Role | None) -> list[str]:
    """Plain-English problems that would stop an alert from posting or pinging."""
    if channel is None:
        return ["That Discord channel no longer exists. Pick a new one."]
    me = guild.me
    if me is None:
        return []
    perms = channel.permissions_for(me)
    out: list[str] = []
    if not perms.view_channel or not perms.send_messages:
        out.append(f"I can't send messages in #{channel.name}. Give me View Channel and Send Messages there.")
    elif not perms.embed_links:
        out.append(f"I'm missing Embed Links in #{channel.name}, so the video preview won't show.")
    if ping_type in {"everyone", "here"} and not perms.mention_everyone:
        out.append(f"I need the Mention Everyone permission in #{channel.name} for @{'everyone' if ping_type == 'everyone' else 'here'} to ping.")
    if ping_type == "role":
        if role is None:
            out.append("The role to ping no longer exists.")
        elif not role.mentionable and not perms.mention_everyone:
            out.append(f"@{role.name} isn't mentionable. Make it mentionable or give me Mention Everyone in #{channel.name}.")
    return out


# ------------------------------------------------------------------------- cog

class CreatorAlerts(commands.Cog):
    """YouTube upload alerts (Creator Integration)."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    # -- lifecycle
    async def cog_load(self) -> None:
        await self.bot.db.db.executescript(SCHEMA)
        await self.bot.db.db.commit()
        self.poll.start()

    async def cog_unload(self) -> None:
        self.poll.cancel()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    # -- network
    async def _get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        try:
            async with self._http().get(url, headers=headers) as resp:
                if resp.status == 404:
                    raise CreatorError("I couldn't find that YouTube channel.")
                if resp.status != 200:
                    raise CreatorError(f"YouTube answered with an error ({resp.status}). Try again in a moment.")
                data = await resp.content.read(MAX_BODY)
                return data.decode("utf-8", errors="replace")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CreatorError("I couldn't reach YouTube right now. Try again in a moment.") from err

    async def resolve_channel(self, text: str) -> str:
        cid, page = parse_channel_input(text)
        if cid:
            return cid
        if not page:
            raise CreatorError("I couldn't read that. Paste a YouTube channel link, an @handle, or a channel ID (starts with UC).")
        html = await self._get_text(page, headers=PAGE_HEADERS)
        found = extract_channel_id_from_page(html)
        if not found:
            raise CreatorError("I couldn't find a channel at that link. Check the spelling, or paste the channel ID.")
        return found

    async def fetch_feed(self, channel_id: str) -> Feed:
        xml_text = await self._get_text(FEED_URL.format(cid=channel_id))
        return parse_feed(xml_text)

    # -- storage
    async def list_alerts(self, guild_id: int) -> list[Any]:
        cur = await self.bot.db.db.execute("SELECT * FROM creator_alerts WHERE guild_id = ? ORDER BY num", (guild_id,))
        return await cur.fetchall()

    async def get_alert(self, guild_id: int, num: int) -> Any | None:
        cur = await self.bot.db.db.execute("SELECT * FROM creator_alerts WHERE guild_id = ? AND num = ?", (guild_id, num))
        return await cur.fetchone()

    async def _seen(self, alert_id: int) -> set[str]:
        cur = await self.bot.db.db.execute("SELECT video_id FROM creator_seen WHERE alert_id = ?", (alert_id,))
        return {r[0] for r in await cur.fetchall()}

    async def _mark_seen(self, alert_id: int, ids: list[str]) -> None:
        if ids:
            await self.bot.db.db.executemany(
                "INSERT OR IGNORE INTO creator_seen (alert_id, video_id) VALUES (?, ?)", [(alert_id, i) for i in ids]
            )
            await self.bot.db.db.commit()

    async def add_alert(
        self,
        guild: discord.Guild,
        link: str,
        channel: discord.TextChannel,
        ping_type: str = "none",
        role_id: int | None = None,
        message: str | None = None,
    ) -> tuple[Any, list[str]]:
        ping_type = self._check_ping(guild, ping_type, role_id)
        existing = await self.list_alerts(guild.id)
        if len(existing) >= MAX_ALERTS_PER_GUILD:
            raise CreatorError(f"This server already has {MAX_ALERTS_PER_GUILD} alerts. Remove one first.")
        cid = await self.resolve_channel(link)
        if any(r["yt_channel_id"] == cid for r in existing):
            raise CreatorError("That YouTube channel already has an alert here. Edit or remove it instead.")
        feed = await self.fetch_feed(cid)
        message = self._clean_message(message)
        num = max([int(r["num"]) for r in existing], default=0) + 1
        db = self.bot.db.db
        cur = await db.execute(
            """INSERT INTO creator_alerts
               (guild_id, num, yt_channel_id, yt_name, discord_channel_id, ping_type, ping_role_id, message, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (guild.id, num, cid, feed.channel_name or cid, channel.id, ping_type, role_id if ping_type == "role" else None, message, time.time()),
        )
        await db.commit()
        # Record what already exists so old videos are never posted.
        await self._mark_seen(int(cur.lastrowid), [v.video_id for v in feed.videos])
        alert = await self.get_alert(guild.id, num)
        return alert, self.warnings_for(guild, alert)

    def _check_ping(self, guild: discord.Guild, ping_type: str, role_id: int | None) -> str:
        ping_type = (ping_type or "none").lower()
        if ping_type not in PING_TYPES:
            raise CreatorError("Ping must be none, everyone, here or a role.")
        if ping_type == "role":
            if not role_id or guild.get_role(int(role_id)) is None:
                raise CreatorError("I couldn't find that role.")
        return ping_type

    @staticmethod
    def _clean_message(message: str | None) -> str | None:
        text = (message or "").strip()
        if not text or text == DEFAULT_MESSAGE:
            return None
        if len(text) > 1500:
            raise CreatorError("That message is too long (max 1500 characters).")
        return text

    async def update_alert(self, guild: discord.Guild, num: int, **fields: Any) -> Any:
        alert = await self.get_alert(guild.id, num)
        if alert is None:
            raise CreatorError("I couldn't find that alert.")
        allowed = {"discord_channel_id", "ping_type", "ping_role_id", "message", "enabled"}
        if set(fields) - allowed:
            raise ValueError("bad fields")
        if "ping_type" in fields:
            role_id = fields.get("ping_role_id", alert["ping_role_id"])
            fields["ping_type"] = self._check_ping(guild, fields["ping_type"], role_id)
            if fields["ping_type"] != "role":
                fields["ping_role_id"] = None
        if "message" in fields:
            fields["message"] = self._clean_message(fields["message"])
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            await self.bot.db.db.execute(
                f"UPDATE creator_alerts SET {sets} WHERE id = ?", (*fields.values(), alert["id"])
            )
            await self.bot.db.db.commit()
        return await self.get_alert(guild.id, num)

    async def remove_alert(self, guild_id: int, num: int) -> bool:
        alert = await self.get_alert(guild_id, num)
        if alert is None:
            return False
        await self.bot.db.db.execute("DELETE FROM creator_seen WHERE alert_id = ?", (alert["id"],))
        await self.bot.db.db.execute("DELETE FROM creator_alerts WHERE id = ?", (alert["id"],))
        await self.bot.db.db.commit()
        return True

    async def find_alert(self, guild_id: int, target: str) -> Any:
        """Look an alert up by its number (3 or #3) or by the channel link it was made from."""
        t = (target or "").strip()
        num_text = t.lstrip("#")
        if num_text.isdigit():
            alert = await self.get_alert(guild_id, int(num_text))
            if alert is None:
                raise CreatorError(f"There's no alert #{num_text}. Use `.creator list` to see them.")
            return alert
        cid = await self.resolve_channel(t)
        for r in await self.list_alerts(guild_id):
            if r["yt_channel_id"] == cid:
                return r
        raise CreatorError("This server has no alert for that channel. Use `.creator list` to see them.")

    # -- display / posting helpers
    def warnings_for(self, guild: discord.Guild, alert: Any) -> list[str]:
        channel = guild.get_channel(int(alert["discord_channel_id"]))
        role = guild.get_role(int(alert["ping_role_id"])) if alert["ping_role_id"] else None
        return permission_warnings(guild, channel, alert["ping_type"], role)

    def render(self, alert: Any, video: Video, channel_name: str | None = None) -> str:
        return format_message(
            alert["message"],
            title=video.title,
            url=video.url,
            channel=channel_name or alert["yt_name"] or "this channel",
            ping_type=alert["ping_type"],
            role_id=alert["ping_role_id"],
        )

    async def _post(self, guild: discord.Guild, alert: Any, video: Video, *, test: bool = False) -> None:
        channel = guild.get_channel(int(alert["discord_channel_id"]))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise CreatorError("The Discord channel for this alert is missing.")
        if test:
            text = "**Test alert** (no ping was sent)\n" + format_message(
                alert["message"], title=video.title, url=video.url, channel=alert["yt_name"] or "this channel",
                ping_type="none", role_id=None,
            ).replace("@everyone", "everyone").replace("@here", "here")
            mentions = discord.AllowedMentions.none()
        else:
            text = self.render(alert, video)
            mentions = allowed_mentions_for(alert["ping_type"], alert["ping_role_id"])
        try:
            await channel.send(text[:2000], allowed_mentions=mentions)
        except discord.Forbidden as err:
            raise CreatorError(f"I'm not allowed to send messages in #{channel.name}.") from err
        except discord.HTTPException as err:
            raise CreatorError("Discord rejected the message. Try again in a moment.") from err

    async def send_test(self, guild: discord.Guild, alert: Any) -> Video:
        feed = await self.fetch_feed(alert["yt_channel_id"])
        if not feed.videos:
            raise CreatorError("That channel has no public videos yet.")
        video = feed.videos[0]
        await self._post(guild, alert, video, test=True)
        return video

    # -- polling
    @tasks.loop(minutes=POLL_MINUTES)
    async def poll(self) -> None:
        try:
            cur = await self.bot.db.db.execute("SELECT * FROM creator_alerts WHERE enabled = 1")
            rows = await cur.fetchall()
        except Exception:
            log.exception("Creator alerts: could not read alerts")
            return
        by_channel: dict[str, list[Any]] = {}
        for r in rows:
            by_channel.setdefault(r["yt_channel_id"], []).append(r)
        for cid, alerts in by_channel.items():
            try:
                feed = await self.fetch_feed(cid)
            except CreatorError as err:
                log.info("Creator alerts: feed %s skipped (%s)", cid, err)
                continue
            except Exception:
                log.exception("Creator alerts: feed %s failed", cid)
                continue
            for alert in alerts:
                try:
                    await self._process(alert, feed)
                except Exception:
                    log.exception("Creator alerts: alert %s failed", alert["id"])

    @poll.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _process(self, alert: Any, feed: Feed) -> None:
        seen = await self._seen(int(alert["id"]))
        fresh = unseen_videos(feed.videos, seen)
        if not fresh:
            return
        # Mark everything first so a crash can never cause a repeat post.
        await self._mark_seen(int(alert["id"]), [v.video_id for v in fresh])
        guild = self.bot.get_guild(int(alert["guild_id"]))
        if guild is None:
            return
        for video in fresh[-MAX_POSTS_PER_POLL:]:
            try:
                await self._post(guild, alert, video)
            except CreatorError as err:
                log.info("Creator alerts: could not post for alert %s: %s", alert["id"], err)
                break

    # -- commands
    @staticmethod
    def _parse_ping(guild: discord.Guild, raw: str | None) -> tuple[str, int | None]:
        text = (raw or "none").strip()
        low = text.lower().lstrip("@")
        if low in {"none", "off", "no", ""}:
            return "none", None
        if low == "everyone":
            return "everyone", None
        if low == "here":
            return "here", None
        m = re.fullmatch(r"<@&(\d{15,20})>|(\d{15,20})", text)
        role = guild.get_role(int(m.group(1) or m.group(2))) if m else None
        if role is None:
            role = discord.utils.find(lambda r: r.name.lower() == text.lstrip("@").lower(), guild.roles)
        if role is None or role.is_default():
            raise CreatorError("Ping must be `none`, `everyone`, `here`, or a role like @Subscribers.")
        return "role", role.id

    def _describe(self, guild: discord.Guild, a: Any) -> str:
        channel = guild.get_channel(int(a["discord_channel_id"]))
        where = channel.mention if channel else "*(missing channel)*"
        if a["ping_type"] == "role":
            role = guild.get_role(int(a["ping_role_id"] or 0))
            ping = f"@{role.name}" if role else "a deleted role"
        else:
            ping = {"none": "no ping", "everyone": "@everyone", "here": "@here"}[a["ping_type"]]
        state = "on" if a["enabled"] else "**off**"
        return f"`#{a['num']}` **{a['yt_name'] or a['yt_channel_id']}** → {where} · {ping} · {state}"

    async def _fail(self, ctx: commands.Context, err: CreatorError) -> None:
        await ctx.send(embed=make_embed("Creator Integration", str(err), color=DANGER), ephemeral=True)

    @commands.hybrid_group(
        name="creator",
        description="YouTube upload alerts for this server (Creator Integration).",
        invoke_without_command=True,
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def creator(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Creator Integration",
                "Post new YouTube uploads in a channel, with an optional @everyone, @here or role ping.\n\n"
                "• `.creator add <channel link or @handle> #channel [everyone|here|@role|none]`\n"
                "• `.creator list`\n"
                "• `.creator remove <link or #number>`\n"
                "• `.creator message <link or #number> <text>` — placeholders: " + PLACEHOLDERS + "\n"
                "• `.creator ping <link or #number> <everyone|here|@role|none>`\n"
                "• `.creator toggle <link or #number> on|off`\n"
                "• `.creator test <link or #number>` — posts the latest video now, without a ping\n\n"
                "You can also manage alerts on the dashboard under **Creator Integration**.",
            ),
            ephemeral=True,
        )

    @creator.command(name="add", description="Post new uploads from a YouTube channel in a Discord channel.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(link="YouTube channel link, @handle or channel ID", channel="Where to post", ping="none, everyone, here or a role")
    async def creator_add(self, ctx: commands.Context, link: str, channel: discord.TextChannel, ping: str = "none") -> None:
        assert ctx.guild
        async with ctx.typing():
            try:
                ping_type, role_id = self._parse_ping(ctx.guild, ping)
                alert, warns = await self.add_alert(ctx.guild, link, channel, ping_type, role_id)
            except CreatorError as err:
                await self._fail(ctx, err)
                return
        text = self._describe(ctx.guild, alert) + "\nOld videos won't be posted. New uploads will appear within about 5 minutes."
        if warns:
            text += "\n\n⚠️ " + "\n⚠️ ".join(warns)
        await ctx.send(embed=make_embed("Alert added", text, color=WARNING if warns else SUCCESS), allowed_mentions=discord.AllowedMentions.none())

    @creator.command(name="remove", description="Remove an alert.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(target="Channel link, @handle, or the alert number")
    async def creator_remove(self, ctx: commands.Context, target: str) -> None:
        assert ctx.guild
        try:
            alert = await self.find_alert(ctx.guild.id, target)
        except CreatorError as err:
            await self._fail(ctx, err)
            return
        await self.remove_alert(ctx.guild.id, int(alert["num"]))
        await ctx.send(embed=make_embed("Alert removed", f"Stopped alerts for **{alert['yt_name']}**.", color=SUCCESS))

    @creator.command(name="list", description="Show this server's YouTube alerts.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def creator_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.list_alerts(ctx.guild.id)
        if not rows:
            await ctx.send(embed=make_embed("Creator Integration", "No alerts yet. Add one with `.creator add <link> #channel`.", color=COLOR), ephemeral=True)
            return
        lines = [self._describe(ctx.guild, r) for r in rows]
        for r in rows:
            for w in self.warnings_for(ctx.guild, r):
                lines.append(f"⚠️ `#{r['num']}` {w}")
        await ctx.send(embed=make_embed("YouTube alerts", "\n".join(lines)[:4000], color=COLOR), allowed_mentions=discord.AllowedMentions.none())

    @creator.command(name="message", description="Set the alert message. Use {title} {url} {channel} {ping}.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(target="Channel link or alert number", text="Message. Placeholders: {title} {url} {channel} {ping}")
    async def creator_message(self, ctx: commands.Context, target: str, *, text: str) -> None:
        assert ctx.guild
        try:
            alert = await self.find_alert(ctx.guild.id, target)
            new = text.strip()
            if new.lower() in {"default", "reset"}:
                new = ""
            await self.update_alert(ctx.guild, int(alert["num"]), message=new)
        except CreatorError as err:
            await self._fail(ctx, err)
            return
        await ctx.send(embed=make_embed("Message updated", f"Alert `#{alert['num']}` will use your message. Say `.creator message {alert['num']} default` to reset it.", color=SUCCESS))

    @creator.command(name="ping", description="Choose who gets pinged: none, everyone, here or a role.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(target="Channel link or alert number", option="none, everyone, here or a role")
    async def creator_ping(self, ctx: commands.Context, target: str, option: str) -> None:
        assert ctx.guild
        try:
            alert = await self.find_alert(ctx.guild.id, target)
            ping_type, role_id = self._parse_ping(ctx.guild, option)
            alert = await self.update_alert(ctx.guild, int(alert["num"]), ping_type=ping_type, ping_role_id=role_id)
        except CreatorError as err:
            await self._fail(ctx, err)
            return
        warns = self.warnings_for(ctx.guild, alert)
        text = self._describe(ctx.guild, alert)
        if warns:
            text += "\n\n⚠️ " + "\n⚠️ ".join(warns)
        await ctx.send(embed=make_embed("Ping updated", text, color=WARNING if warns else SUCCESS), allowed_mentions=discord.AllowedMentions.none())

    @creator.command(name="toggle", description="Turn an alert on or off.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(target="Channel link or alert number", state="on or off")
    async def creator_toggle(self, ctx: commands.Context, target: str, state: str) -> None:
        assert ctx.guild
        if state.lower() not in {"on", "off"}:
            await self._fail(ctx, CreatorError("Say `on` or `off`."))
            return
        try:
            alert = await self.find_alert(ctx.guild.id, target)
            alert = await self.update_alert(ctx.guild, int(alert["num"]), enabled=1 if state.lower() == "on" else 0)
        except CreatorError as err:
            await self._fail(ctx, err)
            return
        await ctx.send(embed=make_embed("Alert updated", self._describe(ctx.guild, alert), color=SUCCESS), allowed_mentions=discord.AllowedMentions.none())

    @creator.command(name="test", description="Post the channel's latest video now, as a test (no ping).")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(target="Channel link or alert number")
    async def creator_test(self, ctx: commands.Context, target: str) -> None:
        assert ctx.guild
        async with ctx.typing():
            try:
                alert = await self.find_alert(ctx.guild.id, target)
                video = await self.send_test(ctx.guild, alert)
            except CreatorError as err:
                await self._fail(ctx, err)
                return
        await ctx.send(embed=make_embed("Test sent", f"Posted **{video.title}** in <#{alert['discord_channel_id']}>.", color=SUCCESS), ephemeral=True)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(CreatorAlerts(bot))
