"""Audit Logs: per-server event logging to a dedicated channel.

Each server picks one log channel and ticks the events it wants (dashboard
"Audit Logs" page or `.auditlog`). Nothing is logged until a channel is set and
an event is ticked. Moderator / reason come from Discord's audit log when the
bot has View Audit Log. This cog only reads events; it never acts on members
and does not touch the existing ban announcements, mod log or reports.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

log = logging.getLogger("socialize.audit")

# (key, label, group)
EVENTS: tuple[tuple[str, str, str], ...] = (
    ("member_join", "Member joins", "Members"),
    ("member_leave", "Member leaves", "Members"),
    ("nickname", "Nickname changes", "Members"),
    ("member_roles", "Roles added/removed on members", "Members"),
    ("ban", "Bans", "Moderation"),
    ("unban", "Unbans", "Moderation"),
    ("kick", "Kicks (via Discord audit log)", "Moderation"),
    ("timeout", "Timeouts", "Moderation"),
    ("role_create", "Role created", "Roles"),
    ("role_delete", "Role deleted", "Roles"),
    ("role_update", "Role updated", "Roles"),
    ("channel_create", "Channel created", "Channels"),
    ("channel_delete", "Channel deleted", "Channels"),
    ("channel_update", "Channel updated", "Channels"),
    ("thread_create", "Thread created", "Channels"),
    ("thread_delete", "Thread deleted", "Channels"),
    ("message_edit", "Message edits", "Messages"),
    ("message_delete", "Message deletes", "Messages"),
    ("bulk_delete", "Bulk message deletes", "Messages"),
    ("voice", "Voice join / leave / move", "Voice"),
    ("invite_create", "Invite created", "Invites"),
    ("invite_delete", "Invite deleted", "Invites"),
    ("emoji", "Emoji changes", "Server"),
    ("sticker", "Sticker changes", "Server"),
    ("server_update", "Server settings updated", "Server"),
)
EVENT_KEYS = tuple(e[0] for e in EVENTS)
EVENT_LABELS = {k: label for k, label, _ in EVENTS}
GROUP_ORDER = ("Members", "Moderation", "Roles", "Channels", "Messages", "Voice", "Invites", "Server")

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_settings (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    log_admins INTEGER NOT NULL DEFAULT 1,
    log_admin_deletes INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_events (
    guild_id INTEGER NOT NULL,
    event TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, event)
);
"""

NO_PINGS = discord.AllowedMentions.none()
AUDIT_LOOKUP_DELAY = 1.0
AUDIT_WINDOW_SECONDS = 20


def grouped_events() -> list[tuple[str, list[tuple[str, str]]]]:
    out: list[tuple[str, list[tuple[str, str]]]] = []
    for group in GROUP_ORDER:
        out.append((group, [(k, label) for k, label, g in EVENTS if g == group]))
    return out


def clip(text: str | None, limit: int = 1000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def who(obj: Any) -> str:
    if obj is None:
        return "Unknown"
    mention = getattr(obj, "mention", None) or f"<@{getattr(obj, 'id', 0)}>"
    return f"{mention} (`{getattr(obj, 'id', '?')}`)"


def by_user(obj: Any) -> str:
    """Responsible user as '@mention (name, id)'."""
    if obj is None:
        return "Unknown"
    uid = getattr(obj, "id", "?")
    mention = getattr(obj, "mention", None) or f"<@{uid}>"
    name = (
        getattr(obj, "display_name", None)
        or getattr(obj, "global_name", None)
        or getattr(obj, "name", None)
        or "Unknown"
    )
    return f"{mention} ({name}, {uid})"


UNKNOWN_BY = "Unknown (needs View Audit Log permission)"


def perm_names(perms: discord.Permissions) -> set[str]:
    return {name for name, value in perms if value}


class AuditLogs(commands.Cog):
    """Server audit logging to a chosen channel."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        # guild_id -> (channel_id | None, enabled event keys)
        self._cfg: dict[int, tuple[int | None, set[str]]] = {}
        # guild_id -> log admin/owner actions (missing means ON)
        self._log_admins: dict[int, bool] = {}
        self._log_admin_deletes: dict[int, bool] = {}

    # ---------- storage ----------
    async def cog_load(self) -> None:
        await self.bot.db.db.executescript(SCHEMA)
        await self._migrate_log_admins()
        await self._load_all()

    async def _load_all(self) -> None:
        cfg: dict[int, tuple[int | None, set[str]]] = {}
        cur = await self.bot.db.db.execute(
            "SELECT guild_id, channel_id, log_admins, log_admin_deletes FROM audit_settings"
        )
        log_admins: dict[int, bool] = {}
        log_admin_deletes: dict[int, bool] = {}
        for row in await cur.fetchall():
            gid = int(row[0])
            cfg[gid] = (int(row[1]) if row[1] else None, set())
            log_admins[gid] = bool(row[2]) if row[2] is not None else True
            log_admin_deletes[gid] = bool(row[3]) if row[3] is not None else True
        cur = await self.bot.db.db.execute("SELECT guild_id, event FROM audit_events WHERE enabled = 1")
        for row in await cur.fetchall():
            gid = int(row[0])
            if row[1] in EVENT_KEYS:
                cfg.setdefault(gid, (None, set()))[1].add(str(row[1]))
        self._cfg = cfg
        self._log_admins = log_admins
        self._log_admin_deletes = log_admin_deletes

    def get_config(self, guild_id: int) -> tuple[int | None, set[str]]:
        channel_id, events = self._cfg.get(int(guild_id), (None, set()))
        return channel_id, set(events)

    async def set_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self.bot.db.db.execute(
            """INSERT INTO audit_settings (guild_id, channel_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
            (int(guild_id), channel_id),
        )
        await self.bot.db.db.commit()
        _old, events = self._cfg.get(int(guild_id), (None, set()))
        self._cfg[int(guild_id)] = (channel_id, events)

    async def set_events(self, guild_id: int, events: set[str]) -> None:
        events = {e for e in events if e in EVENT_KEYS}
        await self.bot.db.db.executemany(
            """INSERT INTO audit_events (guild_id, event, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, event) DO UPDATE SET enabled = excluded.enabled""",
            [(int(guild_id), key, 1 if key in events else 0) for key in EVENT_KEYS],
        )
        await self.bot.db.db.commit()
        channel_id, _old = self._cfg.get(int(guild_id), (None, set()))
        self._cfg[int(guild_id)] = (channel_id, events)

    async def _migrate_log_admins(self) -> None:
        cur = await self.bot.db.db.execute("PRAGMA table_info(audit_settings)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        if "log_admins" not in cols:
            await self.bot.db.db.execute(
                "ALTER TABLE audit_settings ADD COLUMN log_admins INTEGER NOT NULL DEFAULT 1"
            )
            await self.bot.db.db.commit()
        cur = await self.bot.db.db.execute("PRAGMA table_info(audit_settings)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        if "log_admin_deletes" not in cols:
            await self.bot.db.db.execute(
                "ALTER TABLE audit_settings ADD COLUMN log_admin_deletes INTEGER NOT NULL DEFAULT 1"
            )
            await self.bot.db.db.commit()

    def log_admins(self, guild_id: int) -> bool:
        return self._log_admins.get(int(guild_id), True)

    async def set_log_admins(self, guild_id: int, enabled: bool) -> None:
        await self.bot.db.db.execute(
            """INSERT INTO audit_settings (guild_id, channel_id, log_admins) VALUES (?, NULL, ?)
               ON CONFLICT(guild_id) DO UPDATE SET log_admins = excluded.log_admins""",
            (int(guild_id), 1 if enabled else 0),
        )
        await self.bot.db.db.commit()
        self._log_admins[int(guild_id)] = bool(enabled)

    def log_admin_deletes(self, guild_id: int) -> bool:
        return self._log_admin_deletes.get(int(guild_id), True)

    async def set_log_admin_deletes(self, guild_id: int, enabled: bool) -> None:
        await self.bot.db.db.execute(
            "INSERT INTO audit_settings (guild_id, channel_id, log_admin_deletes) VALUES (?, NULL, ?)"
            " ON CONFLICT(guild_id) DO UPDATE SET log_admin_deletes = excluded.log_admin_deletes",
            (int(guild_id), 1 if enabled else 0),
        )
        await self.bot.db.db.commit()
        self._log_admin_deletes[int(guild_id)] = bool(enabled)

    def _omit_admin_delete(self, guild: discord.Guild, user: Any) -> bool:
        return (not self.log_admin_deletes(guild.id)) and self._is_privileged_actor(guild, user)

    def _is_privileged_actor(self, guild: discord.Guild, user: Any) -> bool:
        if user is None:
            return False
        uid = getattr(user, "id", None)
        owner_id = getattr(guild, "owner_id", None)
        if uid is not None and owner_id is not None and int(uid) == int(owner_id):
            return True
        member = user
        if getattr(member, "guild_permissions", None) is None and uid is not None:
            getter = getattr(guild, "get_member", None)
            member = getter(int(uid)) if getter else None
        perms = getattr(member, "guild_permissions", None)
        return bool(perms is not None and getattr(perms, "administrator", False))

    def _omit_actor(self, guild: discord.Guild, user: Any) -> bool:
        return (not self.log_admins(guild.id)) and self._is_privileged_actor(guild, user)

    def _channel_for(self, guild: discord.Guild, event: str) -> discord.TextChannel | None:
        channel_id, events = self._cfg.get(guild.id, (None, set()))
        if not channel_id or event not in events:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    def wants(self, guild: discord.Guild, event: str) -> bool:
        return self._channel_for(guild, event) is not None

    # ---------- posting ----------
    async def _post(self, guild: discord.Guild, event: str, embed: discord.Embed, *, entry: Any = None, actor: Any = None, ignore_log_admins: bool = False) -> bool:
        who_did = actor if actor is not None else (getattr(entry, "user", None) if entry is not None else None)
        if (not ignore_log_admins) and self._omit_actor(guild, who_did):
            return False
        channel = self._channel_for(guild, event)
        if channel is None:
            return False
        embed.set_footer(text=f"Audit log · {EVENT_LABELS[event]}")
        embed.timestamp = datetime.now(timezone.utc)
        try:
            await channel.send(embed=embed, allowed_mentions=NO_PINGS)
            return True
        except discord.HTTPException:
            return False

    async def _audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int | None = None,
        *,
        channel_id: int | None = None,
    ) -> discord.AuditLogEntry | None:
        """Newest recent audit entry for this action (and target), or None if unavailable."""
        me = guild.me
        if me is None or not me.guild_permissions.view_audit_log:
            return None
        await asyncio.sleep(AUDIT_LOOKUP_DELAY)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=AUDIT_WINDOW_SECONDS)
        try:
            async for entry in guild.audit_logs(limit=10, action=action):
                if entry.created_at < cutoff:
                    break
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                if channel_id is not None:
                    extra_channel = getattr(entry.extra, "channel", None)
                    if getattr(extra_channel, "id", None) != channel_id:
                        continue
                return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    @staticmethod
    def _by(entry: discord.AuditLogEntry | None, guild: discord.Guild, *, message_delete: bool = False) -> str:
        if entry is not None and getattr(entry, "user", None) is not None:
            return by_user(entry.user)
        if message_delete:
            return "author or unknown"
        return UNKNOWN_BY

    @staticmethod
    def _reason(entry: discord.AuditLogEntry | None) -> str | None:
        return clip(entry.reason, 500) if entry is not None and entry.reason else None

    def _mod_embed(self, title: str, color: int, guild: discord.Guild, target: Any, entry, extra: str = "") -> discord.Embed:
        lines = [f"**Who:** {who(target)}", f"**By:** {self._by(entry, guild)}"]
        reason = self._reason(entry)
        if reason:
            lines.append(f"**Reason:** {reason}")
        if extra:
            lines.append(extra)
        return make_embed(title, "\n".join(lines), color=color)

    # ---------- members ----------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self.wants(member.guild, "member_join"):
            return
        created = int(member.created_at.timestamp())
        e = make_embed(
            "Member joined",
            f"**Who:** {who(member)}\n**Account created:** <t:{created}:R> (<t:{created}:f>)\n**Members now:** {member.guild.member_count}",
            color=SUCCESS,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        await self._post(member.guild, "member_join", e)

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or not (self.wants(guild, "member_leave") or self.wants(guild, "kick")):
            return
        user = payload.user
        kick_entry = await self._audit_entry(guild, discord.AuditLogAction.kick, user.id)
        if kick_entry is not None:
            if self.wants(guild, "kick"):
                await self._post(guild, "kick", self._mod_embed("Member kicked", DANGER, guild, user, kick_entry), entry=kick_entry)
            return  # a kick is not a voluntary leave
        if not self.wants(guild, "member_leave"):
            return
        # A ban also fires a remove event; the ban has its own log line.
        ban_entry = await self._audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if ban_entry is not None:
            return
        member = guild.get_member(user.id)
        joined = ""
        roles = ""
        if isinstance(member, discord.Member):
            if member.joined_at:
                joined = f"\n**Joined:** <t:{int(member.joined_at.timestamp())}:R>"
            names = [r.mention for r in member.roles if not r.is_default()]
            if names:
                roles = "\n**Roles:** " + clip(" ".join(names), 800)
        e = make_embed("Member left", f"**Who:** {who(user)}{joined}{roles}", color=WARNING)
        e.set_thumbnail(url=user.display_avatar.url)
        await self._post(guild, "member_leave", e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User) -> None:
        if not self.wants(guild, "ban"):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.ban, user.id)
        await self._post(guild, "ban", self._mod_embed("Member banned", DANGER, guild, user, entry), entry=entry)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.abc.User) -> None:
        if not self.wants(guild, "unban"):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.unban, user.id)
        await self._post(guild, "unban", self._mod_embed("Member unbanned", SUCCESS, guild, user, entry), entry=entry)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild
        if before.nick != after.nick and self.wants(guild, "nickname"):
            entry = await self._audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            e = self._mod_embed(
                "Nickname changed", COLOR, guild, after, entry,
                f"**Before:** {before.nick or '*none*'}\n**After:** {after.nick or '*none*'}",
            )
            await self._post(guild, "nickname", e, entry=entry)
        if before.roles != after.roles and self.wants(guild, "member_roles"):
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                entry = await self._audit_entry(guild, discord.AuditLogAction.member_role_update, after.id)
                extra = ""
                if added:
                    extra += "\n**Added:** " + " ".join(r.mention for r in added)
                if removed:
                    extra += "\n**Removed:** " + " ".join(r.mention for r in removed)
                e = self._mod_embed("Member roles changed", COLOR, guild, after, entry, extra.strip())
                await self._post(guild, "member_roles", e, entry=entry)
        if before.timed_out_until != after.timed_out_until and self.wants(guild, "timeout"):
            entry = await self._audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            if after.timed_out_until and after.timed_out_until > datetime.now(timezone.utc):
                until = int(after.timed_out_until.timestamp())
                e = self._mod_embed("Member timed out", WARNING, guild, after, entry, f"**Until:** <t:{until}:f> (<t:{until}:R>)")
            else:
                e = self._mod_embed("Timeout removed", SUCCESS, guild, after, entry)
            await self._post(guild, "timeout", e, entry=entry)

    # ---------- roles ----------
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        if not self.wants(role.guild, "role_create"):
            return
        entry = await self._audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        e = make_embed(
            "Role created",
            f"**Role:** {role.mention} (`{role.id}`)\n**By:** {self._by(entry, role.guild)}",
            color=SUCCESS,
        )
        await self._post(role.guild, "role_create", e, entry=entry)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        if not self.wants(role.guild, "role_delete"):
            return
        entry = await self._audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        e = make_embed(
            "Role deleted",
            f"**Role:** {role.name} (`{role.id}`)\n**By:** {self._by(entry, role.guild)}",
            color=DANGER,
        )
        await self._post(role.guild, "role_delete", e, entry=entry)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if not self.wants(after.guild, "role_update"):
            return
        changes: list[str] = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.colour != after.colour:
            changes.append(f"**Colour:** {before.colour} → {after.colour}")
        if before.hoist != after.hoist:
            changes.append(f"**Shown separately:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionable:** {before.mentionable} → {after.mentionable}")
        if before.permissions != after.permissions:
            old, new = perm_names(before.permissions), perm_names(after.permissions)
            if new - old:
                changes.append("**Permissions added:** " + ", ".join(sorted(new - old)))
            if old - new:
                changes.append("**Permissions removed:** " + ", ".join(sorted(old - new)))
        if not changes:
            return  # position-only moves are too noisy to log
        entry = await self._audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        e = make_embed(
            "Role updated",
            f"**Role:** {after.mention} (`{after.id}`)\n**By:** {self._by(entry, after.guild)}\n" + clip("\n".join(changes), 1500),
            color=COLOR,
        )
        await self._post(after.guild, "role_update", e, entry=entry)

    # ---------- channels / threads ----------
    @staticmethod
    def _chan(channel: Any) -> str:
        mention = getattr(channel, "mention", None) or f"#{getattr(channel, 'name', '?')}"
        kind = str(getattr(channel, "type", "channel")).replace("_", " ")
        return f"{mention} (`{channel.id}`) · {kind}"

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if not self.wants(channel.guild, "channel_create"):
            return
        entry = await self._audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        e = make_embed(
            "Channel created",
            f"**Channel:** {self._chan(channel)}\n**By:** {self._by(entry, channel.guild)}",
            color=SUCCESS,
        )
        await self._post(channel.guild, "channel_create", e, entry=entry)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not self.wants(channel.guild, "channel_delete"):
            return
        entry = await self._audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        kind = str(getattr(channel, "type", "channel")).replace("_", " ")
        e = make_embed(
            "Channel deleted",
            f"**Channel:** #{channel.name} (`{channel.id}`) · {kind}\n**By:** {self._by(entry, channel.guild)}",
            color=DANGER,
        )
        await self._post(channel.guild, "channel_delete", e, entry=entry)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if not self.wants(after.guild, "channel_update"):
            return
        changes: list[str] = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        for attr, label in (("topic", "Topic"), ("nsfw", "Age-restricted"), ("slowmode_delay", "Slowmode (s)"), ("bitrate", "Bitrate"), ("user_limit", "User limit")):
            if getattr(before, attr, None) != getattr(after, attr, None):
                changes.append(f"**{label}:** {clip(str(getattr(before, attr, None)), 200)} → {clip(str(getattr(after, attr, None)), 200)}")
        if getattr(before, "category_id", None) != getattr(after, "category_id", None):
            old = before.category.name if getattr(before, "category", None) else "none"
            new = after.category.name if getattr(after, "category", None) else "none"
            changes.append(f"**Category:** {old} → {new}")
        if before.overwrites != after.overwrites:
            changes.append("**Permission overwrites changed**")
        if not changes:
            return
        entry = await self._audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        e = make_embed(
            "Channel updated",
            f"**Channel:** {self._chan(after)}\n**By:** {self._by(entry, after.guild)}\n" + clip("\n".join(changes), 1500),
            color=COLOR,
        )
        await self._post(after.guild, "channel_update", e, entry=entry)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if not self.wants(thread.guild, "thread_create"):
            return
        owner = thread.owner or (thread.guild.get_member(thread.owner_id) if thread.owner_id else None)
        parent = f"<#{thread.parent_id}>" if thread.parent_id else "unknown"
        e = make_embed(
            "Thread created",
            f"**Thread:** {thread.mention} (`{thread.id}`)\n**In:** {parent}\n**By:** {by_user(owner) if owner else (f'<@{thread.owner_id}>' if thread.owner_id else UNKNOWN_BY)}",
            color=SUCCESS,
        )
        await self._post(thread.guild, "thread_create", e, actor=owner)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        if not self.wants(thread.guild, "thread_delete"):
            return
        entry = await self._audit_entry(thread.guild, discord.AuditLogAction.thread_delete, thread.id)
        parent = f"<#{thread.parent_id}>" if thread.parent_id else "unknown"
        e = make_embed(
            "Thread deleted",
            f"**Thread:** {thread.name} (`{thread.id}`)\n**In:** {parent}\n**By:** {self._by(entry, thread.guild)}",
            color=DANGER,
        )
        await self._post(thread.guild, "thread_delete", e, entry=entry)

    # ---------- messages ----------
    def _ignore_channel(self, guild: discord.Guild, channel_id: int) -> bool:
        return self._cfg.get(guild.id, (None, set()))[0] == channel_id  # never log the log channel

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None or not self.wants(guild, "message_edit") or self._ignore_channel(guild, payload.channel_id):
            return
        data = payload.data or {}
        if (data.get("author") or {}).get("bot"):
            return
        before = payload.cached_message
        new_content = data.get("content")
        if new_content is None:
            return
        if before is not None:
            if before.author.bot or before.content == new_content:
                return
        author = before.author if before is not None else None
        author_id = int((data.get("author") or {}).get("id") or 0) or (author.id if author else 0)
        jump = f"https://discord.com/channels/{guild.id}/{payload.channel_id}/{payload.message_id}"
        author_line = who(author) if author else (f"<@{author_id}> (`{author_id}`)" if author_id else "Unknown")
        lines = [
            f"**Who:** {author_line}",
            f"**Where:** <#{payload.channel_id}> · [jump to message]({jump})",
            f"**Before:** {clip(before.content) if before is not None else '*not cached*'}",
            f"**After:** {clip(new_content) or '*empty*'}",
        ]
        await self._post(guild, "message_edit", make_embed("Message edited", clip("\n".join(lines), 3800), color=COLOR))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None or not self.wants(guild, "message_delete") or self._ignore_channel(guild, payload.channel_id):
            return
        msg = payload.cached_message
        if msg is not None and msg.author.bot:
            return
        entry = None
        if msg is not None:
            entry = await self._audit_entry(guild, discord.AuditLogAction.message_delete, msg.author.id, channel_id=payload.channel_id)
        lines = [
            f"**Author:** {who(msg.author) if msg is not None else '*message not cached*'}",
            f"**Where:** <#{payload.channel_id}>",
            f"**By:** {self._by(entry, guild, message_delete=True)}",
        ]
        if msg is not None:
            lines.append(f"**Content:** {clip(msg.content) or '*no text*'}")
            if msg.attachments:
                lines.append("**Attachments:** " + clip(", ".join(a.filename for a in msg.attachments), 400))
        deleter = entry.user if entry is not None and getattr(entry, "user", None) is not None else (msg.author if msg is not None else None)
        if self._omit_admin_delete(guild, deleter):
            return
        await self._post(
            guild, "message_delete", make_embed("Message deleted", clip("\n".join(lines), 3800), color=DANGER),
            entry=entry, actor=deleter, ignore_log_admins=True,
        )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None or not self.wants(guild, "bulk_delete") or self._ignore_channel(guild, payload.channel_id):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.message_bulk_delete, payload.channel_id)
        e = make_embed(
            "Messages bulk deleted",
            f"**Count:** {len(payload.message_ids)}\n**Where:** <#{payload.channel_id}>\n**By:** {self._by(entry, guild)}",
            color=DANGER,
        )
        deleter = entry.user if entry is not None else None
        if self._omit_admin_delete(guild, deleter):
            return
        await self._post(guild, "bulk_delete", e, entry=entry, ignore_log_admins=True)

    # ---------- voice ----------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        guild = member.guild
        if member.bot or not self.wants(guild, "voice") or before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            title, color, text = "Voice join", SUCCESS, f"**Who:** {who(member)}\n**Joined:** {after.channel.mention}"
        elif before.channel is not None and after.channel is None:
            title, color, text = "Voice leave", WARNING, f"**Who:** {who(member)}\n**Left:** {before.channel.mention}"
        else:
            title, color = "Voice move", COLOR
            text = f"**Who:** {who(member)}\n**From:** {before.channel.mention}\n**To:** {after.channel.mention}"
        await self._post(guild, "voice", make_embed(title, text, color=color))

    # ---------- invites ----------
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        guild = invite.guild
        if not isinstance(guild, discord.Guild) or not self.wants(guild, "invite_create"):
            return
        uses = "unlimited" if not invite.max_uses else str(invite.max_uses)
        age = "never expires" if not invite.max_age else f"expires in {invite.max_age // 60} min"
        e = make_embed(
            "Invite created",
            f"**Code:** `{invite.code}`\n**By:** {by_user(invite.inviter) if invite.inviter else UNKNOWN_BY}\n"
            f"**Channel:** {getattr(invite.channel, 'mention', 'unknown')}\n**Max uses:** {uses} · {age}",
            color=SUCCESS,
        )
        await self._post(guild, "invite_create", e, actor=invite.inviter)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        guild = invite.guild
        if not isinstance(guild, discord.Guild) or not self.wants(guild, "invite_delete"):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.invite_delete)
        e = make_embed(
            "Invite deleted",
            f"**Code:** `{invite.code}`\n**Channel:** {getattr(invite.channel, 'mention', 'unknown')}\n**By:** {self._by(entry, guild)}",
            color=DANGER,
        )
        await self._post(guild, "invite_delete", e, entry=entry)

    # ---------- emoji / stickers / server ----------
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after) -> None:
        if not self.wants(guild, "emoji"):
            return
        old = {e.id: e for e in before}
        new = {e.id: e for e in after}
        lines = [f"**Added:** {new[i]} `:{new[i].name}:`" for i in new if i not in old]
        lines += [f"**Removed:** `:{old[i].name}:`" for i in old if i not in new]
        lines += [f"**Renamed:** `:{old[i].name}:` → {new[i]} `:{new[i].name}:`" for i in new if i in old and old[i].name != new[i].name]
        if not lines:
            return
        action = discord.AuditLogAction.emoji_create if len(after) > len(before) else (
            discord.AuditLogAction.emoji_delete if len(after) < len(before) else discord.AuditLogAction.emoji_update)
        entry = await self._audit_entry(guild, action)
        await self._post(guild, "emoji", make_embed("Emoji changed", clip("\n".join(lines) + f"\n**By:** {self._by(entry, guild)}", 3800), color=COLOR), entry=entry)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before, after) -> None:
        if not self.wants(guild, "sticker"):
            return
        old = {s.id: s for s in before}
        new = {s.id: s for s in after}
        lines = [f"**Added:** {new[i].name}" for i in new if i not in old]
        lines += [f"**Removed:** {old[i].name}" for i in old if i not in new]
        lines += [f"**Renamed:** {old[i].name} → {new[i].name}" for i in new if i in old and old[i].name != new[i].name]
        if not lines:
            return
        action = discord.AuditLogAction.sticker_create if len(after) > len(before) else (
            discord.AuditLogAction.sticker_delete if len(after) < len(before) else discord.AuditLogAction.sticker_update)
        entry = await self._audit_entry(guild, action)
        await self._post(guild, "sticker", make_embed("Stickers changed", clip("\n".join(lines) + f"\n**By:** {self._by(entry, guild)}", 3800), color=COLOR), entry=entry)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        if not self.wants(after, "server_update"):
            return
        changes: list[str] = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.icon != after.icon:
            changes.append("**Icon changed**")
        if before.banner != after.banner:
            changes.append("**Banner changed**")
        if before.owner_id != after.owner_id:
            changes.append(f"**Owner:** <@{before.owner_id}> → <@{after.owner_id}>")
        for attr, label in (
            ("verification_level", "Verification level"),
            ("explicit_content_filter", "Content filter"),
            ("default_notifications", "Default notifications"),
            ("afk_timeout", "AFK timeout (s)"),
        ):
            if getattr(before, attr) != getattr(after, attr):
                changes.append(f"**{label}:** {getattr(before, attr)} → {getattr(after, attr)}")
        for attr, label in (("afk_channel", "AFK channel"), ("system_channel", "System channel"), ("rules_channel", "Rules channel")):
            b, a = getattr(before, attr), getattr(after, attr)
            if (b.id if b else None) != (a.id if a else None):
                changes.append(f"**{label}:** {b.mention if b else 'none'} → {a.mention if a else 'none'}")
        if not changes:
            return
        entry = await self._audit_entry(after, discord.AuditLogAction.guild_update)
        e = make_embed("Server settings updated", clip("\n".join(changes) + f"\n**By:** {self._by(entry, after)}", 3800), color=COLOR)
        await self._post(after, "server_update", e, entry=entry)

    # ---------- commands ----------
    @commands.hybrid_group(
        name="auditlog",
        aliases=["auditlogs"],
        description="Choose where server audit logs go and which events are logged.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog(self, ctx: commands.Context) -> None:
        await self._show_list(ctx)

    @auditlog.command(name="channel", description="Set the audit log channel (omit to clear).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog_channel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        if channel is not None:
            perms = channel.permissions_for(ctx.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await ctx.send(embed=make_embed("Can't use that channel", f"I need View Channel, Send Messages and Embed Links in {channel.mention}.", color=DANGER))
                return
        await self.set_channel(ctx.guild.id, channel.id if channel else None)
        if channel is None:
            await ctx.send(embed=make_embed("Audit logs paused", "The log channel was cleared, so nothing is logged.", color=WARNING))
        else:
            _c, events = self.get_config(ctx.guild.id)
            hint = "" if events else "\nNo events are ticked yet: use the dashboard Audit Logs page or `auditlog enable <event>`."
            await ctx.send(embed=make_embed("Audit log channel set", f"Logs will be posted in {channel.mention}.{hint}", color=SUCCESS))

    @auditlog.command(name="list", description="Show the audit log channel and which events are on or off.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog_list(self, ctx: commands.Context) -> None:
        await self._show_list(ctx)

    async def _show_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        channel_id, events = self.get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        head = f"**Channel:** {channel.mention}" if channel else "**Channel:** not set (nothing is logged until one is set)"
        admins = "logged" if self.log_admins(ctx.guild.id) else "not logged"
        head += f"\n**Admins & owner:** {admins} (`auditlog admins on|off`)"
        lines = []
        for group, items in grouped_events():
            lines.append(f"**{group}**: " + ", ".join(f"{'✅' if k in events else '▫️'} `{k}`" for k, _label in items))
        e = make_embed("Audit logs", head + "\n\n" + "\n".join(lines) + "\n\nTurn events on/off: `auditlog enable <event|all>` · `auditlog disable <event|all>`")
        await ctx.send(embed=e)

    async def _toggle(self, ctx: commands.Context, event: str, on: bool) -> None:
        assert ctx.guild
        event = event.lower().strip()
        _c, events = self.get_config(ctx.guild.id)
        if event == "all":
            events = set(EVENT_KEYS) if on else set()
        elif event in EVENT_KEYS:
            events.add(event) if on else events.discard(event)
        else:
            await ctx.send(embed=make_embed("Unknown event", "Valid events: " + ", ".join(f"`{k}`" for k in EVENT_KEYS) + ", `all`", color=WARNING))
            return
        await self.set_events(ctx.guild.id, events)
        await ctx.send(embed=make_embed("Audit logs updated", f"`{event}` is now **{'on' if on else 'off'}**.", color=SUCCESS))

    @auditlog.command(name="admins", description="Log actions by admins and the server owner (on or off).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog_admins(self, ctx: commands.Context, state: str) -> None:
        assert ctx.guild
        key = state.lower().strip()
        if key not in {"on", "off"}:
            await ctx.send(embed=make_embed("Use on or off", "Try `auditlog admins on` or `auditlog admins off`.", color=WARNING))
            return
        on = key == "on"
        await self.set_log_admins(ctx.guild.id, on)
        if on:
            msg = "Actions by admins and the server owner will be logged."
        else:
            msg = "Actions by admins and the server owner will not be logged."
        await ctx.send(embed=make_embed("Audit logs updated", msg, color=SUCCESS))

    @auditlog.command(name="enable", aliases=["on"], description="Turn an audit event on (or 'all').")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog_enable(self, ctx: commands.Context, event: str) -> None:
        await self._toggle(ctx, event, True)

    @auditlog.command(name="disable", aliases=["off"], description="Turn an audit event off (or 'all').")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def auditlog_disable(self, ctx: commands.Context, event: str) -> None:
        await self._toggle(ctx, event, False)

    async def send_test(self, guild: discord.Guild) -> bool:
        channel_id, _events = self.get_config(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return False
        try:
            await channel.send(
                embed=make_embed("Audit log test", "This channel is set as the audit log channel. Ticked events will appear here.", color=SUCCESS),
                allowed_mentions=NO_PINGS,
            )
            return True
        except discord.HTTPException:
            return False


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(AuditLogs(bot))
