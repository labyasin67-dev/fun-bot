"""Welcome messages for new members."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from discord.components import UnfurledMediaItem

from cogs.v2 import build_game_layout

if TYPE_CHECKING:
    from main import SocializeBot

DEFAULT_WELCOME = "Welcome to {server}, {mention}! You are member #{membercount}."


def render_welcome(template: str, member: discord.Member) -> str:
    guild = member.guild
    return (
        (template or DEFAULT_WELCOME)
        .replace("{user}", member.display_name)
        .replace("{mention}", member.mention)
        .replace("{server}", guild.name)
        .replace("{membercount}", str(guild.member_count or len(guild.members)))
    )


class Welcome(commands.Cog):
    """Greet members when they join."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    def _welcome_embed(self, member: discord.Member, text: str):
        layout = build_game_layout("Welcome!", text)
        if member.guild.icon:
            layout.section = discord.ui.Section(accessory=discord.ui.Thumbnail(UnfurledMediaItem(member.guild.icon.url)))
        return layout

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        channel_id = await self.bot.db.get_feature_channel(member.guild.id, "welcome")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        settings = await self.bot.db.get_settings(member.guild.id)
        text = render_welcome((settings["welcome_message"] if settings else None) or DEFAULT_WELCOME, member)
        try:
            await channel.send(view=self._welcome_embed(member, text))
        except discord.HTTPException:
            pass

    @commands.hybrid_command(name="setwelcome", description="Set the welcome channel and optional message.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel for welcome messages. Omit to disable welcomes.",
        message="Optional message. Placeholders: {mention} {user} {server} {membercount}",
    )
    async def setwelcome(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, message: str | None = None) -> None:
        assert ctx.guild
        if channel is None:
            await self.bot.db.set_feature_channel(ctx.guild.id, "welcome", None)
            await ctx.send(layout=build_game_layout("Welcome messages disabled", "I won't greet new members until you set a channel again."))
            return
        await self.bot.db.set_feature_channel(ctx.guild.id, "welcome", channel.id)
        await self.bot.db.update_settings(ctx.guild.id, welcome_message=message or DEFAULT_WELCOME)
        preview = render_welcome(message or DEFAULT_WELCOME, ctx.author if isinstance(ctx.author, discord.Member) else ctx.guild.me)  # type: ignore[arg-type]
        await ctx.send(
            layout=build_game_layout(
                "Welcome channel set",
                f"New members will be greeted in {channel.mention}.\n\nPreview:\n{preview}\n\n"
                "Placeholders: `{mention}` `{user}` `{server}` `{membercount}`",
            )
        )

    @commands.hybrid_command(name="welcometest", description="Send a test welcome message.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def welcometest(self, ctx: commands.Context) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        channel_id = await self.bot.db.get_feature_channel(ctx.guild.id, "welcome")
        if not channel_id:
            await ctx.send(layout=build_game_layout("Welcome isn't set up", "Set a channel first with `.setwelcome #channel`."), ephemeral=True)
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await ctx.send(layout=build_game_layout("Channel missing", "The welcome channel was deleted. Set it again with `.setwelcome`."), ephemeral=True)
            return
        settings = await self.bot.db.get_settings(ctx.guild.id)
        text = render_welcome((settings["welcome_message"] if settings else None) or DEFAULT_WELCOME, ctx.author)
        await channel.send(view=self._welcome_embed(ctx.author, text))
        if channel.id != ctx.channel.id:
            await ctx.send(layout=build_game_layout("Test sent", f"Posted a preview in {channel.mention}."), ephemeral=True)
        elif ctx.interaction:
            await ctx.send(layout=build_game_layout("Test sent", "The welcome preview is above."), ephemeral=True)


    async def post_test(self, guild: discord.Guild, member: discord.Member) -> discord.TextChannel:
        channel_id = await self.bot.db.get_feature_channel(guild.id, "welcome")
        if not channel_id:
            raise ValueError("Set a welcome channel first.")
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The welcome channel is missing. Set it again.")
        settings = await self.bot.db.get_settings(guild.id)
        text = render_welcome((settings["welcome_message"] if settings else None) or DEFAULT_WELCOME, member)
        await channel.send(view=self._welcome_embed(member, text))
        return channel


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Welcome(bot))

