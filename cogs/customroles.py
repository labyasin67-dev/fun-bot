"""Member-created custom roles, with staff controls and alt-account enforcement."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.roles import can_manage_role
from utils import DANGER, SUCCESS, WARNING, embed as make_embed, level_from_xp, NO_MENTIONS

if TYPE_CHECKING:
    from main import SocializeBot

log = logging.getLogger("socialize")

ALT_LINK_WINDOW = 6 * 3600

STAFF_NAME_RE = re.compile(
    r"\b(admins?|administrators?|mods?|moderators?|moderation|staff|owners?|officials?)\b",
    re.IGNORECASE,
)
MENTION_NAME_RE = re.compile(r"@(?:everyone|here)\b|^\s*(?:everyone|here)\s*$", re.IGNORECASE)
# Simple blocked terms: staff titles plus a short slur/abuse list.
BLOCKED_TERMS = frozenset(
    {
        "admin",
        "admins",
        "administrator",
        "administrators",
        "mod",
        "mods",
        "moderator",
        "moderators",
        "moderation",
        "staff",
        "owner",
        "owners",
        "official",
        "officials",
        "everyone",
        "here",
        "nigger",
        "nigga",
        "faggot",
        "fag",
        "retard",
        "retarded",
        "kike",
        "spic",
        "chink",
        "tranny",
        "rape",
        "rapist",
    }
)

HEX_RE = re.compile(r"^(?:#|0x)?([0-9a-fA-F]{6})$")


def parse_hex_colour(raw: str | None) -> discord.Colour | None:
    if raw is None:
        return None
    match = HEX_RE.fullmatch(raw.strip())
    if not match:
        return None
    return discord.Colour(int(match.group(1), 16))


def _tokens(name: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", name.lower()) if tok}


def is_staff_role(role: discord.Role) -> bool:
    perms = role.permissions
    return bool(
        perms.administrator
        or perms.manage_guild
        or perms.manage_roles
        or perms.ban_members
        or perms.kick_members
        or perms.moderate_members
        or perms.manage_channels
    )


def validate_custom_role_name(name: str, guild: discord.Guild | None = None) -> str | None:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 32:
        return "Role names must be between 1 and 32 characters."
    if MENTION_NAME_RE.search(cleaned) or "@everyone" in cleaned.lower() or "@here" in cleaned.lower():
        return "That name isn't allowed."
    tokens = _tokens(cleaned)
    if tokens & BLOCKED_TERMS or STAFF_NAME_RE.search(cleaned):
        return "That name isn't allowed."
    if guild is not None:
        lowered = cleaned.lower()
        for role in guild.roles:
            if role.name.lower() == lowered and is_staff_role(role):
                return "That name matches an existing staff role."
    return None


def colour_hex(colour: discord.Colour | int) -> str:
    value = colour.value if isinstance(colour, discord.Colour) else int(colour)
    return f"#{value:06x}"


def colour_hex_optional(value) -> str:
    if value is None:
        return ""
    if isinstance(value, discord.Colour):
        return colour_hex(value)
    try:
        return colour_hex(int(value))
    except (TypeError, ValueError):
        return ""


def format_colour_pair(primary: discord.Colour | int, secondary: discord.Colour | int | None = None) -> str:
    if secondary is None:
        return f"`{colour_hex(primary)}`"
    return f"`{colour_hex(primary)}` → `{colour_hex(secondary)}`"


def guild_has_gradients(guild: discord.Guild) -> bool:
    return "ENHANCED_ROLE_COLORS" in (guild.features or [])


GRADIENT_BOOST_NOTE = (
    "Gradients need more server boosts (enhanced role colours), so I used the first colour only."
)


async def create_coloured_role(
    guild: discord.Guild,
    *,
    name: str,
    primary: discord.Colour,
    secondary: discord.Colour | None,
    reason: str,
) -> tuple[discord.Role, bool]:
    """Create a role. Returns (role, used_gradient)."""
    kwargs = {
        "name": name,
        "colour": primary,
        "permissions": discord.Permissions.none(),
        "mentionable": False,
        "hoist": False,
        "reason": reason,
    }
    if secondary is not None and guild_has_gradients(guild):
        try:
            role = await guild.create_role(**kwargs, secondary_colour=secondary)
            return role, True
        except (discord.HTTPException, TypeError):
            pass
    role = await guild.create_role(**kwargs)
    return role, False


async def edit_role_colours(
    role: discord.Role,
    *,
    primary: discord.Colour,
    secondary: discord.Colour | None,
    reason: str,
) -> bool:
    """Apply colours. Returns True if a gradient was applied."""
    if secondary is not None and guild_has_gradients(role.guild):
        try:
            await role.edit(colour=primary, secondary_colour=secondary, reason=reason)
            return True
        except (discord.HTTPException, TypeError):
            pass
    try:
        await role.edit(colour=primary, secondary_colour=None, reason=reason)
    except (discord.HTTPException, TypeError):
        await role.edit(colour=primary, reason=reason)
    return False


async def reply(dest, embed: discord.Embed, *, ephemeral: bool = False, view: discord.ui.View | None = None) -> None:
    kwargs = {"embed": embed, "allowed_mentions": NO_MENTIONS, "ephemeral": ephemeral}
    if view is not None:
        kwargs["view"] = view
    if isinstance(dest, discord.Interaction):
        if dest.response.is_done():
            kwargs.pop("ephemeral", None)
            await dest.followup.send(**kwargs, ephemeral=ephemeral)
        else:
            await dest.response.send_message(**kwargs)
        return
    await dest.send(**kwargs)


async def member_level(db, guild_id: int, user_id: int) -> int:
    row = await db.get_member(guild_id, user_id)
    xp = int(row["xp"]) if row is not None else 0
    return level_from_xp(xp)


def placement_position(guild: discord.Guild, settings) -> int | None:
    me = guild.me
    if me is None or me.top_role is None:
        return None
    ceiling = me.top_role.position
    anchor_id = settings["anchor_role_id"] if settings and settings["anchor_role_id"] else None
    if anchor_id:
        anchor = guild.get_role(int(anchor_id))
        if anchor is not None and 0 < anchor.position < ceiling:
            ceiling = anchor.position
    pos = ceiling - 1
    return pos if pos >= 1 else None


async def place_role(role: discord.Role, settings) -> None:
    pos = placement_position(role.guild, settings)
    if pos is None:
        return
    try:
        await role.edit(position=pos, reason="Place custom role below the bot or anchor role")
    except discord.HTTPException:
        log.warning("Could not move custom role %s in guild %s", role.id, role.guild.id)


async def delete_guild_role(guild: discord.Guild, role_id: int, *, reason: str) -> bool:
    role = guild.get_role(role_id)
    if role is None:
        return False
    try:
        await role.delete(reason=reason)
        return True
    except discord.HTTPException:
        log.warning("Could not delete custom role %s in guild %s", role_id, guild.id)
        return False


async def remove_stored_custom_role(bot: SocializeBot, guild: discord.Guild, user_id: int, *, reason: str) -> discord.Role | int | None:
    row = await bot.db.delete_custom_role(guild.id, user_id)
    if row is None:
        return None
    role_id = int(row["role_id"])
    role = guild.get_role(role_id)
    await delete_guild_role(guild, role_id, reason=reason)
    return role if role is not None else role_id


async def restrict_user(
    bot: SocializeBot,
    guild: discord.Guild,
    user_id: int,
    *,
    reason: str | None,
    by: int | None,
    delete_role: bool = True,
) -> object:
    removed = None
    if delete_role:
        removed = await remove_stored_custom_role(
            bot, guild, user_id, reason=reason or "Custom role restriction"
        )
    await bot.db.restrict_custom_role_user(guild.id, user_id, reason=reason, by=by)
    return removed


async def find_linked_user_ids(bot: SocializeBot, guild: discord.Guild, user: discord.abc.User) -> set[int]:
    created = user.created_at.timestamp() if getattr(user, "created_at", None) else None
    linked: set[int] = set()
    if created is None:
        return linked
    rows = await bot.db.alt_flag_created_times(guild.id)
    for row in rows:
        uid = int(row["user_id"])
        if uid == user.id:
            continue
        other = row["account_created_at"]
        if other is not None and abs(float(other) - created) <= ALT_LINK_WINDOW:
            linked.add(uid)
    for row in await bot.db.list_custom_roles(guild.id):
        uid = int(row["user_id"])
        if uid == user.id or uid in linked:
            continue
        member = guild.get_member(uid)
        other = None
        if member is not None and member.created_at:
            other = member.created_at.timestamp()
        if other is not None and abs(other - created) <= ALT_LINK_WINDOW:
            linked.add(uid)
    return linked


async def _alt_log(bot: SocializeBot, guild: discord.Guild, embed: discord.Embed) -> None:
    log_id = await bot.db.get_feature_channel(guild.id, "alts")
    channel = guild.get_channel(log_id) if log_id else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            log.warning("Could not post custom-role alt log in guild %s", guild.id)
    try:
        await bot.db.add_mod_log(guild.id, "customrole_alt", embed.description or "Custom role alt restriction")
    except Exception:
        pass


async def enforce_custom_roles_on_alt_flag(bot: SocializeBot, member: discord.Member) -> None:
    """If a flagged account is linked to another custom-role owner, drop the newer role and restrict."""
    if member.bot:
        return
    if await bot.db.is_alt_whitelisted(member.guild.id, member.id):
        return
    linked = await find_linked_user_ids(bot, member.guild, member)
    if not linked:
        return
    owners: list[tuple[int, float]] = []
    for uid in {member.id, *linked}:
        row = await bot.db.get_custom_role(member.guild.id, uid)
        if row is not None:
            owners.append((uid, float(row["created_at"])))
    if len(owners) < 2:
        return
    owners.sort(key=lambda item: (item[1], item[0] == member.id), reverse=True)
    # Newest custom role is removed; if tied, prefer the newly flagged member.
    target_id = owners[0][0]
    reason = "Alt detection linked two accounts that both had a custom role"
    await restrict_user(bot, member.guild, target_id, reason=reason, by=None, delete_role=True)
    mention = f"<@{target_id}>"
    others = ", ".join(f"<@{uid}>" for uid, _ in owners if uid != target_id)
    await _alt_log(
        bot,
        member.guild,
        make_embed(
            "Custom role removed (alt link)",
            f"{mention} was restricted and their custom role was deleted because they were "
            f"linked to {others or 'another account'} that also has a custom role.\n"
            f"**Reason:** {reason}",
            color=WARNING,
        ),
    )


async def refuse_if_flagged_alt(bot: SocializeBot, member: discord.Member) -> str | None:
    if await bot.db.is_alt_whitelisted(member.guild.id, member.id):
        return None
    if not await bot.db.has_alt_flag(member.guild.id, member.id):
        return None
    linked = await find_linked_user_ids(bot, member.guild, member)
    for uid in linked:
        if await bot.db.get_custom_role(member.guild.id, uid) is not None:
            reason = "Flagged as an alt of a member who already has a custom role"
            await restrict_user(bot, member.guild, member.id, reason=reason, by=None, delete_role=True)
            await _alt_log(
                bot,
                member.guild,
                make_embed(
                    "Custom role blocked (alt)",
                    f"{member.mention} (`{member.id}`) tried to create a custom role but is linked to "
                    f"<@{uid}>, who already has one. They have been restricted.",
                    color=WARNING,
                ),
            )
            return "You can't create a custom role because this account is linked to someone who already has one. You've been restricted from this feature."
    return None



class CreateCustomRoleModal(discord.ui.Modal, title="Create custom role"):
    def __init__(self, cog: CustomRoles, *, default_name: str | None = None) -> None:
        super().__init__()
        self.cog = cog
        self.name_input = discord.ui.TextInput(
            label="Name",
            placeholder="Your role name",
            default=(default_name or "")[:32],
            min_length=1,
            max_length=32,
            required=True,
        )
        self.colour1_input = discord.ui.TextInput(
            label="Colour 1 (hex)",
            placeholder="#ff0000",
            min_length=6,
            max_length=8,
            required=True,
        )
        self.colour2_input = discord.ui.TextInput(
            label="Colour 2 (hex, optional)",
            placeholder="#0000ff for a gradient",
            required=False,
            max_length=8,
        )
        self.add_item(self.name_input)
        self.add_item(self.colour1_input)
        self.add_item(self.colour2_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.complete_create(
            interaction,
            name=str(self.name_input.value),
            colour=str(self.colour1_input.value),
            colour2=str(self.colour2_input.value or "").strip() or None,
        )


class OpenCreateFormView(discord.ui.View):
    def __init__(self, cog: CustomRoles, *, default_name: str | None = None) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.default_name = default_name

    @discord.ui.button(label="Open form", style=discord.ButtonStyle.primary)
    async def open_form(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CreateCustomRoleModal(self.cog, default_name=self.default_name))


class CustomRoles(commands.Cog):
    """Custom roles members can create once they reach a set level."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="role", description="Custom roles, or add and remove a role.", invoke_without_command=True)
    @commands.guild_only()
    async def role(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Role commands",
                "• `.role create <name> [#hex1] [#hex2]` — make your custom role; two colours make a gradient\n"
                "• `.role create` — open a form for the name and colours\n"
                "• `.role name <new name>` / `.role colour <hex>` / `.role gradient #hex1 #hex2`\n"
                "• `.role delete` / `.role info`\n"
                "• `.role add @user @role` / `.role remove @user [@role]` — (manage roles)\n"
                "• `.role toggle on|off` / `.role minlevel <n>` — (manage roles)\n"
                "• `.role restrict @user [reason]` / `.role unrestrict @user`\n"
                "• `.role remove @user` — take away their custom role\n"
                "• `.role list` — show custom roles and restrictions",
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @role.command(name="create", description="Create your one custom role.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(
        name="Name of your custom role. Leave empty to use the form.",
        colour="Optional hex colour, like #ff0000.",
        colour2="Optional second hex colour to make a gradient.",
    )
    async def role_create(
        self,
        ctx: commands.Context,
        name: str | None = None,
        colour: str | None = None,
        colour2: str | None = None,
    ) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        blocked = await self.creation_block_reason(ctx.guild, ctx.author)
        if blocked:
            await reply(ctx, make_embed("Can't create a custom role", blocked, color=DANGER), ephemeral=True)
            return
        wants_form = not colour
        if wants_form:
            if ctx.interaction is not None:
                await ctx.interaction.response.send_modal(CreateCustomRoleModal(self, default_name=name))
                return
            await reply(
                ctx,
                make_embed(
                    "Create a custom role",
                    "Tap the button below to open a form for the name, a colour, and an optional second colour for a gradient.",
                ),
                view=OpenCreateFormView(self, default_name=name),
            )
            return
        if not name:
            await reply(ctx, make_embed("Missing name", "Give the role a name, or run `.role create` with no arguments to use the form.", color=DANGER), ephemeral=True)
            return
        await self.complete_create(ctx, name=name, colour=colour, colour2=colour2)

    async def creation_block_reason(self, guild: discord.Guild, member: discord.Member) -> str | None:
        settings = await self.bot.db.get_customrole_settings(guild.id)
        if not int(settings["enabled"] or 0):
            return "Staff can turn this on with `.role toggle on`."
        if await self.bot.db.is_custom_role_restricted(guild.id, member.id):
            return "You can't create a custom role in this server."
        existing = await self.bot.db.get_custom_role(guild.id, member.id)
        if existing is not None:
            role = guild.get_role(int(existing["role_id"]))
            mention = role.mention if role else "your custom role"
            return f"You already have {mention}. Use `.role name`, `.role colour` or `.role gradient` to edit it, or `.role delete` to remove it."
        min_level = int(settings["min_level"] or 0)
        level = await member_level(self.bot.db, guild.id, member.id)
        if level < min_level:
            return f"You need to be at least level **{min_level}**. You're level **{level}**."
        blocked = await refuse_if_flagged_alt(self.bot, member)
        if blocked:
            return blocked
        me = guild.me
        if me is None or me.top_role is None or me.top_role.position <= 1:
            return "My highest role is too low to create a custom role. Move me up in the role list."
        return None

    async def complete_create(
        self,
        dest: commands.Context | discord.Interaction,
        *,
        name: str,
        colour: str | None,
        colour2: str | None,
    ) -> None:
        guild = dest.guild if isinstance(dest, commands.Context) else dest.guild
        author = dest.author if isinstance(dest, commands.Context) else dest.user
        if guild is None or not isinstance(author, discord.Member):
            await reply(dest, make_embed("Server only", "This only works in a server.", color=DANGER), ephemeral=True)
            return
        blocked = await self.creation_block_reason(guild, author)
        if blocked:
            await reply(dest, make_embed("Can't create a custom role", blocked, color=DANGER), ephemeral=True)
            return
        error = validate_custom_role_name(name, guild)
        if error:
            await reply(dest, make_embed("Invalid name", error, color=DANGER), ephemeral=True)
            return
        primary = parse_hex_colour(colour) if colour else None
        if colour and primary is None:
            await reply(dest, make_embed("Invalid colour", "Use a 6-digit hex colour such as `#ff0000`.", color=DANGER), ephemeral=True)
            return
        secondary = None
        if colour2:
            secondary = parse_hex_colour(colour2)
            if secondary is None:
                await reply(dest, make_embed("Invalid colour", "The second colour must also be a 6-digit hex, such as `#0000ff`.", color=DANGER), ephemeral=True)
                return
        if primary is None:
            primary = discord.Colour.default()
        settings = await self.bot.db.get_customrole_settings(guild.id)
        try:
            role, used_gradient = await create_coloured_role(
                guild,
                name=name.strip(),
                primary=primary,
                secondary=secondary,
                reason=f"Custom role created by {author} ({author.id})",
            )
        except discord.HTTPException:
            await reply(dest, make_embed("Couldn't create that role", "Discord rejected the role. Try a different name, or check my Manage Roles permission.", color=DANGER), ephemeral=True)
            return
        await place_role(role, settings)
        try:
            await author.add_roles(role, reason="Assign custom role to creator")
        except discord.HTTPException:
            await delete_guild_role(guild, role.id, reason="Failed to assign custom role")
            await reply(dest, make_embed("Couldn't assign the role", "I created the role but couldn't give it to you, so I deleted it. Check the role order and my permissions.", color=DANGER), ephemeral=True)
            return
        stored_secondary = secondary.value if used_gradient and secondary is not None else None
        await self.bot.db.add_custom_role(guild.id, author.id, role.id, secondary_colour=stored_secondary)
        if secondary is not None and not used_gradient:
            detail = (
                f"You now have {role.mention} in `{colour_hex(primary)}`. {GRADIENT_BOOST_NOTE}"
            )
        elif used_gradient and secondary is not None:
            detail = (
                f"You now have {role.mention} with a gradient {format_colour_pair(primary, secondary)}. "
                "This is the only custom role you can have."
            )
        else:
            detail = f"You now have {role.mention}. This is the only custom role you can have."
        await reply(dest, make_embed("Custom role created", detail, color=SUCCESS))

    @role.command(name="name", description="Rename your custom role.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(new_name="The new name (1-32 characters).")
    async def role_name(self, ctx: commands.Context, *, new_name: str) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        role = await self._owned_role(ctx)
        if role is None:
            return
        error = validate_custom_role_name(new_name, ctx.guild)
        if error:
            await reply(ctx, make_embed("Invalid name", error, color=DANGER), ephemeral=True)
            return
        try:
            await role.edit(name=new_name.strip(), reason=f"Renamed by {ctx.author}")
        except discord.HTTPException:
            await reply(ctx, make_embed("Couldn't rename that role", "Check my permissions and try again.", color=DANGER), ephemeral=True)
            return
        await reply(ctx, make_embed("Role renamed", f"Your custom role is now {role.mention}.", color=SUCCESS))

    @role.command(name="colour", description="Change your custom role colour.", aliases=["color"])
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(hex_colour="A 6-digit hex colour, like #ff0000. This clears any gradient.")
    async def role_colour(self, ctx: commands.Context, hex_colour: str) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        role = await self._owned_role(ctx)
        if role is None:
            return
        parsed = parse_hex_colour(hex_colour)
        if parsed is None:
            await reply(ctx, make_embed("Invalid colour", "Use a 6-digit hex colour such as `#ff0000`.", color=DANGER), ephemeral=True)
            return
        try:
            await edit_role_colours(role, primary=parsed, secondary=None, reason=f"Colour changed by {ctx.author}")
        except discord.HTTPException:
            await reply(ctx, make_embed("Couldn't change that colour", "Check my permissions and try again.", color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_custom_role_secondary(ctx.guild.id, ctx.author.id, None)
        await reply(ctx, make_embed("Colour updated", f"{role.mention} is now `{colour_hex(parsed)}`.", color=SUCCESS))

    @role.command(name="gradient", description="Give your custom role a two-colour gradient.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(hex1="First hex colour, like #ff0000.", hex2="Second hex colour, like #0000ff.")
    async def role_gradient(self, ctx: commands.Context, hex1: str, hex2: str) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        role = await self._owned_role(ctx)
        if role is None:
            return
        primary = parse_hex_colour(hex1)
        secondary = parse_hex_colour(hex2)
        if primary is None or secondary is None:
            await reply(ctx, make_embed("Invalid colour", "Use two 6-digit hex colours, such as `.role gradient #ff0000 #0000ff`.", color=DANGER), ephemeral=True)
            return
        try:
            used = await edit_role_colours(
                role, primary=primary, secondary=secondary, reason=f"Gradient changed by {ctx.author}"
            )
        except discord.HTTPException:
            await reply(ctx, make_embed("Couldn't change that gradient", "Check my permissions and try again.", color=DANGER), ephemeral=True)
            return
        if not used:
            await self.bot.db.set_custom_role_secondary(ctx.guild.id, ctx.author.id, None)
            await reply(
                ctx,
                make_embed(
                    "Gradient not available",
                    f"{role.mention} is now `{colour_hex(primary)}`. {GRADIENT_BOOST_NOTE}",
                    color=WARNING,
                ),
            )
            return
        await self.bot.db.set_custom_role_secondary(ctx.guild.id, ctx.author.id, secondary.value)
        await reply(
            ctx,
            make_embed("Gradient updated", f"{role.mention} is now {format_colour_pair(primary, secondary)}.", color=SUCCESS),
        )

    @role.command(name="delete", description="Delete your custom role.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    async def role_delete(self, ctx: commands.Context) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        row = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        if row is None:
            await ctx.send(embed=make_embed("No custom role", "You don't have a custom role to delete.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await remove_stored_custom_role(self.bot, ctx.guild, ctx.author.id, reason=f"Deleted by owner {ctx.author}")
        await ctx.send(embed=make_embed("Custom role deleted", "Your custom role has been removed. You can create a new one later if you're still allowed to.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="info", description="Show your custom role, or someone else's.")
    @commands.guild_only()
    @app_commands.describe(member="Optional member to look up.")
    async def role_info(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        assert ctx.guild
        target = member or ctx.author
        row = await self.bot.db.get_custom_role(ctx.guild.id, target.id)
        if row is None:
            whose = "You don't" if target == ctx.author else f"{target.mention} doesn't"
            await ctx.send(embed=make_embed("No custom role", f"{whose} have a custom role in this server.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        role = ctx.guild.get_role(int(row["role_id"]))
        created = int(float(row["created_at"]))
        if role:
            secondary = getattr(role, "secondary_colour", None)
            if secondary is None and row["secondary_colour"] is not None:
                secondary = int(row["secondary_colour"])
            body = (
                f"**Member:** {target.mention}\n"
                f"**Role:** {role.mention}\n"
                f"**Colour:** {format_colour_pair(role.colour, secondary)}\n"
                f"**Created:** <t:{created}:F>"
            )
        else:
            stored = colour_hex_optional(row["secondary_colour"])
            colour_line = f"**Colour 2:** `{stored}`\n" if stored else ""
            body = (
                f"**Member:** {target.mention}\n"
                f"**Role:** deleted (`{row['role_id']}`)\n"
                f"{colour_line}"
                f"**Created:** <t:{created}:F>"
            )
        await ctx.send(embed=make_embed("Custom role", body), allowed_mentions=NO_MENTIONS)

    @role.command(name="add", description="Give a member a role.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to give the role to.", role="The role to add.")
    async def role_add(self, ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(embed=make_embed("Can't add that role", err, color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if role in member.roles:
            await ctx.send(embed=make_embed("Already has it", f"{member.mention} already has {role.mention}."), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await member.add_roles(role, reason=f"Added by {ctx.author}")
        await ctx.send(embed=make_embed("Role added", f"Gave {role.mention} to {member.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="remove", description="Remove a member's custom role, or a specific role.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to update.", role="Leave empty to remove their custom role.")
    async def role_remove(self, ctx: commands.Context, member: discord.Member, role: discord.Role | None = None) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        if role is None:
            existing = await self.bot.db.get_custom_role(ctx.guild.id, member.id)
            if existing is None:
                await ctx.send(embed=make_embed("No custom role", f"{member.mention} doesn't have a custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            await remove_stored_custom_role(self.bot, ctx.guild, member.id, reason=f"Removed by {ctx.author}")
            await ctx.send(embed=make_embed("Custom role removed", f"Removed the custom role from {member.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)
            return
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(embed=make_embed("Can't remove that role", err, color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if role not in member.roles:
            await ctx.send(embed=make_embed("Doesn't have it", f"{member.mention} doesn't have {role.mention}."), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        stored = await self.bot.db.get_custom_role(ctx.guild.id, member.id)
        if stored is not None and int(stored["role_id"]) == role.id:
            await self.bot.db.delete_custom_role(ctx.guild.id, member.id)
        await ctx.send(embed=make_embed("Role removed", f"Removed {role.mention} from {member.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="toggle", description="Turn custom roles on or off for this server.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(state="on or off")
    async def role_toggle(self, ctx: commands.Context, state: str) -> None:
        assert ctx.guild
        choice = state.strip().lower()
        if choice not in {"on", "off", "enable", "disable", "true", "false", "1", "0"}:
            await ctx.send(embed=make_embed("Use on or off", "Try `.role toggle on` or `.role toggle off`.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        enabled = 1 if choice in {"on", "enable", "true", "1"} else 0
        await self.bot.db.set_customrole_settings(ctx.guild.id, enabled=enabled)
        if enabled:
            await ctx.send(embed=make_embed("Custom roles enabled", "Members who meet the level requirement can use `.role create`.", color=SUCCESS), allowed_mentions=NO_MENTIONS)
        else:
            await ctx.send(embed=make_embed("Custom roles disabled", "Existing custom roles stay, but nobody can create a new one until you turn this back on.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="minlevel", description="Set the minimum level needed to create a custom role.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(level="Minimum level (0 or higher).")
    async def role_minlevel(self, ctx: commands.Context, level: int) -> None:
        assert ctx.guild
        if level < 0 or level > 1000:
            await ctx.send(embed=make_embed("Invalid level", "Use a level between 0 and 1000.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await self.bot.db.set_customrole_settings(ctx.guild.id, min_level=level)
        await ctx.send(embed=make_embed("Minimum level updated", f"Members need to be at least level **{level}** to create a custom role.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="restrict", description="Remove a member's custom role and block them from creating another.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to restrict.", reason="Why they're being restricted.")
    async def role_restrict(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        await restrict_user(self.bot, ctx.guild, member.id, reason=reason, by=ctx.author.id, delete_role=True)
        detail = f" Reason: {reason}" if reason else ""
        await ctx.send(embed=make_embed("Member restricted", f"{member.mention} can no longer create a custom role, and any custom role they had has been deleted.{detail}", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="unrestrict", description="Allow a restricted member to create a custom role again.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member to unrestrict.")
    async def role_unrestrict(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild
        ok = await self.bot.db.unrestrict_custom_role_user(ctx.guild.id, member.id)
        if not ok:
            await ctx.send(embed=make_embed("Not restricted", f"{member.mention} isn't restricted from custom roles.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await ctx.send(embed=make_embed("Restriction lifted", f"{member.mention} can create a custom role again if they meet the requirements.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="list", description="List custom roles and restrictions in this server.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def role_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        settings = await self.bot.db.get_customrole_settings(ctx.guild.id)
        rows = await self.bot.db.list_custom_roles(ctx.guild.id)
        restricted = await self.bot.db.list_custom_role_restrictions(ctx.guild.id)
        state = "on" if int(settings["enabled"] or 0) else "off"
        lines = [f"Feature is **{state}**. Minimum level: **{int(settings['min_level'] or 0)}**."]
        if rows:
            lines.append("\n**Custom roles**")
            for row in rows[:25]:
                role = ctx.guild.get_role(int(row["role_id"]))
                mention = role.mention if role else f"deleted (`{row['role_id']}`)"
                lines.append(f"• <@{int(row['user_id'])}> — {mention}")
            if len(rows) > 25:
                lines.append(f"…and {len(rows) - 25} more")
        else:
            lines.append("\nNo custom roles yet.")
        if restricted:
            lines.append("\n**Restricted members**")
            for row in restricted[:15]:
                reason = f" — {row['reason']}" if row["reason"] else ""
                lines.append(f"• <@{int(row['user_id'])}>{reason}")
        await ctx.send(embed=make_embed("Custom roles", "\n".join(lines)), allowed_mentions=NO_MENTIONS)

    async def _owned_role(self, ctx: commands.Context) -> discord.Role | None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        row = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        if row is None:
            await ctx.send(embed=make_embed("No custom role", "You don't have a custom role. Create one with `.role create` when you're eligible.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return None
        role = ctx.guild.get_role(int(row["role_id"]))
        if role is None:
            await self.bot.db.delete_custom_role(ctx.guild.id, ctx.author.id)
            await ctx.send(embed=make_embed("Role missing", "Your custom role was deleted, so I cleared it. You can create a new one if you're still allowed to.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return None
        return role

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        row = await self.bot.db.get_custom_role(member.guild.id, member.id)
        if row is None:
            return
        await remove_stored_custom_role(
            self.bot,
            member.guild,
            member.id,
            reason=f"Custom role owner left ({member.id})",
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.bot.db.delete_custom_role_by_role_id(role.guild.id, role.id)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(CustomRoles(bot))
