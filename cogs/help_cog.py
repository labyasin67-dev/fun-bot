"""Help, ping, and command-tree sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from premium import CREDIT
from utils import COLOR, DANGER, SUCCESS, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

HELP_SECTIONS = [
    (
        "Games",
        "Drop a game into the channel with `.games` / `/games`, or start one directly.\n"
        "• `.buttonhunt` `.diceduel` `.backwards` `.scramble`\n"
        "• `.celebrity` `.landmark` (`.gtl`) `.pattern` `.capital`\n"
        "• `.redlight` `.missingemoji` `.sequencehunt` `.colorhunt`\n"
        "• `.emojieq` `.flag` `.reaction` `.language` `.word`\n"
        "• `.nickname` `.trivia` `.hilo` `.uno`\n• `.endgame` / `.stopgame` — end the game in this channel",
    ),
    (
        "More",
        "• `.rps [@user]` / `/rps` — rock paper scissors\n"
        "• `.wyr` / `/wyr` — would you rather\n"
        "• `.tod [@user]` / `/tod` — truth or dare\n"
        "• `.truth` / `.dare` — skip the choice and get a prompt\n"
        "• `.eightball` / `.8ball` — ask the 8-ball\n"
        "• `.setcounting #channel` — set a counting channel (manage server)",
    ),
    (
        "Moderation",
        "• `.ban @user [reason]` / `.unban <user_id>`\n"
        "• `.kick @user [reason]`\n"
        "• `.timeout @user 10m|1h|1d [reason]` / `.untimeout @user`\n"
        "• `.mute @user 10m|1h|1d [reason]` / `.unmute @user` — same as `.timeout` / `.untimeout`\n"
        "• `.warn @user [reason]` / `.warnings @user` / `.warn remove @user [id|latest] [reason]` / `.clearwarns @user`\n"
        "• `.purge N` — delete recent messages\n"
        "• `.slowmode <seconds>` — 0 turns it off\n"
        "• `.lock` / `.unlock` `[#channel]`\n"
        "• `.altcheck @user` — account age, score and risk\n"
        "• `.altlist` — recent flagged joins\n"
        "• `.altwhitelist @user` / `.altwhitelist remove @user`\n"
        "• `.altconfig` — log channel, min age, action, quarantine role, on/off",
    ),
    (
        "Channels",
        "• `.setchannel <feature> #channel` — assign a feature (`none` clears it)\n"
        "• `.removechannel games #channel` — remove one games channel\n"
        "• `.channels` — show current assignments\n"
        "Features: `alts`, `modlog`, `levelups`, `welcome`, `games`, `counting`.\n"
        "`.setwelcome`, `.setlevelchannel`, `.setcounting` and `.altconfig channel` stay in sync.",
    ),
    (
        "Levels",
        "Earn XP by chatting (with a short cooldown) and by spending time in voice "
        "with at least one other person, while not AFK or self-deafened.\n"
        "• `.rank [@user]` / `/rank`\n"
        "• `.leaderboard` / `/leaderboard`\n"
        "• `.voicetime [@user]` / `/voicetime`\n"
        "• `.voiceleaderboard` / `/voiceleaderboard`\n"
"• `.setlevelchannel #channel` — where to announce level-ups (manage server)\n"
"• `.levelrole add/remove/list` — auto roles at a level (manage roles)\n"
"• `.addxp @member <amount>`, `.removexp`, `.setxp` — staff XP (manage server)"
    ),
    (
        "Voice",
        "• `.setupjtc` / `/setupjtc` — create or set the Join to Create channel (manage channels)\n"
        "Join that channel to get a personal voice channel, which is deleted when empty.\n"
        "• `.vc lock/unlock/limit/rename/kick/permit/claim` — also available as slash commands\n"
        "A button control panel is posted in the channel's chat.\n"
        "• `.vcstats` / `/vcstats` — how many people are in voice right now",
    ),
    (
        "Roles",
        "• `.role create <name> [#hex1] [#hex2]` — one custom role; two colours make a gradient\n"
        "• `.role create` — open a form for the name and colours\n"
        "• `.role name` / `.role colour` / `.role gradient` / `.role delete` / `.role info`\n"
        "• `.role manage` — hide roles from your `.profile`\n"
        "• `.profile [@user]` — show a member's profile and roles\n"
        "• `.roleremoveme` — drop a custom role someone else gave you\n"
        "• `.role toggle` / `.role minlevel` / `.role list` — (manage roles)\n"
        "• `.role give @user @role` / `.role take @user` — hand over or take back a custom role\n"
        "• `.role restrict @user [reason]` / `.role unrestrict @user`\n"
        "• `.role remove` — delete your own custom role\n"
        "• `.role remove @user [@role]` / `.role add @user @role` — (manage roles)\n"
        "• `.selfrole add/remove/list/panel` — button panel so members can pick roles",
    ),
    (
        "Welcome",
        "• `.setwelcome #channel [message]` — greet new members\n"
        "  Placeholders: `{mention}` `{user}` `{server}` `{membercount}`\n"
        "• `.welcometest` — preview the welcome message",
    ),
    (
        "Reports",
        "• `.report` — reply to a message, or `.report @user [reason]`\n"
        "• Right-click a message → **Report Message**\n"
        "• `.report toggle on|off` — (manage server)\n"
        "• `.reportsetup tickets #channel` — where new reports are posted\n"
        "• `.reportsetup closed #channel` — where approved, denied or closed reports go\n"
        "• `.reportsetup mode channel|ticket` / `.reportsetup category` / `.reportsetup staffrole @role`\n"
        "• `.report block @user [reason]` / `.report unblock @user`\n"
        "Staff can claim, approve or deny a report (optional reason). The reporter is DMed the decision.",
    ),
    (
        "Premium",
        "Meowchi Cafe Premium is billed per server.\n"
        "• `.premium status` — whether this server is subscribed or granted\n"
        "The bot owner can also use `.premium grant`, `.premium revoke`, and `.premium list`.",
    ),
    (
        "YouTube",
        "• `/youtube post` — open a form to schedule a video post\n"
        "• `/youtube embed <link>` — play a YouTube video as an embed\n"
        "• `/youtube auth` — authenticate with YouTube\n"
        "• `/youtube scheduled` — list scheduled posts",
    ),
    (
        "Creator Integration",
        "Post new YouTube uploads in a channel, with an optional @everyone, @here or role ping. Needs Manage Server.\n"
        "• `.creator add <channel link or @handle> #channel [everyone|here|@role|none]`\n"
        "• `.creator list` / `.creator remove <link or #number>`\n"
        "• `.creator message <link or #number> <text>` — placeholders: `{title}` `{url}` `{channel}` `{ping}`\n"
        "• `.creator ping <link or #number> <everyone|here|@role|none>`\n"
        "• `.creator toggle <link or #number> on|off`\n"
        "• `.creator test <link or #number>` — posts the latest video now, without a ping\n"
        "Also on the dashboard under **Creator Integration**. No YouTube login needed.",
    ),
    (
        "Fun",
        "These take `@user` and track how often each action is used.\n"
        "• `.slap` `.kiss` `.laugh` `.boot` `.yeet` `.tickle`\n"
        "• `.hug` `.dap` `.bonk` `.cuddle` `.flirt` `.poke`\n"
        "• `.airkiss` `.angrystare` `.bite` `.bleh` `.celebrate` `.cheers`\n"
        "• `.clap` `.confused` `.cool` `.cry` `.dance` `.drool`\n"
        "• `.evillaugh` `.facepalm` `.handhold` `.headbang` `.lick` `.mad`\n"
        "• `.nervous` `.eat` `.boop` `.nyah` `.pat` `.peek`\n"
        "• `.pinch` `.pout` `.sad` `.scared` `.shout` `.shrug`\n"
        "• `.shy` `.sigh` `.sip` `.sleep` `.slowclap` `.smack`\n"
        "• `.smile` `.sneeze` `.sorry` `.stare` `.surprised` `.sweat`\n"
        "• `.thumbsup` `.tired` `.wave` `.wink` `.woah` `.yawn`\n"
        "• `.yay` `.yes`",
    ),
]



EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_LIMIT = 25
EMBED_TOTAL_LIMIT = 6000
EMBED_NAME_LIMIT = 256


def _chunk_text(text: str, limit: int = EMBED_FIELD_VALUE_LIMIT) -> list[str]:
    text = text or "—"
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return chunks


def _embed_text_len(embed: discord.Embed) -> int:
    total = len(embed.title or "") + len(embed.description or "")
    if embed.footer and embed.footer.text:
        total += len(embed.footer.text)
    if embed.author and embed.author.name:
        total += len(embed.author.name)
    for field in embed.fields:
        total += len(field.name or "") + len(field.value or "")
    return total


def add_help_field(embed: discord.Embed, name: str, value: str, *, inline: bool = False) -> list[tuple[str, str]]:
    """Add a field, splitting values over 1024 characters. Returns leftover (name, value) pairs if the field cap is hit."""
    leftover: list[str] = []
    chunks = _chunk_text(value)
    overflow: list[tuple[str, str]] = []
    for i, chunk in enumerate(chunks):
        label = name if i == 0 else f"{name} (cont.)"
        label = label[:EMBED_NAME_LIMIT]
        if len(embed.fields) >= EMBED_FIELD_LIMIT:
            overflow.append((label, chunk))
            overflow.extend((f"{name} (cont.)"[:EMBED_NAME_LIMIT], c) for c in chunks[i + 1 :])
            break
        # If this field would blow the 6000-character cap, leave it for the next embed.
        projected = _embed_text_len(embed) + len(label) + len(chunk)
        if embed.fields and projected > EMBED_TOTAL_LIMIT:
            overflow.append((label, chunk))
            overflow.extend((f"{name} (cont.)"[:EMBED_NAME_LIMIT], c) for c in chunks[i + 1 :])
            break
        embed.add_field(name=label, value=chunk, inline=inline)
    return overflow


def build_help_embeds(sections: list[tuple[str, str]] | None = None) -> list[discord.Embed]:
    sections = sections if sections is not None else HELP_SECTIONS
    intro = "Every command works with a `.` prefix or as a slash command, for example `.games` and `/games`."
    embeds: list[discord.Embed] = []
    current = make_embed("Help", intro, footer=CREDIT)
    pending: list[tuple[str, str]] = list(sections)
    while pending:
        name, value = pending.pop(0)
        overflow = add_help_field(current, name, value, inline=False)
        if overflow:
            embeds.append(current)
            current = make_embed("Help (continued)", intro, footer=CREDIT)
            pending = overflow + pending
    embeds.append(current)
    return embeds


class Help(commands.Cog):
    """Command help and a simple ping."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="help", description="Show bot commands.")
    async def help(self, ctx: commands.Context, command: str | None = None) -> None:
        if command:
            cmd = self.bot.get_command(command.lower())
            if cmd is None:
                await ctx.send(embed=make_embed("Unknown command", f"I don't have a command called `{command}`. Try `.help`.", color=DANGER), ephemeral=True)
                return
            usage = f".{cmd.qualified_name}"
            if cmd.signature:
                usage += f" {cmd.signature}"
            desc = cmd.help or cmd.description or "No description."
            e = make_embed(f"Help: .{cmd.qualified_name}", f"{desc}\n\nUsage: `{usage}`", footer=CREDIT)
            if isinstance(cmd, commands.Group) and cmd.commands:
                subs = "\n".join(f"• `.{c.qualified_name}` — {c.description or c.help or '—'}" for c in sorted(cmd.commands, key=lambda c: c.name))
                leftover = add_help_field(e, "Subcommands", subs, inline=False)
                if leftover:
                    more = make_embed(f"Help: .{cmd.qualified_name} (continued)", "More subcommands:")
                    for name, value in leftover:
                        add_help_field(more, name, value, inline=False)
                    more.set_footer(text=CREDIT)
                    await ctx.send(embeds=[e, more])
                    return
            await ctx.send(embed=e)
            return

        embeds = build_help_embeds()
        await ctx.send(embeds=embeds)

    @commands.hybrid_command(name="ping", description="Check that the bot is online.")
    async def ping(self, ctx: commands.Context) -> None:
        latency = round(self.bot.latency * 1000)
        await ctx.send(embed=make_embed("Pong", f"Latency: **{latency}ms**."))

    @commands.hybrid_command(name="sync", description="Resync slash commands (bot owner only).")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context) -> None:
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await ctx.send(embed=make_embed("Commands synced", f"Synced **{len(synced)}** slash commands.", color=SUCCESS), ephemeral=True)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Help(bot))
