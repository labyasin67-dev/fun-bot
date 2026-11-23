"""Unit tests for the shared Components V2 design system (cogs/v2.py)."""

from __future__ import annotations

import importlib
import sys as _sys
import unittest

# Ensure the real discord.py package is bound; other test modules (e.g.
# test_game_ui) stub ``discord`` in sys.modules and leak it across the process.
if "discord" in _sys.modules and not getattr(_sys.modules["discord"], "__version__", None):
    del _sys.modules["discord"]
import discord


class _V2Base(unittest.TestCase):
    """Base that rebinds the real discord package before each test so a stub
    left behind by another test module cannot break Components V2 usage."""

    def setUp(self):
        global discord
        # Another test module (test_game_ui) can replace discord.ui with a stub.
        # Always rebind a fresh real discord package so Components V2 works.
        if "discord" in _sys.modules:
            del _sys.modules["discord"]
        discord = importlib.import_module("discord")

from cogs.v2 import (
    MAX_COMPONENTS,
    MAX_TEXT_DISPLAY,
    build_game_layout,
    countdown_field,
    countdown_text,
    phase_color,
    phase_emoji,
    result_layout,
)


class PhaseTests(_V2Base):
    def test_phase_colors(self):
        self.assertEqual(phase_color("play"), 0x7B5CFA)
        self.assertEqual(phase_color("hint"), 0xFEE75C)
        self.assertEqual(phase_color("win"), 0x3BA55D)
        self.assertEqual(phase_color("lose"), 0xED4245)
        self.assertEqual(phase_color("timeout"), 0xFEE75C)
        self.assertEqual(phase_color("unknown"), 0x7B5CFA)

    def test_phase_emojis(self):
        self.assertEqual(phase_emoji("play"), "🎮")
        self.assertEqual(phase_emoji("hint"), "💡")
        self.assertEqual(phase_emoji("win"), "🏆")
        self.assertEqual(phase_emoji("lose"), "❌")
        self.assertEqual(phase_emoji("timeout"), "⏰")


class CountdownTextTests(_V2Base):
    def test_live_wording(self):
        self.assertEqual(countdown_text(1_700_000_000), "⏳ Ends <t:1700000000:R>")

    def test_ended_wording_keeps_same_timestamp(self):
        self.assertEqual(countdown_text(1_700_000_000, ended=True), "✅ Ended <t:1700000000:R>")

    def test_countdown_field_seconds(self):
        end_ts, text = countdown_field(30)
        self.assertGreater(end_ts, 0)
        self.assertEqual(text, f"⏳ Ends <t:{end_ts}:R>")

    def test_countdown_field_zero_seconds(self):
        end_ts, text = countdown_field(0)
        self.assertEqual(text, f"⏳ Ends <t:{end_ts}:R>")

    def test_timeout_wording(self):
        self.assertEqual(countdown_text(1_700_000_000, timeout=True), "⌛ Time's up <t:1700000000:R>")

    def test_ended_at_custom_timestamp(self):
        self.assertEqual(countdown_text(1_700_000_000, ended=True), "✅ Ended <t:1700000000:R>")


class BuildGameLayoutTests(_V2Base):
    def test_layout_is_layout_view(self):
        layout = build_game_layout("Button Hunt", "Press the button.", emoji="🔘")
        self.assertIsInstance(layout, discord.ui.LayoutView)
        self.assertIsInstance(layout.container, discord.ui.Container)

    def test_title_and_body_set(self):
        layout = build_game_layout("Button Hunt", "Press the button.", emoji="🔘")
        self.assertIn("# 🔘 Button Hunt", layout.title_td.content)
        self.assertEqual(layout.body_td.content, "Press the button.")

    def test_phase_sets_accent_colour(self):
        layout = build_game_layout("G", "b", phase="win")
        self.assertEqual(layout.container.accent_color, 0x3BA55D)
        layout.set_phase("lose")
        self.assertEqual(layout.container.accent_color, 0xED4245)

    def test_set_hint_replaces(self):
        layout = build_game_layout("G", "b", hint_text="First hint")
        self.assertEqual(layout.hint_td.content, "First hint")
        layout.set_hint("Second hint")
        self.assertEqual(layout.hint_td.content, "Second hint")

    def test_set_countdown_replaces_not_duplicates(self):
        layout = build_game_layout("G", "b", countdown="⏳ Ends <t:100:R>")
        self.assertEqual(layout.countdown_td.content, "⏳ Ends <t:100:R>")
        layout.set_countdown(200)
        self.assertEqual(layout.countdown_td.content, "⏳ Ends <t:200:R>")
        # Only one countdown text display exists.
        countdown_tds = [c for c in layout.container.children if isinstance(c, discord.ui.TextDisplay) and c.content.startswith("⏳")]
        self.assertEqual(len(countdown_tds), 1)

    def test_countdown_ended_wording(self):
        layout = build_game_layout("G", "b", countdown="⏳ Ends <t:100:R>")
        layout.set_countdown(100, ended=True)
        self.assertEqual(layout.countdown_td.content, "✅ Ended <t:100:R>")

    def test_countdown_timeout_wording(self):
        layout = build_game_layout("G", "b", countdown="⏳ Ends <t:100:R>")
        layout.set_countdown(100, timeout=True)
        self.assertEqual(layout.countdown_td.content, "⌛ Time's up <t:100:R>")

    def test_countdown_ended_at_custom(self):
        layout = build_game_layout("G", "b", countdown="⏳ Ends <t:100:R>")
        layout.set_countdown(200, ended=True)
        self.assertEqual(layout.countdown_td.content, "✅ Ended <t:200:R>")
        self.assertEqual(layout.end_ts, 200)

    def test_host_avatar_section(self):
        layout = build_game_layout("G", "b", host="Alice", host_avatar="https://example.com/a.png")
        self.assertIsNotNone(layout.section)
        self.assertIsInstance(layout.section.accessory, discord.ui.Thumbnail)

    def test_media_gallery(self):
        layout = build_game_layout("G", "b", image_url="https://example.com/flag.png")
        self.assertIsInstance(layout.media_gallery, discord.ui.MediaGallery)

    def test_action_rows_buttons(self):
        b1 = discord.ui.Button(label="A", custom_id="a", style=discord.ButtonStyle.primary)
        b2 = discord.ui.Button(label="B", custom_id="b", style=discord.ButtonStyle.secondary)
        layout = build_game_layout("G", "b", items=(b1, b2))
        self.assertEqual(len(layout.action_rows), 1)
        self.assertEqual(len(layout.action_rows[0].children), 2)

    def test_select_owns_its_row(self):
        select = discord.ui.Select(placeholder="Choose", custom_id="s")
        b = discord.ui.Button(label="B", custom_id="bb")
        layout = build_game_layout("G", "b", items=(select, b))
        # Select gets its own row; button gets another.
        self.assertEqual(len(layout.action_rows), 2)

    def test_disable_items_disables_everything(self):
        b1 = discord.ui.Button(label="A", custom_id="a")
        b2 = discord.ui.Button(label="B", custom_id="b")
        select = discord.ui.Select(placeholder="Choose", custom_id="s")
        layout = build_game_layout("G", "b", items=(b1, b2, select))
        layout.disable_items()
        for row in layout.action_rows:
            for child in row.children:
                if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                    self.assertTrue(child.disabled)

    def test_component_count_under_limit(self):
        items = [discord.ui.Button(label=f"B{i}", custom_id=f"b{i}") for i in range(6)]
        layout = build_game_layout("G", "b", items=tuple(items))
        total = sum(len(getattr(row, "children", [])) for row in layout.action_rows)
        total += len([c for c in layout.container.children if not isinstance(c, discord.ActionRow)])
        self.assertLessEqual(total, MAX_COMPONENTS)

    def test_text_under_limit(self):
        layout = build_game_layout("G", "x" * 5000)
        self.assertEqual(len(layout.body_td.content), MAX_TEXT_DISPLAY)
        self.assertLessEqual(layout.total_text_length(), MAX_TEXT_DISPLAY + 10)


class ResultLayoutTests(_V2Base):
    def test_result_contains_answer_xp_play_again(self):
        layout = result_layout(
            "Trivia",
            "You got it!",
            phase="win",
            answer="Paris",
            xp=25,
            play_again="Play again with `.trivia`.",
            winner="@Alice",
            winner_avatar="https://example.com/a.png",
        )
        self.assertIsInstance(layout, discord.ui.LayoutView)
        self.assertIn("**Answer:** Paris", layout.body_td.content)
        self.assertIn("**XP earned:** +25 XP", layout.body_td.content)
        self.assertIn("Play again with `.trivia`.", layout.body_td.content)
        self.assertIsNotNone(layout.section)

    def test_result_lose_phase_colour(self):
        layout = result_layout("HILO", "Streak ended.", phase="lose")
        self.assertEqual(layout.container.accent_color, 0xED4245)

    def test_result_footer_host(self):
        layout = result_layout("G", "b", host="Alice", host_avatar="https://example.com/a.png")
        self.assertIn("Started by Alice", layout.footer_td.content)


if __name__ == "__main__":
    unittest.main()
