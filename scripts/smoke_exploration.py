#!/usr/bin/env python3
"""Smoke run for the EXPLORATION MEMORY (Fog-Gedaechtnis, 2026-08-16).

The server side of the package: the cell raster, the 3×3 marking, the
in-process cache that keeps a walking avatar from writing on every report, the
signature that rides on the worldmap poll, and the payload of
``GET /play/explored``.

Hermetic: ``STORAGE_DIR`` points at a throwaway directory BEFORE any app
import, so the running server's ``worlds/*/world.db`` is never opened.

Hand-derived expectations (``EXPLORED_CELL_M`` = 64 m, ``MARK_RADIUS_CELLS``
= 1 — every number below follows from those two and nothing else):

  [1] THE RASTER. ``cell_of`` is a floor division:
        0 m     -> 0        (the origin belongs to cell 0)
        63.9 m  -> 0
        64 m    -> 1        (the border belongs to the cell AFTER it)
        100 m   -> 1        (100/64 = 1.56)
        -0.1 m  -> -1       (floor(-0.0016) = -1, NOT 0 — this is the case a
                             truncation would get wrong, and it would make the
                             cell around the origin twice as wide)
        -64 m   -> -1
        -65 m   -> -2
      ``cell_key(1, -2)`` is ``"1,-2"``.

  [2] THE 3×3 BLOCK. A character at (100, 30) stands in cell (1, 0), so
      ``cells_around`` is {0,1,2} × {-1,0,1} — nine cells, and the point's own
      is in the middle of them.

  [3] MARKING. The first report writes those nine, and the signature (= the
      row count, ``explored_sig``) goes from "0" to "9".

  [4] THE CACHE. A second report from ANOTHER POINT IN THE SAME CELL
      ((110, 40) is still cell (1, 0)) must not reach the DB at all: zero
      INSERT statements, counted with sqlite's own trace callback, and an
      unmoved signature. This is the whole reason the cache exists — an avatar
      reports up to four times a second.

  [5] A CELL BORDER CROSSED. (170, 30) is cell (2, 0), so the block is
      {1,2,3} × {-1,0,1}. Six of those nine ({1,2} × {-1,0,1}) are already
      known, so exactly THREE are new and the signature goes 9 -> 12.

  [6] COMING BACK. (100, 30) again: the cache last saw (2, 0), so the nine
      statements DO run — and every one of them is ignored, because the cells
      are known. Signature stays at 12. That is the honest cost of a
      one-cell cache, and it is written down rather than hidden.

  [7] THE PAYLOAD. ``explored_cells`` answers the 12 keys sorted by (cx, cz):
      the four columns 0..3, with column 0 and column 3 carrying only what
      their own block put there.

  [8] SEPARATE MEMORIES. A second character marking at the very same point
      gets its own nine cells; the first one's count does not move.

  [9] UNEMBODIED IS EMPTY. ``explored_cells("")`` is ``[]`` and
      ``explored_sig("")`` is ``""`` — an empty signature can never equal a
      real one (a character with no cells at all answers "0").

 [10] THE ROUTE. ``GET /play/explored`` without an active character answers
      ``{"cells": [], "sig": ""}``; with one it answers that character's cells
      and signature. And ``build_worldmap_payload`` carries ``explored_sig``
      for the avatar it is built for.

 [11] JUNK IS REFUSED, not written: an empty name and a NaN/inf point mark
      nothing and cost no statement.

 [12] THE RED COUNTER-CHECK. Sections [4] and [6] only prove anything if the
      cache is what makes the difference. So the same five reports from the
      same spot run again with ``reset_mark_cache()`` in front of each: the
      statement count goes from 0 to 45 (5 × 9). Without this run, [4] would
      pass on a ``mark_explored`` that had quietly stopped writing at all.

THE TWO CALLERS are checked where their fixtures already stand, not here: an
ACCEPTED ``POST /play/pos`` marks and a REFUSED one does not
(``scripts/smoke_discovery.py`` [4]), and the travel ticker marks every
character with a point (``smoke_discovery.py`` [3]). This file owns the maths,
the payload and the cache — that file owns the two write paths, whose world
(locations, painted water, a journey) it builds anyway.

Usage:  ./.venv/bin/python scripts/smoke_exploration.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point the storage root at a throwaway directory BEFORE any app import — the
# real world.db belongs to the running server (see CLAUDE.md).
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_exploration_")
_TMP_CLIPS = tempfile.TemporaryDirectory(prefix="smoke_exploration_clips_")
os.environ["STORAGE_DIR"] = _TMP_STORAGE.name
os.environ["ANIMATION_CLIPS_DIR"] = _TMP_CLIPS.name

from app.core import paths  # noqa: E402

paths.init(_TMP_STORAGE.name)

from app.core import db  # noqa: E402

db.init_schema()

from app.core.exploration import (  # noqa: E402
    EXPLORED_CELL_M, MARK_RADIUS_CELLS, cell_key, cell_of, cells_around,
    explored_cells, explored_sig, mark_explored, reset_mark_cache)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class InsertCounter:
    """Counts the INSERTs that really reach SQLite.

    ``sqlite3.Connection.set_trace_callback`` fires once per statement the
    driver executes, which is exactly the quantity the in-process cache exists
    to keep at zero — a cheaper measure (rows written) could not tell "the
    statement never ran" from "it ran and changed nothing", and those are the
    two cases sections [4] and [6] have to keep apart.
    """

    def __init__(self):
        self.n = 0

    def __enter__(self):
        self.n = 0
        db.get_connection().set_trace_callback(self._trace)
        return self

    def __exit__(self, *exc):
        db.get_connection().set_trace_callback(None)
        return False

    def _trace(self, sql):
        if "explored_cells" in sql and sql.lstrip().upper().startswith("INSERT"):
            self.n += 1


print("[0] the two constants the whole file is derived from")
check("cell edge (m)", EXPLORED_CELL_M, 64.0)
check("mark radius (cells)", MARK_RADIUS_CELLS, 1)

print("\n[1] the raster — floor, not truncation")
check("0 m", cell_of(0.0), 0)
check("63.9 m", cell_of(63.9), 0)
check("64 m (the border belongs to the cell after it)", cell_of(64.0), 1)
check("100 m", cell_of(100.0), 1)
check("-0.1 m", cell_of(-0.1), -1)
check("-64 m", cell_of(-64.0), -1)
check("-65 m", cell_of(-65.0), -2)
check("key form", cell_key(1, -2), "1,-2")

print("\n[2] the 3x3 block around (100, 30) = cell (1, 0)")
block = cells_around(100.0, 30.0)
check("nine cells", sorted(block),
      sorted([(cx, cz) for cx in (0, 1, 2) for cz in (-1, 0, 1)]))
check("its own cell is among them", (1, 0) in block, True)

WALKER = "demo_avatar"

print("\n[3] the first report writes the nine")
check("signature before", explored_sig(WALKER), "0")
with InsertCounter() as c1:
    added = mark_explored(WALKER, 100.0, 30.0)
check("new cells", added, 9)
check("statements", c1.n, 9)
check("signature", explored_sig(WALKER), "9")

print("\n[4] a second report from the SAME cell never reaches the DB")
with InsertCounter() as c2:
    again = mark_explored(WALKER, 110.0, 40.0)
check("cell of (110, 40)", (cell_of(110.0), cell_of(40.0)), (1, 0))
check("new cells", again, 0)
check("statements", c2.n, 0)
check("signature unmoved", explored_sig(WALKER), "9")

print("\n[5] one cell east: (170, 30) = cell (2, 0), three of nine are new")
with InsertCounter() as c3:
    east = mark_explored(WALKER, 170.0, 30.0)
check("new cells", east, 3)
check("statements", c3.n, 9)
check("signature", explored_sig(WALKER), "12")

print("\n[6] coming back costs nine ignored statements and no cell")
with InsertCounter() as c4:
    back = mark_explored(WALKER, 100.0, 30.0)
check("new cells", back, 0)
check("statements", c4.n, 9)
check("signature unmoved", explored_sig(WALKER), "12")

print("\n[7] the payload — the 12 keys, sorted by (cx, cz)")
expected_cells = sorted(
    {(cx, cz) for cx in (0, 1, 2) for cz in (-1, 0, 1)}
    | {(cx, cz) for cx in (1, 2, 3) for cz in (-1, 0, 1)})
check("cells", explored_cells(WALKER),
      [cell_key(cx, cz) for cx, cz in expected_cells])
check("count matches the signature", str(len(explored_cells(WALKER))),
      explored_sig(WALKER))

print("\n[8] a second character has its own memory")
mark_explored("npc_b", 100.0, 30.0)
check("npc_b", explored_sig("npc_b"), "9")
check("the walker is untouched", explored_sig(WALKER), "12")

print("\n[9] no avatar, no memory")
check("cells", explored_cells(""), [])
check("signature", explored_sig(""), "")
check("...and it can never equal a real one", explored_sig("nobody"), "0")

print("\n[10] the route and the worldmap ride-along")
from app.routes.play import get_explored_route  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models.account import set_active_character  # noqa: E402

check("unembodied", get_explored_route(user=None), {"cells": [], "sig": ""})
set_active_character(WALKER)
payload = get_explored_route(user=None)
check("payload keys", sorted(payload), ["cells", "sig"])
check("payload cells", payload["cells"], explored_cells(WALKER))
check("payload sig", payload["sig"], "12")
check("worldmap ride-along",
      build_worldmap_payload(WALKER).get("explored_sig"), "12")
check("...empty without an avatar",
      build_worldmap_payload("").get("explored_sig"), "")

print("\n[11] junk marks nothing")
with InsertCounter() as c5:
    check("empty name", mark_explored("", 0.0, 0.0), 0)
    check("NaN", mark_explored("junk_walker", float("nan"), 0.0), 0)
    check("inf", mark_explored("junk_walker", 0.0, float("inf")), 0)
check("statements", c5.n, 0)

print("\n[12] RED COUNTER-CHECK — without the cache the writes explode")
with InsertCounter() as c6:
    for _ in range(5):
        mark_explored(WALKER, 100.0, 30.0)
check("five reports WITH the cache", c6.n, 0)
with InsertCounter() as c7:
    for _ in range(5):
        reset_mark_cache()
        mark_explored(WALKER, 100.0, 30.0)
check("five reports WITHOUT it", c7.n, 45)
check("and not one new cell either way", explored_sig(WALKER), "12")

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
