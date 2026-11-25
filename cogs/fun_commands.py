"""Fun interaction commands: .slap, .kiss, .laugh, .boot, .yeet, .tickle, .hug, .dap"""

from __future__ import annotations

import io
import random
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

try:
    from PIL import Image, ImageSequence
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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
    "hug": [f"{BASE_GIF_URL}/hug/{i}.gif" for i in range(1, 34)],
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

# Target max width for enlarged GIFs (keeps file size reasonable while
# making them visibly larger on PC screens).
ENLARGE_MAX_WIDTH = 900


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


def enlarge_gif(gif_bytes: bytes, max_width: int = ENLARGE_MAX_WIDTH) -> bytes:
    """Enlarge an animated GIF by scaling every frame up to max_width.

    Returns the enlarged GIF as raw bytes. Falls back to the original bytes
    if PIL isn't installed or anything goes wrong.
    """
    if not _PIL_AVAILABLE:
        return gif_bytes

    try:
        buf = io.BytesIO(gif_bytes)
        with Image.open(buf) as im:
            if im.n_frames <= 1:
                # Single image — just resize and return
                frame = im.convert("RGBA")
                w, h = frame.size
                if w > max_width:
                    scale = max_width / w
                    new_size = (max_width, max(1, int(h * scale)))
                    frame = frame.resize(new_size, Image.LANCZOS)
                out = io.BytesIO()
                frame.save(out, format="GIF")
                return out.getvalue()

            frames = []
            durations = []
            for frame in ImageSequence.Iterator(im):
                durations.append(frame.info.get("duration", 100))
                frame_rgba = frame.convert("RGBA")
                w, h = frame_rgba.size
                if w > max_width:
                    scale = max_width / w
                    new_size = (max_width, max(1, int(h * scale)))
                    frame_rgba = frame_rgba.resize(new_size, Image.LANCZOS)
                frames.append(frame_rgba)

            out = io.BytesIO()
            frames[0].save(
                out,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
            )
            return out.getvalue()
    except Exception:
        # If resizing fails for any reason, return original bytes so the
        # command still works (just without enlargement).
        return gif_bytes


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
        # Build subtext for every action type
        subtext_map = {
            "slap": f"-# {target.mention} has been slapped {ordinal(count)} time.",
            "kiss": f"-# {target.mention} was kissed by {author.mention}.",
            "laugh": f"-# {target.mention} is being laughed at by {author.mention}.",
            "boot": f"-# {target.mention} got booted by {author.mention}.",
            "yeet": f"-# {target.mention} was yeeted by {author.mention}.",
            "tickle": f"-# {target.mention} was tickled by {author.mention}.",
            "hug": f"-# {target.mention} got a hug from {author.mention}.",
            "dap": f"-# {target.mention} got dapped by {author.mention}.",
        }
        subtext = subtext_map[action]

        # Download GIF, enlarge it, and attach as a file so it covers more
        # of the screen on PC.
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

        enlarged = enlarge_gif(gif_bytes)

        description = f"# <@{author.id}> {verb} <@{target.id}>\n\n{subtext}"
        e = make_embed(description=description, color=SUCCESS)
        file = discord.File(io.BytesIO(enlarged), filename="fun.gif")
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


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(FunCommands(bot))
