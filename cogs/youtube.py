"""YouTube integration: schedule posts, play embeds, and OAuth auth."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
from typing import TYPE_CHECKING

import aiohttp
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

    async def get_valid_access_token(self, guild_id: int, user_id: int) -> str | None:
        """Get a valid access token, refreshing if needed."""
        row = await self.cog.bot.db.get_youtube_token(user_id, guild_id)
        if not row:
            return None

        access_token = row["access_token"]
        refresh_token = row["refresh_token"]
        expires_at = row["expires_at"]

        # If token is still valid (with 60s buffer), return it
        if expires_at - time.time() > 60:
            return access_token

        # Token expired, refresh it
        client_id = os.getenv("YOUTUBE_CLIENT_ID")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    new_access_token = data["access_token"]
                    new_expires_at = time.time() + data.get("expires_in", 3600)

                    await self.cog.bot.db.save_youtube_token(
                        user_id, guild_id, new_access_token, refresh_token, new_expires_at
                    )
                    return new_access_token
        except Exception:
            return None

    @app_commands.command(name="post", description="Schedule a YouTube video post (opens a form).")
    async def post(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if not await self.cog_enabled(interaction.guild.id):
            await interaction.response.send_message(
                embed=make_embed("Disabled", "YouTube is disabled in this server. Enable it in the dashboard.", color=WARNING),
                ephemeral=True,
            )
            return
        # Check if user has YouTube auth
        token = await self.get_valid_access_token(interaction.guild.id, interaction.user.id)
        if not token:
            await interaction.response.send_message(
                embed=make_embed(
                    "YouTube Not Authenticated",
                    "You need to authenticate with YouTube first. Use `/youtube auth` to get started.",
                    color=WARNING,
                ),
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
        e = discord.Embed(url=f"https://youtu.be/{video_id}", color=COLOR)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="auth", description="Open YouTube authentication login.")
    async def auth(self, interaction: discord.Interaction) -> None:
        client_id = os.getenv("YOUTUBE_CLIENT_ID")
        if not client_id:
            await interaction.response.send_message(
                embed=make_embed(
                    "YouTube Auth Not Configured",
                    "YouTube OAuth client ID is not set. Ask the bot owner to set the `YOUTUBE_CLIENT_ID` environment variable.",
                    color=DANGER,
                ),
                ephemeral=True,
            )
            return
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": client_id,
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
            f"1. [Click here to authenticate with YouTube]({url})\n"
            f"2. Log in and grant permissions\n"
            f"3. Copy the authorization code\n"
            f"4. Run `/youtube auth code:<code>` with the code you received",
            color=COLOR,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="auth_code", description="Complete YouTube auth with the code from Google.")
    @app_commands.describe(code="The authorization code from Google OAuth")
    async def auth_code(self, interaction: discord.Interaction, code: str) -> None:
        assert interaction.guild is not None
        client_id = os.getenv("YOUTUBE_CLIENT_ID")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        if not client_id or not client_secret:
            await interaction.response.send_message(
                embed=make_embed(
                    "YouTube Auth Not Configured",
                    "YouTube OAuth client ID or secret is not set. Ask the bot owner to configure them.",
                    color=DANGER,
                ),
                ephemeral=True,
            )
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                    },
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        await interaction.response.send_message(
                            embed=make_embed(
                                "YouTube Auth Failed",
                                f"Failed to exchange code: {error_text[:200]}",
                                color=DANGER,
                            ),
                            ephemeral=True,
                        )
                        return
                    data = await resp.json()

            access_token = data["access_token"]
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 3600)
            expires_at = time.time() + expires_in

            await self.cog.bot.db.save_youtube_token(
                interaction.user.id, interaction.guild.id, access_token, refresh_token, expires_at
            )

            await interaction.response.send_message(
                embed=make_embed(
                    "YouTube Auth Success",
                    "YouTube authentication complete! You can now schedule posts.",
                    color=SUCCESS,
                ),
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.response.send_message(
                embed=make_embed(
                    "YouTube Auth Failed",
                    f"Error: {str(exc)[:200]}",
                    color=DANGER,
                ),
                ephemeral=True,
            )

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
