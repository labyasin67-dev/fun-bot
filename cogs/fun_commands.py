"""Fun interaction commands: .slap, .kiss, .laugh, .boot, .yeet, .tickle, .hug, .dap, .bonk, .cuddle, .flirt, .poke"""

from __future__ import annotations

import io
import random
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from utils import COLOR, SUCCESS, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

BASE_GIF_URL = "https://raw.githubusercontent.com/iceefruit/giffycdn/main"

ACTION_GIFS: dict[str, list[str]] = {
    "slap":   [f"{BASE_GIF_URL}/slap/{i}.gif"   for i in range(1, 30)],
    "kiss":   [f"{BASE_GIF_URL}/kiss/{i}.gif"   for i in range(1, 42)],
    "laugh":  [f"{BASE_GIF_URL}/laugh/{i}.gif"  for i in range(1, 32)],
    "boot":   [f"{BASE_GIF_URL}/punch/{i}.gif"  for i in range(1, 13)],
    "yeet":   [f"{BASE_GIF_URL}/happy/{i}.gif"  for i in range(1, 24)],
    "tickle": [f"{BASE_GIF_URL}/tickle/{i}.gif" for i in range(1, 20)],
    "hug":    [f"{BASE_GIF_URL}/hug/{i}.gif"    for i in range(1, 34)],
    "dap":    [f"{BASE_GIF_URL}/brofist/{i}.gif" for i in range(1, 9)],
    "bonk":   [f"{BASE_GIF_URL}/slap/{i}.gif"   for i in range(1, 30)],
    "cuddle": [f"{BASE_GIF_URL}/cuddle/{i}.gif" for i in range(1, 32)],
    "flirt":  [f"{BASE_GIF_URL}/love/{i}.gif"   for i in range(1, 10)],
    "poke":   [f"{BASE_GIF_URL}/poke/{i}.gif"   for i in range(1, 28)],
}

ACTION_VERBS: dict[str, str] = {
    "slap":   "slaps",
    "kiss":   "kisses",
    "laugh":  "laughs at",
    "boot":   "kicks",
    "yeet":   "yeets",
    "tickle": "tickles",
    "hug":    "hugs",
    "dap":    "daps up",
    "bonk":   "bonks",
    "cuddle": "cuddles",
    "flirt":  "flirts with",
    "poke":   "pokes",
}


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def download_bytes(session: aiohttp.ClientSession, url: str) -> bytes | None:
    """Download raw bytes from a URL."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None


class FunCommands(commands.Cog):
    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "image/gif, image/*, */*",
                    "Referer": "https://github.com/",
                }
            )
        return self._session

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
        count = 0
        if action == "slap":
            await self.bot.db.add_fun_slap(ctx.guild.id, author.id, target.id)
            count = await self.bot.db.count_fun_slaps(ctx.guild.id, target.id)

        verb = ACTION_VERBS[action]
        subtext_map = {
            "slap":   f"-# {target.mention} has been slapped {ordinal(count)} time.",
            "kiss":   f"-# {target.mention} was kissed by {author.mention}.",
            "laugh":  f"-# {target.mention} is being laughed at by {author.mention}.",
            "boot":   f"-# {target.mention} got booted by {author.mention}.",
            "yeet":   f"-# {target.mention} was yeeted by {author.mention}.",
            "tickle": f"-# {target.mention} was tickled by {author.mention}.",
            "hug":    f"-# {target.mention} got a hug from {author.mention}.",
            "dap":    f"-# {target.mention} got dapped by {author.mention}.",
            "bonk":   f"-# {target.mention} got bonked by {author.mention}.",
            "cuddle": f"-# {target.mention} got cuddled by {author.mention}.",
            "flirt":  f"-# {target.mention} got flirted with by {author.mention}.",
            "poke":   f"-# {target.mention} got poked by {author.mention}.",
        }
        subtext = subtext_map[action]

        # Download GIF and attach as a file so Discord renders it large in the embed
        gif_url = self._random_gif(action)
        gif_bytes = await download_bytes(self.session, gif_url)
        if gif_bytes is None:
            await ctx.send(
                embed=make_embed(
                    "Error",
                    "Failed to load GIF. Try again later.",
                    color=COLOR,
                ),
                ephemeral=True,
            )
            return

        description = f"# <@{author.id}> {verb} <@{target.id}>\n\n{subtext}"
        e = make_embed(description=description, color=SUCCESS)
        file = discord.File(io.BytesIO(gif_bytes), filename="fun.gif")
        e.set_image(url="attachment://fun.gif")

        await ctx.send(embed=e, file=file)

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

    @commands.hybrid_command(name="bonk", description="Bonk someone on the head!")
    @commands.guild_only()
    async def bonk(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "bonk", target)

    @commands.hybrid_command(name="cuddle", description="Cuddle someone!")
    @commands.guild_only()
    async def cuddle(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "cuddle", target)

    @commands.hybrid_command(name="flirt", description="Flirt with someone!")
    @commands.guild_only()
    async def flirt(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "flirt", target)

    @commands.hybrid_command(name="poke", description="Poke someone!")
    @commands.guild_only()
    async def poke(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "poke", target)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(FunCommands(bot))
