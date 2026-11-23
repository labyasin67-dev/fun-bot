"""Tests that every message send/edit uses ``view=`` (LayoutView) and never
``layout=``, ``embed=``, ``embeds=``, or ``content=`` keyword arguments.

Also constructs a real ``discord.ui.LayoutView`` and pushes it through a
stubbed discord HTTP layer to confirm discord.py accepts it.
"""

from __future__ import annotations

import asyncio
import os
import re
import unittest
from unittest.mock import patch

import cogs.sessions as sessions_mod


# ---------------------------------------------------------------------------
# 1. No send/edit call site may pass ``layout=`` as a keyword argument.
# ---------------------------------------------------------------------------

_LAYOUT_KW_RE = re.compile(r"(?<=[\(,\s])layout=")


class NoLayoutKeywordTests(unittest.TestCase):
    """Scans every Python source file for stray ``layout=`` keyword args."""

    SOURCE_DIRS = ("cogs",)
    SOURCE_FILES = ("main.py", "utils.py")

    def _iter_source_files(self):
        for directory in self.SOURCE_DIRS:
            for root, _dirs, files in os.walk(directory):
                for name in files:
                    if name.endswith(".py"):
                        yield os.path.join(root, name)
        for name in self.SOURCE_FILES:
            yield name

    def test_no_layout_keyword_in_source(self):
        """No source file may contain ``layout=`` as a call keyword."""
        bad = []
        for path in self._iter_source_files():
            with open(path, "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    # Skip variable assignments: ``layout = ...`` has spaces
                    # around ``=``; our regex only matches ``layout=``.
                    if _LAYOUT_KW_RE.search(line):
                        bad.append(f"{path}:{lineno}: {line.rstrip()}")
        self.assertEqual(
            bad,
            [],
            f"Found {len(bad)} stray ``layout=`` keyword argument(s):\n"
            + "\n".join(bad),
        )


# ---------------------------------------------------------------------------
# 2. send_dest passes ``view=`` with a LayoutView, never embed/content.
# ---------------------------------------------------------------------------


class _RecordingDest:
    """Context-like destination that records kwargs passed to send()."""

    def __init__(self):
        self.kwargs = None

    async def send(self, *, view=None, **kwargs):
        self.kwargs = dict(kwargs)
        self.kwargs["view"] = view
        return None


class _RecordingInteraction:
    """Interaction-like destination that records kwargs."""

    def __init__(self):
        self.response = _RecordingResponse()
        self.followup = _RecordingFollowup()

    async def original_response(self):
        return None


class _RecordingResponse:
    def __init__(self):
        self.is_done_value = False
        self.kwargs = None

    def is_done(self):
        return self.is_done_value

    async def send_message(self, *, view=None, **kwargs):
        self.kwargs = dict(kwargs)
        self.kwargs["view"] = view
        return None


class _RecordingFollowup:
    def __init__(self):
        self.kwargs = None

    async def send(self, *, view=None, **kwargs):
        self.kwargs = dict(kwargs)
        self.kwargs["view"] = view
        return None


class SendDestViewTests(unittest.TestCase):
    """send_dest must forward ``view=`` (a LayoutView) and nothing v1."""

    def setUp(self):
        if "discord" in __import__("sys").modules:
            del __import__("sys").modules["discord"]
        self.discord = __import__("discord")

    def _make_layout(self):
        return self.discord.ui.LayoutView()

    async def _run_context(self, dest, layout):
        await sessions_mod.send_dest(dest, view=layout)
        return dest.kwargs

    async def _run_interaction_response(self, dest, layout):
        await sessions_mod.send_dest(dest, view=layout)
        return dest.response.kwargs

    async def _run_interaction_followup(self, dest, layout):
        dest.response.is_done_value = True
        await sessions_mod.send_dest(dest, view=layout)
        return dest.followup.kwargs

    def _check_recorded(self, recorded):
        self.assertIsInstance(recorded["view"], self.discord.ui.LayoutView)
        for forbidden in ("embed", "embeds", "content"):
            self.assertNotIn(forbidden, recorded)

    def test_send_dest_context_records_view_layout(self):
        dest = _RecordingDest()
        layout = self._make_layout()
        recorded = asyncio.run(self._run_context(dest, layout))
        self._check_recorded(recorded)

    def test_send_dest_interaction_response_records_view_layout(self):
        dest = _RecordingInteraction()
        layout = self._make_layout()
        # Patch discord.Interaction in sessions_mod so isinstance passes.
        with patch.object(sessions_mod.discord, "Interaction", _RecordingInteraction):
            recorded = asyncio.run(self._run_interaction_response(dest, layout))
        self._check_recorded(recorded)

    def test_send_dest_interaction_followup_records_view_layout(self):
        dest = _RecordingInteraction()
        layout = self._make_layout()
        with patch.object(sessions_mod.discord, "Interaction", _RecordingInteraction):
            recorded = asyncio.run(self._run_interaction_followup(dest, layout))
        self._check_recorded(recorded)


# ---------------------------------------------------------------------------
# 3. A real LayoutView passes through a stubbed discord HTTP send.
# ---------------------------------------------------------------------------


class LayoutViewHTTPTests(unittest.TestCase):
    """Construct a real LayoutView and push it through stubbed HTTP."""

    def test_layoutview_accepted_by_stubbed_http(self):
        import discord as d

        layout = d.ui.LayoutView(timeout=60)
        row = d.ui.ActionRow()
        row.add_item(d.ui.Button(label="OK", custom_id="ok"))
        layout.add_item(row)

        captured = {}

        async def _stub_send_message(self, *args, **kwargs):
            captured.update(kwargs)
            captured["args"] = args
            return {"id": 1, "channel_id": 2, "author": {"id": 3}}

        from discord import http as _http

        http = _http.HTTPClient(loop=asyncio.new_event_loop())

        async def _run():
            await http.send_message(1, view=layout.to_components())

        with patch.object(_http.HTTPClient, "send_message", new=_stub_send_message):
            asyncio.run(_run())

        self.assertIn("view", captured)
        self.assertNotIn("embed", captured)
        self.assertNotIn("embeds", captured)
        self.assertNotIn("content", captured)


if __name__ == "__main__":
    unittest.main()
