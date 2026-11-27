"""Join-to-create temporary voice channels, owner controls, and voice stats."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

JTC_CHANNEL_NAME = "➕ Join to Create"
JTC_CATEGORY_NAME = "Voice Channels"


def humans_in(channel: discord.VoiceChannel | discord.StageChannel) -> list[discord.Member]:
    return [m for m in channel.members if not m.bot]


class RenameModal(discord.ui.Modal, title="Rename voice channel"):
    name = discord.ui.TextInput(label="New name", min_length=1, max_length=100, placeholder="e.g. Movie night")

    def __init__(self, cog: "Voice", channel: discord.VoiceChannel) -> None:
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.name.default = channel.name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.rename_channel(interaction, self.channel, str(self.name.value).strip())


class LimitModal(discord.ui.Modal, title="Set a user limit"):
    limit = discord.ui.TextInput(label="Limit (0 for unlimited)", min_length=1, max_length=2, placeholder="0–99")

    def __init__(self, cog: "Voice", channel: discord.VoiceChannel) -> None:
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.limit.default = str(channel.user_limit or 0)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.limit.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Enter a number from 0 to 99.", ephemeral=True)
            return
        await self.cog.set_limit(interaction, self.channel, int(raw))


class VoiceControlView(discord.ui.View):
    def __init__(self, cog: "Voice") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _channel(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        ch = interaction.channel
        return ch if isinstance(ch, discord.VoiceChannel) else None

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="jtc:lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        await self.cog.lock_channel(interaction, channel)

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary, custom_id="jtc:unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        await self.cog.unlock_channel(interaction, channel)

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="jtc:limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        err = await self.cog.owner_error(interaction.user, channel)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal(self.cog, channel))

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="jtc:rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        err = await self.cog.owner_error(interaction.user, channel)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal(self.cog, channel))

    @discord.ui.button(label="Claim", emoji="👑", style=discord.ButtonStyle.primary, custom_id="jtc:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        await self.cog.claim_channel(interaction, channel)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Kick a member...", min_values=1, max_values=1, custom_id="jtc:kick", row=1)
    async def kick(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        user = select.values[0]
        member = channel.guild.get_member(user.id)
        if member is None:
            await interaction.response.send_message("I couldn't find that member.", ephemeral=True)
            return
        await self.cog.kick_member(interaction, channel, member)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Permit a member (when locked)...", min_values=1, max_values=1, custom_id="jtc:permit", row=2)
    async def permit(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        channel = self._channel(interaction)
        if channel is None:
            await interaction.response.send_message("Use this in the voice channel chat.", ephemeral=True)
            return
        user = select.values[0]
        member = channel.guild.get_member(user.id)
        if member is None:
            await interaction.response.send_message("I couldn't find that member.", ephemeral=True)
            return
        await self.cog.permit_member(interaction, channel, member)


class Voice(commands.Cog):
    """Join-to-create voice channels and live voice stats."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._cleaned = False

    def guild_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    async def cog_load(self) -> None:
        self.bot.add_view(VoiceControlView(self))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        await self._cleanup_temp_channels()

    async def _cleanup_temp_channels(self) -> None:
        rows = await self.bot.db.all_temp_voice()
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(row["channel_id"])) if guild else None
            if not isinstance(channel, discord.VoiceChannel):
                await self.bot.db.delete_temp_voice(int(row["channel_id"]))
                continue
            if not humans_in(channel):
                try:
                    await channel.delete(reason="Empty temporary voice channel (startup cleanup)")
                except discord.HTTPException:
                    pass
                await self.bot.db.delete_temp_voice(channel.id)

    async def owner_error(self, user: discord.abc.User, channel: discord.VoiceChannel) -> str | None:
        row = await self.bot.db.get_temp_voice(channel.id)
        if row is None:
            return "This isn't a temporary voice channel I created."
        if user.id == int(row["owner_id"]):
            return None
        member = channel.guild.get_member(user.id)
        if member and member.guild_permissions.manage_channels:
            return None
        return "Only the channel owner can do that."

    def panel_embed(self, channel: discord.VoiceChannel, owner_id: int) -> discord.Embed:
        e = make_embed(
            "Voice channel controls",
            f"Owner: <@{owner_id}>\n\n"
            "Use the buttons below, or:\n"
            "`.vc lock` · `.vc unlock` · `.vc limit <n>` · `.vc rename <name>`\n"
            "`.vc kick @user` · `.vc permit @user` · `.vc claim`",
        )
        e.add_field(name="Channel", value=channel.mention, inline=True)
        limit = "Unlimited" if not channel.user_limit else str(channel.user_limit)
        e.add_field(name="Limit", value=limit, inline=True)
        return e

    async def _reply(self, dest: commands.Context | discord.Interaction, *, embed: discord.Embed | None = None, content: str | None = None, ephemeral: bool = False) -> None:
        if isinstance(dest, discord.Interaction):
            if dest.response.is_done():
                await dest.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await dest.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await dest.send(content=content, embed=embed, ephemeral=ephemeral)

    @commands.hybrid_command(name="setupjtc", description="Create or set a Join to Create voice channel and category.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_channels=True)
    @commands.bot_has_guild_permissions(manage_channels=True, move_members=True)
    @app_commands.describe(
        channel="Existing voice channel to use as Join to Create. A new one is created if omitted.",
        category="Category for temporary channels. A new one is created if omitted.",
    )
    async def setupjtc(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel | None = None,
        category: discord.CategoryChannel | None = None,
    ) -> None:
        assert ctx.guild and ctx.guild.me
        if ctx.interaction:
            await ctx.defer()

        if category is None and channel is not None and channel.category is not None:
            category = channel.category
        if category is None:
            category = await ctx.guild.create_category(JTC_CATEGORY_NAME, reason="Join to Create setup")

        if channel is None:
            channel = await ctx.guild.create_voice_channel(
                JTC_CHANNEL_NAME,
                category=category,
                reason="Join to Create setup",
            )
        elif channel.category_id != category.id:
            try:
                await channel.edit(category=category, reason="Join to Create setup")
            except discord.HTTPException:
                pass

        await self.bot.db.update_settings(
            ctx.guild.id,
            jtc_channel_id=channel.id,
            jtc_category_id=category.id,
        )
        await ctx.send(
            embed=make_embed(
                "Join to Create is ready",
                f"Members who join {channel.mention} will get their own temporary voice channel in **{category.name}**.\n"
                "Owners can use `.vc` commands or the control panel posted in the channel chat.",
                color=SUCCESS,
            )
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot:
            return
        old_ch = before.channel
        new_ch = after.channel
        if old_ch == new_ch:
            return
        settings = await self.bot.db.get_settings(member.guild.id)
        jtc_id = int(settings["jtc_channel_id"]) if settings and settings["jtc_channel_id"] else None

        if new_ch is not None and jtc_id and new_ch.id == jtc_id:
            async with self.guild_lock(member.guild.id):
                await self._create_or_transfer(member, settings)

        if old_ch is not None and old_ch != new_ch:
            await self._maybe_delete_empty(old_ch)

    async def _create_or_transfer(self, member: discord.Member, settings) -> None:
        guild = member.guild
        existing = await self.bot.db.temp_voice_for_owner(guild.id, member.id)
        if existing:
            channel = guild.get_channel(int(existing["channel_id"]))
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await member.move_to(channel, reason="Rejoining owned temporary voice channel")
                    return
                except discord.HTTPException:
                    pass
            else:
                await self.bot.db.delete_temp_voice(int(existing["channel_id"]))

        category_id = int(settings["jtc_category_id"]) if settings and settings["jtc_category_id"] else None
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            jtc = guild.get_channel(int(settings["jtc_channel_id"])) if settings and settings["jtc_channel_id"] else None
            category = jtc.category if isinstance(jtc, discord.VoiceChannel) else None

        name = f"{member.display_name[:80]}'s Channel"
        me = guild.me
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            member: discord.PermissionOverwrite(
                connect=True,
                speak=True,
                stream=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
            ),
        }
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
            )
        try:
            channel = await guild.create_voice_channel(
                name,
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Join to Create for {member}",
            )
        except discord.HTTPException:
            return

        await self.bot.db.add_temp_voice(channel.id, guild.id, member.id)
        try:
            await member.move_to(channel, reason="Join to Create")
        except discord.HTTPException:
            # If we can't move them, still leave the channel — they can join it.
            pass

        try:
            msg = await channel.send(embed=self.panel_embed(channel, member.id), view=VoiceControlView(self))
            await self.bot.db.set_panel_message(channel.id, msg.id)
        except discord.HTTPException:
            pass

    async def _maybe_delete_empty(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.VoiceChannel):
            return
        row = await self.bot.db.get_temp_voice(channel.id)
        if row is None:
            return
        if humans_in(channel):
            return
        async with self.guild_lock(channel.guild.id):
            # Re-check after lock; someone may have joined.
            fresh = channel.guild.get_channel(channel.id)
            if not isinstance(fresh, discord.VoiceChannel) or humans_in(fresh):
                return
            try:
                await fresh.delete(reason="Temporary voice channel empty")
            except discord.HTTPException:
                pass
            await self.bot.db.delete_temp_voice(channel.id)

    async def _resolve_temp(
        self, dest: commands.Context | discord.Interaction
    ) -> tuple[discord.Member | None, discord.VoiceChannel | None]:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        guild = dest.guild
        if not isinstance(user, discord.Member) or guild is None:
            await self._reply(dest, embed=make_embed("Server only", "Use this in a server.", color=DANGER), ephemeral=True)
            return None, None
        channel = user.voice.channel if user.voice else None
        if isinstance(channel, discord.VoiceChannel):
            row = await self.bot.db.get_temp_voice(channel.id)
            if row:
                return user, channel
        owned = await self.bot.db.temp_voice_for_owner(guild.id, user.id)
        if owned:
            found = guild.get_channel(int(owned["channel_id"]))
            if isinstance(found, discord.VoiceChannel):
                return user, found
        await self._reply(
            dest,
            embed=make_embed(
                "No temporary channel",
                "Join the Join to Create voice channel first, then use this from your personal channel.",
                color=DANGER,
            ),
            ephemeral=True,
        )
        return user, None

    async def lock_channel(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        row = await self.bot.db.get_temp_voice(channel.id)
        owner_id = int(row["owner_id"]) if row else user.id
        owner = channel.guild.get_member(owner_id)
        overwrites = channel.overwrites
        overwrites[channel.guild.default_role] = discord.PermissionOverwrite(connect=False, view_channel=True)
        if owner:
            current = overwrites.get(owner) or discord.PermissionOverwrite()
            current.connect = True
            current.view_channel = True
            overwrites[owner] = current
        try:
            await channel.edit(overwrites=overwrites, reason="Lock temporary voice channel")
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't lock", str(e), color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_temp_locked(channel.id, True)
        await self._reply(dest, embed=make_embed("Channel locked", f"{channel.mention} is locked. Use `.vc permit @user` to let someone in.", color=SUCCESS), ephemeral=True)

    async def unlock_channel(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        overwrites = channel.overwrites
        overwrites[channel.guild.default_role] = discord.PermissionOverwrite(connect=True, view_channel=True)
        try:
            await channel.edit(overwrites=overwrites, reason="Unlock temporary voice channel")
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't unlock", str(e), color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_temp_locked(channel.id, False)
        await self._reply(dest, embed=make_embed("Channel unlocked", f"{channel.mention} is open again.", color=SUCCESS), ephemeral=True)

    async def set_limit(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel, limit: int) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        if limit < 0 or limit > 99:
            await self._reply(dest, embed=make_embed("Invalid limit", "Use a number from 0 to 99. 0 means unlimited.", color=DANGER), ephemeral=True)
            return
        try:
            await channel.edit(user_limit=limit, reason="Temporary voice channel limit")
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't set the limit", str(e), color=DANGER), ephemeral=True)
            return
        text = "Unlimited" if limit == 0 else str(limit)
        await self._reply(dest, embed=make_embed("Limit updated", f"{channel.mention} now has a user limit of **{text}**.", color=SUCCESS), ephemeral=True)

    async def rename_channel(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel, name: str) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        name = name.strip()[:100]
        if not name:
            await self._reply(dest, embed=make_embed("Invalid name", "Give the channel a name.", color=DANGER), ephemeral=True)
            return
        try:
            await channel.edit(name=name, reason="Temporary voice channel rename")
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't rename", str(e), color=DANGER), ephemeral=True)
            return
        await self._reply(dest, embed=make_embed("Renamed", f"The channel is now **{name}**.", color=SUCCESS), ephemeral=True)

    async def kick_member(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel, target: discord.Member) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        if target.id == user.id:
            await self._reply(dest, content="You can't kick yourself. Just leave the channel.", ephemeral=True)
            return
        if target.voice is None or target.voice.channel is None or target.voice.channel.id != channel.id:
            await self._reply(dest, content=f"{target.mention} isn't in this channel.", ephemeral=True)
            return
        try:
            await target.move_to(None, reason=f"Kicked from temporary VC by {user}")
        except discord.Forbidden:
            await self._reply(dest, embed=make_embed("Couldn't kick", "I need the **Move Members** permission.", color=DANGER), ephemeral=True)
            return
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't kick", str(e), color=DANGER), ephemeral=True)
            return
        await self._reply(dest, embed=make_embed("Member kicked", f"{target.mention} was disconnected from {channel.mention}.", color=SUCCESS), ephemeral=True)

    async def permit_member(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel, target: discord.Member) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        err = await self.owner_error(user, channel)
        if err:
            await self._reply(dest, content=err, ephemeral=True)
            return
        overwrites = channel.overwrites
        current = overwrites.get(target) or discord.PermissionOverwrite()
        current.connect = True
        current.view_channel = True
        overwrites[target] = current
        try:
            await channel.edit(overwrites=overwrites, reason=f"Permit {target} in temporary VC")
        except discord.HTTPException as e:
            await self._reply(dest, embed=make_embed("Couldn't permit", str(e), color=DANGER), ephemeral=True)
            return
        await self._reply(dest, embed=make_embed("Member permitted", f"{target.mention} can join {channel.mention} even while it's locked.", color=SUCCESS), ephemeral=True)

    async def claim_channel(self, dest: commands.Context | discord.Interaction, channel: discord.VoiceChannel) -> None:
        user = dest.user if isinstance(dest, discord.Interaction) else dest.author
        if not isinstance(user, discord.Member):
            await self._reply(dest, content="Use this in a server.", ephemeral=True)
            return
        row = await self.bot.db.get_temp_voice(channel.id)
        if row is None:
            await self._reply(dest, content="This isn't a temporary voice channel I created.", ephemeral=True)
            return
        if user.id == int(row["owner_id"]):
            await self._reply(dest, content="You already own this channel.", ephemeral=True)
            return
        if user.voice is None or user.voice.channel is None or user.voice.channel.id != channel.id:
            await self._reply(dest, content="Join the channel first, then claim it.", ephemeral=True)
            return
        owner = channel.guild.get_member(int(row["owner_id"]))
        if owner and owner.voice and owner.voice.channel and owner.voice.channel.id == channel.id:
            await self._reply(dest, content="The owner is still in the channel.", ephemeral=True)
            return
        # Transfer owner overwrites.
        overwrites = channel.overwrites
        if owner and owner in overwrites:
            # Keep a basic connect overwrite if they were permitted, but drop manage rights.
            overwrites[owner] = discord.PermissionOverwrite(connect=True, view_channel=True, speak=True)
        overwrites[user] = discord.PermissionOverwrite(
            connect=True,
            speak=True,
            stream=True,
            view_channel=True,
            manage_channels=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
        )
        try:
            await channel.edit(overwrites=overwrites, reason=f"Claimed by {user}")
        except discord.HTTPException:
            pass
        await self.bot.db.set_temp_owner(channel.id, user.id)
        await self._reply(dest, embed=make_embed("Channel claimed", f"{user.mention} is now the owner of {channel.mention}.", color=SUCCESS), ephemeral=True)

    @commands.hybrid_group(name="vc", description="Control your temporary voice channel.", invoke_without_command=True)
    @commands.guild_only()
    async def vc(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=make_embed(
                "Voice controls",
                "These work on the temporary channel you own:\n"
                "• `.vc lock` / `/vc lock` — only permitted members can join\n"
                "• `.vc unlock` / `/vc unlock`\n"
                "• `.vc limit <n>` / `/vc limit` — 0 for unlimited\n"
                "• `.vc rename <name>` / `/vc rename`\n"
                "• `.vc kick @user` / `/vc kick`\n"
                "• `.vc permit @user` / `/vc permit` — allow someone in while locked\n"
                "• `.vc claim` / `/vc claim` — take ownership if the owner left\n\n"
                "A control panel is also posted in the channel's chat when it's created.",
            )
        )

    @vc.command(name="lock", description="Lock your temporary voice channel.")
    @commands.guild_only()
    async def vc_lock(self, ctx: commands.Context) -> None:
        _member, channel = await self._resolve_temp(ctx)
        if channel:
            await self.lock_channel(ctx, channel)

    @vc.command(name="unlock", description="Unlock your temporary voice channel.")
    @commands.guild_only()
    async def vc_unlock(self, ctx: commands.Context) -> None:
        _member, channel = await self._resolve_temp(ctx)
        if channel:
            await self.unlock_channel(ctx, channel)

    @vc.command(name="limit", description="Set a user limit on your temporary voice channel. 0 means unlimited.")
    @commands.guild_only()
    @app_commands.describe(number="Maximum members. 0 means unlimited.")
    async def vc_limit(self, ctx: commands.Context, number: int) -> None:
        _member, channel = await self._resolve_temp(ctx)
        if channel:
            await self.set_limit(ctx, channel, number)

    @vc.command(name="rename", description="Rename your temporary voice channel.")
    @commands.guild_only()
    @app_commands.describe(name="The new channel name.")
    async def vc_rename(self, ctx: commands.Context, *, name: str) -> None:
        _member, channel = await self._resolve_temp(ctx)
        if channel:
            await self.rename_channel(ctx, channel, name)

    @vc.command(name="kick", description="Disconnect a member from your temporary voice channel.")
    @commands.guild_only()
    @app_commands.describe(member="The member to kick.")
    async def vc_kick(self, ctx: commands.Context, member: discord.Member) -> None:
        _owner, channel = await self._resolve_temp(ctx)
        if channel:
            await self.kick_member(ctx, channel, member)

    @vc.command(name="permit", description="Allow a member to join your locked temporary voice channel.")
    @commands.guild_only()
    @app_commands.describe(member="The member to allow in.")
    async def vc_permit(self, ctx: commands.Context, member: discord.Member) -> None:
        _owner, channel = await self._resolve_temp(ctx)
        if channel:
            await self.permit_member(ctx, channel, member)

    @vc.command(name="claim", description="Claim a temporary voice channel if the owner has left.")
    @commands.guild_only()
    async def vc_claim(self, ctx: commands.Context) -> None:
        user = ctx.author
        if not isinstance(user, discord.Member) or user.voice is None or not isinstance(user.voice.channel, discord.VoiceChannel):
            await ctx.send(embed=make_embed("Join first", "Join the temporary voice channel you want to claim.", color=DANGER), ephemeral=True)
            return
        await self.claim_channel(ctx, user.voice.channel)

    @commands.hybrid_command(name="vcstats", description="Show how many people are in voice right now.")
    @commands.guild_only()
    async def vcstats(self, ctx: commands.Context) -> None:
        assert ctx.guild
        total_humans = 0
        total_bots = 0
        lines: list[str] = []
        channels = [c for c in ctx.guild.channels if isinstance(c, (discord.VoiceChannel, discord.StageChannel))]
        channels.sort(key=lambda c: (-len(humans_in(c)), c.position))
        for ch in channels:
            members = list(ch.members)
            if not members:
                continue
            hum = [m for m in members if not m.bot]
            bots = [m for m in members if m.bot]
            total_humans += len(hum)
            total_bots += len(bots)
            extra = f" + {len(bots)} bot{'s' if len(bots) != 1 else ''}" if bots else ""
            lines.append(f"• {ch.mention} — **{len(hum)}**{extra}")
        if not lines:
            await ctx.send(embed=make_embed("Voice stats", "Nobody is in a voice channel right now."))
            return
        description = f"**{total_humans}** member{'s' if total_humans != 1 else ''} in voice right now"
        if total_bots:
            description += f" (plus {total_bots} bot{'s' if total_bots != 1 else ''})"
        description += ".\n\n" + "\n".join(lines[:20])
        if len(lines) > 20:
            description += f"\n…and {len(lines) - 20} more channels."
        await ctx.send(embed=make_embed("Voice stats", description))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Voice(bot))
