"""Shared presentation helpers for the drop-in games.

Everything in this module is pure presentation: phase colours, emoji, embed
titles and footers. Game rules, XP awards, channel locking and timeouts stay in
the game classes themselves.
"""

from __future__ import annotations

from typing import Any

import discord

from utils import COLOR, DANGER, SUCCESS, WARNING

# Discord hard limits (kept here so callers and tests share one source).
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_TOTAL = 6000

PHASES = ("play", "hint", "win", "lose", "timeout")

# blurple for play, amber for hint/timeout, green for win, red for lose.
PHASE_COLORS: dict[str, int] = {
    "play": COLOR,
    "hint": WARNING,
    "win": SUCCESS,
    "lose": DANGER,
    "timeout": WARNING,
}

PHASE_EMOJI: dict[str, str] = {
    "play": "🎮",
    "hint": "💡",
    "win": "🏆",
    "lose": "❌",
    "timeout": "⏰",
}


def phase_color(phase: str) -> int:
    """Colour for a game phase, falling back to blurple for unknown phases."""
    return PHASE_COLORS.get(phase, COLOR)


def phase_emoji(phase: str) -> str:
    """Emoji for a game phase, falling back to the game emoji."""
    return PHASE_EMOJI.get(phase, PHASE_EMOJI["play"])


def _clip(text: Any, limit: int) -> str:
    """Clamp text to a Discord limit, adding an ellipsis when it was cut."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _styled_title(title: str, emoji: str | None) -> str:
    title = (title or "").strip()
    if emoji and not title.startswith(emoji):
        return f"{emoji} {title}"
    return title


def game_footer(game: str, host: str | None = None, *, extra: str | None = None) -> str:
    """Standard 'game • extra • Started by host' footer line."""
    parts = [game.strip()] if game and game.strip() else []
    if extra:
        parts.append(extra)
    if host:
        parts.append(f"Started by {host}")
    return " • ".join(parts)


def game_embed(
    title: str,
    description: str | None = None,
    *,
    emoji: str | None = None,
    color: int | None = None,
    phase: str = "play",
    footer: str | None = None,
    host: str | None = None,
    host_avatar: str | None = None,
    thumbnail: str | None = None,
    image: str | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    """Build a consistently styled game embed.

    ``phase`` picks the colour and emoji unless they are given explicitly.
    ``host`` adds the standard "Started by ..." footer and, when an avatar URL
    is supplied, sets it as the embed author icon.
    """
    resolved_color = phase_color(phase) if color is None else color
    if emoji is None:
        emoji = phase_emoji(phase)

    if footer is None and host is not None:
        footer = game_footer(title, host)

    embed = discord.Embed(
        title=_clip(_styled_title(title, emoji), MAX_TITLE) or None,
        description=_clip(description, MAX_DESCRIPTION) or None,
        color=resolved_color,
    )
    if footer is not None:
        embed.set_footer(text=_clip(footer, 2048))
    if host is not None:
        if host_avatar:
            embed.set_author(name=host, icon_url=host_avatar)
        else:
            embed.set_author(name=host)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    for name, value, inline in fields or []:
        embed.add_field(name=_clip(name, MAX_FIELD_NAME), value=_clip(value, MAX_FIELD_VALUE), inline=inline)
    return embed


def result_embed(
    game: str,
    description: str,
    *,
    emoji: str | None = None,
    color: int | None = None,
    phase: str = "win",
    answer: str | None = None,
    xp: int | None = None,
    play_again: str | None = None,
    winner_avatar: str | None = None,
    host: str | None = None,
    host_avatar: str | None = None,
    footer: str | None = None,
) -> discord.Embed:
    """Standard end-of-round embed: winner, answer, XP and a replay hint."""
    lines = [description]
    if answer:
        lines.append(f"**Answer:** {answer}")
    embed = game_embed(
        game,
        "\n".join(lines),
        emoji=emoji,
        color=color,
        phase=phase,
        footer=footer,
        host=host,
        host_avatar=host_avatar,
        thumbnail=winner_avatar,
    )
    if xp is not None:
        embed.add_field(name="XP earned", value=f"+{xp} XP", inline=True)
    if play_again:
        embed.add_field(name="Play again", value=_clip(play_again, MAX_FIELD_VALUE), inline=False)
    return embed