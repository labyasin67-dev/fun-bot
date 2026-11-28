"""Member-created custom roles, with staff controls and alt-account enforcement."""

from __future__ import annotations

import io
import logging
import struct
import zlib
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


def _colour_value(colour: discord.Colour | int) -> int:
    return colour.value if isinstance(colour, discord.Colour) else int(colour)


def gradient_preview_png(primary: discord.Colour | int, secondary: discord.Colour | int | None = None, *, width: int = 320, height: int = 48) -> io.BytesIO:
    """Build a small RGB PNG of a solid bar or a two-colour gradient (no extra deps)."""
    def rgb(value: int) -> tuple[int, int, int]:
        value = int(value) & 0xFFFFFF
        return (value >> 16) & 255, (value >> 8) & 255, value & 255

    r1, g1, b1 = rgb(_colour_value(primary))
    r2, g2, b2 = rgb(_colour_value(secondary) if secondary is not None else _colour_value(primary))
    raw = bytearray()
    for _y in range(height):
        raw.append(0)
        for x in range(width):
            t = x / (width - 1) if width > 1 else 0
            raw.extend((
                int(r1 + (r2 - r1) * t),
                int(g1 + (g2 - g1) * t),
                int(b1 + (b2 - b1) * t),
            ))
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    buf = io.BytesIO(png)
    buf.seek(0)
    return buf


def attach_colour_preview(embed: discord.Embed, primary: discord.Colour | int, secondary: discord.Colour | int | None = None) -> discord.File:
    value = _colour_value(primary)
    if embed.colour is None or embed.colour.value == 0:
        embed.colour = discord.Colour(value)
    embed.set_image(url="attachment://gradient.png")
    return discord.File(gradient_preview_png(primary, secondary), filename="gradient.png")


def role_colour_snapshot(role: discord.Role | None, row) -> tuple[str, discord.Colour | int | None, discord.Colour | int | None]:
    name = role.name if role is not None else f"deleted ({row['role_id']})"
    primary = role.colour if role is not None else None
    secondary = getattr(role, "secondary_colour", None) if role is not None else None
    if secondary is None and row["secondary_colour"] is not None:
        secondary = int(row["secondary_colour"])
    return name, primary, secondary


def describe_removed_role(name: str, primary, secondary, *, holder_id: int | None) -> str:
    if primary is not None:
        colours = f"**Colour:** {format_colour_pair(primary, secondary)}"
    else:
        colours = "**Colour:** —"
    lines = [f"**Role:** {name}", colours]
    if holder_id is not None:
        lines.append(f"**Also removed from:** <@{holder_id}> (they were holding it through `.role give`)")
    return "\n".join(lines)



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


async def reply(dest, embed: discord.Embed, *, ephemeral: bool = False, view: discord.ui.View | None = None, file: discord.File | None = None) -> None:
    kwargs = {"embed": embed, "allowed_mentions": NO_MENTIONS, "ephemeral": ephemeral}
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file
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
    """Highest position the bot can assign: immediately under its top role."""
    me = guild.me
    if me is None or me.top_role is None:
        return None
    pos = me.top_role.position - 1
    return pos if pos >= 1 else None


async def place_role(role: discord.Role, settings) -> None:
    pos = placement_position(role.guild, settings)
    if pos is None:
        return
    try:
        await role.edit(position=pos, reason="Place custom role just under the bot's highest role")
    except discord.HTTPException:
        log.warning("Could not move custom role %s in guild %s", role.id, role.guild.id)


async def place_self_role_low(role: discord.Role) -> None:
    """Move a self-role/server-given role near the bottom so custom creator roles sit above it."""
    me = role.guild.me
    if me is None or me.top_role is None:
        return
    # Put it just above the @everyone role (position 1), but not below it.
    pos = 1
    try:
        await role.edit(position=pos, reason="Place self-role near the bottom so custom roles show on top")
    except discord.HTTPException:
        log.warning("Could not move self-role %s to bottom in guild %s", role.id, role.guild.id)


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


async def remove_role_from_all_members(bot: SocializeBot, guild: discord.Guild, role_id: int, reason: str) -> None:
    """Remove a custom role from every member who currently has it."""
    role = guild.get_role(role_id)
    if role is None:
        return
    for member in guild.members:
        if role in member.roles:
            try:
                await member.remove_roles(role, reason=reason)
            except discord.HTTPException:
                pass


async def remove_stored_custom_role(bot: SocializeBot, guild: discord.Guild, user_id: int, *, reason: str) -> discord.Role | int | None:
    row = await bot.db.delete_custom_role(guild.id, user_id)
    if row is None:
        return None
    role_id = int(row["role_id"])
    role = guild.get_role(role_id)
    await remove_role_from_all_members(bot, guild, role_id, reason=reason)
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


def holder_id_of(row) -> int:
    raw = row["holder_id"] if "holder_id" in row.keys() else None
    return int(raw) if raw else int(row["user_id"])


def given_custom_roles_held(member_role_ids: set[int], rows, *, member_id: int):
    """Custom roles owned by someone else that this member currently holds."""
    found = []
    held = set(member_role_ids)
    for row in rows:
        if int(row["user_id"]) == int(member_id):
            continue
        if int(row["role_id"]) not in held:
            continue
        found.append(row)
    return found


async def member_owns_or_holds(db, guild_id: int, user_id: int):
    owned = await db.get_custom_role(guild_id, user_id)
    if owned is not None:
        return owned
    return await db.get_custom_role_held(guild_id, user_id)


async def transfer_custom_role(bot: SocializeBot, guild: discord.Guild, row, to_member: discord.Member | None, *, reason: str) -> str | None:
    role = guild.get_role(int(row["role_id"]))
    if role is None:
        return "That custom role no longer exists."
    current = guild.get_member(holder_id_of(row))
    if current is not None and role in current.roles:
        try:
            await current.remove_roles(role, reason=reason)
        except discord.HTTPException:
            return "I couldn't remove the role from the current holder."
    if to_member is not None:
        try:
            await to_member.add_roles(role, reason=reason)
        except discord.HTTPException:
            return "I couldn't give the role to that member."
        await bot.db.set_custom_role_holder(guild.id, int(row["user_id"]), to_member.id)
        try:
            settings = await bot.db.get_customrole_settings(guild.id)
            await place_role(role, settings)
        except Exception:
            log.warning("Could not reposition custom role %s in guild %s", role.id, guild.id, exc_info=True)
    else:
        await bot.db.set_custom_role_holder(guild.id, int(row["user_id"]), int(row["user_id"]))
    return None



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
        holder_raw = row["holder_id"] if "holder_id" in row.keys() else None
        uids = {int(row["user_id"])}
        if holder_raw:
            uids.add(int(holder_raw))
        for uid in uids:
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
    group = {member.id, *linked}
    for uid in group:
        held = await bot.db.get_custom_role_held(member.guild.id, uid)
        if held is None:
            continue
        owner_id = int(held["user_id"])
        if owner_id == uid:
            continue
        owner = member.guild.get_member(owner_id)
        await transfer_custom_role(
            bot, member.guild, held, owner, reason="Returned because linked alt accounts cannot share a custom role"
        )
    owners: list[tuple[int, float]] = []
    for uid in group:
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



ICON_MAX_BYTES = 256 * 1024
ICON_TYPES = {"image/png", "image/jpeg", "image/jpg"}
ICON_EXTS = (".png", ".jpg", ".jpeg")


def guild_has_role_icons(guild: discord.Guild) -> bool:
    return "ROLE_ICONS" in (guild.features or [])


async def read_role_icon(attachment: discord.Attachment) -> tuple[bytes | None, str | None]:
    name = (attachment.filename or "").lower()
    ctype = (attachment.content_type or "").split(";")[0].strip().lower()
    if ctype not in ICON_TYPES and not name.endswith(ICON_EXTS):
        return None, "The role icon must be a PNG or JPG file."
    if attachment.size and int(attachment.size) > ICON_MAX_BYTES:
        return None, "The role icon must be 256 KB or smaller."
    data = await attachment.read()
    if len(data) > ICON_MAX_BYTES:
        return None, "The role icon must be 256 KB or smaller."
    return data, None


COLOR_PRESETS = [
    ("Red", "#FF0000"),
    ("Blue", "#0000FF"),
    ("Green", "#00AA00"),
    ("Yellow", "#FFD700"),
    ("Purple", "#800080"),
    ("Pink", "#FF69B4"),
    ("Orange", "#FFA500"),
    ("Teal", "#008080"),
    ("Black", "#2C2F33"),
    ("White", "#FFFFFF"),
    ("Gold", "#B8860B"),
    ("Lavender", "#E6E6FA"),
    ("Mint", "#98FF98"),
    ("Peach", "#FFDAB9"),
    ("Navy", "#000080"),
    ("Crimson", "#DC143C"),
    ("Lime", "#32CD32"),
    ("Magenta", "#FF00FF"),
    ("Cyan", "#00FFFF"),
    ("Silver", "#C0C0C0"),
]


class RoleColorPickerView(discord.ui.View):
    """Pick preset colours for both role colours, then open the name modal."""

    def __init__(
        self,
        cog: CustomRoles,
        *,
        default_name: str | None = None,
        default_colour1: str | None = None,
        default_colour2: str | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.default_name = default_name or ""
        self.selected_colour1 = default_colour1
        self.selected_colour2 = default_colour2

        self.colour1_select = discord.ui.Select(
            placeholder="Pick colour 1",
            min_values=1,
            max_values=1,
        )
        for name, hex_val in COLOR_PRESETS:
            self.colour1_select.add_option(
                label=name,
                value=hex_val,
                description=hex_val,
            )
        self.colour1_select.add_option(
            label="Custom hex",
            value="__custom__",
            description="Type your own hex in the next step",
        )
        if default_colour1:
            for option in self.colour1_select.options:
                if option.value == default_colour1:
                    option.default = True
        self.colour1_select.callback = self._on_colour1_select
        self.add_item(self.colour1_select)

        self.colour2_select = discord.ui.Select(
            placeholder="Pick colour 2 (optional)",
            min_values=1,
            max_values=1,
        )
        self.colour2_select.add_option(
            label="None",
            value="#NONE",
            description="No second colour",
        )
        for name, hex_val in COLOR_PRESETS:
            self.colour2_select.add_option(
                label=name,
                value=hex_val,
                description=hex_val,
            )
        self.colour2_select.add_option(
            label="Custom hex",
            value="__custom__",
            description="Type your own hex in the next step",
        )
        if default_colour2:
            for option in self.colour2_select.options:
                if option.value == default_colour2:
                    option.default = True
        self.colour2_select.callback = self._on_colour2_select
        self.add_item(self.colour2_select)

        self.create_button = discord.ui.Button(label="Create Role", style=discord.ButtonStyle.primary)
        self.create_button.callback = self._on_create
        self.add_item(self.create_button)

    async def _on_colour1_select(self, interaction: discord.Interaction) -> None:
        val = self.colour1_select.values[0]
        self.selected_colour1 = None if val == "__custom__" else val
        await interaction.response.defer()

    async def _on_colour2_select(self, interaction: discord.Interaction) -> None:
        val = self.colour2_select.values[0]
        self.selected_colour2 = None if val in ("#NONE", "__custom__") else val
        await interaction.response.defer()

    async def _on_create(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            CreateCustomRoleModal(
                self.cog,
                default_name=self.default_name,
                default_colour1=self.selected_colour1,
                default_colour2=self.selected_colour2,
            )
        )


class CreateCustomRoleModal(discord.ui.Modal, title="Customize Role"):
    def __init__(
        self,
        cog: CustomRoles,
        *,
        default_name: str | None = None,
        default_colour1: str | None = None,
        default_colour2: str | None = None,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.name_input = discord.ui.TextInput(
            placeholder="Your role name",
            default=(default_name or "")[:32],
            min_length=1,
            max_length=32,
            required=True,
        )
        self.colour1_input = discord.ui.TextInput(
            placeholder="#A0BAF2",
            min_length=6,
            max_length=8,
            required=True,
            default=default_colour1,
        )
        self.colour2_input = discord.ui.TextInput(
            placeholder="#00ffcc",
            required=False,
            max_length=8,
            default=default_colour2,
        )
        self.icon_upload = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
        self.add_item(discord.ui.Label(
            text="Role Name",
            description="Choose the name displayed for your custom role.",
            component=self.name_input,
        ))
        self.add_item(discord.ui.Label(
            text="Hex Color 1",
            description="Primary colour (e.g. #A0BAF2).",
            component=self.colour1_input,
        ))
        self.add_item(discord.ui.Label(
            text="Hex Color 2",
            description="Optional second colour for a gradient.",
            component=self.colour2_input,
        ))
        self.add_item(discord.ui.Label(
            text="Role Icon (Optional)",
            description="Leave empty for no new icon.",
            component=self.icon_upload,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        icon = None
        uploads = list(self.icon_upload.values)
        if uploads:
            if not interaction.response.is_done():
                await interaction.response.defer()
            icon, err = await read_role_icon(uploads[0])
            if err:
                await reply(interaction, make_embed("Invalid icon", err, color=DANGER), ephemeral=True)
                return
        await self.cog.complete_create(
            interaction,
            name=str(self.name_input.value),
            colour=str(self.colour1_input.value),
            colour2=str(self.colour2_input.value or "").strip() or None,
            icon=icon,
        )


def visible_profile_roles(
    member: discord.Member,
    *,
    custom_role_id: int | None,
    hidden: set[int],
) -> list[discord.Role]:
    roles = [role for role in member.roles if not role.is_default() and role.id not in hidden]
    custom = None
    if custom_role_id:
        custom = next((role for role in roles if role.id == int(custom_role_id)), None)
    rest = [role for role in roles if custom is None or role.id != custom.id]
    rest.sort(key=lambda role: role.position, reverse=True)
    return ([custom] + rest) if custom is not None else rest


class HideRolesView(discord.ui.View):
    def __init__(self, cog: "CustomRoles", member: discord.Member, roles: list[discord.Role], hidden: set[int]) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.member = member
        options = []
        for role in roles[:25]:
            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    default=role.id in hidden,
                    description="Hidden from profile" if role.id in hidden else "Shown on profile",
                )
            )
        select = discord.ui.Select(
            placeholder="Select roles to hide from your profile",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Only you can change your hidden roles.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("This only works in a server.", ephemeral=True)
            return
        values = [int(v) for v in (interaction.data or {}).get("values", [])]
        await self.cog.bot.db.set_profile_hidden_roles(interaction.guild.id, self.member.id, values)
        hidden = set(values)
        hidden_mentions = [role.mention for role in self.member.roles if role.id in hidden]
        body = "Those roles will stay hidden from `.profile` in this server. Discord itself still shows them."
        if hidden_mentions:
            body += "\n**Hidden:** " + " ".join(hidden_mentions[:20])
        await interaction.response.edit_message(
            embed=make_embed("Profile roles updated", body, color=SUCCESS),
            view=None,
        )


class RemoveGivenRolesView(discord.ui.View):
    def __init__(self, cog: "CustomRoles", member: discord.Member, items: list[tuple]) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.member = member
        self.items = {int(role.id): row for row, role in items}
        options = []
        for row, role in items[:25]:
            owner_id = int(row["user_id"])
            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    description=f"Owned by {owner_id}"[:100],
                )
            )
        select = discord.ui.Select(
            placeholder="Select custom roles to remove from yourself",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Only you can remove roles from yourself.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This only works in a server.", ephemeral=True)
            return
        member = guild.get_member(self.member.id) or interaction.user
        values = [int(v) for v in (interaction.data or {}).get("values", [])]
        rows = await self.cog.bot.db.list_custom_roles(guild.id)
        allowed = {
            int(row["role_id"]): row
            for row in given_custom_roles_held({role.id for role in member.roles}, rows, member_id=member.id)
        }
        removed = []
        errors = []
        for role_id in values:
            row = allowed.get(role_id)
            if row is None:
                errors.append(f"`{role_id}` isn't a custom role someone else gave you.")
                continue
            err = await drop_given_custom_role(self.cog.bot, guild, member, row)
            role = guild.get_role(role_id)
            name = role.mention if role else f"`{role_id}`"
            if err:
                errors.append(f"{name}: {err}")
            else:
                removed.append(name)
        parts = []
        if removed:
            parts.append("Removed: " + " ".join(removed))
        if errors:
            parts.append("\n".join(errors))
        title = "Custom roles removed" if removed else "Couldn't remove those roles"
        color = SUCCESS if removed and not errors else (WARNING if removed else DANGER)
        await interaction.response.edit_message(
            embed=make_embed(title, "\n".join(parts) or "Nothing was removed.", color=color),
            view=None,
        )


async def drop_given_custom_role(bot: "SocializeBot", guild: discord.Guild, member: discord.Member, row) -> str | None:
    """Remove a custom role owned by someone else from this member. Does not touch staff or server roles."""
    owner_id = int(row["user_id"])
    if owner_id == member.id:
        return "That's your own custom role."
    role = guild.get_role(int(row["role_id"]))
    if role is None:
        return "That custom role no longer exists."
    if role not in member.roles:
        return "You don't have that role."
    stored = await bot.db.get_custom_role_by_role_id(guild.id, role.id)
    if stored is None or int(stored["user_id"]) == member.id:
        return "That isn't a custom role someone else gave you."
    me = guild.me
    if me is not None and me.top_role <= role:
        return "My highest role is too low to remove that custom role."
    if holder_id_of(stored) == member.id:
        owner = guild.get_member(owner_id)
        return await transfer_custom_role(
            bot, guild, stored, owner if owner is not None else None, reason=f"Dropped with .roleremoveme by {member}"
        )
    try:
        await member.remove_roles(role, reason=f"Dropped with .roleremoveme by {member}")
    except discord.HTTPException:
        return "I couldn't remove that role."
    return None


class CustomRoles(commands.Cog):
    """Custom roles members can create once they reach a set level."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                settings = await self.bot.db.get_customrole_settings(guild.id)
                for row in await self.bot.db.list_custom_roles(guild.id):
                    role = guild.get_role(int(row["role_id"]))
                    if role is not None:
                        await place_role(role, settings)
                # Reposition self-roles to the bottom so custom creator roles show on top.
                for row in await self.bot.db.self_roles(guild.id):
                    role = guild.get_role(int(row["role_id"]))
                    if role is not None:
                        try:
                            await role.edit(position=1, reason="Place self-role near the bottom so custom roles show on top")
                        except discord.HTTPException:
                            pass
            except Exception:
                log.warning("Could not reposition roles in guild %s", getattr(guild, "id", "?"), exc_info=True)

    @commands.hybrid_group(name="role", description="Custom roles, or add and remove a role.", invoke_without_command=True)
    @commands.guild_only()
    async def role(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Role commands",
                "• `.role create <name> [#hex1] [#hex2]` — make your custom role; two colours make a gradient\n"
                "• `.role create` — open a form for the name and colours\n"
                "• `.role name <new name>` / `.role colour <hex>` / `.role gradient #hex1 #hex2`\n"
                "• `.role delete` / `.role remove` — delete your own custom role\n"
                "• `.role info`\n"
                "• `.role give @user @role` / `.role take @user`\n"
                "• `.roleremoveme` — drop a custom role someone gave you\n"
                "• `.role add @user @role` / `.role remove @user [@role]` — (manage roles)\n"
                "• `.role toggle on|off` / `.role minlevel <n>` — (manage roles)\n"
                "• `.role restrict @user [reason]` / `.role unrestrict @user`\n"
                "• `.role remove @user` — (manage roles) take away their custom role\n"
                "• `.role manage` — hide roles from your `.profile`\n"
                "• `.role list` — show custom roles and restrictions",
            ),
            allowed_mentions=NO_MENTIONS,
        )

    @role.command(name="create", description="Create your one custom role.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(
        name="Name of your custom role. Leave empty to open the Customize Role form.",
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
            await reply(
                ctx,
                make_embed(
                    "Customize Role",
                    "Pick colours for your custom role, then enter the name in the next step.",
                ),
                view=RoleColorPickerView(self, default_name=name),
                ephemeral=True,
            )
            return
        if not name:
            await reply(ctx, make_embed("Missing name", "Give the role a name, or run `.role create` with no arguments to open the Customize Role form.", color=DANGER), ephemeral=True)
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
        held = await self.bot.db.get_custom_role_held(guild.id, member.id)
        if held is not None and int(held["user_id"]) != member.id:
            return "You're already holding someone else's custom role. They can take it back with `.role take`, or wait until you no longer hold one."
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
        icon: bytes | None = None,
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
        icon_note = ""
        if icon:
            if not guild_has_role_icons(guild):
                icon_note = " This server doesn't have role icons, so the icon wasn't applied."
            else:
                try:
                    await role.edit(display_icon=icon, reason=f"Custom role icon set by {author} ({author.id})")
                except discord.HTTPException:
                    icon_note = " The role was created, but I couldn't set the icon."
        preview_secondary = secondary if used_gradient else None
        if secondary is not None and not used_gradient:
            detail = (
                f"You now have {role.mention} in `{colour_hex(primary)}`. {GRADIENT_BOOST_NOTE}"
            )
            colour = WARNING
        elif used_gradient and secondary is not None:
            detail = (
                f"You now have {role.mention} with a gradient {format_colour_pair(primary, secondary)}. "
                "This is the only custom role you can have."
            )
            colour = SUCCESS
        else:
            detail = f"You now have {role.mention}"
            if primary and primary.value:
                detail += f" in `{colour_hex(primary)}`"
            detail += ". This is the only custom role you can have."
            colour = SUCCESS
        embed = make_embed("Custom role created", detail + icon_note, color=colour)
        preview = attach_colour_preview(embed, primary, preview_secondary)
        await reply(dest, embed, file=preview)

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
        embed = make_embed("Colour updated", f"{role.mention} is now `{colour_hex(parsed)}`.", color=SUCCESS)
        await reply(ctx, embed, file=attach_colour_preview(embed, parsed))

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
            embed = make_embed(
                "Gradient not available",
                f"{role.mention} is now `{colour_hex(primary)}`. {GRADIENT_BOOST_NOTE}",
                color=WARNING,
            )
            await reply(ctx, embed, file=attach_colour_preview(embed, primary))
            return
        await self.bot.db.set_custom_role_secondary(ctx.guild.id, ctx.author.id, secondary.value)
        embed = make_embed("Gradient updated", f"{role.mention} is now {format_colour_pair(primary, secondary)}.", color=SUCCESS)
        await reply(ctx, embed, file=attach_colour_preview(embed, primary, secondary))

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
        row = await member_owns_or_holds(self.bot.db, ctx.guild.id, target.id)
        if row is None:
            whose = "You don't" if target == ctx.author else f"{target.mention} doesn't"
            await ctx.send(embed=make_embed("No custom role", f"{whose} have a custom role in this server.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        role = ctx.guild.get_role(int(row["role_id"]))
        created = int(float(row["created_at"]))
        owner_id = int(row["user_id"])
        held_by = holder_id_of(row)
        held_line = ""
        if held_by != owner_id:
            held_line = f"\n**Owner:** <@{owner_id}>\n**Held by:** <@{held_by}>"
        if role:
            secondary = getattr(role, "secondary_colour", None)
            if secondary is None and row["secondary_colour"] is not None:
                secondary = int(row["secondary_colour"])
            body = (
                f"**Member:** {target.mention}\n"
                f"**Role:** {role.mention}\n"
                f"**Colour:** {format_colour_pair(role.colour, secondary)}\n"
                f"**Created:** <t:{created}:F>"
                f"{held_line}"
            )
        else:
            stored = colour_hex_optional(row["secondary_colour"])
            colour_line = f"**Colour 2:** `{stored}`\n" if stored else ""
            body = (
                f"**Member:** {target.mention}\n"
                f"**Role:** deleted (`{row['role_id']}`)\n"
                f"{colour_line}"
                f"**Created:** <t:{created}:F>"
                f"{held_line}"
            )
        await ctx.send(embed=make_embed("Custom role", body), allowed_mentions=NO_MENTIONS)

    @role.command(name="give", description="Hand your custom role to another member.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="Who should receive your custom role.")
    async def role_give(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        if member.bot:
            await ctx.send(embed=make_embed("Can't do that", "Bots can't hold a custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if member.id == ctx.author.id:
            await ctx.send(embed=make_embed("Can't do that", "You already have your own custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        row = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        if row is None:
            await ctx.send(embed=make_embed("No custom role", "You do not have a custom role to give.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        role_id = int(row["role_id"])
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send(embed=make_embed("Role missing", "Your custom role no longer exists.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if holder_id_of(row) == member.id:
            await ctx.send(embed=make_embed("Already given", f"{role.mention} was already given to {member.mention}.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        settings = await self.bot.db.get_customrole_settings(ctx.guild.id)
        staff = ctx.author.guild_permissions.manage_roles
        if not staff and not int(settings["give_enabled"] if "give_enabled" in settings.keys() else 1):
            await ctx.send(embed=make_embed("Giving is off", "Staff have turned off `.role give` in this server.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if await self.bot.db.is_custom_role_restricted(ctx.guild.id, ctx.author.id):
            await ctx.send(embed=make_embed("Restricted", "You can't give a custom role while you're restricted.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if await self.bot.db.is_custom_role_restricted(ctx.guild.id, member.id):
            await ctx.send(embed=make_embed("Restricted", f"{member.mention} is restricted from custom roles, so they can't receive one.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if not staff and await self.bot.db.is_custom_role_give_blocked(ctx.guild.id, ctx.author.id):
            await ctx.send(embed=make_embed("Blocked", "You're blocked from using `.role give`.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        linked = await find_linked_user_ids(self.bot, ctx.guild, member)
        for uid in linked:
            if await self.bot.db.get_custom_role(ctx.guild.id, uid) is not None:
                await ctx.send(embed=make_embed("Can't give that", f"{member.mention} is linked to an account that already has a custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
        if ctx.guild.me.top_role <= role:
            await ctx.send(embed=make_embed("Can't do that", "My highest role is too low to move that custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        # Role sharing: owner keeps their role, just add it to the new member.
        try:
            await member.add_roles(role, reason=f"Given by {ctx.author}")
        except discord.HTTPException:
            await ctx.send(embed=make_embed("Couldn't give the role", "Check my permissions and try again.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await ctx.send(embed=make_embed("Custom role given", f"{role.mention} has been given to {member.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="take", description="Take a custom role back from a member.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member who currently holds the custom role.")
    async def role_take(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        row = await self.bot.db.get_custom_role_held(ctx.guild.id, member.id)
        if row is None:
            await ctx.send(embed=make_embed("Not holding one", f"{member.mention} isn't holding a custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        owner_id = int(row["user_id"])
        staff = ctx.author.guild_permissions.manage_roles
        if not staff and ctx.author.id != owner_id:
            await ctx.send(embed=make_embed("Not yours", "You can only take back your own custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if holder_id_of(row) == owner_id:
            await ctx.send(embed=make_embed("Already with the owner", "That custom role is already with its owner.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        owner = ctx.guild.get_member(owner_id)
        if owner is None:
            await ctx.send(embed=make_embed("Owner left", "The owner of that custom role is no longer in the server. Staff can remove it with `.role remove`.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        err = await transfer_custom_role(self.bot, ctx.guild, row, owner, reason=f"Taken back by {ctx.author}")
        if err:
            await ctx.send(embed=make_embed("Couldn't take the role back", err, color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        role = ctx.guild.get_role(int(row["role_id"]))
        mention = role.mention if role else "The custom role"
        await ctx.send(embed=make_embed("Custom role returned", f"{mention} is back with {owner.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

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

    @role.command(name="purge", description="Delete your custom role, or (staff) purge a member's custom role entirely.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="Leave empty to delete your own custom role. Staff can name a member.")
    async def role_purge(self, ctx: commands.Context, member: discord.Member | None = None, role: discord.Role | None = None) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        staff = ctx.author.guild_permissions.manage_roles

        if member is None and role is None:
            existing = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
            if existing is None:
                await ctx.send(embed=make_embed("No custom role", "You don't have a custom role to purge. Staff can use `.role purge @member`.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            discord_role = ctx.guild.get_role(int(existing["role_id"]))
            name, primary, secondary = role_colour_snapshot(discord_role, existing)
            holder = holder_id_of(existing)
            also = holder if holder != ctx.author.id else None
            await remove_stored_custom_role(self.bot, ctx.guild, ctx.author.id, reason=f"Purged by owner {ctx.author}")
            body = describe_removed_role(name, primary, secondary, holder_id=also)
            embed = make_embed("Custom role purged", body, color=SUCCESS)
            file = attach_colour_preview(embed, primary, secondary) if primary is not None else None
            await reply(ctx, embed, file=file)
            return

        if not staff:
            await ctx.send(embed=make_embed("Staff only", "To delete your own custom role, use `.role purge` with no one mentioned. Removing someone else's role needs Manage Roles.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if member is None:
            await ctx.send(embed=make_embed("Who?", "Mention a member, or use `.role purge` with no arguments to delete your own custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if role is None:
            existing = await self.bot.db.get_custom_role(ctx.guild.id, member.id)
            if existing is None:
                await ctx.send(embed=make_embed("No custom role", f"{member.mention} doesn't have a custom role.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            discord_role = ctx.guild.get_role(int(existing["role_id"]))
            name, primary, secondary = role_colour_snapshot(discord_role, existing)
            holder = holder_id_of(existing)
            also = holder if holder != member.id else None
            await remove_stored_custom_role(self.bot, ctx.guild, member.id, reason=f"Purged by {ctx.author}")
            body = describe_removed_role(name, primary, secondary, holder_id=also)
            embed = make_embed("Custom role purged", f"Purged **{name}** from {member.mention}.\n" + body, color=SUCCESS)
            file = attach_colour_preview(embed, primary, secondary) if primary is not None else None
            await reply(ctx, embed, file=file)
            try:
                await member.send(
                    embed=make_embed(
                        "Custom role purged",
                        f"Your custom role **{name}** was purged in **{ctx.guild.name}**.",
                        color=WARNING,
                    ),
                    allowed_mentions=NO_MENTIONS,
                )
            except discord.HTTPException:
                pass
            return
        err = can_manage_role(ctx.author, ctx.guild.me, role)
        if err:
            await ctx.send(embed=make_embed("Can't remove that role", err, color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if role not in member.roles:
            await ctx.send(embed=make_embed("Doesn't have it", f"{member.mention} doesn't have {role.mention}."), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await member.remove_roles(role, reason=f"Purged by {ctx.author}")
        stored = await self.bot.db.get_custom_role(ctx.guild.id, member.id)
        if stored is not None and int(stored["role_id"]) == role.id:
            await self.bot.db.delete_custom_role(ctx.guild.id, member.id)
        await ctx.send(embed=make_embed("Role purged", f"Purged {role.mention} from {member.mention}.", color=SUCCESS), allowed_mentions=NO_MENTIONS)

    @role.command(name="remove", description="Remove your custom role from another member who holds it.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    @app_commands.describe(member="The member who holds your custom role.")
    async def role_remove(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member) and ctx.guild.me
        if member.id == ctx.author.id:
            await ctx.send(embed=make_embed("Can't do that", "You can't remove your own custom role with this command. Use `.role delete` instead.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        row = await self.bot.db.get_custom_role(ctx.guild.id, ctx.author.id)
        if row is None:
            await ctx.send(embed=make_embed("No custom role", "You do not have a custom role to remove from someone.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        role_id = int(row["role_id"])
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send(embed=make_embed("Role missing", "Your custom role no longer exists.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if role not in member.roles:
            await ctx.send(embed=make_embed("Already removed", f"{member.mention} already does not have {role.mention}.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        try:
            await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        except discord.HTTPException:
            await ctx.send(embed=make_embed("Couldn't remove the role", "Check my permissions and try again.", color=DANGER), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        await self.bot.db.set_custom_role_holder(ctx.guild.id, ctx.author.id, ctx.author.id)
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

    @role.command(name="manage", description="Choose which of your roles are hidden from your .profile.")
    @commands.guild_only()
    async def role_manage(self, ctx: commands.Context) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        hidden = set(await self.bot.db.get_profile_hidden_roles(ctx.guild.id, ctx.author.id))
        held = await member_owns_or_holds(self.bot.db, ctx.guild.id, ctx.author.id)
        custom_id = int(held["role_id"]) if held is not None else None
        roles = [role for role in ctx.author.roles if not role.is_default()]
        roles.sort(key=lambda role: (0 if custom_id and role.id == custom_id else 1, -role.position))
        if not roles:
            await reply(ctx, make_embed("No roles", "You don't have any roles I can hide on your profile.", color=DANGER), ephemeral=True)
            return
        extra = ""
        if len(roles) > 25:
            roles = roles[:25]
            extra = " Only the first 25 roles are listed, with your custom role first if you have one."
        await reply(
            ctx,
            make_embed(
                "Hide roles from your profile",
                "Select the roles that should be hidden on `.profile` in this server."
                " This does not hide them in Discord."
                + extra,
            ),
            ephemeral=True,
            view=HideRolesView(self, ctx.author, roles, hidden),
        )

    @commands.hybrid_command(name="profile", description="Show a member's profile and visible roles.")
    @commands.guild_only()
    @app_commands.describe(member="Optional member to look up.")
    async def profile(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        assert ctx.guild
        target = member or ctx.author
        hidden = set(await self.bot.db.get_profile_hidden_roles(ctx.guild.id, target.id))
        held = await member_owns_or_holds(self.bot.db, ctx.guild.id, target.id)
        custom_id = int(held["role_id"]) if held is not None else None
        roles = visible_profile_roles(target, custom_role_id=custom_id, hidden=hidden)
        role_line = " ".join(role.mention for role in roles) if roles else "None shown"
        if len(role_line) > 1000:
            role_line = " ".join(role.mention for role in roles[:30])
            if len(roles) > 30:
                role_line += f" … +{len(roles) - 30} more"
        body = (
            f"**Member:** {target.mention} (`{target.id}`)\n"
            f"**Username:** @{target.name}\n"
            f"**Roles:** {role_line}"
        )
        await reply(ctx, make_embed(f"{target.display_name}'s profile", body), ephemeral=False)

    @commands.hybrid_command(name="roleremoveme", description="Remove a custom role someone else gave you.")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(manage_roles=True)
    async def roleremoveme(self, ctx: commands.Context) -> None:
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        rows = await self.bot.db.list_custom_roles(ctx.guild.id)
        held_rows = given_custom_roles_held({role.id for role in ctx.author.roles}, rows, member_id=ctx.author.id)
        items = []
        for row in held_rows:
            role = ctx.guild.get_role(int(row["role_id"]))
            if role is not None:
                items.append((row, role))
        if not items:
            await reply(
                ctx,
                make_embed(
                    "No given custom roles",
                    "You don't have any custom roles that someone else gave you. This command can't remove your own custom role or server roles.",
                    color=DANGER,
                ),
                ephemeral=True,
            )
            return
        extra = ""
        if len(items) > 25:
            items = items[:25]
            extra = " Only the first 25 are listed."
        await reply(
            ctx,
            make_embed(
                "Remove given custom roles",
                "Select any custom roles other members gave you that you want to remove from yourself."
                " Server and staff roles can't be removed this way."
                + extra,
            ),
            ephemeral=True,
            view=RemoveGivenRolesView(self, ctx.author, items),
        )

    @role.command(name="list", description="List custom roles and restrictions in this server.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    async def role_list(self, ctx: commands.Context) -> None:
        assert ctx.guild
        settings = await self.bot.db.get_customrole_settings(ctx.guild.id)
        rows = await self.bot.db.list_custom_roles(ctx.guild.id)
        restricted = await self.bot.db.list_custom_role_restrictions(ctx.guild.id)
        state = "on" if int(settings["enabled"] or 0) else "off"
        give_state = "on" if int(settings["give_enabled"] if "give_enabled" in settings.keys() else 1) else "off"
        lines = [f"Feature is **{state}**. Giving roles is **{give_state}**. Minimum level: **{int(settings['min_level'] or 0)}**."]
        if rows:
            lines.append("\n**Custom roles**")
            for row in rows[:25]:
                role = ctx.guild.get_role(int(row["role_id"]))
                mention = role.mention if role else f"deleted (`{row['role_id']}`)"
                held_by = holder_id_of(row)
                owner_id = int(row["user_id"])
                extra = f" (held by <@{held_by}>)" if held_by != owner_id else ""
                lines.append(f"• <@{owner_id}> — {mention}{extra}")
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
        owned = await self.bot.db.get_custom_role(member.guild.id, member.id)
        if owned is not None:
            await remove_stored_custom_role(
                self.bot,
                member.guild,
                member.id,
                reason=f"Custom role owner left ({member.id})",
            )
            return
        held = await self.bot.db.get_custom_role_held(member.guild.id, member.id)
        if held is None or int(held["user_id"]) == member.id:
            return
        owner = member.guild.get_member(int(held["user_id"]))
        await transfer_custom_role(
            self.bot,
            member.guild,
            held,
            owner,
            reason=f"Holder left ({member.id}); returned to owner",
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.bot.db.delete_custom_role_by_role_id(role.guild.id, role.id)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(CustomRoles(bot))
