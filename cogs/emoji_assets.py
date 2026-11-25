"""Emoji asset loader: maps custom emoji names to local files and Discord references."""

from __future__ import annotations

from pathlib import Path

EMOJI_DIR = Path(__file__).resolve().parents[1] / "assets" / "emojis"

# name -> local gif file (all downloaded from emoji.gg CDN)
EMOJI_FILES: dict[str, str] = {
    "white": "white.gif",
    "brain": "brain.gif",
    "rainbow": "rainbow.gif",
    "60_sec_timer": "60_sec_timer.gif",
    "chartincreasing": "chartincreasing.gif",
    "spinning_arrow_ball": "spinning_arrow_ball.gif",
    "shuffleparrot": "shuffleparrot.gif",
    "PurpleCity": "PurpleCity.gif",
    "Notebook": "Notebook.gif",
    "verified": "verified.gif",
    "Star": "Star.gif",
    "MinecraftTorch": "MinecraftTorch.gif",
    "wordlesolve": "wordlesolve.gif",
    "BluePortal": "BluePortal.gif",
    "plussign": "plussign.gif",
    "aEarth": "aEarth.gif",
    "speakinghead": "speakinghead.gif",
    "Light": "Light.gif",
    "Sword": "Sword.gif",
    "dollblink": "dollblink.gif",
}


def emoji_path(name: str) -> str | None:
    """Return the local file path for an emoji name, or None if not found."""
    fname = EMOJI_FILES.get(name)
    if fname is None:
        return None
    path = EMOJI_DIR / fname
    return str(path) if path.exists() else None


def emoji_exists(name: str) -> bool:
    """Check whether a local emoji file exists for the given name."""
    return emoji_path(name) is not None


def emoji_discord(name: str, guild_emojis: dict[str, int] | None = None) -> str:
    """Return a Discord-formatted emoji string for the given name.

    If the emoji has been uploaded to the guild (name -> id mapping provided),
    returns ``<a:name:id>`` (animated) or ``<:name:id>``. Otherwise falls back
    to the local file path wrapped as a file:// reference so callers can
    handle it appropriately (e.g. upload to Discord or serve via dashboard).
    """
    if guild_emojis and name in guild_emojis:
        eid = guild_emojis[name]
        return f"<a:{name}:{eid}>"
    path = emoji_path(name)
    if path is not None:
        return f"file://{path}"
    return f":{name}:"


async def upload_emojis_to_guild(bot, guild_id: int) -> dict[str, int]:
    """Upload all local emoji GIFs to a Discord guild as custom emojis.

    Returns {name: emoji_id} for every emoji successfully uploaded or already
    present. Requires the bot to have ``manage_emojis`` permission in the guild.
    """
    import discord

    guild = bot.get_guild(guild_id)
    if guild is None:
        raise ValueError(f"Guild {guild_id} not found in bot's cache.")

    existing = {e.name: e for e in guild.emojis}
    results: dict[str, int] = {}

    for name, fname in EMOJI_FILES.items():
        path = EMOJI_DIR / fname
        if not path.exists():
            continue
        if name in existing:
            results[name] = existing[name].id
            continue
        try:
            with path.open("rb") as f:
                emoji = await guild.create_custom_emoji(name=name, image=f.read(), reason="Fun bot emoji assets")
            results[name] = emoji.id
        except discord.HTTPException:
            pass
    return results


def list_available() -> list[str]:
    """Return all emoji names that have local files."""
    return sorted(EMOJI_FILES.keys())


def all_paths() -> dict[str, str]:
    """Return {name: absolute_path} for every available emoji."""
    out: dict[str, str] = {}
    for name in EMOJI_FILES:
        p = emoji_path(name)
        if p is not None:
            out[name] = p
    return out
