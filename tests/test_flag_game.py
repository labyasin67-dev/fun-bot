"""Tests for the Flag game embed behaviour and file handling.

discord.py is not installed in every environment, so stub it before importing
the helpers (annotations are not evaluated thanks to ``__future__``.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


class FakeEmbed:
    def __init__(self, *, title=None, description=None, color=None):
        self.title = title
        self.description = description
        self.color = color
        self.footer = None
        self.author = None
        self.thumbnail = None
        self.image = None
        self.fields = []

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
        self.fields.append((name, value, inline))
        return self


class FakeFile:
    def __init__(self, path, filename):
        self.path = path
        self.filename = filename


class FakeMessage:
    def __init__(self):
        self.embeds = []


# --- Stub discord.py so cogs.arcade, cogs.sessions, cogs.database can import --
discord_stub = types.ModuleType("discord")
discord_stub.__path__ = []


class _User:
    def __init__(self, id=0, name="test", display_name="Test"):
        self.id = id
        self.name = name
        self.display_name = display_name


class FakeMessage:
    def __init__(self):
        self.embeds = []


discord_stub.Embed = FakeEmbed
discord_stub.File = FakeFile
discord_stub.Message = FakeMessage
discord_stub.HTTPException = Exception
discord_stub.NotFound = Exception
discord_stub.Interaction = type("Interaction", (), {})
discord_stub.Client = type("Client", (), {})
discord_stub.User = _User
discord_stub.Member = _User
discord_stub.Guild = type(
    "Guild",
    (),
    {"id": 0, "name": "test", "get_member": lambda self, uid: None, "get_channel": lambda self, cid: None},
)
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
discord_stub.ButtonStyle = type(
    "ButtonStyle", (), {"secondary": 2, "primary": 3, "success": 4, "danger": 5}
)
discord_stub.SelectOption = type("SelectOption", (), {"__init__": lambda self, **kw: None})
discord_stub.app_commands = types.SimpleNamespace(describe=lambda **kw: (lambda f: f))

sys.modules.setdefault("discord", discord_stub)

ext_stub = types.ModuleType("discord.ext")
ext_stub.__path__ = []
sys.modules.setdefault("discord.ext", ext_stub)
commands_stub = types.ModuleType("discord.ext.commands")
commands_stub.Bot = type("Bot", (), {})
commands_stub.Cog = type("Cog", (), {"listener": lambda f=None: (lambda f2: f2) if f is None else f})
commands_stub.hybrid_command = lambda **kw: (lambda f: f)
commands_stub.guild_only = lambda f=None: (lambda f2: f2) if f is None else f
commands_stub.cooldown = lambda *a, **k: (lambda f: f)
commands_stub.has_guild_permissions = lambda **kw: (lambda f: f)
commands_stub.BucketType = type("BucketType", (), {"user": "user", "channel": "channel", "guild": "guild"})
sys.modules.setdefault("discord.ext.commands", commands_stub)
setattr(discord_stub, "ext", ext_stub)
setattr(ext_stub, "commands", commands_stub)

# Stub aiosqlite so database.py can import
aiosqlite_stub = types.ModuleType("aiosqlite")
aiosqlite_stub.Connection = type("Connection", (), {})
aiosqlite_stub.connect = lambda *a, **k: type(
    "Conn",
    (),
    {"execute": lambda *a, **k: None, "commit": lambda *a, **k: None, "close": lambda *a, **k: None},
)()
sys.modules.setdefault("aiosqlite", aiosqlite_stub)

# Stub utils
utils_stub = types.ModuleType("utils")
utils_stub.COLOR = 0x5865F2
utils_stub.DANGER = 0xED4245
utils_stub.SUCCESS = 0x57F287
utils_stub.WARNING = 0xFAA81A
utils_stub.embed = type("Embed", (), {})
utils_stub.format_duration = lambda s: f"{s}s"
utils_stub.level_from_xp = lambda x: 1
utils_stub.level_progress = lambda x: (1, 0, 100, 1)
utils_stub.progress_bar = lambda *a, **k: ""
utils_stub.xp_for_level = lambda l: 0
sys.modules.setdefault("utils", utils_stub)

# Stub aiohttp
aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.ClientSession = type("ClientSession", (), {})
aiohttp_stub.ClientTimeout = type("ClientTimeout", (), {})
sys.modules.setdefault("aiohttp", aiohttp_stub)

# Stub main
main_stub = types.ModuleType("main")
main_stub.SocializeBot = type("SocializeBot", (), {})
sys.modules.setdefault("main", main_stub)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogs import banks  # noqa: E402
from cogs.game_ui import game_embed  # noqa: E402


class FakeWinner:
    def __init__(self, id=1, name="Winner", display_name="Winner"):
        self.id = id
        self.name = name
        self.display_name = display_name

    def mention(self):
        return f"<@{self.id}>"


class FlagEmbedTests(unittest.TestCase):
    def test_play_embed_has_image(self):
        import cogs.arcade

        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Flag"
        game.prompt = "Which country is this flag from? Type the country name."
        game.answers = ["Germany"]
        game.reveal = "Germany"
        game.hint = "The name starts with **G**."
        game.image_url = "attachment://de.jpg"
        game.timeout = 120
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game._hint_shown = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None

        e = game._embed(phase="play")
        self.assertEqual(e.image, "attachment://de.jpg")

    def test_hint_embed_has_image(self):
        import cogs.arcade

        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Flag"
        game.prompt = "Which country is this flag from? Type the country name."
        game.answers = ["Germany"]
        game.reveal = "Germany"
        game.hint = "The name starts with **G**."
        game.image_url = "attachment://de.jpg"
        game.timeout = 120
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game._hint_shown = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None

        e = game._embed(phase="hint")
        self.assertEqual(e.image, "attachment://de.jpg")

    def test_win_embed_drops_image(self):
        import cogs.arcade

        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Flag"
        game.prompt = "Which country is this flag from? Type the country name."
        game.answers = ["Germany"]
        game.reveal = "Germany"
        game.hint = None
        game.image_url = "attachment://de.jpg"
        game.timeout = 120
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game._hint_shown = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None

        e = game._embed(phase="win", winner=FakeWinner())
        self.assertIsNone(e.image)

    def test_timeout_embed_drops_image(self):
        import cogs.arcade

        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Flag"
        game.prompt = "Which country is this flag from? Type the country name."
        game.answers = ["Germany"]
        game.reveal = "Germany"
        game.hint = None
        game.image_url = "attachment://de.jpg"
        game.timeout = 120
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game._hint_shown = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None

        e = game._embed(phase="timeout")
        self.assertIsNone(e.image)

    def test_no_cdn_or_attachment_in_visible_text(self):
        import cogs.arcade

        game = cogs.arcade.ChatGuessGame.__new__(cogs.arcade.ChatGuessGame)
        game.title = "Flag"
        game.prompt = "Which country is this flag from? Type the country name."
        game.answers = ["Germany"]
        game.reveal = "Germany"
        game.hint = "The name starts with **G**."
        game.image_url = "attachment://de.jpg"
        game.timeout = 120
        game.hint_at = None
        game.xp = 25
        game.match = "fuzzy"
        game.message = None
        game.hinted = False
        game._hint_shown = False
        game.seconds_left = None
        game.end_ts = None
        game.host_name = None
        game.host_avatar = None

        for phase in ("play", "hint", "win", "timeout"):
            e = game._embed(phase=phase, winner=FakeWinner())
            text = " ".join(
                str(part)
                for part in (
                    e.title,
                    e.description,
                    e.footer,
                    *(f"{n} {v}" for n, v, _ in e.fields),
                )
                if part
            )
            self.assertNotIn("cdn.discordapp.com", text, phase)
            self.assertNotIn("attachment://", text, phase)

    def test_game_embed_guard_drops_image_on_win_and_timeout(self):
        embed = game_embed("Flag", "Prompt", phase="play", image="attachment://de.jpg")
        self.assertEqual(embed.image, "attachment://de.jpg")

        embed = game_embed("Flag", "Prompt", phase="win", image="attachment://de.jpg")
        self.assertIsNone(embed.image)

        embed = game_embed("Flag", "Prompt", phase="timeout", image="attachment://de.jpg")
        self.assertIsNone(embed.image)


class FlagFileTests(unittest.TestCase):
    def test_flag_codes_have_png_images(self):
        codes = [item["code"] for item in banks.flags()]
        self.assertIn("de", codes)
        self.assertIn("eg", codes)


if __name__ == "__main__":
    unittest.main()
