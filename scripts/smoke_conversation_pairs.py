#!/usr/bin/env python3
"""Smoke run for the derived conversation pairs (app/core/conversation_pairs.py).

Pure: no world, no DB, no clock. Only ``derive_partners`` is exercised, plus
the config default behind ``pair_window``.

Every expectation below is derived BY HAND from the rule in
``development_instructions/plan-gespraechs-auswahl.md`` § 3.1, not recorded
from an implementation run. The rule, restated:

  * source rows carry ``speaker``, ``addressees`` (list) and ``game_ts``
    (canonical GameTime string);
  * rows are processed NEWEST FIRST by ``game_ts``; the first assignment a
    name receives wins;
  * a row contributes nothing if its speaker is the storyteller, if it has no
    addressees, if its ``game_ts`` is empty/unparseable, or if it is older
    than the window — the exclusion test being ``now - stamp > window``, so a
    line of exactly the window's age still counts;
  * a contributing row sets ``partner(speaker) = addressees[0]`` and
    ``partner(a) = speaker`` for every addressee ``a`` — each only if that
    name has no partner yet.

The fixed clock for every case: ``now = Y0003-D047T14:00:00`` and
``window = 5 game minutes = 300 game seconds``. Since a GameTime is a plain
second count, "N minutes ago" is ``14:00:00`` minus ``N × 60`` seconds on the
same day, i.e.

    1 min ago -> Y0003-D047T13:59:00      now - stamp =  60 s
    2 min ago -> Y0003-D047T13:58:00      now - stamp = 120 s
    4 min ago -> Y0003-D047T13:56:00      now - stamp = 240 s
    5 min ago -> Y0003-D047T13:55:00      now - stamp = 300 s
    6 min ago -> Y0003-D047T13:54:00      now - stamp = 360 s

[0] Constants. ``WINDOW_DEFAULT_MINUTES`` is 5 per E4 of the plan, and with
    no world config loaded ``config.get("chat.pair_window_game_minutes", 5)``
    answers its default, so ``pair_window()`` is 5 × 60 = 300 game seconds.

[1] One addressed line, 2 min old (120 <= 300, inside): speaker A gets its
    first addressee -> partner(A) = B; addressee B gets the speaker ->
    partner(B) = A. Nobody else appears. Expected {A: B, B: A}.

[2] Newest wins. Rows: A -> B at 13:56 (240 s) and A -> C at 13:59 (60 s),
    handed in oldest-first order to prove the function sorts. Newest first
    means A -> C is read first: A is unset -> partner(A) = C, C is unset ->
    partner(C) = A. Then A -> B: A already has a partner and keeps C, but B
    is still unset -> partner(B) = A. B's newest link really is that older
    row, and it stays. Expected {A: C, C: A, B: A} — note this is NOT
    symmetric, and it must not be: A moved on to C while B is still waiting
    on A.

[3] A line to the room (addressees []) pairs nobody. One such row alone ->
    {}. With [1]'s row added the room line changes nothing: {A: B, B: A}.

[4] A storyteller line is narration, not a partner. Speaker
    ``STORYTELLER_SPEAKER`` addressing A, 1 min old -> {}. Checked twice:
    once letting ``derive_partners`` resolve the name itself (its default),
    once passing ``storyteller="Erzaehler"`` to show the parameter decides —
    with a different name configured, the "Storyteller" row is an ordinary
    line again and pairs normally ({Storyteller: A, A: Storyteller}).

[5] Outside the window: A -> B 6 min old, 360 > 300 -> excluded -> {}.

[6] No world stamp: game_ts "" (and a garbage string) -> the row is dropped
    before the window is even consulted -> {}.

[7] The window boundary is inclusive: A -> B exactly 5 min old gives
    300 > 300 = False, so the row is still inside -> {A: B, B: A}. The
    neighbouring second proves the edge: 301 s old -> {}.

[8] Robustness of the row shape (the DB hands these through JSON): a row
    whose ``addressees`` is not a list, a row without a speaker, a blank
    addressee name and a non-dict row all contribute nothing, while a valid
    row in the same batch still pairs. Expected {A: B, B: A}.

Usage:  ./.venv/bin/python scripts/smoke_conversation_pairs.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root and the clip library MUST be redirected BEFORE the first
# app import: any app.models import reaches its world.db through paths, and
# without a storage root every world access raises StorageNotInitialised —
# there is no default world any more, so nothing here can land in the tracked
# worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="conv-pairs-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="conv-pairs-storage-"))

from app.core.conversation_pairs import (  # noqa: E402
    WINDOW_DEFAULT_MINUTES,
    derive_partners,
    pair_window,
)
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER  # noqa: E402

FAILURES = []

NOW = GameTime.from_parts(3, 47, 14, 0, 0)
WINDOW = GameDuration.of(minutes=5)


def check(name, actual, expected):
    """Plain equality assertion that records instead of aborting the run."""
    if actual != expected:
        FAILURES.append(name)
        print(f"  FAIL {name}: {actual!r} != {expected!r}")
        return False
    return True


def ago(seconds: int) -> str:
    """Canonical stamp of the moment ``seconds`` game seconds before NOW."""
    return GameTime(NOW.total_seconds - seconds).canonical()


def row(speaker, addressees, seconds_ago=0, game_ts=None):
    """One utterance row in the shape ``recent_room_utterances`` returns."""
    return {
        "speaker": speaker,
        "addressees": addressees,
        "game_ts": ago(seconds_ago) if game_ts is None else game_ts,
        "content": "…",
        "ts": "2026-09-12T14:00:00+00:00",
        "volume": "normal",
    }


def test_constants():
    check("[0] WINDOW_DEFAULT_MINUTES", WINDOW_DEFAULT_MINUTES, 5)
    check("[0] pair_window default", pair_window(), GameDuration(300))
    # The stamps this file builds must read exactly as documented.
    check("[0] now", NOW.canonical(), "Y0003-D047T14:00:00")
    check("[0] 2 min ago", ago(120), "Y0003-D047T13:58:00")
    check("[0] 6 min ago", ago(360), "Y0003-D047T13:54:00")
    print("[0] constants and stamps")


def test_simple_pair():
    rows = [row("A", ["B"], 120)]
    check("[1] A<->B", derive_partners(rows, NOW, WINDOW), {"A": "B", "B": "A"})
    print("[1] one addressed line pairs both sides")


def test_newest_wins():
    rows = [row("A", ["B"], 240), row("A", ["C"], 60)]
    check("[2] newest wins", derive_partners(rows, NOW, WINDOW),
          {"A": "C", "C": "A", "B": "A"})
    # Same rows in the reverse input order — the function sorts, the caller
    # does not have to.
    check("[2] order independent", derive_partners(list(reversed(rows)), NOW, WINDOW),
          {"A": "C", "C": "A", "B": "A"})
    print("[2] the newest line decides, input order does not")


def test_room_line():
    check("[3] room line alone", derive_partners([row("A", [], 60)], NOW, WINDOW), {})
    rows = [row("A", [], 60), row("A", ["B"], 120)]
    check("[3] room line changes nothing", derive_partners(rows, NOW, WINDOW),
          {"A": "B", "B": "A"})
    print("[3] a line to the room pairs nobody")


def test_storyteller():
    rows = [row(STORYTELLER_SPEAKER, ["A"], 60)]
    check("[4] storyteller ignored", derive_partners(rows, NOW, WINDOW), {})
    check("[4] storyteller name is a parameter",
          derive_partners(rows, NOW, WINDOW, storyteller="Erzaehler"),
          {STORYTELLER_SPEAKER: "A", "A": STORYTELLER_SPEAKER})
    print("[4] narration is not a conversation partner")


def test_outside_window():
    check("[5] 6 min old", derive_partners([row("A", ["B"], 360)], NOW, WINDOW), {})
    print("[5] a line older than the window is gone")


def test_missing_stamp():
    check("[6] empty game_ts",
          derive_partners([row("A", ["B"], game_ts="")], NOW, WINDOW), {})
    check("[6] unparseable game_ts",
          derive_partners([row("A", ["B"], game_ts="2026-09-12T14:00:00")],
                          NOW, WINDOW), {})
    print("[6] a row without a world stamp never forms a pair")


def test_window_boundary():
    check("[7] exactly 5 min", derive_partners([row("A", ["B"], 300)], NOW, WINDOW),
          {"A": "B", "B": "A"})
    check("[7] one second past", derive_partners([row("A", ["B"], 301)], NOW, WINDOW),
          {})
    print("[7] the window boundary is inclusive")


def test_row_shapes():
    rows = [
        {"speaker": "X", "addressees": "B", "game_ts": ago(60)},   # not a list
        {"speaker": "", "addressees": ["B"], "game_ts": ago(60)},  # no speaker
        {"speaker": "Y", "addressees": ["  "], "game_ts": ago(60)},  # blank name
        "not a row",
        row("A", ["B"], 120),
    ]
    check("[8] broken rows skipped", derive_partners(rows, NOW, WINDOW),
          {"A": "B", "B": "A"})
    print("[8] unusable rows are skipped, the valid one still pairs")


def main():
    test_constants()
    test_simple_pair()
    test_newest_wins()
    test_room_line()
    test_storyteller()
    test_outside_window()
    test_missing_stamp()
    test_window_boundary()
    test_row_shapes()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
