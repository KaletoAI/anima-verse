#!/usr/bin/env python3
"""Smoke run for the provenance fields of a memory across a full round trip
(B8 of plan-log-befunde-2026-09-11.md).

Runs WITHOUT a server and WITHOUT a real world: a throwaway SQLite world is
created in a temp directory (``paths.init`` + ``db.init_schema``). ``worlds/``
is never touched, so the running server's locks are irrelevant.

WHY THIS SCRIPT EXISTS

``scripts/test_memory_meta.py`` checks ``_build_meta`` as a pure function and
stayed GREEN while the defect was live, because the defect is not in one call
— it is in the ASYMMETRY between two paths:

  write path     add_memory() builds meta via _build_meta and then merges
                 ``extra_meta`` on top → the INSERT is always complete,
                 whatever the whitelist says.
  write-back     save_memories() → _entry_to_row() → _build_meta() → only
                 META_KEYS survive.

``retrieve_relevant_memories`` writes every entry back on every call (it bumps
access_count / last_accessed / decay_factor), so a field that ``extra_meta``
smuggled in lived exactly until the character's FIRST retrieval and then
vanished — leaving only the log line
"memory entry carries unknown field(s) location_id, participants, room_id,
scene_id — not stored". Only a round trip that includes the RETRIEVAL step
catches that; a check that stops after add → load is green with the bug.

THE HAND VALUES (derived from the specification, not recorded from output)

  The seven provenance keys and the values handed in, per § 3.5 of the plan:

    source        = "scene"              (memory_service.py, intent_engine.py)
    event_id      = "evt_42"             (memory_service.py)
    scene_id      = "sc_7"               (scene_manager.py)
    location_id   = "loc_market"         (scene_manager.py)
    room_id       = "room_hall"          (scene_manager.py)
    participants  = ["Demo", "Other"]    (scene_manager.py — a LIST, so this
                                          also proves the JSON round trip of a
                                          non-scalar meta value)
    date_key      = "Y0002-D109"         (day_consolidation.py; the canonical
                                          GAME day key of the pinned clock)

  Expected after EVERY step below: all seven keys present with exactly those
  values — they are constants handed in, never re-read from the code.

  [1] add_memory(extra_meta=...) → load_memories: all seven present.
      (This step was green WITH the bug — the insert merges extra_meta.)
  [2] save_memories(loaded) → load_memories: all seven present.
      (First step that went red with the bug.)
  [3] retrieve_relevant_memories(..., "scene", max_results=5) → the returned
      entry carries all seven, and load_memories still does.
      access_count must be exactly 1: add_memory stores 0, and one retrieval
      bumps it by one. That bump is WHY the write-back happens at all.
  [4] Across the whole round trip the whitelist warning must never fire for
      these keys — the point of B8 is that real provenance goes quiet while a
      typo still complains. So a synthetic unknown key is fed in last and MUST
      produce exactly one warning (E6: the warning stays sharp).

  The clock is PINNED (``set_game_factor(0.0)`` then ``set_game_time``) so the
  run cannot flake on wall-clock drift; NOW = "Y0002-D109T14:00:00", whose day
  key is "Y0002-D109" — the same constant handed in as ``date_key``.

Usage:  ./.venv/bin/python scripts/smoke_memory_meta_roundtrip.py

Exit code 0 = all checks passed; any failure prints FAIL and exits 1.
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="memory-meta-roundtrip-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="memory-meta-roundtrip-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import timeutils  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.models import memory as mem  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

FAILURES = []
CHECKED = 0

CHAR = "Demo"
NOW = "Y0002-D109T14:00:00"

# The seven provenance fields, exactly as the producers hand them in.
PROVENANCE = {
    "source": "scene",
    "event_id": "evt_42",
    "scene_id": "sc_7",
    "location_id": "loc_market",
    "room_id": "room_hall",
    "participants": ["Demo", "Other"],
    "date_key": "Y0002-D109",
}


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class CountingHandler(logging.Handler):
    """Collects the memory logger's messages so the warning can be counted."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def check_provenance(label, entry):
    """Every one of the seven keys must carry its hand-given value."""
    for key, expected in PROVENANCE.items():
        check(f"{label}: {key}", entry.get(key), expected)


def main() -> int:
    handler = CountingHandler()
    mem.logger.addHandler(handler)

    timeutils.set_game_factor(0.0)
    timeutils.set_game_time(GameTime.parse(NOW))
    save_character_profile(CHAR, {"name": CHAR, "language": "en"},
                           create_new=True)

    print("\n[0] the pinned clock matches the hand-given date_key")
    check("game_time() is pinned at NOW", timeutils.game_time().canonical(), NOW)
    check("day key of NOW", GameTime.parse(NOW).day_key(),
          PROVENANCE["date_key"])

    # ---------------------------------------------------------------- [1]
    print("\n[1] add_memory(extra_meta=...) → load_memories")
    handler.records.clear()
    added = mem.add_memory(CHAR, "scene text", memory_type="episodic",
                           tags=["scene"], extra_meta=dict(PROVENANCE))
    check("a row was written", bool(added), True)
    loaded = mem.load_memories(CHAR)
    check("exactly one memory", len(loaded), 1)
    check_provenance("after add", loaded[0])
    check("access_count starts at 0", loaded[0].get("access_count"), 0)

    # ---------------------------------------------------------------- [2]
    print("\n[2] save_memories(loaded) → load_memories")
    mem.save_memories(CHAR, loaded)
    loaded = mem.load_memories(CHAR)
    check("still exactly one memory", len(loaded), 1)
    check_provenance("after save", loaded[0])

    # ---------------------------------------------------------------- [3]
    print("\n[3] retrieve_relevant_memories → load_memories (the step that"
          " killed the fields)")
    result = mem.retrieve_relevant_memories(CHAR, current_message="scene",
                                            max_results=5)
    check("the retrieval returns the memory", len(result), 1)
    check_provenance("in the retrieved entry", result[0])
    loaded = mem.load_memories(CHAR)
    check("still exactly one memory", len(loaded), 1)
    check_provenance("after the retrieval write-back", loaded[0])
    check("access_count bumped to 1", loaded[0].get("access_count"), 1)

    # ---------------------------------------------------------------- [4]
    print("\n[4] the whitelist warning stayed quiet for provenance and is"
          " still sharp for a typo")
    provenance_warnings = [r for r in handler.records
                           if "unknown field" in r]
    check("no warning during the whole round trip", provenance_warnings, [])
    handler.records.clear()
    mem._build_meta({"content": "x", "scene_ids": "typo"})
    check("a typo still warns exactly once",
          len([r for r in handler.records if "unknown field" in r]), 1)
    check("the warning names the typo",
          "scene_ids" in "".join(handler.records), True)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAILED: {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
