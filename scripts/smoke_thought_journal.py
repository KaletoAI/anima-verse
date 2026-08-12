#!/usr/bin/env python3
"""Smoke run for the thought journal (Block T).

Runs against a THROWAWAY storage directory — it never touches a real world.
Covers the store (order, paging cursor, range query, prune), the thought
context block (T2) and the consolidation variable + retention (T3).

Usage:  ./.venv/bin/python scripts/smoke_thought_journal.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="thought-journal-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.models import thought_store as ts  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


CHAR = "demo"
# Five thoughts across three days, written out of order on purpose — the
# store must sort, not the caller.
FIXTURE = [
    ("2026-07-20T08:00:00+00:00", "Day one, morning."),
    ("2026-07-22T09:00:00+00:00", "Day three, morning."),
    ("2026-07-21T10:00:00+00:00", "Day two, morning."),
    ("2026-07-21T18:00:00+00:00", "Day two, evening."),
    ("2026-07-22T21:00:00+00:00", "Day three, evening."),
]


def test_store() -> None:
    print("\n[1] add + list")
    for stamp, text in FIXTURE:
        ts.add_thought(CHAR, text, location_id="loc1", room_id="room1", ts=stamp)
    check("empty content is not stored",
          ts.add_thought(CHAR, "   ") is False)
    check("a thought for another character is separate",
          ts.add_thought("other", "not mine") is True)

    rows = ts.list_thoughts(CHAR)
    check("all five thoughts of this character, nobody else's",
          len(rows) == 5, str(len(rows)))
    check("newest first",
          [r["content"] for r in rows][0] == "Day three, evening.",
          str([r["ts"] for r in rows]))
    check("location and room ride along",
          rows[0]["location_id"] == "loc1" and rows[0]["room_id"] == "room1",
          f"{rows[0]['location_id']}/{rows[0]['room_id']}")

    print("\n[2] paging with the before cursor")
    page1 = ts.list_thoughts(CHAR, limit=2)
    page2 = ts.list_thoughts(CHAR, limit=2, before=page1[-1]["ts"])
    check("page 1 has 2 rows", len(page1) == 2, str(len(page1)))
    check("page 2 continues without repeating",
          len(page2) == 2 and not ({r["id"] for r in page1}
                                   & {r["id"] for r in page2}),
          str([r["content"] for r in page2]))
    check("page 2 is strictly older", page2[0]["ts"] < page1[-1]["ts"],
          f"{page2[0]['ts']} < {page1[-1]['ts']}")

    print("\n[3] range query (consolidation reads a day)")
    day2 = ts.thoughts_of_range(CHAR, "2026-07-21T00:00:00+00:00",
                                "2026-07-22T00:00:00+00:00")
    check("only the two thoughts of that day", len(day2) == 2, str(len(day2)))
    check("OLDEST first — a day reads morning to evening",
          [r["content"] for r in day2]
          == ["Day two, morning.", "Day two, evening."],
          str([r["content"] for r in day2]))
    check("the window's end is exclusive",
          all(r["ts"] < "2026-07-22T00:00:00+00:00" for r in day2))

    print("\n[4] prune")
    deleted = ts.prune_before(CHAR, "2026-07-21T12:00:00+00:00")
    check("exactly the two older thoughts are gone", deleted == 2, str(deleted))
    left = ts.list_thoughts(CHAR)
    check("three remain, all at or after the cutoff",
          len(left) == 3 and all(r["ts"] >= "2026-07-21T12:00:00+00:00"
                                 for r in left),
          str([r["ts"] for r in left]))
    check("the other character is untouched by that prune",
          len(ts.list_thoughts("other")) == 1)


def test_context_block() -> None:
    print("\n[5] recent_thoughts for the thought prompt (T2)")
    from app.core import thought_context as tc
    block = tc.recent_thoughts_block(CHAR)
    check("the block is filled once thoughts exist", bool(block), block[:60])
    lines = [ln for ln in block.splitlines() if ln.strip()]
    check(f"at most {tc.THOUGHT_RECENT_N} entries",
          len(lines) <= tc.THOUGHT_RECENT_N, str(len(lines)))
    check("newest LAST — the prompt reads chronologically",
          lines[-1].endswith("Day three, evening."), lines[-1])
    check("hard character cap holds",
          len(block) <= tc.THOUGHT_RECENT_CHARS, str(len(block)))

    long_char = "longwind"
    for i in range(5):
        ts.add_thought(long_char, "x" * 900, ts=f"2026-07-2{i}T08:00:00+00:00")
    capped = tc.recent_thoughts_block(long_char)
    check("...even when the entries are long",
          len(capped) <= tc.THOUGHT_RECENT_CHARS, str(len(capped)))
    check("empty journal → empty string",
          tc.recent_thoughts_block("nobody") == "")


def test_consolidation_vars() -> None:
    print("\n[6] thoughts_of_day for the consolidation (T3)")
    from app.core import day_consolidation as dc
    block = dc.thoughts_of_day_block(CHAR, "2026-07-21T00:00:00+00:00",
                                     "2026-07-23T00:00:00+00:00")
    check("the surviving thoughts of the window are in it",
          "Day three, evening." in block and "Day two, evening." in block,
          block[:80].replace("\n", " | "))
    check("a window without thoughts is an empty string",
          dc.thoughts_of_day_block(CHAR, "2026-01-01T00:00:00+00:00",
                                   "2026-01-02T00:00:00+00:00") == "")
    big = "toomuch"
    for i in range(40):
        ts.add_thought(big, "y" * 200, ts=f"2026-07-21T{i % 24:02d}:00:00+00:00")
    capped = dc.thoughts_of_day_block(big, "2026-07-21T00:00:00+00:00",
                                      "2026-07-22T00:00:00+00:00")
    check(f"hard cap at {dc.THOUGHTS_OF_DAY_CHARS} characters",
          len(capped) <= dc.THOUGHTS_OF_DAY_CHARS, str(len(capped)))
    check("retention constant is 7 days", dc.THOUGHT_RETENTION_DAYS == 7,
          str(dc.THOUGHT_RETENTION_DAYS))


SECTIONS = {"store": test_store, "context": test_context_block,
            "consolidation": test_consolidation_vars}


def main() -> int:
    # Sections can be named on the command line — useful while the blocks are
    # still being built, and for re-running just one of them.
    wanted = [a for a in sys.argv[1:] if a in SECTIONS] or list(SECTIONS)
    for name in wanted:
        SECTIONS[name]()
    print(f"\n{CHECKED} checks, {len(FAILURES)} failure(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
