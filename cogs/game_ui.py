"""Shared presentation helpers for the drop-in games.

Everything in this module is pure presentation: phase colours, emoji, embed
titles and footers. Game rules, XP awards, channel locking and timeouts stay in
the game classes themselves.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable

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


def countdown_field(seconds_or_end_ts: int) -> tuple[int, str]:
    """Return ``(end_ts, text)`` for a Discord relative-timestamp countdown.

    If the value looks like a unix timestamp (> 100_000_000) it is used as-is;
    otherwise it is treated as seconds from now. The text is
    ``⏳ Ends <t:{end_ts}:R>`` which Discord renders as a live countdown.
    """
    if seconds_or_end_ts > 100_000_000:
        end_ts = seconds_or_end_ts
    else:
        end_ts = math.ceil(time.time()) + max(1, int(seconds_or_end_ts))
    return end_ts, f"⏳ Ends <t:{end_ts}:R>"


def with_countdown(embed: discord.Embed, end_ts: int) -> None:
    """Add or replace the ``Time left`` field on ``embed``.

    Never duplicates the field; if one already exists it is replaced in place.
    """
    text = f"⏳ Ends <t:{end_ts}:R>"
    for i, field in enumerate(embed.fields):
        if field.name == "Time left":
            embed.set_field_at(i, name="Time left", value=text, inline=False)
            return
    embed.add_field(name="Time left", value=text, inline=False)


def clear_countdown(embed: discord.Embed) -> None:
    """Remove the ``Time left`` field from ``embed`` if it exists."""
    for i, field in enumerate(embed.fields):
        if field.name == "Time left":
            embed.remove_field(i)
            return


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


# Almost every game is "1+ players" and short, so the menu only calls out the
# exceptions (e.g. 2 players) inline instead of repeating it on every line.
DEFAULT_PLAYERS = "1+ players"


def game_menu_line(
    emoji: str,
    title: str,
    command: str,
    *,
    players: str = DEFAULT_PLAYERS,
) -> str:
    """One compact menu line: ``🔘 **Button Hunt** · .buttonhunt``.

    A players note is appended only when a game differs from the default, e.g.
    ``⚔️ **Dice Roll Duel** · .diceduel · 2 players``. Duration is never shown.
    """
    line = f"{emoji} **{title}** · {command}"
    if players and players != DEFAULT_PLAYERS:
        line += f" · {players}"
    return line


def games_menu_embed(
    games: list,
    categories: list,
    meta: dict,
    *,
    command_for: Callable[[str], str],
    title: str = "Choose a game to drop",
) -> discord.Embed:
    """Compact ``.games`` menu: one line per game, grouped into category fields.

    ``categories`` is a list of ``{"key", "label", "games"}`` mappings and
    ``meta`` maps a game key to ``{"players": ...}``. No description, footer,
    thumbnail or duration is included; the title and dropdown carry the rest.
    """
    embed = game_embed(title, emoji="🎮", phase="play")
    for cat in categories:
        items = [game for game in games if game[0] in cat["games"]]
        if not items:
            continue
        lines = [
            game_menu_line(
                emoji,
                game_title,
                command_for(key),
                players=meta.get(key, {}).get("players", DEFAULT_PLAYERS),
            )
            for key, emoji, game_title, _blurb in items
        ]
        embed.add_field(name=f"**{cat['label']}**", value="\n".join(lines), inline=False)
    return embed
