#!/usr/bin/env python3
"""Smoke run for the LAYER CUT of the ground ("Ein Boden" E3, § G3).

Usage:  ./.venv/bin/python scripts/smoke_terrain_layers.py

Runs against a THROWAWAY storage directory — never touches a real world. Every
number below is derived BY HAND from the spec in this docstring (§ B5a); the
script only measures whether the bake produces it.

===========================================================================
THE FIXTURE
===========================================================================
Default ground ``grass``. Three painted shapes, in ``list_areas`` order, i.e.
in ascending priority ("the LAST containing area wins"):

    rank 1  sand   [[0,0],[256,0],[256,256],[0,256]]      the whole tile
    rank 2  water  [[64,64],[192,64],[192,192],[64,192]]  a lake in it
    rank 3  grass  [[100,100],[140,100],[140,140],[100,140]]  a HOLE in the lake

The hole is painted in the DEFAULT kind on purpose: it is the case that proves
index 0 is not a special "unpainted" state but a layer like any other.

THE LAYER TABLE, by hand. Index 0 is the default kind; the painted kinds follow
SORTED, and a shape painted in the default kind maps back onto 0 rather than
getting a twin of it:

    0  grass   (bare ground; also what rank 3 paints)
    1  sand
    2  water

so ``rank_layer == [0, 1, 2, 0]``.

===========================================================================
[1] THE RASTER IS THE SCALAR RULE — and both are ``terrain_query.kind_at``
===========================================================================
``LayerModel.rank_at`` walks the shapes exactly as ``kind_at`` does (last
containing wins). ``rank_grid`` fills the same answer by SCANLINE, which is a
different algorithm for the same rule: crossings per row, sorted, and the
half-open span ``[xs[2m], xs[2m+1])`` — the very set the ray cast calls inside.
Checked at 500 lattice probes on a deterministic 0.5 m sweep: raster ==
``rank_at`` == ``kind_at`` (through the layer table), all three.

===========================================================================
[2] THE PAIR IS CANONICAL — the same (A, B) on BOTH sides of a line
===========================================================================
Along the row z = 128.25 (the sd texel centre nearest the middle of the tile)
the fixture has four boundaries. For each, A is the layer painted LATER (the
higher rank) and B the earlier one, and BOTH neighbours carry that same pair:

    x = 64    sand(rank 1) | water(rank 2)  -> hi = 2 -> A = 2, B = 1
    x = 100   water(2)     | hole(3)        -> hi = 3 -> A = 0, B = 2
    x = 140   hole(3)      | water(2)       -> hi = 3 -> A = 0, B = 2
    x = 192   water(2)     | sand(1)        -> hi = 2 -> A = 2, B = 1

Only the SIGN of the distance differs across the line. That is the whole
mechanism: a NEAREST id fetch may snap to either side without changing which
two materials are mixed, and where the cut runs comes out of the LINEAR
distance alone.

===========================================================================
[3] THE SIGNED DISTANCE, exactly, on the axis-aligned rows
===========================================================================
sd texel ``m`` has its centre at ``0.5·m + 0.25``. A boundary between two
neighbouring lattice samples sits at their MIDPOINT, so the boundary at x = 64
lies exactly between the samples at 63.75 and 64.25 — 0.25 m from each.
Propagation along a row is exact arithmetic (the site is in the same row), so:

    x = 63.75   sand,  0.25 m outside water   ->  −0.25 m
    x = 64.25   water, 0.25 m inside          ->  +0.25 m
    x = 60.25   sand,  3.75 m out             ->  −3.75 m
    x = 68.25   water, 4.25 m in              ->  +4.25 m
    x = 99.75   water, 0.25 m outside hole    ->  −0.25 m
    x = 100.25  hole,  0.25 m inside          ->  +0.25 m

QUANTISED, and the quantisation is the contract: ``code = round(sd · 127/8) +
128``, so 0.25 m is code 128 + round(3.96875) = 132 and decodes to
4/15.875 = 0.251968…; 3.75 m is code 128 − 60 = 68 and decodes to
−3.779527…; 4.25 m is 128 + 67 = 195 -> +4.220472…. The step is 8/127 =
0.062992 m, i.e. a decoded value is never more than half a step (0.0315 m) from
the true one.

===========================================================================
[4] THE BAND, and what lies past it
===========================================================================
The distance is carried ±8 m and no further. At x = 56.25 the boundary at 64 is
7.75 m away — inside the band, so the texel still names the pair (2, 1) and a
negative distance. At x = 55.75 it is 8.25 m away, past the band: the pair
collapses to (own, own) = (1, 1) and the distance is the maximum positive code
255 -> +8.0 m. Both readings composite to the SAME picture (a weight of 0
against B = sand, and a weight of 1 against A = sand), which is what makes the
clamp invisible.

===========================================================================
[5] HOW FAR THE RASTER MAY BE FROM THE TRUE POLYGON
===========================================================================
The baked distance is measured to the LATTICE's own boundary — the midpoints
between samples of different rank — not to the drawn polygon. Along a straight
axis-aligned edge those coincide exactly (checked in [3]). Near a CORNER they
do not: the nearest site lies on the staircase the raster cut, up to the
diagonal of half a texel further away than the true corner. Swept over the
whole tile on the 0.5 m lattice, the largest disagreement with the analytic
distance-to-rectangle is asserted under HALF AN SD TEXEL (0.25 m); measured on
this fixture it is 0.2134 m, at the texel (63.75, 63.75) diagonally outside the
lake's own corner — where the nearest site really is (64.0, 64.25), one texel
along the staircase, and the analytic answer is the corner itself.

===========================================================================
[6] A TILE OF ONE GROUND CARRIES NO MASK AT ALL
===========================================================================
Tile (5, 5) lies 1 km from anything painted: no boundary in its whole apron, so
the bake answers ``{"uniform": 0}`` and ships neither array — 40 bytes instead
of 393 216. Tile (0, 0) ships both: ``id`` is 256² × 2 = 131 072 bytes, ``sd``
is 512² = 262 144 bytes.

===========================================================================
[7] THE TRANSITION WIDTH is a property of the MATERIAL
===========================================================================
``edge_blend_m`` on the terrain type, 0…8 m, default 1.5 (today's fringe). It
is the ONE catalog number where 0 is a VALUE and not "unset" — the hard cut of
a room floor — so it does NOT go through ``_clamped_meta_number``. Junk leaves
no key and reads back as the default.

===========================================================================
[8] THE PAYLOAD
===========================================================================
Index mode carries the table, the coarse overview and the tile keys; batch mode
carries the tiles, capped at ``BATCH_MAX``. A key the index does not know is
left out rather than answered empty.
"""

import base64
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="terrain-layers-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="terrain-layers-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import terrain_layers as TL  # noqa: E402
from app.core import terrain_query, terrain_types  # noqa: E402
from app.models import terrain  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected, tol=None):
    global CHECKED
    CHECKED += 1
    if tol is None:
        ok = actual == expected
    else:
        ok = abs(actual - expected) <= tol
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── The fixture ─────────────────────────────────────────────────────────────

AREAS = [
    {"id": "a_sand", "kind": "sand", "z_order": 0,
     "polygon": [[0, 0], [256, 0], [256, 256], [0, 256]]},
    {"id": "a_water", "kind": "water", "z_order": 0,
     "polygon": [[64, 64], [192, 64], [192, 192], [64, 192]]},
    {"id": "a_hole", "kind": "grass", "z_order": 0,
     "polygon": [[100, 100], [140, 100], [140, 140], [100, 140]]},
]
CATALOG = {
    "grass": {"kind": "grass", "surface": "grass", "meta": {}},
    "sand": {"kind": "sand", "surface": "sand",
             "meta": {TL.EDGE_BLEND_KEY: 0.0}},
    "water": {"kind": "water", "surface": "lake", "meta": {"water": True}},
}
#: The two rectangles whose OUTLINE is a boundary in the fixture. The sand
#: covers the whole tile, so its own rim lies outside every probe below.
RECTS = ((64.0, 64.0, 192.0, 192.0), (100.0, 100.0, 140.0, 140.0))


def rect_boundary_distance(x, z, r):
    """Distance from (x, z) to the OUTLINE of an axis-aligned rectangle."""
    x0, z0, x1, z1 = r
    dx = max(x0 - x, 0.0, x - x1)
    dz = max(z0 - z, 0.0, z - z1)
    if dx == 0.0 and dz == 0.0:
        return min(x - x0, x1 - x, z - z0, z1 - z)
    return math.hypot(dx, dz)


def main():
    model = TL.LayerModel(AREAS, CATALOG, "grass")

    print("\n[0] the layer table — index 0 is bare ground")
    check("the three layers, sorted after the default",
          [(l["index"], l["kind"]) for l in model.layers],
          [(0, "grass"), (1, "sand"), (2, "water")])
    check("a shape painted in the DEFAULT kind maps back onto layer 0",
          model.rank_layer, [0, 1, 2, 0])
    check("the surface is the TYPE's own id, never the kind's spelling",
          [l["surface"] for l in model.layers], ["grass", "sand", "lake"])
    check("water is flagged from the catalog, not from the name",
          [l["water"] for l in model.layers], [False, False, True])
    check("…and the transition width rides with it (sand asked for a hard cut)",
          [l["edge_blend_m"] for l in model.layers], [1.5, 0.0, 1.5])

    tile = TL.tile_masks(model, 0, 0)
    ids = base64.b64decode(tile["id"])
    sd = base64.b64decode(tile["sd"])
    id_n = tile["id_size"]
    sd_n = tile["sd_size"]

    def id_at(x, z):
        i = int(x // TL.ID_STEP_M)
        j = int(z // TL.ID_STEP_M)
        k = (j * id_n + i) * 2
        return (ids[k], ids[k + 1])

    def sd_at(x, z):
        i = int(x // TL.SD_STEP_M)
        j = int(z // TL.SD_STEP_M)
        return TL.decode_sd(sd[j * sd_n + i])

    print("\n[1] the raster IS the scalar rule, and both are kind_at")
    grid = model.rank_grid(0.0, 0.0, TL.SD_STEP_M, sd_n)
    layer_of_kind = {l["kind"]: l["index"] for l in model.layers}
    bad_raster = bad_query = 0
    probes = 0
    # 500 probes on a deterministic sweep of the 0.5 m lattice: every 131st
    # texel of the row-major array, which walks the whole tile without ever
    # repeating a column (131 is coprime with 512).
    for n in range(500):
        k = (n * 131) % (sd_n * sd_n)
        i = k % sd_n
        j = k // sd_n
        x = i * TL.SD_STEP_M + TL.SD_STEP_M / 2
        z = j * TL.SD_STEP_M + TL.SD_STEP_M / 2
        probes += 1
        if grid[j * sd_n + i] != model.rank_at(x, z):
            bad_raster += 1
        kind = terrain_query.kind_at(x, z, areas=AREAS, default_kind="grass")
        if layer_of_kind[kind] != model.layer_at(x, z):
            bad_query += 1
    check("probes taken", probes, 500)
    check("the scanline raster disagrees with rank_at nowhere", bad_raster, 0)
    check("…and neither disagrees with terrain_query.kind_at", bad_query, 0)

    print("\n[2] the pair is CANONICAL — the same (A, B) on both sides")
    Z = 128.25
    check("sand | water at x = 64: A = water, B = sand, on both sides",
          [id_at(63.5, Z), id_at(64.5, Z)], [(2, 1), (2, 1)])
    check("water | hole at x = 100: A = bare ground (painted last), B = water",
          [id_at(99.5, Z), id_at(100.5, Z)], [(0, 2), (0, 2)])
    check("…and the same pair at the hole's other side, x = 140",
          [id_at(139.5, Z), id_at(140.5, Z)], [(0, 2), (0, 2)])
    check("water | sand at x = 192 answers the water pair again",
          [id_at(191.5, Z), id_at(192.5, Z)], [(2, 1), (2, 1)])

    print("\n[3] the signed distance, exactly, on an axis-aligned row")
    q = 1.0 / TL.SD_CODES_PER_M
    check("0.25 m outside the lake", sd_at(63.75, Z), -4 * q, 1e-12)
    check("0.25 m inside it", sd_at(64.25, Z), 4 * q, 1e-12)
    check("3.75 m outside", sd_at(60.25, Z), -60 * q, 1e-12)
    check("4.25 m inside", sd_at(68.25, Z), 67 * q, 1e-12)
    check("0.25 m outside the hole (i.e. in the lake)", sd_at(99.75, Z), -4 * q, 1e-12)
    check("0.25 m inside the hole", sd_at(100.25, Z), 4 * q, 1e-12)
    check("the quantisation step is 8/127 m",
          round(q, 6), round(8.0 / 127.0, 6))

    print("\n[3b] the quantisation round-trips inside half a step")
    worst = 0.0
    for n in range(-1600, 1601):
        metres = n / 200.0                       # −8.000 … +8.000 in 5 mm steps
        code = int(round(metres * TL.SD_CODES_PER_M)) + TL.SD_ZERO
        code = 1 if code < 1 else (255 if code > 255 else code)
        worst = max(worst, abs(TL.decode_sd(code) - metres))
    check("no value in the band is more than half a step from its code",
          worst <= q / 2 + 1e-12, True)
    check("…and zero is EXACTLY representable", TL.decode_sd(TL.SD_ZERO), 0.0)
    check("the band ends where the contract says",
          [round(TL.decode_sd(1), 6), round(TL.decode_sd(255), 6)], [-8.0, 8.0])

    print("\n[4] the band, and what lies past it")
    check("7.75 m out still names the pair and a negative distance",
          [id_at(56.5, Z), round(sd_at(56.25, Z), 4)], [(2, 1), -7.748])
    check("8.25 m out is past the band: the pair collapses and the code saturates",
          [id_at(55.5, Z), sd_at(55.75, Z)], [(1, 1), 8.0])
    check("…and deep inside a ground it is the same statement",
          [id_at(30.0, Z), sd_at(30.0, Z)], [(1, 1), 8.0])

    print("\n[5] how far the raster may be from the true polygon")
    worst = 0.0
    worst_at = None
    for j in range(sd_n):
        cz = j * TL.SD_STEP_M + TL.SD_STEP_M / 2
        for i in range(sd_n):
            cx = i * TL.SD_STEP_M + TL.SD_STEP_M / 2
            true = min(rect_boundary_distance(cx, cz, r) for r in RECTS)
            if true > TL.SD_BAND_M - 0.5:
                continue
            err = abs(abs(TL.decode_sd(sd[j * sd_n + i])) - true)
            if err > worst:
                worst = err
                worst_at = (cx, cz)
    check("the whole tile stays under half an sd texel of the analytic distance",
          worst < TL.SD_STEP_M / 2, True)
    print(f"       measured worst: {worst:.4f} m at {worst_at}")

    print("\n[6] a tile of one ground carries no mask at all")
    far = TL.tile_masks(model, 5, 5)
    check("a tile a kilometre from anything painted is uniform bare ground",
          [far.get("uniform"), "id" in far, "sd" in far], [0, False, False])
    check("the fine tile ships an id of 256 x 256 x 2 bytes", len(ids), 131072)
    check("…and an sd of 512 x 512", len(sd), 262144)
    check("…which is what the two steps say", [id_n, sd_n], [256, 512])

    print("\n[7] the transition width is a property of the MATERIAL")
    check("a kind that says nothing gets today's 1.5 m fringe",
          TL.edge_blend_of({"meta": {}}), TL.EDGE_BLEND_DEFAULT_M)
    check("ZERO IS A VALUE — the hard cut of a room floor",
          TL.edge_blend_of({"meta": {TL.EDGE_BLEND_KEY: 0}}), 0.0)
    check("…and it survives the catalog sanitizer, where every other 0 would not",
          terrain_types.sanitize_type(
              {"kind": "floor", "meta": {TL.EDGE_BLEND_KEY: 0}})["meta"],
          {TL.EDGE_BLEND_KEY: 0.0})
    check("out of range is clamped, never refused",
          [TL.sanitize_edge_blend(-3), TL.sanitize_edge_blend(99)],
          [0.0, TL.EDGE_BLEND_MAX_M])
    check("junk leaves no key…",
          terrain_types.sanitize_type(
              {"kind": "floor", "meta": {TL.EDGE_BLEND_KEY: "wide"}})["meta"], {})
    check("…and reads back as the default", TL.edge_blend_of({"meta": {}}),
          TL.EDGE_BLEND_DEFAULT_M)

    print("\n[8] the payload")
    for area in AREAS:
        terrain.save_area(area)
    for kind, entry in CATALOG.items():
        terrain_types.save_world_type(entry)
    TL.invalidate_cache()
    index = TL.index_payload()
    # PURE BOX COVERAGE, seams included (the rule `heightfield.tile_index_from`
    # follows): the sand square ends exactly ON x = 256 and z = 256, and a point
    # on a seam belongs to the tile east/south of it — so the three neighbours
    # are indexed too and answer `uniform` sand. A shape that only touches a
    # tile still says "there may be something here"; the bake then says what.
    check("the index names every tile a painted shape reaches into, seams too",
          index["tile_keys"], ["0,0", "0,1", "1,0", "1,1"])
    # They are not UNIFORM, and that is the apron doing its job: the sand's own
    # rim at x = 256 lies 8 m inside their band, so they carry masks whose
    # interior is bare ground with the sand named as the runner-up. A tile that
    # only touches a shape still has to know about its edge, or the last 8 m of
    # the neighbour would end on a drawn line.
    east = TL.get_tile(1, 0)
    east_ids = base64.b64decode(east["id"])
    east_sd = base64.b64decode(east["sd"])
    check("…and the three the sand only TOUCHES carry a mask, not a uniform",
          [east.get("uniform"), "id" in east], [None, True])
    check("…whose first metre still names the pair (sand on top, bare under)",
          (east_ids[(128 * 256 + 0) * 2], east_ids[(128 * 256 + 0) * 2 + 1]),
          (1, 0))
    check("…at a quarter metre outside the sand", 
          round(TL.decode_sd(east_sd[256 * 512 + 0]), 4), -0.252)
    check("…while its far side is bare ground and nothing else",
          (east_ids[(128 * 256 + 200) * 2], east_ids[(128 * 256 + 200) * 2 + 1],
           TL.decode_sd(east_sd[256 * 512 + 400])), (0, 0, 8.0))
    check("…carries the layer table",
          [l["kind"] for l in index["layers"]], ["grass", "sand", "water"])
    check("…and the format the bytes decode with",
          [index["id_step_m"], index["sd_step_m"], index["sd_band_m"],
           index["sd_zero"], round(index["sd_codes_per_m"], 6)],
          [1.0, 0.5, 8.0, 128, round(127 / 8, 6)])
    ov = index["overview"]
    check("the coarse world mask is one pair per 8 m texel",
          [ov["step_m"], len(base64.b64decode(ov["id"]))],
          [8.0, ov["cols"] * ov["rows"] * 2])
    batch = TL.batch_payload([(0, 0), (9, 9)])
    check("a batch answers only the tiles the index knows",
          sorted(batch["tiles"]), ["0,0"])
    check("…under the same signature as the index", batch["sig"], index["sig"])
    check("the query parser is the height tiles' own, capped at BATCH_MAX",
          len(TL.parse_keys(",".join(f"{i}:0" for i in range(40)))),
          TL.BATCH_MAX)

    print("\n[9] the RED counter-probes")
    # (a) THE CANONICAL ORDER. Pair the layers by "the one I am standing on"
    #     instead of "the one painted later" and the pair FLIPS across the line
    #     — the id then changes with every texel seam and the linear distance
    #     no longer belongs to it. Measured on the truth: it does not flip.
    check("no boundary in the fixture carries two different pairs",
          [id_at(63.5, Z) == id_at(64.5, Z), id_at(99.5, Z) == id_at(100.5, Z),
           id_at(139.5, Z) == id_at(140.5, Z),
           id_at(191.5, Z) == id_at(192.5, Z)], [True, True, True, True])
    # (b) THE PRIORITY. Reverse the paint order and the hole loses to the lake:
    #     the same three polygons, the opposite answer, which is what makes the
    #     order in [1] a measurement rather than a coincidence.
    reversed_model = TL.LayerModel(list(reversed(AREAS)), CATALOG, "grass")
    check("painted the other way round, the lake wins the hole's ground",
          [model.layer_at(120.0, 120.0), reversed_model.layer_at(120.0, 120.0)],
          [0, 1])
    # (c) THE SIGN. If it were taken from the texel's own layer instead of from
    #     the site's higher rank, the distance would be positive on both sides
    #     of every line and the blend would show A everywhere.
    check("the sign really turns over at the line",
          [sd_at(63.75, Z) < 0, sd_at(64.25, Z) > 0], [True, True])

    print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
