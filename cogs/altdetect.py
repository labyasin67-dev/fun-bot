"""Alt-account detection, alerts, and staff review buttons."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.moderation import hierarchy_error, try_dm
from cogs.v2 import build_game_layout, build_report_layout
from utils import DANGER, SUCCESS, WARNING

if TYPE_CHECKING:
    from main import SocializeBot

ACTIONS = ("none", "log", "timeout", "kick", "quarantine")
BAN_COMPARE_WINDOW = 6 * 3600  # account created within 6h of a recently banned user
BAN_LOOKBACK = 14 * 24 * 3600
JOIN_SOON_STRONG = 3600
JOIN_SOON_MILD = 24 * 3600
LOW_MAX = 29
MEDIUM_MAX = 59


def has_default_avatar(user: discord.abc.User) -> bool:
    base = getattr(user, "_user", user)
    return getattr(base, "avatar", None) is None


def _digit_signal(name: str) -> bool:
    if not name:
        return False
    digits = sum(ch.isdigit() for ch in name)
    return digits >= 4 or (len(name) >= 5 and digits / len(name) >= 0.4) or bool(re.search(r"\d{4,}", name))


def _random_looking(name: str) -> bool:
    if not name:
        return False
    letters = [ch.lower() for ch in name if ch.isalpha()]
    if len(letters) >= 6:
        vowels = sum(ch in "aeiou" for ch in letters)
        if vowels / len(letters) < 0.2:
            return True
        transitions = 0
        for i in range(len(name) - 1):
            a, b = name[i], name[i + 1]
            if a.isalnum() and b.isalnum() and a.isalpha() != b.isalpha():
                transitions += 1
        if transitions >= 3 and any(ch.isdigit() for ch in name):
            return True
    if re.search(r"[^aeiouAEIOU0-9_\s]{5,}", name):
        return True
    return False


def username_signals(user: discord.abc.User) -> list[str]:
    names = {user.name}
    global_name = getattr(user, "global_name", None)
    if global_name:
        names.add(global_name)
    display = getattr(user, "display_name", None)
    if display:
        names.add(display)
    reasons: list[str] = []
    if any(_digit_signal(name) for name in names):
        reasons.append("Username has a lot of digits")
    if any(_random_looking(name) for name in names):
        reasons.append("Username looks random or generated")
    return reasons


def verdict_for(score: int) -> str:
    if score >= 60:
        return "High risk"
    if score >= 30:
        return "Medium risk"
    return "Low risk"


def verdict_color(verdict: str) -> int:
    if verdict.startswith("High"):
        return DANGER
    if verdict.startswith("Medium"):
        return WARNING
    return SUCCESS


@dataclass
class AltAssessment:
    score: int
    verdict: str
    reasons: list[str]
    age: timedelta
    default_avatar: bool
    created_at: datetime
    joined_at: datetime | None


def build_alert_view(user_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(AltActionButton("kick", user_id, "Kick", discord.ButtonStyle.secondary))
    view.add_item(AltActionButton("ban", user_id, "Ban", discord.ButtonStyle.danger))
    view.add_item(AltActionButton("timeout", user_id, "Timeout 1h", discord.ButtonStyle.secondary))
    view.add_item(AltActionButton("safe", user_id, "Mark Safe", discord.ButtonStyle.success))
    return view


class AltActionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"alt:(?P<action>kick|ban|timeout|safe):(?P<user_id>[0-9]+)"):
    def __init__(self, action: str, user_id: int, label: str | None = None, style: discord.ButtonStyle | None = None) -> None:
        labels = {"kick": "Kick", "ban": "Ban", "timeout": "Timeout 1h", "safe": "Mark Safe"}
        styles = {
            "kick": discord.ButtonStyle.secondary,
            "ban": discord.ButtonStyle.danger,
            "timeout": discord.ButtonStyle.secondary,
            "safe": discord.ButtonStyle.success,
        }
        self.action = action
        self.user_id = user_id
        super().__init__(
            discord.ui.Button(
                label=label or labels[action],
                style=style or styles[action],
                custom_id=f"alt:{action}:{user_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: object) -> AltActionButton:
        return cls(str(match["action"]), int(match["user_id"]))  # type: ignore[index]

    async def callback(self, interaction: discord.Interaction) -> None:
        await handle_alert_action(interaction, self.action, self.user_id)


def _button_permission_error(member: discord.Member, action: str) -> str | None:
    perms = member.guild_permissions
    if action == "kick" and not perms.kick_members:
        return "You need the Kick Members permission."
    if action == "ban" and not perms.ban_members:
        return "You need the Ban Members permission."
    if action == "timeout" and not perms.moderate_members:
        return "You need the Moderate Members permission."
    if action == "safe" and not (perms.manage_guild or perms.moderate_members or perms.kick_members or perms.ban_members):
        return "You need Manage Server or a moderation permission."
    return None


async def live_alt_status(guild: discord.Guild, user_id: int, db) -> str:
    if await db.is_alt_whitelisted(guild.id, user_id):
        return "whitelisted"
    member = guild.get_member(user_id)
    if member is not None:
        if member.is_timed_out():
            return "timed_out"
        cfg = await db.get_alt_config(guild.id)
        role_id = cfg["quarantine_role_id"] if cfg else None
        if role_id:
            role = guild.get_role(int(role_id))
            if role and role in member.roles:
                return "quarantined"
        return "in_server"
    try:
        await guild.fetch_ban(discord.Object(id=user_id))
        return "banned"
    except discord.NotFound:
        return "left"
    except discord.HTTPException:
        return "left"


STATUS_LABELS = {
    "in_server": "In server",
    "kicked": "Kicked",
    "banned": "Banned",
    "timed_out": "Timed out",
    "quarantined": "Quarantined",
    "whitelisted": "Whitelisted",
    "left": "Left the server",
}


async def apply_alt_review(
    bot: "SocializeBot",
    guild: discord.Guild,
    action: str,
    user_id: int,
    *,
    actor: discord.Member | None = None,
    flag_id: int | None = None,
    automatic: bool = False,
) -> tuple[bool, str, str | None]:
    """Apply a kick/ban/timeout/safe review. Returns (ok, message, status)."""
    if action not in {"kick", "ban", "timeout", "safe"}:
        return False, "Unknown action.", None
    me = guild.me
    target = guild.get_member(user_id)
    if actor is not None and not automatic:
        missing = _button_permission_error(actor, action)
        if missing:
            return False, missing, None
        if action != "safe" and target is not None and me is not None:
            err = hierarchy_error(actor, target, me)
            if err:
                return False, err, None
    if action != "safe":
        if target is None and action != "ban":
            return False, "That member is no longer in the server.", None
        if automatic and target is not None and me is not None:
            if target.id == guild.owner_id or target.top_role >= me.top_role:
                return False, "I can't moderate this member.", None
    who = actor.mention if actor is not None else "automatic action"
    reason = f"Alt-detect review by {actor}" if actor is not None else "Alt-detect auto action (high risk)"
    status = None
    try:
        if action == "kick":
            assert target is not None
            await try_dm(target, build_game_layout("You were kicked", f"You were kicked from **{guild.name}**.\nReason: Suspected alt account."))
            await target.kick(reason=reason)
            created = target.created_at.timestamp() if target.created_at else None
            await bot.db.add_alt_mod_action(guild.id, user_id, "kick", created)
            status = "kicked"
            summary = "Automatically kicked." if automatic else f"Kicked by {who}"
        elif action == "ban":
            user = target or await bot.fetch_user(user_id)
            if target:
                await try_dm(target, build_game_layout("You were banned", f"You were banned from **{guild.name}**.\nReason: Suspected alt account."))
            created = user.created_at.timestamp() if getattr(user, "created_at", None) else None
            await guild.ban(discord.Object(id=user_id), reason=reason, delete_message_seconds=0)
            await bot.db.add_alt_mod_action(guild.id, user_id, "ban", created)
            status = "banned"
            summary = "Automatically banned." if automatic else f"Banned by {who}"
        elif action == "timeout":
            assert target is not None
            await try_dm(
                target,
                build_game_layout("You were timed out", f"You were timed out in **{guild.name}** for **1 hour**.\nReason: Suspected alt account."),
            )
            await target.timeout(timedelta(hours=1), reason=reason)
            status = "timed_out"
            summary = "Automatically timed out for 1 hour." if automatic else f"Timed out for 1 hour by {who}"
        else:
            added_by = actor.id if actor is not None else (me.id if me else user_id)
            await bot.db.add_alt_whitelist(guild.id, user_id, added_by)
            if target:
                cfg = await bot.db.get_alt_config(guild.id)
                role_id = cfg["quarantine_role_id"]
                if role_id:
                    role = guild.get_role(int(role_id))
                    if role and role in target.roles and me and role < me.top_role:
                        try:
                            await target.remove_roles(role, reason=reason)
                        except discord.HTTPException:
                            pass
                if target.is_timed_out():
                    try:
                        await target.timeout(None, reason=reason)
                    except discord.HTTPException:
                        pass
            status = "whitelisted"
            summary = "Marked safe." if automatic else f"Marked safe (whitelisted) by {who}"
    except discord.Forbidden:
        return False, "I don't have permission to do that.", None
    except discord.HTTPException:
        return False, "That action failed. Try again or use the moderation commands.", None

    await bot.db.update_alt_flag_action(
        flag_id=flag_id,
        guild_id=guild.id,
        user_id=user_id,
        action_taken=action,
        action_by=(actor.id if actor is not None else None),
        status=status,
    )
    if action in {"kick", "ban", "timeout"} and not automatic:
        from cogs.channels import post_modlog
        label = {"kick": "Kicked", "ban": "Banned", "timeout": "Timed out for 1 hour"}[action]
        color = DANGER if action in {"kick", "ban"} else WARNING
        staff = actor.mention if actor is not None else "Dashboard"
        await post_modlog(
            bot,
            guild,
            f"Member {label.lower()}",
            f"**User:** <@{user_id}> (`{user_id}`)\n**Staff:** {staff}\n**Reason:** Suspected alt account.",
            color=color,
        )
    return True, summary, status


async def handle_alert_action(interaction: discord.Interaction, action: str, user_id: int) -> None:
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("This only works in a server.", ephemeral=True)
        return
    bot: SocializeBot = interaction.client  # type: ignore[assignment]
    ok, summary, _status = await apply_alt_review(
        bot, guild, action, user_id, actor=interaction.user
    )
    if not ok:
        await interaction.response.send_message(summary, ephemeral=True)
        return
    updated = build_game_layout(
        f"Alt action — {action}",
        f"**Action:** {action}\n**Review:** {summary}",
    )
    await interaction.response.edit_message(view=updated)


class AltDetect(commands.Cog):
    """Flag suspicious new accounts and let staff review them."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        bot.add_dynamic_items(AltActionButton)

    async def assess(self, guild: discord.Guild, user: discord.abc.User, *, joined_at: datetime | None, min_age_days: int) -> AltAssessment:
        now = datetime.now(timezone.utc)
        created_at = user.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if joined_at is not None and joined_at.tzinfo is None:
            joined_at = joined_at.replace(tzinfo=timezone.utc)
        age = (joined_at or now) - created_at
        age_days = age.total_seconds() / 86400
        score = 0
        reasons: list[str] = []

        if age_days < min_age_days:
            score += 25
            reasons.append(f"Account is {self._age_label(age)} old (minimum {min_age_days} day{'s' if min_age_days != 1 else ''})")
            if age.total_seconds() < 86400:
                score += 15
                reasons.append("Account was created less than a day ago")
            elif age_days < 3:
                score += 8
                reasons.append("Account is under 3 days old")

        default_avatar = has_default_avatar(user)
        if default_avatar:
            score += 15
            reasons.append("Using the default avatar")

        for reason in username_signals(user):
            score += 12
            reasons.append(reason)

        if joined_at is not None:
            delay = (joined_at - created_at).total_seconds()
            if delay < JOIN_SOON_STRONG:
                score += 20
                reasons.append("Joined the server within an hour of creating the account")
            elif delay < JOIN_SOON_MILD:
                score += 10
                reasons.append("Joined the server within 24 hours of creating the account")

        prior = await self.bot.db.prior_alt_mod_actions(guild.id, user.id)
        actions = {str(row["action"]) for row in prior}
        if "ban" in actions:
            score += 30
            reasons.append("This account previously received a ban in this server")
        elif "kick" in actions:
            score += 20
            reasons.append("This account previously received a kick in this server")

        since = (now - timedelta(seconds=BAN_LOOKBACK)).timestamp()
        nearby = await self.bot.db.recent_banned_account_creations(guild.id, since, user.id)
        created_ts = created_at.timestamp()
        close = [
            row
            for row in nearby
            if row["account_created_at"] is not None and abs(float(row["account_created_at"]) - created_ts) <= BAN_COMPARE_WINDOW
        ]
        if close:
            score += 20
            reasons.append("Account was created around the same time as a recently banned user")

        score = min(score, 100)
        return AltAssessment(
            score=score,
            verdict=verdict_for(score),
            reasons=reasons or ["No suspicion signals matched"],
            age=age,
            default_avatar=default_avatar,
            created_at=created_at,
            joined_at=joined_at,
        )

    @staticmethod
    def _age_label(age: timedelta) -> str:
        secs = max(0, int(age.total_seconds()))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def build_report_embed(self, user: discord.abc.User, assessment: AltAssessment, *, title: str | None = None):
        return build_report_layout(
            user,
            assessment,
            title=title,
            age_label=self._age_label(assessment.age),
            accent=verdict_color(assessment.verdict),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        cfg = await self.bot.db.get_alt_config(member.guild.id)
        if not int(cfg["enabled"] or 0):
            return
        if await self.bot.db.is_alt_whitelisted(member.guild.id, member.id):
            return
        min_age = int(cfg["min_age_days"] or 7)
        assessment = await self.assess(member.guild, member, joined_at=member.joined_at, min_age_days=min_age)
        action = str(cfg["action"] or "log")
        notable = assessment.verdict != "Low risk" or any("previously received" in reason for reason in assessment.reasons)
        if not notable:
            return
        created_ts = assessment.created_at.timestamp() if assessment.created_at else None
        joined_ts = assessment.joined_at.timestamp() if assessment.joined_at else None
        flag_id = await self.bot.db.add_alt_flag(
            member.guild.id,
            member.id,
            assessment.score,
            assessment.verdict,
            json.dumps(assessment.reasons),
            username=str(member),
            display_name=member.display_name,
            avatar_url=member.display_avatar.url if member.display_avatar else None,
            account_created_at=created_ts,
            joined_at=joined_ts,
            action_taken="logged" if action != "none" else "none",
            status="in_server",
        )
        if action == "none":
            return
        log_id = await self.bot.db.get_feature_channel(member.guild.id, "alts")
        log_channel = member.guild.get_channel(log_id) if log_id else None
        message = None
        if isinstance(log_channel, discord.TextChannel):
            e = self.build_report_embed(member, assessment, title=f"Suspicious join — {assessment.verdict}")
            try:
                message = await log_channel.send(view=e)
            except discord.HTTPException:
                message = None
        if assessment.verdict != "High risk":
            return
        auto_note = await self._apply_auto_action(member, action, int(cfg["quarantine_role_id"]) if cfg["quarantine_role_id"] else None, flag_id=flag_id)
        if auto_note and message is not None:
            try:
                current = e.body_td.content or ""
                e.body_td.content = f"{current}\n\n**Auto action:** {auto_note}"
                await message.edit(view=e)
            except discord.HTTPException:
                pass

    async def _apply_auto_action(self, member: discord.Member, action: str, role_id: int | None, *, flag_id: int | None = None) -> str | None:
        if action in {"timeout", "kick", "ban"}:
            ok, summary, _status = await apply_alt_review(
                self.bot,
                member.guild,
                action,
                member.id,
                automatic=True,
                flag_id=flag_id,
            )
            return summary if ok else (summary or "Auto action failed — I may be missing permissions.")
        if action != "quarantine":
            return None
        me = member.guild.me
        if me is None or member.id == member.guild.owner_id or member.top_role >= me.top_role:
            return "Auto action skipped — I can't moderate this member."
        if not role_id:
            return "Quarantine is selected, but no quarantine role is configured. Use `.altconfig role @role`."
        role = member.guild.get_role(role_id)
        if role is None or role >= me.top_role or role.is_default() or role.managed:
            return "Couldn't apply the quarantine role (missing, managed, or above me)."
        try:
            await member.add_roles(role, reason="Alt-detect auto action (high risk)")
        except discord.HTTPException:
            return "Auto action failed — I may be missing permissions."
        await self.bot.db.update_alt_flag_action(
            flag_id=flag_id,
            guild_id=member.guild.id,
            user_id=member.id,
            action_taken="quarantine",
            status="quarantined",
        )
        return f"Automatically quarantined with {role.mention}."


    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        created = user.created_at.timestamp() if getattr(user, "created_at", None) else None
        await self.bot.db.add_alt_mod_action(guild.id, user.id, "ban", created)

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        if entry.action is not discord.AuditLogAction.kick or entry.target is None:
            return
        target = entry.target
        user_id = getattr(target, "id", None)
        if user_id is None:
            return
        created = target.created_at.timestamp() if getattr(target, "created_at", None) else None
        await self.bot.db.add_alt_mod_action(entry.guild.id, int(user_id), "kick", created)

    @commands.hybrid_group(name="altconfig", description="Configure alt-account detection.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def altconfig(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await self.altconfig_show(ctx)

    @altconfig.command(name="channel", description="Set the channel where alt alerts are posted.")
    @app_commands.describe(channel="Log channel for alt alerts. Omit to clear.")
    async def altconfig_channel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        await self.bot.db.set_feature_channel(ctx.guild.id, "alts", channel.id if channel else None)
        if channel:
            await ctx.send(layout=build_game_layout("Alt log channel set", f"Alerts will be posted in {channel.mention}."))
        else:
            await ctx.send(layout=build_game_layout("Alt log channel cleared", "I won't post alt alerts until you set a channel again."))

    @altconfig.command(name="minage", description="Set the minimum account age in days.")
    @app_commands.describe(days="Accounts younger than this many days score as too new. Default 7.")
    async def altconfig_minage(self, ctx: commands.Context, days: int) -> None:
        assert ctx.guild
        if days < 0 or days > 365:
            await ctx.send(layout=build_game_layout("Invalid age", "Use a number of days from 0 to 365."), ephemeral=True)
            return
        await self.bot.db.set_alt_config(ctx.guild.id, min_age_days=days)
        await ctx.send(layout=build_game_layout("Minimum age updated", f"Accounts newer than **{days}** day{'s' if days != 1 else ''} will be treated as young."))

    @altconfig.command(name="action", description="What to do when a high-risk account joins.")
    @app_commands.describe(action="none, log, timeout, kick, or quarantine")
    @app_commands.choices(action=[app_commands.Choice(name=name, value=name) for name in ACTIONS])
    async def altconfig_action(self, ctx: commands.Context, action: str) -> None:
        assert ctx.guild
        choice = action.strip().lower()
        if choice not in ACTIONS:
            await ctx.send(layout=build_game_layout("Invalid action", "Use `none`, `log`, `timeout`, `kick`, or `quarantine`."), ephemeral=True)
            return
        await self.bot.db.set_alt_config(ctx.guild.id, action=choice)
        notes = {
            "none": "Joins will still be scored, but I won't post alerts or take action.",
            "log": "I'll post an alert in the alt log channel for medium and high risk joins.",
            "timeout": "High-risk joins will be timed out for 1 hour, and I'll still post an alert.",
            "kick": "High-risk joins will be kicked, and I'll still post an alert.",
            "quarantine": "High-risk joins will be given the quarantine role. Set it with `.altconfig role @role`.",
        }
        await ctx.send(layout=build_game_layout("Alt action updated", notes[choice]))

    @altconfig.command(name="role", description="Set the quarantine role given on a high-risk join.")
    @app_commands.describe(role="Role to grant when the action is quarantine. Omit to clear.")
    async def altconfig_role(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        assert ctx.guild and ctx.guild.me and isinstance(ctx.author, discord.Member)
        if role is not None:
            if role.is_default() or role.managed:
                await ctx.send(layout=build_game_layout("Can't use that role", "Pick a normal role, not @everyone or a managed role."), ephemeral=True)
                return
            if role >= ctx.guild.me.top_role:
                await ctx.send(layout=build_game_layout("Role too high", "That role is above or equal to me, so I couldn't assign it."), ephemeral=True)
                return
        await self.bot.db.set_alt_config(ctx.guild.id, quarantine_role_id=role.id if role else None)
        if role:
            await ctx.send(layout=build_game_layout("Quarantine role set", f"High-risk joins will receive {role.mention} when the action is `quarantine`."))
        else:
            await ctx.send(layout=build_game_layout("Quarantine role cleared", "No quarantine role is configured."))

    @altconfig.command(name="on", description="Enable alt-account detection.")
    async def altconfig_on(self, ctx: commands.Context) -> None:
        assert ctx.guild
        await self.bot.db.set_alt_config(ctx.guild.id, enabled=1)
        await ctx.send(layout=build_game_layout("Alt detection enabled", "New joins will be scored. Use `.altconfig show` to review settings."))

    @altconfig.command(name="off", description="Disable alt-account detection.")
    async def altconfig_off(self, ctx: commands.Context) -> None:
        assert ctx.guild
        await self.bot.db.set_alt_config(ctx.guild.id, enabled=0)
        await ctx.send(layout=build_game_layout("Alt detection disabled", "I won't score or act on new joins until you turn it back on."))

    @altconfig.command(name="show", description="Show the current alt-detection settings.")
    async def altconfig_show(self, ctx: commands.Context) -> None:
        assert ctx.guild
        cfg = await self.bot.db.get_alt_config(ctx.guild.id)
        log_id = await self.bot.db.get_feature_channel(ctx.guild.id, "alts")
        log_ch = ctx.guild.get_channel(log_id) if log_id else None
        role_id = cfg["quarantine_role_id"]
        role = ctx.guild.get_role(int(role_id)) if role_id else None
        enabled = "On" if int(cfg["enabled"] or 0) else "Off"
        await ctx.send(
            layout=build_game_layout(
                "Alt detection settings",
                f"**Status:** {enabled}\n"
                f"**Log channel:** {log_ch.mention if log_ch else 'Not set'}\n"
                f"**Minimum age:** {int(cfg['min_age_days'] or 7)} days\n"
                f"**Action:** `{cfg['action'] or 'log'}`\n"
                f"**Quarantine role:** {role.mention if role else 'Not set'}",
            )
        )

    @commands.hybrid_command(name="altcheck", description="Score a user for possible alt-account signals.")
    @commands.guild_only()
    @commands.check_any(
        commands.has_permissions(manage_guild=True),
        commands.has_permissions(moderate_members=True),
        commands.has_permissions(kick_members=True),
        commands.has_permissions(ban_members=True),
    )
    @app_commands.describe(user="The member to check.")
    async def altcheck(self, ctx: commands.Context, user: discord.Member) -> None:
        assert ctx.guild
        cfg = await self.bot.db.get_alt_config(ctx.guild.id)
        assessment = await self.assess(ctx.guild, user, joined_at=user.joined_at, min_age_days=int(cfg["min_age_days"] or 7))
        e = self.build_report_embed(user, assessment)
        if await self.bot.db.is_alt_whitelisted(ctx.guild.id, user.id):
            e.body_td.content = f"{e.body_td.content}\n\n**Whitelist:** This user is marked safe."
        await ctx.send(view=e)

    @commands.hybrid_command(name="altlist", description="List recent joins flagged by alt detection.")
    @commands.guild_only()
    @commands.check_any(
        commands.has_permissions(manage_guild=True),
        commands.has_permissions(moderate_members=True),
        commands.has_permissions(kick_members=True),
        commands.has_permissions(ban_members=True),
    )
    async def altlist(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.bot.db.recent_alt_flags(ctx.guild.id, 15)
        if not rows:
            await ctx.send(layout=build_game_layout("Recent alt flags", "No joins have been flagged yet."))
            return
        lines = []
        for row in rows:
            ts = int(row["created_at"])
            lines.append(
                f"• <@{row['user_id']}> (`{row['user_id']}`) — **{row['score']}**, {row['verdict']} — <t:{ts}:R>"
            )
        await ctx.send(layout=build_game_layout("Recent alt flags", "\n".join(lines)))

    @commands.hybrid_group(name="altwhitelist", description="Mark a user as safe so they aren't flagged.", fallback="add")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(user="The user to whitelist.")
    async def altwhitelist(self, ctx: commands.Context, user: discord.User) -> None:
        assert ctx.guild
        added = await self.bot.db.add_alt_whitelist(ctx.guild.id, user.id, ctx.author.id)
        if added:
            await ctx.send(layout=build_game_layout("User whitelisted", f"{user.mention} (`{user.id}`) is marked safe and won't be flagged."))
        else:
            await ctx.send(layout=build_game_layout("Already whitelisted", f"{user.mention} is already marked safe."))

    @altwhitelist.command(name="remove", description="Remove a user from the alt whitelist.")
    @app_commands.describe(user="The user to remove from the whitelist.")
    async def altwhitelist_remove(self, ctx: commands.Context, user: discord.User) -> None:
        assert ctx.guild
        removed = await self.bot.db.remove_alt_whitelist(ctx.guild.id, user.id)
        if removed:
            await ctx.send(layout=build_game_layout("Whitelist removed", f"{user.mention} (`{user.id}`) can be flagged again."))
        else:
            await ctx.send(layout=build_game_layout("Not whitelisted", f"{user.mention} wasn't on the whitelist."), ephemeral=True)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(AltDetect(bot))

