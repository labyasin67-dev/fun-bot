"""Fun interaction commands: .slap, .kiss, .laugh, .kick, .yeet, .tickle, .greet, .dap"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils import COLOR, SUCCESS, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

ACTION_GIFS: dict[str, list[str]] = {
    "slap": [
        "https://media.giphy.com/media/L1K396A1e2yoM/giphy.gif",
        "https://media.giphy.com/media/13H57c5kh0yB0c/giphy.gif",
        "https://media.giphy.com/media/l0MYr5Qmw988ZB77a/giphy.gif",
    ],
    "kiss": [
        "https://media.giphy.com/media/l0HlN7Ow7RtE4Bq8I/giphy.gif",
        "https://media.giphy.com/media/xT9IgLjqeZ7S33b1rK/giphy.gif",
        "https://media.giphy.com/media/3o7WIVsJ16qZJpf5mI/giphy.gif",
    ],
    "laugh": [
        "https://media.giphy.com/media/103gZ5UKVNPMjO/giphy.gif",
        "https://media.giphy.com/media/l0MYr5Qmw988ZB77a/giphy.gif",
        "https://media.giphy.com/media/xT9IgLjqeZ7S33b1rK/giphy.gif",
    ],
    "kick": [
        "https://media.giphy.com/media/l0HlO731fS0gO/giphy.gif",
        "https://media.giphy.com/media/3o7WIVsJ16qZJpf5mI/giphy.gif",
        "https://media.giphy.com/media/xT9IgLjqeZ7S33b1rK/giphy.gif",
    ],
    "yeet": [
        "https://media.giphy.com/media/3ohhwdB7daQfXM5vPq/giphy.gif",
        "https://media.giphy.com/media/l0HlN7Ow7RtE4Bq8I/giphy.gif",
        "https://media.giphy.com/media/xT9IgLjqeZ7S33b1rK/giphy.gif",
    ],
    "tickle": [
        "https://media.giphy.com/media/l0HlN7Ow7RtE4Bq8I/giphy.gif",
        "https://media.giphy.com/media/103gZ5UKVNPMjO/giphy.gif",
        "https://media.giphy.com/media/l0MYr5Qmw988ZB77a/giphy.gif",
    ],
    "greet": [
        "https://media.giphy.com/media/l0HlO731fS0gO/giphy.gif",
        "https://media.giphy.com/media/103gZ5UKVNPMjO/giphy.gif",
        "https://media.giphy.com/media/xT9IgLjqeZ7S33b1rK/giphy.gif",
    ],
    "dap": [
        "https://media.giphy.com/media/l0MYr5Qmw988ZB77a/giphy.gif",
        "https://media.giphy.com/media/3o7WIVsJ16qZJpf5mI/giphy.gif",
        "https://media.giphy.com/media/l0HlN7Ow7RtE4Bq8I/giphy.gif",
    ],
}

ACTION_VERBS: dict[str, str] = {
    "slap": "slaps",
    "kiss": "kisses",
    "laugh": "laughs at",
    "kick": "kicks",
    "yeet": "yeets",
    "tickle": "tickles",
    "greet": "greets",
    "dap": "daps up",
}


class FunCommands(commands.Cog):
    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    def _random_gif(self, action: str) -> str:
        return random.choice(ACTION_GIFS[action])

    async def _do_action(
        self,
        ctx: commands.Context,
        action: str,
        target: discord.Member | None = None,
    ) -> None:
        assert ctx.guild is not None
        author = ctx.author
        if target is None:
            await ctx.send(
                embed=make_embed(
                    "Missing target",
                    f"Mention someone to {action}! Example: `.{action} @user`",
                    color=COLOR,
                ),
                ephemeral=True,
            )
            return
        if target.id == author.id:
            await ctx.send(
                embed=make_embed(
                    "Nice try",
                    f"You can't {action} yourself!",
                    color=COLOR,
                ),
                ephemeral=True,
            )
            return

        # Track slap counts in the database
        if action == "slap":
            await self.bot.db.add_fun_slap(ctx.guild.id, author.id, target.id)
            count = await self.bot.db.count_fun_slaps(ctx.guild.id, target.id)
            count_text = f"This is the **{count}** time {target.mention} has been slapped."
        else:
            count_text = ""

        gif = self._random_gif(action)
        verb = ACTION_VERBS[action]
        desc = f"{author.mention} {verb} {target.mention}! {count_text}".strip()
        e = make_embed(f"{action.capitalize()}!", desc, color=SUCCESS)
        e.set_image(url=gif)
        await ctx.send(embed=e)

    # --- prefix commands ---

    @commands.hybrid_command(name="slap", description="Slap someone!")
    @commands.guild_only()
    async def slap(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "slap", target)

    @commands.hybrid_command(name="kiss", description="Kiss someone!")
    @commands.guild_only()
    async def kiss(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "kiss", target)

    @commands.hybrid_command(name="laugh", description="Laugh at someone!")
    @commands.guild_only()
    async def laugh(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "laugh", target)

    @commands.hybrid_command(name="kick", description="Kick someone (fun, not a mod kick)!")
    @commands.guild_only()
    async def kick(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "kick", target)

    @commands.hybrid_command(name="yeet", description="Yeet someone!")
    @commands.guild_only()
    async def yeet(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yeet", target)

    @commands.hybrid_command(name="tickle", description="Tickle someone!")
    @commands.guild_only()
    async def tickle(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "tickle", target)

    @commands.hybrid_command(name="greet", description="Greet someone!")
    @commands.guild_only()
    async def greet(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "greet", target)

    @commands.hybrid_command(name="dap", description="Dap someone up!")
    @commands.guild_only()
    async def dap(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "dap", target)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(FunCommands(bot))
