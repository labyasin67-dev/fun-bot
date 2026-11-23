"""Multiplayer UNO drop-in game."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from cogs.game_ui import game_embed, game_footer, result_embed
from cogs.sessions import ChannelGame, award_xp, dest_user, launch_channel_game, send_dest
from utils import WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot

COLORS = ("red", "yellow", "green", "blue")
COLOR_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢", "blue": "🔵"}
KIND_LABEL = {"skip": "Skip", "reverse": "Reverse", "draw2": "+2", "wild": "Wild", "wild4": "Wild +4"}
UNO_XP = 50
TURN_SECONDS = 60
MAX_PLAYERS = 10


def _avatar_url(user: Any) -> str | None:
    avatar = getattr(user, "display_avatar", None)
    return getattr(avatar, "url", None) if avatar is not None else None


@dataclass
class Card:
    color: str | None
    kind: str

    def label(self) -> str:
        if self.kind in ("wild", "wild4"):
            return f"⬛ {KIND_LABEL[self.kind]}"
        return f"{COLOR_EMOJI.get(self.color, '⬛')} {KIND_LABEL.get(self.kind, self.kind)}"

    def playable_on(self, top: "Card", current_color: str, hand: list["Card"] | None = None) -> bool:
        if self.kind == "wild":
            return True
        if self.kind == "wild4":
            if hand is None:
                return True
            return not any(
                other is not self and other.kind != "wild4" and other.playable_on(top, current_color)
                for other in hand
            )
        if self.color == current_color:
            return True
        return self.kind == top.kind and self.kind not in ("wild", "wild4")


def build_deck() -> list[Card]:
    deck: list[Card] = []
    for color in COLORS:
        deck.append(Card(color, "0"))
        for n in range(1, 10):
            deck.extend((Card(color, str(n)), Card(color, str(n))))
        for kind in ("skip", "reverse", "draw2"):
            deck.extend((Card(color, kind), Card(color, kind)))
    deck.extend(Card(None, "wild") for _ in range(4))
    deck.extend(Card(None, "wild4") for _ in range(4))
    random.shuffle(deck)
    return deck


class UnoGame(ChannelGame):
    key = "uno"
    max_duration = 3600

    def __init__(self, bot: SocializeBot, channel: discord.abc.Messageable, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.started = False
        self.players: list[int] = [host_id]
        self.hands: dict[int, list[Card]] = {}
        self.draw_pile: list[Card] = []
        self.discard: list[Card] = []
        self.current_color = "red"
        self.turn_index = 0
        self.direction = 1
        self.uno_pending: int | None = None
        self.uno_called = False
        self.message: discord.Message | None = None
        self.lobby_view: discord.ui.View | None = None
        self.play_view: discord.ui.View | None = None
        self.turn_task: asyncio.Task[Any] | None = None
        self.host_name = "Host"
        self.host_avatar: str | None = None

    @property
    def current_id(self) -> int:
        return self.players[self.turn_index]

    def mention(self, user_id: int) -> str:
        return f"<@{user_id}>"

    def top(self) -> Card:
        return self.discard[-1]

    def reshuffle_if_needed(self) -> None:
        if self.draw_pile:
            return
        if len(self.discard) <= 1:
            self.draw_pile = build_deck()
            return
        top = self.discard.pop()
        self.draw_pile = self.discard
        self.discard = [top]
        random.shuffle(self.draw_pile)

    def draw_cards(self, user_id: int, n: int) -> list[Card]:
        taken: list[Card] = []
        for _ in range(n):
            self.reshuffle_if_needed()
            if not self.draw_pile:
                break
            taken.append(self.draw_pile.pop())
        self.hands.setdefault(user_id, []).extend(taken)
        return taken

    def lobby_embed(self) -> discord.Embed:
        names = "\n".join(f"• {self.mention(uid)}" + (" (host)" if uid == self.host_id else "") for uid in self.players)
        return game_embed(
            "UNO lobby",
            f"2–10 players. The host presses **Start** when you're ready.",
            emoji="🃏",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            footer=game_footer("UNO lobby", self.host_name, extra=f"{len(self.players)}/{MAX_PLAYERS} players"),
            fields=[("Players", names or "None yet", False)],
        )

    def board_embed(self) -> discord.Embed:
        order = self.players if self.direction == 1 else list(reversed(self.players))
        # Show turn order starting at current.
        start = order.index(self.current_id)
        cycle = order[start:] + order[:start]
        arrow = "↓ clockwise" if self.direction == 1 else "↑ counter-clockwise"
        counts = "\n".join(
            f"{'👉 ' if uid == self.current_id else '• '}{self.mention(uid)} — **{len(self.hands.get(uid, []))}** card(s)"
            for uid in cycle
        )
        pending = ""
        if self.uno_pending and not self.uno_called:
            pending = f"\n\n⚠️ {self.mention(self.uno_pending)} has one card and hasn't called UNO!"
        return game_embed(
            "UNO",
            f"Top card: **{self.top().label()}**\nColour in play: {COLOR_EMOJI[self.current_color]}\n"
            f"Current turn: {self.mention(self.current_id)}\nDirection: {arrow}",
            emoji="🃏",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            footer=game_footer("UNO", self.host_name, extra=f"{len(self.players)} players"),
            fields=[("Turn order", counts + pending, False)],
        )

    async def begin(self, dest: commands.Context | discord.Interaction) -> None:
        user = dest_user(dest)
        self.host_name = getattr(user, "display_name", user.name)
        self.host_avatar = _avatar_url(user)
        self.lobby_view = LobbyView(self)
        self.message = await send_dest(dest, embed=self.lobby_embed(), view=self.lobby_view)

    async def refresh(self, interaction: discord.Interaction | None = None, *, view: discord.ui.View | None = None) -> None:
        if self.message is None:
            return
        embed = self.board_embed() if self.started else self.lobby_embed()
        use_view = view if view is not None else (self.play_view if self.started else self.lobby_view)
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=use_view)
            else:
                await self.message.edit(embed=embed, view=use_view)
        except discord.HTTPException:
            pass

    async def add_player(self, interaction: discord.Interaction) -> None:
        if self.started or self.finished:
            await interaction.response.send_message("The game has already started.", ephemeral=True)
            return
        uid = interaction.user.id
        if uid in self.players:
            await interaction.response.send_message("You're already in the lobby.", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message("The lobby is full (10 players).", ephemeral=True)
            return
        self.players.append(uid)
        await self.refresh(interaction)

    async def remove_player(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if uid not in self.players:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        if not self.started:
            if uid == self.host_id and len(self.players) > 1:
                # Host leaves lobby: pass host to next player.
                self.players.remove(uid)
                self.host_id = self.players[0]
            elif uid == self.host_id:
                await interaction.response.edit_message(
                    embed=make_embed("UNO lobby closed", "The host left before the game started.", color=WARNING),
                    view=None,
                )
                if self.lobby_view:
                    self.lobby_view.stop()
                await self.finish(result="UNO lobby closed — the host left.")
                return
            else:
                self.players.remove(uid)
            await self.refresh(interaction)
            return
        # Mid-game leave.
        was_current = uid == self.current_id
        idx = self.players.index(uid)
        self.players.remove(uid)
        self.hands.pop(uid, None)
        if self.uno_pending == uid:
            self.uno_pending = None
        if len(self.players) < 2:
            if self.play_view:
                for child in self.play_view.children:
                    if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                        child.disabled = True
                self.play_view.stop()
            await interaction.response.edit_message(
                embed=make_embed("UNO ended", f"{interaction.user.mention} left, and there aren't enough players to continue.", color=WARNING),
                view=self.play_view,
            )
            self._cancel_turn()
            await self.finish(result=f"UNO ended — {interaction.user.mention} left, and there aren't enough players to continue.")
            return
        if was_current:
            self.turn_index = idx % len(self.players)
            self._open_catch_window_clear()
        elif self.turn_index > idx:
            self.turn_index -= 1
        await self.refresh(interaction)
        if was_current:
            self._arm_turn_timer()

    async def start_game(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
            return
        if len(self.players) < 2:
            await interaction.response.send_message("Need at least 2 players to start.", ephemeral=True)
            return
        if self.started:
            await interaction.response.send_message("It's already started.", ephemeral=True)
            return
        self.started = True
        if self.lobby_view:
            self.lobby_view.stop()
        self.draw_pile = build_deck()
        random.shuffle(self.players)
        for uid in self.players:
            self.hands[uid] = [self.draw_pile.pop() for _ in range(7)]
        first = self.draw_pile.pop()
        while first.kind == "wild4":
            self.draw_pile.append(first)
            random.shuffle(self.draw_pile)
            first = self.draw_pile.pop()
        self.discard = [first]
        if first.kind == "wild":
            self.current_color = random.choice(COLORS)
        else:
            self.current_color = first.color or "red"
        self.turn_index = 0
        # If the first card is an action, apply it.
        if first.kind == "skip":
            self.turn_index = 1 % len(self.players)
        elif first.kind == "reverse":
            self.direction = -1
            self.turn_index = 0
        elif first.kind == "draw2":
            self.draw_cards(self.current_id, 2)
            self.turn_index = 1 % len(self.players)
        self.play_view = PlayView(self)
        await self.refresh(interaction, view=self.play_view)
        self._arm_turn_timer()

    def _cancel_turn(self) -> None:
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = None

    def _arm_turn_timer(self) -> None:
        self._cancel_turn()
        self.turn_task = asyncio.create_task(self._turn_timeout())

    def _open_catch_window_clear(self) -> None:
        self.uno_pending = None
        self.uno_called = False

    async def _turn_timeout(self) -> None:
        try:
            await asyncio.sleep(TURN_SECONDS)
        except asyncio.CancelledError:
            return
        if self.finished or not self.started:
            return
        uid = self.current_id
        self.draw_cards(uid, 1)
        self._open_catch_window_clear()
        self._advance()
        await self.refresh()
        self._arm_turn_timer()

    def _advance(self, steps: int = 1) -> None:
        if not self.players:
            return
        self.turn_index = (self.turn_index + self.direction * steps) % len(self.players)

    async def call_uno(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if not self.started or uid not in self.players:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        if len(self.hands.get(uid, [])) != 1:
            await interaction.response.send_message("You can only call UNO when you have exactly one card.", ephemeral=True)
            return
        self.uno_pending = uid
        self.uno_called = True
        await interaction.response.send_message("UNO!", ephemeral=True)
        await self.refresh()

    async def catch_uno(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if not self.started or uid not in self.players:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        if not self.uno_pending or self.uno_called or self.uno_pending == uid:
            await interaction.response.send_message("There's nobody to catch right now.", ephemeral=True)
            return
        target = self.uno_pending
        self.draw_cards(target, 2)
        self._open_catch_window_clear()
        await interaction.response.send_message(f"Caught {self.mention(target)} — they draw 2.", ephemeral=True)
        await self.refresh()

    async def show_hand(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if not self.started or uid not in self.players:
            await interaction.response.send_message("You're not in this game.", ephemeral=True)
            return
        hand = self.hands.get(uid, [])
        playable = [c for c in hand if c.playable_on(self.top(), self.current_color, hand)]
        lines = [c.label() for c in hand] or ["(no cards)"]
        e = game_embed(
            "Your hand",
            "\n".join(f"• {line}" for line in lines),
            emoji="🃏",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            footer=game_footer("UNO", self.host_name, extra="your hand"),
        )
        if uid != self.current_id:
            e.set_footer(text="It's not your turn — you can look, but you can't play yet.")
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        await interaction.response.send_message(embed=e, view=HandView(self, uid, playable), ephemeral=True)

    async def play_card(self, interaction: discord.Interaction, card: Card) -> None:
        uid = interaction.user.id
        if not self.started or uid != self.current_id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        hand = self.hands.get(uid, [])
        if card not in hand or not card.playable_on(self.top(), self.current_color, hand):
            await interaction.response.send_message("You can't play that card.", ephemeral=True)
            return
        if card.kind in ("wild", "wild4"):
            await interaction.response.send_message(
                "Choose a colour for your wild.",
                view=WildColorView(self, uid, card),
                ephemeral=True,
            )
            return
        await self._apply_play(interaction, uid, card, card.color or self.current_color)

    async def play_wild(self, interaction: discord.Interaction, card: Card, color: str) -> None:
        uid = interaction.user.id
        if uid != self.current_id or card not in self.hands.get(uid, []):
            await interaction.response.send_message("You can't play that now.", ephemeral=True)
            return
        await self._apply_play(interaction, uid, card, color)

    async def _apply_play(self, interaction: discord.Interaction, uid: int, card: Card, color: str) -> None:
        hand = self.hands[uid]
        hand.remove(card)
        if card.kind in ("wild", "wild4"):
            card = Card(None, card.kind)
        self.discard.append(card)
        self.current_color = color
        remaining = len(hand)
        # Catch window: if they now have 1 card, they must call UNO before the next turn.
        if remaining == 1:
            self.uno_pending = uid
            self.uno_called = False
        else:
            self._open_catch_window_clear()
        if remaining == 0:
            self.finished = True
            self._cancel_turn()
            if self.play_view:
                for child in self.play_view.children:
                    if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                        child.disabled = True
                self.play_view.stop()
            await award_xp(self.bot, interaction.user, self.channel, UNO_XP)
            e = result_embed(
                "UNO!",
                f"{interaction.user.mention} played {card.label()} and went out!",
                emoji="🃏",
                phase="win",
                xp=UNO_XP,
                play_again="Start a fresh lobby with `.uno`.",
                winner_avatar=_avatar_url(interaction.user),
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            if not interaction.response.is_done():
                await interaction.response.edit_message(content="You win!", embed=None, view=None)
            if self.message:
                try:
                    await self.message.edit(embed=e, view=self.play_view)
                except discord.HTTPException:
                    pass
            await self.finish(result=f"🏆 {interaction.user.mention} won UNO! (+{UNO_XP} XP)")
            return
        # Action effects.
        if card.kind == "reverse":
            if len(self.players) == 2:
                self._advance(2)
            else:
                self.direction *= -1
                self._advance(1)
        elif card.kind == "skip":
            self._advance(2)
        elif card.kind == "draw2":
            self._advance(1)
            self.draw_cards(self.current_id, 2)
            self._advance(1)
        elif card.kind == "wild4":
            self._advance(1)
            self.draw_cards(self.current_id, 4)
            self._advance(1)
        else:
            self._advance(1)
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=f"Played {card.label()}.", embed=None, view=None)
        else:
            try:
                await interaction.edit_original_response(content=f"Played {card.label()}.", embed=None, view=None)
            except discord.HTTPException:
                pass
        await self.refresh()
        self._arm_turn_timer()

    async def draw_from_hand(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if uid != self.current_id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        taken = self.draw_cards(uid, 1)
        self._open_catch_window_clear()
        if taken and taken[0].playable_on(self.top(), self.current_color, self.hands[uid]):
            await interaction.response.send_message(
                f"You drew {taken[0].label()}. You can play it or keep it.",
                view=DrawnCardView(self, uid, taken[0]),
                ephemeral=True,
            )
            return
        label = taken[0].label() if taken else "nothing"
        self._advance(1)
        await interaction.response.send_message(f"You drew {label}. Your turn is over.", ephemeral=True)
        await self.refresh()
        self._arm_turn_timer()

    async def keep_drawn(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.current_id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        self._advance(1)
        await interaction.response.edit_message(content="Kept the card. Turn passed.", view=None)
        await self.refresh()
        self._arm_turn_timer()


class LobbyView(discord.ui.View):
    def __init__(self, game: UnoGame):
        super().__init__(timeout=300)
        self.game = game

    async def on_timeout(self) -> None:
        if self.game.started or self.game.finished:
            return
        if self.game.message:
            try:
                await self.game.message.edit(embed=make_embed("UNO lobby closed", "The lobby timed out.", color=WARNING), view=None)
            except discord.HTTPException:
                pass
        await self.game.finish(result="⏰ UNO lobby timed out.")

    @discord.ui.button(label="➕ Join", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.add_player(interaction)

    @discord.ui.button(label="▶️ Start", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.start_game(interaction)

    @discord.ui.button(label="🚪 Leave", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.remove_player(interaction)


class PlayView(discord.ui.View):
    def __init__(self, game: UnoGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="🃏 View Hand", style=discord.ButtonStyle.primary)
    async def hand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.show_hand(interaction)

    @discord.ui.button(label="📣 UNO!", style=discord.ButtonStyle.success)
    async def uno(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.call_uno(interaction)

    @discord.ui.button(label="🙋 Catch", style=discord.ButtonStyle.danger)
    async def catch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.catch_uno(interaction)

    @discord.ui.button(label="🚪 Leave", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.remove_player(interaction)


class HandView(discord.ui.View):
    def __init__(self, game: UnoGame, user_id: int, playable: list[Card]):
        super().__init__(timeout=60)
        self.game = game
        self.user_id = user_id
        self.playable = playable
        if playable:
            options = []
            for i, card in enumerate(playable[:25]):
                options.append(discord.SelectOption(label=card.label()[:100], value=str(i)))
            self.add_item(PlaySelect(options))

    @discord.ui.button(label="🃏 Draw", style=discord.ButtonStyle.secondary)
    async def draw(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your hand.", ephemeral=True)
            return
        await self.game.draw_from_hand(interaction)


class PlaySelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Play a card…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, HandView)
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("This isn't your hand.", ephemeral=True)
            return
        idx = int(self.values[0])
        card = view.playable[idx]
        await view.game.play_card(interaction, card)


class WildColorView(discord.ui.View):
    def __init__(self, game: UnoGame, user_id: int, card: Card):
        super().__init__(timeout=30)
        self.game = game
        self.user_id = user_id
        self.card = card
        for color, emoji, style in (
            ("red", "🔴 Red", discord.ButtonStyle.danger),
            ("yellow", "🟡 Yellow", discord.ButtonStyle.secondary),
            ("green", "🟢 Green", discord.ButtonStyle.success),
            ("blue", "🔵 Blue", discord.ButtonStyle.primary),
        ):
            self.add_item(ColorButton(color, emoji, style))


class ColorButton(discord.ui.Button):
    def __init__(self, color: str, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.color = color

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, WildColorView)
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("This isn't your play.", ephemeral=True)
            return
        await view.game.play_wild(interaction, view.card, self.color)


class DrawnCardView(discord.ui.View):
    def __init__(self, game: UnoGame, user_id: int, card: Card):
        super().__init__(timeout=30)
        self.game = game
        self.user_id = user_id
        self.card = card

    @discord.ui.button(label="▶️ Play it", style=discord.ButtonStyle.success)
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your card.", ephemeral=True)
            return
        await self.game.play_card(interaction, self.card)

    @discord.ui.button(label="✋ Keep it", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your card.", ephemeral=True)
            return
        await self.game.keep_drawn(interaction)


class Uno(commands.Cog):
    """Multiplayer UNO."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot

    async def start_lobby(self, dest: commands.Context | discord.Interaction) -> None:
        guild = getattr(dest, "guild", None)
        if guild is not None and not await self.bot.db.is_game_enabled(guild.id, "uno"):
            from cogs.sessions import send_dest
            from utils import DANGER, embed as make_embed
            await send_dest(dest, embed=make_embed("Game disabled", "UNO is disabled in this server.", color=DANGER), ephemeral=True)
            return
        async def factory(bot, channel, host_id):
            return UnoGame(bot, channel, host_id)
        game = await launch_channel_game(dest, self.bot, factory)
        if game is None:
            return
        try:
            await game.begin(dest)
        except Exception:
            await game.finish()
            raise

    @commands.hybrid_command(name="uno", description="Start a multiplayer UNO lobby in this channel.")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def uno(self, ctx: commands.Context) -> None:
        await self.start_lobby(ctx)


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Uno(bot))
