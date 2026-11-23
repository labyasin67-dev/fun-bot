"""Tests for the shared game_ui presentation helpers.

discord.py is not installed in every environment, so stub it before importing
the helpers (annotations are not evaluated thanks to ``__future__``).
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
        self.fields: list[tuple[str, str, bool]] = []

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
    MAX_DESCRIPTION,
    MAX_FIELD_VALUE,
    MAX_TITLE,
    PHASE_COLORS,
    game_embed,
    game_footer,
    phase_color,
    phase_emoji,
    result_embed,
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
        name, value, _inline = embed.fields[0]
        self.assertLessEqual(len(name), 256)
        self.assertLessEqual(len(value), MAX_FIELD_VALUE)

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
        fields = dict((name, value) for name, value, _inline in embed.fields)
        self.assertEqual(fields["XP earned"], "+25 XP")
        self.assertEqual(fields["Play again"], "Run `.trivia` again.")

    def test_timeout_result_uses_timeout_colour(self):
        embed = result_embed("Trivia", "Nobody got it.", phase="timeout", answer="Mars")
        self.assertEqual(embed.color, WARNING)
        self.assertEqual(embed.title, "⏰ Trivia")


if __name__ == "__main__":
    unittest.main()