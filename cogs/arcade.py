"""Drop-in channel games and the .games menu."""

from __future__ import annotations

import asyncio
import html
import random
from typing import TYPE_CHECKING, Any, Callable

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs import banks
from cogs.game_ui import (
    countdown_field,
    game_embed,
    game_footer,
    games_menu_embed,
    result_embed,
)
from cogs.sessions import (
    DEFAULT_WIN_XP,
    ChannelGame,
    answers_match,
    award_xp,
    dest_user,
    end_game_message,
    launch_channel_game,
    normalize_answer,
    send_dest,
)
from utils import DANGER, WARNING, embed as make_embed

if TYPE_CHECKING:
    from main import SocializeBot


def avatar_url(user: Any) -> str | None:
    avatar = getattr(user, "display_avatar", None)
    return getattr(avatar, "url", None) if avatar is not None else None


def host_details(dest: Any, host_id: int) -> tuple[str | None, str | None]:
    """Best-effort display name and avatar URL for the host footer."""
    user = dest_user(dest)
    name = getattr(user, "display_name", None) or getattr(user, "name", None)
    return (name or f"<@{host_id}>"), avatar_url(user)

# key, emoji, title, blurb, command name
MENU_GAMES = [
    ("buttonhunt", "🔘", "Button Hunt", "A grid of buttons — first to hit the right one wins."),
    ("diceduel", ":Sword:", "Dice Roll Duel", "The first two to join roll; highest roll wins."),
    ("backwards", ":spinning-arrow-ball:", "Word Backwards", "Type the word shown, but reversed."),
    ("scramble", ":shuffleparrot:", "Word Scramble", "Unscramble the letters to make a word."),
    ("celebrity", ":star:", "Guess the Celebrity", "Name the famous person in the photo."),
    ("landmark", ":MinecraftTorch:", "Guess the Landmark", "Name the famous landmark in the photo."),
    ("pattern", ":wordlesolve:", "Pattern Puzzle", "Work out the next item in the sequence."),
    ("capital", ":purplecity:", "Capital Scramble", "Unscramble the capital city. Hint: the country."),
    ("redlight", ":dollblink:", "Red Light Green Light", "Type on green to score; typing on red is out."),
    ("missingemoji", ":BluePortal:", "Missing Emoji", "Spot which emoji was removed from the line."),
    ("sequencehunt", ":brain:", "Sequence Hunt", "Remember the order, then tap it back."),
    ("colorhunt", ":rainbow:", "Color Hunt", "Click the colour you're asked for — labels try to trick you."),
    ("emojieq", ":plussign:", "Emoji Equation", "Solve the emoji maths puzzle."),
    ("flag", ":aEarth:", "Flag", "Name the country from its flag."),
    ("reaction", ":60_sec_timer:", "Reaction", "Wait for GO, then be first to click or type."),
    ("language", ":speakinghead:", "Language", "Guess which language the phrase is written in."),
    ("word", ":notebook:", "Word", "Be first to type a word that fits the rule."),
    ("nickname", ":verified:", "Nickname", "Guess the person or team from their nickname."),
    ("trivia", ":Light:", "Trivia", "A multiple-choice question for the channel."),
    ("hilo", ":chartincreasing:", "HILO", "Will the next number be higher or lower?"),
    ("uno", "🃏", "UNO", "Multiplayer UNO for 2–10 players."),
]

# Presentation-only metadata used by the menu. Rules live in the classes below.
MENU_CATEGORIES = [
    {
        "key": "quick",
        "emoji": "⚡",
        "label": "Quick reflex",
        "games": ["buttonhunt", "reaction", "colorhunt", "sequencehunt", "hilo"],
    },
    {
        "key": "word",
        "emoji": "🔤",
        "label": "Word games",
        "games": ["backwards", "scramble", "word", "capital", "nickname"],
    },
    {
        "key": "trivia",
        "emoji": ":brain:",
        "label": "Trivia & knowledge",
        "games": ["celebrity", "landmark", "pattern", "missingemoji", "emojieq", "flag", "language", "trivia"],
    },
    {
        "key": "multi",
        "emoji": "👥",
        "label": "Multiplayer",
        "games": ["diceduel", "redlight", "uno"],
    },
]

# Only games that differ from the default "1+ players" need an entry; the menu
# calls those out inline and never mentions duration.
GAME_META = {
    "diceduel": {"players": "2 players"},
    "uno": {"players": "2–10 players"},
}

MENU_EMOJI = {key: emoji for key, emoji, _title, _blurb in MENU_GAMES}

COLOR_WORD_EMOJI = {"RED": "🟥", "GREEN": "🟩", "BLUE": "🟦", "GREY": "⬜"}


def scramble_word(word: str) -> str:
    letters = list(word)
    for _ in range(20):
        random.shuffle(letters)
        mixed = "".join(letters)
        if mixed.lower() != word.lower():
            return mixed
    return "".join(letters)


def emoji_equal(guess: str, target: str) -> bool:
    def clean(s: str) -> str:
        return s.replace("\uFE0F", "").replace("\uFE0E", "").strip()
    return clean(guess) == clean(target) and bool(clean(guess))


async def get_trivia() -> tuple[str, str, list[str]]:
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://opentdb.com/api.php", params={"amount": 1, "type": "multiple"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results") or []
                    if results:
                        item = results[0]
                        question = html.unescape(item["question"])
                        correct = html.unescape(item["correct_answer"])
                        options = [html.unescape(x) for x in item["incorrect_answers"]] + [correct]
                        random.shuffle(options)
                        return question, correct, options
    except Exception:
        pass
    fallback = [
        {"q": "What is the capital of Australia?", "correct": "Canberra", "wrong": ["Sydney", "Melbourne", "Perth"]},
        {"q": "Which planet is known as the Red Planet?", "correct": "Mars", "wrong": ["Venus", "Jupiter", "Mercury"]},
        {"q": "How many sides does a hexagon have?", "correct": "6", "wrong": ["5", "7", "8"]},
    ]
    item = random.choice(fallback)
    options = item["wrong"] + [item["correct"]]
    random.shuffle(options)
    return item["q"], item["correct"], options


def command_for_title(title: str) -> str:
    for key, _emoji, game_title, _blurb in MENU_GAMES:
        if game_title == title:
            return command_name(key)
    return ".games"


def build_menu_embed(games: list) -> discord.Embed:
    """Compact menu: one line per game, grouped by category."""
    return games_menu_embed(games, MENU_CATEGORIES, GAME_META, command_for=command_name)


class GamesDropMenu(discord.ui.View):
    def __init__(self, cog: "Arcade", games: list | None = None):
        super().__init__(timeout=120)
        self.cog = cog
        self.message: discord.Message | None = None
        self.games = list(games if games is not None else MENU_GAMES)
        self._set_game_options(self.games)

    def _set_game_options(self, games: list) -> None:
        self.select.options = [
            discord.SelectOption(label=title, value=key, emoji=emoji, description=blurb[:100])
            for key, emoji, title, blurb in games
        ]

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.select(placeholder="Choose a game to drop into this channel...")
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await self.cog.drop_game(interaction, select.values[0])


class ChatGuessGame(ChannelGame):
    """A timed 'type the answer in chat' game with an optional mid-round hint."""

    def __init__(
        self,
        bot: SocializeBot,
        channel: discord.abc.Messageable,
        host_id: int,
        *,
        title: str,
        prompt: str,
        answers: list[str],
        reveal: str,
        hint: str | None = None,
        image_url: str | None = None,
        timeout: int = 120,
        hint_at: int | None = 15,
        xp: int = DEFAULT_WIN_XP,
        match: str = "fuzzy",
    ) -> None:
        super().__init__(bot, channel, host_id)
        self.title = title
        self.prompt = prompt
        self.answers = answers
        self.reveal = reveal
        self.hint = hint
        self.image_url = image_url
        self.timeout = timeout
        self.hint_at = hint_at
        self.xp = xp
        self.match = match
        self.message: discord.Message | None = None
        self.hinted = False
        self.seconds_left: int | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _embed(self, *, phase: str, winner: discord.abc.User | None = None) -> discord.Embed:
        emoji = MENU_EMOJI.get(self.title, "🎮")
        if phase == "win" and winner is not None:
            e = result_embed(
                self.title,
                f"{winner.mention} got it!",
                emoji=emoji,
                phase="win",
                answer=self.reveal,
                xp=self.xp,
                play_again=f"Play again with `{command_for_title(self.title)}`.",
                winner_avatar=avatar_url(winner),
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
        elif phase == "timeout":
            e = result_embed(
                self.title,
                "Nobody got it in time.",
                emoji=emoji,
                phase="timeout",
                answer=self.reveal,
                play_again=f"Play again with `{command_for_title(self.title)}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
        else:
            fields = []
            if self.hinted and self.hint:
                fields.append(("💡 Hint", self.hint, False))
            if self.end_ts is not None:
                fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
            e = game_embed(
                self.title,
                self.prompt,
                emoji=emoji,
                phase="hint" if self.hinted else "play",
                host=self.host_name,
                host_avatar=self.host_avatar,
                fields=fields,
            )
        if self.image_url:
            e.set_image(url=self.image_url)
        return e

    def is_correct(self, text: str) -> bool:
        if self.match == "emoji":
            return any(emoji_equal(text, a) for a in self.answers)
        if self.match == "number":
            g = text.strip().replace(",", "")
            return any(g == a or g.lower() == a.lower() for a in self.answers)
        return answers_match(text, self.answers)

    async def refresh(self) -> None:
        if self.message is None or self.finished:
            return
        try:
            await self.message.edit(embed=self._embed(phase="play"))
        except discord.HTTPException:
            pass

    async def begin(self, dest: commands.Context | discord.Interaction) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(self.timeout)
        self.message = await send_dest(dest, embed=self._embed(phase="play"))
        self.task = asyncio.create_task(self._timer())

    async def _timer(self) -> None:
        try:
            for remaining in range(self.timeout, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                if (
                    self.hint
                    and not self.hinted
                    and self.hint_at is not None
                    and remaining <= self.hint_at
                ):
                    self.hinted = True
                await self.refresh()
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            if self.message:
                await end_game_message(self.message, self._embed(phase="timeout"))
            await self.finish(result=f"⏰ Time's up! The answer was **{self.reveal}**.")
        except asyncio.CancelledError:
            return

    async def on_message(self, message: discord.Message) -> bool:
        if self.finished or message.author.bot or not message.content:
            return False
        if message.content.startswith("."):
            return False
        if not self.is_correct(message.content):
            return False
        self.finished = True
        if self.task and not self.task.done():
            self.task.cancel()
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
        await award_xp(self.bot, message.author, message.channel, self.xp)
        if self.message:
            await end_game_message(self.message, self._embed(phase="win", winner=message.author))
        else:
            try:
                await message.channel.send(embed=self._embed(phase="win", winner=message.author))
            except discord.HTTPException:
                pass
        await self.finish(result=f"🏆 {message.author.mention} won {self.title}! Answer: **{self.reveal}** (+{self.xp} XP)")
        return True


class WordRuleGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int, prompt: str, kind: str, payload: str, words: set[str]) -> None:
        super().__init__(bot, channel, host_id)
        self.prompt = prompt
        self.kind = kind
        self.payload = payload
        self.words = words
        self.message: discord.Message | None = None
        self.seconds_left: int | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def valid(self, text: str) -> bool:
        word = normalize_answer(text)
        if not word or " " in word or word not in self.words:
            return False
        if self.kind == "startswith":
            return word.startswith(self.payload)
        if self.kind == "endswith":
            return word.endswith(self.payload)
        if self.kind == "contains":
            return self.payload in word
        if self.kind == "length":
            return len(word) == int(self.payload)
        if self.kind == "startend":
            start, end = self.payload.split("|")
            return word.startswith(start) and word.endswith(end)
        if self.kind == "startlen":
            start, length = self.payload.split("|")
            return word.startswith(start) and len(word) == int(length)
        return False

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.message = await send_dest(dest, embed=self._play_embed())
        self.seconds_left = 120
        self.task = asyncio.create_task(self._timer())

    def _play_embed(self) -> discord.Embed:
        return game_embed(
            "Word",
            f"{self.prompt}\n\nFirst valid English word wins.",
            emoji=":notebook:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=[("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False)] if self.end_ts else [],
        )

    async def _timer(self) -> None:
        try:
            for remaining in range(120, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                if self.message:
                    try:
                        await self.message.edit(embed=self._play_embed())
                    except discord.HTTPException:
                        pass
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            if self.message:
                e = result_embed(
                    "Word",
                    "Nobody found a word that fits.",
                    emoji=":notebook:",
                    phase="timeout",
                    play_again=f"Play again with `{command_for_title('Word')}`.",
                    host=self.host_name,
                    host_avatar=self.host_avatar,
                )
                await end_game_message(self.message, e)
            await self.finish(result="⏰ Time's up! Nobody found a word that fits.")
        except asyncio.CancelledError:
            return

    async def on_message(self, message: discord.Message) -> bool:
        if self.finished or message.author.bot or not message.content or message.content.startswith("."):
            return False
        if not self.valid(message.content):
            return False
        self.finished = True
        if self.task and not self.task.done():
            self.task.cancel()
        word = normalize_answer(message.content)
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
        await award_xp(self.bot, message.author, message.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Word",
            f"{message.author.mention} played **{word}**",
            emoji=":notebook:",
            phase="win",
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Word')}`.",
            winner_avatar=avatar_url(message.author),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        if self.message:
            await end_game_message(self.message, e)
        await self.finish(result=f"🏆 {message.author.mention} won Word! Answer: **{word}** (+{DEFAULT_WIN_XP} XP)")
        return True


class ButtonHuntView(discord.ui.View):
    def __init__(self, game: "ButtonHuntGame", *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.game = game
        winner_index = random.randrange(20)
        for i in range(20):
            self.add_item(HuntButton(i, i == winner_index, row=i // 5))

    async def on_timeout(self) -> None:
        await self.game.timed_out()


class HuntButton(discord.ui.Button):
    def __init__(self, index: int, correct: bool, row: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=str(index + 1), row=row)
        self.correct = correct

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.view.game  # type: ignore[union-attr]
        assert isinstance(game, ButtonHuntGame)
        if game.finished:
            await interaction.response.send_message("This round is over.", ephemeral=True)
            return
        if interaction.user.id in game.eliminated:
            await interaction.response.send_message("You're already out of this round.", ephemeral=True)
            return
        if not self.correct:
            game.eliminated.add(interaction.user.id)
            await interaction.response.send_message("Not that one — you're out!", ephemeral=True)
            await game.refresh()
            return
        await game.win(interaction)


class ButtonHuntGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.eliminated: set[int] = set()
        self.message: discord.Message | None = None
        self.view: ButtonHuntView | None = None
        self.seconds_left: int | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _embed(self) -> discord.Embed:
        fields = []
        if self.eliminated:
            count = len(self.eliminated)
            fields.append(("Eliminated", f"{count} player{'s' if count != 1 else ''} out", True))
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "Button Hunt",
            "One of these buttons is the winner. First to press it wins. A wrong press puts you out.",
            emoji="🔘",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def refresh(self) -> None:
        if self.message is None or self.finished:
            return
        try:
            await self.message.edit(embed=self._embed(), view=self.view)
        except discord.HTTPException:
            pass

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.view = ButtonHuntView(self, timeout=120)  # backstop; the countdown drives the actual timeout
        self.message = await send_dest(dest, embed=self._embed(), view=self.view)
        self.task = asyncio.create_task(self._countdown())

    async def _countdown(self) -> None:
        try:
            for remaining in range(120, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                await self.refresh()
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            await self.timed_out()
        except asyncio.CancelledError:
            return

    async def win(self, interaction: discord.Interaction) -> None:
        if self.finished:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
                    if getattr(child, "correct", False):
                        child.style = discord.ButtonStyle.success
            self.view.stop()
        await award_xp(self.bot, interaction.user, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Button Hunt",
            f"{interaction.user.mention} found the right button!",
            emoji="🔘",
            phase="win",
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Button Hunt')}`.",
            winner_avatar=avatar_url(interaction.user),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        await interaction.response.defer()
        await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {interaction.user.mention} won Button Hunt! (+{DEFAULT_WIN_XP} XP)")

    async def timed_out(self) -> None:
        if self.finished:
            return
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
        if self.message:
            e = result_embed(
                "Button Hunt",
                "Nobody found the right button.",
                emoji="🔘",
                phase="timeout",
                play_again=f"Play again with `{command_for_title('Button Hunt')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await end_game_message(self.message, e, self.view)
        await self.finish(result="⏰ Time's up! Nobody found the right button.")


class DiceJoinView(discord.ui.View):
    def __init__(self, game: "DiceDuelGame"):
        super().__init__(timeout=120)
        self.game = game

    async def on_timeout(self) -> None:
        await self.game.timed_out()

    @discord.ui.button(label="🎲 Join", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.join(interaction)


class DiceDuelGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.players: list[discord.abc.User] = []
        self.message: discord.Message | None = None
        self.view: DiceJoinView | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _embed(self) -> discord.Embed:
        remaining = max(0, 2 - len(self.players))
        extra = f"Waiting for {remaining} more player{'s' if remaining != 1 else ''}" if remaining else "Rolling…"
        roster = "\n".join(f"• {player.mention}" for player in self.players) or "Waiting for players…"
        fields = [("Players", roster, False)]
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "Dice Roll Duel",
            "First two players to join will each roll a d6. Highest roll wins.",
            emoji=":Sword:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            footer=game_footer("Dice Roll Duel", self.host_name, extra=extra),
            fields=fields,
        )

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.view = DiceJoinView(self)
        self.message = await send_dest(dest, embed=self._embed(), view=self.view)

    async def join(self, interaction: discord.Interaction) -> None:
        if self.finished:
            await interaction.response.send_message("This duel has already started or ended.", ephemeral=True)
            return
        if any(p.id == interaction.user.id for p in self.players):
            await interaction.response.send_message("You're already in.", ephemeral=True)
            return
        self.players.append(interaction.user)
        if len(self.players) < 2:
            await interaction.response.edit_message(embed=self._embed(), view=self.view)
            return
        await interaction.response.defer()
        await self.resolve()

    async def resolve(self) -> None:
        if self.finished or len(self.players) < 2:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.view.stop()
        a, b = self.players[0], self.players[1]
        while True:
            ra, rb = random.randint(1, 6), random.randint(1, 6)
            if ra != rb:
                break
        winner, loser, wr, lr = (a, b, ra, rb) if ra > rb else (b, a, rb, ra)
        await award_xp(self.bot, winner, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Dice Roll Duel",
            f"{a.mention} rolled **{ra}**.\n{b.mention} rolled **{rb}**.\n\n{winner.mention} wins!",
            emoji=":Sword:",
            phase="win",
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Dice Roll Duel')}`.",
            winner_avatar=avatar_url(winner),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        if self.message:
            await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {winner.mention} won Dice Roll Duel! {wr}–{lr} (+{DEFAULT_WIN_XP} XP)")

    async def timed_out(self) -> None:
        if self.finished:
            return
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
        if self.message:
            e = result_embed(
                "Dice Roll Duel",
                "Not enough players joined.",
                emoji=":Sword:",
                phase="timeout",
                play_again=f"Play again with `{command_for_title('Dice Roll Duel')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await end_game_message(self.message, e, self.view)
        await self.finish(result="⏰ Dice Roll Duel ended — not enough players joined.")


class ColorHuntView(discord.ui.View):
    def __init__(self, game: "ColorHuntGame", *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.game = game
        styles = [
            ("RED", discord.ButtonStyle.danger),
            ("GREEN", discord.ButtonStyle.success),
            ("BLUE", discord.ButtonStyle.primary),
            ("GREY", discord.ButtonStyle.secondary),
        ]
        labels = ["RED", "GREEN", "BLUE", "GREY"]
        random.shuffle(labels)
        # Target is a style; labels are shuffled so they often lie.
        self.target_name, self.target_style = random.choice(styles)
        for i, ((true_name, style), label) in enumerate(zip(styles, labels)):
            display = f"{COLOR_WORD_EMOJI.get(label, '🔘')} {label}"
            self.add_item(ColorHuntButton(style, display, style == self.target_style))

    async def on_timeout(self) -> None:
        await self.game.timed_out()


class ColorHuntButton(discord.ui.Button):
    def __init__(self, style: discord.ButtonStyle, label: str, correct: bool):
        super().__init__(style=style, label=label)
        self.correct = correct

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.view.game  # type: ignore[union-attr]
        assert isinstance(game, ColorHuntGame)
        if game.finished:
            await interaction.response.send_message("This round is over.", ephemeral=True)
            return
        if interaction.user.id in game.eliminated:
            await interaction.response.send_message("You're already out of this round.", ephemeral=True)
            return
        if not self.correct:
            game.eliminated.add(interaction.user.id)
            await interaction.response.send_message("That's the wrong button — you're out!", ephemeral=True)
            await game.refresh()
            return
        await game.win(interaction)


class ColorHuntGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.eliminated: set[int] = set()
        self.message: discord.Message | None = None
        self.view: ColorHuntView | None = None
        self.seconds_left: int | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _embed(self) -> discord.Embed:
        target = self.view.target_name if self.view else "?"
        fields = []
        if self.eliminated:
            count = len(self.eliminated)
            fields.append(("Eliminated", f"{count} player{'s' if count != 1 else ''} out", True))
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "Color Hunt",
            f"Click the **{target}** button.\nThat's the actual button colour, not the word written on it.",
            emoji=":rainbow:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def refresh(self) -> None:
        if self.message is None or self.finished:
            return
        try:
            await self.message.edit(embed=self._embed(), view=self.view)
        except discord.HTTPException:
            pass

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.view = ColorHuntView(self, timeout=120)  # backstop; the countdown drives the actual timeout
        self.message = await send_dest(dest, embed=self._embed(), view=self.view)
        self.task = asyncio.create_task(self._countdown())

    async def _countdown(self) -> None:
        try:
            for remaining in range(120, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                await self.refresh()
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            await self.timed_out()
        except asyncio.CancelledError:
            return

    async def win(self, interaction: discord.Interaction) -> None:
        if self.finished:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.view.stop()
        await award_xp(self.bot, interaction.user, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Color Hunt",
            f"{interaction.user.mention} clicked the right colour!",
            emoji=":rainbow:",
            phase="win",
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Color Hunt')}`.",
            winner_avatar=avatar_url(interaction.user),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        await interaction.response.defer()
        await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {interaction.user.mention} won Color Hunt! (+{DEFAULT_WIN_XP} XP)")

    async def timed_out(self) -> None:
        if self.finished:
            return
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
        if self.message:
            e = result_embed(
                "Color Hunt",
                "Nobody clicked the right colour.",
                emoji=":rainbow:",
                phase="timeout",
                play_again=f"Play again with `{command_for_title('Color Hunt')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await end_game_message(self.message, e, self.view)
        await self.finish(result="⏰ Time's up! Nobody clicked the right colour.")


class ReactionView(discord.ui.View):
    def __init__(self, game: "ReactionGame"):
        super().__init__(timeout=120)
        self.game = game

    @discord.ui.button(label="⏳ Wait…", style=discord.ButtonStyle.secondary, disabled=False)
    async def click(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.on_click(interaction)


# How many seconds the Reaction button stays live after it flips to GO!.
REACTION_LIVE_SECONDS = 120


class ReactionGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.live = False
        self.eliminated: set[int] = set()
        self.message: discord.Message | None = None
        self.view: ReactionView | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None
        self.seconds_left: int | None = None
        self.end_ts: int | None = None

    def _embed(self, *, live: bool = False) -> discord.Embed:
        fields = []
        if self.eliminated:
            count = len(self.eliminated)
            fields.append(("Eliminated", f"{count} player{'s' if count != 1 else ''} out", True))
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        if live:
            left = f"{self.seconds_left}s left" if self.seconds_left is not None else "GO!"
            description = f"**GO!** First to click the button or type `go` wins.\n{left}"
        else:
            description = "Wait for it…\nDon't click or type **go** until the message says **GO!**"
        return game_embed(
            "Reaction",
            description,
            emoji=":60_sec_timer:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def refresh(self) -> None:
        if self.message is None or self.finished:
            return
        try:
            await self.message.edit(embed=self._embed(live=self.live), view=self.view)
        except discord.HTTPException:
            pass

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        wait_seconds = random.uniform(2.5, 6.5)
        self.wait_seconds = wait_seconds
        self.end_ts, _ = countdown_field(int(wait_seconds))
        self.view = ReactionView(self)
        self.message = await send_dest(dest, embed=self._embed(), view=self.view)
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self.wait_seconds)
            if self.finished:
                return
            self.live = True
            self.end_ts, _ = countdown_field(REACTION_LIVE_SECONDS)
            if self.view:
                for child in self.view.children:
                    if isinstance(child, discord.ui.Button):
                        child.label = "🏁 GO!"
                        child.style = discord.ButtonStyle.success
            if self.message and self.view:
                try:
                    await self.message.edit(embed=self._embed(live=True), view=self.view)
                except discord.HTTPException:
                    pass
            for remaining in range(REACTION_LIVE_SECONDS, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                await self.refresh()
                if remaining > 0:
                    await asyncio.sleep(1)
            self.seconds_left = None
            if not self.finished:
                if self.view:
                    for child in self.view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    self.view.stop()
                if self.message:
                    e = result_embed(
                        "Reaction",
                        "Nobody reacted in time.",
                        emoji=":60_sec_timer:",
                        phase="timeout",
                        play_again=f"Play again with `{command_for_title('Reaction')}`.",
                        host=self.host_name,
                        host_avatar=self.host_avatar,
                    )
                    await end_game_message(self.message, e, self.view)
                await self.finish(result="⏰ Too slow! Nobody reacted in time.")
        except asyncio.CancelledError:
            return

    async def on_click(self, interaction: discord.Interaction) -> None:
        if self.finished:
            await interaction.response.send_message("This round is over.", ephemeral=True)
            return
        if interaction.user.id in self.eliminated:
            await interaction.response.send_message("You jumped early, so you're out.", ephemeral=True)
            return
        if not self.live:
            self.eliminated.add(interaction.user.id)
            await interaction.response.send_message("Too early — you're out!", ephemeral=True)
            await self.refresh()
            return
        await self.win(interaction.user, interaction)

    async def win(self, user: discord.abc.User, interaction: discord.Interaction | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.view.stop()
        if self.task and not self.task.done():
            self.task.cancel()
        await award_xp(self.bot, user, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Reaction",
            f"{user.mention} was first!",
            emoji=":60_sec_timer:",
            phase="win",
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Reaction')}`.",
            winner_avatar=avatar_url(user),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        if interaction is not None:
            await interaction.response.defer()
        if self.message:
            await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {user.mention} won Reaction! (+{DEFAULT_WIN_XP} XP)")

    async def on_message(self, message: discord.Message) -> bool:
        if self.finished or message.author.bot:
            return False
        if normalize_answer(message.content) not in {"go", "click"}:
            return False
        if message.author.id in self.eliminated:
            return False
        if not self.live:
            self.eliminated.add(message.author.id)
            try:
                await message.add_reaction("❌")
            except discord.HTTPException:
                pass
            await self.refresh()
            return False
        await self.win(message.author)
        return True


class SequenceHuntView(discord.ui.View):
    EMOJIS = ["🔴", ":dollblink:", "🔵", "🟡"]

    def __init__(self, game: "SequenceHuntGame", enabled: bool, *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.game = game
        for i, emoji in enumerate(self.EMOJIS):
            self.add_item(SequenceButton(i, emoji, enabled))

    async def on_timeout(self) -> None:
        await self.game.timed_out()


class SequenceButton(discord.ui.Button):
    def __init__(self, index: int, emoji: str, enabled: bool):
        super().__init__(style=discord.ButtonStyle.secondary, emoji=emoji, disabled=not enabled)
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.view.game  # type: ignore[union-attr]
        assert isinstance(game, SequenceHuntGame)
        await game.press(interaction, self.index)


class SequenceHuntGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        length = random.randint(4, 5)
        self.sequence = [random.randrange(4) for _ in range(length)]
        self.progress: dict[int, int] = {}
        self.failed: set[int] = set()
        self.accepting = False
        self.message: discord.Message | None = None
        self.view: SequenceHuntView | None = None
        self.seconds_left: int | None = None
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _seq_text(self) -> str:
        return " ".join(SequenceHuntView.EMOJIS[i] for i in self.sequence)

    def _embed(self, *, show_sequence: bool) -> discord.Embed:
        fields = []
        if self.failed:
            count = len(self.failed)
            fields.append(("Out", f"{count} player{'s' if count != 1 else ''} out", True))
        if show_sequence:
            description = f"Remember this order:\n\n# {self._seq_text()}"
        else:
            description = "Repeat the sequence by pressing the buttons in order. First to finish wins."
            if self.end_ts is not None:
                fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "Sequence Hunt",
            description,
            emoji=":brain:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def refresh(self) -> None:
        if self.message is None or self.finished:
            return
        try:
            await self.message.edit(embed=self._embed(show_sequence=False), view=self.view)
        except discord.HTTPException:
            pass

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        preview = SequenceHuntView(self, enabled=False, timeout=None)  # replaced after the preview
        self.message = await send_dest(dest, embed=self._embed(show_sequence=True), view=preview)
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await asyncio.sleep(3)
            if self.finished:
                return
            self.accepting = True
            self.end_ts, _ = countdown_field(120)
            self.view = SequenceHuntView(self, enabled=True, timeout=120)  # backstop; the countdown drives the actual timeout
            if self.message:
                try:
                    await self.message.edit(embed=self._embed(show_sequence=False), view=self.view)
                except discord.HTTPException:
                    pass
            await self._countdown()
        except asyncio.CancelledError:
            return

    async def _countdown(self) -> None:
        try:
            for remaining in range(120, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                await self.refresh()
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            await self.timed_out()
        except asyncio.CancelledError:
            return

    async def press(self, interaction: discord.Interaction, index: int) -> None:
        if self.finished or not self.accepting:
            await interaction.response.send_message("Wait for the buttons to unlock.", ephemeral=True)
            return
        if interaction.user.id in self.failed:
            await interaction.response.send_message("You already slipped up — wait for the next game.", ephemeral=True)
            return
        step = self.progress.get(interaction.user.id, 0)
        if self.sequence[step] != index:
            self.failed.add(interaction.user.id)
            await interaction.response.send_message("Wrong order — you're out of this round.", ephemeral=True)
            await self.refresh()
            return
        step += 1
        self.progress[interaction.user.id] = step
        if step < len(self.sequence):
            await interaction.response.send_message(f"Nice — {step}/{len(self.sequence)}.", ephemeral=True)
            return
        await self.win(interaction)

    async def win(self, interaction: discord.Interaction) -> None:
        if self.finished:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.view.stop()
        await award_xp(self.bot, interaction.user, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Sequence Hunt",
            f"{interaction.user.mention} repeated the sequence!",
            emoji=":brain:",
            phase="win",
            answer=self._seq_text(),
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Sequence Hunt')}`.",
            winner_avatar=avatar_url(interaction.user),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        await interaction.response.defer()
        await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {interaction.user.mention} won Sequence Hunt! (+{DEFAULT_WIN_XP} XP)")

    async def timed_out(self) -> None:
        if self.finished:
            return
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
        if self.message:
            e = result_embed(
                "Sequence Hunt",
                "Time's up!",
                emoji=":brain:",
                phase="timeout",
                answer=self._seq_text(),
                play_again=f"Play again with `{command_for_title('Sequence Hunt')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await end_game_message(self.message, e, self.view)
        await self.finish(result=f"⏰ Time's up! The sequence was {self._seq_text()}.")


class HiLoView(discord.ui.View):
    def __init__(self, game: "HiLoGame"):
        super().__init__(timeout=120)
        self.game = game

    async def on_timeout(self) -> None:
        await self.game.round_timeout()

    @discord.ui.button(label="⬆️ Higher", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.guess(interaction, "higher")

    @discord.ui.button(label="⬇️ Lower", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.game.guess(interaction, "lower")


class HiLoGame(ChannelGame):
    max_duration = 600
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.current = random.randint(1, 100)
        self.next_number = self._next()
        self.streak = 0
        self.message: discord.Message | None = None
        self.view: HiLoView | None = None
        self.round_open = True
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _next(self) -> int:
        n = random.randint(1, 100)
        while n == self.current:
            n = random.randint(1, 100)
        return n

    def _embed(
        self,
        *,
        over: bool = False,
        wrong: str | None = None,
        title: str | None = None,
        phase: str | None = None,
        extra: str | None = None,
    ) -> discord.Embed:
        if over:
            body = f"The next number was **{self.next_number}** (current was {self.current}).\nStreak: **{self.streak}**."
            if wrong:
                body = f"{wrong}\n\n" + body
            return game_embed(
                title or "HILO over",
                body,
                emoji=":chartincreasing:",
                phase=phase or ("win" if self.streak else "lose"),
                host=self.host_name,
                host_avatar=self.host_avatar,
                footer=game_footer("HILO", self.host_name, extra=extra),
            )
        fields = []
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "HILO",
            f"The number is **{self.current}**.\nWill the next number (1–100) be higher or lower?\n\nStreak: **{self.streak}**",
            emoji=":chartincreasing:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.view = HiLoView(self)
        self.message = await send_dest(dest, embed=self._embed(), view=self.view)

    async def guess(self, interaction: discord.Interaction, choice: str) -> None:
        if self.finished or not self.round_open:
            await interaction.response.send_message("This round is already over.", ephemeral=True)
            return
        self.round_open = False
        actual = "higher" if self.next_number > self.current else "lower"
        if choice != actual:
            self.finished = True
            if self.view:
                for child in self.view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                self.view.stop()
            extra = ""
            if self.streak:
                extra = f" The streak ended at **{self.streak}**."
            e = self._embed(
                over=True,
                phase="lose",
                wrong=f"{interaction.user.mention} guessed **{choice}** — not quite.{extra}",
            )
            await interaction.response.defer()
            await end_game_message(self.message, e, self.view)
            await self.finish(result=f"HILO ended — the streak stopped at **{self.streak}**.")
            return
        self.streak += 1
        await award_xp(self.bot, interaction.user, self.channel, 10)
        if self.streak >= 15:
            self.finished = True
            if self.view:
                for child in self.view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                self.view.stop()
            e = result_embed(
                "HILO",
                f"{interaction.user.mention} got it right!\n**{self.current}** → **{self.next_number}**\nStreak of **{self.streak}** — that's the limit.",
                emoji=":chartincreasing:",
                phase="win",
                xp=10,
                play_again=f"Play again with `{command_for_title('HILO')}`.",
                winner_avatar=avatar_url(interaction.user),
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await interaction.response.defer()
            await end_game_message(self.message, e, self.view)
            await self.finish(result=f"🏆 {interaction.user.mention} won HILO with a streak of **{self.streak}**! (+10 XP)")
            return
        self.current = self.next_number
        self.next_number = self._next()
        self.view = HiLoView(self)
        self.round_open = True
        self.end_ts, _ = countdown_field(120)
        e = self._embed(extra=f"{interaction.user.display_name} was right • +10 XP")
        await interaction.response.edit_message(embed=e, view=self.view)

    async def round_timeout(self) -> None:
        if self.finished or not self.round_open:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
        if self.message:
            await end_game_message(self.message, self._embed(over=True, phase="timeout", title="HILO timed out"), self.view)
        await self.finish(result=f"⏰ HILO timed out. The streak ended at **{self.streak}**.")


class TriviaChannelView(discord.ui.View):
    def __init__(self, game: "TriviaGame", options: list[str], correct: str, *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.game = game
        for option in options:
            self.add_item(TriviaChannelButton(option, option == correct))

    async def on_timeout(self) -> None:
        await self.game.timed_out()


class TriviaChannelButton(discord.ui.Button):
    def __init__(self, label: str, is_correct: bool):
        super().__init__(label=f"🔹 {label}"[:80], style=discord.ButtonStyle.primary)
        self.is_correct = is_correct

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.view.game  # type: ignore[union-attr]
        assert isinstance(game, TriviaGame)
        if game.finished:
            await interaction.response.send_message("This round is over.", ephemeral=True)
            return
        if interaction.user.id in game.wrong:
            await interaction.response.send_message("You already used your guess.", ephemeral=True)
            return
        if not self.is_correct:
            game.wrong.add(interaction.user.id)
            await interaction.response.send_message(f"Not **{self.label}**. You're out of this question.", ephemeral=True)
            return
        await game.win(interaction, self.label or "")


class TriviaGame(ChannelGame):
    def __init__(self, bot, channel, host_id: int, question: str, correct: str, options: list[str]) -> None:
        super().__init__(bot, channel, host_id)
        self.question = question
        self.correct = correct
        self.options = options
        self.wrong: set[int] = set()
        self.message: discord.Message | None = None
        self.view: TriviaChannelView | None = None
        self.seconds_left: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.view = TriviaChannelView(self, self.options, self.correct, timeout=120)  # backstop; the countdown drives the actual timeout
        self.seconds_left = 120
        self.message = await send_dest(dest, embed=self._play_embed(), view=self.view)
        self.task = asyncio.create_task(self._countdown())

    def _play_embed(self) -> discord.Embed:
        return game_embed(
            "Trivia",
            self.question,
            emoji=":Light:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=[("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False)] if self.end_ts else [],
        )

    async def _countdown(self) -> None:
        try:
            for remaining in range(120, -1, -1):
                if self.finished:
                    return
                self.seconds_left = remaining
                if self.message:
                    try:
                        await self.message.edit(embed=self._play_embed())
                    except discord.HTTPException:
                        pass
                if remaining > 0:
                    await asyncio.sleep(1)
            if self.finished:
                return
            await self.timed_out()
        except asyncio.CancelledError:
            return

    async def win(self, interaction: discord.Interaction, picked: str) -> None:
        if self.finished:
            return
        self.finished = True
        if self.view:
            for child in self.view.children:
                if isinstance(child, TriviaChannelButton):
                    child.disabled = True
                    if child.is_correct:
                        child.style = discord.ButtonStyle.success
            self.view.stop()
        await award_xp(self.bot, interaction.user, self.channel, DEFAULT_WIN_XP)
        e = result_embed(
            "Trivia",
            f"{interaction.user.mention} answered correctly!",
            emoji=":Light:",
            phase="win",
            answer=self.correct,
            xp=DEFAULT_WIN_XP,
            play_again=f"Play again with `{command_for_title('Trivia')}`.",
            winner_avatar=avatar_url(interaction.user),
            host=self.host_name,
            host_avatar=self.host_avatar,
        )
        await interaction.response.defer()
        await end_game_message(self.message, e, self.view)
        await self.finish(result=f"🏆 {interaction.user.mention} won Trivia! Answer: **{self.correct}** (+{DEFAULT_WIN_XP} XP)")

    async def timed_out(self) -> None:
        if self.finished:
            return
        if self.view:
            for child in self.view.children:
                if isinstance(child, TriviaChannelButton):
                    child.disabled = True
                    if child.is_correct:
                        child.style = discord.ButtonStyle.success
        if self.message:
            e = result_embed(
                "Trivia",
                "Time's up!",
                emoji=":Light:",
                phase="timeout",
                answer=self.correct,
                play_again=f"Play again with `{command_for_title('Trivia')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            await end_game_message(self.message, e, self.view)
        await self.finish(result=f"⏰ Time's up! The answer was **{self.correct}**.")


class RedLightGame(ChannelGame):
    max_duration = 300
    def __init__(self, bot, channel, host_id: int) -> None:
        super().__init__(bot, channel, host_id)
        self.green = True
        self.scores: dict[int, int] = {}
        self.names: dict[int, str] = {}
        self.eliminated: set[int] = set()
        self.message: discord.Message | None = None
        self.rounds_left = 8
        self.end_ts: int | None = None
        self.host_name: str | None = None
        self.host_avatar: str | None = None

    def _embed(self) -> discord.Embed:
        light = "🟢 **GREEN LIGHT** — type in chat to score!" if self.green else "🔴 **RED LIGHT** — don't type or you're out!"
        lines = []
        for uid, score in sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            mark = " (out)" if uid in self.eliminated else ""
            lines.append(f"• {self.names.get(uid, uid)} — **{score}**{mark}")
        body = light
        if lines:
            body += "\n\n" + "\n".join(lines)
        fields = []
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(
            "Red Light Green Light",
            body,
            emoji=":dollblink:",
            phase="play",
            host=self.host_name,
            host_avatar=self.host_avatar,
            fields=fields,
        )

    async def begin(self, dest) -> None:
        self.host_name, self.host_avatar = host_details(dest, self.host_id)
        self.end_ts, _ = countdown_field(120)
        self.message = await send_dest(dest, embed=self._embed())
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            for _ in range(8):
                await asyncio.sleep(random.uniform(2.0, 4.5))
                if self.finished:
                    return
                self.green = not self.green
                if self.message:
                    try:
                        await self.message.edit(embed=self._embed())
                    except discord.HTTPException:
                        pass
            if self.finished:
                return
            await self.end_game()
        except asyncio.CancelledError:
            return

    async def on_message(self, message: discord.Message) -> bool:
        if self.finished or message.author.bot or not message.content or message.content.startswith("."):
            return False
        uid = message.author.id
        self.names[uid] = message.author.display_name
        if uid in self.eliminated:
            return False
        if self.green:
            self.scores[uid] = self.scores.get(uid, 0) + 1
            try:
                await message.add_reaction("✅")
            except discord.HTTPException:
                pass
            return False
        self.eliminated.add(uid)
        self.scores.setdefault(uid, 0)
        try:
            await message.add_reaction("❌")
        except discord.HTTPException:
            pass
        return False

    async def end_game(self) -> None:
        if self.finished:
            return
        self.finished = True
        alive = {uid: sc for uid, sc in self.scores.items() if uid not in self.eliminated}
        pool = alive if alive else self.scores
        if not pool:
            e = result_embed(
                "Red Light Green Light",
                "Nobody scored this time.",
                emoji=":dollblink:",
                phase="timeout",
                play_again=f"Play again with `{command_for_title('Red Light Green Light')}`.",
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            result = "⏰ Red Light Green Light ended — nobody scored."
        else:
            best = max(pool.values())
            winners = [uid for uid, sc in pool.items() if sc == best]
            mentions = ", ".join(f"<@{uid}>" for uid in winners)
            winner_avatar = None
            for uid in winners:
                user = getattr(self.channel, "guild", None)
                member = user.get_member(uid) if user else None
                if member:
                    if len(winners) == 1:
                        winner_avatar = avatar_url(member)
                    await award_xp(self.bot, member, self.channel, DEFAULT_WIN_XP)
            label = "Winner" if len(winners) == 1 else "Winners"
            e = result_embed(
                "Red Light Green Light",
                f"{label}: {mentions} with **{best}** point{'s' if best != 1 else ''}!",
                emoji=":dollblink:",
                phase="win",
                xp=DEFAULT_WIN_XP,
                play_again=f"Play again with `{command_for_title('Red Light Green Light')}`.",
                winner_avatar=winner_avatar,
                host=self.host_name,
                host_avatar=self.host_avatar,
            )
            if len(self.scores) > 1:
                board = "\n".join(
                    f"{self.names.get(uid, uid)} — **{sc}**"
                    for uid, sc in sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)[:10]
                )
                e.add_field(name="Scoreboard", value=board[:1024], inline=False)
            result = f"🏆 {mentions} won Red Light Green Light with **{best}** point{'s' if best != 1 else ''}! (+{DEFAULT_WIN_XP} XP)"
        if self.message:
            await end_game_message(self.message, e)
        await self.finish(result=result)


class Arcade(commands.Cog):
    """Drop-in competitive games plus the .games menu."""

    def __init__(self, bot: SocializeBot) -> None:
        self.bot = bot
        self._words = banks.word_list()

    async def cog_load(self) -> None:
        self.bot.add_check(self.game_enabled_check)

    async def cog_unload(self) -> None:
        self.bot.remove_check(self.game_enabled_check)

    async def game_enabled_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or ctx.command is None:
            return True
        root = ctx.command.qualified_name.split()[0]
        keys = {key for key, *_ in MENU_GAMES}
        if root not in keys:
            return True
        if await self.bot.db.is_game_enabled(ctx.guild.id, root):
            return True
        raise commands.CheckFailure("That game is disabled in this server.")

    async def send_menu(self, dest: commands.Context | discord.Interaction) -> None:
        games = list(MENU_GAMES)
        guild = getattr(dest, "guild", None)
        if guild is not None:
            disabled = await self.bot.db.disabled_game_keys(guild.id)
            games = [item for item in MENU_GAMES if item[0] not in disabled]
        if not games:
            await send_dest(dest, embed=make_embed("Games disabled", "All drop-in games are disabled in this server.", color=WARNING))
            return
        e = build_menu_embed(games)
        view = GamesDropMenu(self, games)
        msg = await send_dest(dest, embed=e, view=view)
        view.message = msg
        channel_id = getattr(getattr(dest, "channel", None), "id", None)
        if channel_id and msg is not None:
            self.bot.game_sessions.remember_menu(channel_id, msg)

    async def drop_game(self, dest: commands.Context | discord.Interaction, key: str) -> None:
        guild = getattr(dest, "guild", None)
        if guild is not None and not await self.bot.db.is_game_enabled(guild.id, key):
            await send_dest(dest, embed=make_embed("Game disabled", "That game is disabled in this server.", color=DANGER), ephemeral=True)
            return
        if key == "uno":
            uno = self.bot.get_cog("Uno")
            if uno is None:
                await send_dest(dest, embed=make_embed("UNO isn't loaded", "Try again in a moment.", color=DANGER), ephemeral=True)
                return
            await uno.start_lobby(dest)  # type: ignore[attr-defined]
            return
        starter = {
            "buttonhunt": self._start_buttonhunt,
            "diceduel": self._start_diceduel,
            "backwards": self._start_backwards,
            "scramble": self._start_scramble,
            "celebrity": self._start_celebrity,
            "landmark": self._start_landmark,
            "pattern": self._start_pattern,
            "capital": self._start_capital,
            "redlight": self._start_redlight,
            "missingemoji": self._start_missingemoji,
            "sequencehunt": self._start_sequencehunt,
            "colorhunt": self._start_colorhunt,
            "emojieq": self._start_emojieq,
            "flag": self._start_flag,
            "reaction": self._start_reaction,
            "language": self._start_language,
            "word": self._start_word,
            "nickname": self._start_nickname,
            "trivia": self._start_trivia,
            "hilo": self._start_hilo,
        }.get(key)
        if starter is None:
            await send_dest(dest, content="I don't know that game.", ephemeral=True)
            return
        await starter(dest)

    async def _launch(self, dest, factory) -> ChannelGame | None:
        game = await launch_channel_game(dest, self.bot, factory)
        if game is None:
            return None
        try:
            await game.begin(dest)  # type: ignore[attr-defined]
        except Exception:
            await game.finish()
            raise
        return game

    async def _start_buttonhunt(self, dest) -> None:
        await self._launch(dest, ButtonHuntGame)

    async def _start_diceduel(self, dest) -> None:
        await self._launch(dest, DiceDuelGame)

    async def _start_backwards(self, dest) -> None:
        word = random.choice(banks.SCRAMBLE_WORDS)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Word Backwards",
                prompt=f"Type this word **backwards**:\n# {word.upper()}",
                answers=[word[::-1]],
                reveal=f"{word[::-1]}  ({word} backwards)",
                hint=None,
                hint_at=None,
            )
        await self._launch(dest, factory)

    async def _start_scramble(self, dest) -> None:
        word = random.choice(banks.SCRAMBLE_WORDS)
        mixed = scramble_word(word).upper()
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Word Scramble",
                prompt=f"Unscramble this word:\n# {mixed}",
                answers=[word],
                reveal=word,
                hint=f"It starts with **{word[0].upper()}**.",
            )
        await self._launch(dest, factory)

    async def _start_celebrity(self, dest) -> None:
        item = random.choice(banks.celebrities())
        answers = [item["name"], *item.get("aliases", [])]
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Guess the Celebrity",
                prompt="Who is this? Type their name in the chat.",
                answers=answers,
                reveal=item["name"],
                hint=f"They're known as a **{item.get('hint') or 'famous person'}**.",
                image_url=item["url"],
            )
        await self._launch(dest, factory)

    async def _start_landmark(self, dest) -> None:
        item = random.choice(banks.landmarks())
        answers = [item["name"], *item.get("aliases", [])]
        location = ", ".join(p for p in (item.get("location"), item.get("country")) if p)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Guess the Landmark",
                prompt="What landmark is this? Type your guess in the chat.",
                answers=answers,
                reveal=f"{item['name']}\n{location}",
                hint=f"This landmark is in **{item['country']}**.",
                image_url=item["url"],
            )
        await self._launch(dest, factory)

    async def _start_pattern(self, dest) -> None:
        prompt, answers, explanation = random.choice(banks.PATTERNS)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Pattern Puzzle",
                prompt=f"What comes next?\n# {prompt}",
                answers=answers,
                reveal=f"{answers[0]}\n{explanation}",
                hint=None,
                hint_at=None,
                match="fuzzy",
            )
        await self._launch(dest, factory)

    async def _start_capital(self, dest) -> None:
        capital, country, extra = random.choice(banks.CAPITALS)
        mixed = scramble_word(capital.replace(" ", "")).upper()
        answers = [capital, *extra]
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Capital Scramble",
                prompt=f"Unscramble this capital city:\n# {mixed}\n\nHint: it's the capital of **{country}**.",
                answers=answers,
                reveal=f"{capital}, {country}",
                hint=None,
                hint_at=None,
            )
        await self._launch(dest, factory)

    async def _start_redlight(self, dest) -> None:
        await self._launch(dest, RedLightGame)

    async def _start_missingemoji(self, dest) -> None:
        seq, missing = random.choice(banks.MISSING_EMOJI)
        shown = [e if e != missing else "⬜" for e in seq]
        # If the missing emoji appears more than once, only blank one occurrence.
        if shown.count("⬜") != 1:
            shown = list(seq)
            shown[seq.index(missing)] = "⬜"
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Missing Emoji",
                prompt=f"Full set:\n{' '.join(seq)}\n\nOne is missing here:\n{' '.join(shown)}\n\nType the missing emoji.",
                answers=[missing],
                reveal=missing,
                hint=None,
                hint_at=None,
                match="emoji",
            )
        await self._launch(dest, factory)

    async def _start_sequencehunt(self, dest) -> None:
        await self._launch(dest, SequenceHuntGame)

    async def _start_colorhunt(self, dest) -> None:
        await self._launch(dest, ColorHuntGame)

    async def _start_emojieq(self, dest) -> None:
        prompt, answers, explanation = random.choice(banks.EMOJI_EQUATIONS)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Emoji Equation",
                prompt=f"{prompt}\n\nType the number.",
                answers=answers,
                reveal=f"{answers[0]}\n{explanation}",
                hint=None,
                hint_at=None,
                match="number",
            )
        await self._launch(dest, factory)

    async def _start_flag(self, dest) -> None:
        item = random.choice(banks.flags())
        answers = [item["name"], *item.get("aliases", [])]
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Flag",
                prompt="Which country is this flag from? Type the country name.",
                answers=answers,
                reveal=item["name"],
                hint=f"The name starts with **{item['name'][0].upper()}**.",
                image_url=item["url"],
            )
        await self._launch(dest, factory)

    async def _start_reaction(self, dest) -> None:
        await self._launch(dest, ReactionGame)

    async def _start_language(self, dest) -> None:
        phrase, answers, reveal = random.choice(banks.LANGUAGES)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Language",
                prompt=f"Which language is this?\n\n**{phrase}**",
                answers=answers,
                reveal=reveal,
                hint=f"It starts with **{reveal[0].upper()}**.",
            )
        await self._launch(dest, factory)

    async def _start_word(self, dest) -> None:
        prompt, kind, payload = random.choice(banks.WORD_RULES)
        def factory(bot, channel, host_id):
            return WordRuleGame(bot, channel, host_id, prompt, kind, payload, self._words)
        await self._launch(dest, factory)

    async def _start_nickname(self, dest) -> None:
        nick, answers, reveal = random.choice(banks.NICKNAMES)
        def factory(bot, channel, host_id):
            return ChatGuessGame(
                bot, channel, host_id,
                title="Nickname",
                prompt=f"Who or what is known as:\n# {nick}",
                answers=[reveal, *answers],
                reveal=reveal,
                hint=f"The answer starts with **{reveal[0].upper()}**.",
            )
        await self._launch(dest, factory)

    async def _start_trivia(self, dest) -> None:
        question, correct, options = await get_trivia()
        def factory(bot, channel, host_id):
            return TriviaGame(bot, channel, host_id, question, correct, options)
        await self._launch(dest, factory)

    async def _start_hilo(self, dest) -> None:
        await self._launch(dest, HiLoGame)



def command_name(key: str) -> str:
    return {
        "buttonhunt": ".buttonhunt",
        "diceduel": ".diceduel",
        "backwards": ".backwards",
        "scramble": ".scramble",
        "celebrity": ".celebrity",
        "landmark": ".landmark",
        "pattern": ".pattern",
        "capital": ".capital",
        "redlight": ".redlight",
        "missingemoji": ".missingemoji",
        "sequencehunt": ".sequencehunt",
        "colorhunt": ".colorhunt",
        "emojieq": ".emojieq",
        "flag": ".flag",
        "reaction": ".reaction",
        "language": ".language",
        "word": ".word",
        "nickname": ".nickname",
        "trivia": ".trivia",
        "hilo": ".hilo",
        "uno": ".uno",
    }.get(key, f".{key}")



GAME_COMMANDS = [
    ("buttonhunt", "buttonhunt", "Drop a Button Hunt round into this channel.", []),
    ("diceduel", "diceduel", "Start a two-player dice duel.", ["dice"]),
    ("backwards", "backwards", "Type a word backwards.", ["wordbackwards", "reverseword"]),
    ("scramble", "scramble", "Unscramble a word.", ["wordscramble"]),
    ("celebrity", "celebrity", "Guess the celebrity from a photo.", ["celeb"]),
    ("landmark", "landmark", "Guess the landmark from a photo.", ["gtl"]),
    ("pattern", "pattern", "Find the next item in a sequence.", ["patternpuzzle"]),
    ("capital", "capital", "Unscramble a capital city.", ["capitalscramble"]),
    ("redlight", "redlight", "Play Red Light Green Light.", ["rlgl"]),
    ("missingemoji", "missingemoji", "Spot the missing emoji.", []),
    ("sequencehunt", "sequencehunt", "Repeat a sequence of buttons.", ["sequence"]),
    ("colorhunt", "colorhunt", "Click the correct colour button.", ["colourhunt"]),
    ("emojieq", "emojieq", "Solve an emoji maths puzzle.", ["emojimath", "equation"]),
    ("flag", "flag", "Name the country from its flag.", []),
    ("reaction", "reaction", "Wait for GO, then react first.", []),
    ("language", "language", "Guess which language a phrase is in.", []),
    ("word", "word", "Be first to type a word that fits the rule.", []),
    ("nickname", "nickname", "Guess who a nickname belongs to.", []),
    ("trivia", "trivia", "A multiple-choice trivia question for the channel.", []),
    ("hilo", "hilo", "Play higher or lower with a shared streak.", []),
]


async def setup(bot: SocializeBot) -> None:
    cog = Arcade(bot)
    await bot.add_cog(cog)
    for name, key, description, aliases in GAME_COMMANDS:
        async def wrapper(ctx: commands.Context, _key: str = key) -> None:
            await cog.drop_game(ctx, _key)
        wrapper.__name__ = name
        wrapper.__qualname__ = f"Arcade.{name}"
        command = commands.hybrid_command(name=name, aliases=aliases, description=description)(wrapper)
        command = commands.guild_only()(command)
        command = commands.cooldown(1, 5, commands.BucketType.channel)(command)
        bot.add_command(command)
