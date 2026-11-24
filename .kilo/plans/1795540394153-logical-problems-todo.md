# Logical Problems Todo List

Status: Open — needs user decisions on design tensions before implementation.

## Context

Recent change: all game timeouts set to 120s, all `asyncio.sleep()` delays set to `sleep(0)` ("no delay"). Files changed: `cogs/arcade.py`, `cogs/games.py`, `cogs/uno.py`, `dashboard/web.py`, `tests/test_game_ui.py`.

These changes introduced gameplay-breaking side effects that must be resolved alongside other pre-existing logical problems.

---

## Issues Found

### A. Gameplay broken by "no delay" changes (from the timeout work)

**A1. SequenceHunt preview skipped — game unplayable**
- File: `cogs/arcade.py:1121`
- `await asyncio.sleep(4)` → `await asyncio.sleep(0)`. The sequence preview embed is shown for ~0s before switching to the answer phase. Players cannot memorize anything.
- Recommended fix: Restore a short preview delay (e.g. 3–4s) so the game remains playable. This conflicts with "no delay" — needs user decision.

**A2. RedLight cycles instantly — game ends immediately**
- File: `cogs/arcade.py:1547`
- `await asyncio.sleep(random.uniform(2.0, 4.5))` → `await asyncio.sleep(0)`. All 8 red/green rounds execute back-to-back with no visible state changes. Game ends in a single tick.
- Recommended fix: Restore a short per-round delay (e.g. 2–4s). Conflicts with "no delay" — needs user decision.

**A3. Reaction countdown misleading**
- File: `cogs/arcade.py:928–939`
- `begin()` sets `countdown_field(120)` but `_run()` sleeps 0 and goes live immediately, then sets another 120s countdown. The first embed shows "Ends in 120s" but the game is already live.
- Recommended fix: Show the pre-GO wait as a countdown or remove the initial countdown field. Needs user decision.

### B. Double notification on game end

**B1. `finish()` sends plain text after games already send an embed**
- File: `cogs/sessions.py:78–93`
- `ChannelGame.finish(result=...)` sends `result` as plain text via `self.channel.send(text)`.
- Games call `end_game_message(message, embed)` (sends result embed) AND THEN `finish(result=...)`, producing TWO messages: one embed + one plain text.
- Affected games: ChatGuessGame, WordRuleGame, ButtonHunt, ColorHunt, SequenceHunt, Trivia, DiceDuel, HiLo, Reaction, RedLight, UNO.
- Recommended fix: Make `finish()` not send plain text (or only send when no embed was already posted), and have games rely solely on `end_game_message()` for the result embed.

### C. Moderation DM-before-action ordering

**C1. Ban/kick/timeout DM sent before the Discord API call**
- File: `cogs/moderation.py:93–97` (ban), `:130–134` (kick), `:155–163` (timeout)
- The user is DM'd that they were banned/kicked/timed out BEFORE `member.ban()`, `member.kick()`, `member.timeout()` is called. If the API call fails (Forbidden/HTTPException), the user received a false confirmation.
- Recommended fix: Move the `try_dm()` call to after the successful moderation action.

### D. Voice XP / voice seconds not atomic

**D1. XP awarded without voice time tracked (or vice versa)**
- File: `cogs/leveling.py:145–146`
- `voice_xp_loop` calls `add_xp()` then `add_voice_seconds()` sequentially. If the first succeeds and the second fails, XP is granted but voice time isn't recorded. No transaction wrapping.
- Recommended fix: Wrap both writes so they succeed or fail together, or accept eventual inconsistency (user decision).

### E. Alt detection logic gaps

**E1. Auto-action only triggers for "High risk", ignoring config for medium risk**
- File: `cogs/altdetect.py:482–483`
- `on_member_join`: `if assessment.verdict != "High risk": return` — auto-action (`_apply_auto_action`) only runs for High risk verdicts, even if the admin configured action `timeout`/`kick`/`quarantine` for medium risk joins. The config's `action` setting is effectively ignored below High risk.
- Recommended fix: Apply the configured auto-action for any non-Low risk (or at least Medium+), respecting the admin's `action` setting.

**E2. Alert view includes "Ban" but dashboard omits it**
- File: `cogs/altdetect.py:105–111` (`build_alert_view` adds Ban button) vs `dashboard/routes.py:34` (`ALT_ACTIONS = ("none", "log", "timeout", "kick", "quarantine")` — no "ban")
- Inconsistent action sets between Discord alert buttons and dashboard.

### F. Dashboard bug

**F1. `can_act` is always True**
- File: `dashboard/routes.py:229`
- `"can_act": status not in {"banned"} or True` — the `or True` makes this always evaluate to True. Dead condition, likely meant to restrict actions on banned users.

### G. Trivia API HTTP timeout too long

**G1. 120s HTTP timeout for external trivia API**
- File: `cogs/arcade.py:134` (`aiohttp.ClientTimeout(total=120)`) and `cogs/games.py:510` (same)
- If opentdb.com hangs, the user waits 2 minutes before the fallback questions are used. Game timeout should be 120s, but the HTTP call should fail fast (e.g. 10–15s).
- Recommended fix: Keep game countdown at 120s but reduce the external HTTP timeout to ~10s.

### H. Session / channel lock race

**H1. Non-atomic check-then-start for channel games**
- File: `cogs/sessions.py:145–164` (`refuse_if_busy`) and `:203–218` (`launch_channel_game`)
- `refuse_if_busy()` calls `get()`, then `launch_channel_game` calls `start()`. Between them another task can start a game. Acknowledged by comment ("Race: another game started in between.") but not resolved.
- Recommended fix: Make `GameManager.start()` atomic (it already pops-and-replaces if existing is finished/stale), and have `launch_channel_game` rely on `start()`'s return value as the source of truth without a separate pre-check.

---

## Design Decisions Needed (ask user)

1. **SequenceHunt / RedLight delays**: Restore short playable delays despite "no delay" request? (Recommended: yes, ~3–4s preview / ~2–4s per round)
2. **Reaction countdown**: Remove the misleading initial countdown or repurpose it? (Recommended: show pre-GO wait countdown instead)
3. **`finish()` plain text**: Remove plain-text sending from `finish()` entirely? (Recommended: yes)
4. **Voice XP atomicity**: Wrap `add_xp` + `add_voice_seconds` so they fail together? (Recommended: yes)
5. **Alt auto-action threshold**: Apply configured action for Medium+ risk instead of High-only? (Recommended: yes)
6. **Trivia HTTP timeout**: Reduce to ~10s while keeping game timeout at 120s? (Recommended: yes)

---

## Suggested Implementation Order

1. **B1** — Fix double notification (`finish()` / `end_game_message()`) — low risk, clear win.
2. **C1** — Moderation DM ordering — low risk, correctness fix.
3. **F1** — Dashboard `can_act` bug — trivial fix.
4. **A1/A2/A3** — Restore playable delays — requires user decision on delay values.
5. **G1** — Trivia HTTP timeout — requires user decision on value.
6. **E1/E2** — Alt detection logic — requires user decision on threshold.
7. **D1** — Voice XP atomicity — requires user decision on approach.
8. **H1** — Session race — requires user decision on whether to refactor `launch_channel_game`.

---

## Validation

- Run `python -m py_compile` on all edited files.
- Run `pytest tests/` (or `python -m unittest discover tests`) to confirm no regressions.
- Manually verify each game starts, runs its countdown, and ends with exactly one result message (no duplicate plain text).