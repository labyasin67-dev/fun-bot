"""Progressive hint engine for word-guessing games.

Generates a deterministic sequence of letter reveals for a given answer,
scaled to the game's timeout. Hints never reveal the full answer.
"""

from __future__ import annotations

import random
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence


# Default stage fractions (fraction of total timeout when hint is revealed).
# Can be overridden per game via HintPlan(stage_fractions=...).
DEFAULT_STAGE_FRACTIONS = (0.35, 0.55, 0.75, 0.90)

# Minimum letters to leave hidden (never reveal everything).
MIN_HIDDEN = 2


@dataclass(frozen=True)
class HintStage:
    """A single hint stage with its trigger time and the masked answer."""
    fraction: float          # fraction of timeout (0..1)
    trigger_ts: float        # absolute monotonic timestamp when this stage becomes visible
    masked: str              # masked answer with revealed letters
    label: str               # short label for UI ("Hint 1/4", "First letters", etc.)


@dataclass
class HintPlan:
    """Complete hint schedule for a single game.

    The plan is fully deterministic once built: the reveal order is shuffled
    once at construction (seeded per game) so hints are consistent and never
    un-reveal letters.
    """

    answer: str
    timeout: int
    stage_fractions: Sequence[float]
    semantic_hint: str | None = None  # e.g. "Known as an actor", "Country: France"
    _seed: int | None = None

    # Internal state (populated by build)
    _maskable_positions: list[int] = None
    _reveal_order: list[int] = None
    _stages: list[HintStage] = None
    _initial_masked: str = None
    _initial_label: str = None

    def __post_init__(self):
        # Validate
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 0 < len(self.stage_fractions) <= 4:
            raise ValueError("stage_fractions must have 1-4 elements")
        if any(not (0 < f < 1) for f in self.stage_fractions):
            raise ValueError("stage_fractions must be in (0, 1)")
        if any(self.stage_fractions[i] >= self.stage_fractions[i + 1] for i in range(len(self.stage_fractions) - 1)):
            raise ValueError("stage_fractions must be strictly increasing")

    def build(self, *, seed: int | None = None) -> "HintPlan":
        """Construct the full hint schedule.

        This must be called once before the game starts. It determines the
        letter reveal order and computes the masked answer for each stage.
        """
        if self._stages is not None:
            return self  # already built

        rng = random.Random(seed if seed is not None else self._seed)
        if rng is None:
            rng = random.Random()

        # Normalize answer: keep only letters/digits as maskable; spaces, punctuation shown immediately
        self._maskable_positions = self._find_maskable_positions(self.answer)
        total_maskable = len(self._maskable_positions)

        # Determine reveal order: shuffle maskable positions once
        self._reveal_order = self._maskable_positions[:]
        rng.shuffle(self._reveal_order)

        # For short answers, limit stages
        max_stages = len(self.stage_fractions)
        if total_maskable <= 3:
            max_stages = 1

        # Build each stage
        self._stages = []
        revealed = set()
        total_stages = min(max_stages, len(self.stage_fractions))
        start_time = time.monotonic()

        # Stage 0: initial mask (no letters revealed)
        self._initial_masked = self._make_masked(self.answer, revealed)
        word_count = len(self.answer.split())
        letter_count = sum(1 for c in self.answer if c.isalnum())
        self._initial_label = f"{word_count} word{'s' if word_count != 1 else ''}, {letter_count} letter{'s' if letter_count != 1 else ''}"

        for i in range(total_stages):
            frac = self.stage_fractions[i]
            # How many letters to reveal at this stage
            if i == 0:
                # Stage 1: first letter of each word
                new_reveals = self._first_letters_per_word(self.answer)
                revealed.update(new_reveals)
                target = len(revealed)
            elif i == total_stages - 1:
                # Final stage: ~65% of total maskable, but leave at least MIN_HIDDEN
                target = min(int(total_maskable * 0.65), total_maskable - MIN_HIDDEN)
                target = max(target, len(revealed) + 1)
            else:
                # Intermediate stages: ~25% increments
                target = min(int(total_maskable * 0.25 * (i + 1)), total_maskable - MIN_HIDDEN)
                target = max(target, len(revealed) + 1)

            # Reveal up to target letters, respecting reveal order and never un-revealing
            for pos in self._reveal_order:
                if len(revealed) >= target:
                    break
                revealed.add(pos)

            masked = self._make_masked(self.answer, revealed)
            trigger_ts = start_time + self.timeout * frac
            self._stages.append(HintStage(
                fraction=frac,
                trigger_ts=trigger_ts,
                masked=masked,
                label=f"Hint {i + 1}/{total_stages}",
            ))

        return self

    def _find_maskable_positions(self, text: str) -> list[int]:
        """Return indices of characters that should be masked (letters/digits only)."""
        positions = []
        for i, ch in enumerate(text):
            if ch.isalnum():  # letters and digits are maskable
                positions.append(i)
        return positions

    def _first_letters_per_word(self, text: str) -> set[int]:
        """Return positions of the first letter of each word (if alnum)."""
        revealed = set()
        in_word = False
        for i, ch in enumerate(text):
            if ch.isalnum():
                if not in_word:
                    revealed.add(i)
                    in_word = True
            else:
                in_word = False
        return revealed

    def _make_masked(self, text: str, revealed: set[int]) -> str:
        """Build the masked string: revealed letters shown, maskable hidden as _, punctuation/space shown."""
        out = []
        for i, ch in enumerate(text):
            if i in revealed:
                out.append(ch)
            elif ch.isalnum():
                out.append("_")
            else:
                out.append(ch)
        # Add spaces between characters for readability (but keep punctuation attached)
        # We'll join with space for alnum/underscore, but keep punctuation adjacent.
        # Simpler: just space-separate every character
        return " ".join(out)

    def get_initial_masked(self) -> str:
        """Return the initial fully-masked answer (stage 0)."""
        if self._stages is None:
            self.build()
        return self._initial_masked

    def get_initial_label(self) -> str:
        """Return the initial label (word/letter count)."""
        if self._stages is None:
            self.build()
        return self._initial_label

    def get_stages(self) -> list[HintStage]:
        """Return all hint stages in order."""
        if self._stages is None:
            self.build()
        return self._stages

    def get_stage_at_time(self, now: float) -> HintStage | None:
        """Return the highest-index stage whose trigger_ts <= now, or None if none yet."""
        if self._stages is None:
            self.build()
        result = None
        for stage in self._stages:
            if stage.trigger_ts <= now:
                result = stage
            else:
                break
        return stage

    def get_final_reveal(self) -> str:
        """Return the fully revealed answer (for timeout/win)."""
        return self.answer

    def semantic_hint_line(self) -> str | None:
        """Return the semantic hint text if provided, for display at stage 1."""
        return self.semantic_hint


def normalize_for_hint(text: str) -> str:
    """Normalize text for hint purposes (NFKD, strip combining marks, keep alnum/punctuation)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# Example usage / quick self-test
if __name__ == "__main__":
    import sys

    # Test 1: single word
    plan = HintPlan("Paris", timeout=30, stage_fractions=(0.35, 0.55, 0.75, 0.90))
    plan.build(seed=42)
    print("Test: single word 'Paris'")
    print(f"  Initial: {plan.get_initial_masked()} ({plan.get_initial_label()})")
    for s in plan.get_stages():
        print(f"  {s.label} @ {s.fraction:.0%}: {s.masked}")
    print(f"  Final: {plan.get_final_reveal()}")

    # Test 2: multi-word with punctuation
    plan2 = HintPlan("New York", timeout=30, stage_fractions=(0.35, 0.55, 0.75, 0.90))
    plan2.build(seed=42)
    print("\nTest: 'New York'")
    print(f"  Initial: {plan2.get_initial_masked()} ({plan2.get_initial_label()})")
    for s in plan2.get_stages():
        print(f"  {s.label} @ {s.fraction:.0%}: {s.masked}")

    # Test 3: short answer (<=3 letters)
    plan3 = HintPlan("Go", timeout=20, stage_fractions=(0.35, 0.55, 0.75, 0.90))
    plan3.build(seed=42)
    print("\nTest: short 'Go'")
    print(f"  Initial: {plan3.get_initial_masked()} ({plan3.get_initial_label()})")
    for s in plan3.get_stages():
        print(f"  {s.label} @ {s.fraction:.0%}: {s.masked}")

    # Test 4: unicode
    plan4 = HintPlan("São Paulo", timeout=30, stage_fractions=(0.35, 0.55, 0.75, 0.90))
    plan4.build(seed=42)
    print("\nTest: unicode 'São Paulo'")
    print(f"  Initial: {plan4.get_initial_masked()} ({plan4.get_initial_label()})")
    for s in plan4.get_stages():
        print(f"  {s.label} @ {s.fraction:.0%}: {s.masked}")

    # Test 5: semantic hint
    plan5 = HintPlan("Leonardo DiCaprio", timeout=30, stage_fractions=(0.35, 0.55, 0.75, 0.90),
                     semantic_hint="Known as an actor")
    plan5.build(seed=42)
    print("\nTest: semantic hint")
    print(f"  Semantic: {plan5.semantic_hint_line()}")
    for s in plan5.get_stages():
        print(f"  {s.label} @ {s.fraction:.0%}: {s.masked}")