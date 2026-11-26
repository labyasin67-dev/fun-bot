"""Per-server master On/Off switch for levelling (default ON).

Stored in its own small table so the developer's leveling cog and database.py
stay as they were. When a server turns levelling off, the leveling cog's
early-return guards stop XP gain, level-up messages and level roles, and its
rank/leaderboard commands reply that levelling is off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils import SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

SCHEMA = """
CREATE TABLE IF NOT EXISTS levels_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1
);
"""

OFF_TITLE = "Levelling is off"
OFF_TEXT = "Levelling is turned off in this server, so there are no levels, ranks or leaderboards right now."


class LevelsSwitch(commands.Cog):
    """Master switch for the Levels feature."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.db.executescript(SCHEMA)
        cur = await self.bot.db.db.execute("SELECT guild_id FROM levels_settings WHERE enabled = 0")
        # The leveling cog reads this set directly (it is a plain in-memory lookup).
        self.bot.levels_off_guilds = {int(r[0]) for r in await cur.fetchall()}

    async def cog_unload(self) -> None:
        self.bot.levels_off_guilds = set()

    def is_enabled(self, guild_id: int) -> bool:
        return int(guild_id) not in getattr(self.bot, "levels_off_guilds", set())

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.bot.db.db.execute(
            """INSERT INTO levels_settings (guild_id, enabled) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET enabled = excluded.enabled""",
            (int(guild_id), 1 if enabled else 0),
        )
        await self.bot.db.db.commit()
        off = getattr(self.bot, "levels_off_guilds", None)
        if off is None:
            off = self.bot.levels_off_guilds = set()
        if enabled:
            off.discard(int(guild_id))
        else:
            off.add(int(guild_id))

    @commands.hybrid_command(
        name="levelsystem",
        aliases=["levelling", "leveling"],
        description="Turn levelling on or off for this server (or check its status).",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(state="on, off, or status")
    @app_commands.choices(state=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
        app_commands.Choice(name="status", value="status"),
    ])
    async def levelsystem(self, ctx: commands.Context, state: str = "status") -> None:
        assert ctx.guild
        state = (state or "status").strip().lower()
        if state in ("on", "enable", "enabled", "true"):
            await self.set_enabled(ctx.guild.id, True)
            await ctx.send(embed=make_embed("Levelling is on", "XP, level-ups, ranks and leaderboards are active in this server.", color=SUCCESS))
        elif state in ("off", "disable", "disabled", "false"):
            await self.set_enabled(ctx.guild.id, False)
            await ctx.send(embed=make_embed(
                OFF_TITLE,
                "No XP will be earned and no level-up messages will be sent. Existing XP is kept and returns if you turn it back on.",
                color=WARNING,
            ))
        elif state == "status":
            on = self.is_enabled(ctx.guild.id)
            await ctx.send(embed=make_embed(
                "Levelling is on" if on else OFF_TITLE,
                "Use `levelsystem off` to turn it off." if on else "Use `levelsystem on` to turn it back on.",
                color=SUCCESS if on else WARNING,
            ))
        else:
            await ctx.send(embed=make_embed("Levelling", "Use `on`, `off` or `status`.", color=WARNING))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(LevelsSwitch(bot))
