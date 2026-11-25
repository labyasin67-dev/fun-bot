"""Fun interaction commands — all 956 GIFs from iceefruit/giffycdn mapped to relatable commands.

Categories → commands (every category covered):
slap→.slap, kiss→.kiss, laugh→.laugh, punch→.boot, happy→.yeet, tickle→.tickle,
hug→.hug, brofist→.dap, slap→.bonk, cuddle→.cuddle, love→.flirt, poke→.poke,
airkiss→.airkiss, angrystare→.angrystare, bite→.bite, bleh→.bleh,
celebrate→.celebrate, cheers→.cheers, clap→.clap, confused→.confused,
cool→.cool, cry→.cry, dance→.dance, drool→.drool, evillaugh→.evillaugh,
facepalm→.facepalm, handhold→.handhold, headbang→.headbang, lick→.lick,
mad→.mad, nervous→.nervous, nom→.eat, nuzzle→.boop, nyah→.nyah,
pat→.pat, peek→.peek, pinch→.pinch, pout→.pout, sad→.sad,
scared→.scared, shout→.shout, shrug→.shrug, shy→.shy, sigh→.sigh,
sip→.sip, sleep→.sleep, slowclap→.slowclap, smack→.smack,
smile→.smile, sneeze→.sneeze, sorry→.sorry, stare→.stare,
surprised→.surprised, sweat→.sweat, thumbsup→.thumbsup,
tired→.tired, wave→.wave, wink→.wink, woah→.woah,
yawn→.yawn, yay→.yay, yes→.yes

Most commands are prefix-only (.command) to stay under Discord's 100 global
slash-command limit. A small set of popular ones are hybrid (slash + prefix).
"""

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
    # Original commands
    "slap":   [f"{BASE_GIF_URL}/slap/{i}.gif"   for i in range(1, 30)],
    "kiss":   [f"{BASE_GIF_URL}/kiss/{i}.gif"   for i in range(1, 42)],
    "laugh":  [f"{BASE_GIF_URL}/laugh/{i}.gif"  for i in range(1, 32)],
    "boot":   [f"{BASE_GIF_URL}/punch/{i}.gif"  for i in range(1, 13)],
    "yeet":   [f"{BASE_GIF_URL}/happy/{i}.gif"  for i in range(1, 24)],
    "tickle": [f"{BASE_GIF_URL}/tickle/{i}.gif" for i in range(1, 21)],
    "hug":    [f"{BASE_GIF_URL}/hug/{i}.gif"    for i in range(1, 34)],
    "dap":    [f"{BASE_GIF_URL}/brofist/{i}.gif" for i in range(1, 9)],
    "bonk":   [f"{BASE_GIF_URL}/slap/{i}.gif"   for i in range(1, 30)],
    "cuddle": [f"{BASE_GIF_URL}/cuddle/{i}.gif" for i in range(1, 32)],
    "flirt":  [f"{BASE_GIF_URL}/love/{i}.gif"   for i in range(1, 10)],
    "poke":   [f"{BASE_GIF_URL}/poke/{i}.gif"   for i in range(1, 28)],

    # New commands (all remaining giffycdn categories)
    "airkiss": [f"{BASE_GIF_URL}/airkiss/{i}.gif" for i in range(1, 7)],
    "angrystare": [f"{BASE_GIF_URL}/angrystare/{i}.gif" for i in range(1, 19)],
    "bite": [f"{BASE_GIF_URL}/bite/{i}.gif" for i in range(1, 24)],
    "bleh": [f"{BASE_GIF_URL}/bleh/{i}.gif" for i in range(1, 8)],
    "celebrate": [f"{BASE_GIF_URL}/celebrate/{i}.gif" for i in range(1, 8)],
    "cheers": [f"{BASE_GIF_URL}/cheers/{i}.gif" for i in range(1, 7)],
    "clap": [f"{BASE_GIF_URL}/clap/{i}.gif" for i in range(1, 9)],
    "confused": [f"{BASE_GIF_URL}/confused/{i}.gif" for i in range(1, 9)],
    "cool": [f"{BASE_GIF_URL}/cool/{i}.gif" for i in range(1, 5)],
    "cry": [f"{BASE_GIF_URL}/cry/{i}.gif" for i in range(1, 40)],
    "dance": [f"{BASE_GIF_URL}/dance/{i}.gif" for i in range(1, 30)],
    "drool": [f"{BASE_GIF_URL}/drool/{i}.gif" for i in range(1, 11)],
    "evillaugh": [f"{BASE_GIF_URL}/evillaugh/{i}.gif" for i in range(1, 11)],
    "facepalm": [f"{BASE_GIF_URL}/facepalm/{i}.gif" for i in range(1, 16)],
    "handhold": [f"{BASE_GIF_URL}/handhold/{i}.gif" for i in range(1, 11)],
    "headbang": [f"{BASE_GIF_URL}/headbang/{i}.gif" for i in range(1, 9)],
    "lick": [f"{BASE_GIF_URL}/lick/{i}.gif" for i in range(1, 11)],
    "mad": [f"{BASE_GIF_URL}/mad/{i}.gif" for i in range(1, 21)],
    "nervous": [f"{BASE_GIF_URL}/nervous/{i}.gif" for i in range(1, 14)],
    "eat": [f"{BASE_GIF_URL}/nom/{i}.gif" for i in range(1, 32)],
    "boop": [f"{BASE_GIF_URL}/nuzzle/{i}.gif" for i in range(1, 10)],
    "nyah": [f"{BASE_GIF_URL}/nyah/{i}.gif" for i in range(1, 8)],
    "pat": [f"{BASE_GIF_URL}/pat/{i}.gif" for i in range(1, 32)],
    "peek": [f"{BASE_GIF_URL}/peek/{i}.gif" for i in range(1, 7)],
    "pinch": [f"{BASE_GIF_URL}/pinch/{i}.gif" for i in range(1, 10)],
    "pout": [f"{BASE_GIF_URL}/pout/{i}.gif" for i in range(1, 30)],
    "sad": [f"{BASE_GIF_URL}/sad/{i}.gif" for i in range(1, 6)],
    "scared": [f"{BASE_GIF_URL}/scared/{i}.gif" for i in range(1, 18)],
    "shout": [f"{BASE_GIF_URL}/shout/{i}.gif" for i in range(1, 10)],
    "shrug": [f"{BASE_GIF_URL}/shrug/{i}.gif" for i in range(1, 13)],
    "shy": [f"{BASE_GIF_URL}/shy/{i}.gif" for i in range(1, 14)],
    "sigh": [f"{BASE_GIF_URL}/sigh/{i}.gif" for i in range(1, 8)],
    "sip": [f"{BASE_GIF_URL}/sip/{i}.gif" for i in range(1, 11)],
    "sleep": [f"{BASE_GIF_URL}/sleep/{i}.gif" for i in range(1, 30)],
    "slowclap": [f"{BASE_GIF_URL}/slowclap/{i}.gif" for i in range(1, 4)],
    "smack": [f"{BASE_GIF_URL}/smack/{i}.gif" for i in range(1, 17)],
    "smile": [f"{BASE_GIF_URL}/smile/{i}.gif" for i in range(1, 32)],
    "sneeze": [f"{BASE_GIF_URL}/sneeze/{i}.gif" for i in range(1, 5)],
    "sorry": [f"{BASE_GIF_URL}/sorry/{i}.gif" for i in range(1, 5)],
    "stare": [f"{BASE_GIF_URL}/stare/{i}.gif" for i in range(1, 28)],
    "surprised": [f"{BASE_GIF_URL}/surprised/{i}.gif" for i in range(1, 15)],
    "sweat": [f"{BASE_GIF_URL}/sweat/{i}.gif" for i in range(1, 5)],
    "thumbsup": [f"{BASE_GIF_URL}/thumbsup/{i}.gif" for i in range(1, 17)],
    "tired": [f"{BASE_GIF_URL}/tired/{i}.gif" for i in range(1, 13)],
    "wave": [f"{BASE_GIF_URL}/wave/{i}.gif" for i in range(1, 27)],
    "wink": [f"{BASE_GIF_URL}/wink/{i}.gif" for i in range(1, 30)],
    "woah": [f"{BASE_GIF_URL}/woah/{i}.gif" for i in range(1, 9)],
    "yawn": [f"{BASE_GIF_URL}/yawn/{i}.gif" for i in range(1, 10)],
    "yay": [f"{BASE_GIF_URL}/yay/{i}.gif" for i in range(1, 8)],
    "yes": [f"{BASE_GIF_URL}/yes/{i}.gif" for i in range(1, 9)],
}

ACTION_VERBS: dict[str, str] = {
    # Original
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
    # New
    "airkiss": "air kisses",
    "angrystare": "angrily stares at",
    "bite": "bites",
    "bleh": "makes a bleh face at",
    "celebrate": "celebrates with",
    "cheers": "cheers with",
    "clap": "claps for",
    "confused": "looks confused at",
    "cool": "looks cool with",
    "cry": "cries at",
    "dance": "dances with",
    "drool": "drools at",
    "evillaugh": "evilly laughs at",
    "facepalm": "facepalms at",
    "handhold": "holds hands with",
    "headbang": "headbangs with",
    "lick": "licks",
    "mad": "gets mad at",
    "nervous": "gets nervous around",
    "eat": "eats with",
    "boop": "boops",
    "nyah": "nyahs at",
    "pat": "pats",
    "peek": "peeks at",
    "pinch": "pinches",
    "pout": "pouts at",
    "sad": "gets sad at",
    "scared": "gets scared at",
    "shout": "shouts at",
    "shrug": "shrugs at",
    "shy": "gets shy around",
    "sigh": "sighs at",
    "sip": "sips with",
    "sleep": "sleeps with",
    "slowclap": "slow claps for",
    "smack": "smacks",
    "smile": "smiles at",
    "sneeze": "sneezes at",
    "sorry": "says sorry to",
    "stare": "stares at",
    "surprised": "gets surprised at",
    "sweat": "sweats at",
    "thumbsup": "gives a thumbs up to",
    "tired": "gets tired with",
    "wave": "waves at",
    "wink": "winks at",
    "woah": "says woah at",
    "yawn": "yawns with",
    "yay": "yays with",
    "yes": "says yes to",
}

# Past-tense verb forms for subtexts and footers
ACTION_VERBS_PAST: dict[str, str] = {
    # Original
    "slap":   "slapped",
    "kiss":   "kissed",
    "laugh":  "laughed at",
    "boot":   "kicked",
    "yeet":   "yeeted",
    "tickle": "tickled",
    "hug":    "hugged",
    "dap":    "dapped",
    "bonk":   "bonked",
    "cuddle": "cuddled",
    "flirt":  "flirted with",
    "poke":   "poked",
    # New
    "airkiss": "air kissed",
    "angrystare": "angrily stared at",
    "bite": "bitten",
    "bleh": "made a bleh face at",
    "celebrate": "celebrated with",
    "cheers": "cheered with",
    "clap": "clapped for",
    "confused": "looked confused at",
    "cool": "looked cool with",
    "cry": "cried at",
    "dance": "danced with",
    "drool": "drooled at",
    "evillaugh": "evilly laughed at",
    "facepalm": "facepalmed",
    "handhold": "held hands with",
    "headbang": "headbanged with",
    "lick": "licked",
    "mad": "made mad at",
    "nervous": "made nervous around",
    "eat": "ate with",
    "boop": "booped",
    "nyah": "nyah'd at",
    "pat": "patted",
    "peek": "peeked at",
    "pinch": "pinched",
    "pout": "pouted at",
    "sad": "made sad at",
    "scared": "scared",
    "shout": "shouted at",
    "shrug": "shrugged at",
    "shy": "made shy around",
    "sigh": "sighed at",
    "sip": "sipped with",
    "sleep": "slept with",
    "slowclap": "slow clapped for",
    "smack": "smacked",
    "smile": "smiled at",
    "sneeze": "sneezed at",
    "sorry": "said sorry to",
    "stare": "stared at",
    "surprised": "surprised",
    "sweat": "sweated at",
    "thumbsup": "gave a thumbs up to",
    "tired": "made tired with",
    "wave": "waved at",
    "wink": "winked at",
    "woah": "said woah at",
    "yawn": "yawned with",
    "yay": "yayed with",
    "yes": "said yes to",
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

        # Track action counts in the database for ALL actions
        await self.bot.db.add_fun_slap(ctx.guild.id, author.id, target.id, action)
        count = await self.bot.db.count_fun_slaps(ctx.guild.id, target.id, action)

        verb = ACTION_VERBS[action]
        verb_past = ACTION_VERBS_PAST[action]

        # Subtext: describes what just happened
        subtext = f"-# {target.mention} {verb_past} by {author.mention}."

        # Footer: tracks how many times this has happened
        footer_text = f"{target.display_name} has been {verb_past} {ordinal(count)} time."

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
        e.set_footer(text=footer_text)
        e.set_image(url="attachment://fun.gif")
        file = discord.File(io.BytesIO(gif_bytes), filename="fun.gif")

        await ctx.send(embed=e, file=file)

    # --- prefix commands ---
    # Only a few popular ones are hybrid (slash + prefix) to stay under
    # Discord's 100 global slash-command limit. Everything else is prefix-only.

    @commands.hybrid_command(name="slap", description="Slap someone!")
    @commands.guild_only()
    async def slap(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "slap", target)

    @commands.hybrid_command(name="kiss", description="Kiss someone!")
    @commands.guild_only()
    async def kiss(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "kiss", target)

    @commands.hybrid_command(name="hug", description="Hug someone!")
    @commands.guild_only()
    async def hug(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "hug", target)

    @commands.hybrid_command(name="tickle", description="Tickle someone!")
    @commands.guild_only()
    async def tickle(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "tickle", target)

    @commands.hybrid_command(name="bonk", description="Bonk someone on the head!")
    @commands.guild_only()
    async def bonk(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "bonk", target)

    @commands.hybrid_command(name="pat", description="Pat someone!")
    @commands.guild_only()
    async def pat(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "pat", target)

    @commands.hybrid_command(name="wave", description="Wave at someone!")
    @commands.guild_only()
    async def wave(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "wave", target)

    @commands.hybrid_command(name="wink", description="Wink at someone!")
    @commands.guild_only()
    async def wink(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "wink", target)

    @commands.hybrid_command(name="poke", description="Poke someone!")
    @commands.guild_only()
    async def poke(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "poke", target)

    @commands.hybrid_command(name="dance", description="Dance with someone!")
    @commands.guild_only()
    async def dance(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "dance", target)

    # --- prefix-only commands (everything else) ---

    @commands.command(name="laugh", description="Laugh at someone!")
    @commands.guild_only()
    async def laugh_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "laugh", target)

    @commands.command(name="boot", description="Boot someone (fun, not a mod kick)!")
    @commands.guild_only()
    async def boot_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "boot", target)

    @commands.command(name="yeet", description="Yeet someone!")
    @commands.guild_only()
    async def yeet_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yeet", target)

    @commands.command(name="dap", description="Dap someone up!")
    @commands.guild_only()
    async def dap_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "dap", target)

    @commands.command(name="cuddle", description="Cuddle someone!")
    @commands.guild_only()
    async def cuddle_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "cuddle", target)

    @commands.command(name="flirt", description="Flirt with someone!")
    @commands.guild_only()
    async def flirt_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "flirt", target)

    @commands.command(name="airkiss", description="Air kiss someone!")
    @commands.guild_only()
    async def airkiss_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "airkiss", target)

    @commands.command(name="angrystare", description="Angrily stare at someone!")
    @commands.guild_only()
    async def angrystare_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "angrystare", target)

    @commands.command(name="bite", description="Bite someone!")
    @commands.guild_only()
    async def bite_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "bite", target)

    @commands.command(name="bleh", description="Make a bleh face at someone!")
    @commands.guild_only()
    async def bleh_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "bleh", target)

    @commands.command(name="celebrate", description="Celebrate with someone!")
    @commands.guild_only()
    async def celebrate_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "celebrate", target)

    @commands.command(name="cheers", description="Cheers with someone!")
    @commands.guild_only()
    async def cheers_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "cheers", target)

    @commands.command(name="clap", description="Clap for someone!")
    @commands.guild_only()
    async def clap_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "clap", target)

    @commands.command(name="confused", description="Look confused at someone!")
    @commands.guild_only()
    async def confused_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "confused", target)

    @commands.command(name="cool", description="Look cool with someone!")
    @commands.guild_only()
    async def cool_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "cool", target)

    @commands.command(name="cry", description="Cry at someone!")
    @commands.guild_only()
    async def cry_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "cry", target)

    @commands.command(name="drool", description="Drool at someone!")
    @commands.guild_only()
    async def drool_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "drool", target)

    @commands.command(name="evillaugh", description="Evil laugh at someone!")
    @commands.guild_only()
    async def evillaugh_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "evillaugh", target)

    @commands.command(name="facepalm", description="Facepalm at someone!")
    @commands.guild_only()
    async def facepalm_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "facepalm", target)

    @commands.command(name="handhold", description="Hold hands with someone!")
    @commands.guild_only()
    async def handhold_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "handhold", target)

    @commands.command(name="headbang", description="Headbang with someone!")
    @commands.guild_only()
    async def headbang_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "headbang", target)

    @commands.command(name="lick", description="Lick someone!")
    @commands.guild_only()
    async def lick_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "lick", target)

    @commands.command(name="mad", description="Get mad at someone!")
    @commands.guild_only()
    async def mad_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "mad", target)

    @commands.command(name="nervous", description="Get nervous around someone!")
    @commands.guild_only()
    async def nervous_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "nervous", target)

    @commands.command(name="eat", description="Eat with someone!")
    @commands.guild_only()
    async def eat_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "eat", target)

    @commands.command(name="boop", description="Boop someone!")
    @commands.guild_only()
    async def boop_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "boop", target)

    @commands.command(name="nyah", description="Nyah at someone!")
    @commands.guild_only()
    async def nyah_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "nyah", target)

    @commands.command(name="peek", description="Peek at someone!")
    @commands.guild_only()
    async def peek_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "peek", target)

    @commands.command(name="pinch", description="Pinch someone!")
    @commands.guild_only()
    async def pinch_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "pinch", target)

    @commands.command(name="pout", description="Pout at someone!")
    @commands.guild_only()
    async def pout_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "pout", target)

    @commands.command(name="sad", description="Get sad at someone!")
    @commands.guild_only()
    async def sad_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sad", target)

    @commands.command(name="scared", description="Get scared at someone!")
    @commands.guild_only()
    async def scared_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "scared", target)

    @commands.command(name="shout", description="Shout at someone!")
    @commands.guild_only()
    async def shout_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "shout", target)

    @commands.command(name="shrug", description="Shrug at someone!")
    @commands.guild_only()
    async def shrug_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "shrug", target)

    @commands.command(name="shy", description="Get shy around someone!")
    @commands.guild_only()
    async def shy_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "shy", target)

    @commands.command(name="sigh", description="Sigh at someone!")
    @commands.guild_only()
    async def sigh_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sigh", target)

    @commands.command(name="sip", description="Sip with someone!")
    @commands.guild_only()
    async def sip_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sip", target)

    @commands.command(name="sleep", description="Sleep with someone!")
    @commands.guild_only()
    async def sleep_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sleep", target)

    @commands.command(name="slowclap", description="Slow clap for someone!")
    @commands.guild_only()
    async def slowclap_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "slowclap", target)

    @commands.command(name="smack", description="Smack someone!")
    @commands.guild_only()
    async def smack_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "smack", target)

    @commands.command(name="smile", description="Smile at someone!")
    @commands.guild_only()
    async def smile_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "smile", target)

    @commands.command(name="sneeze", description="Sneeze at someone!")
    @commands.guild_only()
    async def sneeze_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sneeze", target)

    @commands.command(name="sorry", description="Say sorry to someone!")
    @commands.guild_only()
    async def sorry_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sorry", target)

    @commands.command(name="stare", description="Stare at someone!")
    @commands.guild_only()
    async def stare_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "stare", target)

    @commands.command(name="surprised", description="Get surprised at someone!")
    @commands.guild_only()
    async def surprised_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "surprised", target)

    @commands.command(name="sweat", description="Sweat at someone!")
    @commands.guild_only()
    async def sweat_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "sweat", target)

    @commands.command(name="thumbsup", description="Give someone a thumbs up!")
    @commands.guild_only()
    async def thumbsup_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "thumbsup", target)

    @commands.command(name="tired", description="Get tired with someone!")
    @commands.guild_only()
    async def tired_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "tired", target)

    @commands.command(name="yawn", description="Yawn with someone!")
    @commands.guild_only()
    async def yawn_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yawn", target)

    @commands.command(name="yay", description="Yay with someone!")
    @commands.guild_only()
    async def yay_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yay", target)

    @commands.command(name="yes", description="Say yes to someone!")
    @commands.guild_only()
    async def yes_prefix(self, ctx: commands.Context, target: discord.Member | None = None) -> None:
        await self._do_action(ctx, "yes", target)

    # --- fun commands list with pagination ---

    FUN_COMMAND_LIST: list[tuple[str, str]] = [
        ("slap", "Slap someone!"),
        ("kiss", "Kiss someone!"),
        ("laugh", "Laugh at someone!"),
        ("boot", "Boot someone (fun, not a mod kick)!"),
        ("yeet", "Yeet someone!"),
        ("tickle", "Tickle someone!"),
        ("hug", "Hug someone!"),
        ("dap", "Dap someone up!"),
        ("bonk", "Bonk someone on the head!"),
        ("cuddle", "Cuddle someone!"),
        ("flirt", "Flirt with someone!"),
        ("poke", "Poke someone!"),
        ("airkiss", "Air kiss someone!"),
        ("angrystare", "Angrily stare at someone!"),
        ("bite", "Bite someone!"),
        ("bleh", "Make a bleh face at someone!"),
        ("celebrate", "Celebrate with someone!"),
        ("cheers", "Cheers with someone!"),
        ("clap", "Clap for someone!"),
        ("confused", "Look confused at someone!"),
        ("cool", "Look cool with someone!"),
        ("cry", "Cry at someone!"),
        ("dance", "Dance with someone!"),
        ("drool", "Drool at someone!"),
        ("evillaugh", "Evil laugh at someone!"),
        ("facepalm", "Facepalm at someone!"),
        ("handhold", "Hold hands with someone!"),
        ("headbang", "Headbang with someone!"),
        ("lick", "Lick someone!"),
        ("mad", "Get mad at someone!"),
        ("nervous", "Get nervous around someone!"),
        ("eat", "Eat with someone!"),
        ("boop", "Boop someone!"),
        ("nyah", "Nyah at someone!"),
        ("pat", "Pat someone!"),
        ("peek", "Peek at someone!"),
        ("pinch", "Pinch someone!"),
        ("pout", "Pout at someone!"),
        ("sad", "Get sad at someone!"),
        ("scared", "Get scared at someone!"),
        ("shout", "Shout at someone!"),
        ("shrug", "Shrug at someone!"),
        ("shy", "Get shy around someone!"),
        ("sigh", "Sigh at someone!"),
        ("sip", "Sip with someone!"),
        ("sleep", "Sleep with someone!"),
        ("slowclap", "Slow clap for someone!"),
        ("smack", "Smack someone!"),
        ("smile", "Smile at someone!"),
        ("sneeze", "Sneeze at someone!"),
        ("sorry", "Say sorry to someone!"),
        ("stare", "Stare at someone!"),
        ("surprised", "Get surprised at someone!"),
        ("sweat", "Sweat at someone!"),
        ("thumbsup", "Give someone a thumbs up!"),
        ("tired", "Get tired with someone!"),
        ("wave", "Wave at someone!"),
        ("wink", "Wink at someone!"),
        ("woah", "Say woah at someone!"),
        ("yawn", "Yawn with someone!"),
        ("yay", "Yay with someone!"),
        ("yes", "Say yes to someone!"),
    ]

    COMMANDS_PER_PAGE = 10

    class FunCommandsPagination(discord.ui.View):
        def __init__(self, command_list: list[tuple[str, str]], per_page: int = 10) -> None:
            super().__init__(timeout=180)
            self.command_list = command_list
            self.per_page = per_page
            self.total_pages = max(1, (len(command_list) + per_page - 1) // per_page)
            self.page = 0
            self._update_buttons()

        def _update_buttons(self) -> None:
            self.prev_button.disabled = self.page == 0
            self.next_button.disabled = self.page >= self.total_pages - 1
            self.page_button.label = f"Page {self.page + 1}/{self.total_pages}"

        def _build_embed(self) -> discord.Embed:
            start = self.page * self.per_page
            end = start + self.per_page
            page_items = self.command_list[start:end]

            lines = []
            for name, desc in page_items:
                gif_count = len(ACTION_GIFS.get(name, []))
                lines.append(f"• `.{name} @user` — {desc} ({gif_count} GIFs)")

            e = make_embed(
                "Fun Interaction Commands",
                "\n".join(lines),
                color=COLOR,
            )
            e.set_footer(
                text=f"Page {self.page + 1}/{self.total_pages} | Use .{page_items[0][0]} @user to try one!"
                if page_items else "No commands",
            )
            return e

        @discord.ui.button(label="<", style=discord.ButtonStyle.secondary)
        async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if self.page > 0:
                self.page -= 1
                self._update_buttons()
                await interaction.response.edit_message(embed=self._build_embed(), view=self)

        @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True)
        async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            pass

        @discord.ui.button(label=">", style=discord.ButtonStyle.secondary)
        async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if self.page < self.total_pages - 1:
                self.page += 1
                self._update_buttons()
                await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @commands.command(name="funcommands", description="List all fun interaction commands with pagination.")
    @commands.guild_only()
    async def funcommands(self, ctx: commands.Context) -> None:
        view = self.FunCommandsPagination(self.FUN_COMMAND_LIST, self.COMMANDS_PER_PAGE)
        await ctx.send(embed=view._build_embed(), view=view)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(FunCommands(bot))
