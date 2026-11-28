"""Admin permission panel for custom roles created with ``.role create``.

Shows every custom role as a button so staff can manage that role's owner
privileges, plus a ``Global Config`` button for the per-guild default config.
Privileges apply strictly to the custom role *owner*, never to members the role
was shared with (unless they are also the owner). Does not touch server roles.

Usage: ``.permpanel custom role``  (requires Manage Roles)
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

ROLE_PAGE_SIZE = 10  # role buttons per page
PERM_PAGE_SIZE = 16  # permission buttons per page


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

    def __init__(self, cog: "PermPanel", current: int, is_global: bool, owner_id: int | None) -> None:
        super().__init__()
        self.cog = cog
        self.is_global = is_global
        self.owner_id = owner_id
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
        if self.is_global:
            await self.cog.db.set_custom_role_global_settings(interaction.guild.id, min_level=level)
        else:
            await self.cog.db.set_custom_role_perms(interaction.guild.id, self.owner_id, min_level=level)
        await interaction.response.send_message(
            embed=make_embed("Minimum level set", f"Minimum level is now **{level}**.", color=SUCCESS),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# View: permission toggle list (paginated)
# ---------------------------------------------------------------------------

class PermListView(discord.ui.View):
    """Toggle individual permissions on/off for either global or per-role config."""

    @classmethod
    async def create(
        cls,
        cog: "PermPanel",
        guild: discord.Guild,
        *,
        owner_id: int | None = None,
        page: int = 0,
        back_view: discord.ui.View | None = None,
    ) -> "PermListView":
        if owner_id is None:
            enabled = set(await cog.db.get_custom_role_global_permissions(guild.id))
        else:
            enabled = set(await cog.db.get_custom_role_permissions(guild.id, owner_id))
        return cls(cog, guild, owner_id, enabled, page, back_view)

    def __init__(
        self,
        cog: "PermPanel",
        guild: discord.Guild,
        owner_id: int | None,
        enabled: set[str],
        page: int = 0,
        back_view: discord.ui.View | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.owner_id = owner_id
        self.enabled = enabled
        self.page = page
        self.back_view = back_view

        total_pages = max(1, math.ceil(len(PERMISSION_NAMES) / PERM_PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        self.page = page
        self.total_pages = total_pages

        start = page * PERM_PAGE_SIZE
        for index, name in enumerate(PERMISSION_NAMES[start:start + PERM_PAGE_SIZE]):
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
            if interaction.guild is None:
                await interaction.response.send_message("Server only.", ephemeral=True)
                return
            if self.owner_id is None:
                currently = await self.cog.db.has_custom_role_global_permission(self.guild.id, name)
                await self.cog.db.set_custom_role_global_permission(self.guild.id, name, not currently)
            else:
                currently = await self.cog.db.has_custom_role_permission(self.guild.id, self.owner_id, name)
                await self.cog.db.set_custom_role_permission(self.guild.id, self.owner_id, name, not currently)
            new_view = await PermListView.create(self.cog, self.guild, owner_id=self.owner_id, page=self.page, back_view=self.back_view)
            await interaction.response.edit_message(view=new_view)
        return callback

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, owner_id=self.owner_id, page=self.page - 1, back_view=self.back_view)
        await interaction.response.edit_message(view=new_view)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        new_view = await PermListView.create(self.cog, self.guild, owner_id=self.owner_id, page=self.page + 1, back_view=self.back_view)
        await interaction.response.edit_message(view=new_view)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        if self.back_view is not None and hasattr(self.back_view, "refresh"):
            await self.back_view.refresh(interaction)
        else:
            await interaction.response.edit_message(view=None)


# ---------------------------------------------------------------------------
# Base form view shared by per-role and global config
# ---------------------------------------------------------------------------

class BasePermFormView(discord.ui.View):
    """Shared config form: feature toggle, min level, permissions."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild, owner_id: int | None) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.owner_id = owner_id
        self.is_global = owner_id is None
        self.embed: discord.Embed | None = None
        self._title: str = "Permissions"
        self._owner_mention: str | None = None
        self._role_mention: str | None = None

    async def _load(self) -> tuple[int, int, list[str]]:
        if self.is_global:
            row = await self.cog.db.get_custom_role_global_settings(self.guild.id)
            enabled = int(row["enabled"]) if row else 1
            min_level = int(row["min_level"]) if row else 0
            perms = await self.cog.db.get_custom_role_global_permissions(self.guild.id)
        else:
            row = await self.cog.db.get_custom_role_perms(self.guild.id, self.owner_id)
            enabled = int(row["enabled"]) if row else 1
            min_level = int(row["min_level"]) if row else 0
            perms = await self.cog.db.get_custom_role_permissions(self.guild.id, self.owner_id)
        return enabled, min_level, perms

    async def _render(self, interaction: discord.Interaction, title: str, owner_mention: str | None, role_mention: str | None) -> None:
        enabled, min_level, perms = await self._load()

        status = "On" if enabled else "Off"
        status_emoji = "🟢" if enabled else "🔴"
        perm_list = ", ".join(perm_display(p) for p in perms) if perms else "None"
        if len(perm_list) > 900:
            perm_list = perm_list[:900] + " …"

        lines = [
            f"Feature: {status_emoji} **{status}**",
            f"Minimum level: **{min_level}** (0-1000)",
            f"Enabled permissions ({len(perms)}): {perm_list}",
        ]
        if owner_mention:
            lines.insert(0, f"Owner: {owner_mention}")
        if role_mention:
            lines.insert(1 if owner_mention else 0, f"Role: {role_mention}")

        self.embed = make_embed(title, "\n".join(lines), color=SUCCESS if enabled else DANGER)
        self.embed.set_footer(text="Changes apply to the role owner only, not shared holders. Does not touch server roles.")

        self._title = title
        self._owner_mention = owner_mention
        self._role_mention = role_mention

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

    async def refresh(self, interaction: discord.Interaction) -> None:
        """Subclasses override to compute title/mentions then call _render."""
        raise NotImplementedError

    async def _on_toggle(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        if self.is_global:
            row = await self.cog.db.get_custom_role_global_settings(interaction.guild.id)
            current = int(row["enabled"]) if row else 1
            await self.cog.db.set_custom_role_global_settings(interaction.guild.id, enabled=0 if current else 1)
        else:
            row = await self.cog.db.get_custom_role_perms(interaction.guild.id, self.owner_id)
            current = int(row["enabled"]) if row else 1
            await self.cog.db.set_custom_role_perms(interaction.guild.id, self.owner_id, enabled=0 if current else 1)
        await self._render(interaction, self._title, self._owner_mention, self._role_mention)

    async def _on_level(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        if self.is_global:
            row = await self.cog.db.get_custom_role_global_settings(interaction.guild.id)
            current = int(row["min_level"]) if row else 0
        else:
            row = await self.cog.db.get_custom_role_perms(interaction.guild.id, self.owner_id)
            current = int(row["min_level"]) if row else 0
        modal = MinLevelModal(self.cog, current, self.is_global, self.owner_id)
        await interaction.response.send_modal(modal)

    async def _on_perms(self, interaction: discord.Interaction) -> None:
        assert interaction.guild
        view = await PermListView.create(self.cog, self.guild, owner_id=self.owner_id, page=0, back_view=self)
        await interaction.response.edit_message(
            embed=make_embed(
                "Permissions",
                "Click a permission to toggle it (green = on, red = off).",
                color=COLOR,
            ),
            view=view,
        )

    async def _on_back(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)


# ---------------------------------------------------------------------------
# Per-role config form
# ---------------------------------------------------------------------------

class PermFormView(BasePermFormView):
    """Config form for a single custom role's owner."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild, owner: discord.Member, role: discord.Role | None) -> None:
        super().__init__(cog, guild, owner.id)
        self.owner = owner
        self.role = role

    async def refresh(self, interaction: discord.Interaction) -> None:
        title = f"Permissions — {self.role.name if self.role else 'deleted role'}"
        owner_mention = self.owner.mention
        role_mention = self.role.mention if self.role else "deleted"
        await self._render(interaction, title, owner_mention, role_mention)


# ---------------------------------------------------------------------------
# Global config form
# ---------------------------------------------------------------------------

class GlobalPermFormView(BasePermFormView):
    """Config form for the global default config."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild) -> None:
        super().__init__(cog, guild, None)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self._render(interaction, "Custom Role Permission Panel (Global)", None, None)


# ---------------------------------------------------------------------------
# View: role list (the panel) + global config button
# ---------------------------------------------------------------------------

class PermPanelView(discord.ui.View):
    """Panel listing every custom role as a button, plus a Global Config button."""

    def __init__(self, cog: "PermPanel", guild: discord.Guild, roles: list[discord.Role], page: int = 0) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.roles = roles
        self.page = page
        self.embed: discord.Embed | None = None
        self._build()

    def _build(self) -> None:
        total_pages = max(1, math.ceil(len(self.roles) / ROLE_PAGE_SIZE))
        page = max(0, min(self.page, total_pages - 1))
        self.page = page
        self.total_pages = total_pages
        start = page * ROLE_PAGE_SIZE
        end = start + ROLE_PAGE_SIZE
        page_roles = self.roles[start:end]

        self.clear_items()
        for index, role in enumerate(page_roles):
            button = discord.ui.Button(label=role.name[:80], style=discord.ButtonStyle.secondary, custom_id=f"panel:role:{role.id}", row=index // 5)
            button.callback = self._make_role_callback(role.id)
            self.add_item(button)

        # Global config button (its own row).
        global_btn = discord.ui.Button(label="Global Config", style=discord.ButtonStyle.primary, custom_id="panel:global", row=5)
        global_btn.callback = self._on_global
        self.add_item(global_btn)

        nav_row = 6
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
                "Privileges apply to the role owner only — not to members the role was shared with.\n"
                "Use Global Config to set the per-guild default."
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

    async def _on_global(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        form = GlobalPermFormView(self.cog, interaction.guild)
        await form.refresh(interaction)

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
    """Admin panel for custom role owner privileges (per-role + global config)."""

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
                "Use `.permpanel custom role` to open the panel.",
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
                "Use `.permpanel custom role` to open the panel.",
                color=COLOR,
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @permpanel_custom.command(name="role", description="Open the custom role permission panel (role list + global config).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def permpanel_custom_role(self, ctx: commands.Context) -> None:
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
