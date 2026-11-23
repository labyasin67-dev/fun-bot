"""Self-role panels and moderator role commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.v2 import build_game_layout

if TYPE_CHECKING:
    from main import SocializeBot


class SelfRoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"selfrole:(?P<role_id>[0-9]+)"):
    def __init__(self, role_id: int, label: str = "Role", emoji: str | None = None) -> None:
        self.role_id = role_id
        kwargs: dict = {
            "style": discord.ButtonStyle.secondary,
            "label": label[:80],
            "custom_id": f"selfrole:{role_id}",
        }
        if emoji:
            kwargs["emoji"] = emoji
        super().__init__(discord.ui.Button(**kwargs))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: object) -> SelfRoleButton:
        return cls(int(match["role_id"]))  # type: ignore[index]

    async def callback(self, interaction: discord.Interaction) -> None:
        await toggle_self_role(interaction, self.role_id)


async def toggle_self_role(interaction: discord.Interaction, role_id: int) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("This only works in a server.", ephemeral=True)
        return
    role = interaction.guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message("That role no longer exists. Ask a mod to update the panel.", ephemeral=True)
        return
    me = interaction.guild.me
    if me is None or role >= me.top_role or role.is_default() or role.managed:
        await interaction.response.send_message("I can't assign that role. It may be above me or managed.", ephemeral=True)
        return
    member = interaction.user
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Self-role panel")
            await interaction.response.send_message(f"Removed {role.mention}.", ephemeral=True)
        else:
            await member.add_roles(role, reason="Self-role panel")
            await interaction.response.send_message(f"Gave you {role.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to change that role.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("I couldn't update your roles just then. Try again.", ephemeral=True)


def build_self_role_view(rows) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for i, row in enumerate(rows[:25]):
        emoji = row["emoji"]
        try:
            button = SelfRoleButton(int(row["role_id"]), row["label"], emoji)
        except (discord.HTTPException, TypeError, ValueError):
            button = SelfRoleButton(int(row["role_id"]), row["label"], None)
        button.item.row = i // 5
        view.add_item(button)
    return view


def can_manage_role(actor: discord.Member, bot_member: discord.Member, role: discord.Role) -> str | None:
    if role.is_default() or role.managed:
        return "I can't change a managed or @everyone role."
    if role >= bot_member.top_role:
        return "That role is higher than or equal to my highest role."
    if actor != actor.guild.owner and role >= actor.top_role:
        return "That role is higher than or equal to your highest role."
    return None


class Roles(commands.Cog):
    """Self-role panels and moderator role tools."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        bot.add_dynamic_items(SelfRoleButton)

    @commands.hybrid_group(name="role", description="Add or remove a role from a member.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    async def role(self, ctx: commands.Context) -> None:
        await ctx.send(
            layout=build_game_layout(
                "Role commands",
                "• `.role add @user @role` / `/role add`\n"
                "• `.role remove @user @role` / `/role remove`\n"
                "• `.selfrole add`, `.selfrole remove`, `.selfrole panel`, `.selfrole list`",
            )
        )

    @role.command(name="add", description="Give a member a role.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to give the role to.", role="The role to add.")
    async def role_add(self, ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(layout=build_game_layout("Can't add that role", err), ephemeral=True)
            return
        if role in member.roles:
            await ctx.send(layout=build_game_layout("Already has it", f"{member.mention} already has {role.mention}."), ephemeral=True)
            return
        await member.add_roles(role, reason=f"Added by {ctx.author}")
        await ctx.send(layout=build_game_layout("Role added", f"Gave {role.mention} to {member.mention}."))

    @role.command(name="remove", description="Remove a role from a member.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to remove the role from.", role="The role to remove.")
    async def role_remove(self, ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(layout=build_game_layout("Can't remove that role", err), ephemeral=True)
            return
        if role not in member.roles:
            await ctx.send(layout=build_game_layout("Doesn't have it", f"{member.mention} doesn't have {role.mention}."), ephemeral=True)
            return
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        await ctx.send(layout=build_game_layout("Role removed", f"Removed {role.mention} from {member.mention}."))

    @commands.hybrid_group(name="selfrole", description="Manage the self-role button panel.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def selfrole(self, ctx: commands.Context) -> None:
        await ctx.send(
            layout=build_game_layout(
                "Self-roles",
                "• `.selfrole add @role [label] [emoji]` — add a role to the panel\n"
                "• `.selfrole remove @role` — take it off the panel\n"
                "• `.selfrole list` — show configured roles\n"
                "• `.selfrole panel` — post the button panel in this channel",
            )
        )

    @selfrole.command(name="add", description="Add a role to the self-role panel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(role="Role members can pick.", label="Button label. Defaults to the role name.", emoji="Optional emoji for the button.")
    async def selfrole_add(self, ctx: commands.Context, role: discord.Role, label: str | None = None, emoji: str | None = None) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(layout=build_game_layout("Can't use that role", err), ephemeral=True)
            return
        existing = await self.bot.db.self_roles(ctx.guild.id)
        if any(int(r["role_id"]) == role.id for r in existing) is False and len(existing) >= 25:
            await ctx.send(layout=build_game_layout("Panel is full", "You can have at most 25 self-roles."), ephemeral=True)
            return
        await self.bot.db.add_self_role(ctx.guild.id, role.id, (label or role.name)[:80], emoji)
        await ctx.send(layout=build_game_layout("Self-role added", f"{role.mention} is on the panel. Run `.selfrole panel` to post or refresh it."))

    @selfrole.command(name="remove", description="Remove a role from the self-role panel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def selfrole_remove(self, ctx: commands.Context, role: discord.Role) -> None:
        assert ctx.guild
        ok = await self.bot.db.remove_self_role(ctx.guild.id, role.id)
        if not ok:
            await ctx.send(layout=build_game_layout("Not on the panel", f"{role.mention} isn't a self-role."), ephemeral=True)
            return
        await ctx.send(layout=build_game_layout("Self-role removed", f"{role.mention} is no longer on the panel. Post a new panel with `.selfrole panel`."))

    @selfrole.command(name="list", description="List the roles on the self-role panel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def selfrole_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        rows = await self.bot.db.self_roles(ctx.guild.id)
        if not rows:
            await ctx.send(layout=build_game_layout("No self-roles", "Add some with `.selfrole add @role`."))
            return
        lines = []
        for row in rows:
            role = ctx.guild.get_role(int(row["role_id"]))
            mention = role.mention if role else f"`{row['role_id']}` (deleted)"
            emoji = f"{row['emoji']} " if row["emoji"] else ""
            lines.append(f"{emoji}{mention} — {row['label']}")
        await ctx.send(layout=build_game_layout("Self-roles", "\n".join(lines)))

    @selfrole.command(name="panel", description="Post the self-role button panel in this channel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def selfrole_panel(self, ctx: commands.Context) -> None:
        assert ctx.guild
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send(layout=build_game_layout("Can't post here", "Use a text channel."), ephemeral=True)
            return
        try:
            await self.post_panel(ctx.channel)
        except ValueError as err:
            await ctx.send(layout=build_game_layout("No self-roles", str(err)), ephemeral=True)

    async def post_panel(self, channel: discord.TextChannel) -> discord.Message:
        rows = await self.bot.db.self_roles(channel.guild.id)
        if not rows:
            raise ValueError("Add some first with `.selfrole add @role`.")
        view = build_self_role_view(rows)
        return await channel.send(layout=build_game_layout("Pick your roles", "Click a button to add or remove a role.", components=[view]))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Roles(bot))

