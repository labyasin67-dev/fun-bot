"""Chat and voice XP, ranks, leaderboards, and level roles."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import (
    COLOR,
    DANGER,
    NO_MENTIONS,
    SAFE_MENTIONS,
    SUCCESS,
    embed as make_embed,
    format_duration,
    level_from_xp,
    level_progress,
    progress_bar,
    xp_for_level,
)

if TYPE_CHECKING:
    from main import SocializeBot

MESSAGE_COOLDOWN = 60
MESSAGE_XP_MIN = 15
MESSAGE_XP_MAX = 25
VOICE_XP_PER_MINUTE = 10
VOICE_TICK_SECONDS = 60


class Leveling(commands.Cog):
    """Levels from chat and time in voice."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self._awarding: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        self.voice_xp_loop.start()

    async def cog_unload(self) -> None:
        self.voice_xp_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or not message.content:
            return
        # Don't award XP for counting-channel traffic or bare prefix pokes.
        counting_id = await self.bot.db.get_feature_channel(message.guild.id, "counting")
        if counting_id == message.channel.id:
            return
        now = time.time()
        member_row = await self.bot.db.ensure_member(message.guild.id, message.author.id)
        if now - float(member_row["last_message_xp"] or 0) < MESSAGE_COOLDOWN:
            return
        amount = random.randint(MESSAGE_XP_MIN, MESSAGE_XP_MAX)
        old_xp, new_xp = await self.bot.db.add_xp(message.guild.id, message.author.id, amount, message_ts=now)
        await self._handle_level_up(message.guild, message.author, message.channel, old_xp, new_xp)

    async def _handle_level_up(
        self,
        guild: discord.Guild,
        user: discord.abc.User,
        origin_channel: discord.abc.Messageable | None,
        old_xp: int,
        new_xp: int,
    ) -> None:
        old_level = level_from_xp(old_xp)
        new_level = level_from_xp(new_xp)
        if new_level <= old_level:
            return
        member = guild.get_member(user.id)
        added: list[discord.Role] = []
        if member:
            added, _removed = await self._sync_level_roles(member, new_level)
        role_text = ""
        if added:
            role_text = " You earned " + ", ".join(role.mention for role in added) + "."
        # Off: no DM and no channel post. Roles still applied above.
        mode = await self.bot.db.get_levelup_mode(guild.id)
        if mode == "off":
            return
        levelup_id = await self.bot.db.get_feature_channel(guild.id, "levelups")
        if mode == "channel":
            if levelup_id:
                found = guild.get_channel(levelup_id)
                if isinstance(found, discord.abc.Messageable):
                    name = member.display_name if member else getattr(user, "display_name", user.name)
                    e = make_embed(
                        "Level up!",
                        f"**{name}** reached **level {new_level}**.{role_text}",
                        color=SUCCESS,
                    )
                    try:
                        await found.send(embed=e, allowed_mentions=NO_MENTIONS)
                    except discord.HTTPException:
                        pass
            return
        target = member or user
        e = make_embed(
            "Level up!",
            f"You reached **level {new_level}** in **{guild.name}**.{role_text}",
            color=SUCCESS,
        )
        try:
            await target.send(embed=e, allowed_mentions=SAFE_MENTIONS)
        except discord.HTTPException:
            # DMs closed or blocked — fail silently, do not post in the channel.
            pass

    async def _sync_level_roles(self, member: discord.Member, level: int) -> tuple[list[discord.Role], list[discord.Role]]:
        rows = await self.bot.db.level_roles(member.guild.id)
        if not rows or member.guild.me is None:
            return [], []
        to_add: list[discord.Role] = []
        to_remove: list[discord.Role] = []
        for row in rows:
            role = member.guild.get_role(int(row["role_id"]))
            if role is None or role.managed or role >= member.guild.me.top_role:
                continue
            if int(row["level"]) <= level:
                if role not in member.roles:
                    to_add.append(role)
            elif role in member.roles:
                to_remove.append(role)
        if to_add:
            try:
                await member.add_roles(*to_add, reason="Level role")
            except discord.HTTPException:
                to_add = []
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="No longer qualifies for this level role")
            except discord.HTTPException:
                to_remove = []
        return to_add, to_remove

    async def apply_xp_delta(self, guild: discord.Guild, user_id: int, delta: int) -> dict:
        """Staff XP adjustment: clamp at 0, recompute level, and sync level roles."""
        if delta == 0:
            raise ValueError("Enter an amount other than 0.")
        old_xp, new_xp = await self.bot.db.adjust_xp(guild.id, user_id, delta)
        new_level = level_from_xp(new_xp)
        member = guild.get_member(user_id)
        added, removed = [], []
        if member is not None:
            added, removed = await self._sync_level_roles(member, new_level)
        return {
            "old_xp": old_xp,
            "new_xp": new_xp,
            "level": new_level,
            "member": member,
            "added": added,
            "removed": removed,
        }

    def _qualifies_for_voice_xp(self, state: discord.VoiceState) -> bool:
        channel = state.channel
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return False
        if state.self_deaf or state.afk:
            return False
        # Ignore AFK channels even if the afk flag isn't set.
        guild = channel.guild
        if guild.afk_channel and channel.id == guild.afk_channel.id:
            return False
        humans = [m for m in channel.members if not m.bot]
        return len(humans) >= 2

    @tasks.loop(seconds=VOICE_TICK_SECONDS)
    async def voice_xp_loop(self) -> None:
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                humans = [m for m in channel.members if not m.bot]
                if len(humans) < 2:
                    continue
                if guild.afk_channel and channel.id == guild.afk_channel.id:
                    continue
                for member in humans:
                    state = member.voice
                    if state is None or state.self_deaf or state.afk:
                        continue
                    if state.channel is None or state.channel.id != channel.id:
                        continue
                    key = (guild.id, member.id)
                    if key in self._awarding:
                        continue
                    self._awarding.add(key)
                    try:
                        old_xp, new_xp = await self.bot.db.add_xp(guild.id, member.id, VOICE_XP_PER_MINUTE)
                        await self.bot.db.add_voice_seconds(guild.id, member.id, VOICE_TICK_SECONDS)
                        await self._handle_level_up(guild, member, None, old_xp, new_xp)
                    except Exception:
                        pass
                    finally:
                        self._awarding.discard(key)

    @voice_xp_loop.before_loop
    async def before_voice_xp(self) -> None:
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="rank", aliases=["level", "xp"], description="Show your level, XP, and voice time.")
    @commands.guild_only()
    @app_commands.describe(member="Whose rank to show. Defaults to you.")
    async def rank(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        assert ctx.guild
        target = member or ctx.author
        row = await self.bot.db.ensure_member(ctx.guild.id, target.id)
        xp = int(row["xp"])
        voice_seconds = int(row["voice_seconds"])
        level, into, needed, _ = level_progress(xp)
        rank = await self.bot.db.xp_rank(ctx.guild.id, target.id)
        voice_rank = await self.bot.db.voice_rank(ctx.guild.id, target.id)
        bar = progress_bar(into, needed)
        e = make_embed(f"{target.display_name}'s rank")
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Level", value=f"**{level}**", inline=True)
        e.add_field(name="Rank", value=f"**#{rank}**", inline=True)
        e.add_field(name="XP", value=f"**{xp:,}**", inline=True)
        e.add_field(name="Progress", value=f"{bar} {into:,}/{needed:,}", inline=False)
        e.add_field(name="Voice time", value=format_duration(voice_seconds), inline=True)
        e.add_field(name="Voice rank", value=f"**#{voice_rank}**", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "levels"], description="Show the server XP leaderboard.")
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.bot.db.top_xp(ctx.guild.id, 10)
        if not rows:
            await ctx.send(embed=make_embed("Leaderboard", "No one has earned XP yet. Chat or hop in voice to get started."))
            return
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, row in enumerate(rows, start=1):
            member = ctx.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else f"User {row['user_id']}"
            level = level_from_xp(int(row["xp"]))
            medal = medals.get(i, f"`{i}.`")
            lines.append(f"{medal} **{name}** — level {level} · {int(row['xp']):,} XP")
        e = make_embed("XP leaderboard", "\n".join(lines))
        e.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="voicetime", description="Show how long you or another member have spent in voice.")
    @commands.guild_only()
    @app_commands.describe(member="Whose voice time to show. Defaults to you.")
    async def voicetime(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        assert ctx.guild
        target = member or ctx.author
        row = await self.bot.db.ensure_member(ctx.guild.id, target.id)
        seconds = int(row["voice_seconds"])
        rank = await self.bot.db.voice_rank(ctx.guild.id, target.id)
        e = make_embed(
            f"{target.display_name}'s voice time",
            f"**{format_duration(seconds)}** in voice (counted when not alone, AFK, or self-deafened).\nVoice rank: **#{rank}**",
        )
        e.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="voiceleaderboard", aliases=["voicelb", "vclb"], description="Show the server voice-time leaderboard.")
    @commands.guild_only()
    async def voiceleaderboard(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.bot.db.top_voice(ctx.guild.id, 10)
        if not rows or all(int(r["voice_seconds"]) == 0 for r in rows):
            await ctx.send(embed=make_embed("Voice leaderboard", "No voice time has been tracked yet."))
            return
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, row in enumerate(rows, start=1):
            if int(row["voice_seconds"]) <= 0:
                continue
            member = ctx.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else f"User {row['user_id']}"
            medal = medals.get(i, f"`{i}.`")
            lines.append(f"{medal} **{name}** — {format_duration(int(row['voice_seconds']))}")
        e = make_embed("Voice leaderboard", "\n".join(lines) or "No voice time has been tracked yet.")
        e.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="levelup", description="Set level-up announcements to off, DM, or a channel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(setting="off, dm, or a #channel")
    async def levelup(self, ctx: commands.Context, setting: str | None = None) -> None:
        assert ctx.guild
        if setting is None:
            mode = await self.bot.db.get_levelup_mode(ctx.guild.id)
            if mode == "off":
                text = "Level-up announcements are **off**. Members still earn XP and level roles."
            elif mode == "channel":
                channel_id = await self.bot.db.get_feature_channel(ctx.guild.id, "levelups")
                channel = ctx.guild.get_channel(channel_id) if channel_id else None
                where = channel.mention if channel else "a channel that I can't find"
                text = f"Level-ups are posted in {where}, without pings."
            else:
                text = "Level-ups are sent as a **DM** to the member (the default). If their DMs are closed, nothing is posted."
            await ctx.send(embed=make_embed("Level-up announcements", text + "\nUse `.levelup off`, `.levelup dm`, or `.levelup #channel` to change this."))
            return
        raw = setting.strip()
        key = raw.lower()
        if key in {"off", "disable", "disabled", "none", "silent"}:
            await self.bot.db.set_levelup_mode(ctx.guild.id, "off")
            await ctx.send(embed=make_embed("Level-ups off", "I won't DM members or post in a channel when they level up. XP and level roles still work."))
            return
        if key in {"dm", "dms", "message", "default"}:
            await self.bot.db.set_levelup_mode(ctx.guild.id, "dm")
            await ctx.send(embed=make_embed("Level-ups sent as DMs", "Members will be DMed when they level up. If their DMs are closed, nothing is posted in the server."))
            return
        # Accept a channel mention, ID, or name.
        channel = None
        if ctx.message and ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
        if channel is None:
            cleaned = raw.strip("<>#")
            if cleaned.isdigit():
                channel = ctx.guild.get_channel(int(cleaned))
            if channel is None:
                lowered = raw.lstrip("#").lower()
                channel = discord.utils.find(
                    lambda c: isinstance(c, discord.TextChannel) and c.name.lower() == lowered,
                    ctx.guild.text_channels,
                )
        if not isinstance(channel, discord.TextChannel):
            await ctx.send(embed=make_embed("Use off, dm, or a channel", "Try `.levelup off`, `.levelup dm`, or `.levelup #channel`.", color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_levelup_mode(ctx.guild.id, "channel", channel.id)
        await ctx.send(embed=make_embed("Level-up channel set", f"Level-ups will be posted in {channel.mention} without pings."))

    @commands.hybrid_command(name="setlevelchannel", description="Set a channel for level-up messages, or DM members instead.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Where to announce level-ups. Omit to DM the member instead (the default).")
    async def setlevelchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        if channel:
            await self.bot.db.set_levelup_mode(ctx.guild.id, "channel", channel.id)
            await ctx.send(embed=make_embed("Level-up channel set", f"Level-ups will be posted in {channel.mention} without pings."))
        else:
            await self.bot.db.set_levelup_mode(ctx.guild.id, "dm")
            await ctx.send(embed=make_embed("Level-ups sent as DMs", "Members will be DMed when they level up. If their DMs are closed, nothing is posted in the server."))

    @commands.hybrid_command(name="addxp", description="Add XP to a member.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The member to give XP to.", amount="How much XP to add.")
    async def addxp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        assert ctx.guild
        if amount <= 0:
            await ctx.send(embed=make_embed("Invalid amount", "Enter a positive number of XP to add.", color=DANGER), ephemeral=True)
            return
        result = await self.apply_xp_delta(ctx.guild, member.id, amount)
        await ctx.send(
            embed=make_embed(
                "XP added",
                f"Added **{amount:,}** XP to **{member.display_name}**. They now have **{result['new_xp']:,}** XP (level **{result['level']}**).",
                color=SUCCESS,
            )
        )

    @commands.hybrid_command(name="removexp", description="Remove XP from a member.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The member to take XP from.", amount="How much XP to remove.")
    async def removexp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        assert ctx.guild
        if amount <= 0:
            await ctx.send(embed=make_embed("Invalid amount", "Enter a positive number of XP to remove.", color=DANGER), ephemeral=True)
            return
        result = await self.apply_xp_delta(ctx.guild, member.id, -amount)
        await ctx.send(
            embed=make_embed(
                "XP removed",
                f"Removed **{amount:,}** XP from **{member.display_name}**. They now have **{result['new_xp']:,}** XP (level **{result['level']}**).",
                color=SUCCESS,
            )
        )

    @commands.hybrid_group(name="levelrole", description="Assign roles automatically when members reach a level.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def levelrole(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Level roles",
                "• `.levelrole add <level> @role` — grant a role at that level\n"
                "• `.levelrole remove <level>` — stop granting it\n"
                "• `.levelrole list` — show the current rewards",
            )
        )

    @levelrole.command(name="add", description="Grant a role when a member reaches a level.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(level="The level that unlocks the role.", role="The role to grant.")
    async def levelrole_add(self, ctx: commands.Context, level: int, role: discord.Role) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        if level < 1 or level > 1000:
            await ctx.send(embed=make_embed("Invalid level", "Use a level between 1 and 1000.", color=DANGER), ephemeral=True)
            return
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            await ctx.send(embed=make_embed("Can't use that role", "The role must be below my highest role, and not managed.", color=DANGER), ephemeral=True)
            return
        if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            await ctx.send(embed=make_embed("Can't use that role", "That role is higher than or equal to your highest role.", color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_level_role(ctx.guild.id, level, role.id)
        await ctx.send(embed=make_embed("Level role set", f"{role.mention} will be given at **level {level}**.", color=SUCCESS))

    @levelrole.command(name="remove", description="Stop granting a role at a given level.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def levelrole_remove(self, ctx: commands.Context, level: int) -> None:
        assert ctx.guild
        ok = await self.bot.db.remove_level_role(ctx.guild.id, level)
        if not ok:
            await ctx.send(embed=make_embed("Nothing to remove", f"There is no level role at level {level}.", color=DANGER), ephemeral=True)
            return
        await ctx.send(embed=make_embed("Level role removed", f"No role will be granted at level {level} any more.", color=SUCCESS))

    @levelrole.command(name="list", description="List automatic level roles.")
    @commands.guild_only()
    async def levelrole_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.bot.db.level_roles(ctx.guild.id)
        if not rows:
            await ctx.send(embed=make_embed("Level roles", "None set. A mod can add some with `.levelrole add`."))
            return
        lines = []
        for row in rows:
            role = ctx.guild.get_role(int(row["role_id"]))
            mention = role.mention if role else f"`{row['role_id']}` (deleted)"
            lines.append(f"Level **{row['level']}** — {mention}")
        await ctx.send(embed=make_embed("Level roles", "\n".join(lines)))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Leveling(bot))
