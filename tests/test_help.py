"""Help embed stays within Discord limits."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogs.help_cog import (
    EMBED_FIELD_LIMIT,
    EMBED_FIELD_VALUE_LIMIT,
    EMBED_TOTAL_LIMIT,
    HELP_SECTIONS,
    _embed_text_len,
    add_help_field,
    build_help_embeds,
)
from premium import CREDIT


class HelpEmbedTests(unittest.TestCase):
    def test_main_help_fits_discord_limits(self):
        embeds = build_help_embeds()
        self.assertTrue(embeds)
        self.assertLessEqual(len(embeds), 10)
        names = []
        for embed in embeds:
            self.assertLessEqual(len(embed.fields), EMBED_FIELD_LIMIT)
            self.assertLessEqual(_embed_text_len(embed), EMBED_TOTAL_LIMIT)
            self.assertEqual(embed.footer.text, CREDIT)
            for field in embed.fields:
                self.assertLessEqual(len(field.name or ""), 256)
                self.assertLessEqual(len(field.value or ""), EMBED_FIELD_VALUE_LIMIT)
                self.assertTrue(field.value)
                names.append(field.name)
        joined = " ".join(body for _title, body in HELP_SECTIONS)
        self.assertIn(".warn remove", joined)
        self.assertIn(".profile", joined)
        self.assertIn(".role manage", joined)
        self.assertIn(".roleremoveme", joined)
        # Every original fun command is still listed
        for cmd in ("slap", "kiss", "bonk", "yeet", "yes", "airkiss", "thumbsup"):
            self.assertIn(f".{cmd}", joined)
        self.assertTrue(any(n == "Fun" for n in names))
        self.assertTrue(any(n == "Roles" for n in names))

    def test_oversized_section_is_split_safely(self):
        huge = "x" * 2500
        leftover = []
        import discord
        from utils import embed as make_embed
        e = make_embed("Help", "intro", footer=CREDIT)
        leftover = add_help_field(e, "Big", huge)
        for field in e.fields:
            self.assertLessEqual(len(field.value or ""), EMBED_FIELD_VALUE_LIMIT)
        # All text is either on this embed or in leftover
        used = "".join(f.value for f in e.fields)
        rest = "".join(v for _n, v in leftover)
        self.assertEqual(used + rest, huge)
        embeds = build_help_embeds([("Big", huge)] * 8)
        for embed in embeds:
            self.assertLessEqual(_embed_text_len(embed), EMBED_TOTAL_LIMIT)
            self.assertLessEqual(len(embed.fields), EMBED_FIELD_LIMIT)


if __name__ == "__main__":
    unittest.main()
