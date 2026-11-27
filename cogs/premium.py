"""Owner premium commands and the global command gate."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from premium import (
    CREDIT,
    PremiumRequired,
    command_is_exempt,
    format_renewal,
    guild_access,
    owner_ids_from_env,
    premium_needed_message,
    status_label,
)
from cogs.v2 import build_game_layout

if TYPE_CHECKING:
    from main import SocializeBot


def _owner_ids(bot: commands.Bot) -> set[int]:
    ids = set(getattr(bot, "app_owner_ids", None) or set())
    ids |= owner_ids_from_env()
    if bot.owner_ids:
        ids |= set(bot.owner_ids)
    if bot.owner_id:
        ids.add(int(bot.owner_id))
    return ids


def is_app_owner():
    async def pred(ctx: commands.Context) -> bool:
        if ctx.author.id in _owner_ids(ctx.bot):
            return True
        try:
            if await ctx.bot.is_owner(ctx.author):
                return True
        except Exception:
            pass
        raise commands.CheckFailure("Only the bot owner can do that.")

    return commands.check(pred)


class Premium(commands.Cog):
    """Manual grants and the per-server Premium gate."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_check(self.premium_command_check)
        self.bot.tree.interaction_check = self.premium_interaction_check  # type: ignore[method-assign]
        self.bot.tree.on_error = self.on_app_command_error  # type: ignore[method-assign]

    async def cog_unload(self) -> None:
        self.bot.remove_check(self.premium_command_check)

    async def premium_command_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return True
        name = ctx.command.qualified_name if ctx.command else None
        if command_is_exempt(name):
            return True
        if ctx.author.id in _owner_ids(self.bot):
            return True
        access = await guild_access(
            self.bot.db,
            ctx.guild.id,
            guild_owner_id=ctx.guild.owner_id,
            owner_ids=_owner_ids(self.bot),
        )
        if access.allowed:
            return True
        raise PremiumRequired(premium_needed_message())

    async def premium_interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return True
        name = None
        if interaction.command is not None:
            name = interaction.command.qualified_name
        if command_is_exempt(name):
            return True
        user = interaction.user
        if user and user.id in _owner_ids(self.bot):
            return True
        access = await guild_access(
            self.bot.db,
            interaction.guild.id,
            guild_owner_id=interaction.guild.owner_id,
            owner_ids=_owner_ids(self.bot),
        )
        if access.allowed:
            return True
        raise PremiumRequired(premium_needed_message())

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        err = getattr(error, "original", error)
        if isinstance(err, PremiumRequired) or isinstance(error, PremiumRequired):
            msg = str(err) or premium_needed_message()
            layout = build_game_layout("Premium required", msg)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(view=layout, ephemeral=True)
                else:
                    await interaction.response.send_message(view=layout, ephemeral=True)
            except discord.HTTPException:
                pass
            return
        # Fall through is silent for unknown errors here; command error handler covers prefix.

    @commands.hybrid_group(name="premium", description="Fun bot Premium status and owner grants.", invoke_without_command=True)
    async def premium(self, ctx: commands.Context) -> None:
        await self.status(ctx)

    @premium.command(name="status", description="Show this server's Fun bot Premium status.")
    async def status(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(view=build_game_layout("Server only", "Check premium status in a server.", phase="lose"), ephemeral=True)
            return
        access = await guild_access(
            self.bot.db,
            ctx.guild.id,
            guild_owner_id=ctx.guild.owner_id,
            owner_ids=_owner_ids(self.bot),
        )
        lines = [
            f"**Status:** {status_label(access)}",
            f"**Renewal:** {format_renewal(access.renewal)}",
        ]
        if access.detail:
            lines.append(f"**Note:** {access.detail}")
        if not access.allowed:
            lines.append(f"\nSubscribe at {premium_needed_message().rsplit(' at ', 1)[-1]}")
        await ctx.send(view=build_game_layout("Fun bot Premium", "\n".join(lines), phase="win" if access.allowed else "hint"), ephemeral=True)

    @premium.command(name="grant", description="(Owner) Grant Premium to a server.")
    @is_app_owner()
    async def grant(self, ctx: commands.Context, guild_id: int, days: int | None = None, *, note: str | None = None) -> None:
        expires = None
        if days is not None:
            if days <= 0:
                await ctx.send(view=build_game_layout("Invalid duration", "Days must be a positive number, or omit it for lifetime."), ephemeral=True)
                return
            expires = time.time() + days * 86400
        grant_id = await self.bot.db.add_premium_grant(
            grant_type="guild",
            guild_id=guild_id,
            expires_at=expires,
            note=note,
            granted_by=ctx.author.id,
        )
        until = format_renewal(expires)
        await ctx.send(
            view=build_game_layout(
                "Premium granted",
                f"Grant **#{grant_id}** on server `{guild_id}` until **{until}**.",
            ),
            ephemeral=True,
        )

    @premium.command(name="revoke", description="(Owner) Revoke manual Premium grants for a server.")
    @is_app_owner()
    async def revoke(self, ctx: commands.Context, guild_id: int) -> None:
        n = await self.bot.db.revoke_guild_grants(guild_id)
        if n:
            await ctx.send(view=build_game_layout("Premium revoked", f"Revoked **{n}** manual grant(s) for `{guild_id}`."), ephemeral=True)
        else:
            await ctx.send(view=build_game_layout("Nothing to revoke", f"No active manual grants for `{guild_id}`."), ephemeral=True)

    @premium.command(name="list", description="(Owner) List active subscriptions and manual grants.")
    @is_app_owner()
    async def list_cmd(self, ctx: commands.Context) -> None:
        subs = await self.bot.db.list_subscriptions()
        grants = await self.bot.db.list_premium_grants(active_only=True)
        lines: list[str] = []
        active_subs = [s for s in subs if s["status"] in {"active", "trialing", "past_due"}]
        if active_subs:
            lines.append("**Stripe**")
            for s in active_subs[:20]:
                end = format_renewal(s["current_period_end"])
                lines.append(f"• `{s['guild_id']}` — {s['plan'] or '—'} · {s['status']} · {end}")
        if grants:
            lines.append("**Manual grants**")
            for g in grants[:20]:
                target = f"guild `{g['guild_id']}`" if g["grant_type"] == "guild" else f"user `{g['user_id']}`"
                end = format_renewal(g["expires_at"])
                note = f" — {g['note']}" if g["note"] else ""
                lines.append(f"• #{g['id']} {target} until {end}{note}")
        if not lines:
            lines.append("No active subscriptions or grants.")
        lines.append(CREDIT)
        await ctx.send(view=build_game_layout("Premium list", "\n".join(lines)), ephemeral=True)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Premium(bot))


