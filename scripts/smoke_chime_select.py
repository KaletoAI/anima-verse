#!/usr/bin/env python3
"""Smoke run for the chime selection (app/core/chime_select.py).

Pure: no world, no DB. Only the pure functions are exercised
(``mentioned_names``, ``chime_scores``, ``select_chimer``,
``effective_chattiness``); the DB wrapper that builds the candidates lives in
the agent loop and is deliberately NOT called.

Every expectation below is derived BY HAND from plan § 3.2
(``development_instructions/plan-gespraechs-auswahl.md``), not recorded from
an implementation run.

The score formula, by hand::

    score = chattiness x rel x aim
    rel   = 0.5 + strength/100        (strength 0..100; no relationship = 10)
    aim   = AIM_FACTOR (0.3) when the line HAS addressees, else 1.0
    busy (partner set and partner not in {speaker} u addressees) -> 0
    mentioned by full name                                        -> 1.0
    clamped to [0, 1]

Cases:

  [1] "Hallo Liesa", addressed to Liesa, chattiness 0.5, three bystanders
      without relationships: rel = 0.5 + 10/100 = 0.6, aim = 0.3
      -> 0.5 x 0.6 x 0.3 = 0.09 each  (so in 91 % of the lines nobody chimes in)
  [2] the same three on a line to the room (no addressees): aim = 1.0
      -> 0.5 x 0.6 x 1.0 = 0.30 each
  [3] location override chattiness 0.8, room-wide
      -> 0.8 x 0.6 x 1.0 = 0.48 each
  [4] relationship strength 60, room-wide, chattiness 0.5:
      rel = 0.5 + 60/100 = 1.1 -> 0.5 x 1.1 x 1.0 = 0.55
  [5] busy: Karl's partner is Oskar, the speaker is Kai and the line is
      addressed to Liesa -> Oskar is neither speaker nor addressee, Karl sits
      in a foreign pair -> 0. Oskar himself has partner Karl, likewise 0.
  [6] the same shape but Karl's partner IS the speaker Kai -> not busy, the
      normal formula applies -> 0.5 x 0.6 x 0.3 = 0.09
  [7] mention: "Karl Schnaps, was meinst du?" against the names
      ["Karl Schnaps", "Oskar Richter"] -> ["Karl Schnaps"]. Only the FULL
      name as a WHOLE word counts, so "karl" inside "Karlsruhe" matches
      nothing ("Karl" is followed by a word character, no word boundary) and
      a first name is never resolved to a full name. Matching is literal per
      name: if a world really held both "Karl" and "Karl Schnaps", the phrase
      "Karl Schnaps" would match BOTH (the short name occurs as a whole word
      inside the long one) — documented, not designed around; the name rule
      of this repo makes that pair a naming mistake, not a case to handle.
  [8] two mentions, "Erst Oskar Richter, dann Karl Schnaps": the result is in
      TEXT order -> ["Oskar Richter", "Karl Schnaps"], independent of the
      order the names were passed in.
  [9] select_chimer: a mentioned candidate wins outright even when its
      partner is somebody else entirely (being named by the speaker pulls it
      out of the foreign pair) — and without consuming a single rng draw.
 [10] the draw. Seeded ``random.Random`` yields as its first value:
      seed 0 -> r = 0.844422, seed 1 -> r = 0.134364 (printed during
      development, reproducible: Python's Mersenne twister is stable).
      With the [2] scores, p_any = max = 0.30:
        seed 0: r = 0.844422 >= 0.30 -> nobody chimes in -> None
        seed 1: r = 0.134364 <  0.30 -> weighted pick, second draw
                r2 = 0.847434. random.choices bisects r2 x total over the
                cumulative weights: total = 3 x 0.30 = 0.9, cum =
                [0.3, 0.6, 0.9], r2 x 0.9 = 0.762691 -> falls in the third
                bucket -> "Oskar" (the third candidate).
 [11] always_someone forces p_any = 1.0, so even the tiny [1] scores of 0.09
      always produce a chimer: seed 1 -> r = 0.134364 < 1.0, then
      r2 = 0.847434 over total = 3 x 0.09 = 0.27, cum = [0.09, 0.18, 0.27],
      r2 x 0.27 = 0.228807 -> third bucket -> "Oskar".
 [12] always_someone cannot conjure a speaker: with every candidate busy all
      scores are 0, the candidate list is empty after dropping the zeros
      -> None.
 [13] effective_chattiness: {"chattiness": 0.8} -> 0.8 (the location wins);
      {"chattiness": ""} -> the world value, and without a loaded config
      ``config.get("chat.chattiness", 0.5)`` returns its default 0.5 (asserted
      separately, so the case cannot silently pass for the wrong reason);
      a missing key behaves the same; {"chattiness": 1.7} -> clamped to 1.0.

Usage:  ./.venv/bin/python scripts/smoke_chime_select.py
"""
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root and the clip library MUST be redirected BEFORE the first
# app import: paths.init otherwise falls back to worlds/demo — the world that
# is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="chime-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="chime-storage-"))

from app.core import config as app_config  # noqa: E402
from app.core.chime_select import (  # noqa: E402
    AIM_FACTOR,
    NO_RELATIONSHIP_STRENGTH,
    Candidate,
    chime_scores,
    effective_chattiness,
    mentioned_names,
    select_chimer,
)

FAILURES = []


def check(name, actual, expected):
    """Plain equality assertion that records instead of aborting the run."""
    if actual != expected:
        FAILURES.append(name)
        print(f"  FAIL {name}: {actual!r} != {expected!r}")
        return False
    return True


def check_scores(name, actual, expected):
    """Compare a score dict at 6 decimals (0.5*0.6*0.3 is not exactly 0.09)."""
    rounded = {key: round(value, 6) for key, value in actual.items()}
    return check(name, rounded, expected)


def bystanders(strength=NO_RELATIONSHIP_STRENGTH, partner=None):
    """The three bystanders of the tavern example, in a fixed order."""
    return [Candidate("Karl", strength, partner),
            Candidate("Luisa", strength, partner),
            Candidate("Oskar", strength, partner)]


def test_constants():
    check("AIM_FACTOR", AIM_FACTOR, 0.3)
    check("NO_RELATIONSHIP_STRENGTH", NO_RELATIONSHIP_STRENGTH, 10.0)
    print("[0] constants")


def test_addressed_line():
    # [1] a line with an addressee: aim 0.3 -> 0.5 * 0.6 * 0.3 = 0.09
    got = chime_scores(bystanders(), speaker="Kai", addressees=["Liesa"],
                       content="Hallo Liesa", chattiness=0.5)
    check_scores("[1] addressed", got,
                 {"Karl": 0.09, "Luisa": 0.09, "Oskar": 0.09})
    print("[1] addressed line -> 0.09")


def test_room_line():
    # [2] no addressee: aim 1.0 -> 0.5 * 0.6 = 0.30
    got = chime_scores(bystanders(), speaker="Kai", addressees=[],
                       content="Was fuer ein Wetter heute", chattiness=0.5)
    check_scores("[2] room-wide", got,
                 {"Karl": 0.30, "Luisa": 0.30, "Oskar": 0.30})
    print("[2] room-wide line -> 0.30")


def test_location_override():
    # [3] chattiness 0.8 -> 0.8 * 0.6 = 0.48
    got = chime_scores(bystanders(), speaker="Kai", addressees=[],
                       content="Was fuer ein Wetter heute", chattiness=0.8)
    check_scores("[3] chattiness 0.8", got,
                 {"Karl": 0.48, "Luisa": 0.48, "Oskar": 0.48})
    print("[3] chattiness 0.8 -> 0.48")


def test_relationship():
    # [4] strength 60 -> rel 1.1 -> 0.5 * 1.1 = 0.55
    got = chime_scores(bystanders(strength=60), speaker="Kai", addressees=[],
                       content="Was fuer ein Wetter heute", chattiness=0.5)
    check_scores("[4] strength 60", got,
                 {"Karl": 0.55, "Luisa": 0.55, "Oskar": 0.55})
    # a strength high enough to exceed 1.0 is clamped: 1.0 * (0.5 + 1.0) = 1.5
    got = chime_scores([Candidate("Karl", 100.0)], speaker="Kai",
                       addressees=[], content="hallo", chattiness=1.0)
    check_scores("[4] clamp", got, {"Karl": 1.0})
    print("[4] relationship strength -> 0.55 / clamp")


def test_busy():
    # [5] Karl and Oskar talk to each other, the line is Kai -> Liesa
    pair = [Candidate("Karl", partner="Oskar"),
            Candidate("Oskar", partner="Karl"),
            Candidate("Luisa")]
    got = chime_scores(pair, speaker="Kai", addressees=["Liesa"],
                       content="Hallo Liesa", chattiness=0.5)
    check_scores("[5] busy", got, {"Karl": 0.0, "Oskar": 0.0, "Luisa": 0.09})
    print("[5] foreign pair -> 0")


def test_busy_with_speaker():
    # [6] the partner IS the speaker -> the candidate is not busy
    got = chime_scores([Candidate("Karl", partner="Kai")], speaker="Kai",
                       addressees=["Liesa"], content="Hallo Liesa",
                       chattiness=0.5)
    check_scores("[6] partner is speaker", got, {"Karl": 0.09})
    # the partner is one of the addressees -> likewise not busy
    got = chime_scores([Candidate("Karl", partner="Liesa")], speaker="Kai",
                       addressees=["Liesa"], content="Hallo Liesa",
                       chattiness=0.5)
    check_scores("[6] partner is addressee", got, {"Karl": 0.09})
    print("[6] partner in {speaker} u addressees -> not busy")


def test_mentions():
    names = ["Karl Schnaps", "Oskar Richter"]
    # [7] full name as a whole word, case-insensitive
    check("[7] mention", mentioned_names("Karl Schnaps, was meinst du?", names),
          ["Karl Schnaps"])
    check("[7] lowercase", mentioned_names("karl schnaps, was meinst du?", names),
          ["Karl Schnaps"])
    # a word that merely STARTS with the name is not a mention
    check("[7] Karlsruhe", mentioned_names("Ich komme aus Karlsruhe", names), [])
    check("[7] first name only",
          mentioned_names("Karl, was meinst du?", names), [])
    check("[7] nothing", mentioned_names("Schoenes Wetter heute", names), [])
    check("[7] empty text", mentioned_names("", names), [])
    # [8] two mentions come back in TEXT order, not in argument order
    check("[8] text order",
          mentioned_names("Erst Oskar Richter, dann Karl Schnaps", names),
          ["Oskar Richter", "Karl Schnaps"])
    check("[8] text order reversed",
          mentioned_names("Erst Karl Schnaps, dann Oskar Richter", names),
          ["Karl Schnaps", "Oskar Richter"])
    print("[7-8] mentioned_names")


def test_mentioned_score_and_pick():
    # [9] mentioned scores 1.0 even while stuck in a foreign pair, and
    #     select_chimer returns it without touching the rng at all
    cands = [Candidate("Karl Schnaps", partner="Berta"), Candidate("Luisa")]
    got = chime_scores(cands, speaker="Kai", addressees=["Liesa"],
                       content="Karl Schnaps, was meinst du?", chattiness=0.5)
    check_scores("[9] mentioned busy", got, {"Karl Schnaps": 1.0, "Luisa": 0.09})

    class NoRng:
        def random(self):
            raise AssertionError("[9] select_chimer drew on a mention")

        def choices(self, *a, **kw):
            raise AssertionError("[9] select_chimer drew on a mention")

    check("[9] mentioned wins",
          select_chimer(cands, speaker="Kai", addressees=["Liesa"],
                        content="Karl Schnaps, was meinst du?",
                        chattiness=0.5, rng=NoRng()),
          "Karl Schnaps")
    print("[9] a mention wins outright")


def test_draw():
    # [10] p_any = 0.30; seed 0 -> r 0.844422 >= 0.30 -> nobody
    check("[10] seed 0 -> None",
          select_chimer(bystanders(), speaker="Kai", addressees=[],
                        content="Was fuer ein Wetter heute", chattiness=0.5,
                        rng=random.Random(0)),
          None)
    # seed 1 -> r 0.134364 < 0.30, r2 0.847434 * 0.9 = 0.762691 -> 3rd bucket
    check("[10] seed 1 -> Oskar",
          select_chimer(bystanders(), speaker="Kai", addressees=[],
                        content="Was fuer ein Wetter heute", chattiness=0.5,
                        rng=random.Random(1)),
          "Oskar")
    # no candidates at all -> None, whatever the roll
    check("[10] empty",
          select_chimer([], speaker="Kai", addressees=[], content="hallo",
                        chattiness=1.0, rng=random.Random(1)),
          None)
    print("[10] draw against p_any")


def test_always_someone():
    # [11] p_any forced to 1.0: the 0.09 scores still yield a chimer
    check("[11] always_someone",
          select_chimer(bystanders(), speaker="Kai", addressees=["Liesa"],
                        content="Hallo Liesa", chattiness=0.5,
                        always_someone=True, rng=random.Random(1)),
          "Oskar")
    # without the flag the same seed would fall silent: 0.134364 >= 0.09
    check("[11] without the flag",
          select_chimer(bystanders(), speaker="Kai", addressees=["Liesa"],
                        content="Hallo Liesa", chattiness=0.5,
                        rng=random.Random(1)),
          None)
    # [12] every candidate busy -> no weight to draw from -> None
    busy = [Candidate("Karl", partner="Berta"), Candidate("Oskar", partner="Tim")]
    check("[12] all busy",
          select_chimer(busy, speaker="Kai", addressees=["Liesa"],
                        content="Hallo Liesa", chattiness=0.5,
                        always_someone=True, rng=random.Random(1)),
          None)
    print("[11-12] always_someone")


def test_effective_chattiness():
    # [13] the world default must really be the schema default here
    check("[13] config default", app_config.get("chat.chattiness", 0.5), 0.5)
    check("[13] location 0.8", effective_chattiness({"chattiness": 0.8}), 0.8)
    check("[13] location string", effective_chattiness({"chattiness": "0.8"}), 0.8)
    check("[13] empty -> world", effective_chattiness({"chattiness": ""}), 0.5)
    check("[13] None -> world", effective_chattiness({"chattiness": None}), 0.5)
    check("[13] missing -> world", effective_chattiness({}), 0.5)
    check("[13] no location -> world", effective_chattiness(None), 0.5)
    check("[13] clamp high", effective_chattiness({"chattiness": 1.7}), 1.0)
    check("[13] clamp low", effective_chattiness({"chattiness": -0.5}), 0.0)
    check("[13] garbage -> world", effective_chattiness({"chattiness": "viel"}), 0.5)
    print("[13] effective_chattiness")


def main():
    test_constants()
    test_addressed_line()
    test_room_line()
    test_location_override()
    test_relationship()
    test_busy()
    test_busy_with_speaker()
    test_mentions()
    test_mentioned_score_and_pick()
    test_draw()
    test_always_someone()
    test_effective_chattiness()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
