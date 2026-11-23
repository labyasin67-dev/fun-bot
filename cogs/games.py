"""Fun games: trivia, RPS, would you rather, truth or dare, and counting."""

from __future__ import annotations

import html
import random
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils import DANGER, SUCCESS, WARNING

from cogs.v2 import build_game_layout, result_layout, countdown_field
from cogs.sessions import end_game_message_v2

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


class RPSView(discord.ui.LayoutView):
    def __init__(self, challenger: discord.Member, opponent: discord.Member | None):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent  # None means vs bot
        self.choices: dict[int, str] = {}
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(label="Rock", emoji="🪨", style=discord.ButtonStyle.secondary, custom_id="rps:rock", callback=self.rock))
        row.add_item(discord.ui.Button(label="Paper", emoji="📄", style=discord.ButtonStyle.secondary, custom_id="rps:paper", callback=self.paper))
        row.add_item(discord.ui.Button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.secondary, custom_id="rps:scissors", callback=self.scissors))
        self.add_item(row)
        self.title_td = discord.ui.TextDisplay("# Rock Paper Scissors")
        self.container.add_item(self.title_td)
        self.body_td = discord.ui.TextDisplay("")
        self.container.add_item(self.body_td)
        self.countdown_td = discord.ui.TextDisplay("")
        self.container.add_item(self.countdown_td)
        self.container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        self.footer_td = discord.ui.TextDisplay("-# Started by ")
        self.container.add_item(self.footer_td)

    def _result(self, title: str, text: str, color: int):
        phase = "win" if color == SUCCESS else ("lose" if color == DANGER else "play")
        name, avatar = _host_details(self.challenger)
        return build_game_layout(title, text, phase=phase, emoji="✊", host=name, host_avatar=avatar)

    async def on_timeout(self) -> None:
        self.disable_items()
        if self.message:
            try:
                await self.message.edit(view=self)
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
                title, text = "It's a draw!", f"You both picked **{choice}**."
            elif result == 1:
                title, text = "You win!", f"You picked **{choice}**. I picked **{bot_choice}**."
            else:
                title, text = "You lose!", f"You picked **{choice}**. I picked **{bot_choice}**."
            self.stop()
            await interaction.response.defer()
            await end_game_message_v2(self.message, self._result(title, text, SUCCESS if result == 1 else DANGER if result == -1 else WARNING), self)
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
            title, text = "It's a draw!", f"{self.challenger.mention} and {self.opponent.mention} both picked **{c1}**."
        elif result == 1:
            title, text = f"{_member_name(self.challenger)} wins!", f"{self.challenger.mention} picked **{c1}**.\n{self.opponent.mention} picked **{c2}**."
        else:
            title, text = f"{_member_name(self.opponent)} wins!", f"{self.challenger.mention} picked **{c1}**.\n{self.opponent.mention} picked **{c2}**."
        self.stop()
        await end_game_message_v2(self.message, self._result(title, text, SUCCESS if result == 1 else WARNING), self)

    async def rock(self, interaction: discord.Interaction) -> None:
        await self._pick(interaction, "rock")

    async def paper(self, interaction: discord.Interaction) -> None:
        await self._pick(interaction, "paper")

    async def scissors(self, interaction: discord.Interaction) -> None:
        await self._pick(interaction, "scissors")


def _rps_result(a: str, b: str) -> int:
    if a == b:
        return 0
    wins = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
    return 1 if (a, b) in wins else -1


class TriviaView(discord.ui.LayoutView):
    def __init__(self, correct: str, options: list[str], author_id: int):
        super().__init__(timeout=25)
        self.correct = correct
        self.author_id = author_id
        self.finished = False
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        row = discord.ui.ActionRow()
        for option in options:
            row.add_item(discord.ui.Button(label=option[:80], style=discord.ButtonStyle.primary, custom_id="trivia:opt", callback=self._make_callback(option, option == correct)))
        self.add_item(row)
        self.title_td = discord.ui.TextDisplay("# Trivia")
        self.container.add_item(self.title_td)
        self.body_td = discord.ui.TextDisplay("")
        self.container.add_item(self.body_td)
        self.countdown_td = discord.ui.TextDisplay("")
        self.container.add_item(self.countdown_td)
        self.container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        self.footer_td = discord.ui.TextDisplay("")
        self.container.add_item(self.footer_td)

    def _make_callback(self, option: str, is_correct: bool):
        async def callback(interaction: discord.Interaction) -> None:
            if self.finished:
                await interaction.response.send_message("This round is already over.", ephemeral=True)
                return
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("Start your own round with `.trivia` or `/trivia`.", ephemeral=True)
                return
            self.finished = True
            self.disable_items()
            if is_correct:
                self.body_td.content = f"Correct! **{option}** is the right answer."
                result = result_layout("Trivia", f"Correct! **{option}** is the right answer.", phase="win", emoji="🧠", play_again="Start another round with `.trivia`.")
            else:
                self.body_td.content = f"Not quite. You picked **{option}**. The answer was **{self.correct}**."
                result = result_layout("Trivia", f"Not quite. You picked **{option}**. The answer was **{self.correct}**.", phase="lose", emoji="🧠", answer=self.correct, play_again="Start another round with `.trivia`.")
            await interaction.response.edit_message(layout=self)
            await end_game_message_v2(self.message, result, self)
            self.stop()
        return callback

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.disable_items()
        self.body_td.content = "Time's up!"
        if self.message:
            try:
                await self.message.edit(layout=self)
            except discord.HTTPException:
                pass
        try:
            result = result_layout("Trivia", "Time's up!", phase="timeout", emoji="🧠", answer=self.correct, play_again="Start another round with `.trivia`.")
            await end_game_message_v2(self.message, result, self)
        except Exception:
            pass


class WYRView(discord.ui.LayoutView):
    def __init__(self, option_a: str, option_b: str):
        super().__init__(timeout=60)
        self.option_a = option_a
        self.option_b = option_b
        self.votes: dict[int, str] = {}
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(label=option_a[:80], style=discord.ButtonStyle.primary, custom_id="wyr:a", callback=self.a_button))
        row.add_item(discord.ui.Button(label=option_b[:80], style=discord.ButtonStyle.secondary, custom_id="wyr:b", callback=self.b_button))
        self.add_item(row)
        self.title_td = discord.ui.TextDisplay("# Would you rather...?")
        self.container.add_item(self.title_td)
        self.body_td = discord.ui.TextDisplay("")
        self.container.add_item(self.body_td)
        self.countdown_td = discord.ui.TextDisplay("")
        self.container.add_item(self.countdown_td)
        self.container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        self.footer_td = discord.ui.TextDisplay("")
        self.container.add_item(self.footer_td)

    def _content(self) -> str:
        a = sum(1 for v in self.votes.values() if v == "a")
        b = sum(1 for v in self.votes.values() if v == "b")
        total = a + b

        def line(n: int, label: str) -> str:
            pct = 0 if total == 0 else round(100 * n / total)
            return f"**{label}**\n{n} vote{'s' if n != 1 else ''} ({pct}%)"

        return f"{line(a, self.option_a)}\n\n{line(b, self.option_b)}"

    async def _vote(self, interaction: discord.Interaction, side: str) -> None:
        self.votes[interaction.user.id] = side
        a = sum(1 for v in self.votes.values() if v == "a")
        b = sum(1 for v in self.votes.values() if v == "b")
        total = a + b
        self.body_td.content = self._content()
        self.footer_td.content = f"-# {total} vote{'s' if total != 1 else ''}"
        await interaction.response.edit_message(layout=self)

    async def a_button(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "a")

    async def b_button(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "b")

    async def on_timeout(self) -> None:
        self.disable_items()
        if self.message:
            try:
                await self.message.edit(layout=self)
            except discord.HTTPException:
                pass


class TODView(discord.ui.LayoutView):
    def __init__(self, target: discord.Member):
        super().__init__(timeout=90)
        self.target = target
        self.message: discord.Message | None = None
        self.end_ts: int | None = None
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(label="Truth", emoji="🔵", style=discord.ButtonStyle.primary, custom_id="tod:truth", callback=self.truth))
        row.add_item(discord.ui.Button(label="Dare", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="tod:dare", callback=self.dare))
        row.add_item(discord.ui.Button(label="Random", emoji="🎲", style=discord.ButtonStyle.secondary, custom_id="tod:random", callback=self.random_btn))
        self.add_item(row)
        self.title_td = discord.ui.TextDisplay("# 🎲 Truth or Dare")
        self.container.add_item(self.title_td)
        self.body_td = discord.ui.TextDisplay("")
        self.container.add_item(self.body_td)

    def _prompt(self, kind: str) -> str:
        if kind == "truth":
            return random.choice(TRUTHS)
        return random.choice(DARES)

    async def on_timeout(self) -> None:
        self.disable_items()
        if self.message:
            try:
                await self.message.edit(layout=self)
            except discord.HTTPException:
                pass

    async def truth(self, interaction: discord.Interaction) -> None:
        self.body_td.content = self._prompt("truth")
        await interaction.response.edit_message(layout=self)

    async def dare(self, interaction: discord.Interaction) -> None:
        self.body_td.content = self._prompt("dare")
        await interaction.response.edit_message(layout=self)

    async def random_btn(self, interaction: discord.Interaction) -> None:
        self.body_td.content = self._prompt(random.choice(["truth", "dare"]))
        await interaction.response.edit_message(layout=self)


class GamesMenu(discord.ui.LayoutView):
    def __init__(self, cog: "Games"):
        super().__init__(timeout=120)
        self.cog = cog
        self.message: discord.Message | None = None
        select = discord.ui.Select(
            placeholder="Pick a game to start...",
            options=[
                discord.SelectOption(label="Trivia", value="trivia", emoji="🧠", description="Answer a multiple-choice question"),
                discord.SelectOption(label="Rock Paper Scissors", value="rps", emoji="✊", description="Play against the bot"),
                discord.SelectOption(label="Would You Rather", value="wyr", emoji="🤔", description="Vote on a tough choice"),
                discord.SelectOption(label="Truth or Dare", value="tod", emoji="🎲", description="Get a truth or a dare"),
            ],
        )

        async def pick(interaction: discord.Interaction) -> None:
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

        select.callback = pick
        row = discord.ui.ActionRow(select)
        self.add_item(row)
        self.title_td = discord.ui.TextDisplay("# Games")
        self.container.add_item(self.title_td)
        self.body_td = discord.ui.TextDisplay("Pick a game to start from the menu below.")
        self.container.add_item(self.body_td)

    async def on_timeout(self) -> None:
        self.disable_items()
        if self.message:
            try:
                await self.message.edit(layout=self)
            except discord.HTTPException:
                pass


class Games(commands.Cog):
    """Fun games and the counting channel."""

    def __init__(self, bot: SocializeBot):
        self.bot = bot

    @commands.hybrid_command(name="games", description="Open a menu of games to drop into this channel.")
    @commands.guild_only()
    async def games(self, ctx: commands.Context) -> None:
        arcade = self.bot.get_cog("Arcade")
        if arcade is None:
            await ctx.send(layout=build_game_layout("Games aren't ready", "Try again in a moment.", phase="lose"))
            return
        await arcade.send_menu(ctx)

    async def start_trivia(self, destination: commands.Context | discord.Interaction) -> None:
        question, correct, options = await self._get_trivia()
        view = TriviaView(correct, options, destination.user.id if isinstance(destination, discord.Interaction) else destination.author.id)
        author = destination.user if isinstance(destination, discord.Interaction) else destination.author
        host, host_avatar = _host_details(author)
        view.end_ts, _ = countdown_field(25)
        view.body_td.content = question
        view.countdown_td.content = f"⏳ Ends <t:{view.end_ts}:R>"
        view.footer_td.content = f"-# Started by {host}"
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(layout=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(layout=view)

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
                await destination.send(layout=build_game_layout("Can't do that", content, phase="lose"))
            return
        if opponent and opponent.bot:
            content = "Bots don't have hands. Leave the opponent blank to play against me."
            if isinstance(destination, discord.Interaction):
                await destination.response.send_message(content, ephemeral=True)
            else:
                await destination.send(layout=build_game_layout("Can't do that", content, phase="lose"))
            return
        view = RPSView(author, opponent)
        host, host_avatar = _host_details(author)
        view.end_ts, _ = countdown_field(60)
        if opponent is None:
            view.body_td.content = f"{author.mention}, pick your move. You're playing against me."
        else:
            view.body_td.content = f"{author.mention} challenged {opponent.mention}!\nBoth of you, pick a move."
        view.countdown_td.content = f"⏳ Ends <t:{view.end_ts}:R>"
        view.footer_td.content = f"-# Started by {host}"
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(layout=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(layout=view)

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
        view.body_td.content = view._content()
        view.countdown_td.content = f"⏳ Ends <t:{view.end_ts}:R>"
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(layout=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(layout=view)

    @commands.hybrid_command(name="wyr", aliases=["wouldyourather"], description="Start a would-you-rather vote.")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def wyr(self, ctx: commands.Context) -> None:
        await self.start_wyr(ctx)

    async def start_tod(self, destination: commands.Context | discord.Interaction, target: discord.Member) -> None:
        view = TODView(target)
        view.end_ts, _ = countdown_field(90)
        view.body_td.content = f"{target.mention}, pick **Truth**, **Dare**, or **Random**."
        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(layout=view)
            view.message = await destination.original_response()
        else:
            view.message = await destination.send(layout=view)

    @commands.hybrid_command(name="tod", aliases=["truthordare"], description="Start a truth or dare for yourself or someone else.")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    @app_commands.describe(member="Who has to choose? Defaults to you.")
    async def tod(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            await ctx.send(layout=build_game_layout("Server only", "This command can only be used in a server.", phase="lose"), ephemeral=True)
            return
        await self.start_tod(ctx, target)

    @commands.hybrid_command(name="truth", description="Get a random truth question.")
    @commands.guild_only()
    async def truth(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        await ctx.send(layout=build_game_layout(f"Truth for {_member_name(target)}", random.choice(TRUTHS)))

    @commands.hybrid_command(name="dare", description="Get a random dare.")
    @commands.guild_only()
    async def dare(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        await ctx.send(layout=build_game_layout(f"Dare for {_member_name(target)}", random.choice(DARES)))


    @commands.hybrid_command(name="eightball", aliases=["8ball", "eight_ball"], description="Ask the magic 8-ball a question.")
    async def eightball(self, ctx: commands.Context, *, question: str | None = None) -> None:
        from cogs.banks import EIGHTBALL
        answer = random.choice(EIGHTBALL)
        prompt = question.strip() if question else "The 8-ball says:"
        await ctx.send(layout=build_game_layout("8-ball", f"**{prompt}**\n\n{answer}"))

    @commands.hybrid_command(name="setcounting", description="Set or clear the counting channel.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="The counting channel. Omit to clear it.")
    async def setcounting(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        assert ctx.guild
        if channel is None:
            await self.bot.db.update_settings(ctx.guild.id, counting_next=1, counting_last_user=None)
            await self.bot.db.set_feature_channel(ctx.guild.id, "counting", None)
            await ctx.send(layout=build_game_layout("Counting disabled", "I won't look for a counting channel any more."))
            return
        await self.bot.db.update_settings(ctx.guild.id, counting_next=1, counting_last_user=None)
        await self.bot.db.set_feature_channel(ctx.guild.id, "counting", channel.id)
        await ctx.send(
            layout=build_game_layout(
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
                await message.channel.send(layout=build_game_layout("Nice streak!", f"The server just hit **{expected}**! High score: **{high}**."))
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
                layout=build_game_layout("Streak broken", f"{message.author.mention} — {reason}\nHigh score: **{high}**.", phase="lose")
            )
        except discord.HTTPException:
            pass


    @commands.hybrid_command(name="endgame", aliases=["stopgame"], description="End the game running in this channel.")
    @commands.guild_only()
    async def endgame(self, ctx: commands.Context) -> None:
        game = self.bot.game_sessions.peek(ctx.channel.id)
        if game is None:
            await ctx.send(layout=build_game_layout("No game running", "There's no game to end in this channel.", phase="lose"), ephemeral=True)
            return
        try:
            await game.finish()
        except Exception:
            self.bot.game_sessions.end(ctx.channel.id)
        await ctx.send(layout=build_game_layout("Game ended", "The channel is free — you can start a new game.", phase="win"))


async def setup(bot: SocializeBot) -> None:
    await bot.add_cog(Games(bot))
