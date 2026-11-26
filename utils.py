"""Shared helpers for embeds, leveling math, and time formatting."""

from __future__ import annotations

import re

import discord

COLOR = 0x7B5CFA
SUCCESS = 0x3BA55D
DANGER = 0xED4245
WARNING = 0xFEE75C


def embed(title: str | None = None, description: str | None = None, *, color: int = COLOR, footer: str | None = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    if footer:
        e.set_footer(text=footer)
    return e


def level_from_xp(xp: int) -> int:
    """MEE6-style curve: cost(n) = 5n^2 + 50n + 100 to go from n to n+1."""
    level = 0
    remaining = xp
    while remaining >= xp_to_next(level):
        remaining -= xp_to_next(level)
        level += 1
    return level


def xp_to_next(level: int) -> int:
    return 5 * level * level + 50 * level + 100


def xp_for_level(level: int) -> int:
    """Total XP required to reach this level from 0."""
    total = 0
    for n in range(level):
        total += xp_to_next(n)
    return total


def level_progress(xp: int) -> tuple[int, int, int, int]:
    """Return (level, xp_into_level, xp_needed_for_next, total_xp)."""
    level = level_from_xp(xp)
    into = xp - xp_for_level(level)
    needed = xp_to_next(level)
    return level, into, needed, xp


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    if h >= 24:
        d, h2 = divmod(h, 24)
        return f"{d}d {h2}h {m}m"
    return " ".join(parts)


def progress_bar(current: int, maximum: int, size: int = 10) -> str:
    if maximum <= 0:
        filled = size
    else:
        filled = max(0, min(size, round(size * current / maximum)))
    return "█" * filled + "░" * (size - filled)


SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)
NO_MENTIONS = discord.AllowedMentions.none()


USER_ID_RE = re.compile(r"^(?:<@!?(\d{15,20})>|(\d{15,20}))$")


def parse_user_id(raw: str) -> int | None:
    """Accept a raw Discord ID or a mention like <@123>."""
    text = (raw or "").strip()
    match = USER_ID_RE.fullmatch(text)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def resolve_member(guild: discord.Guild, raw: str) -> discord.Member | None:
    """Find a guild member by ID, mention, username, or display name."""
    text = (raw or "").strip()
    if not text:
        return None
    user_id = parse_user_id(text)
    if user_id is not None:
        return guild.get_member(user_id)
    needle = text.lstrip("@").lower()
    exact: list[discord.Member] = []
    partial: list[discord.Member] = []
    for member in guild.members:
        names = {member.name.lower(), member.display_name.lower(), str(member).lower()}
        global_name = getattr(member, "global_name", None)
        if global_name:
            names.add(str(global_name).lower())
        if needle in names:
            exact.append(member)
        elif any(name.startswith(needle) for name in names):
            partial.append(member)
    if len(exact) == 1:
        return exact[0]
    if not exact and len(partial) == 1:
        return partial[0]
    return None
