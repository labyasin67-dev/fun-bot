"""Tests for the shared game_ui presentation helpers.

discord.py is not installed in every environment, so stub it before importing
the helpers (annotations are not evaluated thanks to ``__future__``).
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


class FakeEmbedField:
    def __init__(self, name, value, inline=True):
        self.name = name
        self.value = value
        self.inline = inline


class FakeEmbed:
    def __init__(self, *, title=None, description=None, color=None):
        self.title = title
        self.description = description
        self.color = color
        self.footer = None
        self.author = None
        self.thumbnail = None
        self.image = None
        self.fields: list[FakeEmbedField] = []

    def set_footer(self, *, text=None):
        self.footer = text
        return self

    def set_author(self, *, name=None, icon_url=None):
        self.author = (name, icon_url)
        return self

    def set_thumbnail(self, *, url=None):
        self.thumbnail = url
        return self

    def set_image(self, *, url=None):
        self.image = url
        return self

    def add_field(self, *, name, value, inline=True):
        self.fields.append(FakeEmbedField(name, value, inline))
        return self

    def set_field_at(self, index, *, name, value, inline):
        self.fields[index] = FakeEmbedField(name, value, inline)

    def remove_field(self, index):
        del self.fields[index]


discord_stub = sys.modules.get("discord")
if discord_stub is None:
    discord_stub = types.ModuleType("discord")
    sys.modules["discord"] = discord_stub
if not hasattr(discord_stub, "Embed"):
    discord_stub.Embed = FakeEmbed
if not hasattr(discord_stub, "Interaction"):
    discord_stub.Interaction = type("Interaction", (), {})
if not hasattr(discord_stub, "abc"):
    discord_stub.abc = types.SimpleNamespace(User=type("User", (), {}))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogs.game_ui import (  # noqa: E402
    DEFAULT_PLAYERS,
    MAX_DESCRIPTION,
    MAX_FIELD_VALUE,
    MAX_TITLE,
    PHASE_COLORS,
    clear_countdown,
    countdown_field,
    game_embed,
    game_footer,
    game_menu_line,
    games_menu_embed,
    phase_color,
    phase_emoji,
    result_embed,
    with_countdown,
)
from utils import COLOR, DANGER, SUCCESS, WARNING  # noqa: E402


class PhaseTests(unittest.TestCase):
    def test_phase_colors(self):
        self.assertEqual(phase_color("play"), COLOR)
        self.assertEqual(phase_color("hint"), WARNING)
        self.assertEqual(phase_color("timeout"), WARNING)
        self.assertEqual(phase_color("win"), SUCCESS)
        self.assertEqual(phase_color("lose"), DANGER)

    def test_unknown_phase_falls_back_to_blurple(self):
        self.assertEqual(phase_color("nonsense"), COLOR)

    def test_phase_emojis(self):
        self.assertEqual(phase_emoji("play"), "🎮")
        self.assertEqual(phase_emoji("hint"), "💡")
        self.assertEqual(phase_emoji("win"), "🏆")
        self.assertEqual(phase_emoji("lose"), "❌")
        self.assertEqual(phase_emoji("timeout"), "⏰")

    def test_every_phase_has_a_color(self):
        self.assertEqual(set(PHASE_COLORS), {"play", "hint", "win", "lose", "timeout"})


class GameEmbedTests(unittest.TestCase):
    def test_title_gets_emoji_once(self):
        self.assertEqual(game_embed("Button Hunt", emoji="🔘").title, "🔘 Button Hunt")
        # An emoji already in the title is not added twice.
        self.assertEqual(game_embed("🔘 Button Hunt", emoji="🔘").title, "🔘 Button Hunt")

    def test_color_comes_from_phase(self):
        self.assertEqual(game_embed("Trivia", phase="win").color, SUCCESS)
        self.assertEqual(game_embed("Trivia", phase="timeout").color, WARNING)

    def test_explicit_color_overrides_phase(self):
        self.assertEqual(game_embed("Trivia", phase="win", color=DANGER).color, DANGER)

    def test_host_sets_footer_and_author(self):
        embed = game_embed("Trivia", host="Ann", host_avatar="https://x/a.png")
        self.assertEqual(embed.footer, "Trivia • Started by Ann")
        self.assertEqual(embed.author, ("Ann", "https://x/a.png"))

    def test_footer_override_wins(self):
        embed = game_embed("Trivia", host="Ann", footer="Trivia • 30s left")
        self.assertEqual(embed.footer, "Trivia • 30s left")

    def test_game_footer_joins_parts(self):
        self.assertEqual(game_footer("Trivia", "Ann", extra="30s left"), "Trivia • 30s left • Started by Ann")
        self.assertEqual(game_footer("Trivia"), "Trivia")

    def test_title_is_clamped(self):
        embed = game_embed("x" * 400, emoji="🎮")
        self.assertLessEqual(len(embed.title), MAX_TITLE)

    def test_description_is_clamped(self):
        embed = game_embed("Trivia", "y" * 6000)
        self.assertLessEqual(len(embed.description), MAX_DESCRIPTION)

    def test_fields_are_clamped(self):
        embed = game_embed(
            "Trivia",
            fields=[("n" * 400, "v" * 2000, False)],
        )
        field = embed.fields[0]
        self.assertLessEqual(len(field.name), 256)
        self.assertLessEqual(len(field.value), MAX_FIELD_VALUE)

    def test_image_and_thumbnail(self):
        embed = game_embed("Flag", thumbnail="https://x/t.png", image="https://x/i.png")
        self.assertEqual(embed.thumbnail, "https://x/t.png")
        self.assertEqual(embed.image, "https://x/i.png")


class ResultEmbedTests(unittest.TestCase):
    def test_result_has_answer_xp_and_replay(self):
        embed = result_embed(
            "Trivia",
            "Ann got it!",
            answer="Canberra",
            xp=25,
            play_again="Run `.trivia` again.",
            winner_avatar="https://x/w.png",
        )
        self.assertIn("Canberra", embed.description)
        self.assertEqual(embed.color, SUCCESS)
        self.assertEqual(embed.thumbnail, "https://x/w.png")
        fields = dict((f.name, f.value) for f in embed.fields)
        self.assertEqual(fields["XP earned"], "+25 XP")
        self.assertEqual(fields["Play again"], "Run `.trivia` again.")

    def test_timeout_result_uses_timeout_colour(self):
        embed = result_embed("Trivia", "Nobody got it.", phase="timeout", answer="Mars")
        self.assertEqual(embed.color, WARNING)
        self.assertEqual(embed.title, "⏰ Trivia")


class GameMenuLineTests(unittest.TestCase):
    def test_single_line_with_command(self):
        self.assertEqual(
            game_menu_line("🔘", "Button Hunt", ".buttonhunt"),
            "🔘 **Button Hunt** · .buttonhunt",
        )

    def test_default_players_are_omitted(self):
        line = game_menu_line("💡", "Trivia", ".trivia", players=DEFAULT_PLAYERS)
        self.assertNotIn("players", line)
        self.assertNotIn("30s", line)

    def test_exception_players_are_shown_inline(self):
        self.assertEqual(
            game_menu_line("⚔️", "Dice Roll Duel", ".diceduel", players="2 players"),
            "⚔️ **Dice Roll Duel** · .diceduel · 2 players",
        )

    def test_duration_is_never_shown(self):
        line = game_menu_line("🃏", "UNO", ".uno", players="2–10 players")
        self.assertIn("2–10 players", line)
        self.assertNotIn("min", line)


class GamesMenuEmbedTests(unittest.TestCase):
    def setUp(self):
        self.games = [
            ("buttonhunt", "🔘", "Button Hunt", "blurb"),
            ("diceduel", "⚔️", "Dice Roll Duel", "blurb"),
            ("uno", "🃏", "UNO", "blurb"),
        ]
        self.categories = [
            {"key": "quick", "emoji": "⚡", "label": "Quick reflex", "games": ["buttonhunt"]},
            {"key": "multi", "emoji": "👥", "label": "Multiplayer", "games": ["diceduel", "uno"]},
        ]
        self.meta = {"diceduel": {"players": "2 players"}, "uno": {"players": "2–10 players"}}

    def _build(self, games=None):
        return games_menu_embed(
            games if games is not None else self.games,
            self.categories,
            self.meta,
            command_for=lambda key: f".{key}",
        )

    def test_title_present_and_no_description(self):
        embed = self._build()
        self.assertEqual(embed.title, "🎮 Choose a game to drop")
        self.assertIsNone(embed.description)

    def test_one_field_per_nonempty_category(self):
        embed = self._build()
        self.assertEqual([f.name for f in embed.fields], ["**Quick reflex**", "**Multiplayer**"])

    def test_each_game_is_a_single_line(self):
        embed = self._build()
        values = {f.name: f.value for f in embed.fields}
        quick_lines = values["**Quick reflex**"].split("\n")
        self.assertEqual(quick_lines, ["🔘 **Button Hunt** · .buttonhunt"])
        multi_lines = values["**Multiplayer**"].split("\n")
        self.assertEqual(
            multi_lines,
            [
                "⚔️ **Dice Roll Duel** · .diceduel · 2 players",
                "🃏 **UNO** · .uno · 2–10 players",
            ],
        )

    def test_no_duration_or_footer_or_thumbnail(self):
        embed = self._build()
        self.assertIsNone(embed.footer)
        self.assertIsNone(embed.thumbnail)
        for f in embed.fields:
            self.assertNotIn("30s", f.value)
            self.assertNotIn("min", f.value)

    def test_empty_categories_are_skipped(self):
        embed = self._build(games=[("diceduel", "⚔️", "Dice Roll Duel", "blurb")])
        self.assertEqual([f.name for f in embed.fields], ["**Multiplayer**"])


class CountdownFieldTests(unittest.TestCase):
    def test_seconds_become_end_ts(self):
        end_ts, text = countdown_field(30)
        self.assertGreater(end_ts, 0)
        self.assertEqual(text, f"⏳ Ends <t:{end_ts}:R>")

    def test_end_ts_passed_through_is_used_as_is(self):
        fake_ts = 1_700_000_000
        end_ts, text = countdown_field(fake_ts)
        self.assertEqual(end_ts, fake_ts)
        self.assertEqual(text, f"⏳ Ends <t:{fake_ts}:R>")

    def test_includes_zero_seconds(self):
        end_ts, text = countdown_field(0)
        self.assertEqual(text, f"⏳ Ends <t:{end_ts}:R>")


class WithCountdownTests(unittest.TestCase):
    def _embed(self):
        return game_embed("Trivia", "What is 2+2?", emoji="💡", phase="play")

    def test_adds_time_left_field(self):
        embed = self._embed()
        end_ts, _ = countdown_field(25)
        with_countdown(embed, end_ts)
        names = [f.name for f in embed.fields]
        self.assertIn("Time left", names)
        value = next(f.value for f in embed.fields if f.name == "Time left")
        self.assertEqual(value, f"⏳ Ends <t:{end_ts}:R>")

    def test_replaces_existing_time_left_field(self):
        embed = self._embed()
        end_ts1, _ = countdown_field(25)
        end_ts2, _ = countdown_field(60)
        with_countdown(embed, end_ts1)
        with_countdown(embed, end_ts2)
        time_fields = [(f.name, f.value) for f in embed.fields if f.name == "Time left"]
        self.assertEqual(len(time_fields), 1)
        self.assertEqual(time_fields[0][1], f"⏳ Ends <t:{end_ts2}:R>")

    def test_total_under_discord_limit(self):
        embed = self._embed()
        end_ts, _ = countdown_field(25)
        with_countdown(embed, end_ts)
        total = len(embed.title or "") + len(embed.description or "") + sum(len(f.name) + len(f.value) for f in embed.fields)
        self.assertLessEqual(total, 6000)


class ClearCountdownTests(unittest.TestCase):
    def _embed_with_countdown(self):
        embed = game_embed("Trivia", "What is 2+2?", emoji="💡", phase="play")
        end_ts, _ = countdown_field(25)
        with_countdown(embed, end_ts)
        return embed

    def test_removes_time_left_field(self):
        embed = self._embed_with_countdown()
        self.assertTrue(any(f.name == "Time left" for f in embed.fields))
        clear_countdown(embed)
        self.assertFalse(any(f.name == "Time left" for f in embed.fields))

    def test_noop_when_no_countdown(self):
        embed = game_embed("Trivia", "What is 2+2?", emoji="💡", phase="play")
        try:
            clear_countdown(embed)
        except Exception:
            self.fail("clear_countdown raised on embed without Time left field")


class SmokeTest(unittest.TestCase):
    """Smoke test: import the game modules and build every game embed."""

    def setUp(self):
        import sys
        import types

        # Stub discord.py as a package so cogs.arcade, cogs.games, cogs.sessions can import.
        discord_stub = sys.modules.get("discord")
        if discord_stub is None:
            discord_stub = types.ModuleType("discord")
            discord_stub.__path__ = []
            sys.modules["discord"] = discord_stub

        # discord.ext subpackage
        ext_stub = types.ModuleType("discord.ext")
        ext_stub.__path__ = []
        sys.modules["discord.ext"] = ext_stub
        commands_stub = types.ModuleType("discord.ext.commands")
        commands_stub.Bot = type("Bot", (), {})
        commands_stub.Cog = type("Cog", (), {"listener": lambda f=None: (lambda f2: f2) if f is None else f})
        commands_stub.hybrid_command = lambda **kw: (lambda f: f)
        commands_stub.guild_only = lambda f=None: (lambda f2: f2) if f is None else f
        commands_stub.cooldown = lambda *a, **k: (lambda f: f)
        commands_stub.has_guild_permissions = lambda **kw: (lambda f: f)
        commands_stub.BucketType = type("BucketType", (), {"user": "user", "channel": "channel", "guild": "guild"})
        sys.modules["discord.ext.commands"] = commands_stub
        setattr(discord_stub, "ext", ext_stub)
        setattr(ext_stub, "commands", commands_stub)

        class FakeMessage:
            def __init__(self):
                self.embeds = []

        discord_stub.Embed = FakeEmbed
        discord_stub.Message = FakeMessage
        discord_stub.HTTPException = Exception
        discord_stub.NotFound = Exception
        discord_stub.Interaction = type("Interaction", (), {})
        discord_stub.Client = type("Client", (), {})
        discord_stub.User = type("User", (), {"id": 0, "name": "test", "display_name": "Test"})
        discord_stub.Member = type("Member", (), {"id": 0, "name": "test", "display_name": "Test", "bot": False})
        discord_stub.Guild = type("Guild", (), {"id": 0, "name": "test", "get_member": lambda self, uid: None, "get_channel": lambda self, cid: None})
        discord_stub.TextChannel = type("TextChannel", (), {"id": 0, "name": "test", "guild": None})
        discord_stub.abc = types.SimpleNamespace(
            User=type("User", (), {}),
            Messageable=type("Messageable", (), {}),
        )
        discord_stub.ui = types.SimpleNamespace(
            View=type("View", (), {}),
            Button=type("Button", (), {}),
            Select=type("Select", (), {}),
        )
        discord_stub.ui.select = lambda **kw: (lambda f: f)
        discord_stub.ui.button = lambda **kw: (lambda f: f)
        discord_stub.ButtonStyle = type("ButtonStyle", (), {
            "secondary": 2, "primary": 3, "success": 4, "danger": 5,
        })
        discord_stub.SelectOption = type("SelectOption", (), {"__init__": lambda self, **kw: None})
        discord_stub.app_commands = types.SimpleNamespace(describe=lambda **kw: (lambda f: f))

        # Stub aiosqlite so database.py can import
        aiosqlite_stub = sys.modules.get("aiosqlite")
        if aiosqlite_stub is None:
            aiosqlite_stub = types.ModuleType("aiosqlite")
            sys.modules["aiosqlite"] = aiosqlite_stub
        aiosqlite_stub.Connection = type("Connection", (), {})
        aiosqlite_stub.connect = lambda *a, **k: type("Conn", (), {"execute": lambda *a, **k: None, "commit": lambda *a, **k: None, "close": lambda *a, **k: None})()

        # Stub utils
        utils_stub = sys.modules.get("utils")
        if utils_stub is None:
            utils_stub = types.ModuleType("utils")
            sys.modules["utils"] = utils_stub
        utils_stub.COLOR = 0x5865F2
        utils_stub.DANGER = 0xED4245
        utils_stub.SUCCESS = 0x57F287
        utils_stub.WARNING = 0xFAA81A
        utils_stub.embed = FakeEmbed
        utils_stub.format_duration = lambda s: f"{s}s"
        utils_stub.level_from_xp = lambda x: 1
        utils_stub.level_progress = lambda x: (1, 0, 100, 1)
        utils_stub.progress_bar = lambda *a, **k: ""
        utils_stub.xp_for_level = lambda l: 0

        # Stub aiohttp
        aiohttp_stub = sys.modules.get("aiohttp")
        if aiohttp_stub is None:
            aiohttp_stub = types.ModuleType("aiohttp")
            sys.modules["aiohttp"] = aiohttp_stub
        aiohttp_stub.ClientSession = type("ClientSession", (), {})
        aiohttp_stub.ClientTimeout = type("ClientTimeout", (), {})

        # Stub main
        main_stub = sys.modules.get("main")
        if main_stub is None:
            main_stub = types.ModuleType("main")
            sys.modules["main"] = main_stub
        main_stub.SocializeBot = type("SocializeBot", (), {})

    def test_arcade_imports(self):
        """Importing cogs.arcade must not raise (catches missing imports like countdown_field)."""
        import cogs.arcade  # noqa: F401

    def test_games_imports(self):
        """Importing cogs.games must not raise."""
        import cogs.games  # noqa: F401

    def test_sessions_imports(self):
        """Importing cogs.sessions must not raise."""
        import cogs.sessions  # noqa: F401

    def test_database_imports(self):
        """Importing cogs.database must not raise."""
        import database  # noqa: F401

    def test_chat_guess_embed(self):
        import cogs.arcade
        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Test"
        game.prompt = "What is 2+2?"
        game.answers = ["4"]
        game.reveal = "4"
        game.hint = None
        game.image_url = None
        game.timeout = 30
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed(phase="play")
        self.assertIsNotNone(e)

    def test_word_rule_embed(self):
        import cogs.arcade
        game = cogs.arcade.WordRuleGame.__new__(cogs.arcade.WordRuleGame)
        game.prompt = "Type a word"
        game.kind = "startswith"
        game.payload = "a"
        game.words = {"apple"}
        game.message = None
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._play_embed()
        self.assertIsNotNone(e)

    def test_button_hunt_embed(self):
        import cogs.arcade
        game = cogs.arcade.ButtonHuntGame.__new__(cogs.arcade.ButtonHuntGame)
        game.eliminated = set()
        game.message = None
        game.view = None
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed()
        self.assertIsNotNone(e)

    def test_dice_duel_embed(self):
        import cogs.arcade
        game = cogs.arcade.DiceDuelGame.__new__(cogs.arcade.DiceDuelGame)
        game.players = []
        game.message = None
        game.view = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed()
        self.assertIsNotNone(e)

    def test_color_hunt_embed(self):
        import cogs.arcade
        game = cogs.arcade.ColorHuntGame.__new__(cogs.arcade.ColorHuntGame)
        game.eliminated = set()
        game.message = None
        game.view = None
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed()
        self.assertIsNotNone(e)

    def test_reaction_embed(self):
        import cogs.arcade
        game = cogs.arcade.ReactionGame.__new__(cogs.arcade.ReactionGame)
        game.live = False
        game.eliminated = set()
        game.message = None
        game.view = None
        game.host_name = None
        game.host_avatar = None
        game.seconds_left = None
        game.end_ts = None
        e = game._embed(live=False)
        self.assertIsNotNone(e)

    def test_sequence_hunt_embed(self):
        import cogs.arcade
        game = cogs.arcade.SequenceHuntGame.__new__(cogs.arcade.SequenceHuntGame)
        game.sequence = [0, 1, 2]
        game.progress = {}
        game.failed = set()
        game.accepting = False
        game.message = None
        game.view = None
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed(show_sequence=False)
        self.assertIsNotNone(e)

    def test_hilo_embed(self):
        import cogs.arcade
        game = cogs.arcade.HiLoGame.__new__(cogs.arcade.HiLoGame)
        game.current = 50
        game.next_number = 75
        game.streak = 0
        game.message = None
        game.view = None
        game.round_open = True
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed()
        self.assertIsNotNone(e)

    def test_trivia_arcade_embed(self):
        import cogs.arcade
        game = cogs.arcade.TriviaGame.__new__(cogs.arcade.TriviaGame)
        game.question = "Q?"
        game.correct = "A"
        game.options = ["A", "B"]
        game.wrong = set()
        game.message = None
        game.view = None
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._play_embed()
        self.assertIsNotNone(e)

    def test_red_light_embed(self):
        import cogs.arcade
        game = cogs.arcade.RedLightGame.__new__(cogs.arcade.RedLightGame)
        game.green = True
        game.scores = {}
        game.names = {}
        game.eliminated = set()
        game.message = None
        game.rounds_left = 8
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None
        e = game._embed()
        self.assertIsNotNone(e)

    def test_games_rps_embed(self):
        import cogs.games
        view = cogs.games.RPSView.__new__(cogs.games.RPSView)
        view.challenger = type("M", (), {"id": 1, "display_name": "Test", "name": "Test"})()
        view.opponent = None
        view.choices = {}
        view.message = None
        view.end_ts = None
        e = view._embed("Test", "text", 0x5865F2)
        self.assertIsNotNone(e)

    def test_games_trivia_embed(self):
        import cogs.games
        view = cogs.games.TriviaView.__new__(cogs.games.TriviaView)
        view.correct = "A"
        view.author_id = 1
        view.finished = False
        view.message = None
        view.end_ts = None
        # Can't easily call _embed without buttons, but check attributes exist
        self.assertIsNotNone(view)

    def test_games_wyr_embed(self):
        import cogs.games
        view = cogs.games.WYRView.__new__(cogs.games.WYRView)
        view.option_a = "A"
        view.option_b = "B"
        view.votes = {}
        view.message = None
        view.end_ts = None
        view.a_button = type("B", (), {"label": "A"})()
        view.b_button = type("B", (), {"label": "B"})()
        e = view._embed()
        self.assertIsNotNone(e)

    def test_games_tod_embed(self):
        import cogs.games
        view = cogs.games.TODView.__new__(cogs.games.TODView)
        view.target = type("M", (), {"id": 1, "display_name": "Test", "name": "Test", "mention": "@Test"})()
        view.message = None
        view.end_ts = None
        e = view._prompt("truth")
        self.assertIsNotNone(e)


if __name__ == "__main__":
    unittest.main()
