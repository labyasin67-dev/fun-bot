"""User reports for staff, delivered to a report channel or an optional ticket."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.moderation import try_dm
from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed, NO_MENTIONS

if TYPE_CHECKING:
    from main import SocializeBot

log = logging.getLogger("socialize")

COOLDOWN_SECONDS = 60
MAX_OPEN = 3
PREVIEW_LEN = 800
STATUS_LABELS = {
    "open": "Open",
    "approved": "Approved",
    "denied": "Denied",
    "closed": "Closed",
}
STATUS_COLORS = {
    "open": WARNING,
    "approved": SUCCESS,
    "denied": DANGER,
    "closed": COLOR,
}


def snapshot(user: discord.abc.User | discord.Member | None) -> tuple[int | None, str | None, str | None]:
    if user is None:
        return None, None, None
    name = getattr(user, "display_name", None) or getattr(user, "global_name", None) or str(user)
    avatar = None
    av = getattr(user, "display_avatar", None)
    if av is not None:
        avatar = str(av.url)
    return int(user.id), str(name), avatar


def staff_mentions(role: discord.Role | None) -> discord.AllowedMentions:
    if role is None:
        return NO_MENTIONS
    return discord.AllowedMentions(everyone=False, users=False, roles=[role], replied_user=False)


def is_report_staff(member: discord.Member, settings) -> bool:
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    role_id = settings["staff_role_id"] if settings and settings["staff_role_id"] else None
    if role_id and any(role.id == int(role_id) for role in member.roles):
        return True
    return bool(perms.kick_members or perms.ban_members or perms.moderate_members)


def preview_message(message: discord.Message | None) -> str | None:
    if message is None:
        return None
    text = (message.clean_content or "").strip()
    if message.attachments:
        extras = ", ".join(att.filename for att in message.attachments[:4])
        text = f"{text}\n[attachments: {extras}]" if text else f"[attachments: {extras}]"
    if message.stickers:
        text = f"{text}\n[sticker]" if text else "[sticker]"
    text = text.strip()
    if not text:
        return None
    if len(text) > PREVIEW_LEN:
        return text[: PREVIEW_LEN - 1] + "…"
    return text


def format_ts(ts: float | None) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))


def _cached_username(guild: discord.Guild, user_id: int | None, stored_name: str | None = None) -> str | None:
    if user_id:
        member = guild.get_member(int(user_id))
        if member is not None:
            return member.name or member.display_name or stored_name
        state = getattr(guild, "_state", None)
        user = state.get_user(int(user_id)) if state is not None and hasattr(state, "get_user") else None
        if user is not None:
            return getattr(user, "name", None) or getattr(user, "global_name", None) or getattr(user, "display_name", None) or stored_name
    return stored_name


def format_report_user(guild: discord.Guild, user_id, stored_name: str | None = None) -> str:
    """Mention plus @username and id for the report embed: '<@id> @username (id)'."""
    if not user_id:
        if stored_name:
            return stored_name if str(stored_name).startswith("@") else f"@{stored_name}"
        return "—"
    name = _cached_username(guild, int(user_id), stored_name)
    mention = f"<@{int(user_id)}>"
    uid = int(user_id)
    if name:
        uname = name if str(name).startswith("@") else f"@{name}"
        return f"{mention} {uname} ({uid})"
    return f"{mention} ({uid})"


def format_claimer(guild: discord.Guild, user_id, stored_name: str | None = None) -> str:
    """@username (user ID) for a claimed report."""
    if not user_id:
        return stored_name or "—"
    name = _cached_username(guild, int(user_id), stored_name)
    if name:
        uname = name if str(name).startswith("@") else f"@{name}"
        return f"{uname} ({int(user_id)})"
    return str(int(user_id))


def build_report_embed(guild: discord.Guild, row) -> discord.Embed:
    status = str(row["status"] or "open")
    reporter = format_report_user(guild, row["reporter_id"], row["reporter_name"])
    reported = format_report_user(guild, row["reported_user_id"], row["reported_name"]) if row["reported_user_id"] or row["reported_name"] else "—"
    reason = row["reason"] or "No reason given."
    desc = (
        f"**Reporter:** {reporter}\n"
        f"**Reported:** {reported}\n"
        f"**Reason:** {reason}"
    )
    e = make_embed(
        f"Report #{int(row['id'])} — {STATUS_LABELS.get(status, status)}",
        desc,
        color=STATUS_COLORS.get(status, COLOR),
    )
    preview = row["message_preview"]
    link = row["message_link"]
    if preview or link:
        body = preview or "*(no text)*"
        if link:
            body += f"\n[Jump to message]({link})"
        e.add_field(name="Message", value=body[:1024], inline=False)
    if row["claimed_by"]:
        who = format_claimer(guild, row["claimed_by"], row["claimed_by_name"])
        when = format_ts(row["claimed_at"])
        e.add_field(name="Claimed by", value=f"{who}{(' · ' + when) if when else ''}", inline=False)
    if status in {"approved", "denied"} and row["decided_by"]:
        who = row["decided_by_name"] or f"ID {row['decided_by']}"
        when = format_ts(row["decided_at"])
        decision = f"{who}{(' · ' + when) if when else ''}"
        if row["decision_reason"]:
            decision += f"\nReason: {row['decision_reason']}"
        e.add_field(name="Decision", value=decision[:1024], inline=False)
    e.set_footer(text=f"Report #{int(row['id'])} in {guild.name}")
    return e


def build_report_view(ticket_id: int, *, status: str, has_ticket: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    open_ = status == "open"
    decided = status in {"approved", "denied"}
    view.add_item(ReportButton("claim", ticket_id, "Claim", discord.ButtonStyle.secondary, disabled=not open_))
    view.add_item(ReportButton("approve", ticket_id, "Approve", discord.ButtonStyle.success, disabled=not open_))
    view.add_item(ReportButton("deny", ticket_id, "Deny", discord.ButtonStyle.danger, disabled=not open_))
    if has_ticket and status != "closed":
        view.add_item(ReportButton("close", ticket_id, "Close ticket", discord.ButtonStyle.secondary, disabled=False))
    if not open_ and not (has_ticket and status != "closed"):
        # Keep disabled decision buttons visible on channel-mode resolved reports.
        if decided:
            pass
    return view


class ReportButton(discord.ui.DynamicItem[discord.ui.Button], template=r"report:(?P<action>claim|approve|deny|close):(?P<ticket_id>[0-9]+)"):
    def __init__(self, action: str, ticket_id: int, label: str | None = None, style: discord.ButtonStyle | None = None, *, disabled: bool = False) -> None:
        labels = {"claim": "Claim", "approve": "Approve", "deny": "Deny", "close": "Close ticket"}
        styles = {
            "claim": discord.ButtonStyle.secondary,
            "approve": discord.ButtonStyle.success,
            "deny": discord.ButtonStyle.danger,
            "close": discord.ButtonStyle.secondary,
        }
        self.action = action
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label=label or labels[action],
                style=style or styles[action],
                custom_id=f"report:{action}:{ticket_id}",
                disabled=disabled,
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: object) -> ReportButton:
        return cls(str(match["action"]), int(match["ticket_id"]))  # type: ignore[index]

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: Reports | None = interaction.client.get_cog("Reports")  # type: ignore[assignment]
        if cog is None or interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This report action is unavailable right now.", ephemeral=True)
            return
        await cog.handle_button(interaction, self.action, self.ticket_id)


class ReasonModal(discord.ui.Modal):
    def __init__(self, cog: Reports, *, title: str, ticket_id: int | None = None, message: discord.Message | None = None, target: discord.abc.User | None = None, action: str | None = None) -> None:
        super().__init__(title=title)
        self.cog = cog
        self.ticket_id = ticket_id
        self.message = message
        self.target = target
        self.action = action
        self.reason = discord.ui.TextInput(
            label="Reason (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="Add a reason, or leave this blank.",
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        reason = str(self.reason.value or "").strip() or None
        if self.action in {"approve", "deny"} and self.ticket_id is not None:
            await self.cog.finish_decision(interaction, self.ticket_id, self.action, reason)
            return
        await self.cog.finish_submit(interaction, message=self.message, target=self.target, reason=reason)


class Reports(commands.Cog):
    """Report a message or member to server staff."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        bot.add_dynamic_items(ReportButton)
        self._ctx_menu = app_commands.ContextMenu(name="Report Message", callback=self.context_report)
        bot.tree.add_command(self._ctx_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self._ctx_menu.name, type=self._ctx_menu.type)

    async def context_report(self, interaction: discord.Interaction, message: discord.Message) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This only works in a server.", ephemeral=True)
            return
        block = await self.submit_block_reason(interaction.guild, interaction.user)
        if block:
            await interaction.response.send_message(block, ephemeral=True)
            return
        await interaction.response.send_modal(
            ReasonModal(self, title="Report message", message=message, target=message.author)
        )

    @commands.hybrid_group(name="report", description="Report a message or member to staff.", invoke_without_command=True)
    @commands.guild_only()
    @app_commands.describe(target="Optional member to report.", reason="Why you're reporting them.")
    async def report(self, ctx: commands.Context, target: discord.Member | None = None, *, reason: str | None = None) -> None:
        if ctx.invoked_subcommand is not None:
            return
        assert ctx.guild
        message = None
        if ctx.message and ctx.message.reference:
            ref = ctx.message.reference
            message = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if message is None and ref.message_id and isinstance(ctx.channel, discord.abc.Messageable):
                try:
                    message = await ctx.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    message = None
        if message is not None and target is None:
            target = message.author if isinstance(message.author, discord.Member) else None
            if target is None:
                target_user = message.author
            else:
                target_user = target
        else:
            target_user = target
        if message is None and target_user is None:
            await self._ack(
                ctx,
                make_embed(
                    "How to report",
                    "Reply to a message with `.report [reason]`, use `.report @user [reason]`, "
                    "or right-click a message and choose **Report Message**.",
                    color=DANGER,
                ),
                ephemeral=True,
            )
            return
        block = await self.submit_block_reason(ctx.guild, ctx.author)
        if block:
            await self._ack(ctx, make_embed("Can't report", block, color=DANGER), ephemeral=True)
            return
        if not reason and ctx.interaction is not None:
            await ctx.interaction.response.send_modal(
                ReasonModal(self, title="Submit report", message=message, target=target_user)
            )
            return
        await self.finish_submit(ctx, message=message, target=target_user, reason=reason)

    async def submit_block_reason(self, guild: discord.Guild, user: discord.abc.User) -> str | None:
        settings = await self.bot.db.get_report_settings(guild.id)
        if not int(settings["enabled"] or 0):
            return "Reports are disabled in this server."
        if await self.bot.db.is_report_blocked(guild.id, user.id):
            return "You aren't allowed to send reports in this server."
        last = await self.bot.db.last_report_at(guild.id, user.id)
        if last and time.time() - last < COOLDOWN_SECONDS:
            wait = int(COOLDOWN_SECONDS - (time.time() - last)) + 1
            return f"Please wait **{wait}s** before sending another report."
        open_count = await self.bot.db.count_open_reports(guild.id, user.id)
        if open_count >= MAX_OPEN:
            return f"You already have **{open_count}** open reports. Wait until staff finish one of them."
        if not settings["alert_channel_id"]:
            return "Reports aren't set up yet. Staff need to set a report channel with `.reportsetup alerts #channel`."
        return None

    async def finish_submit(
        self,
        dest: commands.Context | discord.Interaction,
        *,
        message: discord.Message | None,
        target: discord.abc.User | None,
        reason: str | None,
    ) -> None:
        guild = dest.guild
        author = dest.author if isinstance(dest, commands.Context) else dest.user
        if guild is None or not isinstance(author, discord.Member):
            await self._ack(dest, make_embed("Server only", "This only works in a server.", color=DANGER), ephemeral=True)
            return
        block = await self.submit_block_reason(guild, author)
        if block:
            await self._ack(dest, make_embed("Can't report", block, color=DANGER), ephemeral=True)
            return
        settings = await self.bot.db.get_report_settings(guild.id)
        reported = target or (message.author if message is not None else None)
        reporter_id, reporter_name, reporter_avatar = snapshot(author)
        reported_id, reported_name, reported_avatar = snapshot(reported)
        ticket_id = await self.bot.db.create_report_ticket(
            guild.id,
            reporter_id=reporter_id or author.id,
            reporter_name=reporter_name,
            reporter_avatar=reporter_avatar,
            reported_user_id=reported_id,
            reported_name=reported_name,
            reported_avatar=reported_avatar,
            message_link=message.jump_url if message is not None else None,
            message_preview=preview_message(message),
            reason=reason,
        )
        try:
            await self._deliver(guild, settings, ticket_id)
        except Exception:
            log.exception("Failed to deliver report %s in guild %s", ticket_id, guild.id)
            await self._ack(
                dest,
                make_embed(
                    "Couldn't send that report",
                    "I saved the report but couldn't post it for staff. Check my permissions and the report channel.",
                    color=DANGER,
                ),
                ephemeral=True,
            )
            return
        await self._ack(
            dest,
            make_embed("Report sent", "Staff have received your report. Thanks, we'll take a look.", color=SUCCESS),
            ephemeral=True,
            delete_command=True,
        )

    async def _deliver(self, guild: discord.Guild, settings, ticket_id: int) -> None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return
        alert_id = int(settings["alert_channel_id"]) if settings["alert_channel_id"] else None
        alert = guild.get_channel(alert_id) if alert_id else None
        if not isinstance(alert, discord.TextChannel):
            raise RuntimeError("alert channel missing")
        staff_role = guild.get_role(int(settings["staff_role_id"])) if settings["staff_role_id"] else None
        mode = str(settings["mode"] or "channel")
        ticket_channel = None
        if mode == "ticket":
            ticket_channel = await self._create_ticket_channel(guild, settings, row, staff_role)
            embed = build_report_embed(guild, row)
            view = build_report_view(ticket_id, status="open", has_ticket=True)
            panel = await ticket_channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            jump = panel.jump_url
            ping = staff_role.mention if staff_role else None
            notice = make_embed(
                f"New report #{ticket_id}",
                f"A new report was opened. Staff can review it in {ticket_channel.mention}.\n[Open ticket]({jump})",
            )
            announce = await alert.send(content=ping, embed=notice, allowed_mentions=staff_mentions(staff_role))
            await self.bot.db.set_report_panel(
                ticket_id,
                channel_id=ticket_channel.id,
                message_channel_id=ticket_channel.id,
                message_id=panel.id,
                announce_channel_id=alert.id,
                announce_message_id=announce.id,
            )
            return
        embed = build_report_embed(guild, row)
        view = build_report_view(ticket_id, status="open", has_ticket=False)
        ping = staff_role.mention if staff_role else None
        panel = await alert.send(content=ping, embed=embed, view=view, allowed_mentions=staff_mentions(staff_role))
        await self.bot.db.set_report_panel(
            ticket_id, channel_id=None, message_channel_id=alert.id, message_id=panel.id
        )

    async def _create_ticket_channel(self, guild: discord.Guild, settings, row, staff_role: discord.Role | None) -> discord.TextChannel:
        category_id = int(settings["category_id"]) if settings["category_id"] else None
        category = guild.get_channel(category_id) if category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        me = guild.me
        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True,
                attach_files=True, embed_links=True, manage_messages=True,
            )
        reporter = guild.get_member(int(row["reporter_id"]))
        if reporter is not None:
            overwrites[reporter] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True,
            )
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True, manage_messages=True,
            )
        name = f"report-{int(row['id'])}"
        return await guild.create_text_channel(
            name,
            category=category,
            overwrites=overwrites,
            reason=f"Report #{int(row['id'])} from {row['reporter_id']}",
        )

    async def handle_button(self, interaction: discord.Interaction, action: str, ticket_id: int) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        settings = await self.bot.db.get_report_settings(interaction.guild.id)
        if not is_report_staff(interaction.user, settings):
            await interaction.response.send_message("Only staff can use these buttons.", ephemeral=True)
            return
        row = await self.bot.db.get_report_ticket(ticket_id, interaction.guild.id)
        if row is None:
            await interaction.response.send_message("That report no longer exists.", ephemeral=True)
            return
        if action in {"approve", "deny"}:
            if str(row["status"]) != "open":
                await interaction.response.send_message("This report has already been decided.", ephemeral=True)
                return
            title = "Approve report" if action == "approve" else "Deny report"
            await interaction.response.send_modal(ReasonModal(self, title=title, ticket_id=ticket_id, action=action))
            return
        if action == "claim":
            if str(row["status"]) != "open":
                await interaction.response.send_message("This report has already been decided.", ephemeral=True)
                return
            uid, name, avatar = snapshot(interaction.user)
            await self.bot.db.claim_report_ticket(ticket_id, uid or interaction.user.id, name=name, avatar=avatar)
            await self.refresh_panel(interaction.guild, ticket_id)
            await interaction.response.send_message(f"You claimed report #{ticket_id}.", ephemeral=True)
            return
        if action == "close":
            await interaction.response.defer(ephemeral=True)
            await self.close_ticket(interaction.guild, ticket_id, interaction.user)
            await interaction.followup.send("Ticket closed. A summary was sent to the closed-tickets channel, if one is set.", ephemeral=True)

    async def finish_decision(self, interaction: discord.Interaction, ticket_id: int, action: str, reason: str | None) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        row = await self.bot.db.get_report_ticket(ticket_id, interaction.guild.id)
        if row is None or str(row["status"]) != "open":
            await interaction.response.send_message("This report is no longer open.", ephemeral=True)
            return
        status = "approved" if action == "approve" else "denied"
        uid, name, avatar = snapshot(interaction.user)
        if not row["claimed_by"]:
            await self.bot.db.claim_report_ticket(ticket_id, uid or interaction.user.id, name=name, avatar=avatar)
        await self.bot.db.decide_report_ticket(
            ticket_id,
            status=status,
            decided_by=uid or interaction.user.id,
            decided_by_name=name,
            decided_by_avatar=avatar,
            decision_reason=reason,
        )
        await self.notify_reporter(interaction.guild, ticket_id, approved=(status == "approved"), reason=reason)
        await interaction.response.send_message(f"Report #{ticket_id} was {status}.", ephemeral=True)
        await self.archive_report(interaction.guild, ticket_id, interaction.user)

    async def apply_decision(
        self,
        guild: discord.Guild,
        ticket_id: int,
        *,
        status: str,
        actor_id: int,
        actor_name: str | None,
        actor_avatar: str | None,
        reason: str | None,
    ) -> str | None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return "That report was not found."
        if str(row["status"]) != "open":
            return "That report is no longer open."
        if not row["claimed_by"]:
            await self.bot.db.claim_report_ticket(ticket_id, actor_id, name=actor_name, avatar=actor_avatar)
        await self.bot.db.decide_report_ticket(
            ticket_id,
            status=status,
            decided_by=actor_id,
            decided_by_name=actor_name,
            decided_by_avatar=actor_avatar,
            decision_reason=reason,
        )
        await self.notify_reporter(guild, ticket_id, approved=(status == "approved"), reason=reason)
        # Dashboard actor may be a user-like object; archive uses name already stored on the row.
        class _Actor:
            def __init__(self, uid, name):
                self.id = uid
                self._name = name
            def __str__(self):
                return self._name or str(self.id)
        await self.archive_report(guild, ticket_id, _Actor(actor_id, actor_name), actor_name=actor_name, actor_avatar=actor_avatar)
        return None

    async def add_private_note(
        self,
        guild: discord.Guild,
        ticket_id: int,
        *,
        author_id: int,
        author_name: str | None,
        author_avatar: str | None,
        body: str,
    ) -> str | None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return "That report was not found."
        text = body.strip()
        if not text:
            return "Write a comment first."
        await self.bot.db.add_report_note(
            ticket_id,
            guild.id,
            author_id=author_id,
            author_name=author_name,
            author_avatar=author_avatar,
            body=text[:2000],
        )
        return None

    async def refresh_panel(self, guild: discord.Guild, ticket_id: int) -> None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None or not row["message_id"] or not row["message_channel_id"]:
            return
        channel = guild.get_channel(int(row["message_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(row["message_id"]))
        except discord.HTTPException:
            return
        has_ticket = bool(row["channel_id"]) and str(row["status"]) != "closed"
        view = build_report_view(ticket_id, status=str(row["status"]), has_ticket=has_ticket)
        try:
            await message.edit(embed=build_report_embed(guild, row), view=view, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            log.warning("Could not edit report panel %s in guild %s", ticket_id, guild.id)

    async def notify_reporter(self, guild: discord.Guild, ticket_id: int, *, approved: bool, reason: str | None) -> None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return
        verb = "approved" if approved else "denied"
        text = f"Your report in {guild.name} was {verb}."
        if reason:
            text += f"\nReason: {reason}"
        e = make_embed(f"Report {verb}", text, color=SUCCESS if approved else DANGER)
        user = guild.get_member(int(row["reporter_id"]))
        sent = False
        if user is not None:
            sent = await try_dm(user, e)
        if sent:
            return
        # Only fall back where the reporter can already see the channel (a ticket they belong to).
        ticket_id_ch = int(row["channel_id"]) if row["channel_id"] else None
        channel = guild.get_channel(ticket_id_ch) if ticket_id_ch else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"<@{int(row['reporter_id'])}> {text}",
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
                )
            except discord.HTTPException:
                pass

    async def close_ticket(self, guild: discord.Guild, ticket_id: int, actor: discord.abc.User, *, actor_name: str | None = None, actor_avatar: str | None = None) -> str | None:
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return "That report was not found."
        if actor_name is None:
            _, actor_name, actor_avatar = snapshot(actor)
        await self.bot.db.close_report_ticket(
            ticket_id, closed_by=getattr(actor, "id", None), closed_by_name=actor_name, closed_by_avatar=actor_avatar
        )
        await self.archive_report(guild, ticket_id, actor, actor_name=actor_name, actor_avatar=actor_avatar)
        return None

    async def _delete_message(self, guild: discord.Guild, channel_id: int | None, message_id: int | None) -> None:
        if not channel_id or not message_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.delete()
        except discord.HTTPException:
            pass

    async def _ticket_transcript(self, ticket_ch: discord.TextChannel, row) -> io.BytesIO | None:
        lines = [
            f"Ticket #{int(row['id'])} transcript",
            f"Status: {row['status']}",
            f"Reporter: {row['reporter_name'] or row['reporter_id']}",
            f"Reported: {row['reported_name'] or row['reported_user_id']}",
            f"Reason: {row['reason'] or ''}",
            "",
        ]
        try:
            async for msg in ticket_ch.history(limit=500, oldest_first=True):
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {msg.author}: {msg.clean_content}")
        except discord.HTTPException:
            lines.append("(couldn't read the full channel history)")
        return io.BytesIO("\n".join(lines).encode("utf-8"))

    async def archive_report(
        self,
        guild: discord.Guild,
        ticket_id: int,
        actor: discord.abc.User,
        *,
        actor_name: str | None = None,
        actor_avatar: str | None = None,
    ) -> None:
        """Move a decided or closed report to the closed-tickets channel, if configured."""
        row = await self.bot.db.get_report_ticket(ticket_id, guild.id)
        if row is None:
            return
        settings = await self.bot.db.get_report_settings(guild.id)
        closed_id = int(settings["closed_channel_id"]) if settings and settings["closed_channel_id"] else None
        closed = guild.get_channel(closed_id) if closed_id else None
        tickets_id = int(settings["alert_channel_id"]) if settings and settings["alert_channel_id"] else None
        tickets = guild.get_channel(tickets_id) if tickets_id else None
        ticket_ch = guild.get_channel(int(row["channel_id"])) if row["channel_id"] else None
        transcript = None
        if isinstance(ticket_ch, discord.TextChannel):
            transcript = await self._ticket_transcript(ticket_ch, row)
        dest = closed if isinstance(closed, discord.TextChannel) else (tickets if isinstance(tickets, discord.TextChannel) and not isinstance(closed, discord.TextChannel) else None)
        # If a closed channel is set, post the summary there and remove the original.
        # If not, keep the updated panel in the tickets channel (and still send a transcript there on ticket close).
        move = isinstance(closed, discord.TextChannel)
        summary = build_report_embed(guild, row)
        if move:
            dest = closed
        elif transcript is not None and isinstance(tickets, discord.TextChannel):
            dest = tickets
        if isinstance(dest, discord.TextChannel):
            kwargs = {"embed": summary, "allowed_mentions": NO_MENTIONS}
            if transcript is not None:
                transcript.seek(0)
                kwargs["file"] = discord.File(transcript, filename=f"report-{ticket_id}.txt")
            try:
                await dest.send(**kwargs)
            except discord.HTTPException:
                log.warning("Could not post report archive for %s in guild %s", ticket_id, guild.id)
        if move:
            await self._delete_message(guild, row["message_channel_id"], row["message_id"])
            await self._delete_message(guild, row["announce_channel_id"] if "announce_channel_id" in row.keys() else None, row["announce_message_id"] if "announce_message_id" in row.keys() else None)
        else:
            await self.refresh_panel(guild, ticket_id)
        if isinstance(ticket_ch, discord.TextChannel):
            await asyncio.sleep(5)
            try:
                await ticket_ch.delete(reason=f"Report #{ticket_id} archived")
            except discord.HTTPException:
                log.warning("Could not delete ticket channel for report %s", ticket_id)

    async def _ack(
        self,
        dest: commands.Context | discord.Interaction,
        embed: discord.Embed,
        *,
        ephemeral: bool = False,
        delete_command: bool = False,
    ) -> None:
        if isinstance(dest, discord.Interaction):
            if dest.response.is_done():
                await dest.followup.send(embed=embed, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)
            else:
                await dest.response.send_message(embed=embed, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)
            return
        if dest.interaction is not None:
            if dest.interaction.response.is_done():
                await dest.interaction.followup.send(embed=embed, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)
            else:
                await dest.interaction.response.send_message(embed=embed, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)
            return
        if delete_command and dest.message:
            try:
                await dest.message.delete()
            except discord.HTTPException:
                pass
            sent = await try_dm(dest.author, embed)
            if not sent:
                try:
                    notice = await dest.send(embed=embed, allowed_mentions=NO_MENTIONS)
                    await notice.delete(delay=15)
                except discord.HTTPException:
                    pass
            return
        await dest.send(embed=embed, ephemeral=ephemeral, allowed_mentions=NO_MENTIONS)

    @report.command(name="toggle", description="Turn reports on or off for this server.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(state="on or off")
    async def report_toggle(self, ctx: commands.Context, state: str) -> None:
        assert ctx.guild
        choice = state.strip().lower()
        if choice not in {"on", "off", "enable", "disable", "true", "false", "1", "0"}:
            await self._ack(ctx, make_embed("Use on or off", "Try `.report toggle on` or `.report toggle off`.", color=DANGER), ephemeral=True)
            return
        enabled = 1 if choice in {"on", "enable", "true", "1"} else 0
        await self.bot.db.set_report_settings(ctx.guild.id, enabled=enabled)
        if enabled:
            await self._ack(ctx, make_embed("Reports enabled", "Members can use `.report` and the **Report Message** menu. Set the report channel with `.reportsetup alerts #channel` if you haven't already.", color=SUCCESS))
        else:
            await self._ack(ctx, make_embed("Reports disabled", "`.report` will tell members that reports are turned off.", color=SUCCESS))

    @report.command(name="block", description="Stop a member from sending reports.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The member to block.", reason="Why they're blocked.")
    async def report_block(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        assert ctx.guild
        await self.bot.db.block_reporter(ctx.guild.id, member.id, reason=reason, by=ctx.author.id)
        detail = f" Reason: {reason}" if reason else ""
        await self._ack(ctx, make_embed("Reporter blocked", f"{member.mention} can no longer send reports.{detail}", color=SUCCESS))

    @report.command(name="unblock", description="Allow a blocked member to send reports again.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The member to unblock.")
    async def report_unblock(self, ctx: commands.Context, member: discord.Member) -> None:
        assert ctx.guild
        ok = await self.bot.db.unblock_reporter(ctx.guild.id, member.id)
        if not ok:
            await self._ack(ctx, make_embed("Not blocked", f"{member.mention} isn't blocked from reporting.", color=DANGER), ephemeral=True)
            return
        await self._ack(ctx, make_embed("Reporter unblocked", f"{member.mention} can send reports again.", color=SUCCESS))

    @commands.hybrid_group(name="reportsetup", description="Configure how reports are delivered to staff.", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def reportsetup(self, ctx: commands.Context) -> None:
        assert ctx.guild
        settings = await self.bot.db.get_report_settings(ctx.guild.id)
        alert = ctx.guild.get_channel(int(settings["alert_channel_id"])) if settings["alert_channel_id"] else None
        closed = ctx.guild.get_channel(int(settings["closed_channel_id"])) if settings["closed_channel_id"] else None
        category = ctx.guild.get_channel(int(settings["category_id"])) if settings["category_id"] else None
        role = ctx.guild.get_role(int(settings["staff_role_id"])) if settings["staff_role_id"] else None
        mode = "tickets channel" if (settings["mode"] or "channel") == "channel" else "private ticket channel"
        state = "on" if int(settings["enabled"] or 0) else "off"
        await self._ack(
            ctx,
            make_embed(
                "Report settings",
                f"**Feature:** {state}\n"
                f"**Delivery:** {mode}\n"
                f"**Tickets channel:** {alert.mention if isinstance(alert, discord.TextChannel) else 'not set'}\n"
                f"**Closed tickets channel:** {closed.mention if isinstance(closed, discord.TextChannel) else 'not set'}\n"
                f"**Ticket category:** {category.mention if isinstance(category, discord.CategoryChannel) else 'not set'}\n"
                f"**Staff role:** {role.mention if role else 'not set'}\n\n"
                "• `.reportsetup tickets #channel` — where new reports are posted\n"
                "• `.reportsetup closed #channel` — where decided or closed reports go\n"
                "• `.reportsetup category #category` — where ticket channels are created (ticket mode)\n"
                "• `.reportsetup staffrole @role`\n"
                "• `.reportsetup mode channel|ticket`\n"
                "• `.report toggle on|off`",
            ),
        )

    @reportsetup.command(name="tickets", description="Set the tickets channel where new reports are posted or announced.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Channel for new reports. In ticket mode, new tickets are announced here.")
    async def reportsetup_tickets(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        assert ctx.guild
        await self.bot.db.set_report_settings(ctx.guild.id, alert_channel_id=channel.id)
        await self._ack(ctx, make_embed("Tickets channel set", f"New reports will be posted or announced in {channel.mention}.", color=SUCCESS))

    @reportsetup.command(name="alerts", description="Alias for .reportsetup tickets.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Channel for new reports.")
    async def reportsetup_alerts(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self.reportsetup_tickets(ctx, channel)

    @reportsetup.command(name="closed", description="Set the channel where approved, denied, or closed reports are moved.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Closed tickets channel. Omit to clear.")
    async def reportsetup_closed(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        await self.bot.db.set_report_settings(ctx.guild.id, closed_channel_id=channel.id if channel else None)
        if channel:
            await self._ack(ctx, make_embed("Closed tickets channel set", f"When a report is approved, denied or closed, I'll post a summary in {channel.mention} and remove it from the tickets channel.", color=SUCCESS))
        else:
            await self._ack(ctx, make_embed("Closed tickets channel cleared", "Decided reports will stay in the tickets channel unless you set a closed-tickets channel."))

    @reportsetup.command(name="category", description="Set the category used when ticket-channel delivery is on.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(category="Category for private report tickets. Omit to clear.")
    async def reportsetup_category(self, ctx: commands.Context, category: discord.CategoryChannel | None = None) -> None:
        assert ctx.guild
        await self.bot.db.set_report_settings(ctx.guild.id, category_id=category.id if category else None)
        if category:
            await self._ack(ctx, make_embed("Ticket category set", f"Private report tickets will be created under {category.mention} when delivery mode is ticket.", color=SUCCESS))
        else:
            await self._ack(ctx, make_embed("Ticket category cleared", "Tickets will be created without a category until you set one."))

    @reportsetup.command(name="staffrole", description="Set the staff role pinged for new reports.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(role="Staff role to ping and to grant ticket access. Omit to clear.")
    async def reportsetup_staffrole(self, ctx: commands.Context, role: discord.Role | None = None) -> None:
        assert ctx.guild
        await self.bot.db.set_report_settings(ctx.guild.id, staff_role_id=role.id if role else None)
        if role:
            await self._ack(ctx, make_embed("Staff role set", f"I'll ping {role.mention} when a new report arrives.", color=SUCCESS))
        else:
            await self._ack(ctx, make_embed("Staff role cleared", "New reports won't ping a role."))

    @reportsetup.command(name="mode", description="Choose report delivery: staff channel (default) or a private ticket.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(mode="channel (default) or ticket")
    async def reportsetup_mode(self, ctx: commands.Context, mode: str) -> None:
        assert ctx.guild
        choice = mode.strip().lower()
        if choice in {"channel", "staff", "report", "alert"}:
            value = "channel"
        elif choice in {"ticket", "tickets"}:
            value = "ticket"
        else:
            await self._ack(ctx, make_embed("Choose a mode", "Use `.reportsetup mode channel` (default) or `.reportsetup mode ticket`.", color=DANGER), ephemeral=True)
            return
        await self.bot.db.set_report_settings(ctx.guild.id, mode=value)
        if value == "channel":
            await self._ack(ctx, make_embed("Delivery set", "New reports will be posted as an embed in the tickets channel. No private ticket channel is created.", color=SUCCESS))
        else:
            await self._ack(ctx, make_embed("Delivery set", "New reports will open a private ticket channel under the ticket category, and staff will be pinged in the tickets channel.", color=SUCCESS))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Reports(bot))
