#!/usr/bin/env python3
"""Smoke run for the reply-shape facts (app/core/reply_shape.py).

Pure: no world, no DB. Only the three pure helpers are exercised
(``classify_incoming``, ``tier``, ``compose_reply_shape``) plus
``sentiment_label`` from ``app.models.relationship``; the world loader
``build_reply_shape_section`` is deliberately NOT called.

Every expectation below is derived BY HAND from the interface contract
(.superpowers/sdd/plan-reply-length/constraints.md), not recorded from an
implementation run.

Size classification (constants: BRIEF_MAX_WORDS 12, LONG_MIN_WORDS 45):
spoken words = whitespace tokens AFTER removing every ``*action*`` segment.

  ""                        -> no text at all           -> kind ""      q False
  "Ich will ein Bier"       -> 4 tokens, 4 <= 12         -> "brief"      q False
  "Was machst du gerade?"   -> 4 tokens, ends in "?"     -> "brief"      q True
  "*nickt*"                 -> 0 spoken words but the message is not
                               empty (a pure action)     -> "brief"      q False
  "*grinst* Noch eins?"     -> "Noch eins?" = 2 tokens   -> "brief"      q True
  12 words, no "?"          -> 12 <= 12 (inclusive)      -> "brief"      q False
  13 words                  -> 13 > 12, 13 < 45          -> "normal"     q False
  44 words                  -> 44 < 45 (inclusive bound) -> "normal"     q False
  45 words ending in "?"    -> 45 >= 45                  -> "long"       q True

Tiers (TIER_LOW_BELOW 34, TIER_HIGH_FROM 67, default 50):
  10 < 34 low | 33 < 34 low | 34 average | 66 average | 67 >= 67 high
  None/"abc" -> default 50 -> average | "80" -> float 80 >= 67 -> high

Sentiment thresholds (unchanged from build_relationship_prompt_section):
  0.6 > 0.5 -> "very positive"      0.2 > 0.1 -> "positive"
  0.0 -> "neutral"                  -0.2 < -0.1 -> "negative"
  -0.6 < -0.5 -> "very negative"

Bullet composition: one line per fact, in the fixed order incoming /
on_duty / mood / relationship / attention / discretion, joined with "\\n",
no trailing newline; no fact at all -> "".

Usage:  ./.venv/bin/python scripts/smoke_reply_shape.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.reply_shape import (  # noqa: E402
    BRIEF_MAX_WORDS,
    LONG_MIN_WORDS,
    TIER_HIGH_FROM,
    TIER_LOW_BELOW,
    classify_incoming,
    compose_reply_shape,
    tier,
)
from app.models.relationship import sentiment_label  # noqa: E402

FAILURES = []


def check(name, actual, expected):
    """Plain equality assertion that records instead of aborting the run."""
    if actual != expected:
        FAILURES.append(name)
        print(f"  FAIL {name}: {actual!r} != {expected!r}")
        return False
    return True


def words(n: int) -> str:
    """A message of exactly n whitespace tokens."""
    return " ".join(f"w{i}" for i in range(n))


def test_constants():
    check("BRIEF_MAX_WORDS", BRIEF_MAX_WORDS, 12)
    check("LONG_MIN_WORDS", LONG_MIN_WORDS, 45)
    check("TIER_LOW_BELOW", TIER_LOW_BELOW, 34)
    check("TIER_HIGH_FROM", TIER_HIGH_FROM, 67)
    print("[0] constants")


def test_classify_incoming():
    # [1] empty text has no size at all
    check("[1] empty", classify_incoming(""), {"kind": "", "question": False})
    check("[1] blanks", classify_incoming("   \n "), {"kind": "", "question": False})
    # [2] 4 spoken words
    check("[2] brief", classify_incoming("Ich will ein Bier"),
          {"kind": "brief", "question": False})
    # [3] 4 spoken words ending in a question mark
    check("[3] brief question", classify_incoming("Was machst du gerade?"),
          {"kind": "brief", "question": True})
    # [4] pure action: 0 spoken words, but the message is not empty
    check("[4] pure action", classify_incoming("*nickt*"),
          {"kind": "brief", "question": False})
    # [5] action plus 2 spoken words ending in "?"
    check("[5] action + speech", classify_incoming("*grinst* Noch eins?"),
          {"kind": "brief", "question": True})
    # [6] boundary: 12 words are still brief
    check("[6] 12 words", classify_incoming(words(12)),
          {"kind": "brief", "question": False})
    # [7] 13 words tip over into normal
    check("[7] 13 words", classify_incoming(words(13)),
          {"kind": "normal", "question": False})
    # [8] boundary: 44 words are still normal
    check("[8] 44 words", classify_incoming(words(44)),
          {"kind": "normal", "question": False})
    # [9] boundary: 45 words are long; the "?" is seen on the spoken text
    check("[9] 45 words question", classify_incoming(words(44) + " really?"),
          {"kind": "long", "question": True})
    print("[1-9] classify_incoming")


def test_tier():
    # [10] tier thresholds and fallbacks
    check("[10] 10", tier(10), "low")
    check("[10] 33", tier(33), "low")
    check("[10] 34", tier(34), "average")
    check("[10] 66", tier(66), "average")
    check("[10] 67", tier(67), "high")
    check("[10] None", tier(None), "average")
    check("[10] abc", tier("abc"), "average")
    check("[10] '80'", tier("80"), "high")
    print("[10] tier")


def test_compose_empty():
    # [11] no fact at all -> no section
    check("[11] empty facts", compose_reply_shape({}), "")
    print("[11] compose_reply_shape({})")


def test_compose_full():
    # [12] brief line, on duty with activity, mood, stranger, low attention,
    #      high discretion — every bullet the composer knows except the
    #      relationship variant covered by [13]
    got = compose_reply_shape({
        "incoming_kind": "brief", "incoming_question": False,
        "on_duty": "innkeeper", "activity": "serving drinks", "mood": "annoyed",
        "partner": "Bob", "relationship": None, "partner_attention": "low",
        "discretion": "high",
    })
    expected = (
        "- The incoming line is brief.\n"
        "- You are on the job: innkeeper. Right now: serving drinks.\n"
        "- Your mood: annoyed.\n"
        "- You have no relationship with Bob yet — a stranger.\n"
        "- Bob draws your attention: little.\n"
        "- Your discretion about other people: high."
    )
    check("[12] full", got, expected)
    print("[12] compose_reply_shape full")


def test_compose_long_relationship():
    # [13] long question with a known partner and a relationship
    got = compose_reply_shape({
        "incoming_kind": "long", "incoming_question": True,
        "partner": "Bob",
        "relationship": {"type": "Friend", "closeness": 72, "feeling": "positive"},
        "partner_attention": "high",
    })
    expected = (
        "- The incoming line is long — Bob had a lot to say. It ends in a question.\n"
        "- Relationship with Bob: Friend, closeness 72/100, you feel positive about them.\n"
        "- Bob draws your attention: a lot."
    )
    check("[13] long", got, expected)
    print("[13] compose_reply_shape long + relationship")


def test_compose_no_partner():
    # [14] a long line without a known partner names no one
    check("[14] long no partner", compose_reply_shape({"incoming_kind": "long"}),
          "- The incoming line is long — the other person had a lot to say.")
    # the remaining incoming variants, same wording table
    check("[14] brief question", compose_reply_shape({"incoming_kind": "brief",
                                                      "incoming_question": True}),
          "- The incoming line is a brief question.")
    check("[14] normal", compose_reply_shape({"incoming_kind": "normal"}),
          "- The incoming line is of normal length.")
    check("[14] normal question", compose_reply_shape({"incoming_kind": "normal",
                                                       "incoming_question": True}),
          "- The incoming line is a question of normal length.")
    # on duty without activity: no "Right now" tail
    check("[14] duty only", compose_reply_shape({"on_duty": "guard"}),
          "- You are on the job: guard.")
    # an activity without duty is not a fact of its own
    check("[14] activity only", compose_reply_shape({"activity": "sweeping"}), "")
    # attention wording for the middle tier; a known partner without a
    # relationship is always a stranger (the loader passes None, never nothing)
    check("[14] attention average",
          compose_reply_shape({"partner": "Bob", "relationship": None,
                               "partner_attention": "average"}),
          "- You have no relationship with Bob yet — a stranger.\n"
          "- Bob draws your attention: somewhat.")
    print("[14] compose_reply_shape variants")


def test_sentiment_label():
    # [15] thresholds unchanged from the relationship prompt section
    check("[15] 0.6", sentiment_label(0.6), "very positive")
    check("[15] 0.2", sentiment_label(0.2), "positive")
    check("[15] 0.0", sentiment_label(0.0), "neutral")
    check("[15] -0.2", sentiment_label(-0.2), "negative")
    check("[15] -0.6", sentiment_label(-0.6), "very negative")
    print("[15] sentiment_label")


def main():
    test_constants()
    test_classify_incoming()
    test_tier()
    test_compose_empty()
    test_compose_full()
    test_compose_long_relationship()
    test_compose_no_partner()
    test_sentiment_label()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
