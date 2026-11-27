"""Shared Components V2 (LayoutView) presentation helpers for the drop-in games.

Everything here is pure presentation: phase colours, emoji, layout structure and
text clipping. Game rules, XP awards, channel locking and timeouts stay in the
game classes themselves.

Components V2 rules (discord.py >= 2.6):
- A V2 message sends ``view=LayoutView`` only. It cannot include ``content`` or
  ``embeds``. discord.py sets the IS_COMPONENTS_V2 flag automatically when a
  LayoutView is sent.
- A message sent as V2 cannot be edited back to v1, and vice versa. Every
  message a game sends and later edits must be V2 from the start.
- At most 40 components in total (nested ones count). TextDisplay content is
  capped at 4000 characters per display (about 4000 across the message).
- Buttons and selects go inside ActionRow (max 5 buttons per row, or one select
  per row; selects cannot be mixed with buttons).
- Relative timestamps ``<t:UNIX:R>`` render inside TextDisplay. This is what the
  live countdown uses.
- Ephemeral messages can be V2 too.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import discord
from discord.components import MediaGalleryItem, SeparatorSpacing, UnfurledMediaItem

from utils import COLOR, DANGER, SUCCESS, WARNING

# --- limits ---
MAX_TEXT_DISPLAY = 4000  # per TextDisplay
MAX_TOTAL_TEXT = 4000    # approximate across the whole message
MAX_COMPONENTS = 40

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
    """Emoji for a game phase, falling back to the play emoji."""
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


def countdown_text(end_ts: int, *, ended: bool = False, timeout: bool = False) -> str:
    """Return the countdown TextDisplay content for a given end timestamp.

    While the game is live: ``⏳ Ends <t:END:R>`` (Discord renders "in N seconds").
    Once the game is over: ``✅ Ended <t:END:R>`` (Discord renders "N seconds ago").
    On timeout: ``⌛ Time's up <t:END:R>``.
    """
    if timeout:
        return f"⌛ Time's up <t:{end_ts}:R>"
    if ended:
        return f"✅ Ended <t:{end_ts}:R>"
    return f"⏳ Ends <t:{end_ts}:R>"


def countdown_field(seconds_or_end_ts: int) -> tuple[int, str]:
    """Return ``(end_ts, text)`` for a Discord relative-timestamp countdown.

    If the value looks like a unix timestamp (> 100_000_000) it is used as-is;
    otherwise it is treated as seconds from now.
    """
    if seconds_or_end_ts > 100_000_000:
        end_ts = seconds_or_end_ts
    else:
        end_ts = int(time.time()) + seconds_or_end_ts
    return end_ts, countdown_text(end_ts)


class GameLayout(discord.ui.LayoutView):
    """A persistent Components V2 layout for a single game message.

    The layout is built once (see :func:`build_game_layout`) and then mutated in
    place via :meth:`set_phase`, :meth:`set_hint`, :meth:`set_countdown` and
    :meth:`disable_items`, after which the caller edits the message with
    ``view=self``.
    """

    def __init__(self, *, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.container: discord.ui.Container = discord.ui.Container(accent_color=COLOR)
        self.add_item(self.container)

        # Child references so the layout can be mutated in place.
        self.title_td: discord.TextDisplay | None = None
        self.body_td: discord.TextDisplay | None = None
        self.countdown_td: discord.TextDisplay | None = None
        self.hint_td: discord.TextDisplay | None = None
        self.section: discord.Section | None = None
        self.media_gallery: discord.MediaGallery | None = None
        self.footer_td: discord.TextDisplay | None = None
        self.action_rows: list[discord.ActionRow] = []
        self._end_ts: int | None = None

    # -- mutation helpers -------------------------------------------------

    def set_phase(self, phase: str) -> None:
        """Change the container accent colour to match the phase."""
        self.container.accent_color = phase_color(phase)

    def set_hint(self, text: str | None) -> None:
        """Replace the hint TextDisplay content (or hide it)."""
        if self.hint_td is None:
            return
        if text is None:
            self.hint_td.content = ""
        else:
            self.hint_td.content = _clip(text, MAX_TEXT_DISPLAY)

    def set_countdown(self, end_ts: int, *, ended: bool = False, timeout: bool = False) -> None:
        """Replace the countdown TextDisplay content (live -> ended/timeout wording)."""
        if self.countdown_td is None:
            return
        self._end_ts = end_ts
        self.countdown_td.content = countdown_text(end_ts, ended=ended, timeout=timeout)

    @property
    def end_ts(self) -> int | None:
        """Return the stored end timestamp, if any."""
        return self._end_ts

    def disable_items(self) -> None:
        """Disable every Button and Select in every ActionRow."""
        for row in self.action_rows:
            for child in row.children:
                if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                    child.disabled = True

    def total_text_length(self) -> int:
        """Approximate total TextDisplay characters across the layout."""
        total = 0
        for td in (
            self.title_td,
            self.body_td,
            self.countdown_td,
            self.hint_td,
            self.footer_td,
        ):
            if td is not None:
                total += len(td.content or "")
        return total


# -- builders ------------------------------------------------------------

def _pack_action_rows(items: Iterable[Any]) -> list[discord.ActionRow]:
    """Pack Button/Select items into ActionRows.

    Rules: max 5 buttons per row; a Select gets its own row and cannot be mixed
    with buttons. Pre-built ActionRow items are passed through unchanged.
    """
    rows: list[discord.ui.ActionRow] = []
    current: discord.ui.ActionRow | None = None
    for item in items:
        if isinstance(item, discord.ui.ActionRow):
            rows.append(item)
            current = None
            continue
        if isinstance(item, discord.ui.Select):
            rows.append(discord.ui.ActionRow(item))
            current = None
            continue
        if isinstance(item, discord.ui.Button):
            if current is None or len(current.children) >= 5:
                current = discord.ui.ActionRow()
                rows.append(current)
            current.add_item(item)
            continue
        # Unknown item type: ignore rather than crash the layout.
    return rows


def build_game_layout(
    title: str,
    body: str,
    *,
    phase: str = "play",
    emoji: str | None = None,
    hint_text: str | None = None,
    countdown: str | None = None,
    image_url: str | None = None,
    host: str | None = None,
    host_avatar: str | None = None,
    footer: str | None = None,
    items: tuple = (),
) -> GameLayout:
    """Build a consistently styled Components V2 game layout.

    Structure (top to bottom): title, body, optional countdown, optional hint,
    optional section with avatar thumbnail, optional media gallery, separator,
    optional footer, optional action rows with buttons/selects.
    """
    layout = GameLayout()
    container = layout.container
    container.accent_color = phase_color(phase)

    resolved_emoji = phase_emoji(phase) if emoji is None else emoji
    styled = _styled_title(title, resolved_emoji)
    layout.title_td = discord.ui.TextDisplay(f"# {_clip(styled, MAX_TEXT_DISPLAY)}")
    container.add_item(layout.title_td)

    layout.body_td = discord.ui.TextDisplay(_clip(body, MAX_TEXT_DISPLAY))
    container.add_item(layout.body_td)

    if countdown is not None:
        layout.countdown_td = discord.ui.TextDisplay(_clip(countdown, MAX_TEXT_DISPLAY))
        container.add_item(layout.countdown_td)

    if hint_text:
        layout.hint_td = discord.ui.TextDisplay(_clip(hint_text, MAX_TEXT_DISPLAY))
        container.add_item(layout.hint_td)

    # Optional section with host/winner avatar thumbnail.
    if host_avatar:
        thumbnail = discord.ui.Thumbnail(UnfurledMediaItem(host_avatar))
        layout.section = discord.ui.Section(accessory=thumbnail)
        container.add_item(layout.section)

    # Optional media gallery (flag, landmark, celebrity images).
    if image_url:
        gallery = discord.ui.MediaGallery(MediaGalleryItem(UnfurledMediaItem(image_url)))
        layout.media_gallery = gallery
        container.add_item(gallery)

    # Separator before the footer/action area.
    container.add_item(discord.ui.Separator(spacing=SeparatorSpacing.small))

    if footer is None and host is not None:
        footer = f"Started by {host}"
    if footer:
        layout.footer_td = discord.ui.TextDisplay(f"-# {_clip(footer, MAX_TEXT_DISPLAY)}")
        container.add_item(layout.footer_td)

    # Action rows with buttons/selects.
    layout.action_rows = _pack_action_rows(items)
    for row in layout.action_rows:
        container.add_item(row)

    return layout


def result_layout(
    game: str,
    description: str,
    *,
    phase: str = "win",
    emoji: str | None = None,
    answer: str | None = None,
    xp: int | None = None,
    play_again: str | None = None,
    winner: str | None = None,
    winner_avatar: str | None = None,
    scoreboard: str | None = None,
    host: str | None = None,
    host_avatar: str | None = None,
    footer: str | None = None,
    items: tuple = (),
) -> GameLayout:
    """Standard end-of-round V2 layout: winner, answer, XP, scoreboard, replay hint.

    All result text is built into the body at construction time; there are no
    mutable hint/countdown fields here because the game is over.
    """
    layout = GameLayout()
    container = layout.container
    container.accent_color = phase_color(phase)

    resolved_emoji = phase_emoji(phase) if emoji is None else emoji
    styled = _styled_title(game, resolved_emoji)
    layout.title_td = discord.ui.TextDisplay(f"# {_clip(styled, MAX_TEXT_DISPLAY)}")
    container.add_item(layout.title_td)

    lines = [description]
    if answer:
        lines.append(f"**Answer:** {answer}")
    if xp is not None:
        lines.append(f"**XP earned:** +{xp} XP")
    if scoreboard:
        lines.append("")
        lines.append(_clip(scoreboard, MAX_TEXT_DISPLAY))
    if play_again:
        lines.append("")
        lines.append(_clip(play_again, MAX_TEXT_DISPLAY))
    layout.body_td = discord.ui.TextDisplay(_clip("\n".join(lines), MAX_TEXT_DISPLAY))
    container.add_item(layout.body_td)

    if winner_avatar:
        thumbnail = discord.ui.Thumbnail(UnfurledMediaItem(winner_avatar))
        layout.section = discord.ui.Section(accessory=thumbnail)
        container.add_item(layout.section)

    container.add_item(discord.ui.Separator(spacing=SeparatorSpacing.small))

    if footer is None and host is not None:
        footer = f"Started by {host}"
    if footer:
        layout.footer_td = discord.ui.TextDisplay(f"-# {_clip(footer, MAX_TEXT_DISPLAY)}")
        container.add_item(layout.footer_td)

    layout.action_rows = _pack_action_rows(items)
    for row in layout.action_rows:
        container.add_item(row)

    return layout


def build_report_layout(
    user: Any,
    assessment: Any,
    *,
    title: str | None = None,
    age_label: str = "",
    accent: int | None = None,
) -> GameLayout:
    """Build a Components V2 report layout for an alt-account check."""
    layout = GameLayout()
    container = layout.container
    container.accent_color = accent if accent is not None else COLOR

    resolved_title = title or f"Alt check — {assessment.verdict}"
    layout.title_td = discord.ui.TextDisplay(f"# {_clip(resolved_title, MAX_TEXT_DISPLAY)}")
    container.add_item(layout.title_td)

    joined = "Unknown"
    if getattr(assessment, "joined_at", None):
        jt = int(assessment.joined_at.timestamp())
        joined = f"<t:{jt}:D> (<t:{jt}:R>)"
    ct = int(assessment.created_at.timestamp())
    lines = [
        f"**User:** {user.mention} `{user}` (`{user.id}`)",
        f"**Account created:** <t:{ct}:D> (<t:{ct}:R>)",
        f"**Joined server:** {joined}",
        f"**Account age:** {age_label}",
        f"**Default avatar:** {'Yes' if assessment.default_avatar else 'No'}",
        f"**Score:** **{assessment.score}**/100 — **{assessment.verdict}**",
    ]
    if assessment.reasons:
        lines.append("")
        lines.append("**Signals**")
        lines.extend(f"• {reason}" for reason in assessment.reasons)
    layout.body_td = discord.ui.TextDisplay(_clip("\n".join(lines), MAX_TEXT_DISPLAY))
    container.add_item(layout.body_td)

    thumbnail = getattr(getattr(user, "display_avatar", None), "url", None)
    if thumbnail:
        section = discord.ui.Section(accessory=discord.ui.Thumbnail(UnfurledMediaItem(thumbnail)))
        layout.section = section
        container.add_item(section)

    return layout
