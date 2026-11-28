"""Admin permission panel for custom roles created with ``.role create``.

Shows a SINGLE global configuration panel (not a per-role list). Privileges are
stored per-guild and apply as the default for custom role owners. This does not
touch Discord server roles.

Usage: ``.permpanel``  (requires Manage Roles)
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed, NO_MENTIONS

if TYPE_CHECKING:
    from main import SocializeBot

log = logging.getLogger("socialize")

PAGE_SIZE = 16  # permission buttons per page (leaves room for nav buttons)


# ---------------------------------------------------------------------------
# Permission list (all Discord permission flags)
# ---------------------------------------------------------------------------

def _discord_permission_names() -> list[str]:
    base = discord.Permissions.none()
    names: list[str] = []
    for attr in sorted(dir(base)):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(base, attr)
        except AttributeError:
            continue
        if isinstance(value, bool):
            names.append(attr)
    return names


PERMISSION_NAMES = _discord_permission_names()


def perm_display(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split("_"))


def perm_button_style(enabled: bool) -> discord.ButtonStyle:
    return discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger


# ---------------------------------------------------------------------------
# Modal: set minimum level
# ---------------------------------------------------------------------------

class MinLevelModal(discord.ui.Modal, title="Set Minimum Level"):
    level = discord.ui.TextInput(
        label="Minimum level (0-1000)",
        placeholder="e.g. 5",
        min_length=1,
        max_length=4,
        required=True,
    )

    def __init__(self, cog: "PermPanel", current: int) -> None:
        super().__init__()
        self.cog = cog
        self.level.default = str(current)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.level.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Enter a whole number between 0 and 1000.", ephemeral=True)
            return
        level = int(raw)
        if level < 0 or level > 1000:
            await interaction.response.send_message("Level must be between 0 and 1000.", ephemeral=True)
            return
        assert interaction.guild
        await self.cog.db.set_custom_role_global_settings(interaction.guild.id, min_level=level)
        await interaction.response.send_message(
            embed=make_embed("Minimum level set", f"Global minimum level is now **{level}**.", color=SUCCESS),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# View: permission toggle list (paginated) for global config
# ---------------------------------------------------------------------------

class PermListView(discord.ui.View):
    """Toggle individual permissions on/off for the global config."""

    @classmethod
    async def create(
        cls,
        cog: "PermPanel",
        guild: discord.Guild,
        page: int = 0,
    ) -> "PermListView":
        enabled = set(await cog.db.get_custom_role_global_permissions(guild.id))
        return cls(cog, guild, enabled, page)

    def __init__(
        self,
        cog: "PermPanel",
        guild: discord.Guild,
        enabled: set[str],
        page: int = 0,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.enabled = enabled

        total_pages = max(1, math.ceil(len(PERMISSION_NAMES) / PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        self.page = page
        self.total_pages = total_pages

        start = page * PAGE_SIZE
        for index, name in enumerate(PERMISSION_NAMES[start:start + PAGE_SIZE]):
            button = discord.ui.Button(
                label=perm_display(name)[:80],
                style=perm_button_style(name in enabled),
                custom_id=f"gperm:{name}",
                row=index // 4,
            )
            button.callback = self._make_perm_callback(name)
            self.add_item(button)

        nav_row = 4
        prev_btn = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="gperm:prev", row=nav_row)
        prev_btn.callback = self._on_prev
        self.add_item(prev_btn)

        page_btn = discord.ui.Button(label=f"Page {page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, custom_id="gperm:page", row=nav_row, disabled=True)
        self.add_item(page_btn)

        next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="gperm:next", row=nav_row)
        next_btn.callback = self._on_next
        self.add_item(next_btn)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, custom_id="gperm:back", row=nav_row)
        back_btn.callback = self._on_back
        self.add_item(back_btn)

    def _make_perm_callback(self, name: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.guild is None:
                await interaction.response.send_message("Server only.", ephemeral=True)
                return
            currently = await self.cog.db.has_custom_role_global_permission(self.guild.id, name)
            await self.cog.db.set_custom_role_global_permission(self.guild.id, name, not currently)
            new_view = await PermListView.create(self.cog, self.guild, page=self.page)
            await interaction.response.edit_message(view=new_view)
        return callback

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, page=self.page - 1)
        await interaction.response.edit_message(view=new_view)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, page=self.page + 1)
        await interaction.response.edit_message(view=new_view)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)


# ---------------------------------------------------------------------------
# View: the single global config form
# ---------------------------------------------------------------------------

class PermFormView(discord.ui.View):
    """Single global config form: feature toggle, min level, permissions."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.embed: discord.Embed | None = None

    async def refresh(self, interaction: discord.Interaction) -> None:
        row = await self.cog.db.get_custom_role_global_settings(self.guild.id)
        enabled = int(row["enabled"]) if row else 1
        min_level = int(row["min_level"]) if row else 0
        perms = await self.cog.db.get_custom_role_global_permissions(self.guild.id)

        status = "On" if enabled else "Off"
        status_emoji = "🟢" if enabled else "🔴"
        perm_list = ", ".join(perm_display(p) for p in perms) if perms else "None"
        if len(perm_list) > 900:
            perm_list = perm_list[:900] + " …"

        self.embed = make_embed(
            "Custom Role Permission Panel (Global)",
            (
                f"Feature: {status_emoji} **{status}**\n"
                f"Minimum level: **{min_level}** (0-1000)\n"
                f"Enabled permissions ({len(perms)}): {perm_list}"
            ),
            color=SUCCESS if enabled else DANGER,
        )
        self.embed.set_footer(text="Global default config for custom role owners. Does not touch server roles.")

        self.clear_items()
        toggle_label = f"Feature: {'Off' if enabled else 'On'}"
        toggle_btn = discord.ui.Button(label=toggle_label, style=perm_button_style(enabled), custom_id="form:toggle")
        toggle_btn.callback = self._on_toggle
        self.add_item(toggle_btn)

        level_btn = discord.ui.Button(label=f"Min Level: {min_level}", style=discord.ButtonStyle.secondary, custom_id="form:level")
        level_btn.callback = self._on_level
        self.add_item(level_btn)

        perms_btn = discord.ui.Button(label="Manage Permissions", style=discord.ButtonStyle.primary, custom_id="form:perms")
        perms_btn.callback = self._on_perms
        self.add_item(perms_btn)

        await interaction.response.edit_message(embed=self.embed, view=self)

    async def _on_toggle(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        row = await self.cog.db.get_custom_role_global_settings(interaction.guild.id)
        current = int(row["enabled"]) if row else 1
        await self.cog.db.set_custom_role_global_settings(interaction.guild.id, enabled=0 if current else 1)
        await self.refresh(interaction)

    async def _on_level(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        row = await self.cog.db.get_custom_role_global_settings(interaction.guild.id)
        current = int(row["min_level"]) if row else 0
        await interaction.response.send_modal(MinLevelModal(self.cog, current))

    async def _on_perms(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        view = await PermListView.create(self.cog, self.guild, page=0)
        await interaction.response.edit_message(
            embed=make_embed(
                "Custom Role Permission Panel (Global)",
                "Click a permission to toggle it (green = on, red = off) for the global config.",
                color=COLOR,
            ),
            view=view,
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class PermPanel(commands.Cog):
    """Admin panel for custom role owner privileges (single global config)."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_group(name="permpanel", description="Manage custom role owner privileges (admin panel).", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def permpanel(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Custom Role Permission Panel",
                "Use `.permpanel custom role` to open the global config form.",
                color=COLOR,
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @permpanel.group(name="custom", description="Manage custom role permissions.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def permpanel_custom(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Custom Role Permissions",
                "Use `.permpanel custom role` to open the global config form.",
                color=COLOR,
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @permpanel_custom.command(name="role", description="Open the custom role permission panel (global config).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def permpanel_custom_role(self, ctx: commands.Context) -> None:
        assert ctx.guild
        row = await self.db.get_custom_role_global_settings(ctx.guild.id)
        enabled = int(row["enabled"]) if row else 1
        min_level = int(row["min_level"]) if row else 0
        perms = await self.db.get_custom_role_global_permissions(ctx.guild.id)

        status = "On" if enabled else "Off"
        status_emoji = "🟢" if enabled else "🔴"
        perm_list = ", ".join(perm_display(p) for p in perms) if perms else "None"
        if len(perm_list) > 900:
            perm_list = perm_list[:900] + " …"

        embed = make_embed(
            "Custom Role Permission Panel",
            (
                "Select a custom role to manage its owner privileges.\n"
                f"Showing 1 config (global).\n"
                "Privileges apply to the role owner only — not to members the role was shared with."
            ),
            color=COLOR,
        )
        embed.set_footer(text="Global config applies to all user-created custom roles. Does not touch server roles.")

        open_btn = discord.ui.Button(label="Open Global Config", style=discord.ButtonStyle.primary, custom_id="panel:open")
        async def open_callback(interaction: discord.Interaction) -> None:
            view = PermFormView(self, interaction.guild)
            await view.refresh(interaction)
        open_btn.callback = open_callback
        view = discord.ui.View(timeout=180)
        view.add_item(open_btn)

        await ctx.send(embed=embed, ephemeral=True, allowed_mentions=NO_MENTIONS, view=view)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(PermPanel(bot))
