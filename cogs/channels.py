"""Assign bot features to channels, and post moderation logs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils import COLOR
from cogs.v2 import build_game_layout

if TYPE_CHECKING:
    from main import SocializeBot

FEATURES: dict[str, str] = {
    "alts": "Alt-account alerts",
    "modlog": "Moderation log (ban, kick, timeout, warn, purge)",
    "levelups": "Level-up announcements",
    "welcome": "Welcome messages",
    "games": "Games (commands only work in these channels once set)",
    "counting": "Counting",
}

ALIASES = {
    "alt": "alts",
    "alert": "alts",
    "alerts": "alts",
    "audit": "alts",
    "mod": "modlog",
    "mods": "modlog",
    "modlogs": "modlog",
    "log": "modlog",
    "logs": "modlog",
    "level": "levelups",
    "levelup": "levelups",
    "levels": "levelups",
    "game": "games",
    "count": "counting",
}

MULTI_FEATURES = {"games"}

GAME_COMMANDS = {
    "games",
    "uno",
    "rps",
    "wyr",
    "tod",
    "truth",
    "dare",
    "eightball",
    "buttonhunt",
    "diceduel",
    "backwards",
    "scramble",
    "celebrity",
    "landmark",
    "pattern",
    "capital",
    "redlight",
    "missingemoji",
    "sequencehunt",
    "colorhunt",
    "emojieq",
    "flag",
    "reaction",
    "language",
    "word",
    "nickname",
    "trivia",
    "hilo",
}

FEATURE_CHOICES = [app_commands.Choice(name=name, value=name) for name in FEATURES]


def normalize_feature(raw: str) -> str | None:
    key = raw.strip().lower()
    if key in FEATURES:
        return key
    return ALIASES.get(key)


def format_channel_list(guild: discord.Guild, channel_ids: list[int]) -> str:
    if not channel_ids:
        return "Not set"
    parts: list[str] = []
    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        parts.append(channel.mention if channel else f"`#{channel_id}` (deleted)")
    return ", ".join(parts)


async def post_modlog(
    bot: SocializeBot,
    guild: discord.Guild,
    title: str,
    description: str,
    *,
    color: int = COLOR,
) -> None:
    try:
        await bot.db.add_mod_log(guild.id, title, description)
    except Exception:
        pass
    channel_id = await bot.db.get_feature_channel(guild.id, "modlog")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.send(view=build_game_layout(title, description))
    except discord.HTTPException:
        pass


class ChannelAssignments(commands.Cog):
    """Route features to specific channels."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_check(self.games_channel_check)

    async def cog_unload(self) -> None:
        self.bot.remove_check(self.games_channel_check)

    async def games_channel_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or ctx.command is None:
            return True
        root = ctx.command.qualified_name.split()[0]
        if root not in GAME_COMMANDS:
            return True
        allowed = await self.bot.db.get_feature_channels(ctx.guild.id, "games")
        if not allowed or ctx.channel.id in allowed:
            return True
        mentions = ", ".join(f"<#{channel_id}>" for channel_id in allowed)
        raise commands.CheckFailure(f"Game commands can only be used in {mentions}.")

    @commands.hybrid_command(name="setchannel", description="Assign a bot feature to a channel, or use none to clear.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(feature="Which feature to assign.", channel="A channel mention, or 'none' to clear.")
    @app_commands.choices(feature=FEATURE_CHOICES)
    async def setchannel(self, ctx: commands.Context, feature: str, channel: str) -> None:
        assert ctx.guild
        key = normalize_feature(feature)
        if key is None:
            names = ", ".join(f"`{name}`" for name in FEATURES)
            await ctx.send(view=build_game_layout("Unknown feature", f"Use one of: {names}."))
            return
        raw = channel.strip()
        if raw.lower() in {"none", "off", "clear", "disable", "reset"}:
            if key == "counting":
                await self.bot.db.update_settings(
                    ctx.guild.id, counting_next=1, counting_last_user=None
                )
            await self.bot.db.set_feature_channel(ctx.guild.id, key, None)
            await ctx.send(view=build_game_layout("Channel cleared", f"**{key}** is no longer assigned to a channel."))
            return
        try:
            target = await commands.TextChannelConverter().convert(ctx, raw)
        except commands.BadArgument:
            await ctx.send(view=build_game_layout("Invalid channel", "Mention a text channel, or type `none` to clear the assignment."))
            return
        if key in MULTI_FEATURES:
            added = await self.bot.db.add_feature_channel(ctx.guild.id, key, target.id)
            if not added:
                await ctx.send(view=build_game_layout("Already set", f"{target.mention} is already a **{key}** channel."))
                return
            all_ids = await self.bot.db.get_feature_channels(ctx.guild.id, key)
            await ctx.send(view=build_game_layout("Channel added", f"Added {target.mention} as a **{key}** channel.\nCurrent: {format_channel_list(ctx.guild, all_ids)}\nUse `.removechannel {key} {target.mention}` to remove one."))
            return
        extra = ""
        if key == "counting":
            existing = await self.bot.db.get_feature_channel(ctx.guild.id, "counting")
            if not existing:
                await self.bot.db.update_settings(
                    ctx.guild.id, counting_next=1, counting_last_user=None
                )
                extra = " Start at **1**."
        await self.bot.db.set_feature_channel(ctx.guild.id, key, target.id)
        await ctx.send(view=build_game_layout("Channel set", f"**{key}** will use {target.mention}.{extra}"))

    @commands.hybrid_command(name="removechannel", description="Remove a channel assignment. For games, remove one channel.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(feature="Which feature.", channel="The channel to remove. Required for games.")
    @app_commands.choices(feature=FEATURE_CHOICES)
    async def removechannel(
        self,
        ctx: commands.Context,
        feature: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        assert ctx.guild
        key = normalize_feature(feature)
        if key is None:
            names = ", ".join(f"`{name}`" for name in FEATURES)
            await ctx.send(view=build_game_layout("Unknown feature", f"Use one of: {names}."))
            return
        if key in MULTI_FEATURES and channel is None:
            await ctx.send(view=build_game_layout("Channel required", f"Use `.removechannel {key} #channel` to remove one {key} channel, or `.setchannel {key} none` to clear them all."))
            return
        if key == "counting" and channel is None:
            await self.bot.db.update_settings(
                ctx.guild.id, counting_next=1, counting_last_user=None
            )
        removed = await self.bot.db.remove_feature_channel(
            ctx.guild.id, key, channel.id if channel else None
        )
        if not removed:
            await ctx.send(view=build_game_layout("Nothing to remove", f"That channel isn't assigned to **{key}**." if channel else f"**{key}** has no channel set."))
            return
        if key in MULTI_FEATURES:
            remaining = await self.bot.db.get_feature_channels(ctx.guild.id, key)
            leftover = format_channel_list(ctx.guild, remaining)
            await ctx.send(view=build_game_layout("Channel removed", f"Removed {channel.mention if channel else 'that channel'} from **{key}**.\nCurrent: {leftover}"))
            return
        await ctx.send(view=build_game_layout("Channel cleared", f"**{key}** is no longer assigned to a channel."))

    @commands.hybrid_command(name="channels", description="Show which channels are assigned to bot features.")
    @commands.guild_only()
    async def channels(self, ctx: commands.Context) -> None:
        assert ctx.guild
        assigned = await self.bot.db.list_feature_channels(ctx.guild.id)
        lines = []
        for key, label in FEATURES.items():
            lines.append(f"• **{key}** — {format_channel_list(ctx.guild, assigned.get(key) or [])}\n  _{label}_")
        await ctx.send(view=build_game_layout("Feature channels", "\n".join(lines) + "\n\nUse `.setchannel <feature> #channel` to assign, or `.setchannel <feature> none` to clear. `.setwelcome`, `.setlevelchannel`, `.setcounting` and `.altconfig channel` stay in sync."))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(ChannelAssignments(bot))


