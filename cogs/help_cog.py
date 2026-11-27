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
        "• `.mute @user 10m|1h|1d [reason]` / `.unmute @user` — `.timeout` and `.untimeout` still work\n"
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
        "• `.levelup off` / `.levelup #channel` — nothing posted, or post in a channel without pings\n"
        "• `.setlevelchannel #channel` — same as `.levelup #channel`; omit to turn announcements off\n"
        "• `.addxp @user amount` / `.removexp @user amount` — adjust XP (manage server)\n"
        "• `.levelrole add/remove/list` — auto roles at a level (manage roles)",
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
        "• `.role create <name> [#hex1] [#hex2]` — one custom role; two colours make a gradient\n"
        "• `.role create` — open a form for the name and colours\n"
        "• `.role name <new>` / `.role colour <hex>` / `.role gradient #hex1 #hex2` / `.role delete` / `.role info`\n"
        "• `.role toggle on|off` / `.role minlevel <n>` / `.role list` — (manage roles)\n"
        "• `.role give @user @role` — hand your custom role to another member, even if they already own one; staff can give any custom role\n"
        "• `.role take @user` — take your custom role back\n"
        "• `.role restrict @user [reason]` / `.role unrestrict @user`\n"
        "• `.role remove` — delete your own custom role (and take it off anyone you gave it to)\n"
        "• `.role remove @user` — (manage roles) take away their custom role; add `@role` for a normal role\n"
        "• `.role add @user @role` — (manage roles)\n"
        "• `.selfrole add/remove/list/panel` — button panel so members can pick roles\n"
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
        "Fun bot Premium is billed per server.\n"
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
        "Fun",
        "• `.slap @user` — slap someone (tracks count)\n"
        "• `.kiss @user` — kiss someone\n"
        "• `.laugh @user` — laugh at someone\n"
        "• `.boot @user` — kick someone (fun)\n"
        "• `.yeet @user` — yeet someone\n"
        "• `.tickle @user` — tickle someone\n"
        "• `.hug @user` — hug someone\n"
        "• `.dap @user` — dap someone up\n"
        "• `.bonk @user` — bonk someone\n"
        "• `.cuddle @user` — cuddle someone\n"
        "• `.flirt @user` — flirt with someone\n"
        "• `.poke @user` — poke someone\n"
        "• `.airkiss @user` — air kiss someone\n"
        "• `.angrystare @user` — angrily stare at someone\n"
        "• `.bite @user` — bite someone\n"
        "• `.bleh @user` — bleh face at someone\n"
        "• `.celebrate @user` — celebrate with someone\n"
        "• `.cheers @user` — cheers with someone\n"
        "• `.clap @user` — clap for someone\n"
        "• `.confused @user` — look confused at someone\n"
        "• `.cool @user` — look cool with someone\n"
        "• `.cry @user` — cry at someone\n"
        "• `.dance @user` — dance with someone\n"
        "• `.drool @user` — drool at someone\n"
        "• `.evillaugh @user` — evil laugh at someone\n"
        "• `.facepalm @user` — facepalm at someone\n"
        "• `.handhold @user` — hold hands with someone\n"
        "• `.headbang @user` — headbang with someone\n"
        "• `.lick @user` — lick someone\n"
        "• `.mad @user` — get mad at someone\n"
        "• `.nervous @user` — get nervous around someone\n"
        "• `.eat @user` — eat with someone\n"
        "• `.boop @user` — boop someone\n"
        "• `.nyah @user` — nyah at someone\n"
        "• `.pat @user` — pat someone\n"
        "• `.peek @user` — peek at someone\n"
        "• `.pinch @user` — pinch someone\n"
        "• `.pout @user` — pout at someone\n"
        "• `.sad @user` — get sad at someone\n"
        "• `.scared @user` — get scared at someone\n"
        "• `.shout @user` — shout at someone\n"
        "• `.shrug @user` — shrug at someone\n"
        "• `.shy @user` — get shy around someone\n"
        "• `.sigh @user` — sigh at someone\n"
        "• `.sip @user` — sip with someone\n"
        "• `.sleep @user` — sleep with someone\n"
        "• `.slowclap @user` — slow clap for someone\n"
        "• `.smack @user` — smack someone\n"
        "• `.smile @user` — smile at someone\n"
        "• `.sneeze @user` — sneeze at someone\n"
        "• `.sorry @user` — say sorry to someone\n"
        "• `.stare @user` — stare at someone\n"
        "• `.surprised @user` — get surprised at someone\n"
        "• `.sweat @user` — sweat at someone\n"
        "• `.thumbsup @user` — thumbs up someone\n"
        "• `.tired @user` — get tired with someone\n"
        "• `.wave @user` — wave at someone\n"
        "• `.wink @user` — wink at someone\n"
        "• `.woah @user` — say woah at someone\n"
        "• `.yawn @user` — yawn with someone\n"
        "• `.yay @user` — yay with someone\n"
        "• `.yes @user` — say yes to someone",
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
                await ctx.send(embed=make_embed("Unknown command", f"I don't have a command called `{command}`. Try `.help`.", color=DANGER), ephemeral=True)
                return
            usage = f".{cmd.qualified_name}"
            if cmd.signature:
                usage += f" {cmd.signature}"
            desc = cmd.help or cmd.description or "No description."
            e = make_embed(f"Help: .{cmd.qualified_name}", f"{desc}\n\nUsage: `{usage}`", footer=CREDIT)
            if isinstance(cmd, commands.Group) and cmd.commands:
                subs = "\n".join(f"• `.{c.qualified_name}` — {c.description or c.help or '—'}" for c in sorted(cmd.commands, key=lambda c: c.name))
                e.add_field(name="Subcommands", value=subs, inline=False)
            await ctx.send(embed=e)
            return

        e = make_embed(
            "Help",
            "Every command works with a `.` prefix or as a slash command, for example `.games` and `/games`.",
        )
        for title, body in HELP_SECTIONS:
            e.add_field(name=title, value=body, inline=False)
        e.set_footer(text=CREDIT)
        await ctx.send(embed=e)

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
