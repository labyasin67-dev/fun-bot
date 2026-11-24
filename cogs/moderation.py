"""Moderation commands: ban, kick, timeout, warns, purge, slowmode, lock."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.channels import post_modlog
from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_TIMEOUT = 28 * 24 * 3600


def parse_duration(text: str) -> timedelta | None:
    match = DURATION_RE.fullmatch(text.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    seconds = amount * UNITS[unit]
    if seconds < 1 or seconds > MAX_TIMEOUT:
        return None
    return timedelta(seconds=seconds)


def format_delta(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs % 86400 == 0:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''}"
    if secs % 3600 == 0:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''}"
    if secs % 60 == 0:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''}"
    return f"{secs} second{'s' if secs != 1 else ''}"


def hierarchy_error(actor: discord.Member, target: discord.Member, bot_member: discord.Member) -> str | None:
    if target.id == actor.id:
        return "You can't use that on yourself."
    if target.id == actor.guild.owner_id:
        return "You can't use that on the server owner."
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return "That member is above or equal to you in the role list."
    if target.top_role >= bot_member.top_role:
        return "That member is above or equal to me in the role list."
    return None


async def try_dm(user: discord.abc.User, embed: discord.Embed) -> bool:
    try:
        await user.send(embed=embed)
        return True
    except discord.HTTPException:
        return False


class Moderation(commands.Cog):
    """Staff tools for bans, kicks, timeouts, warns and channel cleanup."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def _target_check(self, ctx: commands.Context, member: discord.Member) -> bool:
        assert ctx.guild and ctx.guild.me and isinstance(ctx.author, discord.Member)
        err = hierarchy_error(ctx.author, member, ctx.guild.me)
        if err:
            await ctx.send(embed=make_embed("Can't do that", err, color=DANGER), ephemeral=True)
            return False
        return True

    @commands.hybrid_command(name="ban", description="Ban a member from the server.")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban.", reason="Optional reason, shown in the audit log.")
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        if not await self._target_check(ctx, member):
            return
        why = reason or "No reason provided."
        assert ctx.guild
        await member.ban(reason=f"{ctx.author} : {why}", delete_message_seconds=0)
        dm_ok = await try_dm(
            member,
            make_embed("You were banned", f"You were banned from **{ctx.guild.name}**.\nReason: {why}", color=DANGER),
        )
        extra = "" if dm_ok else " I couldn't DM them."
        await ctx.send(embed=make_embed("Member banned", f"**{member}** was banned. Reason: {why}.{extra}", color=SUCCESS))
        await post_modlog(self.bot, ctx.guild, "Member banned", f"**User:** {member.mention} (`{member.id}`)\n**Staff:** {ctx.author.mention}\n**Reason:** {why}", color=DANGER)

    @commands.hybrid_command(name="unban", description="Unban a user by their Discord ID.")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The numeric Discord ID of the banned user.")
    async def unban(self, ctx: commands.Context, user_id: str) -> None:
        assert ctx.guild
        if not user_id.isdigit():
            await ctx.send(embed=make_embed("Invalid ID", "Give a numeric Discord user ID.", color=DANGER), ephemeral=True)
            return
        uid = int(user_id)
        try:
            await ctx.guild.unban(discord.Object(id=uid), reason=f"Unbanned by {ctx.author}")
        except discord.NotFound:
            await ctx.send(embed=make_embed("Not banned", "I couldn't find a ban for that user ID.", color=DANGER), ephemeral=True)
            return
        await ctx.send(embed=make_embed("User unbanned", f"<@{uid}> (`{uid}`) can join again.", color=SUCCESS))

    @commands.hybrid_command(name="kick", description="Kick a member from the server.")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick.", reason="Optional reason, shown in the audit log.")
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        if not await self._target_check(ctx, member):
            return
        why = reason or "No reason provided."
        assert ctx.guild
        await member.kick(reason=f"{ctx.author} : {why}")
        created = member.created_at.timestamp() if member.created_at else None
        await self.bot.db.add_alt_mod_action(ctx.guild.id, member.id, "kick", created)
        dm_ok = await try_dm(
            member,
            make_embed("You were kicked", f"You were kicked from **{ctx.guild.name}**.\nReason: {why}", color=DANGER),
        )
        extra = "" if dm_ok else " I couldn't DM them."
        await ctx.send(embed=make_embed("Member kicked", f"**{member}** was kicked. Reason: {why}.{extra}", color=SUCCESS))
        await post_modlog(self.bot, ctx.guild, "Member kicked", f"**User:** {member.mention} (`{member.id}`)\n**Staff:** {ctx.author.mention}\n**Reason:** {why}", color=DANGER)

    @commands.hybrid_command(name="timeout", description="Timeout a member. Duration examples: 10m, 1h, 1d.")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to timeout.", duration="How long, for example 10m, 1h or 1d.", reason="Optional reason.")
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration: str, *, reason: str | None = None) -> None:
        if not await self._target_check(ctx, member):
            return
        delta = parse_duration(duration)
        if delta is None:
            await ctx.send(embed=make_embed("Invalid duration", "Use a number followed by s, m, h or d — for example `10m`, `1h`, `1d`. Max 28 days.", color=DANGER), ephemeral=True)
            return
        why = reason or "No reason provided."
        assert ctx.guild
        await member.timeout(delta, reason=f"{ctx.author} : {why}")
        dm_ok = await try_dm(
            member,
            make_embed(
                "You were timed out",
                f"You were timed out in **{ctx.guild.name}** for **{format_delta(delta)}**.\nReason: {why}",
                color=WARNING,
            ),
        )
        extra = "" if dm_ok else " I couldn't DM them."
        await ctx.send(embed=make_embed("Member timed out", f"**{member}** is timed out for **{format_delta(delta)}**. Reason: {why}.{extra}", color=SUCCESS))
        await post_modlog(self.bot, ctx.guild, "Member timed out", f"**User:** {member.mention} (`{member.id}`)\n**Staff:** {ctx.author.mention}\n**Duration:** {format_delta(delta)}\n**Reason:** {why}", color=WARNING)

    @commands.hybrid_command(name="untimeout", description="Remove a timeout from a member.")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to remove the timeout from.")
    async def untimeout(self, ctx: commands.Context, member: discord.Member) -> None:
        if not await self._target_check(ctx, member):
            return
        await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
        await ctx.send(embed=make_embed("Timeout removed", f"**{member}** can speak again.", color=SUCCESS))

    @commands.hybrid_command(name="warn", description="Warn a member and log the reason.")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn.", reason="Why they're being warned.")
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        if not await self._target_check(ctx, member):
            return
        why = reason or "No reason provided."
        assert ctx.guild
        count_before = len(await self.bot.db.get_warnings(ctx.guild.id, member.id))
        await self.bot.db.add_warning(ctx.guild.id, member.id, ctx.author.id, why)
        total = count_before + 1
        await try_dm(member, make_embed("You were warned", f"You were warned in **{ctx.guild.name}**.\nReason: {why}", color=WARNING))
        await ctx.send(embed=make_embed("Member warned", f"**{member}** was warned. Reason: {why}\nThey now have **{total}** warning{'s' if total != 1 else ''}.", color=SUCCESS))
        await post_modlog(self.bot, ctx.guild, "Member warned", f"**User:** {member.mention} (`{member.id}`)\n**Staff:** {ctx.author.mention}\n**Reason:** {why}\n**Warnings:** {total}", color=WARNING)

    @commands.hybrid_command(name="warnings", description="List a member's warnings.")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member whose warnings you want to see.")
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild
        rows = await self.bot.db.get_warnings(ctx.guild.id, member.id)
        if not rows:
            await ctx.send(embed=make_embed("Warnings", f"**{member}** has no warnings."))
            return
        lines = []
        for i, row in enumerate(rows, start=1):
            reason = row["reason"] or "No reason provided."
            lines.append(f"**{i}.** {reason} — by <@{row['moderator_id']}>")
        await ctx.send(embed=make_embed(f"Warnings for {member}", "\n".join(lines[:25])))

    @commands.hybrid_command(name="clearwarns", description="Clear all warnings for a member.")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member whose warnings should be cleared.")
    async def clearwarns(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild
        removed = await self.bot.db.clear_warnings(ctx.guild.id, member.id)
        await ctx.send(embed=make_embed("Warnings cleared", f"Removed **{removed}** warning{'s' if removed != 1 else ''} from **{member}**.", color=SUCCESS))

    @commands.hybrid_command(name="purge", description="Delete a number of recent messages in this channel.")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @app_commands.describe(amount="How many messages to delete (1–100).")
    async def purge(self, ctx: commands.Context, amount: int) -> None:
        if amount < 1 or amount > 100:
            await ctx.send(embed=make_embed("Invalid amount", "Choose a number from 1 to 100.", color=DANGER), ephemeral=True)
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send(embed=make_embed("Can't purge here", "I can only purge text channels.", color=DANGER), ephemeral=True)
            return
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        deleted = await ctx.channel.purge(limit=amount + (0 if ctx.interaction else 1), check=lambda m: True)
        # For prefix commands, the invoke message is included in the purge window; that's intended.
        count = len(deleted)
        await ctx.send(embed=make_embed("Messages deleted", f"Deleted **{count}** message{'s' if count != 1 else ''}.", color=SUCCESS), ephemeral=True, delete_after=5)
        await post_modlog(self.bot, ctx.guild, "Messages purged", f"**Channel:** {ctx.channel.mention}\n**Staff:** {ctx.author.mention}\n**Deleted:** {count}", color=WARNING)

    @commands.hybrid_command(name="slowmode", description="Set slowmode in this channel, in seconds. 0 turns it off.")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode delay in seconds (0–21600). 0 disables it.")
    async def slowmode(self, ctx: commands.Context, seconds: int) -> None:
        if seconds < 0 or seconds > 21600:
            await ctx.send(embed=make_embed("Invalid slowmode", "Use a value from 0 to 21600 seconds.", color=DANGER), ephemeral=True)
            return
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            await ctx.send(embed=make_embed("Can't set slowmode here", "Slowmode only works in text channels.", color=DANGER), ephemeral=True)
            return
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {ctx.author}")
        if seconds == 0:
            await ctx.send(embed=make_embed("Slowmode off", "Slowmode has been disabled in this channel.", color=SUCCESS))
        else:
            await ctx.send(embed=make_embed("Slowmode updated", f"Members can send one message every **{seconds}** second{'s' if seconds != 1 else ''}.", color=SUCCESS))

    @commands.hybrid_command(name="lock", description="Lock a channel so @everyone can't send messages.")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to lock. Defaults to the current channel.")
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            await ctx.send(embed=make_embed("Can't lock that", "I can only lock text channels.", color=DANGER), ephemeral=True)
            return
        overwrite = target.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await target.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Locked by {ctx.author}")
        await ctx.send(embed=make_embed("Channel locked", f"{target.mention} is locked. @everyone can no longer send messages.", color=SUCCESS))

    @commands.hybrid_command(name="unlock", description="Unlock a channel so @everyone can send messages again.")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to unlock. Defaults to the current channel.")
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            await ctx.send(embed=make_embed("Can't unlock that", "I can only unlock text channels.", color=DANGER), ephemeral=True)
            return
        overwrite = target.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await target.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {ctx.author}")
        await ctx.send(embed=make_embed("Channel unlocked", f"{target.mention} is unlocked.", color=SUCCESS))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Moderation(bot))
