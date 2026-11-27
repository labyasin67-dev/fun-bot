"""Phase 0 preconditions: discord.py >= 2.6.0 and Components V2 classes exist."""

import unittest

import discord


class V2PreconditionsTests(unittest.TestCase):
    def test_discord_version_at_least_2_6_0(self):
        version = discord.__version__
        parts = tuple(int(x) for x in version.split(".")[:2])
        self.assertGreaterEqual(parts, (2, 6), f"discord.py {version} is too old; need >= 2.6.0")

    def test_components_v2_classes_exist(self):
        self.assertTrue(hasattr(discord.ui, "LayoutView"), "discord.ui.LayoutView missing")
        self.assertTrue(hasattr(discord.ui, "Container"), "discord.ui.Container missing")
        self.assertTrue(hasattr(discord.ui, "TextDisplay"), "discord.ui.TextDisplay missing")
        self.assertTrue(hasattr(discord.ui, "Section"), "discord.ui.Section missing")
        self.assertTrue(hasattr(discord.ui, "Separator"), "discord.ui.Separator missing")
        self.assertTrue(hasattr(discord.ui, "MediaGallery"), "discord.ui.MediaGallery missing")
        self.assertTrue(hasattr(discord.ui, "Thumbnail"), "discord.ui.Thumbnail missing")
        self.assertTrue(hasattr(discord.ui, "ActionRow"), "discord.ui.ActionRow missing")

    def test_version_is_printed(self):
        # Confirm we can read the version (rendered in CI/test output).
        print(f"\ndiscord.py version: {discord.__version__}")


if __name__ == "__main__":
    unittest.main()
