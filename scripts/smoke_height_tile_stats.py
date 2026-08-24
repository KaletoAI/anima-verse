#!/usr/bin/env python3
"""Smoke run for the PERSISTED TILE STATISTICS of the heightfield (§ G2).

Throwaway storage, no server, no real world. Every number below is derived BY
HAND in this header from the rules, never recorded from the current output.

WHY THE MECHANISM EXISTS
------------------------
A tile statistic (``min``/``max`` plus one vertical error per mip level) is
read off a FINISHED 129² raster, so asking for one means rastering that tile:
about 90 ms of pure Python. A CDLOD client asks for the statistics of every
tile it knows, because it takes its worst error per level over all of them —
so on the demo world (1077 indexed tiles) a cold process paid 1077 rasters.
Measured 2026-08-24 in ``logs/main.log``: seventeen ``GET
/play/heightfield/stats`` batches, 15:57:33 → 15:59:15, 102 s; the SAME
seventeen batches against the same world on a warm process (23:04:25 →
23:04:26 of the 2026-08-23 log) took one second. The cache was process-local,
so every restart and every ``HEIGHT_BAKE_VERSION`` bump paid the 102 s again.

Now the statistics are stored in ``world_height_tile_stats``, keyed by the
same ``height_sig`` the rastered grid already carries — the tile-level twin of
``world_heightfield``.

THE RULES BEING CHECKED
-----------------------
R1  A statistic asked for once is STORED, under the current ``height_sig``,
    one row per tile.
R2  A fresh process (generation bumped, process maps dropped — exactly what
    ``invalidate_cache`` leaves behind) reads them back and rasters NOTHING.
R3  A changed world invalidates them by SIGNATURE: the statistics of the new
    world are computed, and the rows of the old signature are gone.
R4  A stored ``err`` of the wrong length is ignored — ``MIP_LEVELS_M`` is not
    part of the signature, so a changed level list must not be handed to a
    client as an error per level it does not have.
R5  An unindexed tile answers the flat-world record and stores no row.
R6  ``tile_stats_many`` writes the whole batch, and answers exactly the keys
    the index knows.

THE SHAPE USED BELOW
--------------------
  PLATEAU  square (−100,−100)-(400,400), height_m 7, falloff_m 4

and the tile under test is (0, 0), which covers x, z ∈ [0, 256] (``TILE_M``
256, ``TILE_STEP_M`` 2 → 129 × 129 support points).

[1] EVERY support point of tile (0,0) sits at the FULL height. The ramp is
      h(p) = height_m · min(1, distance(p, outline) / falloff_m)
    and the nearest outline edge to any point of [0,256]² is the west or north
    edge of the square at −100, so the distance is at least 100 m:
      min(1, 100/4) = 1  ->  h = 7 · 1 = 7 at every one of the 16641 points.
    Nothing else touches the tile: a fresh world has no placed location (no
    plateau), no painted terrain (no micro-relief) and no water (no carve).
    So the statistic of tile (0,0) is derived, not recorded:
      min = 7.0, max = 7.0
      err = [0, 0, 0, 0, 0] — one per MIP_LEVELS_M (4, 8, 16, 32, 64 m).
    The error is the vertical distance between the tile drawn at that level
    and the tile at the 2 m base; a CONSTANT field decimates exactly, every
    coarse lattice interpolates back to the same 7, so every level is 0.
[2] AFTER THE EDIT (height_m 7 -> 9) the same arithmetic gives
      min = 9.0, max = 9.0, err = [0, 0, 0, 0, 0]
    and 9.0 is the number that proves the invalidation: a reader that trusted
    the stored row would answer the old 7.0.
[3] THE INDEX around the plateau. The square spans −100…400 on both axes and
    a tile is 256 m anchored at the world origin, so it reaches
      tx ∈ {−1, 0, 1} (−100 is in tile −1, 400 is in tile 1)
    and the same for tz — NINE tiles, of which (0,0) is one. Tile (9, 9)
    covers x, z ∈ [2304, 2560] and is nowhere near it: unindexed, flat.

Usage:  ./.venv/bin/python scripts/smoke_height_tile_stats.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="tile-stats-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="tile-stats-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import heightfield as hf  # noqa: E402
from app.models import heightfield as store  # noqa: E402

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


def check_not(label, actual, forbidden):
    """The other half of a red counter-probe: the value a MUTANT would
    produce, asserted absent."""
    global CHECKED
    CHECKED += 1
    ok = actual != forbidden
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — this is the mutant's {forbidden!r}"))
    if not ok:
        FAILURES.append(label)


# ── The counter: how often the process actually RASTERS a tile ──────────

RASTERS = []
_real_rasterize_tile = hf.rasterize_tile


def counting_rasterize_tile(tx, tz, *args, **kwargs):
    RASTERS.append((tx, tz))
    return _real_rasterize_tile(tx, tz, *args, **kwargs)


hf.rasterize_tile = counting_rasterize_tile


def stored_rows():
    """``{(sig, tx, tz): stats}`` — the whole table, read raw."""
    conn = db.get_connection()
    out = {}
    for sig, tx, tz, raw in conn.execute(
            "SELECT sig, tx, tz, stats FROM world_height_tile_stats"):
        out[(sig, int(tx), int(tz))] = json.loads(raw)
    return out


def fresh_process():
    """What a RESTART leaves behind: no process cache, the same DB.

    ``invalidate_cache`` drops exactly the four per-generation maps a new
    process would not have (the field, the tile inputs, the model, the tile
    statistics) and empties the tile LRU. What it cannot drop is the DB, which
    is the whole point of the mechanism under test.
    """
    hf.invalidate_cache()
    RASTERS.clear()


FLAT_ERR = [0.0] * len(hf.MIP_LEVELS_M)
PLATEAU = {"polygon": [[-100, -100], [400, -100], [400, 400], [-100, 400]],
           "height_m": 7, "falloff_m": 4}

print("\n[0] the world: one plateau, and the tile (0,0) inside it")
area = store.save_height_area(dict(PLATEAU))
SIG_7 = store.height_sig()
check("MIP_LEVELS_M — five levels, so five error entries per tile",
      list(hf.MIP_LEVELS_M), [4.0, 8.0, 16.0, 32.0, 64.0])
check("tile (0,0) covers [0,256]² and is indexed", (0, 0) in hf.tile_index(),
      True)
check("tile (9,9) covers [2304,2560]² — nowhere near the plateau",
      (9, 9) in hf.tile_index(), False)

print("\n[1] R1 — the first ask rasters ONCE and stores the row")
RASTERS.clear()
first = hf.tile_stats(0, 0)
check("[1] min of tile (0,0): every support point is at 7 · min(1, 100/4)",
      first["min"], 7.0)
check("[1] max of tile (0,0): the same 7 — a plateau has no relief in it",
      first["max"], 7.0)
check("[1] err per level: a CONSTANT field decimates exactly",
      first["err"], FLAT_ERR)
check("[1] exactly one raster paid", RASTERS, [(0, 0)])
check("[1] one row stored, under the signature of THIS world",
      sorted(stored_rows()), [(SIG_7, 0, 0)])
check("[1] and the stored record is the answer, not a summary of it",
      stored_rows()[(SIG_7, 0, 0)], first)

print("\n[2] the second ask inside the same process is the process map")
RASTERS.clear()
check("[2] same answer", hf.tile_stats(0, 0), first)
check("[2] no raster", RASTERS, [])

print("\n[3] R2 — a FRESH PROCESS reads the rows back and rasters nothing")
fresh_process()
check("[3] the signature did not move: no authoring write happened",
      store.height_sig(), SIG_7)
again = hf.tile_stats(0, 0)
check("[3] same statistic after the restart", again, first)
check("[3] NOTHING was rastered — this is the 102 s the mechanism removes",
      RASTERS, [])

print("\n[4] R6 — a batch: eight cold neighbours, one write")
fresh_process()
NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1),
              (1, -1), (1, 0), (1, 1)]
batch = hf.tile_stats_many(NEIGHBOURS + [(0, 0), (9, 9)])
check("[4] the unindexed (9,9) is left out of the answer", (9, 9) in batch,
      False)
check("[4] the nine indexed tiles answered", sorted(batch),
      sorted(NEIGHBOURS + [(0, 0)]))
check("[4] (0,0) came out of the DB, so only the eight others rastered",
      sorted(RASTERS), sorted(NEIGHBOURS))
check("[4] nine rows stand now, all under the same signature",
      sorted(stored_rows()),
      sorted((SIG_7, tx, tz) for tx, tz in NEIGHBOURS + [(0, 0)]))
check("[4] no row for the unindexed tile", (SIG_7, 9, 9) in stored_rows(),
      False)

print("\n[5] R5 — an unindexed tile is the flat world, and costs nothing")
fresh_process()
flat = hf.tile_stats(9, 9)
check("[5] the flat-world record", flat,
      {"min": 0.0, "max": 0.0, "err": FLAT_ERR})
check("[5] no raster", RASTERS, [])
check("[5] and no row: it is true for every signature and worth none",
      (SIG_7, 9, 9) in stored_rows(), False)

print("\n[6] R3 — the world changes: the signature invalidates the rows")
store.save_height_area({**PLATEAU, "id": area["id"], "height_m": 9})
SIG_9 = store.height_sig()
check_not("[6] the signature moved with the world", SIG_9, SIG_7)
RASTERS.clear()
raised = hf.tile_stats(0, 0)
check("[6] min of tile (0,0) is now 9 — the ramp caps at the new height",
      raised["min"], 9.0)
check("[6] max likewise", raised["max"], 9.0)
check_not("[6] RED COUNTER-PROBE: a reader that trusted the stored row would "
          "answer the OLD world's 7.0", raised["min"], 7.0)
check("[6] it was rastered again, which is what a changed world costs",
      RASTERS, [(0, 0)])
check("[6] and the nine rows of the old signature are GONE — the table holds "
      "one generation of the world", sorted(stored_rows()), [(SIG_9, 0, 0)])

print("\n[7] R2 again, on the new world")
fresh_process()
check("[7] the restart reads the NEW statistic back", hf.tile_stats(0, 0),
      raised)
check("[7] without rastering", RASTERS, [])

print("\n[8] R4 — a stored err of the wrong length is ignored")
fresh_process()
store.store_tile_stats(SIG_9, {(0, 0): {"min": 1.0, "max": 2.0,
                                        "err": [0.0, 0.0, 0.0]}})
check("[8] the poisoned row IS in the table",
      stored_rows()[(SIG_9, 0, 0)]["err"], [0.0, 0.0, 0.0])
fresh_process()
repaired = hf.tile_stats(0, 0)
check("[8] but the reader drops it and rasters instead", RASTERS, [(0, 0)])
check("[8] so the answer has one error per level again", len(repaired["err"]),
      len(hf.MIP_LEVELS_M))
check_not("[8] RED COUNTER-PROBE: a reader that took the row would hand a "
          "CDLOD client a min of 1.0 for a 9 m plateau", repaired["min"], 1.0)
check("[8] …and it is the real statistic", repaired, raised)
check("[8] the repaired row replaced the poisoned one",
      stored_rows()[(SIG_9, 0, 0)], raised)

print("\n[9] the payload builders go through the same door")
fresh_process()
payload = hf.stats_payload([(0, 0), (9, 9)])
check("[9] stats_payload keys the way the index does", sorted(payload),
      ["sig", "tile_stats"])
check("[9] …and answers only indexed tiles",
      sorted(payload["tile_stats"]), ["0,0"])
check("[9] with the stored record", payload["tile_stats"]["0,0"], raised)
check("[9] and paid no raster for it", RASTERS, [])
tiles = hf.tiles_payload([(0, 0)])
check("[9] tiles_payload carries the same statistic beside the grid",
      tiles["tiles"]["0,0"]["stats"], raised)
check("[9] the GRID is not cached in the DB, so THAT one rasters",
      RASTERS, [(0, 0)])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
