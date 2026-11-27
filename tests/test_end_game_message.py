"""Tests for the end_game_message helper used at every game ending."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

# cogs.sessions imports discord at module level, which may not be installed in
# every environment. Stub it so the helper can be imported and tested in
# isolation (annotations are not evaluated thanks to __future__).
discord_stub = types.ModuleType("discord")


class _User:
    pass


discord_stub.Interaction = _User
discord_stub.abc = types.SimpleNamespace(User=_User)
sys.modules.setdefault("discord", discord_stub)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogs.sessions import end_game_message  # noqa: E402


class FakeChild:
    def __init__(self) -> None:
        self.disabled = False


class FakeView:
    def __init__(self) -> None:
        self.children = [FakeChild(), FakeChild()]


class FakeMessage:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.edit_calls: list[tuple] = []

    async def edit(self, *, view=None, embed=None) -> None:
        self.edit_calls.append((view, embed))


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, *, embed=None) -> None:
        self.sent.append(embed)


class EndGameMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_disables_controls_keeps_embed_posts_result_separately(self):
        channel = FakeChannel()
        view = FakeView()
        message = FakeMessage(channel)
        result_embed = object()

        await end_game_message(message, result_embed, view)

        self.assertTrue(all(child.disabled for child in view.children))
        # Only the view (disabled controls) is edited; the original embed is kept.
        self.assertEqual(message.edit_calls, [(view, None)])
        # The result is posted as a separate message.
        self.assertEqual(channel.sent, [result_embed])

    async def test_without_view_still_posts_result(self):
        channel = FakeChannel()
        message = FakeMessage(channel)
        result_embed = object()

        await end_game_message(message, result_embed)

        self.assertEqual(message.edit_calls, [])
        self.assertEqual(channel.sent, [result_embed])

    async def test_failures_are_swallowed(self):
        channel = FakeChannel()
        message = FakeMessage(channel)

        async def boom(**kwargs):
            raise RuntimeError("boom")

        message.edit = boom  # type: ignore[assignment]
        channel.send = boom  # type: ignore[assignment]

        await end_game_message(message, object())  # must not raise


if __name__ == "__main__":
    unittest.main()
