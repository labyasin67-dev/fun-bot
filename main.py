"""Socialize-style Discord bot: games, roles, levels, welcome, and voice."""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.sessions import GameManager
from dashboard.web import start_dashboard, stop_dashboard
from database import Database
from premium import PremiumRequired
from utils import embed as make_embed, DANGER, WARNING

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("socialize")


def ensure_data_dir() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "bot.db"
    seed = ROOT / "seed" / "bot.db"
    if not db_path.exists() and seed.is_file():
        import shutil
        shutil.copy2(seed, db_path)
        log.info("Initialized the database from the bundled seed")
    return data_dir


EXTENSIONS = (
    "cogs.games",
    "cogs.arcade",
    "cogs.uno",
    "cogs.moderation",
    "cogs.altdetect",
    "cogs.channels",
    "cogs.roles",
    "cogs.customroles",
    "cogs.reports",
    "cogs.leveling",
    "cogs.welcome",
    "cogs.voice",
    "cogs.help_cog",
    "cogs.premium",
    "cogs.youtube",
    "cogs.fun_commands",
    "cogs.creator_alerts",
    "cogs.levels_switch",
    "cogs.audit_logs",
    "cogs.afk",
)


class SocializeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        data_dir = ensure_data_dir()
        self.db = Database(str(data_dir / "bot.db"))
        self.game_sessions = GameManager()

    async def setup_hook(self) -> None:
        ensure_data_dir()
        await self.db.setup()
        await self._load_owner_ids()
        await self._bootstrap_stripe()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("Loaded %s", ext)
        # Persistent views are registered by the cogs that own them.
        await start_dashboard(self)

    async def _load_owner_ids(self) -> None:
        from premium import owner_ids_from_env

        ids = owner_ids_from_env()
        try:
            info = await self.application_info()
            if info.owner is not None:
                ids.add(info.owner.id)
            if info.team is not None and info.team.owner_id:
                ids.add(int(info.team.owner_id))
        except Exception:
            log.exception("Could not fetch the application owner id")
        self.app_owner_ids = ids
        self.owner_ids = set(ids)
        log.info("Premium admin owners loaded: %s id(s)", len(ids))

    async def _bootstrap_stripe(self) -> None:
        from stripe_billing import ensure_stripe_prices, stripe_configured

        self.stripe_prices = {}
        if not stripe_configured():
            log.info("Stripe is not configured; /pricing will show payments coming soon")
            return
        try:
            self.stripe_prices = await asyncio.to_thread(ensure_stripe_prices)
            log.info("Stripe prices are ready")
        except Exception:
            log.exception("Could not ensure Stripe prices; checkout will stay unavailable")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        if not getattr(self, "_initial_premium_granted", False):
            granted = 0
            for guild in self.guilds:
                if await self.db.has_initial_guild_grant(guild.id):
                    continue
                await self.db.add_premium_grant(
                    grant_type="guild",
                    guild_id=guild.id,
                    expires_at=None,
                    note="initial",
                    granted_by=None,
                )
                granted += 1
            self._initial_premium_granted = True
            log.info("Granted initial lifetime premium to %s server(s)", granted)
        try:
            synced = await self.tree.sync()
            log.info("Synced %s app commands", len(synced))
        except Exception:
            log.exception("Failed to sync application commands")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=".games | /help",
            )
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        error = getattr(error, "original", error)
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.HybridCommandError):
            error = getattr(error, "original", error)
            error = getattr(error, "original", error)

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(permission.replace("_", " ") for permission in error.missing_permissions)
            await ctx.send(embed=make_embed("Missing permissions", f"You need: **{perms}**.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(permission.replace("_", " ") for permission in error.missing_permissions)
            await ctx.send(embed=make_embed("I am missing permissions", f"I need: **{perms}**.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=make_embed("Missing argument", f"Missing `{error.param.name}`. Try `.help {ctx.command.qualified_name}`." if ctx.command else "Missing an argument.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=make_embed("Invalid argument", str(error), color=DANGER), ephemeral=True)
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=make_embed("Slow down", f"Try again in **{error.retry_after:.1f}s**.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=make_embed("Server only", "This command can only be used in a server.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, PremiumRequired):
            await ctx.send(embed=make_embed("Premium required", str(error), color=WARNING), ephemeral=True)
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=make_embed("You can't do that", str(error) or "You don't have permission to use this command.", color=DANGER), ephemeral=True)
            return
        if isinstance(error, discord.NotFound):
            # Interaction already acknowledged or expired — nothing useful to send.
            log.warning("NotFound during command %s: %s", ctx.command, error)
            return

        log.error("Command error in %s:\n%s", ctx.command, "".join(traceback.format_exception(type(error), error, error.__traceback__)))
        try:
            await ctx.send(embed=make_embed("Something went wrong", "I hit an unexpected error running that command.", color=DANGER), ephemeral=True)
        except Exception:
            pass

    async def close(self) -> None:
        await stop_dashboard(self)
        await self.db.close()
        await super().close()


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and paste the bot token."
        )
    bot = SocializeBot()
    bot.run(token)


if __name__ == "__main__":
    main()
