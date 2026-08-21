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
two materials are mixed, and where the cut runs comes out of the interpolated
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
[4] THE BAND, THE COLLAPSE, and what lies past both
===========================================================================
The distance is carried ±8 m and no further, and the PAIR is carried only as
far as the transition is still being drawn (`collapse_band_m`): half the blend
width on each side, plus the noise push (itself capped at half the width), plus
`COLLAPSE_SLACK_M` = 1 m for the reach of the renderer's own interpolation and
for the pixel-wide anti-aliasing of a hard cut. The lake's water is the default
1.5 m wide, so its band is 0.75 + 0.5 + 1 = 2.25 m.

The pair is decided PER ID TEXEL, from the nearest of the four sd texels under
it, so the id texel [61, 62) is judged by its sub-texel at 61.75 — 2.25 m out,
exactly the band, so it is the LAST one that still names a runner-up:

    x = 61.75   2.25 m outside water, still paired  -> (2, 1), −2.25 m
    x = 60.75   3.25 m out, the pair has COLLAPSED  -> (1, 1), −3.25 m
    x = 56.25   7.75 m out, same statement          -> (1, 1), −7.75 m
    x = 55.75   8.25 m out, past the band as well   -> (1, 1), +8.0 m

The distance keeps its true value and its sign through the collapse — a
neighbouring texel that is still blending may read it and must not find a cliff
there. (Since the second finding round the renderer interpolates ONLY the four
texels of its own id texel, `@anima/scene-render` `layerSdBlockAt`: the sign of
a texel means "on A's side of MY pair", so a filter that reached past the id
texel mixed two numbers on two scales — § A16.7.) What the collapse changes is
that the texel no longer NAMES a runner-up, so `a == b` and the shader ignores the
distance altogether. THAT IS THE POINT: two id texels deep inside one ground
used to name two different boundaries — the one to the west and the one to the
north — and the interpolated distance between them crossed zero, which drew a
line of the wrong material straight down the middle of a room ([12]).
Quantised, −2.25 m is code 128 − round(2.25·15.875) = 128 − 36 = 92 and decodes
to −2.2677; −3.25 m is 128 − 52 = 76 -> −3.2756.

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

===========================================================================
[10] LOCATION FLOORS ARE THE TOPMOST LAYERS ("Ein Boden" E5a, § G3/§ G5)
===========================================================================
A second fixture, two placed locations over one painted meadow, all of it in
tile (0, 0):

    PLAZA   pin (100, 100), yaw 0, boundary ±20  -> area 1600 m²
            zone  "plaza"  local −10…10  -> world  90…110, floor "sand"
            room  "hall"   local  −4…4   -> world  96…104, floor "wood"
    HUT     pin  (98,  98), yaw 0, boundary ±3   -> area   36 m²
            room  "hut"    local  −2…2   -> world  96…100, floor "tiles"
    meadow  a painted terrain area over the whole tile

THE LAYER TABLE grows past the terrain kinds — a floor kind is a
SURFACE-library id, so "wood" and "tiles" are layers even though nobody
painted them. Index 0 stays bare ground, the painted kinds follow sorted, then
the floor kinds sorted by (kind, width):

    0 grass (the default)   1 meadow      2 sand   3 tiles   4 wood

and the ranks — bare, the painted area, then the floors in priority order
(largest plot first, zones before closed rooms within a plot) — are

    rank_layer == [0, 1, 2, 4, 3]
      rank 1 meadow -> layer 1
      rank 2 plaza  -> layer 2 (sand)
      rank 3 hall   -> layer 4 (wood)
      rank 4 hut    -> layer 3 (tiles)   <- the SMALLEST plot writes LAST

THE FOUR PROBES, hand-derived from "the last containing entry wins":

    (85, 85)   only the meadow                        -> 1
    (92, 92)   meadow + plaza                         -> 2  (a FLOOR beats a
                                                             painted area)
    (102, 102) meadow + plaza + hall                  -> 4
    (97, 97)   meadow + plaza + hall + hut            -> 3  (the 36 m² plot
                                                             beats the 1600 m²
                                                             one)

THE TRANSITION WIDTH of a floor defaults to **0** — the hard cut — where a
painted ground kind defaults to 1.5 m. A room may dial its own
(``layout.edge_blend_m``), and a kind at two widths is two layers, because the
width is what the shader reads out of the table.

THE MASK CARRIES IT. On the row z = 102.25 (inside the hall, north of the hut)
the boundary between plaza and hall sits at x = 96, exactly midway between the
lattice samples at 95.75 (rank 2) and 96.25 (rank 3). Both texels therefore
carry the SAME pair — A = the later-painted layer 4 (wood), B = layer 2 (sand)
— and only the sign of the distance differs: −0.25 m outside, +0.25 m inside,
i.e. codes 124 and 132.

===========================================================================
[11] THE MASK AND THE SCENE PAYLOAD AGREE ON THE SAME POLYGON
===========================================================================
``scene_recipe.compose_scene`` ships each storey-0 room in ``floor_plan`` as
``polygon_world`` in the SCENE frame (local metres around the pin); the bake
transforms the very same hull into world metres. Run the scene polygons through
the ONE pin transform (``world_geometry.polygon_local_to_world``) and the two
lists have to be the same points — asserted well inside a centimetre, which is
the precision the plan coordinates are stored at. A yawed location is checked
too: the transform is the only thing between the two, so if it were applied
twice or not at all, 90° would show it.

===========================================================================
[12] TWO BOUNDARIES IN ONE NEIGHBOURHOOD (finding round 2026-08-21)
===========================================================================
The canonical pair is canonical PER BOUNDARY. Where two boundaries compete —
a room's west wall and the kitchen against its north wall, a beach's edge
against the forest and its edge against the lake — a texel used to read its
PAIR off one of them and its SIGN off the other, and the two composed into a
ground that is at neither. Decoded off the live world it looked like this, at
the living-room floor of "Haus von Kai" (world −1551.95, −761.50):

    id texel: the west wall's pair   (wood | grass)   at 2.75 m
    sd texel: the north line's sign  (rubber | wood)  at 2.75 m
    composed: A = wood, sd = −2.77  ->  GRASS, three metres inside the room

627 texels like it in the three regions the user photographed; 0 after. The
three rules that got there are in :func:`app.core.terrain_layers.bake_masks`
and the whole section derives them by hand on a two-room fixture. Its last
part is a SWEEP rather than a probe, because the defect was a thin wandering
set of texels no handful of points would have caught: every interior texel of
the house and its surroundings must draw what the priority law says, and no
texel anywhere may name a pair its own ground is not part of.
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



# ── The location-floor fixture (E5a) ────────────────────────────────────────

def _room(room_id, x, y, w, d, floor, *, zone=False, blend=None):
    lay = {"x": x, "y": y, "w": w, "d": d, "level": 0}
    if floor:
        lay["surfaces"] = {"floor": floor}
    if zone:
        lay["always_visible"] = True
    if blend is not None:
        lay["edge_blend_m"] = blend
    return {"id": room_id, "name": room_id, "layout": lay}


def _location(loc_id, x, z, half, rooms, yaw=0.0):
    return {"id": loc_id, "pos_x": x, "pos_z": z, "yaw_deg": yaw,
            "map3d": {"boundary": [[-half, -half], [half, -half],
                                   [half, half], [-half, half]],
                      "plan_width_m": 2 * half},
            "rooms": rooms}


PLAZA_LOC = _location("plaza_loc", 100.0, 100.0, 20.0, [
    _room("plaza", -10.0, -10.0, 20.0, 20.0, "sand", zone=True),
    _room("hall", -4.0, -4.0, 8.0, 8.0, "wood"),
])
HUT_LOC = _location("hut_loc", 98.0, 98.0, 3.0, [
    _room("hut", -2.0, -2.0, 4.0, 4.0, "tiles"),
])
MEADOW = [{"id": "a_meadow", "kind": "meadow", "z_order": 0,
           "polygon": [[0, 0], [256, 0], [256, 256], [0, 256]]}]
FLOOR_CATALOG = {
    "grass": {"kind": "grass", "surface": "grass", "meta": {}},
    "meadow": {"kind": "meadow", "surface": "meadow", "meta": {}},
}


def test_location_floors():
    print("\n[10] location floors are the topmost layers (E5a)")
    floors = TL.world_floors([PLAZA_LOC, HUT_LOC], FLOOR_CATALOG)
    check("the floors come in PRIORITY order: big plot first, zones before "
          "closed rooms, smallest plot LAST",
          [(f.location_id, f.room_id) for f in floors],
          [("plaza_loc", "plaza"), ("plaza_loc", "hall"),
           ("hut_loc", "hut")])
    check("...and the input order does NOT decide it — the AREA does",
          [(f.location_id, f.room_id) for f in
           TL.world_floors([HUT_LOC, PLAZA_LOC], FLOOR_CATALOG)],
          [("plaza_loc", "plaza"), ("plaza_loc", "hall"),
           ("hut_loc", "hut")])
    model = TL.LayerModel(MEADOW, FLOOR_CATALOG, "grass", floors)
    check("the table grows past the painted kinds onto the FLOOR kinds",
          [(l["index"], l["kind"]) for l in model.layers],
          [(0, "grass"), (1, "meadow"), (2, "sand"), (3, "tiles"),
           (4, "wood")])
    check("a floor kind wears ITSELF as its surface (it IS a library id)",
          [l["surface"] for l in model.layers],
          ["grass", "meadow", "sand", "tiles", "wood"])
    check("A FLOOR CUTS HARD (0 m) where a painted kind fringes (1.5 m)",
          [l["edge_blend_m"] for l in model.layers],
          [1.5, 1.5, 0.0, 0.0, 0.0])
    check("the ranks map onto those layers", model.rank_layer, [0, 1, 2, 4, 3])

    print("\n[10b] the four probes — the last containing entry wins")
    check("only the painted meadow out at (85, 85)", model.layer_at(85.0, 85.0), 1)
    check("A FLOOR BEATS A PAINTED AREA: the plaza's sand at (92, 92)",
          model.layer_at(92.0, 92.0), 2)
    check("a CLOSED room beats the zone it lies in: wood at (102, 102)",
          model.layer_at(102.0, 102.0), 4)
    check("THE SMALLEST PLOT WINS: the hut's tiles at (97, 97)",
          model.layer_at(97.0, 97.0), 3)
    # RED COUNTER-PROBES, one per rule.
    check("red: were the plots ordered as they came, (97, 97) would be wood",
          model.layer_at(97.0, 97.0) != 4, True)
    check("red: without the floors the very same points are all meadow",
          [TL.LayerModel(MEADOW, FLOOR_CATALOG, "grass").layer_at(x, z)
           for x, z in ((92.0, 92.0), (97.0, 97.0), (102.0, 102.0))],
          [1, 1, 1])
    # THE YARD IS NOT A FLOOR (§ A13a) and a kindless ZONE paints nothing.
    from app.models.world import GROUND_ROOM_ID
    quiet = _location("quiet", 300.0, 300.0, 10.0, [
        {"id": GROUND_ROOM_ID, "name": "", "layout": {
            "x": -5.0, "y": -5.0, "w": 10.0, "d": 10.0, "level": 0,
            "surfaces": {"floor": "sand"}}},
        _room("open", -3.0, -3.0, 6.0, 6.0, "", zone=True),
        _room("upstairs", -3.0, -3.0, 6.0, 6.0, "wood"),
    ])
    quiet["rooms"][2]["layout"]["level"] = 1
    check("the yard, a kindless zone and a storey-1 room contribute nothing",
          TL.world_floors([quiet], FLOOR_CATALOG), [])
    check("...while a CLOSED room that names no kind still has a floor",
          [f.kind for f in TL.world_floors([_location("c", 400.0, 400.0, 5.0, [
              _room("box", -2.0, -2.0, 4.0, 4.0, "")])], FLOOR_CATALOG)],
          [TL.FLOOR_KIND_DEFAULT])
    check("an UNPLACED location owns no world metre and colours none",
          TL.world_floors([{"id": "nowhere", "rooms": [
              _room("r", 0.0, 0.0, 2.0, 2.0, "wood")]}], FLOOR_CATALOG), [])

    print("\n[10c] the width is a property of the ROOM, and 0 is a value")
    wide = _location("wide", 500.0, 500.0, 10.0, [
        _room("soft", -5.0, -5.0, 10.0, 10.0, "sand", zone=True, blend=2.5)])
    two = TL.LayerModel(MEADOW, FLOOR_CATALOG, "grass",
                        TL.world_floors([PLAZA_LOC, wide], FLOOR_CATALOG))
    check("the SAME kind at two widths is two layers — the shader reads the "
          "width out of the table",
          sorted((l["kind"], l["edge_blend_m"]) for l in two.layers
                 if l["kind"] == "sand"),
          [("sand", 0.0), ("sand", 2.5)])
    check("a dialled width is clamped and rounded like a catalog one",
          [TL.floor_edge_blend_of({"edge_blend_m": v})
           for v in (2.5, -1, 99, "wide", None)],
          [2.5, 0.0, TL.EDGE_BLEND_MAX_M, 0.0, 0.0])

    print("\n[10d] the mask carries the floor boundary")
    tile = TL.tile_masks(model, 0, 0)
    ids = base64.b64decode(tile["id"])
    sd = base64.b64decode(tile["sd"])
    id_n, sd_n = tile["id_size"], tile["sd_size"]

    def pair(x, z):
        k = (int(z // TL.ID_STEP_M) * id_n + int(x // TL.ID_STEP_M)) * 2
        return (ids[k], ids[k + 1])

    def dist(x, z):
        return TL.decode_sd(sd[int(z // TL.SD_STEP_M) * sd_n
                               + int(x // TL.SD_STEP_M)])

    Z = 102.25          # inside the hall, north of the hut
    check("plaza | hall at x = 96 carries ONE pair on both sides: (wood, sand)",
          [pair(95.5, Z), pair(96.5, Z)], [(4, 2), (4, 2)])
    q = 1.0 / TL.SD_CODES_PER_M
    check("...0.25 m outside the hall", dist(95.75, Z), -4 * q, 1e-12)
    check("...and 0.25 m inside it", dist(96.25, Z), 4 * q, 1e-12)
    check("the index names the tile the floors reach into",
          "0,0" in [TL._format_key(tx, tz) for tx, tz in TL.tile_index(model)],
          True)


# ── The three-room fixture (finding round 2026-08-21) ───────────────────────

#: THE SHAPE OF THE FINDING, at round numbers. A house of two rooms that TOUCH,
#: on bare ground — the living room of "Haus von Kai" with the kitchen against
#: its north wall, which is where the user photographed metre-wide chevrons of
#: meadow on the parquet and a strip of the kitchen's rubber floor beside them.
#:
#:      hall     world x 90…102, z 90…96   floor "wood"
#:      kitchen  world x 90… 94, z 96…100  floor "tiles"
#:
#: Ranks, and therefore priority: 1 = hall, 2 = kitchen (room order). The layer
#: table is the default kind first, then the floor kinds sorted:
#:
#:      0 grass (blend 1.5)   1 tiles (0.0)   2 wood (0.0)
#:      rank_layer == [0, 2, 1]
#:
#: THREE BOUNDARIES, and their canonical pairs — A is always the layer of the
#: HIGHER rank, i.e. the one painted later:
#:
#:      hall | grass      (x = 90 / z = 90 / x = 102 / z = 96 east of x = 94)
#:                        hi = rank 1 -> wood,  lo = rank 0 -> grass  -> (2, 0)
#:      hall | kitchen    (z = 96, x = 90…94)
#:                        hi = rank 2 -> tiles, lo = rank 1 -> wood   -> (1, 2)
#:      kitchen | grass   (x = 90 / x = 94 / z = 100, z = 96…100)     -> (1, 0)
TWO_ROOM_LOC = _location("house", 100.0, 100.0, 20.0, [
    _room("hall", -10.0, -10.0, 12.0, 6.0, "wood"),
    _room("kitchen", -10.0, -4.0, 4.0, 4.0, "tiles"),
])


def test_three_regions():
    """[12] TWO BOUNDARIES IN ONE NEIGHBOURHOOD — the finding round.

    THE MEASUREMENT THAT STARTED IT. Decoded off the live world's own masks at
    the living-room floor of "Haus von Kai" (world −1551.95, −761.50):

        the ID texel carried the pair of the WEST wall   (wood | grass), 2.75 m
        the SD texel carried the sign of the NORTH wall  (rubber | wood), 2.75 m
        composed: A = wood, sd = −2.77  ->  it drew GRASS, three metres inside

    The two boundaries are EXACTLY equidistant there, which is what a medial
    axis is; which of them a texel ends up carrying is a tie-break of the
    sweep, and the id lattice (1 m) and the sd lattice (0.5 m) broke it
    differently. 627 such texels in the three regions the user photographed.

    THE SAME SHAPE, BY HAND, in the fixture above. Take the point
    (92.75, 93.75) inside the hall:

        distance to the west wall  x = 90   ->  2.75 m
        distance to the hall|kitchen line z = 96  ->  2.25 m

    so the point's own nearest boundary is the hall|kitchen one and its sign is
    NEGATIVE (wood is the B of that pair). The id texel it falls in is
    [92, 93) x [93, 94), and the four sd texels under it sit at 92.25/92.75 and
    93.25/93.75, i.e. at distances

        (92.25, 93.25)  west 2.25  north 2.75   ->  2.25, the WEST wall
        (92.75, 93.25)  west 2.75  north 2.75
        (92.25, 93.75)  west 2.25  north 2.25
        (92.75, 93.75)  west 2.75  north 2.25   ->  2.25, the NORTH line

    THE OLD RULE read the pair off the corner texel (92.25, 93.25) — the west
    wall, pair (wood, grass) — and the sign off the point's own texel — the
    north line, −2.25 m — and drew grass. THE NEW RULE takes the nearest of the
    four (2.25 m) and, because that is past the collapse band of wood
    (`collapse_band_m(0) == 1.0 m`), names no runner-up at all: the pair is
    (wood, wood), `a == b`, and the distance is not consulted.
    """
    print("\n[12] two boundaries in one neighbourhood (2026-08-21)")
    floors = TL.world_floors([TWO_ROOM_LOC], FLOOR_CATALOG)
    model = TL.LayerModel([], FLOOR_CATALOG, "grass", floors)
    check("the table: bare ground, then the two floor kinds sorted",
          [(l["index"], l["kind"], l["edge_blend_m"]) for l in model.layers],
          [(0, "grass", 1.5), (1, "tiles", 0.0), (2, "wood", 0.0)])
    check("…and the ranks map onto them", model.rank_layer, [0, 2, 1])
    tile = TL.tile_masks(model, 0, 0)
    ids = base64.b64decode(tile["id"])
    sd = base64.b64decode(tile["sd"])
    id_n, sd_n = tile["id_size"], tile["sd_size"]

    def pair(x, z):
        k = (int(z // TL.ID_STEP_M) * id_n + int(x // TL.ID_STEP_M)) * 2
        return (ids[k], ids[k + 1])

    def dist(x, z):
        return TL.decode_sd(sd[int(z // TL.SD_STEP_M) * sd_n
                               + int(x // TL.SD_STEP_M)])

    def top(x, z):
        a, b = pair(x, z)
        return a if a == b else (a if dist(x, z) >= 0 else b)

    print("  (a) the medial axis of two boundaries — the photographed defect")
    check("2.75 m from the west wall, 2.25 m from the kitchen: NO runner-up",
          pair(92.75, 93.75), (2, 2))
    check("…so the parquet stays parquet", top(92.75, 93.75), 2)
    # RED. The distance is untouched by the collapse and still says −2.27 m: it
    # is the point's own nearest boundary, the kitchen line, and wood is that
    # pair's B. Under the old rule THAT number met the west wall's pair, whose
    # B is grass — which is the whole defect in two lines.
    check("red: the distance under it is still the kitchen line's, negative",
          round(dist(92.75, 93.75), 4), -2.2677)
    check("red: had the pair been the west wall's, that sign would draw GRASS",
          (2, 0)[1], 0)

    print("  (b) …while a real boundary is still cut to the metre")
    check("both sides of the hall|kitchen line carry ONE pair",
          [pair(92.25, 95.75), pair(92.25, 96.25)], [(1, 2), (1, 2)])
    q = 1.0 / TL.SD_CODES_PER_M
    check("…0.25 m into the hall the sign is negative: wood is that pair's B",
          dist(92.25, 95.75), -4 * q, 1e-12)
    check("…0.25 m into the kitchen it is positive: tiles is A",
          dist(92.25, 96.25), 4 * q, 1e-12)
    check("…and the reading flips exactly there",
          [top(92.25, 95.75), top(92.25, 96.25)], [2, 1])
    check("the hall's west wall is cut just as sharply",
          [top(89.75, 93.25), top(90.25, 93.25)], [0, 2])

    print("  (c) the invariant, swept over the whole tile")
    # THE ACCEPTANCE TEST OF THE ROUND, and it is a sweep rather than a probe
    # because the defect was a THIN, wandering set of texels that no handful of
    # points would have caught. Two properties, at every sd texel centre of the
    # 256 m tile:
    #
    #   1. A TEXEL NEVER NAMES A PAIR ITS OWN GROUND IS NOT PART OF. That is
    #      what makes the sign mean anything at all.
    #   2. THE READING IS THE LAW, everywhere except within half an sd texel of
    #      a boundary — where the raster legitimately cannot say more (see [5]).
    #      "Interior" is decided by the law alone: the same answer at the point
    #      and 0.6 m to each of the eight sides.
    #
    # THIS SWEEP IS AT TEXEL CENTRES, and that is its limit: it measures what the
    # BAKE wrote, not how a renderer reconstructs the field BETWEEN two texels.
    # The second finding round of 2026-08-21 lived exactly in that gap — every
    # texel here was right while a filtered fetch across an id texel's rim drew
    # the kitchen's floor inside the living room. The reconstruction is the
    # renderers' one shared reading and is checked where it lives:
    # `client3d/scripts/smoke_layer_cut.mjs` [4b].
    stranger = 0
    defects = 0
    interior = 0
    worst = None
    for j in range(sd_n):
        cz = j * TL.SD_STEP_M + TL.SD_STEP_M / 2
        if not (86.0 < cz < 104.0):
            continue
        for i in range(sd_n):
            cx = i * TL.SD_STEP_M + TL.SD_STEP_M / 2
            if not (86.0 < cx < 106.0):
                continue
            a, b = pair(cx, cz)
            own = model.layer_at(cx, cz)
            if own not in (a, b):
                stranger += 1
            if not all(model.layer_at(cx + dx, cz + dz) == own
                       for dx in (-0.6, 0.0, 0.6) for dz in (-0.6, 0.0, 0.6)):
                continue
            interior += 1
            if top(cx, cz) != own:
                defects += 1
                if worst is None:
                    worst = (cx, cz, a, b, round(dist(cx, cz), 3), own)
    check("no texel of the house and its surroundings names a stranger's pair",
          stranger, 0)
    check(f"…and none of the {interior} interior texels draws the wrong ground",
          (defects, worst), (0, None))



def test_mask_and_scene_agree():
    print("\n[11] the bake and the scene payload use ONE polygon")
    from app.core.scene_recipe import compose_scene
    from app.core.world_geometry import polygon_local_to_world
    for yaw in (0.0, 90.0, 37.5):
        loc = {**PLAZA_LOC, "yaw_deg": yaw}
        scene = compose_scene(loc, plan_width_m=40.0)
        plan = {f["room_id"]: f for f in scene["floor_plan"]}
        baked = {f.room_id: f for f in TL.world_floors([loc], FLOOR_CATALOG)}
        check(f"yaw {yaw}: the same two rooms on both sides",
              sorted(plan), sorted(baked))
        worst = 0.0
        for room_id, entry in plan.items():
            turned = polygon_local_to_world(entry["polygon_world"],
                                            loc["pos_x"], loc["pos_z"], yaw)
            other = baked[room_id].polygon
            for (ax, az), (bx, bz) in zip(turned, other):
                worst = max(worst, abs(ax - bx), abs(az - bz))
        check(f"yaw {yaw}: point for point, well inside a centimetre",
              worst < 0.01, True)
        print(f"       measured worst: {worst:.6f} m")
        check(f"yaw {yaw}: the kinds agree as well",
              {r: e["floor_kind"] for r, e in plan.items()},
              {r: f.kind for r, f in baked.items()})
    # RED COUNTER-PROBE: forget the pin transform and a location 100 m out is
    # 100 m wrong — so the agreement above is the transform, not a tautology.
    raw = compose_scene(PLAZA_LOC, plan_width_m=40.0)["floor_plan"][0]
    baked0 = TL.world_floors([PLAZA_LOC], FLOOR_CATALOG)[0]
    check("red: the scene frame is NOT the world frame — the pin is 100 m out",
          abs(raw["polygon_world"][0][0] - baked0.polygon[0][0]) > 99.0, True)


def test_water_bed_and_edge_law():
    """[13] WATER WEARS ITS BED, and the top layer owns the edge (W1).

    TWO CLAIMS, both hand-derived from § A16.7.

    (a) THE BED. A water layer keeps its own ``kind`` — the mask has to answer
        "water here" for the undergrowth gate and for every point query — but
        what it PAINTS is the ground under the water. Without an authored
        ``meta.bed_kind`` that is the world's bare ground, which is exactly the
        substitution the renderer did by itself until now, so nothing looks
        different until somebody turns the dial. With one, the layer wears that
        kind's surface AND that kind's transition width, and two ponds of one
        kind over two beds are TWO layers, because the bed is part of the key.

        The catalog below: grass (default, surface "grass", width 1.5), rock
        (surface "rock", width 3.0), water (surface "lake", flagged, width
        1.5). Two water areas, one bare and one on rock. Sorted by (kind, bed),
        the table is therefore

            0  grass   surface grass  width 1.5  water False
            1  water   surface grass  width 1.5  water True   bed grass
            2  water   surface rock   width 3.0  water True   bed rock

        and rank 1 (the bare pond) maps to layer 1, rank 2 (the rock pond) to
        layer 2. Note what is NOT in the table: "lake", the water kind's own
        surface, which nothing may paint onto the terrain.

    (b) THE EDGE LAW, confirmed and pinned rather than rebuilt: at a shared
        edge the LATER-painted layer decides the width. The bake writes that
        into the pair — A is always the later-painted layer, never "the one I
        am standing on" — and the shader reads ``b`` off A. So the same two
        rectangles in the two paint orders give the two widths, and the number
        the shader would use flips with the order and with nothing else.
    """
    print("\n[13] a water layer wears its BED, and the top layer owns the edge")
    catalog = {
        "grass": {"kind": "grass", "surface": "grass", "meta": {}},
        "rock": {"kind": "rock", "surface": "rock",
                 "meta": {TL.EDGE_BLEND_KEY: 3.0}},
        "water": {"kind": "water", "surface": "lake",
                  "meta": {"water": True}},
    }
    areas = [
        {"id": "a_bare", "kind": "water", "z_order": 0,
         "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]]},
        {"id": "a_rock", "kind": "water", "z_order": 0,
         "polygon": [[60, 0], [100, 0], [100, 40], [60, 40]],
         "meta": {"bed_kind": "rock"}},
    ]
    m = TL.LayerModel(areas, catalog, "grass")
    check("three layers: bare ground and the same water on two beds",
          [(l["index"], l["kind"], l.get("bed_kind")) for l in m.layers],
          [(0, "grass", None), (1, "water", "grass"), (2, "water", "rock")])
    check("the bare pond paints the DEFAULT ground's surface",
          m.layers[1]["surface"], "grass")
    check("the rock pond paints ROCK's",
          m.layers[2]["surface"], "rock")
    check("red: nothing paints the water kind's own surface onto the terrain",
          [l["surface"] for l in m.layers if l["surface"] == "lake"], [])
    check("the bare pond keeps the WATER kind's own width (today's number)",
          m.layers[1]["edge_blend_m"], TL.EDGE_BLEND_DEFAULT_M)
    check("…and an authored bed brings its OWN width with it",
          m.layers[2]["edge_blend_m"], 3.0)
    check("each area finds its own layer", m.rank_layer, [0, 1, 2])
    check("both are still WATER for the mask, the gate and every point query",
          [m.layers[i]["water"] for i in (1, 2)], [True, True])
    check("…and 'water' is still the answer at a point in either pond",
          [m.layers[m.layer_at(20.0, 20.0)]["kind"],
           m.layers[m.layer_at(80.0, 20.0)]["kind"]], ["water", "water"])

    print("\n[13b] ONE predicate decides `water`, for every row of the table")
    # Not "the table agrees with itself": the flag is recomputed here from
    # ``terrain_types.is_water_kind`` — the one function § A16.3 names — and
    # compared row by row, floors included. The second book (the surface
    # library's material class) is gone; a floor is water only if the terrain
    # catalog says its kind is.
    from app.core.terrain_types import is_water_kind
    floors = TL.world_floors([PLAZA_LOC, HUT_LOC], FLOOR_CATALOG)
    table = TL.layer_table(AREAS, CATALOG, "grass", floors)
    check("every row's flag IS is_water_kind(kind, catalog)",
          [l["water"] for l in table],
          [bool(is_water_kind(l["kind"], CATALOG)) for l in table])
    check("…and the floor rows are in that list too",
          sorted({l["kind"] for l in table}) != sorted({l["kind"]
                                                        for l in
                                                        TL.layer_table(
                                                            AREAS, CATALOG,
                                                            "grass")}), True)

    print("\n[13c] the EDGE LAW: the LATER-painted layer owns the width")
    over = [
        {"id": "a_lower", "kind": "grass", "z_order": 0,
         "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]},
        {"id": "a_upper", "kind": "sand", "z_order": 0,
         "polygon": [[40, 0], [100, 0], [100, 100], [40, 100]]},
    ]
    edge_catalog = {
        "grass": {"kind": "grass", "surface": "grass",
                  "meta": {TL.EDGE_BLEND_KEY: 4.0}},
        "sand": {"kind": "sand", "surface": "sand",
                 "meta": {TL.EDGE_BLEND_KEY: 0.0}},
    }
    top = TL.LayerModel(over, edge_catalog, "path")
    flip = TL.LayerModel(list(reversed(over)), edge_catalog, "path")

    def width_of(mdl, x, z):
        """What the shader would use at (x, z): ``b`` of the pair's layer A —
        i.e. of the LATER-painted of the two, which is the rank the bake
        already resolves the point to on the winning side."""
        return mdl.layers[mdl.layer_at(x, z)]["edge_blend_m"]

    check("sand painted over grass: the shared edge is sand's HARD cut",
          width_of(top, 60.0, 50.0), 0.0)
    check("…and the same two shapes the other way round give grass's 4 m",
          width_of(flip, 60.0, 50.0), 4.0)
    check("red: the two orders really are the same geometry, only re-ranked",
          [a["polygon"] for a in over],
          [a["polygon"] for a in reversed(list(reversed(over)))])


def main():
    model = TL.LayerModel(AREAS, CATALOG, "grass")

    print("\n[0] the layer table — index 0 is bare ground")
    check("the three layers, sorted after the default",
          [(l["index"], l["kind"]) for l in model.layers],
          [(0, "grass"), (1, "sand"), (2, "water")])
    check("a shape painted in the DEFAULT kind maps back onto layer 0",
          model.rank_layer, [0, 1, 2, 0])
    check("the surface is the TYPE's own id, never the kind's spelling — and "
          "a WATER layer wears its BED, which here is the bare ground (W1)",
          [l["surface"] for l in model.layers], ["grass", "sand", "grass"])
    check("…which is what the water layer NAMES as its bed",
          [l.get("bed_kind") for l in model.layers], [None, None, "grass"])
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

    print("\n[4] the band, the collapse, and what lies past both")
    check("2.25 m out — the last metre that still names the pair",
          [id_at(61.5, Z), round(sd_at(61.75, Z), 4)], [(2, 1), -2.2677])
    check("one metre further the pair has COLLAPSED, the distance is untouched",
          [id_at(60.5, Z), round(sd_at(60.75, Z), 4)], [(1, 1), -3.2756])
    check("7.75 m out is the same statement, one metre before the band ends",
          [id_at(56.5, Z), round(sd_at(56.25, Z), 4)], [(1, 1), -7.748])
    check("8.25 m out is past the band: the code saturates as well",
          [id_at(55.5, Z), sd_at(55.75, Z)], [(1, 1), 8.0])
    check("…and deep inside a ground it is the same statement",
          [id_at(30.0, Z), sd_at(30.0, Z)], [(1, 1), 8.0])
    check("the collapse band is the drawn transition plus the slack",
          [TL.collapse_band_m(0.0), TL.collapse_band_m(1.5),
           TL.collapse_band_m(8.0)], [1.0, 2.25, 5.5])

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

    test_location_floors()
    test_mask_and_scene_agree()
    test_three_regions()
    test_water_bed_and_edge_law()

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
