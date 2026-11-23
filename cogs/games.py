"""Fun games: trivia, RPS, would you rather, truth or dare, and counting."""

from __future__ import annotations

import html
import random
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils import DANGER, SUCCESS, WARNING, embed as make_embed

from cogs.game_ui import countdown_field, clear_countdown, game_embed, result_embed
from cogs.sessions import end_game_message

if TYPE_CHECKING:
    from main import SocializeBot


def _host_details(user: discord.abc.User) -> tuple[str | None, str | None]:
    name = getattr(user, "display_name", None) or getattr(user, "name", None)
    avatar = getattr(user, "display_avatar", None)
    return name, getattr(avatar, "url", None) if avatar is not None else None

WYR_QUESTIONS: list[tuple[str, str]] = [
    ("Be able to fly", "Be able to turn invisible"),
    ("Have a personal chef", "Have a personal chauffeur"),
    ("Live without music", "Live without movies"),
    ("Always be 10 minutes late", "Always be 20 minutes early"),
    ("Have unlimited takeaway", "Have unlimited first-class travel"),
    ("Be able to speak every language", "Be able to talk to animals"),
    ("Give up sweets forever", "Give up savoury snacks forever"),
    ("Have a rewind button for your life", "Have a pause button for your life"),
    ("Be famous for a talent you don't have", "Be unknown for a talent you do have"),
    ("Live in a big city", "Live in a quiet coastal town"),
    ("Never use social media again", "Never watch another TV series"),
    ("Have a photographic memory", "Be able to forget anything you want"),
    ("Fight 100 duck-sized horses", "Fight one horse-sized duck"),
    ("Always know when someone is lying", "Always get away with lying"),
    ("Be stuck in a game of Monopoly", "Be stuck in a game of Uno"),
    ("Have free Wi-Fi everywhere", "Have free coffee everywhere"),
    ("Only be able to whisper", "Only be able to shout"),
    ("Explore the deep ocean", "Explore outer space"),
    ("Lose all your photos", "Lose all your saved chats"),
    ("Be slightly too hot all the time", "Be slightly too cold all the time"),
    ("Have a dragon", "Have a unicorn"),
    ("Go without your phone for a month", "Go without dessert for a year"),
    ("Always have to sing instead of speak", "Always have to dance into every room"),
    ("Read minds", "See 10 minutes into the future"),
    ("Have a house with a cinema", "Have a house with a pool"),
    ("Never have to sleep", "Never have to eat"),
    ("Be the funniest person in the room", "Be the smartest person in the room"),
    ("Time travel to the past", "Time travel to the future"),
    ("Have a pause button for other people", "Have a skip button for awkward moments"),
    ("Only eat pizza for a year", "Only eat burgers for a year"),
    ("Have super strength", "Have super speed"),
    ("Live without air conditioning", "Live without heating"),
    ("Be able to teleport", "Be able to clone yourself"),
    ("Win $10,000 now", "Have a 10% chance of winning $1,000,000"),
    ("Have your dream job with average pay", "Have a boring job with huge pay"),
    ("Never be able to use a voice chat again", "Never be able to type in chat again"),
    ("Always have perfect timing", "Always have perfect luck"),
    ("Be great at every game", "Be great at every instrument"),
    ("Have dinner with your favourite celebrity", "Have dinner with your future self"),
    ("Keep your current friends and never make new ones", "Make new friends but forget your current ones"),
]

TRUTHS: list[str] = [
    "What's the most embarrassing thing that's happened to you in a voice chat?",
    "What's a nickname you secretly don't mind?",
    "What's your most-used emoji and why?",
    "What's a song you have on repeat that you'd be shy to admit?",
    "What's the last thing you searched for?",
    "Who in this server would you want as a teammate in a game, and why?",
    "What's a habit you're trying to break?",
    "What's the worst fashion choice you've ever made?",
    "If you had to delete one app from your phone forever, which would it be?",
    "What's a random skill you're surprisingly good at?",
    "What's your go-to comfort food?",
    "What's a hill you'll die on, even if it's silly?",
    "What's the last compliment you received that stuck with you?",
    "What's something you believed for way too long as a kid?",
    "What's your most controversial food opinion?",
    "If you could swap lives with someone in this server for a day, who would it be?",
    "What's a show you started and never finished?",
    "What's your most-used Discord feature?",
    "What's the weirdest dream you can remember?",
    "What's a hobby you dropped and kind of miss?",
    "What's your favourite way to spend a Sunday?",
    "What's something that always makes you laugh?",
    "What's a small thing that instantly improves your day?",
    "What's the last game you rage-quit?",
    "What's a talent you wish you had?",
    "What's your most unpopular opinion about a popular game or show?",
    "What's the kindest thing a stranger has done for you?",
    "What's a goal you're working on right now?",
    "If you had to eat one meal for the rest of the week, what would it be?",
    "What's a word or phrase you say way too often?",
    "What's the best DM you've ever received (keep it PG)?",
    "What's something you collect, even a little?",
    "What's a place you want to visit this year?",
    "What's your favourite voice-chat memory?",
    "What's a compliment you wish people gave you more often?",
]

DARES: list[str] = [
    "Send a message using only emojis and make the others guess what it means.",
    "Change your nickname to something the last person who talked chooses (for 10 minutes).",
    "Do your best impression of another member (no being mean).",
    "Type your next three messages in all caps.",
    "Post a voice-message style sentence in text, full of ums and pauses.",
    "Compliment three people in this channel.",
    "Talk in rhymes for the next five minutes.",
    "Share a fun fact about yourself that nobody here knows.",
    "Use a random reaction on the next 5 messages you see.",
    "Write a 2-line advertisement selling an everyday object as if it's legendary loot.",
    "Make up a dramatic backstory for your profile picture.",
    "Send a tongue twister and challenge someone to say it out loud in VC.",
    "Talk like a sports commentator about whatever is happening in chat.",
    "Start a countdown from 10 as if something huge is about to happen.",
    "Ask someone a would-you-rather you invented on the spot.",
    "Give the group a 30-second pep talk.",
    "Use only questions for your next five messages.",
    "Recommend a song and explain it in exactly one sentence.",
    "Create a new inside joke in one message and try to make it stick.",
    "Pretend you're a greeter at the server door and welcome everyone again.",
    "Share your current song or the last song you played.",
    "Describe your day as a movie trailer.",
    "Let the group pick a word you have to sneak into your next three messages.",
    "Do a dramatic reading of the last message in the channel.",
    "Invent a mini rule for the next 10 minutes of chat and enforce it kindly.",
    "Send a motivational quote you just made up.",
    "Draw an ASCII animal and post it.",
    "Rate the last game, song or show you enjoyed, out of 10, and defend the score.",
    "Start a one-minute story and let the next person continue it.",
    "Tell the group what your role or colour would be if this server were a game class.",
    "Speak only in movie titles (or close enough) for three messages.",
    "Give someone a mock award with a made-up category.",
    "Write a haiku about voice chat.",
    "Challenge someone to rock-paper-scissors with `.rps`.",
    "Post your best (harmless) pickup line for a video game item.",
]

FALLBACK_TRIVIA: list[dict] = [
    {"q": "What is the capital of Australia?", "correct": "Canberra", "wrong": ["Sydney", "Melbourne", "Perth"]},
    {"q": "How many players are on the field for one side in a game of soccer?", "correct": "11", "wrong": ["10", "9", "12"]},
    {"q": "Which planet is known as the Red Planet?", "correct": "Mars", "wrong": ["Venus", "Jupiter", "Mercury"]},
    {"q": "What year did Discord officially launch?", "correct": "2015", "wrong": ["2013", "2016", "2014"]},
    {"q": "In rock-paper-scissors, what beats paper?", "correct": "Scissors", "wrong": ["Rock", "Paper", "Lizard"]},
    {"q": "How many minutes are in a full day?", "correct": "1440", "wrong": ["1400", "1600", "1240"]},
    {"q": "Which ocean is the largest?", "correct": "Pacific", "wrong": ["Atlantic", "Indian", "Arctic"]},
    {"q": "What is the chemical symbol for gold?", "correct": "Au", "wrong": ["Ag", "Gd", "Go"]},
    {"q": "Who painted the Mona Lisa?", "correct": "Leonardo da Vinci", "wrong": ["Michelangelo", "Van Gogh", "Picasso"]},
    {"q": "What is the smallest prime number?", "correct": "2", "wrong": ["1", "3", "0"]},
    {"q": "Which country is home to the kangaroo?", "correct": "Australia", "wrong": ["New Zealand", "South Africa", "Brazil"]},
    {"q": "How many keys does a standard piano have?", "correct": "88", "wrong": ["76", "100", "64"]},
    {"q": "What does CPU stand for?", "correct": "Central Processing Unit", "wrong": ["Computer Power Unit", "Central Program Utility", "Core Processing Upgrade"]},
    {"q": "Which Shakespeare play features the characters Romeo and Juliet?", "correct": "Romeo and Juliet", "wrong": ["Hamlet", "Macbeth", "Othello"]},
    {"q": "What is the fastest land animal?", "correct": "Cheetah", "wrong": ["Lion", "Pronghorn", "Greyhound"]},
    {"q": "How many sides does a hexagon have?", "correct": "6", "wrong": ["5", "7", "8"]},
    {"q": "Which gas do plants absorb from the air?", "correct": "Carbon dioxide", "wrong": ["Oxygen", "Nitrogen", "Helium"]},
    {"q": "What is the largest mammal?", "correct": "Blue whale", "wrong": ["Elephant", "Giraffe", "Orca"]},
    {"q": "In which sport would you perform a slam dunk?", "correct": "Basketball", "wrong": ["Volleyball", "Tennis", "Rugby"]},
    {"q": "What's the name of the 0 point of temperature in Celsius, in terms of water?", "correct": "Freezing point of water", "wrong": ["Boiling point of water", "Absolute zero", "Room temperature"]},
]


def _member_name(user: discord.abc.User) -> str:
    return getattr(user, "display_name", user.name)


class RPSView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member | None):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent  # None means vs bot
        self.choices: dict[int, str] = {}
        self.message: discord.Message | None = None
        self.end_ts: int | None = None

    def _embed(self, title: str, text: str, color: int) -> discord.Embed:
        phase = "win" if color == SUCCESS else ("lose" if color == DANGER else "play")
        name, avatar = _host_details(self.challenger)
        fields = []
        if self.end_ts is not None and color != SUCCESS and color != DANGER:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        return game_embed(title, text, emoji="✊", phase=phase, color=color, host=name, host_avatar=avatar, fields=fields)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                if self.message.embeds:
                    original = self.message.embeds[0]
                    clear_countdown(original)
                    await self.message.edit(embed=original, view=self)
            except discord.HTTPException:
                pass

    async def _pick(self, interaction: discord.Interaction, choice: str) -> None:
        user = interaction.user
        if self.opponent is None:
            if user.id != self.challenger.id:
                await interaction.response.send_message("This isn't your match.", ephemeral=True)
                return
            bot_choice = random.choice(["rock", "paper", "scissors"])
            result = _rps_result(choice, bot_choice)
            if result == 0:
                title, color, text = "It's a draw!", WARNING, f"You both picked **{choice}**."
            elif result == 1:
                title, color, text = "You win!", SUCCESS, f"You picked **{choice}**. I picked **{bot_choice}**."
            else:
                title, color, text = "You lose!", DANGER, f"You picked **{choice}**. I picked **{bot_choice}**."
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            self.stop()
            await interaction.response.defer()
            await end_game_message(self.message, self._embed(title, text, color), self)
            return

        if user.id not in (self.challenger.id, self.opponent.id):
            await interaction.response.send_message("You're not in this match.", ephemeral=True)
            return
        if user.id in self.choices:
            await interaction.response.send_message("You've already locked in a choice.", ephemeral=True)
            return
        self.choices[user.id] = choice
        await interaction.response.send_message(f"You picked **{choice}**. Waiting for the other player...", ephemeral=True)
        if len(self.choices) < 2:
            return
        c1 = self.choices[self.challenger.id]
        c2 = self.choices[self.opponent.id]
        result = _rps_result(c1, c2)
        if result == 0:
            title, color, text = "It's a draw!", WARNING, f"{self.challenger.mention} and {self.opponent.mention} both picked **{c1}**."
        elif result == 1:
            title, color, text = f"{_member_name(self.challenger)} wins!", SUCCESS, f"{self.challenger.mention} picked **{c1}**.\n{self.opponent.mention} picked **{c2}**."
        else:
            title, color, text = f"{_member_name(self.opponent)} wins!", SUCCESS, f"{self.challenger.mention} picked **{c1}**.\n{self.opponent.mention} picked **{c2}**."
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            await end_game_message(self.message, self._embed(title, text, color), self)
        self.stop()

    @discord.ui.button(label="Rock", emoji="🪨", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "rock")

    @discord.ui.button(label="Paper", emoji="📄", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "paper")

    @discord.ui.button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "scissors")


def _rps_result(a: str, b: str) -> int:
    if a == b:
        return 0
    wins = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
    return 1 if (a, b) in wins else -1


class TriviaView(discord.ui.View):
    def __init__(self, correct: str, options: list[str], author_id: int):
        super().__init__(timeout=25)
        self.correct = correct
        self.author_id = author_id
        self.finished = False
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        for option in options:
            self.add_item(TriviaButton(option, option == correct))

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.finished = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                if child.label == self.correct:
                    child.style = discord.ButtonStyle.success
        if self.message:
            e = result_embed(
                "Trivia",
                "Time's up!",
                emoji="🧠",
                phase="timeout",
                answer=self.correct,
                play_again="Start another round with `.trivia`.",
            )
            await end_game_message(self.message, e, self)


class TriviaButton(discord.ui.Button):
    def __init__(self, label: str, is_correct: bool):
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary)
        self.is_correct = is_correct

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, TriviaView)
        if view.finished:
            await interaction.response.send_message("This round is already over.", ephemeral=True)
            return
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("Start your own round with `.trivia` or `/trivia`.", ephemeral=True)
            return
        view.finished = True
        for child in view.children:
            if isinstance(child, TriviaButton):
                child.disabled = True
                if child.is_correct:
                    child.style = discord.ButtonStyle.success
                elif child is self and not child.is_correct:
                    child.style = discord.ButtonStyle.danger
        if self.is_correct:
            e = game_embed("Correct!", f"**{self.label}** is the right answer.", emoji="🧠", phase="win")
        else:
            e = game_embed(
                "Not quite.",
                f"You picked **{self.label}**. The answer was **{view.correct}**.",
                emoji="🧠",
                phase="lose",
            )
        await interaction.response.defer()
        await end_game_message(view.message, e, view)
        view.stop()


class WYRView(discord.ui.View):
    def __init__(self, option_a: str, option_b: str):
        super().__init__(timeout=60)
        self.option_a = option_a
        self.option_b = option_b
        self.votes: dict[int, str] = {}
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        self.a_button.label = option_a[:80]
        self.b_button.label = option_b[:80]

    def _embed(self) -> discord.Embed:
        a = sum(1 for v in self.votes.values() if v == "a")
        b = sum(1 for v in self.votes.values() if v == "b")
        total = a + b
        def line(n: int, label: str) -> str:
            pct = 0 if total == 0 else round(100 * n / total)
            return f"**{label}**\n{n} vote{'s' if n != 1 else ''} ({pct}%)"
        fields = []
        if self.end_ts is not None:
            fields.append(("Time left", f"⏳ Ends <t:{self.end_ts}:R>", False))
        e = game_embed("Would you rather...", f"{line(a, self.option_a)}\n\n{line(b, self.option_b)}", emoji="🤔", phase="play", fields=fields)
        e.set_footer(text=f"{total} vote{'s' if total != 1 else ''}")
        return e

    async def _vote(self, interaction: discord.Interaction, side: str) -> None:
        self.votes[interaction.user.id] = side
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.primary)
    async def a_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._vote(interaction, "a")

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.secondary)
    async def b_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._vote(interaction, "b")

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                if self.message.embeds:
                    original = self.message.embeds[0]
                    clear_countdown(original)
                    await self.message.edit(embed=original, view=self)
            except discord.HTTPException:
                pass


class TODView(discord.ui.View):
    def __init__(self, target: discord.Member):
        super().__init__(timeout=90)
        self.target = target
        self.message: discord.Message | None = None
        self.end_ts: int | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                if self.message.embeds:
                    original = self.message.embeds[0]
                    clear_countdown(original)
                    await self.message.edit(embed=original, view=self)
            except discord.HTTPException:
                pass

    def _prompt(self, kind: str) -> discord.Embed:
        if kind == "truth":
            text = random.choice(TRUTHS)
            return game_embed(f"Truth for {_member_name(self.target)}", text, emoji="🎲", phase="play")
        text = random.choice(DARES)
        return game_embed(f"Dare for {_member_name(self.target)}", text, emoji="🎲", phase="play")

    @discord.ui.button(label="Truth", emoji="🔵", style=discord.ButtonStyle.primary)
    async def truth(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=self._prompt("truth"), view=self)

    @discord.ui.button(label="Dare", emoji="🔴", style=discord.ButtonStyle.danger)
    async def dare(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=self._prompt("dare"), view=self)

    @discord.ui.button(label="Random", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def random_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=self._prompt(random.choice(["truth", "dare"])), view=self)


class GamesMenu(discord.ui.View):
    def __init__(self, cog: "Games"):
        super().__init__(timeout=120)
        self.cog = cog
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.select(
        placeholder="Pick a game to start...",
        options=[
            discord.SelectOption(label="Trivia", value="trivia", emoji="🧠", description="Answer a multiple-choice question"),
            discord.SelectOption(label="Rock Paper Scissors", value="rps", emoji="✊", description="Play against the bot"),
            discord.SelectOption(label="Would You Rather", value="wyr", emoji="🤔", description="Vote on a tough choice"),
            discord.SelectOption(label="Truth or Dare", value="tod", emoji="🎲", description="Get a truth or a dare"),
        ],
    )
    async def pick(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        choice = select.values[0]
        if choice == "trivia":
            await self.cog.start_trivia(interaction)
        elif choice == "rps":
            await self.cog.start_rps(interaction, opponent=None)
        elif choice == "wyr":
            await self.cog.start_wyr(interaction)
        elif choice == "tod":
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if member is None:
                await interaction.response.send_message("You can only play this in a server.", ephemeral=True)
                return
            await self.cog.start_tod(interaction, member)


class Games(commands.Cog):
    """Fun games and the counting channel."""

    def __init__(self, bot: SocializeBot):
        self.bot = bot

    @commands.hybrid_command(name="games", description="Open a menu of games to drop into this channel.")
    @commands.guild_only()
    async def games(self, ctx: commands.Context) -> None:
        arcade = self.bot.get_cog("Arcade")
        if arcade is None:
            await ctx.send(embed=make_embed("Games aren't ready", "Try again in a moment.", color=DANGER))
            return
        await arcade.send_menu(ctx)

    async def start_trivia(self, destination: commands.Context | discord.Interaction) -> None:
        question, correct, options = await self._get_trivia()
        view = TriviaView(correct, options, destination.user.id if isinstance(destination, discord.Interaction) else destination.author.id)
        author = destination.user if isinstance(destination, discord.Interaction) else destination.author
        host, host_avatar = _host_details(author)
        view.end_ts, _ = countdown_field(25)
        e = game_embed(
            "Trivia",
            question,
            emoji="🧠",
            phase="play",
            host=host,
            host_avatar=host_avatar,
            fields=[("Time left", f"⏳ Ends <t:{view.end_ts}:R>", False)],
        )
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=e, view=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(embed=e, view=view)

    async def _get_trivia(self) -> tuple[str, str, list[str]]:
        try:
            timeout = aiohttp.ClientTimeout(total=6)
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
        item = random.choice(FALLBACK_TRIVIA)
        options = item["wrong"] + [item["correct"]]
        random.shuffle(options)
        return item["q"], item["correct"], options

    async def start_rps(self, destination: commands.Context | discord.Interaction, opponent: discord.Member | None) -> None:
        if isinstance(destination, discord.Interaction):
            author = destination.user
        else:
            author = destination.author
        if not isinstance(author, discord.Member):
            return
        if opponent and opponent.id == author.id:
            content = "You can't challenge yourself. Leave the opponent blank to play against me."
            if isinstance(destination, discord.Interaction):
                await destination.response.send_message(content, ephemeral=True)
            else:
                await destination.send(embed=make_embed("Can't do that", content, color=DANGER))
            return
        if opponent and opponent.bot:
            content = "Bots don't have hands. Leave the opponent blank to play against me."
            if isinstance(destination, discord.Interaction):
                await destination.response.send_message(content, ephemeral=True)
            else:
                await destination.send(embed=make_embed("Can't do that", content, color=DANGER))
            return
        view = RPSView(author, opponent)
        host, host_avatar = _host_details(author)
        view.end_ts, _ = countdown_field(60)
        if opponent is None:
            e = game_embed(
                "Rock Paper Scissors",
                f"{author.mention}, pick your move. You're playing against me.",
                emoji="✊",
                phase="play",
                host=host,
                host_avatar=host_avatar,
                fields=[("Time left", f"⏳ Ends <t:{view.end_ts}:R>", False)],
            )
        else:
            e = game_embed(
                "Rock Paper Scissors",
                f"{author.mention} challenged {opponent.mention}!\nBoth of you, pick a move.",
                emoji="✊",
                phase="play",
                host=host,
                host_avatar=host_avatar,
                fields=[("Time left", f"⏳ Ends <t:{view.end_ts}:R>", False)],
            )
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=e, view=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(embed=e, view=view)

    @commands.hybrid_command(name="rps", description="Play rock paper scissors against the bot or another member.")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    @app_commands.describe(opponent="Leave empty to play against the bot.")
    async def rps(self, ctx: commands.Context, opponent: discord.Member | None = None) -> None:
        await self.start_rps(ctx, opponent)

    async def start_wyr(self, destination: commands.Context | discord.Interaction) -> None:
        a, b = random.choice(WYR_QUESTIONS)
        view = WYRView(a, b)
        view.end_ts, _ = countdown_field(60)
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=view._embed(), view=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(embed=view._embed(), view=view)

    @commands.hybrid_command(name="wyr", aliases=["wouldyourather"], description="Start a would-you-rather vote.")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def wyr(self, ctx: commands.Context) -> None:
        await self.start_wyr(ctx)

    async def start_tod(self, destination: commands.Context | discord.Interaction, target: discord.Member) -> None:
        view = TODView(target)
        view.end_ts, _ = countdown_field(90)
        e = game_embed(
            "Truth or Dare",
            f"{target.mention}, pick **Truth**, **Dare**, or **Random**.",
            emoji="🎲",
            phase="play",
            fields=[("Time left", f"⏳ Ends <t:{view.end_ts}:R>", False)],
        )
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=e, view=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(embed=e, view=view)

    @commands.hybrid_command(name="tod", aliases=["truthordare"], description="Start a truth or dare for yourself or someone else.")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    @app_commands.describe(member="Who has to choose? Defaults to you.")
    async def tod(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            await ctx.send(embed=make_embed("Server only", "This command can only be used in a server.", color=DANGER), ephemeral=True)
            return
        await self.start_tod(ctx, target)

    @commands.hybrid_command(name="truth", description="Get a random truth question.")
    @commands.guild_only()
    async def truth(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        await ctx.send(embed=make_embed(f"Truth for {_member_name(target)}", random.choice(TRUTHS)))

    @commands.hybrid_command(name="dare", description="Get a random dare.")
    @commands.guild_only()
    async def dare(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        await ctx.send(embed=make_embed(f"Dare for {_member_name(target)}", random.choice(DARES)))


    @commands.hybrid_command(name="eightball", aliases=["8ball", "eight_ball"], description="Ask the magic 8-ball a question.")
    async def eightball(self, ctx: commands.Context, *, question: str | None = None) -> None:
        from cogs.banks import EIGHTBALL
        answer = random.choice(EIGHTBALL)
        prompt = question.strip() if question else "The 8-ball says:"
        e = make_embed("8-ball", f"**{prompt}**\n\n{answer}")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="setcounting", description="Set or clear the counting channel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="The counting channel. Omit to clear it.")
    async def setcounting(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        if channel is None:
            await self.bot.db.update_settings(ctx.guild.id, counting_next=1, counting_last_user=None)
            await self.bot.db.set_feature_channel(ctx.guild.id, "counting", None)
            await ctx.send(embed=make_embed("Counting disabled", "I won't look for a counting channel any more."))
            return
        await self.bot.db.update_settings(ctx.guild.id, counting_next=1, counting_last_user=None)
        await self.bot.db.set_feature_channel(ctx.guild.id, "counting", channel.id)
        await ctx.send(
            embed=make_embed(
                "Counting channel set",
                f"Start at **1** in {channel.mention}. No skipping, and you can't count twice in a row.",
            )
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not message.content.startswith("."):
            game = self.bot.game_sessions.get(message.channel.id)
            if game is not None and await game.on_message(message):
                return
        if message.content.startswith("."):
            return
        counting_id = await self.bot.db.get_feature_channel(message.guild.id, "counting")
        if counting_id != message.channel.id:
            return
        settings = await self.bot.db.get_settings(message.guild.id)
        if not settings:
            return
        expected = int(settings["counting_next"] or 1)
        last_user = settings["counting_last_user"]
        content = message.content.strip().replace(",", "")
        try:
            number = int(content.split()[0]) if content else None
        except (ValueError, IndexError):
            number = None
        if number is None:
            return
        if last_user is not None and int(last_user) == message.author.id:
            await self._fail_count(message, expected, "You can't count twice in a row. Back to **1**.")
            return
        if number != expected:
            await self._fail_count(message, expected, f"The next number was **{expected}**. Back to **1**.")
            return
        high = max(int(settings["counting_high"] or 0), expected)
        await self.bot.db.update_settings(
            message.guild.id,
            counting_next=expected + 1,
            counting_last_user=message.author.id,
            counting_high=high,
        )
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
        if expected > 0 and expected % 100 == 0:
            try:
                await message.channel.send(embed=make_embed("Nice streak!", f"The server just hit **{expected}**! High score: **{high}**."))
            except discord.HTTPException:
                pass

    async def _fail_count(self, message: discord.Message, expected: int, reason: str) -> None:
        assert message.guild
        settings = await self.bot.db.get_settings(message.guild.id)
        high = int(settings["counting_high"] or 0) if settings else 0
        high = max(high, expected - 1)
        await self.bot.db.update_settings(
            message.guild.id,
            counting_next=1,
            counting_last_user=None,
            counting_high=high,
        )
        try:
            await message.add_reaction("❌")
            await message.channel.send(
                embed=make_embed("Streak broken", f"{message.author.mention} — {reason}\nHigh score: **{high}**.", color=DANGER)
            )
        except discord.HTTPException:
            pass


    @commands.hybrid_command(name="endgame", aliases=["stopgame"], description="End the game running in this channel.")
    @commands.guild_only()
    async def endgame(self, ctx: commands.Context) -> None:
        game = self.bot.game_sessions.peek(ctx.channel.id)
        if game is None:
            await ctx.send(embed=make_embed("No game running", "There's no game to end in this channel."), ephemeral=True)
            return
        try:
            await game.finish()
        except Exception:
            self.bot.game_sessions.end(ctx.channel.id)
        await ctx.send(embed=make_embed("Game ended", "The channel is free — you can start a new game.", color=SUCCESS))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Games(bot))
