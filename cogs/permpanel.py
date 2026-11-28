"""Admin permission panel for custom roles created with ``.role create``.

This cog lets staff manage per-owner privileges for custom roles. It does not
touch Discord server roles; privileges are stored in the database and apply
strictly to the custom role *owner*, never to members the role was shared with
(unless they are also the owner).

Usage: ``.permpanel``  (requires Manage Roles)
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils import COLOR, DANGER, SUCCESS, embed as make_embed, NO_MENTIONS

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
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        await self.cog.db.set_custom_role_perms(interaction.guild.id, interaction.user.id, min_level=level)
        await interaction.response.send_message(
            embed=make_embed("Minimum level set", f"Minimum level is now **{level}**.", color=SUCCESS),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# View: permission toggle list (paginated)
# ---------------------------------------------------------------------------

class PermListView(discord.ui.View):
    """Toggle individual permissions on/off for the current custom-role owner."""

    @classmethod
    async def create(
        cls,
        cog: "PermPanel",
        guild: discord.Guild,
        owner_id: int,
        role: discord.Role | None,
        page: int = 0,
        back_view: discord.ui.View | None = None,
    ) -> "PermListView":
        enabled = set(await cog.db.get_custom_role_permissions(guild.id, owner_id))
        return cls(cog, guild, owner_id, role, enabled, page, back_view)

    def __init__(
        self,
        cog: "PermPanel",
        guild: discord.Guild,
        owner_id: int,
        role: discord.Role | None,
        enabled: set[str],
        page: int = 0,
        back_view: discord.ui.View | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.owner_id = owner_id
        self.role = role
        self.enabled = enabled
        self.page = page
        self.back_view = back_view

        total_pages = max(1, math.ceil(len(PERMISSION_NAMES) / PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        self.page = page

        start = page * PAGE_SIZE
        for index, name in enumerate(PERMISSION_NAMES[start:start + PAGE_SIZE]):
            button = discord.ui.Button(
                label=perm_display(name)[:80],
                style=perm_button_style(name in enabled),
                custom_id=f"perm:{name}",
                row=index // 4,
            )
            button.callback = self._make_perm_callback(name)
            self.add_item(button)

        nav_row = 4
        prev_btn = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="perm:prev", row=nav_row)
        prev_btn.callback = self._on_prev
        self.add_item(prev_btn)

        page_btn = discord.ui.Button(label=f"Page {page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, custom_id="perm:page", row=nav_row, disabled=True)
        self.add_item(page_btn)

        next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="perm:next", row=nav_row)
        next_btn.callback = self._on_next
        self.add_item(next_btn)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, custom_id="perm:back", row=nav_row)
        back_btn.callback = self._on_back
        self.add_item(back_btn)

    def _make_perm_callback(self, name: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("Server only.", ephemeral=True)
                return
            currently = await self.cog.db.has_custom_role_permission(self.guild.id, self.owner_id, name)
            await self.cog.db.set_custom_role_permission(self.guild.id, self.owner_id, name, not currently)
            new_view = await PermListView.create(self.cog, self.guild, self.owner_id, self.role, page=self.page, back_view=self.back_view)
            await interaction.response.edit_message(view=new_view)
        return callback

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, self.owner_id, self.role, page=self.page - 1, back_view=self.back_view)
        await interaction.response.edit_message(view=new_view)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, self.owner_id, self.role, page=self.page + 1, back_view=self.back_view)
        await interaction.response.edit_message(view=new_view)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        if self.back_view is not None and hasattr(self.back_view, "refresh"):
            await self.back_view.refresh(interaction)
        else:
            await interaction.response.edit_message(view=None)


# ---------------------------------------------------------------------------
# View: the permission form for one custom role
# ---------------------------------------------------------------------------

class PermFormView(discord.ui.View):
    """Form to adjust a custom role owner's feature toggle, min level, and permissions."""

    def __init__(
        self,
        cog: "PermPanel",
        guild: discord.Guild,
        owner: discord.Member,
        role: discord.Role | None,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.owner = owner
        self.role = role
        self.embed: discord.Embed | None = None

    async def refresh(self, interaction: discord.Interaction) -> None:
        row = await self.cog.db.get_custom_role_perms(self.guild.id, self.owner.id)
        enabled = int(row["enabled"]) if row else 1
        min_level = int(row["min_level"]) if row else 0
        perms = await self.cog.db.get_custom_role_permissions(self.guild.id, self.owner.id)

        status = "On" if enabled else "Off"
        status_emoji = "🟢" if enabled else "🔴"
        perm_list = ", ".join(perm_display(p) for p in perms) if perms else "None"
        if len(perm_list) > 900:
            perm_list = perm_list[:900] + " …"

        self.embed = make_embed(
            f"Permissions — {self.role.name if self.role else 'deleted role'}",
            (
                f"Owner: {self.owner.mention}\n"
                f"Role: {self.role.mention if self.role else 'deleted'}\n"
                f"Feature: {status_emoji} **{status}**\n"
                f"Minimum level: **{min_level}** (0-1000)\n"
                f"Enabled permissions ({len(perms)}): {perm_list}"
            ),
            color=SUCCESS if enabled else DANGER,
        )
        self.embed.set_footer(text="Changes apply to the role owner only, not shared holders.")

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

        back_btn = discord.ui.Button(label="Back to Role List", style=discord.ButtonStyle.secondary, custom_id="form:back")
        back_btn.callback = self._on_back
        self.add_item(back_btn)

        await interaction.response.edit_message(embed=self.embed, view=self)

    async def _on_toggle(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        row = await self.cog.db.get_custom_role_perms(interaction.guild.id, self.owner.id)
        current = int(row["enabled"]) if row else 1
        await self.cog.db.set_custom_role_perms(interaction.guild.id, self.owner.id, enabled=0 if current else 1)
        await self.refresh(interaction)

    async def _on_level(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        row = await self.cog.db.get_custom_role_perms(interaction.guild.id, self.owner.id)
        current = int(row["min_level"]) if row else 0
        await interaction.response.send_modal(MinLevelModal(self.cog, current))

    async def _on_perms(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        view = await PermListView.create(self.cog, self.guild, self.owner.id, self.role, page=0, back_view=self)
        await interaction.response.edit_message(
            embed=make_embed(
                f"Permissions — {self.role.name if self.role else 'deleted role'}",
                "Click a permission to toggle it (green = on, red = off) for this role owner.",
                color=COLOR,
            ),
            view=view,
        )

    async def _on_back(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)


# ---------------------------------------------------------------------------
# View: role list (the panel)
# ---------------------------------------------------------------------------

class PermPanelView(discord.ui.View):
    """Panel listing every custom role in the server, each with a manage button."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild, roles: list[discord.Role], page: int = 0) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.roles = roles
        self.page = page
        self.embed: discord.Embed | None = None
        self._build()

    def _build(self) -> None:
        total_pages = max(1, math.ceil(len(self.roles) / PAGE_SIZE))
        page = max(0, min(self.page, total_pages - 1))
        self.page = page
        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        page_roles = self.roles[start:end]

        self.clear_items()
        for index, role in enumerate(page_roles):
            button = discord.ui.Button(label=role.name[:80], style=discord.ButtonStyle.secondary, custom_id=f"panel:role:{role.id}", row=index // 5)
            button.callback = self._make_role_callback(role.id)
            self.add_item(button)

        nav_row = 5
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="panel:prev", row=nav_row)
            prev_btn.callback = self._on_prev
            self.add_item(prev_btn)

            page_btn = discord.ui.Button(label=f"Page {page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, custom_id="panel:page", row=nav_row, disabled=True)
            self.add_item(page_btn)

            next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="panel:next", row=nav_row)
            next_btn.callback = self._on_next
            self.add_item(next_btn)

        self.embed = make_embed(
            "Custom Role Permission Panel",
            (
                f"Select a custom role to manage its owner privileges.\n"
                f"Showing {len(page_roles)} role(s) (page {page + 1}/{total_pages}).\n"
                "Privileges apply to the role owner only — not to members the role was shared with."
            ),
            color=COLOR,
        )

    def _make_role_callback(self, role_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("Server only.", ephemeral=True)
                return
            row = await self.cog.db.get_custom_role_by_role_id(interaction.guild.id, role_id)
            if row is None:
                await interaction.response.send_message("That custom role is no longer tracked.", ephemeral=True)
                return
            owner_id = int(row["user_id"])
            owner = interaction.guild.get_member(owner_id) or interaction.user
            role = interaction.guild.get_role(role_id)
            form = PermFormView(self.cog, interaction.guild, owner, role)
            await form.refresh(interaction)
        return callback

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        new_view = PermPanelView(self.cog, self.guild, self.roles, page=self.page - 1)
        await interaction.response.edit_message(embed=new_view.embed, view=new_view)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        new_view = PermPanelView(self.cog, self.guild, self.roles, page=self.page + 1)
        await interaction.response.edit_message(embed=new_view.embed, view=new_view)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class PermPanel(commands.Cog):
    """Admin panel for managing custom role owner privileges."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(name="permpanel", description="Manage custom role owner privileges (admin panel).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def permpanel(self, ctx: commands.Context) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        rows = await self.db.list_custom_roles(ctx.guild.id)
        if not rows:
            await ctx.send(
                embed=make_embed("No custom roles", "There are no custom roles created with ``.role create`` in this server yet.", color=DANGER),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        roles: list[discord.Role] = []
        for row in rows:
            role = ctx.guild.get_role(int(row["role_id"]))
            if role is not None:
                roles.append(role)
        roles.sort(key=lambda r: r.name.lower())

        view = PermPanelView(self, ctx.guild, roles, page=0)
        await ctx.send(embed=view.embed, ephemeral=True, allowed_mentions=NO_MENTIONS, view=view)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(PermPanel(bot))
