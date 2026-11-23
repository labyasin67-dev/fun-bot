"""Help, ping, and command-tree sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

from premium import CREDIT
from cogs.v2 import build_game_layout

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
        "• `.warn @user [reason]` / `.warnings @user` / `.clearwarns @user`\n"
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
        "Roles & welcome",
        "• `.role add/remove @user @role` — (manage roles)\n"
        "• `.selfrole add/remove/list/panel` — button panel so members can pick roles\n"
        "• `.setwelcome #channel [message]` — greet new members\n"
        "  Placeholders: `{mention}` `{user}` `{server}` `{membercount}`\n"
        "• `.welcometest` — preview the welcome message",
    ),
    (
        "Premium",
        "Fun bot Premium is billed per server.\n"
        "• `.premium status` — whether this server is subscribed or granted\n"
        "The bot owner can also use `.premium grant`, `.premium revoke`, and `.premium list`.",
    ),
]


class Help(commands.Cog):
    """Command help and a simple ping."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="help", description="Show bot commands.")
    async def help(self, ctx: commands.Context, command: str | None = None) -> None:
        if command:
            cmd = self.bot.get_command(command.lower())
            if cmd is None:
                await ctx.send(layout=build_game_layout("Unknown command", f"I don't have a command called `{command}`. Try `.help`."))
                return
            usage = f".{cmd.qualified_name}"
            if cmd.signature:
                usage += f" {cmd.signature}"
            desc = cmd.help or cmd.description or "No description."
            body = f"{desc}\n\nUsage: `{usage}`"
            if isinstance(cmd, commands.Group) and cmd.commands:
                subs = "\n".join(f"• `.{c.qualified_name}` — {c.description or c.help or '—'}" for c in sorted(cmd.commands, key=lambda c: c.name))
                body = f"{body}\n\n**Subcommands**\n{subs}"
            body = f"{body}\n\n{CREDIT}"
            await ctx.send(layout=build_game_layout(f"Help: .{cmd.qualified_name}", body))
            return

        body = (
            "Every command works with a `.` prefix or as a slash command, for example `.games` and `/games`."
        )
        for title, body_text in HELP_SECTIONS:
            body = f"{body}\n\n**{title}**\n{body_text}"
        body = f"{body}\n\n{CREDIT}"
        await ctx.send(layout=build_game_layout("Help", body))

    @commands.hybrid_command(name="ping", description="Check that the bot is online.")
    async def ping(self, ctx: commands.Context) -> None:
        latency = round(self.bot.latency * 1000)
        await ctx.send(layout=build_game_layout("Pong", f"Latency: **{latency}ms**."))

    @commands.hybrid_command(name="sync", description="Resync slash commands (bot owner only).")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context) -> None:
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await ctx.send(layout=build_game_layout("Commands synced", f"Synced **{len(synced)}** slash commands.", phase="win"))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Help(bot))

