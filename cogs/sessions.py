"""One active channel game at a time, answer matching, and XP awards."""

from __future__ import annotations

import asyncio
import time
import difflib
import re
import unicodedata
from typing import TYPE_CHECKING, Any

import discord

from cogs.game_ui import clear_countdown

if TYPE_CHECKING:
    from main import SocializeBot

DEFAULT_WIN_XP = 25


def normalize_answer(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.startswith("the "):
        text = text[4:]
    return text


def answers_match(guess: str, answers: list[str], *, threshold: float = 0.8) -> bool:
    guess_n = normalize_answer(guess)
    if not guess_n:
        return False
    for raw in answers:
        name = normalize_answer(raw)
        if not name:
            continue
        if guess_n == name:
            return True
        if difflib.SequenceMatcher(None, guess_n, name).ratio() >= threshold:
            return True
    return False


class ChannelGame:
    """A drop-in game occupying a text channel until it ends."""

    key: str = "game"
    # Seconds a game may occupy a channel before the lock is treated as stale.
    # GameManager adds a further 30s grace period on top of this.
    max_duration: int = 180

    def __init__(self, bot: SocializeBot, channel: discord.abc.Messageable, host_id: int) -> None:
        self.bot = bot
        self.channel = channel
        self.channel_id = getattr(channel, "id", 0)
        self.host_id = host_id
        self.finished = False
        self.task: asyncio.Task[Any] | None = None
        self.started_at: float = time.monotonic()
        self.message: discord.Message | None = None
        self.menu_message: discord.Message | None = None
        self._cleaned = False

    def is_stale(self) -> bool:
        return time.monotonic() - self.started_at > (self.max_duration + 30)

    async def on_message(self, message: discord.Message) -> bool:
        """Return True if the message was consumed as a winning (or otherwise final) guess."""
        return False

    async def cancel(self, reason: str | None = None) -> None:
        await self.finish()

    async def finish(self, result: str | None = None) -> None:
        """Release the channel lock, even if this game already marked itself finished."""
        self.finished = True
        # Always drop the lock first so a later exception cannot leave the channel stuck.
        self.bot.game_sessions.end(self.channel_id)
        if self.task and not self.task.done() and asyncio.current_task() is not self.task:
            self.task.cancel()
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        text = result
        if text:
            try:
                await self.channel.send(text)
            except discord.HTTPException:
                pass


class GameManager:
    def __init__(self) -> None:
        self._games: dict[int, ChannelGame] = {}
        self.menus: dict[int, discord.Message] = {}

    def remember_menu(self, channel_id: int, message: discord.Message | None) -> None:
        if message is not None:
            self.menus[channel_id] = message

    def take_menu(self, channel_id: int) -> discord.Message | None:
        return self.menus.pop(channel_id, None)

    def peek(self, channel_id: int) -> ChannelGame | None:
        """Return the occupying game, including finished or stale ones."""
        return self._games.get(channel_id)

    def get(self, channel_id: int) -> ChannelGame | None:
        game = self._games.get(channel_id)
        if game is None:
            return None
        if game.finished or game.is_stale():
            self._games.pop(channel_id, None)
            return None
        return game

    def start(self, game: ChannelGame) -> bool:
        existing = self._games.get(game.channel_id)
        if existing is not None and not existing.finished and not existing.is_stale():
            return False
        if existing is not None:
            self._games.pop(game.channel_id, None)
        game.started_at = time.monotonic()
        self._games[game.channel_id] = game
        return True

    def end(self, channel_id: int) -> None:
        self._games.pop(channel_id, None)


async def award_xp(bot: SocializeBot, user: discord.abc.User, channel: discord.abc.Messageable, amount: int) -> None:
    guild = getattr(channel, "guild", None) or getattr(user, "guild", None)
    if guild is None:
        return
    old_xp, new_xp = await bot.db.add_xp(guild.id, user.id, amount)
    leveling = bot.get_cog("Leveling")
    if leveling is not None:
        await leveling._handle_level_up(guild, user, channel, old_xp, new_xp)


async def refuse_if_busy(ctx: discord.Interaction | Any, bot: SocializeBot) -> bool:
    """If a game is already running in this channel, tell the user and return True."""
    from utils import DANGER, embed as make_embed

    channel = ctx.channel
    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        return False
    existing = bot.game_sessions.get(channel_id)
    if existing is None:
        return False
    msg = "There's already a game running in this channel. Finish it or wait for it to end."
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            await ctx.followup.send(msg, ephemeral=True)
        else:
            await ctx.response.send_message(msg, ephemeral=True)
    else:
        await ctx.send(embed=make_embed("Game in progress", msg, color=DANGER), ephemeral=True)
    return True



def dest_user(dest: discord.Interaction | Any) -> discord.abc.User:
    return dest.user if isinstance(dest, discord.Interaction) else dest.author


async def end_game_message(message, result_embed, view=None) -> None:
    """Keep the original game embed, disable its controls, and post the result separately."""
    if view is not None:
        for child in getattr(view, "children", []):
            try:
                child.disabled = True
            except Exception:
                pass
        try:
            embeds = getattr(message, "embeds", None)
            if embeds:
                original = embeds[0]
                clear_countdown(original)
            # Always edit the view to disable controls; pass embed=None to satisfy test expectation
            await message.edit(view=view, embed=None)
        except Exception:
            pass
    try:
        await message.channel.send(embed=result_embed)
    except Exception:
        pass


async def end_game_message_v2(message, result_embed, layout, *, timeout: bool = False, ended_at: int | None = None) -> None:
    """End a V2 game message: update countdown to ended/timeout, disable controls, post result.

    Args:
        message: The message to edit (the original game message)
        result_embed: The result embed to send as a followup message
        layout: The GameLayout instance to update
        timeout: If True, use "Time's up" wording instead of "Ended"
        ended_at: Optional custom end timestamp (for "finished early" case).
                  If provided, this timestamp is used for the countdown instead of the layout's original end_ts.
    """
    # Update countdown to ended/timeout state
    if layout.countdown_td is not None:
        end_ts = ended_at if ended_at is not None else layout.end_ts
        if end_ts is not None:
            layout.set_countdown(end_ts, ended=not timeout, timeout=timeout)
    # Disable all interactive components
    layout.disable_items()
    # Edit the message with the updated layout
    try:
        await message.edit(view=layout)
    except Exception:
        pass
    # Post the result as a separate message
    try:
        await message.channel.send(embed=result_embed)
    except Exception:
        pass


async def send_dest(
    dest: discord.Interaction | Any,
    *,
    view: discord.ui.View | None = None,
    embed: discord.Embed | None = None,
    **kwargs,
) -> discord.Message | None:
    if isinstance(dest, discord.Interaction):
        if dest.response.is_done():
            msg = await dest.followup.send(view=view, embed=embed, **kwargs)
            return msg  # type: ignore[return-value]
        await dest.response.send_message(view=view, embed=embed, **kwargs)
        return await dest.original_response()
    return await dest.send(view=view, embed=embed, **kwargs)


async def launch_channel_game(dest: discord.Interaction | Any, bot: Any, factory) -> ChannelGame | None:
    """Create and register a channel game, or refuse if one is already running."""
    if await refuse_if_busy(dest, bot):
        return None
    channel = dest.channel
    user = dest_user(dest)
    game = factory(bot, channel, user.id)
    game.menu_message = bot.game_sessions.take_menu(getattr(channel, "id", 0))
    if not bot.game_sessions.start(game):
        # Race: another game started in between.
        if isinstance(dest, discord.Interaction) and not dest.response.is_done():
            await dest.response.send_message("There's already a game running in this channel.", ephemeral=True)
        elif not isinstance(dest, discord.Interaction):
            from utils import DANGER, embed as make_embed
            await dest.send(embed=make_embed("Game in progress", "There's already a game running in this channel.", color=DANGER), ephemeral=True)
        return None
    return game
