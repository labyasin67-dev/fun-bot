"""YouTube integration: schedule posts, play embeds, and OAuth auth."""

from __future__ import annotations

import datetime as _dt
import re
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils import COLOR, DANGER, SUCCESS, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(url: str) -> str | None:
    m = YOUTUBE_URL_RE.search(url.strip())
    return m.group(1) if m else None


class YoutubeScheduleModal(discord.ui.Modal, title="Schedule YouTube Post"):
    def __init__(self, cog: "YoutubeCog") -> None:
        super().__init__()
        self.cog = cog

    video_link = discord.ui.TextInput(
        label="YouTube video link",
        placeholder="https://youtube.com/watch?v=...",
        required=True,
        max_length=200,
    )
    channel = discord.ui.TextInput(
        label="Destination channel (ID or #mention)",
        placeholder="#announcements or 123456789",
        required=True,
        max_length=50,
    )
    scheduled_at = discord.ui.TextInput(
        label="Schedule time (ISO 8601 or seconds from now)",
        placeholder="2026-12-01T20:00:00 or 3600",
        required=True,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        video_id = extract_video_id(self.video_link.value)
        if not video_id:
            await interaction.response.send_message(
                embed=make_embed("Invalid link", "That doesn't look like a YouTube video URL.", color=DANGER),
                ephemeral=True,
            )
            return

        target: discord.TextChannel | None = None
        raw = self.channel.value.strip()
        m = re.match(r"<#(\d+)>", raw)
        if m:
            target = interaction.guild.get_channel(int(m.group(1)))
        elif raw.isdigit():
            target = interaction.guild.get_channel(int(raw))
        if target is None:
            await interaction.response.send_message(
                embed=make_embed("Invalid channel", "Could not resolve that channel.", color=DANGER),
                ephemeral=True,
            )
            return

        raw_time = self.scheduled_at.value.strip()
        try:
            if raw_time.isdigit():
                run_at = time.time() + int(raw_time)
            else:
                run_at = _dt.datetime.fromisoformat(raw_time).timestamp()
        except Exception:
            await interaction.response.send_message(
                embed=make_embed("Invalid time", "Use ISO 8601 (e.g. 2026-12-01T20:00:00) or seconds from now (e.g. 3600).", color=DANGER),
                ephemeral=True,
            )
            return

        if run_at <= time.time():
            await interaction.response.send_message(
                embed=make_embed("Time in the past", "Schedule a time in the future.", color=DANGER),
                ephemeral=True,
            )
            return

        sid = await self.cog.bot.db.add_youtube_schedule(
            interaction.guild.id, target.id, f"https://youtu.be/{video_id}", run_at
        )
        await interaction.response.send_message(
            embed=make_embed(
                "YouTube post scheduled",
                f"Video: https://youtu.be/{video_id}\nChannel: {target.mention}\nTime: <t:{int(run_at)}:F>",
                color=SUCCESS,
            ),
            ephemeral=True,
        )


class YoutubeGroup(app_commands.Group, name="youtube"):
    def __init__(self, cog: "YoutubeCog") -> None:
        super().__init__()
        self.cog = cog

    async def cog_enabled(self, guild_id: int) -> bool:
        return await self.cog.bot.db.is_youtube_enabled(guild_id)

    @app_commands.command(name="post", description="Schedule a YouTube video post (opens a form).")
    async def post(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if not await self.cog_enabled(interaction.guild.id):
            await interaction.response.send_message(
                embed=make_embed("Disabled", "YouTube is disabled in this server. Enable it in the dashboard.", color=WARNING),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(YoutubeScheduleModal(self.cog))

    @app_commands.command(name="embed", description="Play a YouTube video as an embed.")
    @app_commands.describe(link="YouTube video link")
    async def embed(self, interaction: discord.Interaction, link: str) -> None:
        assert interaction.guild is not None
        if not await self.cog_enabled(interaction.guild.id):
            await interaction.response.send_message(
                embed=make_embed("Disabled", "YouTube is disabled in this server. Enable it in the dashboard.", color=WARNING),
                ephemeral=True,
            )
            return
        video_id = extract_video_id(link)
        if not video_id:
            await interaction.response.send_message(
                embed=make_embed("Invalid link", "That doesn't look like a YouTube video URL.", color=DANGER),
                ephemeral=True,
            )
            return
        e = make_embed(
            "YouTube",
            f"https://youtu.be/{video_id}",
            color=COLOR,
            fields=[("Watch", f"https://youtube.com/watch?v={video_id}", False)],
        )
        e.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="auth", description="Open YouTube authentication login.")
    async def auth(self, interaction: discord.Interaction) -> None:
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": "YOUR_YOUTUBE_CLIENT_ID",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.upload",
            "access_type": "offline",
            "prompt": "consent",
        }
        from urllib.parse import urlencode
        url = f"{auth_url}?{urlencode(params)}"
        e = make_embed(
            "YouTube Auth",
            f"[Click here to authenticate with YouTube]({url})\n\nAfter authorising, paste the code back here.",
            color=COLOR,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="scheduled", description="Show scheduled YouTube posts.")
    async def scheduled(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if not await self.cog_enabled(interaction.guild.id):
            await interaction.response.send_message(
                embed=make_embed("Disabled", "YouTube is disabled in this server. Enable it in the dashboard.", color=WARNING),
                ephemeral=True,
            )
            return
        rows = await self.cog.bot.db.list_youtube_schedule(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                embed=make_embed("Scheduled YouTube posts", "No scheduled posts.", color=WARNING),
                ephemeral=True,
            )
            return
        lines = []
        for row in rows:
            ch = interaction.guild.get_channel(int(row["channel_id"]))
            ch_name = ch.name if ch else f"ID {row['channel_id']}"
            lines.append(f"• <t:{int(float(row['scheduled_at']))}:F> — {row['video_url']} in #{ch_name}")
        e = make_embed("Scheduled YouTube posts", "\n".join(lines), color=COLOR)
        await interaction.response.send_message(embed=e, ephemeral=True)


class YoutubeCog(commands.Cog):
    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self.youtube = YoutubeGroup(self)
        self.bot.tree.add_command(self.youtube)

    async def cog_unload(self) -> None:
        pass


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(YoutubeCog(bot))
