#!/usr/bin/env python3
"""Smoke: the composer's negation guard ends a negation clause at the next
clause separator (``app/core/prompt_compose.split_negations``; footwear P1 fix
round, docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md).

Usage:
    ./.venv/bin/python scripts/smoke_prompt_negation_clauses.py

Pure — no world, no storage, no config, no hub.

The P1 acceptance run logged "Moved negated items to the negative prompt:
foot, leg, seen exactly from the side, toe pointing to the left, plain white
background": the trailing-clause rule took everything from ", no" to the end
of the sentence and split it on commas, so the clauses AFTER the negation
became negated items. The rule now: a negation clause is a separator
(comma / semicolon / dash) + opener (no / without / ohne / kein…) up to the
next separator or the sentence end; its items split on and / or / und / oder.

Expected, by hand (subject -> cleaned, moved, inline):
[N1] "the same shoe, alone and empty, no foot or leg, seen exactly from the
     side, toe pointing to the left, plain white background"
     -> the clause is ", no foot or leg" (ends at the next comma) -> moved
     ["foot", "leg"]; cleaned = the subject without it: "the same shoe, alone
     and empty, seen exactly from the side, toe pointing to the left, plain
     white background"; inline [].
[N2] the same with the clause LAST (footwear_source.EMPTY_PROMPT): same
     cleaned text, moved ["foot", "leg"].
[N3] "A cozy kitchen, no tables, no chairs." -> two clauses, moved
     ["tables", "chairs"], cleaned "A cozy kitchen." (the terminator kept).
[N4] "A cozy kitchen. Ohne Tische und Stühle." -> the second sentence IS a
     negation -> moved ["Tische", "Stühle"], cleaned "A cozy kitchen.".
[N5] "a dress with no sleeves, red" -> "no" is not after a separator -> not
     moved; reported inline ["a dress with no sleeves, red"], cleaned as is.
[N6] "Eine Küche, keine Tische, mit Fenster" -> moved ["Tische"], cleaned
     "Eine Küche, mit Fenster" (the clause after the negation stays).
[N7] no negation word -> byte-identical, ([], []).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  (got {got!r}, want {want!r})"))
    if not ok:
        FAILS.append(label)


def main():
    from app.core.prompt_compose import split_negations
    positive = ("the same shoe, alone and empty, seen exactly from the side, toe pointing to the left, "
                "plain white background")
    check("[N1] negation in the middle",
          split_negations("the same shoe, alone and empty, no foot or leg, seen exactly from the side, "
                          "toe pointing to the left, plain white background"),
          (positive, ["foot", "leg"], []))
    check("[N2] negation last", split_negations(positive + ", no foot or leg"), (positive, ["foot", "leg"], []))
    from app.core.footwear_source import EMPTY_PROMPT
    check("[N2] EMPTY_PROMPT ends with the exclusion clause", EMPTY_PROMPT, positive + ", no foot or leg")
    check("[N3] two clauses", split_negations("A cozy kitchen, no tables, no chairs."),
          ("A cozy kitchen.", ["tables", "chairs"], []))
    check("[N4] negation sentence", split_negations("A cozy kitchen. Ohne Tische und Stühle."),
          ("A cozy kitchen.", ["Tische", "Stühle"], []))
    check("[N5] inline only", split_negations("a dress with no sleeves, red"),
          ("a dress with no sleeves, red", [], ["a dress with no sleeves, red"]))
    check("[N6] clause after the negation stays", split_negations("Eine Küche, keine Tische, mit Fenster"),
          ("Eine Küche, mit Fenster", ["Tische"], []))
    text = "a red pump, side view"
    got = split_negations(text)
    check("[N7] untouched", (got[0] is text or got[0] == text, got[1], got[2]), (True, [], []))
    if FAILS:
        print(f"\n{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
