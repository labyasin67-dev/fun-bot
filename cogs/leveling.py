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
    SUCCESS,
    WARNING,
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

    def _levels_off(self, guild_id: int) -> bool:
        """True when the server turned levelling off (see cogs/levels_switch.py)."""
        return guild_id in getattr(self.bot, "levels_off_guilds", ())

    async def _reply_if_off(self, ctx: commands.Context) -> bool:
        assert ctx.guild
        if not self._levels_off(ctx.guild.id):
            return False
        await ctx.send(embed=make_embed("Levelling is off", "Levelling is turned off in this server, so there are no levels, ranks or leaderboards right now.", color=WARNING))
        return True

    async def cog_load(self) -> None:
        self.voice_xp_loop.start()

    async def cog_unload(self) -> None:
        self.voice_xp_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or not message.content:
            return
        if self._levels_off(message.guild.id):
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
        if self._levels_off(guild.id):
            return
        old_level = level_from_xp(old_xp)
        new_level = level_from_xp(new_xp)
        if new_level <= old_level:
            return
        member = guild.get_member(user.id)
        if member:
            await self._sync_level_roles(member, new_level)
        channel: discord.abc.Messageable | None = origin_channel
        levelup_id = await self.bot.db.get_feature_channel(guild.id, "levelups")
        if levelup_id:
            found = guild.get_channel(levelup_id)
            if isinstance(found, discord.abc.Messageable):
                channel = found
        if channel is None:
            return
        e = make_embed("Level up!", f"{user.mention} reached **level {new_level}**!", color=SUCCESS)
        try:
            await channel.send(embed=e)
        except discord.HTTPException:
            pass

    async def _sync_level_roles(self, member: discord.Member, level: int) -> None:
        rows = await self.bot.db.level_roles(member.guild.id)
        if not rows or member.guild.me is None:
            return
        to_add: list[discord.Role] = []
        for row in rows:
            if int(row["level"]) > level:
                continue
            role = member.guild.get_role(int(row["role_id"]))
            if role is None or role in member.roles or role >= member.guild.me.top_role or role.managed:
                continue
            to_add.append(role)
        if to_add:
            try:
                await member.add_roles(*to_add, reason="Level role")
            except discord.HTTPException:
                pass

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
            if self._levels_off(guild.id):
                continue
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
                        old_xp, new_xp = await self.bot.db.add_voice_xp_and_seconds(guild.id, member.id, VOICE_XP_PER_MINUTE, VOICE_TICK_SECONDS)
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
        if await self._reply_if_off(ctx):
            return
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
        if await self._reply_if_off(ctx):
            return
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
        if await self._reply_if_off(ctx):
            return
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
        if await self._reply_if_off(ctx):
            return
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

    @commands.hybrid_command(name="setlevelchannel", description="Set the channel for level-up messages, or clear it.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Where to announce level-ups. Omit to announce in the chat that triggered them.")
    async def setlevelchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        await self.bot.db.set_feature_channel(ctx.guild.id, "levelups", channel.id if channel else None)
        if channel:
            await ctx.send(embed=make_embed("Level-up channel set", f"Level-ups will be posted in {channel.mention}."))
        else:
            await ctx.send(embed=make_embed("Level-up channel cleared", "Level-ups from chatting will be posted in the same channel."))

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


    @commands.hybrid_command(name="addxp", description="Add XP to a member.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def addxp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        if member.bot:
            await ctx.send(embed=make_embed("Can't do that", "Bots don't earn XP.", color=DANGER), ephemeral=True)
            return
        if amount <= 0 or amount > 1_000_000:
            await ctx.send(embed=make_embed("Invalid amount", "Amount must be between 1 and 1,000,000.", color=DANGER), ephemeral=True)
            return
        old, new = await self.bot.db.add_xp(ctx.guild.id, member.id, amount)
        _, _, _, _ = level_progress(new)
        if new > old:
            await self._handle_level_up(ctx.guild, member, ctx.channel, old, new)
        level, _, _, _ = level_progress(new)
        await ctx.send(embed=make_embed("XP added", f"{member.mention}: **{old:,}** → **{new:,}** XP · Level **{level}**", color=SUCCESS))
        from cogs.channels import post_modlog
        await post_modlog(self.bot, ctx.guild, "XP added", f"**Staff:** {ctx.author.mention}\n**Target:** {member.mention} (`{member.id}`)\n**Old:** {old:,} → **New:** {new:,}", color=SUCCESS)

    @commands.hybrid_command(name="removexp", description="Remove XP from a member.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def removexp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        if member.bot:
            await ctx.send(embed=make_embed("Can't do that", "Bots don't earn XP.", color=DANGER), ephemeral=True)
            return
        if amount <= 0 or amount > 1_000_000:
            await ctx.send(embed=make_embed("Invalid amount", "Amount must be between 1 and 1,000,000.", color=DANGER), ephemeral=True)
            return
        old_xp = int((await self.bot.db.ensure_member(ctx.guild.id, member.id))["xp"])
        new_xp = max(0, old_xp - amount)
        old, new = await self.bot.db.set_xp(ctx.guild.id, member.id, new_xp)
        level, _, _, _ = level_progress(new)
        await ctx.send(embed=make_embed("XP removed", f"{member.mention}: **{old:,}** → **{new:,}** XP · Level **{level}**", color=SUCCESS))
        from cogs.channels import post_modlog
        await post_modlog(self.bot, ctx.guild, "XP removed", f"**Staff:** {ctx.author.mention}\n**Target:** {member.mention} (`{member.id}`)\n**Old:** {old:,} → **New:** {new:,}", color=WARNING)

    @commands.hybrid_command(name="setxp", description="Set a member's XP to an exact value.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def setxp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        if member.bot:
            await ctx.send(embed=make_embed("Can't do that", "Bots don't earn XP.", color=DANGER), ephemeral=True)
            return
        if amount < 0 or amount > 1_000_000:
            await ctx.send(embed=make_embed("Invalid amount", "Amount must be between 0 and 1,000,000.", color=DANGER), ephemeral=True)
            return
        old, new = await self.bot.db.set_xp(ctx.guild.id, member.id, amount)
        if new > old:
            await self._handle_level_up(ctx.guild, member, ctx.channel, old, new)
        level, _, _, _ = level_progress(new)
        await ctx.send(embed=make_embed("XP set", f"{member.mention}: **{old:,}** → **{new:,}** XP · Level **{level}**", color=SUCCESS))
        from cogs.channels import post_modlog
        await post_modlog(self.bot, ctx.guild, "XP set", f"**Staff:** {ctx.author.mention}\n**Target:** {member.mention} (`{member.id}`)\n**Old:** {old:,} → **New:** {new:,}", color=SUCCESS)

    @commands.hybrid_command(name="setlvl", aliases=["setlv"], description="Set a member's level to an exact value.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(member="The member whose level to set.", level="The level to set them to (1–1000).")
    async def setlvl(self, ctx: commands.Context, member: discord.Member, level: int) -> None:
        if member.bot:
            await ctx.send(embed=make_embed("Can't do that", "Bots don't earn levels.", color=DANGER), ephemeral=True)
            return
        if level < 0 or level > 1000:
            await ctx.send(embed=make_embed("Invalid level", "Level must be between 0 and 1000.", color=DANGER), ephemeral=True)
            return
        target_xp = xp_for_level(level)
        old, new = await self.bot.db.set_xp(ctx.guild.id, member.id, target_xp)
        if new > old:
            await self._handle_level_up(ctx.guild, member, ctx.channel, old, new)
        old_level = level_from_xp(old)
        new_level, _, _, _ = level_progress(new)
        await ctx.send(embed=make_embed("Level set", f"{member.mention}: level **{old_level}** → **{new_level}** ({new:,} XP)", color=SUCCESS))
        from cogs.channels import post_modlog
        await post_modlog(self.bot, ctx.guild, "Level set", f"**Staff:** {ctx.author.mention}\n**Target:** {member.mention} (`{member.id}`)\n**Level:** {new_level}", color=SUCCESS)

async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Leveling(bot))
