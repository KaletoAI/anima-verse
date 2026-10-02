#!/usr/bin/env python3
"""Smoke run for "the topmost painted area decides whether a point is wet"
(bake v11, bug "Wasser über Land", 2026-10-02).

Usage:  ./.venv/bin/python scripts/smoke_water_topmost.py

THE BUG. A world painted the way every paint program works — a sea over the
whole map, the island painted on top of it — came out flooded: the carve
(``HeightModel._carve``) and the water raster (``HeightModel.water_at``) looked
at water polygons alone, so the sea's bed dug out the whole island (a +22 m hill
measured −2.0 m) and every building stood on its plateau like a rock in the
water. ``terrain_query.kind_at``, the layer mask and the client's ``typeAt``
already called that ground dry. Since v11 a land area painted AFTER a water
(``heightfield.water_areas_covered``) ends that water where it lies.

Every expectation below is derived BY HAND from the fixture of its block, in
the comment above it. Shared conventions of all pure blocks:

    catalog   "water", "sea", "lake" are water kinds; "grass", "path" are not
    natural   0 everywhere unless a block adds a height area (no relief)
    ss(t)     the smoothstep t²(3 − 2t): ss(0.25) = 0.15625, ss(0.5) = 0.5
    ring      the raster's dilation, WATER_RASTER_DILATION_M = 4 m

[A] THE MINIMAL CASE OF THE BUG REPORT
    water (0..100)², z 0, mirror 0, depth 2, shore ramp 0; grass (40..60)², z 1
      (50, 50)  under the grass, 10 m from its edge: dry (None), final 0 —
                NOT the −2 bed it was
      (10, 10)  open water: final −2, level 0, sd = distance to the waterline
                = 10 (the outline; the grass is 30 m away)
    + a height area +10 m (falloff 0) over the grass:
      (50, 50)  final 10 — the hill stands, the carve no longer cuts it

[B] AN ISLAND HAS A SHORE: the same fixture with shore ramp 4
      (39, 50)  1 m off the grass: bed = 0 − 2·ss(1/4) = −0.3125
      (38, 50)  2 m off:           bed = 0 − 2·ss(1/2) = −1.0, sd 2
      (30, 50)  10 m off, past the ramp: −2

[C] THE RING REACHES UNDER THE ISLAND, negative (shore ramp 0 again)
      (42, 50) sd −2;  (44, 50) sd −4 (the ring's own edge);  (44.5, 50) None

[D] WATER OVER WATER STACKS AS BEFORE
    sea (0..100)², z 0, depth 2; shallows x 0..50 × z 0..100, z 1, depth 1;
    both mirror 0, ramp 0
      (25, 50)  both wet: carve = min(−2, −1) = −2 (the sea's deeper bed);
                the raster names the TOPMOST water, the shallows
      neither water has a cover, so both keep the plain ring path

[E] A LAKE ON THE ISLAND IS NOT UNDERCUT BY THE SEA
    sea (0..200)², z 0, mirror 0, depth 2; island (50..150)², z 1, with a
    height area +10 (falloff 0) over it; lake (90..110)², z 2, mirror 10,
    depth 1, ramp 0
      (100, 100)  final = min(10, 10 − 1) = 9 — the sea is covered there by
                  the island, so its −2 never enters the min; raster: the lake
      (70, 100)   island, 20 m from the lake: final 10, dry (None)
      (20, 100)   open sea: final −2

[F] A ROAD OVER A RIVER IS A CAUSEWAY
    river x 0..100 × z 45..55, z 0, mirror 0, depth 2, ramp 0;
    path x 40..60 × z 0..100, z 1
      (50, 50)  10 m from the open water: dry (None), final 0
      (20, 50)  river: final −2
      (38, 50)  river, 2 m from the causeway (the river's own rim is 5 m
                away): sd 2

[G] TWO LAND AREAS SHARING AN EDGE DRAW NO WATERLINE BETWEEN THEM
    water (0..100)², z 0; grass A x 30..50 × z 30..70, grass B x 50..70 ×
    z 30..70, both z 1 — they meet on x = 50, land on both sides
      (50, 50)  on the shared edge, 20 m from any open water: None (a phantom
                waterline on x = 50 would put it in the ring at sd 0)
      (52, 50)  under B, 18 m from the water: None
      (50, 32)  under the land, 2 m from the open water at z = 30: sd −2

[H] THE WORLD — signature and floor plans, through the real store
    sea "water" (−100..100)², z 0, saved through ``save_area`` (its mirror
    settles to the rim median of a flat world: 0)
      a grass area painted 500 m away (its box does not reach the sea's):
        ``height_sig`` does NOT move — it covers nothing, and flat dry ground
        is no input of the field
      a grass island (−20..20)² painted over the sea: ``height_sig`` MOVES
        (``water_basis`` carries it as a cover), and the world model answers
        (0, 0) dry at final 0
      ``_map_water_ref``: a 10 m house hull at (0, 0) lies on NO water; the
        same hull at (−75, −75) lies on the sea
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="water-topmost-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import heightfield as hf  # noqa: E402

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


def near(label, actual, expected, tol=1e-9):
    global CHECKED
    CHECKED += 1
    ok = actual is not None and abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


CATALOG = {
    "water": {"kind": "water", "meta": {"water": True}},
    "sea": {"kind": "sea", "meta": {"water": True}},
    "lake": {"kind": "lake", "meta": {"water": True}},
    "grass": {"kind": "grass", "meta": {}},
    "path": {"kind": "path", "meta": {}},
}


def box(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def water(area_id, kind, polygon, z, level=0.0, depth=2.0, ramp=0.0):
    return {"id": area_id, "kind": kind, "z_order": z, "polygon": polygon,
            "meta": {"water_level": level, "water_depth_m": depth,
                     "shore_ramp_m": ramp}}


def land(area_id, kind, polygon, z):
    return {"id": area_id, "kind": kind, "z_order": z, "polygon": polygon,
            "meta": {}}


def sd(model, x, z):
    found = model.water_at(x, z)
    return None if found is None else round(found[3], 9)


check("the ring is 4 m wide, as every block assumes",
      hf.WATER_RASTER_DILATION_M, 4.0)
check("the bake version turned for the rule change", hf.HEIGHT_BAKE_VERSION,
      11)

# ── [A] ─────────────────────────────────────────────────────────────────
print("\n[A] the minimal case of the bug report")
A_WATER = water("w", "water", box(0, 0, 100, 100), 0)
A_GRASS = land("g", "grass", box(40, 40, 60, 60), 1)
MA = hf.build_model([], [], [A_WATER, A_GRASS], CATALOG)
check("under the grass there is no water", MA.water_at(50.0, 50.0), None)
near("...and no carve: final(50, 50) = 0, not the -2 bed", MA.final(50, 50),
     0.0)
near("open water still carves: final(10, 10) = -2", MA.final(10, 10), -2.0)
near("...at the mirror 0", MA.water_at(10.0, 10.0)[0], 0.0)
check("...with sd = 10, the distance to the outline", sd(MA, 10, 10), 10.0)
MA_HILL = hf.build_model([{"id": "h", "polygon": box(40, 40, 60, 60),
                           "height_m": 10.0, "falloff_m": 0.0}], [],
                         [A_WATER, A_GRASS], CATALOG)
near("a +10 m height area on the grass stands: final(50, 50) = 10",
     MA_HILL.final(50, 50), 10.0)
check("a covered water takes the covered shape",
      MA._water_fast[0][6] is not None, True)
MA_BARE = hf.build_model([], [], [A_WATER], CATALOG)
check("an uncovered water keeps the plain ring path (no shape at all)",
      MA_BARE._water_fast[0][6], None)

# ── [B] ─────────────────────────────────────────────────────────────────
print("\n[B] an island has a shore — the bed ramps up to it")
MB = hf.build_model([], [], [water("w", "water", box(0, 0, 100, 100), 0,
                                   ramp=4.0), A_GRASS], CATALOG)
near("1 m off the island: 0 - 2*ss(1/4) = -0.3125", MB.final(39, 50),
     -0.3125)
near("2 m off the island: 0 - 2*ss(1/2) = -1.0", MB.final(38, 50), -1.0)
check("...where sd is 2 — the island's edge is a waterline", sd(MB, 38, 50),
      2.0)
near("10 m off, past the ramp: the full -2", MB.final(30, 50), -2.0)

# ── [C] ─────────────────────────────────────────────────────────────────
print("\n[C] the ring reaches under the island, with a negative sd")
check("2 m inside the island: sd -2", sd(MA, 42, 50), -2.0)
check("4 m inside, the ring's own edge: sd -4", sd(MA, 44, 50), -4.0)
check("4.5 m inside: past the ring, no water", MA.water_at(44.5, 50.0), None)

# ── [D] ─────────────────────────────────────────────────────────────────
print("\n[D] water over water stacks exactly as before")
MD = hf.build_model([], [], [
    water("sea", "sea", box(0, 0, 100, 100), 0, depth=2.0),
    water("sh", "water", box(0, 0, 50, 100), 1, depth=1.0)], CATALOG)
near("the shallows keep the sea's deeper bed: min(-2, -1) = -2",
     MD.final(25, 50), -2.0)
check("...and the raster names the topmost water, the shallows",
      MD.water_at(25.0, 50.0)[4], "water")
check("neither water has a cover, so both keep the plain ring path",
      [entry[6] for entry in MD._water_fast], [None, None])

# ── [E] ─────────────────────────────────────────────────────────────────
print("\n[E] a lake on the island is not undercut by the sea")
ME = hf.build_model(
    [{"id": "isle", "polygon": box(50, 50, 150, 150), "height_m": 10.0,
      "falloff_m": 0.0}], [],
    [water("sea", "sea", box(0, 0, 200, 200), 0, depth=2.0),
     land("isle", "grass", box(50, 50, 150, 150), 1),
     water("lake", "lake", box(90, 90, 110, 110), 2, level=10.0, depth=1.0)],
    CATALOG)
near("mid-lake: min(10, 10 - 1) = 9, the sea's -2 never enters",
     ME.final(100, 100), 9.0)
check("...and the raster names the lake", ME.water_at(100.0, 100.0)[4],
      "lake")
near("on the island beside the lake: final 10", ME.final(70, 100), 10.0)
check("...and dry", ME.water_at(70.0, 100.0), None)
near("in the open sea: final -2", ME.final(20, 100), -2.0)

# ── [F] ─────────────────────────────────────────────────────────────────
print("\n[F] a road over a river is a causeway")
MF = hf.build_model([], [], [
    water("river", "water", box(0, 45, 100, 55), 0),
    land("road", "path", box(40, 0, 60, 100), 1)], CATALOG)
check("on the causeway, 10 m from the water: dry", MF.water_at(50.0, 50.0),
      None)
near("...at the natural 0", MF.final(50, 50), 0.0)
near("in the river: -2", MF.final(20, 50), -2.0)
check("2 m before the causeway: sd 2", sd(MF, 38, 50), 2.0)

# ── [G] ─────────────────────────────────────────────────────────────────
print("\n[G] two land areas sharing an edge draw no waterline between them")
MG = hf.build_model([], [], [
    water("w", "water", box(0, 0, 100, 100), 0),
    land("ga", "grass", box(30, 30, 50, 70), 1),
    land("gb", "grass", box(50, 30, 70, 70), 1)], CATALOG)
check("on the shared edge, 20 m from open water: no water",
      MG.water_at(50.0, 50.0), None)
check("2 m into the second area: still none", MG.water_at(52.0, 50.0), None)
check("2 m in from the real waterline at z = 30: sd -2", sd(MG, 50, 32),
      -2.0)

# ── [H] ─────────────────────────────────────────────────────────────────
print("\n[H] the world: signature and floor plans through the real store")
from app.core import scene_recipe  # noqa: E402
from app.models.heightfield import height_sig  # noqa: E402
from app.models.terrain import save_area  # noqa: E402

save_area({"kind": "water", "polygon": box(-100, -100, 100, 100),
           "z_order": 0})
_sig_sea = height_sig()
save_area({"kind": "grass", "polygon": box(500, 500, 520, 520), "z_order": 1})
check("grass painted 500 m away does not move height_sig", height_sig(),
      _sig_sea)
save_area({"kind": "grass", "polygon": box(-20, -20, 20, 20), "z_order": 1})
check("a grass island painted over the sea MOVES height_sig",
      height_sig() != _sig_sea, True)
_world = hf.world_model()
check("the world model answers the island dry", _world.water_at(0.0, 0.0),
      None)
near("...at final 0", _world.final(0.0, 0.0), 0.0)
near("...while the open sea is its bed, mirror 0 minus its depth",
     _world.final(-75.0, -75.0),
     -_world.water_depth_by_area[next(iter(_world.water_depth_by_area))])
_waters = scene_recipe._painted_waters()
check("a house on the island lies on no water",
      scene_recipe._map_water_ref(box(-5, -5, 5, 5), _waters), None)
_ref = scene_recipe._map_water_ref(box(-80, -80, -70, -70), _waters)
check("...the same hull out at sea lies on the sea",
      (_ref or {}).get("kind"), "water")

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
for name in FAILURES:
    print(f"  FAILED: {name}")
sys.exit(1 if FAILURES else 0)
