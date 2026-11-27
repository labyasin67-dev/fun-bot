"""Set an AFK status and announce it when the member is mentioned."""

from __future__ import annotations

import time

import discord
from discord.ext import commands

from utils import COLOR, embed as make_embed


class AFK(commands.Cog):
    """In-memory AFK notes, per guild and member."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # (guild_id, user_id) -> (reason, started_unix)
        self._afk: dict[tuple[int, int], tuple[str, float]] = {}

    @commands.hybrid_command(name="afk", description="Mark yourself AFK, with an optional reason.")
    @commands.guild_only()
    async def afk(self, ctx: commands.Context, *, reason: str | None = None) -> None:
        assert ctx.guild
        text = (reason or "AFK").strip() or "AFK"
        text = text[:200]
        self._afk[(ctx.guild.id, ctx.author.id)] = (text, time.time())
        await ctx.send(embed=make_embed("AFK", f"You're now AFK: {text}", color=COLOR))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        content = message.content or ""
        lowered = content.lower()
        if lowered == ".afk" or lowered.startswith(".afk "):
            return

        key = (message.guild.id, message.author.id)
        if key in self._afk:
            del self._afk[key]
            try:
                await message.channel.send(f"Welcome back, {message.author.display_name}.")
            except discord.HTTPException:
                pass

        lines: list[str] = []
        seen: set[int] = set()
        for user in message.mentions:
            if user.bot or user.id == message.author.id or user.id in seen:
                continue
            entry = self._afk.get((message.guild.id, user.id))
            if entry is None:
                continue
            seen.add(user.id)
            reason, started = entry
            lines.append(f"{user.display_name} is AFK: {reason} (since <t:{int(started)}:R>)")
        if not lines:
            return
        try:
            await message.channel.send(chr(10).join(lines))
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AFK(bot))
