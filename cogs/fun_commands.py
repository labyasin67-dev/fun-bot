"""Fun interaction commands: .slap, .kiss, .laugh, .boot, .yeet, .tickle, .hug, .dap"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils import COLOR, SUCCESS, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

BASE_GIF_URL = "https://raw.githubusercontent.com/iceefruit/giffycdn/main"

ACTION_GIFS: dict[str, list[str]] = {
    "slap": [f"{BASE_GIF_URL}/slap/{i}.gif" for i in range(1, 30)],
    "kiss": [f"{BASE_GIF_URL}/kiss/{i}.gif" for i in range(1, 42)],
    "laugh": [f"{BASE_GIF_URL}/laugh/{i}.gif" for i in range(1, 32)],
    "boot": [f"{BASE_GIF_URL}/punch/{i}.gif" for i in range(1, 13)],
    "yeet": [f"{BASE_GIF_URL}/happy/{i}.gif" for i in range(1, 24)],
    "tickle": [f"{BASE_GIF_URL}/tickle/{i}.gif" for i in range(1, 20)],
    "greet": [f"{BASE_GIF_URL}/hug/{i}.gif" for i in range(1, 34)],
    "dap": [f"{BASE_GIF_URL}/brofist/{i}.gif" for i in range(1, 9)],
}

ACTION_VERBS: dict[str, str] = {
    "slap": "slaps",
    "kiss": "kisses",
    "laugh": "laughs at",
    "boot": "kicks",
    "yeet": "yeets",
    "tickle": "tickles",
    "hug": "hugs",
    "dap": "daps up",
}


class FunCommands(commands.Cog):
    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    def _random_gif(self, action: str) -> str:
        import random
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

        gif_url = self._random_gif(action)

        verb = ACTION_VERBS[action]
        desc = f"{author.mention} {verb} {target.mention}! {count_text}".strip()
        e = make_embed(f"{action.capitalize()}!", desc, color=SUCCESS)
        e.set_image(url=gif_url)

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

    @commands.hybrid_command(name="boot", description="Boot someone (fun, not a mod kick)!")
    @commands.guild_only()
    async def boot(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "boot", target)

    @commands.hybrid_command(name="yeet", description="Yeet someone!")
    @commands.guild_only()
    async def yeet(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yeet", target)

    @commands.hybrid_command(name="tickle", description="Tickle someone!")
    @commands.guild_only()
    async def tickle(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "tickle", target)

    @commands.hybrid_command(name="hug", description="Hug someone!")
    @commands.guild_only()
    async def hug(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "hug", target)

    @commands.hybrid_command(name="dap", description="Dap someone up!")
    @commands.guild_only()
    async def dap(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "dap", target)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(FunCommands(bot))
