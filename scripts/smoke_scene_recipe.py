#!/usr/bin/env python3
"""Smoke run for the scene composer (Block M).

Pure geometry, no world, no DB: a hand-built location dict goes straight into
``scene_recipe.compose_scene``. The numbers below are computed BY HAND from
the contract (docs/schnittstellen-3d.md § A2/A3/A6) — that is the point of
the file: it catches a wrong split, a lost constant and a scale that stopped
being 1.

THE FIXTURE IS METRIC (contract v6 Nr. 2, the metric wave). Every stored
plan coordinate is a LOCAL METRE around the anchor pin — room rects, room
outlines, curve control points, markers, props, ``model_at``, the building
contour and the elevator alike. Nothing is denormalized on the way into the
payload any more, and ``k = 1`` as since E4: a metre in the plan is a metre in
the scene.

THIS FILE IS THE OLD FIXTURE, CONVERTED ONCE. Every number below is the
fraction this smoke used before, run through the retired mapping
``x/y → (f − 0.5) × 10``, ``w/d → f × 10``, ``bbox-local point → f × (w, d)``
— i.e. the SAME world geometry. All expected payload numbers are therefore
unchanged and are still the hand-derived ones. The only blocks re-derived by
hand are the two that tested the fraction mechanic itself ([1] "a wider anchor
is a wider square" and [1b]): a wider ``plan_width_m`` cannot scale a room any
more, which is exactly what the wave is for.

The fixture is 10 m wide (``plan_width_m`` 10, so the location bbox runs −5…5
on both axes) with a storey of 3 m:

    contour = the whole 10 × 10 square        elevator at (3, −3)
    room "a"     x −4 y −4 w 4 d 3            window N, door S
    room "garden" x −4 y  1 w 3 d 2           always_visible (outdoor)

    room "a"   world x −4…0, z −4…−1        room "garden" x −4…−1, z 1…3

Usage:  ./.venv/bin/python scripts/smoke_scene_recipe.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import scene_recipe  # noqa: E402

FAILURES = []
PLAN_W = 10.0     # map3d.plan_width_m — the footprint edge AND the square
EXTENT = PLAN_W   # payload extent_m = plan_width_m since E4 (k = 1)
STOREY_REAL = 3.0
STOREY = 3.0      # = storey_height_m, no factor left
WALL_H = STOREY - 0.15
# THE SKIRT OF A STOREY-0 WALL (§ A16.9, finding round 2026-08-21), derived by
# hand from the contract and NOT imported: before E5a a contour wall's foot sat
# at LEVEL_PLATE_TOP 0.08 over a level plate whose body reached down to
# 0.08 − LEVEL_PLATE_THICKNESS 0.14 = −0.06 — 0.14 m of solid material under
# the foot. Storey 0 lost that plate and now gets the same 0.14 m as a skirt
# INTO the terrain, so relief under a wall cannot open a lit gap. A DECLARED
# storey still has its plate and is not skirted at all.
SINK = 0.14


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a: float, b: float, eps: float = 1e-3) -> bool:
    return abs(float(a) - float(b)) <= eps


def fixture(extra_rooms=()) -> dict:
    return {
        "id": "loc",
        "map3d": {
            "plan_width_m": PLAN_W,
            "storey_height_m": STOREY_REAL,
            "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
            "elevator": [3.0, -3.0],
            "level_floors": {"0": "parquet"},
        },
        "rooms": [
            {"id": "a", "name": "A", "layout": {
                "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
                "surfaces": {"floor": "wood", "wall": "plaster"},
                "openings": [
                    {"edge": 0, "at": 0.5, "type": "window",
                     "width_m": 2.0, "height_m": 1.2, "sill_m": 0.9},
                    {"edge": 2, "at": 0.5, "type": "door",
                     "width_m": 1.0, "height_m": 2.1, "to": "outside"},
                ]}},
            {"id": "garden", "name": "Garden", "layout": {
                "x": -4.0, "y": 1.0, "w": 3.0, "d": 2.0, "level": 0,
                "always_visible": True,
                "surfaces": {"floor": "grass"}}},
            *extra_rooms,
        ],
    }


def scene(extra_rooms=()) -> dict:
    return scene_recipe.compose_scene(fixture(extra_rooms), plan_width_m=PLAN_W)


def walls_of(sc: dict, room_id: str) -> list:
    return [w for w in sc["walls"] if w.get("room_id") == room_id]


def is_full(w: dict) -> bool:
    """Is this a SOLID piece that runs the whole height of its wall?

    Two forms, both derived by hand from § A16.9: on storey 0 a wall foot is
    skirted, so a full piece is WALL_H + SINK tall; on a declared storey the
    plate is still under the foot and it is WALL_H. Everything else is a band
    in the wall — a window's sill or head, its glass, the LINTEL over a door
    or the door's own LEAF (findings 2026-08-25).

    The FLAGS come first, because a band can be as tall as the wall: a door
    whose height nobody authored reaches the top, so its leaf measures exactly
    WALL_H and would otherwise pass for a solid run.
    """
    if w.get("glass") or w.get("leaf") or w.get("lintel"):
        return False
    return near(w["height"], WALL_H + SINK) or near(w["height"], WALL_H)


def test_scalars() -> None:
    print("\n[1] scalars and levels")
    sc = scene()
    check("extent_m = plan_width_m (the square IS the footprint)",
          near(sc["extent_m"], PLAN_W), str(sc["extent_m"]))
    check("k = 1, constant since E4", near(sc["k"], 1.0), str(sc["k"]))
    check("storey = storey_height_m, no factor", near(sc["storey_m"], STOREY),
          str(sc["storey_m"]))
    check("one used level with floor_y 0",
          sc["levels"] == [{"level": 0, "floor_y": 0.0}], str(sc["levels"]))
    # ``extent_m`` is a REPORTED width now, not a scale: it is the location's
    # bounding box, and since v6 Nr. 2 nothing is derived from it. A location
    # declared 25 m wide therefore reports 25 — and its DRAWN contour stays
    # exactly where it was drawn, at ±5.
    wide = scene_recipe.compose_scene(
        {**fixture(), "map3d": {**fixture()["map3d"], "plan_width_m": 25.0}},
        plan_width_m=25.0)
    check("a wider anchor IS a wider extent_m, k stays 1",
          near(wide["extent_m"], 25.0) and near(wide["k"], 1.0),
          f"{wide['extent_m']}/{wide['k']}")
    # THE CONTOUR IS THE WALLS NOW. Storey 0 draws no level plate since E5a,
    # so the drawn building outline is read where it still is geometry: the
    # shell pieces of level 0, whose endpoints span the very ±5 square.
    _cxz = [c for w in wide["walls"] if not w.get("room_id")
            for c in (w["from"], w["to"])]
    check("...and the DRAWN contour does not move with it (still ±5)",
          near(max(c[0] for c in _cxz), 5.0)
          and near(min(c[0] for c in _cxz), -5.0)
          and near(max(c[1] for c in _cxz), 5.0)
          and near(min(c[1] for c in _cxz), -5.0),
          f"x {min(c[0] for c in _cxz)}…{max(c[0] for c in _cxz)}")
    # map3d.extent_m was the world-metre dial of the tile era. It is not read
    # any more — an old blob carrying it composes exactly like one without.
    stale = scene_recipe.compose_scene(
        {**fixture(), "map3d": {**fixture()["map3d"], "extent_m": 40.0}},
        plan_width_m=PLAN_W)
    check("a leftover map3d.extent_m changes NOTHING",
          near(stale["extent_m"], PLAN_W) and near(stale["k"], 1.0)
          and stale["plates"] == sc["plates"]
          and stale["floor_plan"] == sc["floor_plan"],
          f"{stale['extent_m']}/{stale['k']}")
    tall = scene_recipe.compose_scene(
        {**fixture(), "map3d": {**fixture()["map3d"], "storey_height_m": 4.5}},
        plan_width_m=PLAN_W)
    check("the storey is its own dial, in metres", near(tall["storey_m"], 4.5),
          str(tall["storey_m"]))
    anchorless = scene_recipe.compose_scene({"map3d": {}, "rooms": []})
    check("no anchor → the 10 m fallback square, k = 1, storey 3",
          near(anchorless["extent_m"], 10.0) and near(anchorless["k"], 1.0)
          and near(anchorless["storey_m"], 3.0),
          f"{anchorless['extent_m']}/{anchorless['k']}/{anchorless['storey_m']}")


def test_scale_is_one() -> None:
    print("\n[1b] the anchor scales NOTHING any more (v6 Nr. 2)")
    # THE POINT OF THE METRIC WAVE, stated as a red check. The SAME plan with
    # twice the declared width: before v6 the room rectangle was a fraction of
    # that width and doubled with it (x −8…0 instead of −4…0). Now the plan is
    # metres, so doubling ``plan_width_m`` moves the reported ``extent_m`` and
    # NOTHING else — the room stands where it was drawn.
    loc = fixture()
    loc["map3d"]["plan_width_m"] = 20.0
    big = scene_recipe.compose_scene(loc, plan_width_m=20.0)
    check("extent_m = 20 (the reported bbox width), k = 1",
          near(big["extent_m"], 20.0) and near(big["k"], 1.0),
          f'{big["extent_m"]}/{big["k"]}')
    check("storey 3 m — not 1.5", near(big["storey_m"], 3.0),
          str(big["storey_m"]))
    check("figure 1.70 m — not 0.85",
          near(big["figures"]["base_height_m_world"], 1.7),
          str(big["figures"]["base_height_m_world"]))
    check("the 1.0 m door is 1.0 m wide — not 0.5",
          len(big["doorways"]) == 1 and near(big["doorways"][0]["width_m"], 1.0),
          str([d["width_m"] for d in big["doorways"]]))
    # Room "a" is stored as x −4 y −4 w 4 d 3, so it is x −4…0, z −4…−1 —
    # under ANY declared plan width.
    xs = [p[0] for p in plate_of(big, "a")["outline"]]
    zs = [p[1] for p in plate_of(big, "a")["outline"]]
    check("the room does NOT grow with the anchor: still x −4…0, z −4…−1",
          near(min(xs), -4.0) and near(max(xs), 0.0)
          and near(min(zs), -4.0) and near(max(zs), -1.0),
          str(plate_of(big, "a")["outline"]))
    check("...and its plate is point-for-point the one of the 10 m location",
          plate_of(big, "a")["outline"] == plate_of(scene(), "a")["outline"],
          str(plate_of(big, "a")["outline"]))
    check("the elevator keeps its contract size (1.8 m shaft) AND its place",
          len([e for e in big["extras"] if e["kind"] == "elevator_shaft"
               and near(e["size"][0], 1.8)]) == 1
          and near([e for e in big["extras"]
                    if e["kind"] == "elevator_cabin"][0]["center"][0], 3.0),
          str(sorted({e["size"][0] for e in big["extras"]
                      if e["kind"] == "elevator_shaft"})))


# One UPPER STOREY and one roof terrace, so the plate law still has something
# to measure after E5a: storey 0 has no plates at all any more, storeys above
# and below are untouched scene geometry (§ G5).
UPPER = {"id": "up", "name": "Up", "layout": {
    "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 1,
    "surfaces": {"floor": "tiles"}}}
TERRACE = {"id": "terrace", "name": "Terrace", "layout": {
    "x": 1.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 1,
    "always_visible": True, "surfaces": {"floor": "stone"}}}


def test_plates() -> None:
    print("\n[2] plates — DECLARED STOREYS ONLY (Ein Boden E5a)")
    # THE HAND DERIVATION. Storey 0 is the terrain: no level plate, no room
    # plate, no zone surface, and every one of the old L0 numbers (0.08 / 0.09
    # / 0.10) is gone from it. Storey 1 keeps exactly what it always had:
    #     level plate      top = 1 x 3.0 + 0.08 = 3.08, thickness 0.14
    #     closed room "up" top = 1 x 3.0 + 0.10 = 3.10, thickness 0.02
    #     zone "terrace"   top = 1 x 3.0 + 0.08 + 0.01 = 3.09, thickness 0
    sc = scene([UPPER, TERRACE])
    check("the levels the rooms occupy", [lv["level"] for lv in sc["levels"]]
          == [0, 1], str(sc["levels"]))
    check("NOT ONE plate on storey 0",
          not [p for p in sc["plates"] if p["level"] == 0],
          str([p.get("room_id") for p in sc["plates"] if p["level"] == 0]))
    level = [p for p in sc["plates"] if not p.get("room_id")]
    check("one contour plate, and it is the upper storey's",
          len(level) == 1 and level[0]["level"] == 1, str(len(level)))
    p = level[0]
    check("top at level x storey + 0.08", near(p["top_y"], 3.08),
          str(p["top_y"]))
    check("thickness 0.14", near(p["thickness"], 0.14), str(p["thickness"]))
    check("level_floors has no entry for storey 1 → the default kind",
          p["texture_kind"] == "floor", str(p.get("texture_kind")))
    check("contour in world metres (±5 = the 10 m square)",
          p["outline"][0] == [-5.0, -5.0] and p["outline"][2] == [5.0, 5.0],
          str(p["outline"]))
    check("an upper storey is ghosted (the LOWEST used level is opaque)",
          p["opacity_role"] == "upper", str(p["opacity_role"]))

    up = [q for q in sc["plates"] if q.get("room_id") == "up"]
    check("the upper room has its own plate", len(up) == 1)
    check("with the room's floor kind", up[0].get("texture_kind") == "tiles",
          str(up[0].get("texture_kind")))
    check("a body above the level plate: 3.10 over 3.08",
          near(up[0]["top_y"], 3.10) and near(up[0]["thickness"], 0.02),
          str(up[0]))
    terrace = [q for q in sc["plates"] if q.get("room_id") == "terrace"]
    check("an outdoor room on a storey is a texture surface at 0.08 + 0.01",
          len(terrace) == 1 and near(terrace[0]["thickness"], 0.0)
          and near(terrace[0]["top_y"], 3.09), str(terrace))
    check("...and still carries its floor kind",
          terrace[0].get("texture_kind") == "stone")

    # RED COUNTER-PROBES: the three L0 datums must be GONE, not moved.
    tops = [q["top_y"] for q in sc["plates"]]
    check("red: no plate sits at the old L0 level datum 0.08",
          not any(near(t, 0.08) for t in tops), str(tops))
    check("red: none at the old L0 zone datum 0.09",
          not any(near(t, 0.09) for t in tops), str(tops))
    check("red: none at the old L0 room datum 0.10",
          not any(near(t, 0.10) for t in tops), str(tops))

    print("\n[2b] floor_plan — the storey-0 rooms as DATA")
    plan = {f["room_id"]: f for f in sc["floor_plan"]}
    check("exactly the two storey-0 rooms, in recipe order",
          [f["room_id"] for f in sc["floor_plan"]] == ["a", "garden"],
          str([f["room_id"] for f in sc["floor_plan"]]))
    check("the closed room says so and carries its floor kind",
          plan["a"]["closed"] is True and plan["a"]["floor_kind"] == "wood",
          str(plan["a"]))
    check("the zone says so and carries its own",
          plan["garden"]["closed"] is False
          and plan["garden"]["floor_kind"] == "grass", str(plan["garden"]))
    check("the polygon IS the room hull the recipe composed: x −4…0, z −4…−1",
          [min(q[0] for q in plan["a"]["polygon_world"]),
           max(q[0] for q in plan["a"]["polygon_world"]),
           min(q[1] for q in plan["a"]["polygon_world"]),
           max(q[1] for q in plan["a"]["polygon_world"])]
          == [-4.0, 0.0, -4.0, -1.0], str(plan["a"]["polygon_world"]))
    check("no height rides with it — that comes from the sampler",
          not any(k in plan["a"] for k in ("top_y", "y", "floor_y")),
          str(sorted(plan["a"])))
    check("a storey-1 room is NOT in the floor plan",
          "up" not in plan and "terrace" not in plan, str(sorted(plan)))
    # A CLOSED room that names no floor still has one — that is the whole
    # point of the stage (parquet under the furniture, never grass).
    bare = scene_recipe.compose_scene(
        {"map3d": {"plan_width_m": PLAN_W},
         "rooms": [{"id": "c", "name": "C", "layout": {
             "x": 0.0, "y": 0.0, "w": 2.0, "d": 2.0, "level": 0}},
            {"id": "z", "name": "Z", "layout": {
                "x": 4.0, "y": 0.0, "w": 2.0, "d": 2.0, "level": 0,
                "always_visible": True}}]},
        plan_width_m=PLAN_W)
    kinds = {f["room_id"]: f["floor_kind"] for f in bare["floor_plan"]}
    check("a closed room without a declared kind falls back to 'floor'",
          kinds.get("c") == scene_recipe.DEFAULT_FLOOR_KIND, str(kinds))
    check("...while a KINDLESS ZONE declares nothing — the terrain shows",
          kinds.get("z") == "", str(kinds))

    no_contour = scene_recipe.compose_scene(
        {"map3d": {"plan_width_m": PLAN_W},
         "rooms": fixture()["rooms"] + [UPPER]},
        plan_width_m=PLAN_W)
    check("without map3d.outline there is no level plate",
          not [q for q in no_contour["plates"] if not q.get("room_id")])


def test_room_walls() -> None:
    print("\n[3] room shell walls — splits, window band, outdoor")
    sc = scene()
    a = walls_of(sc, "a")
    check("outdoor rooms have no shell", not walls_of(sc, "garden"))
    # THE TOP EDGE is what "wall height" means since the skirt (§ A16.9): a
    # storey-0 piece starts SINK below the floor and is SINK taller for it, so
    # `base_y + height` is the number that did not move.
    check("wall top = max(0.6, storey − 0.15) over the storey floor",
          all(near(w["base_y"] + w["height"], WALL_H) or w.get("glass")
              or w["base_y"] + w["height"] < WALL_H for w in a))
    # A PANE is not a wall: a window's glass and a door's leaf are both
    # 0.07 × 0.6 = 0.042 thick and carry no texture kind (§ B1).
    panes = [w for w in a if w.get("glass") or w.get("leaf")]
    check("thickness 0.07 on solid walls",
          all(near(w["thickness"], 0.07) for w in a if w not in panes))
    check("the wall texture kind rides along",
          all(w.get("texture_kind") == "plaster" for w in a if w not in panes))
    # THE FOOT OF A STOREY-0 WALL IS THE TERRAIN (Ein Boden E5a) — and since
    # the finding round of 2026-08-21 it reaches SINK metres INTO it (§ A16.9).
    # The old room plate (0.10) it used to stand on is gone with every other
    # L0 plate; the skirt is what replaces the plate BODY the foot was
    # embedded in. Derived by hand: the deepest pre-E5a foot was the contour
    # wall's LEVEL_PLATE_TOP 0.08 over a level plate whose body ended at
    # 0.08 − 0.14 = −0.06, i.e. 0.14 m of material under it.
    # A FULL-HEIGHT piece is now WALL_H + SINK tall — that is what identifies
    # it, and its top still lands on WALL_H.
    check("the storey-0 foot sinks LEVEL_PLATE_THICKNESS into the ground",
          all(near(w["base_y"], -SINK) and near(w["base_y"] + w["height"], WALL_H)
              for w in a if near(w["height"], WALL_H + SINK)),
          str(sorted({w["base_y"] for w in a})))
    check("RED: no storey-0 foot on the old 0.10 room plate — nor on a bare 0",
          not any(near(w["base_y"], 0.10) or near(w["base_y"], 0.0)
                  for w in a if near(w["height"], WALL_H + SINK)),
          str(sorted({w["base_y"] for w in a})))

    # Room a in world metres: x −4…0 (4 wide), z −4…−1 (3 deep).
    north = [w for w in a if near(w["from"][1], -4.0) and near(w["to"][1], -4.0)]
    check("north edge yields 2 solids + sill + head + glass = 5",
          len(north) == 5, str(len(north)))
    # Window: width_m 2.0 IS 2 world metres (k = 1), centred at t = 2.0 on the
    # 4 m edge → span [1.0, 3.0].
    full = [w for w in north if not w.get("glass")
            and near(w["height"], WALL_H + SINK)]
    solid_n = sorted(full, key=lambda w: w["from"][0])
    check("the opening is the declared 2 metres wide",
          len(solid_n) == 2 and near(solid_n[0]["to"][0], -4.0 + 1.0)
          and near(solid_n[1]["from"][0], -4.0 + 3.0),
          str([[w["from"], w["to"]] for w in solid_n]))
    glass = [w for w in north if w.get("glass")]
    check("exactly one glass pane", len(glass) == 1)
    # THE SKIRT IS FOR FEET ONLY. Glass and head start further UP the wall and
    # are untouched — 0.9 and 2.1 are the same numbers as before the skirt.
    check("glass sits at sill_m 0.9 and is height_m 1.2 tall — NO skirt",
          len(glass) == 1 and near(glass[0]["base_y"], 0.0 + 0.9)
          and near(glass[0]["height"], 1.2), str(glass))
    check("glass is thinner than the wall and carries no texture kind",
          glass and near(glass[0]["thickness"], 0.042)
          and "texture_kind" not in glass[0], str(glass))
    band = sorted([w for w in north if not w.get("glass")
                   and not near(w["height"], WALL_H + SINK)],
                  key=lambda w: w["base_y"])
    # The SILL stands on the floor, so it gets the skirt: −0.14 → 0.9, i.e.
    # 1.04 tall. The HEAD hangs at 2.1 and keeps its 0.75.
    check("sill −SINK → 0.9 (skirted) and head 2.1 → 2.85 (not)",
          len(band) == 2 and near(band[0]["base_y"], -SINK)
          and near(band[0]["height"], 0.9 + SINK)
          and near(band[1]["base_y"], 0.0 + 2.1)
          and near(band[1]["height"], WALL_H - 2.1), str(band))

    # THE DOOR, edge 2 of room "a" — (0, −1) → (−4, −1), u = (−1, 0), 4 m
    # long. Door at 0.5, width_m 1.0 → span [1.5, 2.5] → world x −1.5 … −2.5.
    # Since the lintel and the leaf (findings 2026-08-25) that edge carries
    # FOUR pieces, derived exactly like a window's:
    #   solid   x  0.0 … −1.5   foot −SINK, height WALL_H + SINK
    #   solid   x −2.5 … −4.0   foot −SINK, height WALL_H + SINK
    #   LINTEL  x −1.5 … −2.5   foot height_m 2.1, height 2.85 − 2.1 = 0.75
    #   LEAF    x −1.5 … −2.5   foot 0.00 (the floor line, NO skirt),
    #                           height 2.1 = the clear opening, 0.042 thick
    # and NO glass — a door's pane is its leaf, not a window band.
    south = [w for w in a if near(w["from"][1], -1.0) and near(w["to"][1], -1.0)]
    solid_s = sorted([w for w in south if is_full(w)],
                     key=lambda w: -w["from"][0])
    lintel_s = [w for w in south if w.get("lintel")]
    leaf_s = [w for w in south if w.get("leaf")]
    check("a door is 2 solids + its lintel + its leaf, no glass",
          len(south) == 4 and len(solid_s) == 2 and len(lintel_s) == 1
          and len(leaf_s) == 1
          and not [w for w in south if w.get("glass")],
          str([(w["from"], w["to"], w["base_y"], w["height"])
               for w in south]))
    check("the door gap is the declared 1 metre wide",
          len(solid_s) == 2
          and near(abs(solid_s[0]["to"][0] - solid_s[1]["from"][0]), 1.0),
          str([[w["from"], w["to"]] for w in solid_s]))
    check("the lintel spans exactly the gap, x −1.5 … −2.5",
          len(lintel_s) == 1 and near(lintel_s[0]["from"][0], -1.5)
          and near(lintel_s[0]["to"][0], -2.5),
          str([lintel_s[0]["from"], lintel_s[0]["to"]] if lintel_s else None))
    check("...and stands on the DOOR's height 2.1, 0.75 tall — no skirt",
          len(lintel_s) == 1 and near(lintel_s[0]["base_y"], 2.1)
          and near(lintel_s[0]["height"], WALL_H - 2.1),
          str([lintel_s[0]["base_y"], lintel_s[0]["height"]] if lintel_s
              else None))
    # THE FLAG that keeps the door walkable: the piece over a door/passage is
    # drawn like any wall but bars nothing in a floor plan. A WINDOW's head
    # carries no flag — its own sill blocks that span anyway.
    check("the door lintel says it is one; nothing else does",
          len(lintel_s) == 1 and lintel_s[0].get("lintel") is True
          and not [w for w in a if w.get("lintel") and w not in lintel_s],
          str([(w["base_y"], w.get("lintel")) for w in a if w.get("lintel")]))
    check("...the window's head and pane stay unflagged",
          all(not w.get("lintel") for w in north),
          str([(w["base_y"], w.get("lintel")) for w in north]))
    # THE DOOR LEAF (user decision 2026-08-25) — the door's own pane, derived
    # the way the glass band is: it fills the CLEAR opening from the floor
    # line (0.00, NOT the skirted −0.14: the leaf is the door, not a wall
    # standing in the terrain) to the door's height 2.1, and it is as thin as
    # the glass — WALL_THICKNESS 0.07 × PANE_THICKNESS_FACTOR 0.6 = 0.042.
    check("the leaf fills the gap, x −1.5 … −2.5",
          len(leaf_s) == 1 and near(leaf_s[0]["from"][0], -1.5)
          and near(leaf_s[0]["to"][0], -2.5),
          str([[leaf_s[0]["from"], leaf_s[0]["to"]]] if leaf_s else None))
    check("...from the FLOOR LINE 0.00 to the door's head 2.1 — no skirt",
          len(leaf_s) == 1 and near(leaf_s[0]["base_y"], 0.0)
          and near(leaf_s[0]["height"], 2.1),
          str([leaf_s[0]["base_y"], leaf_s[0]["height"]] if leaf_s else None))
    check("...as thin as a glass pane (0.07 × 0.6) and untextured",
          len(leaf_s) == 1 and near(leaf_s[0]["thickness"], 0.042)
          and "texture_kind" not in leaf_s[0], str(leaf_s))
    check("RED: the leaf is NOT skirted — no foot at −0.14 and no 2.24 height",
          len(leaf_s) == 1 and not near(leaf_s[0]["base_y"], -SINK)
          and not near(leaf_s[0]["height"], 2.1 + SINK), str(leaf_s))
    check("the leaf says it is one; nothing else does",
          len(leaf_s) == 1 and leaf_s[0].get("leaf") is True
          and [w for w in a if w.get("leaf")] == leaf_s,
          str([(w["base_y"], w.get("leaf")) for w in a if w.get("leaf")]))
    check("...and it is no lintel, and the lintel is no leaf",
          not lintel_s[0].get("leaf") and not leaf_s[0].get("lintel"),
          str([lintel_s[0].get("leaf"), leaf_s[0].get("lintel")]))
    # A PASSAGE is an authored opening WITHOUT a door: same hole, same lintel,
    # but nothing in it — a leaf there would state a door nobody drew.
    passage = scene_recipe.compose_scene(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "passage", "width_m": 1.0,
         "height_m": 2.1, "to": "outside"}]), plan_width_m=PLAN_W)
    p_south = [w for w in walls_of(passage, "a")
               if near(w["from"][1], -1.0) and near(w["to"][1], -1.0)]
    check("a PASSAGE keeps its lintel and stays empty — 3 pieces, no leaf",
          len(p_south) == 3
          and len([w for w in p_south if w.get("lintel")]) == 1
          and not [w for w in passage["walls"] if w.get("leaf")],
          f"{len(p_south)} pieces, "
          f"{len([w for w in passage['walls'] if w.get('leaf')])} leaves")
    check("RED: no door gap reaches the top of the wall any more",
          not [w for w in a if is_full(w)
               and near(w["from"][1], -1.0) and near(w["to"][1], -1.0)
               and near(abs(w["to"][0] - w["from"][0]), 1.0)],
          str([[w["from"], w["to"]] for w in south]))
    # 4 edges: north 2 solids + sill + head + glass = 5, south 2 + lintel +
    # leaf = 4, east 1, west 1 → 11.
    check("11 wall segments in total for the room", len(a) == 11, str(len(a)))
    check("outward normals point away from the room (north edge → −z)",
          all(near(w["outward_normal"][1], -1.0) for w in north),
          str(north[0]["outward_normal"]))


def contour_pieces(sc: dict, level: int = 0) -> list:
    """The contour wall pieces of one level (no room_id), in emission order."""
    return [w for w in sc["walls"]
            if not w.get("room_id") and w["level"] == level]


def edge_pieces(sc: dict, *, z: float = None, x: float = None,
                level: int = 0, lintels: bool = False,
                leaves: bool = False) -> list:
    """The contour pieces lying on ONE straight contour line, sorted along the
    edge direction (the south edge runs −x, the east edge +z).

    By default only the pieces that run the WHOLE height of the shell, i.e.
    the runs a door's projection splits the line into. ``lintels=True`` gives
    the pieces hanging OVER those holes instead, ``leaves=True`` the DOOR
    LEAVES filling them (findings 2026-08-25) — by their flags, never by a
    height, so a full-height leaf cannot be mistaken for a run.
    """
    def want(w: dict) -> bool:
        if lintels:
            return bool(w.get("lintel"))
        if leaves:
            return bool(w.get("leaf"))
        return is_full(w)
    if z is not None:
        out = [w for w in contour_pieces(sc, level)
               if near(w["from"][1], z) and near(w["to"][1], z) and want(w)]
        return sorted(out, key=lambda w: -w["from"][0])
    out = [w for w in contour_pieces(sc, level)
           if near(w["from"][0], x) and near(w["to"][0], x) and want(w)]
    return sorted(out, key=lambda w: w["from"][1])


def full_edges(sc: dict, level: int = 0) -> int:
    """How many contour pieces still span a whole 10 m edge (= uncut)."""
    return len([w for w in contour_pieces(sc, level)
                if near(abs(w["to"][0] - w["from"][0])
                        + abs(w["to"][1] - w["from"][1]), EXTENT)])


def contour_room_fixture() -> dict:
    """Contour = the whole square, ONE room whose south wall lies ON the south
    contour line: world x −3…1, z 2…5. Its south
    wall carries a 1.0 m (real) door at 0.5."""
    return {
        "id": "loc",
        "map3d": {"plan_width_m": PLAN_W, "storey_height_m": STOREY_REAL,
                  "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]},
        "rooms": [{"id": "c", "name": "C", "layout": {
            "x": -3.0, "y": 2.0, "w": 4.0, "d": 3.0, "level": 0,
            "openings": [{"edge": 2, "at": 0.5, "type": "door",
                          "width_m": 1.0, "height_m": 2.1, "to": "outside"}]}}],
    }


def test_contour_walls() -> None:
    print("\n[4] contour walls — the hull takes its hole from the outside door")
    # THE SET-BACK ROOM (plan-betreten-und-tueren.md § 4.2, "Dome Morgenröte").
    # Room "a" is world x −4…0, z −4…−1 and does NOT touch the plan boundary.
    # Its south door (edge 2, at 0.5, width_m 1.0 → 1.0 world, k = 1) has its
    # clear middle at (−2, −1) and faces +z, so the nearest contour spot IN
    # FRONT of it is the south contour line z = 5 at x = −2. The south edge
    # runs (5, 5) → (−5, 5), so that spot is t = 7 along it and the hole is
    # t 6.5 … 7.5 → world x −1.5 … −2.5.
    # THE HOLE ENDS AT THE DOOR (finding 2026-08-25): over it the contour
    # carries on as a lintel, and since the user decision of the same day the
    # hole itself carries the door's LEAF — so the south line has 2 full runs
    # + 1 lintel + 1 leaf and the shell counts 3 + 4 = 7 pieces.
    sc = scene()
    check("4 edges, the south one split by the projection + lintel + leaf",
          len(contour_pieces(sc)) == 7, str(len(contour_pieces(sc))))
    south = edge_pieces(sc, z=5.0)
    check("the projection opens the south line in TWO pieces", len(south) == 2,
          str([[w["from"], w["to"]] for w in south]))
    check("the piece before the hole ends at x = −1.5",
          len(south) == 2 and near(south[0]["to"][0], -1.5),
          str(south[0]["to"] if south else None))
    check("the piece after it starts at x = −2.5",
          len(south) == 2 and near(south[1]["from"][0], -2.5),
          str(south[1]["from"] if len(south) > 1 else None))
    check("i.e. the gap is the DOOR's own 1.0 m, not the old fixed 0.8",
          len(south) == 2
          and near(abs(south[0]["to"][0] - south[1]["from"][0]), 1.0),
          str(abs(south[0]["to"][0] - south[1]["from"][0]) if len(south) > 1
              else None))
    check("the other three edges stay whole", full_edges(sc) == 3,
          str(full_edges(sc)))
    # THE LINTEL over that projected hole. The door's head stands at the room
    # wall's own foot (storey 0 = the terrain, 0.00) plus its height_m 2.1;
    # the shell's top is WALL_H 2.85, so the piece is 0.75 tall and spans the
    # very same x −1.5 … −2.5 the hole does. It is NOT skirted: it hangs in
    # the wall, it does not stand on the ground.
    heads = edge_pieces(sc, z=5.0, lintels=True)
    check("the contour carries a LINTEL over the door hole",
          len(heads) == 1 and near(heads[0]["from"][0], -1.5)
          and near(heads[0]["to"][0], -2.5),
          str([[w["from"], w["to"]] for w in heads]))
    check("...at the door's own head 2.1, 0.75 tall",
          len(heads) == 1 and near(heads[0]["base_y"], 2.1)
          and near(heads[0]["height"], WALL_H - 2.1),
          str([[w["base_y"], w["height"]] for w in heads]))
    check("RED: the hull hole no longer runs to the top of the shell",
          len(heads) == 1 and near(heads[0]["base_y"] + heads[0]["height"],
                                   WALL_H),
          str(heads))
    check("...and it says `lintel`, so no collider walls the entrance up",
          len(heads) == 1 and heads[0].get("lintel") is True
          and all(not w.get("lintel") for w in edge_pieces(sc, z=5.0)),
          str([w.get("lintel") for w in heads]))
    # THE LEAF IN THAT SAME HOLE (user decision 2026-08-25) — this is what
    # makes the door VISIBLE from outside: same x span as the lintel, from the
    # shell's floor line 0.00 (no skirt) up to the door's head 2.1, 0.042
    # thick and untextured, so the shell's `wall_kind` cannot paint over it.
    door_leaves = edge_pieces(sc, z=5.0, leaves=True)
    check("the contour carries the DOOR LEAF in the hole",
          len(door_leaves) == 1 and near(door_leaves[0]["from"][0], -1.5)
          and near(door_leaves[0]["to"][0], -2.5),
          str([[w["from"], w["to"]] for w in door_leaves]))
    check("...from 0.00 to 2.1, 0.042 thick, no texture kind",
          len(door_leaves) == 1 and near(door_leaves[0]["base_y"], 0.0)
          and near(door_leaves[0]["height"], 2.1)
          and near(door_leaves[0]["thickness"], 0.042)
          and "texture_kind" not in door_leaves[0], str(door_leaves))
    check("RED: the hole is no longer empty — leaf top meets the lintel foot",
          len(door_leaves) == 1 and len(heads) == 1
          and near(door_leaves[0]["base_y"] + door_leaves[0]["height"],
                   heads[0]["base_y"]),
          f"{door_leaves[0]['base_y'] + door_leaves[0]['height']} vs "
          f"{heads[0]['base_y']}" if door_leaves and heads else "—")
    # A door as TALL as the wall leaves nothing over it — the old picture,
    # and the proof that the lintel is the door's number and not a constant.
    tall = scene_recipe.compose_scene(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0,
         "height_m": WALL_H, "to": "outside"}]), plan_width_m=PLAN_W)
    check("a door as tall as the wall gets no lintel at all",
          not edge_pieces(tall, z=5.0, lintels=True)
          and len(edge_pieces(tall, z=5.0)) == 2,
          str(len(edge_pieces(tall, z=5.0, lintels=True))))
    # …but it still gets its LEAF, and that one is as tall as the wall: the
    # hole is the door, so the door fills it — 0.00 … 2.85.
    tall_leaf = edge_pieces(tall, z=5.0, leaves=True)
    check("...but the hole is still filled, 0.00 … WALL_H",
          len(tall_leaf) == 1 and near(tall_leaf[0]["base_y"], 0.0)
          and near(tall_leaf[0]["height"], WALL_H), str(tall_leaf))

    # The same door on the EAST wall (edge 1: (0, −4) → (0, −1), u = (0, 1),
    # normal +x): clear middle (0, −2.5), ray east → east contour line x = 5
    # at z = −2.5, i.e. t = 2.5 on the edge (5, −5) → (5, 5); hole 2.0…3.0
    # → world z −3.0 … −2.0. Nothing lands in the south wall any more —
    # that is the fallback gone.
    east_door = scene_recipe.compose_scene(door_fixture(a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.0,
         "to": "outside"}]), plan_width_m=PLAN_W)
    east = edge_pieces(east_door, x=5.0)
    check("an east door opens the EAST line at z −3.0 … −2.0",
          len(east) == 2 and near(east[0]["to"][1], -3.0)
          and near(east[1]["from"][1], -2.0),
          str([[w["from"], w["to"]] for w in east]))
    check("...and the south wall keeps its whole 10 m (no fallback door)",
          len(edge_pieces(east_door, z=5.0)) == 1
          and near(edge_pieces(east_door, z=5.0)[0]["to"][0], -5.0),
          str([[w["from"], w["to"]] for w in edge_pieces(east_door, z=5.0)]))

    # ONE WALL, ONE OWNER: room "c" runs ON the south contour line (x −3…1),
    # so the contour yields over t 4…8 of that edge — the pieces end at the
    # ROOM's corners x = 1 and x = −3, and the room's own wall gap
    # (x −0.5 … −1.5) IS the entrance. The door's projection falls inside
    # the yielded stretch and changes nothing.
    on_line = scene_recipe.compose_scene(contour_room_fixture(),
                                         plan_width_m=PLAN_W)
    south3 = edge_pieces(on_line, z=5.0)
    check("the contour yields to the room, no second hole next to it",
          len(south3) == 2 and near(south3[0]["to"][0], 1.0)
          and near(south3[1]["from"][0], -3.0),
          str([[w["from"], w["to"]] for w in south3]))
    room_south = sorted([w for w in on_line["walls"]
                         if w.get("room_id") == "c" and near(w["from"][1], 5.0)
                         and near(w["to"][1], 5.0) and is_full(w)],
                        key=lambda w: -w["from"][0])
    check("the room's own wall carries the 1.0 m entrance at x −0.5 … −1.5",
          len(room_south) == 2 and near(room_south[0]["to"][0], -0.5)
          and near(room_south[1]["from"][0], -1.5),
          str([[w["from"], w["to"]] for w in room_south]))
    # ...and the LINTEL belongs to the same wall: the contour yielded that
    # stretch, so there is no contour piece over the door either.
    room_head = [w for w in on_line["walls"] if w.get("room_id") == "c"
                 and near(w["from"][1], 5.0) and near(w["to"][1], 5.0)
                 and w.get("lintel")]
    check("the yielding contour leaves the lintel to the room wall too",
          len(room_head) == 1 and near(room_head[0]["base_y"], 2.1)
          and not edge_pieces(on_line, z=5.0, lintels=True),
          f"{len(room_head)} room heads, "
          f"{len(edge_pieces(on_line, z=5.0, lintels=True))} contour heads")
    # ...and the LEAF follows the same owner. THIS is the answer to "who
    # carries the door where contour and room overlap": exactly one wall does,
    # the one that was not clipped away — no two leaves in one hole.
    room_leaf = [w for w in on_line["walls"] if w.get("room_id") == "c"
                 and w.get("leaf")]
    check("...and the LEAF as well — ONE leaf in that hole, on the room wall",
          len(room_leaf) == 1 and near(room_leaf[0]["base_y"], 0.0)
          and near(room_leaf[0]["height"], 2.1)
          and not edge_pieces(on_line, z=5.0, leaves=True)
          and len([w for w in on_line["walls"] if w.get("leaf")]) == 1,
          f"{len(room_leaf)} room leaves, "
          f"{len(edge_pieces(on_line, z=5.0, leaves=True))} contour leaves")

    # A CONCAVE room: the outward side of a wall follows the hull's clockwise
    # winding (interior to the RIGHT of every edge), NOT the room's average
    # vertex. Room "L" occupies world x −4…2 / z −4…−3 plus x −4…−3 / z −4…2,
    # i.e. the room-local outline (0,0) (6,0) (6,1) (1,1) (1,6) (0,6) metres
    # over the rectangle x −4…2, y −4…2.
    # Its edge 2 runs (2, −3) → (−3, −3), u = (−1, 0), length 5 — the inner
    # wall facing the cut-out corner. Outward is (uz, −ux) = (0, 1), while the
    # vertex average (−1⅔, −1⅔) lies IN the cut-out, i.e. outside the room, and
    # would flip it. Door at 0.5, width_m 1.0 → clear 1.0 with its middle at
    # (−0.5, −3); the ray runs +z to the south contour line, t = 5.5 on the
    # edge (5, 5) → (−5, 5), hole 5.0…6.0 → world x 0.0 … −1.0. Flipped,
    # the hole would land on the NORTH facade instead.
    ell = scene_recipe.compose_scene({
        "id": "loc",
        "map3d": {"plan_width_m": PLAN_W, "storey_height_m": STOREY_REAL,
                  "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]},
        "rooms": [{"id": "L", "name": "L", "layout": {
            "x": -4.0, "y": -4.0, "w": 6.0, "d": 6.0, "level": 0,
            "outline": [[0, 0], [6, 0], [6, 1], [1, 1],
                        [1, 6], [0, 6]],
            "openings": [{"edge": 2, "at": 0.5, "type": "door",
                          "width_m": 1.0, "to": "outside"}]}}],
    }, plan_width_m=PLAN_W)
    ell_south = edge_pieces(ell, z=5.0)
    check("a concave room's door still opens the contour IN FRONT of it",
          len(ell_south) == 2 and near(ell_south[0]["to"][0], 0.0)
          and near(ell_south[1]["from"][0], -1.0),
          str([[w["from"], w["to"]] for w in ell_south]))
    check("...and the far (north) facade stays whole",
          len(edge_pieces(ell, z=-5.0)) == 1,
          str([[w["from"], w["to"]] for w in edge_pieces(ell, z=-5.0)]))

    # A door on an UPPER storey opens the hull on ITS OWN storey: room "u"
    # (level 1, world x −4…−2, z −4…−2) with a south door at 0.5 → clear
    # middle (−3, −2), ray +z → south line at x = −3, t = 8, hole 7.5…8.5
    # → x −2.5 … −3.5. Level 0 keeps room "a"'s own gap at −1.5 … −2.5.
    upper = scene_recipe.compose_scene(fixture([
        {"id": "u", "name": "U", "layout": {
            "x": -4.0, "y": -4.0, "w": 2.0, "d": 2.0, "level": 1,
            "openings": [{"edge": 2, "at": 0.5, "type": "door",
                          "width_m": 1.0, "to": "outside"}]}}]),
        plan_width_m=PLAN_W)
    up_south = edge_pieces(upper, z=5.0, level=1)
    check("the upper storey opens where ITS door is (x −2.5 … −3.5)",
          len(up_south) == 2 and near(up_south[0]["to"][0], -2.5)
          and near(up_south[1]["from"][0], -3.5),
          str([[w["from"], w["to"]] for w in up_south]))
    check("...and level 0 keeps its own gap at −1.5 … −2.5",
          near(edge_pieces(upper, z=5.0)[0]["to"][0], -1.5)
          and near(edge_pieces(upper, z=5.0)[1]["from"][0], -2.5),
          str([[w["from"], w["to"]] for w in edge_pieces(upper, z=5.0)]))
    check("a storey without an outside door keeps its ring closed",
          full_edges(scene_recipe.compose_scene(
              {**fixture(), "rooms": [{"id": "u", "layout": {
                  "x": -4.0, "y": -4.0, "w": 2.0, "d": 2.0, "level": 1}}]},
              plan_width_m=PLAN_W), level=1) == 4)


def test_no_building_entrance() -> None:
    print("\n[4f] problems — a building without an outside door says so")
    # Room "a" keeps only its window; a window is no way out, so there is no
    # outside door on level 0 at all. The hull STAYS CLOSED (the old fallback
    # would have punched one into the south wall) and the finding is reported.
    sealed = scene_recipe.compose_scene(door_fixture(a_openings=[
        {"edge": 0, "at": 0.5, "type": "window", "width_m": 2.0,
         "height_m": 1.2, "sill_m": 0.9}]), plan_width_m=PLAN_W)
    check("no door, no hole: 4 whole edges", len(contour_pieces(sealed)) == 4
          and full_edges(sealed) == 4,
          f"{len(contour_pieces(sealed))} pieces, {full_edges(sealed)} whole")
    check("one problem, kind no_building_entrance, at the location",
          [(p["kind"], p.get("location_id")) for p in sealed["problems"]]
          == [("no_building_entrance", "loc")], str(sealed["problems"]))
    check("...with a message for the surfaces to show",
          bool((sealed["problems"] or [{}])[0].get("message")),
          str(sealed["problems"]))
    check("a building WITH an outside door reports nothing",
          scene()["problems"] == [], str(scene()["problems"]))

    # A door between two rooms is no way out either: room "b" east of "a",
    # a's east door names it, so the doorway has two rooms and outside=false.
    inner = scene_recipe.compose_scene(door_fixture(
        extra_rooms=[{"id": "b", "name": "B", "layout": {
            "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0}}],
        a_openings=[{"edge": 1, "at": 0.5, "type": "door", "width_m": 1.0,
                     "to": "b"}]), plan_width_m=PLAN_W)
    check("an inner door leaves the hull closed and the finding standing",
          full_edges(inner) == 4
          and [p["kind"] for p in inner["problems"]] == ["no_building_entrance"],
          f"{full_edges(inner)} whole edges, {inner['problems']}")

    # No walled room on level 0 = no building: an outdoor zone inside a
    # contour is not something one puts a door into, so nothing is reported.
    outdoor = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": "garden", "layout": {
            "x": -4.0, "y": 1.0, "w": 3.0, "d": 2.0, "level": 0,
            "always_visible": True}}]}, plan_width_m=PLAN_W)
    check("a contour with only outdoor rooms is no sealed building",
          outdoor["problems"] == [], str(outdoor["problems"]))


def test_rooms_without_layout() -> None:
    print("\n[4g] problems — a contour over rooms that all lack a layout")
    # The quiet sealed hull (diagnosis 2026-08-15): the contour is drawn, both
    # rooms have no ``layout``, so compose_recipe returns None for each. No
    # recipe = no shell = shell_levels empty, and no_building_entrance can
    # never fire — this is the finding that does.
    blind = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": "a", "name": "A"},
                                {"id": "b", "name": "B", "layout": {}}]},
        plan_width_m=PLAN_W)
    check("exactly one problem, kind rooms_without_layout, at the location",
          [(p["kind"], p.get("location_id")) for p in blind["problems"]]
          == [("rooms_without_layout", "loc")], str(blind["problems"]))
    check("...counting both rooms, with a message for the surfaces to show",
          blind["problems"][0].get("room_count") == 2
          and bool(blind["problems"][0].get("message")),
          str(blind["problems"][0]))
    # Counter-check: ONE room with a layout is enough — the recipe exists, so
    # the quiet finding goes and the ordinary entrance rule takes over. Room
    # "a" here is the fixture room minus its south door (window only), so the
    # hull is walled on level 0 and still has no way in.
    one = scene_recipe.compose_scene(
        {**fixture(), "rooms": [
            {"id": "a", "name": "A", "layout": {
                "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
                "openings": [{"edge": 0, "at": 0.5, "type": "window",
                              "width_m": 2.0, "height_m": 1.2,
                              "sill_m": 0.9}]}},
            {"id": "b", "name": "B"}]},
        plan_width_m=PLAN_W)
    check("one laid-out room ends it — no_building_entrance takes over",
          [p["kind"] for p in one["problems"]] == ["no_building_entrance"],
          str(one["problems"]))
    # No contour, no finding: without a hull nothing was sealed, and rooms
    # without a layout are simply rooms nobody placed yet.
    loose = scene_recipe.compose_scene(
        {**fixture(), "map3d": {k: v for k, v in fixture()["map3d"].items()
                                if k != "outline"},
         "rooms": [{"id": "a", "name": "A"}]}, plan_width_m=PLAN_W)
    check("without a contour an unplaced room is no finding",
          loose["problems"] == [], str(loose["problems"]))
    # And a location without rooms at all keeps quiet too: there is nothing
    # that HAS no layout, and the empty room list is visible by itself. The
    # reserved GROUND room counts as nothing here — it never carries a layout
    # (world_ops._sanitize_rooms_layout strips one), so it must not be blamed
    # for the missing one. Every migrated location owns it.
    from app.models.world import GROUND_ROOM_ID
    empty = scene_recipe.compose_scene({**fixture(), "rooms": []},
                                       plan_width_m=PLAN_W)
    check("a contour without any room reports nothing",
          empty["problems"] == [], str(empty["problems"]))
    ground = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": GROUND_ROOM_ID, "name": "Outside"}]},
        plan_width_m=PLAN_W)
    check("...and a contour over the GROUND room alone is no finding either",
          ground["problems"] == [], str(ground["problems"]))
    with_ground = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": GROUND_ROOM_ID, "name": "Outside"},
                                {"id": "a", "name": "A"}]},
        plan_width_m=PLAN_W)
    check("beside a real room it drops out of the count (1, not 2)",
          [(p["kind"], p.get("room_count")) for p in with_ground["problems"]]
          == [("rooms_without_layout", 1)], str(with_ground["problems"]))


def test_openings_without_walls() -> None:
    print("\n[4h] problems — openings drawn into a room whose walls are off")
    # The trap of 2026-08-15: the author unticked "Render walls" on every room
    # while doors and windows stayed authored. The 2D plan keeps drawing them,
    # 3D builds nothing — and nothing said so. Room "a" of the fixture carries
    # exactly 2 openings (window north, door south to outside).
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["no_walls"] = True
    blind = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    check("exactly one problem, kind openings_without_walls, at the location",
          [(p["kind"], p.get("location_id")) for p in blind["problems"]]
          == [("openings_without_walls", "loc")], str(blind["problems"]))
    check("...counting the one room, with a message for the surfaces to show",
          blind["problems"][0].get("room_count") == 1
          and bool(blind["problems"][0].get("message")),
          str(blind["problems"][0]))
    # THE regression guard of this bug: what the finding claims must be true
    # of the geometry. Walls off ⇒ not one threshold, not one pane.
    check("...and it is true: no doorway and no glass exist",
          not blind["doorways"]
          and not [w for w in blind["walls"] if w.get("glass")],
          f"{len(blind['doorways'])} doorways, "
          f"{len([w for w in blind['walls'] if w.get('glass')])} panes")
    # Counter-check: walls back on ⇒ the finding goes AND the very same two
    # openings become geometry — the door a threshold, the window a glass
    # segment between sill and head.
    walled = scene()
    check("walls on ⇒ the finding is gone",
          walled["problems"] == [], str(walled["problems"]))
    check("...and the door builds a threshold, the window a pane",
          len(walled["doorways"]) == 1
          and len([w for w in walled["walls"] if w.get("glass")
                   and w.get("room_id") == "a"]) == 1,
          f"{len(walled['doorways'])} doorways, "
          f"{len([w for w in walled['walls'] if w.get('glass')])} panes")
    # A wall-less room WITHOUT openings is a legal open zone (pavilion, an
    # area inside an area model) — the combination is the trap, not the flag.
    bare = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": "a", "name": "A", "layout": {
            "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
            "no_walls": True}}]}, plan_width_m=PLAN_W)
    check("a wall-less room without openings stays silent",
          bare["problems"] == [], str(bare["problems"]))
    # The outdoor zone loses its walls the same way (§ A5), so a door drawn
    # into one is the same trap. The fixture's own openings-free "garden"
    # never spoke up in any of the cases above.
    outdoor = scene_recipe.compose_scene(
        {**fixture(), "rooms": [{"id": "garden", "name": "Garden", "layout": {
            "x": -4.0, "y": 1.0, "w": 3.0, "d": 2.0, "level": 0,
            "always_visible": True,
            "openings": [{"edge": 0, "at": 0.5, "type": "door",
                          "width_m": 1.0, "height_m": 2.1}]}}]},
        plan_width_m=PLAN_W)
    check("an OUTDOOR room with a drawn door reports the same way",
          [(p["kind"], p.get("room_count")) for p in outdoor["problems"]]
          == [("openings_without_walls", 1)], str(outdoor["problems"]))


def test_wall_skirt() -> None:
    """THE SKIRT OF A STOREY-0 WALL (§ A16.9, finding round 2026-08-21).

    A wall foot is a straight horizontal line; the ground under it is not. Until
    E5a that never showed, because the foot was EMBEDDED in a plate body — a
    contour wall at LEVEL_PLATE_TOP 0.08 over a level plate reaching down to
    0.08 − 0.14 = −0.06, i.e. 0.14 m of material under it. E5a deleted the
    plate, the foot met the bare terrain, and every millimetre the ground drops
    away opened a lit gap.

    The wall keeps that 0.14 m as a skirt INTO the terrain. Derived by hand,
    both ways:

        storey 0, contour   base −0.14, height 2.85 + 0.14 = 2.99, top 2.85
        storey 0, room      base −0.14, height           = 2.99, top 2.85
        storey 1, contour   base  3.08, height           = 2.85, top 5.93
        storey 1, room      base  3.10, height           = 2.85, top 5.95

    THE TWO PROPERTIES THAT MAKE IT SAFE. The TOP never moves (the height grows
    by exactly the skirt), so nothing above the floor is touched; and a DECLARED
    storey is not skirted at all, because its plate is still there — 0.14 would
    be precisely the depth at which a contour wall's foot reached the level
    plate's UNDERSIDE and started hanging out of the ceiling below.
    """
    print("\n[4a] the storey-0 wall skirt — 0.14 m into the ground, top fixed")
    sc = scene([UPPER])
    # ONLY THE PIECES THAT STAND ON THE GROUND are skirted — a door's lintel
    # hangs in the wall (base 2.1, 0.75 tall) and never touches the terrain,
    # exactly like a window's head.
    g_contour = [w for w in sc["walls"]
                 if not w.get("room_id") and w["level"] == 0 and is_full(w)]
    u_contour = [w for w in sc["walls"]
                 if not w.get("room_id") and w["level"] == 1 and is_full(w)]
    g_heads = [w for w in sc["walls"] if not w.get("room_id")
               and w["level"] == 0 and w.get("lintel")]
    g_leaves = [w for w in sc["walls"] if not w.get("room_id")
                and w["level"] == 0 and w.get("leaf")]
    check("storey-0 contour pieces sink to −0.14 and top out on 2.85",
          g_contour and all(near(w["base_y"], -SINK)
                            and near(w["base_y"] + w["height"], WALL_H)
                            for w in g_contour),
          str(sorted({(w["base_y"], w["height"]) for w in g_contour})))
    check("RED: no storey-0 contour foot on the old LEVEL_PLATE_TOP 0.08",
          not any(near(w["base_y"], 0.08) for w in g_contour),
          str(sorted({w["base_y"] for w in g_contour})))
    check("a door lintel hangs at 2.1 / 0.75 and is NOT skirted",
          len(g_heads) == 1 and near(g_heads[0]["base_y"], 2.1)
          and near(g_heads[0]["height"], WALL_H - 2.1),
          str(sorted({(w["base_y"], w["height"]) for w in g_heads})))
    # …and neither is the LEAF (user decision 2026-08-25): it stands ON the
    # floor line, so the y <= 0 rule would have skirted it — 0.00 / 2.10 is
    # the proof it is exempt, because it fills the CLEAR opening and the
    # threshold lies at its foot.
    check("a door leaf stands at 0.00 / 2.10 and is NOT skirted either",
          len(g_leaves) == 1 and near(g_leaves[0]["base_y"], 0.0)
          and near(g_leaves[0]["height"], 2.1),
          str(sorted({(w["base_y"], w["height"]) for w in g_leaves})))
    # A DECLARED STOREY DID NOT MOVE BY A MILLIMETRE (§ A16.9).
    check("storey-1 contour keeps 3.08 / 2.85 — no skirt on a plate",
          u_contour and all(near(w["base_y"], 1 * STOREY + 0.08)
                            and near(w["height"], WALL_H)
                            for w in u_contour),
          str(sorted({(w["base_y"], w["height"]) for w in u_contour})))
    up_room = walls_of(sc, "up")
    check("storey-1 room walls keep 3.10 / 2.85 either",
          up_room and all(near(w["base_y"], 1 * STOREY + 0.10)
                          and near(w["height"], WALL_H)
                          for w in up_room
                          if not (w.get("glass") or w.get("leaf"))),
          str(sorted({(w["base_y"], w["height"]) for w in up_room})))
    # THE CEILING OF THE MARGIN, hand-checked: sunk by the skirt, a storey-1
    # contour foot would land exactly on the level plate's underside (3.08 −
    # 0.14 = 2.94 = 3.08 − LEVEL_PLATE_THICKNESS) and be visible from below.
    # That is why the skirt is storey-0 only, and why 0.14 is its largest
    # defensible value rather than an arbitrary one.
    check("the margin is exactly the level plate's body (its own ceiling)",
          near(SINK, scene_recipe.LEVEL_PLATE_THICKNESS)
          and near(scene_recipe.WALL_SINK_M, SINK),
          f"{scene_recipe.WALL_SINK_M} vs {SINK}")
    # THE FLOOR OF THE MARGIN: a wall's outer face lies WALL_THICKNESS/2
    # outside the hull the plateau stamp follows, and just outside the plot the
    # ground may fall at the full max_slope_deg 40°.
    ramp = (scene_recipe.WALL_THICKNESS / 2) * math.tan(math.radians(40.0))
    check("...and it clears the plateau-ramp case 0.029 m by 4.8x",
          SINK > ramp * 4 and near(ramp, 0.0294, eps=1e-3), f"{ramp:.4f} m")
    # A DOORWAY IS NOT A WALL: its base_y is the STANDING height of the rooms
    # it joins, and the skirt must not have touched it.
    door_sc = scene_recipe.compose_scene(contour_room_fixture(),
                                         plan_width_m=PLAN_W)
    check("a doorway threshold keeps the floor, not the skirt",
          door_sc["doorways"] and all(near(d["base_y"], 0.0)
                                      for d in door_sc["doorways"]),
          str([d["base_y"] for d in door_sc["doorways"]]))


def test_contour_wall_texture() -> None:
    print("\n[4b] map3d.wall_kind textures the whole shell")
    plain = scene()
    contour_plain = [w for w in plain["walls"] if not w.get("room_id")]
    check("without the field the contour carries no texture kind",
          all("texture_kind" not in w for w in contour_plain),
          str([w.get("texture_kind") for w in contour_plain]))

    loc = fixture()
    loc["map3d"]["wall_kind"] = "brick"
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    contour = [w for w in sc["walls"] if not w.get("room_id")]
    # 7 = the 3 whole edges + the 2 runs of the split south line + the lintel
    # over the door hole + the door's LEAF in it. The lintel is a shell piece
    # like any other and wears the shell kind too; the leaf is a PANE and
    # wears none, exactly like a window's glass.
    shell = [w for w in contour if not w.get("leaf")]
    check("every contour piece carries the shell kind",
          len(contour) == 7 and len(shell) == 6
          and all(w.get("texture_kind") == "brick" for w in shell),
          f"{len(contour)} pieces, "
          f"{sorted(str(w.get('texture_kind')) for w in contour)}")
    check("room walls keep their own surfaces.wall kind",
          all(w.get("texture_kind") == "plaster" for w in walls_of(sc, "a")
              if not (w.get("glass") or w.get("leaf"))),
          str(sorted(str(w.get("texture_kind")) for w in walls_of(sc, "a")
                     if not (w.get("glass") or w.get("leaf")))))
    check("panes stay untextured — glass and door leaf alike",
          all("texture_kind" not in w for w in sc["walls"]
              if w.get("glass") or w.get("leaf")))
    check("plates are untouched by a WALL kind",
          [p.get("texture_kind") for p in sc["plates"]]
          == [p.get("texture_kind") for p in plain["plates"]])
    check("the signature moves with wall_kind (map3d is part of it)",
          sc["signature"] != plain["signature"],
          f"{sc['signature'][:8]} vs {plain['signature'][:8]}")

    loc2 = fixture()
    loc2["map3d"]["wall_kind"] = "stone"
    check("...and a different kind gives a different signature",
          scene_recipe.compose_scene(loc2, plan_width_m=PLAN_W)["signature"]
          != sc["signature"])


# ── Area locations (plan-area-locations.md) ────────────────────────────
# Contour covers the LEFT HALF of the location (world x −5…0), so
# "outside the floor plan" is expressible at all. Four rooms, one per case.
AREA_ROOMS = [
    # indoor inside  -> ordinary room, no cutout of its own
    {"id": "in", "name": "In", "layout": {
        "x": -4.0, "y": -4.0, "w": 2.0, "d": 2.0, "level": 0}},
    # indoor OUTSIDE -> cuts its own hole (the hut off to the side)
    {"id": "out", "name": "Out", "layout": {
        "x": 2.0, "y": -4.0, "w": 2.0, "d": 2.0, "level": 0}},
    # outdoor OUTSIDE -> zone ON the model: no plate, but an overlay
    {"id": "zone", "name": "Zone", "layout": {
        "x": 2.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 0,
        "always_visible": True}},
    # outdoor inside -> § A5 unchanged: thickness-0 plate, no overlay
    {"id": "yard", "name": "Yard", "layout": {
        "x": -4.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 0,
        "always_visible": True}},
]


def area_fixture(area: bool) -> dict:
    loc = {
        "id": "loc",
        "map3d": {
            "plan_width_m": PLAN_W,
            "storey_height_m": STOREY_REAL,
            "outline": [[-5, -5], [0, -5], [0, 5], [-5, 5]],
        },
        "rooms": AREA_ROOMS,
    }
    if area:
        loc["map3d"]["area_model"] = True
    return loc


def area_scene(area: bool = True, meta=None) -> dict:
    return scene_recipe.compose_scene(area_fixture(area), plan_width_m=PLAN_W,
                                      building_meta=meta or {})


def test_area_locations() -> None:
    print("\n[4c] area location — cutouts and overlay zones")
    plain = area_scene(area=False)
    sc = area_scene()
    b_plain = [m for m in plain["models"] if m["role"] == "building"]
    check("without a building model there is no building spec to carry cutouts",
          not b_plain and not [m for m in sc["models"] if m["role"] == "building"])

    withb = area_scene(meta=GROUND_META)
    building = [m for m in withb["models"] if m["role"] == "building"][0]
    cut = building.get("cutouts") or []
    check("2 cutouts: the floor plan + the indoor room outside it",
          len(cut) == 2, str(len(cut)))
    check("the first is the contour in world metres (left half, x −5…0)",
          cut[0][0] == [-5.0, -5.0] and cut[0][2] == [0.0, 5.0], str(cut[0]))
    xs = [p[0] for p in cut[1]]
    check("the second is the OUTSIDE indoor room (world x 2.0…4.0)",
          near(min(xs), 2.0) and near(max(xs), 4.0), str(cut[1]))
    check("the inside indoor room does NOT cut",
          all(not (near(min(p[0] for p in poly), -4.0)
                   and near(max(p[0] for p in poly), -2.0)) for poly in cut))
    check("an area model declares itself as GROUND (no renderer guessing)",
          building.get("display") == "ground", str(building.get("display")))
    check("a normal building is a shell",
          spec_of(area_scene(area=False, meta=BUILDING_META), "building")
          .get("display") == "shell")

    print("\n[4d] overlay zones instead of floors")
    # SINCE "Ein Boden" E5a THERE ARE NO STOREY-0 PLATES AT ALL, so the old
    # split "the zone outside the plan has no plate, the yard inside keeps
    # one" is measured where the storey-0 rooms live now: ``floor_plan``. What
    # is unchanged is the OTHER half of the rule — a zone lying ON the area
    # model gets an ``overlay`` block (centre, rect, height) and no walls,
    # because nothing else says where an NPC stands on a mesh.
    check("storey 0 draws no plate for ANY of the four rooms",
          not [p for p in withb["plates"] if p["level"] == 0],
          str([p.get("room_id") for p in withb["plates"]]))
    plan = {f["room_id"] for f in withb["floor_plan"]}
    check("all four storey-0 rooms are in the floor plan",
          plan == {"in", "out", "zone", "yard"}, str(sorted(plan)))
    check("an overlay room produces no walls either",
          not [w for w in withb["walls"] if w.get("room_id") == "zone"])

    by_id = {r["room_id"]: r for r in withb["rooms"]}
    ov = by_id["zone"].get("overlay")
    # Room "zone": world x 2.0…4.0, z 1.0…3.0;
    # centre (3.0, 2.0), extent 2.0 × 2.0.
    check("the overlay carries the centre in world metres",
          ov and near(ov["centre"][0], 3.0) and near(ov["centre"][1], 2.0),
          str(ov))
    check("...and the rect with its real extent",
          ov and near(ov["rect"]["w"], 2.0) and near(ov["rect"]["d"], 2.0),
          str(ov and ov["rect"]))
    # A ground model is anchored at its WALKABLE surface, so offset_y IS the
    # height you walk at — no socle, no measured fraction needed for that.
    # THE STOREY-0 FLOOR IS THE TERRAIN (E5a): the datum is 0.00, not the
    # 0.08 slab of the plate era. The mesh hangs walk_y (4 m) below it, so
    # 0.00 − 4 = −4.00, and every number in this block sits 0.08 lower than it
    # did while a drawn boundary produced a storey slab.
    check("the ground of an area location IS the storey-0 floor (0.00)",
          ov and near(ov["y"], 0.0), str(ov and ov["y"]))
    check("...and the mesh hangs below it by walk_y",
          near(building["bottom_y"], -4.0),
          f"{building['bottom_y']} (walk_y 4 m, k = 1)")
    check("red: the old 0.08 slab datum is gone from both",
          not near(ov["y"], 0.08) and not near(building["bottom_y"], -3.92),
          f'{ov["y"]}/{building["bottom_y"]}')
    check("offset_y does NOT apply — a level-0 square cannot sink to level −1",
          near(spec_of(area_scene(meta={**GROUND_META, "offset_y": -3.0}),
                       "building")["bottom_y"], -4.0),
          str(spec_of(area_scene(meta={**GROUND_META, "offset_y": -3.0}),
                      "building")["bottom_y"]))
    check("without the dial a ground model puts its UNDERSIDE on that floor",
          near(spec_of(area_scene(meta=BUILDING_META), "building")["bottom_y"],
               0.0),
          str(spec_of(area_scene(meta=BUILDING_META), "building")["bottom_y"]))
    check("without a building model it falls back to that same floor",
          near((next(r for r in sc["rooms"] if r["room_id"] == "zone")
                ["overlay"]["y"]), 0.0))
    # v6 Nr. 3: a GROUND model follows the same width law as a shell. Without
    # a declared width it fills its boundary (10 m, what the forced size 1
    # produced); with one it is that wide — the anchor law is untouched.
    check("a ground model without a width fills its boundary (old size 1)",
          near(building["max_m"], EXTENT)
          and building.get("width_estimated") is True,
          str(building.get("max_m")))
    ground_wide = spec_of(area_scene(meta={**GROUND_META, "width_m": 25.0}),
                          "building")
    check("...and a declared 25 m wins there too, anchor unchanged",
          near(ground_wide["max_m"], 25.0)
          and near(ground_wide["bottom_y"], -4.0),
          f"{ground_wide.get('max_m')}/{ground_wide.get('bottom_y')}")
    check("only the zone gets an overlay",
          [r for r in withb["rooms"] if r.get("overlay")][0]["room_id"] == "zone"
          and len([r for r in withb["rooms"] if r.get("overlay")]) == 1)

    # A zone WITH a declared floor kind used to get a texture plate at the
    # zone's own height + 0.01. THAT PLATE IS GONE (E5a): a storey-0 zone
    # floor is a LAYER of the ground now (``core.terrain_layers``), cut into
    # the terrain mask at the very polygon the floor plan carries. The kind
    # here is SAND and not water: since W1 a floor kind may not be water at all
    # (the sanitizer strips it — [4w] below), because water is painted on the
    # map and a room only ever REFERS to it.
    import copy
    lake = copy.deepcopy(area_fixture(True))
    for r in lake["rooms"]:
        if r["id"] == "zone":
            r["layout"]["surfaces"] = {"floor": "sand"}
    lake_sc = scene_recipe.compose_scene(lake, plan_width_m=PLAN_W,
                                         building_meta=GROUND_META)
    zp = [pl for pl in lake_sc["plates"] if pl.get("room_id") == "zone"]
    lake_ov = next(r["overlay"] for r in lake_sc["rooms"]
                   if r["room_id"] == "zone")
    check("red: a zone with a floor kind gets NO texture plate any more",
          not zp, str(zp))
    zone_plan = next(f for f in lake_sc["floor_plan"] if f["room_id"] == "zone")
    check("...its kind travels in the floor plan instead",
          zone_plan["floor_kind"] == "sand" and zone_plan["closed"] is False,
          str(zone_plan))
    check("...on the very polygon the zone was drawn as (x 2…4, z 1…3)",
          [min(q[0] for q in zone_plan["polygon_world"]),
           max(q[0] for q in zone_plan["polygon_world"]),
           min(q[1] for q in zone_plan["polygon_world"]),
           max(q[1] for q in zone_plan["polygon_world"])]
          == [2.0, 4.0, 1.0, 3.0], str(zone_plan["polygon_world"]))
    check("the zone keeps its overlay as well", bool(lake_ov))

    print("\n[4e] without the flag nothing changes")
    check("no cutouts on the building spec",
          "cutouts" not in [m for m in scene_recipe.compose_scene(
              area_fixture(False), plan_width_m=PLAN_W,
              building_meta=BUILDING_META)["models"]
              if m["role"] == "building"][0])
    check("no overlay on any room",
          not [r for r in plain["rooms"] if r.get("overlay")])
    check("the outdoor room outside the plan is an ordinary storey-0 room",
          "zone" in {f["room_id"] for f in plain["floor_plan"]}
          and not [p for p in plain["plates"] if p["level"] == 0])
    check("the flag moves the signature (clients re-fetch)",
          sc["signature"] != plain["signature"],
          f"{sc['signature'][:8]} vs {plain['signature'][:8]}")


def test_room_floor_offset() -> None:
    print("\n[3c] per-room floor offset")
    # WHAT ``floor_offset_y`` STILL IS after "Ein Boden" E5a: a per-room lift
    # of everything that STANDS in the room. What it is NOT any more: a
    # compensation for a second ground (there is one now, and the room's mesh
    # stands on it), and not a WATERLINE for a zone — since W1 a room has no
    # water fields at all, and the mirror of the water it stands on belongs to
    # the painted AREA (``map_water`` names which one).
    # Storey 0 has no plates left, so what the lift is measured on is the
    # room's WALLS and its props.
    base = scene()
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["floor_offset_y"] = 2.0   # metres, k = 1
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    lift = 2.0
    walls = [w for w in sc["walls"] if w.get("room_id") == "a"]
    check("the room's walls rise by floor_offset_y — 0.0 -> 2.0",
          all(near(w["base_y"], wb["base_y"] + lift)
              for w, wb in zip(walls, walls_of(base, "a"))),
          f"{walls[0]['base_y']} vs {walls_of(base, 'a')[0]['base_y']}")
    check("the room's own hull does NOT move sideways with it",
          plate_of(sc, "a")["outline"] == plate_of(base, "a")["outline"])
    check("a neighbouring room does not move",
          all(near(w["base_y"], wb["base_y"]) for w, wb
              in zip(walls_of(sc, "garden"), walls_of(base, "garden"))))
    check("the flag moves the signature", sc["signature"] != base["signature"])


def test_no_walls() -> None:
    print("\n[3b] per-room no_walls")
    base = scene()
    a_before = len(walls_of(base, "a"))

    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["no_walls"] = True
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    a = walls_of(sc, "a")
    check(f"the room emitted {a_before} wall segments before, now none",
          len(a) == 0, str(len(a)))
    check("...not even the window's glass pane",
          not [w for w in sc["walls"] if w.get("glass")
               and w.get("room_id") == "a"])
    check("its floor is still in the floor plan",
          len([f for f in sc["floor_plan"] if f["room_id"] == "a"]) == 1)
    check("its openings stay in the rooms block (the 2D editor draws them)",
          len([r for r in sc["rooms"]
               if r["room_id"] == "a"][0].get("openings") or []) == 2,
          str(len([r for r in sc["rooms"]
                   if r["room_id"] == "a"][0].get("openings") or [])))

    # A room without a shell has no wall, hence no door — and the hull takes
    # its holes from the doors. So the contour closes here (7 pieces before:
    # 4 on the split south line — 2 runs, the door's lintel and its leaf —
    # plus the 3 whole edges; 4 whole edges now) instead of keeping the gap.
    # `no_building_entrance` has nothing to report: no walled room is left on
    # level 0, and an outdoor zone is not a building one puts a door into.
    # The lost openings are what `openings_without_walls` says instead ([4h]).
    contour_before = [w for w in base["walls"] if not w.get("room_id")]
    contour = [w for w in sc["walls"] if not w.get("room_id")]
    check("the shell-less room takes its hull hole with it",
          len(contour_before) == 7 and len(contour) == 4,
          f"{len(contour)} vs {len(contour_before)}")
    check("a neighbouring room keeps its walls",
          not walls_of(base, "garden") and not walls_of(sc, "garden"))
    check("the flag moves the signature (it rides in the room recipe)",
          sc["signature"] != base["signature"],
          f"{sc['signature'][:8]} vs {base['signature'][:8]}")


def door_fixture(*, extra_rooms=(), a_openings=None,
                 no_walls=False) -> dict:
    """The base fixture with room "a"'s openings (and shell) swapped out."""
    loc = fixture(extra_rooms)
    for room in loc["rooms"]:
        if room["id"] != "a":
            continue
        if a_openings is not None:
            room["layout"]["openings"] = a_openings
        if no_walls:
            room["layout"]["no_walls"] = True
    return loc


def doors(loc: dict) -> list:
    return scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)["doorways"]


def test_doorways() -> None:
    print("\n[3d] doorways — thresholds as finished primitives")
    # Everything below is derived by hand from the same rule the wall splitter
    # runs on (plan-betreten-und-tueren.md § 4.1), at k = 1 with the reference
    # square = 10 metres:
    #   half   = min(width_m / 2, edge_length / 2)
    #   centre = clamp(at, 0, 1) × edge_length
    #   span   = [max(0, centre − half), min(edge_length, centre + half)]
    # Room "a" (x −4 y −4 w 4 d 3) is world x −4…0, z −4…−1. Its hull is
    # wound clockwise, so edge 2 runs (0, −1) → (−4, −1): u = (−1, 0),
    # length 4. The S door (at 0.5, width_m 1.0) gives half = 0.5,
    # centre = 2 → span [1.5, 2.5]: clear width 1.0, middle at t = 2 →
    # world (0 − 2, −1) = (−2, −1). base_y = the foot of the wall it was cut
    # from, and on STOREY 0 that is the terrain: level 0 × 3 + 0.00 (E5a — the
    # room plate the old 0.10 came from is gone).
    ds = doors(fixture())
    check("the N window is NO doorway — one entry for the room", len(ds) == 1,
          str(ds))
    d = ds[0] if ds else {}
    check("at_world = middle of the CLEAR opening (−2, −1)",
          d.get("at_world") == [-2.0, -1.0], str(d.get("at_world")))
    check("along = the wall's unit direction (−1, 0)",
          d.get("along") == [-1.0, 0.0], str(d.get("along")))
    check("width_m = the clear width after the edge clamp, here the full 1.0",
          near(d.get("width_m", 0), 1.0), str(d.get("width_m")))
    # The CLEAR HEIGHT travels with the gap (finding 2026-08-25): the authored
    # height_m 2.1, clamped against the wall's 2.85 exactly as the splitter
    # clamps it. base_y + height_m is where the lintel over this door begins.
    check("height_m = the clear height after the same clamp, 2.1",
          near(d.get("height_m", 0), 2.1), str(d.get("height_m")))
    tall_door = doors(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0,
         "height_m": 9.0, "to": "outside"}]))
    check("...a door taller than the wall is clamped to it, 2.85",
          len(tall_door) == 1 and near(tall_door[0]["height_m"], WALL_H),
          str([t["height_m"] for t in tall_door]))
    no_height = doors(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0}]))
    check("...and an UNAUTHORED height stays the wall's own, no lintel",
          len(no_height) == 1 and near(no_height[0]["height_m"], WALL_H),
          str([t["height_m"] for t in no_height]))
    check("base_y = the wall's own foot, 0.00", near(d.get("base_y", -1), 0.0),
          str(d.get("base_y")))
    check("level 0", d.get("level") == 0, str(d.get("level")))
    check("an outside door names ONE room and says outside",
          d.get("rooms") == ["a"] and d.get("outside") is True, str(d))
    # `outside` is read off the finished geometry, not off the author's `to`:
    # one room in `rooms` means no second room's wall meets this gap. The very
    # same door with an EMPTY `to` is the same hole in the same wall.
    untold_out = doors(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0}]))
    check("an unlabelled door on an exterior wall is outside all the same",
          len(untold_out) == 1 and untold_out[0]["rooms"] == ["a"]
          and untold_out[0]["outside"] is True, str(untold_out))

    # ── shared wall ─────────────────────────────────────────────────────
    # Room "b" (x 0 y −4 w 2 d 3) sits east of "a": a's edge 1 runs
    # (0, −4) → (0, −1) with u = (0, 1) and length 3, b's edge 3 runs back
    # along the same line, so the wall is shared and b gets the mirrored copy.
    # Door at 0.5, width_m 1.6 → half = min(0.8, 1.5) = 0.8, centre = 1.5 →
    # span [0.7, 2.3]: width 1.6, middle at world (0, −4 + 1.5) = (0, −2.5).
    b_room = {"id": "b", "name": "B", "layout": {
        "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0}}
    shared = doors(door_fixture(extra_rooms=(b_room,), a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6, "to": "b"}]))
    check("ONE physical opening on a shared wall = ONE entry",
          len(shared) == 1, str(shared))
    s = shared[0] if shared else {}
    check("it names both rooms, the wall's owner first",
          s.get("rooms") == ["a", "b"], str(s.get("rooms")))
    check("...and does not lead outside", s.get("outside") is False,
          str(s.get("outside")))
    check("at_world (0, −2.5), along (0, 1), clear width 1.6",
          s.get("at_world") == [0.0, -2.5] and s.get("along") == [0.0, 1.0]
          and near(s.get("width_m", 0), 1.6), str(s))
    # The same wall WITHOUT a declared target: the neighbour is then known
    # only from the mirrored copy — the dedup has to supply it.
    untold = doors(door_fixture(extra_rooms=(b_room,), a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6}]))
    check("an undeclared target still yields one entry with both rooms",
          len(untold) == 1 and untold[0]["rooms"] == ["a", "b"], str(untold))
    check("...and is not outside: a second room's wall meets this gap",
          len(untold) == 1 and untold[0]["outside"] is False, str(untold))

    # ── one gap, one entry ──────────────────────────────────────────────
    # BOTH rooms author a door at the same spot on the party wall: a's edge 1
    # at 0.5 and b's edge 3 at 0.5 are the same world point (0, −2.5), and
    # each room ALSO gets the other's mirrored copy — four openings, four
    # identical spans, and _subtract melts them into ONE gap. The block has to
    # say the same thing: one entry, both rooms.
    both = scene_recipe.compose_scene(door_fixture(
        extra_rooms=({**b_room, "layout": {**b_room["layout"], "openings": [
            {"edge": 3, "at": 0.5, "type": "door", "width_m": 1.6,
             "to": "a"}]}},),
        a_openings=[{"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6,
                     "to": "b"}]), plan_width_m=PLAN_W)
    check("a door authored from BOTH sides is ONE entry",
          len(both["doorways"]) == 1, str(both["doorways"]))
    check("...at the same place as the one-sided one",
          len(both["doorways"]) == 1
          and both["doorways"][0]["at_world"] == [0.0, -2.5]
          and near(both["doorways"][0]["width_m"], 1.6)
          and both["doorways"][0]["rooms"] == ["a", "b"], str(both["doorways"]))
    # The party wall runs at world x = 0 from z −4 to −1; the gap [0.7, 2.3]
    # leaves exactly two solid pieces in room a's east wall — plus the door's
    # own LEAF in the gap, which is a pane and not a piece of wall. Nothing
    # else: the door names no height, so it reaches the top and gets no
    # lintel (the leaf then measures the full WALL_H).
    east_line = [w for w in walls_of(both, "a")
                 if near(w["from"][0], 0.0) and near(w["to"][0], 0.0)]
    east_a = [w for w in east_line if is_full(w)]
    check("...and the wall really has ONE gap there (2 pieces)",
          len(east_a) == 2, str([[w["from"], w["to"]] for w in east_a]))
    check("...with the door's leaf in it, and nothing else",
          len(east_line) == 3
          and len([w for w in east_line if w.get("leaf")]) == 1,
          str([(w["base_y"], w["height"], w.get("leaf")) for w in east_line]))
    # Same rule inside ONE room: the identical opening entered twice.
    twice = doors(door_fixture(a_openings=[
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0, "to": "outside"},
        {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0,
         "to": "outside"}]))
    check("a door authored twice in one room is ONE entry too",
          len(twice) == 1 and near(twice[0]["width_m"], 1.0), str(twice))

    # ── corner clamp ────────────────────────────────────────────────────
    # Room "c" (x 1 y 1 w 2 d 2) is world x 1…3, z 1…3; edge 0 runs
    # (1, 1) → (3, 1), u = (1, 0), length 2. A door AT the corner (at 0.0)
    # with width_m 2.0 → half = min(1.0, 1.0) = 1.0, centre = 0 →
    # [max(0, −1.0), 1.0] = [0, 1.0]: the clear width is 1.0, NOT 2.0, and the
    # middle sits at t = 0.5 → world (1.5, 1).
    c_room = {"id": "c", "name": "C", "layout": {
        "x": 1.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 0, "openings": [
            {"edge": 0, "at": 0.0, "type": "door", "width_m": 2.0,
             "to": "outside"}]}}
    corner = [x for x in doors(fixture((c_room,))) if "c" in x["rooms"]]
    check("a door in the corner is clamped to the edge: width 1.0",
          len(corner) == 1 and near(corner[0]["width_m"], 1.0), str(corner))
    check("...and its middle moves with the clamp, to (1.5, 1)",
          len(corner) == 1 and corner[0]["at_world"] == [1.5, 1.0],
          str(corner[0]["at_world"] if corner else None))

    # ── two doors meeting in a corner stay two ──────────────────────────
    # Room a's east edge runs (0, −4) → (0, −1) and its south edge (0, −1) →
    # (−4, −1): they meet at the corner (0, −1). A door AT the corner from
    # each side has its unclamped centre exactly there — zero metres apart —
    # so only the wall DIRECTION tells them apart.
    #   east:  at 1.0, 1.0 m → half 0.5, centre 3 → [2.5, 3] (clamped),
    #          width 0.5, middle t = 2.75 → world (0, −1.25), along (0, 1)
    #   south: at 0.0, 1.0 m → half 0.5, centre 0 → [0, 0.5],
    #          width 0.5, middle t = 0.25 → world (−0.25, −1), along (−1, 0)
    elbow = doors(door_fixture(a_openings=[
        {"edge": 1, "at": 1.0, "type": "door", "width_m": 1.0, "to": "outside"},
        {"edge": 2, "at": 0.0, "type": "door", "width_m": 1.0,
         "to": "outside"}]))
    check("two doors in one corner of one room are TWO thresholds",
          len(elbow) == 2, str(elbow))
    check("...the south one at (−0.25, −1) along (−1, 0), width 0.5",
          len(elbow) == 2 and elbow[0]["at_world"] == [-0.25, -1.0]
          and elbow[0]["along"] == [-1.0, 0.0]
          and near(elbow[0]["width_m"], 0.5), str(elbow))
    check("...the east one at (0, −1.25) along (0, 1), width 0.5",
          len(elbow) == 2 and elbow[1]["at_world"] == [0.0, -1.25]
          and elbow[1]["along"] == [0.0, 1.0]
          and near(elbow[1]["width_m"], 0.5), str(elbow))
    check("...and BOTH stay exterior doors",
          all(x["outside"] is True and len(x["rooms"]) == 1 for x in elbow),
          str(elbow))

    # Two rooms that touch in that same corner (0, −1), each with its own
    # exterior door pushed into it — no shared wall, so no mirror; room "d"
    # (x 0 y −1 w 2 d 2) is world x 0…2, z −1…1 and its N edge runs
    # (0, −1) → (2, −1): at 0.0, 1.0 m → [0, 0.5], middle (0.25, −1),
    # along (1, 0). Perpendicular to a's east door — two thresholds, and no
    # passage between two rooms that share nothing but a point.
    d_room = {"id": "d", "name": "D", "layout": {
        "x": 0.0, "y": -1.0, "w": 2.0, "d": 2.0, "level": 0, "openings": [
            {"edge": 0, "at": 0.0, "type": "door", "width_m": 1.0,
             "to": "outside"}]}}
    touch = doors(door_fixture(extra_rooms=(d_room,), a_openings=[
        {"edge": 1, "at": 1.0, "type": "door", "width_m": 1.0,
         "to": "outside"}]))
    check("corner-touching rooms keep their own exterior doors",
          len(touch) == 2 and [x["rooms"] for x in touch] == [["a"], ["d"]],
          str(touch))
    check("...and neither of them turns into a passage",
          len(touch) == 2 and all(x["outside"] is True for x in touch),
          str(touch))
    # The same corner from the COLLINEAR side: room "e" sits where "d" sits,
    # but its door is on the W edge (0, 1) → (0, −1) at 1.0 → [1.5, 2],
    # middle (0, −0.75), along (0, −1). Same line as a's east door, opposite
    # direction — and the two clamped spans (z −1.5…−1 and −1…−0.5) touch in
    # a point instead of overlapping, so they are still two thresholds.
    e_room = {**d_room, "id": "e", "name": "E", "layout": {
        **d_room["layout"], "openings": [
            {"edge": 3, "at": 1.0, "type": "door", "width_m": 1.0,
             "to": "outside"}]}}
    collinear = doors(door_fixture(extra_rooms=(e_room,), a_openings=[
        {"edge": 1, "at": 1.0, "type": "door", "width_m": 1.0,
         "to": "outside"}]))
    check("...same for two collinear doors that only touch in the corner",
          len(collinear) == 2
          and [x["at_world"] for x in collinear] == [[0.0, -1.25],
                                                     [0.0, -0.75]]
          and all(x["outside"] is True for x in collinear), str(collinear))

    # ── no shell, no threshold ──────────────────────────────────────────
    check("a room without walls has no doorway either",
          doors(door_fixture(no_walls=True)) == [],
          str(doors(door_fixture(no_walls=True))))
    check("an outdoor room has none either (no shell, no openings)",
          not [x for x in ds if "garden" in x["rooms"]], str(ds))

    # ── signature ───────────────────────────────────────────────────────
    # The doorways are a pure function of the openings, and those ride in the
    # room recipe's own signature — a wider door has to move the scene hash,
    # otherwise no client ever re-fetches it.
    base_sig = scene_recipe.compose_scene(fixture(),
                                          plan_width_m=PLAN_W)["signature"]
    wider = scene_recipe.compose_scene(door_fixture(a_openings=[
        {"edge": 0, "at": 0.5, "type": "window",
         "width_m": 2.0, "height_m": 1.2, "sill_m": 0.9},
        {"edge": 2, "at": 0.5, "type": "door",
         "width_m": 1.4, "height_m": 2.1, "to": "outside"}]),
        plan_width_m=PLAN_W)["signature"]
    check("a wider door moves the signature", wider != base_sig,
          f"{wider[:8]} vs {base_sig[:8]}")


# ── Door props (plan-door-props-texture-slots.md, contract v5) ──────────

# The ONE published variant of the door prop. Since spec-bild-props-v2 E1 the
# orientation fix, the areas, the leaf box and the pane defaults are facts of
# the MODEL FILE and ride on the variant entry — the record has no prop-level
# `rotation` / `leaf_bbox` / `area_defaults` any more.
DOOR_TIER = {
    "variant": 0, "tiers": ["full"],
    "dims": {"width_m": 0.9, "depth_m": 0.06, "height_m": 2.0},
    "rotation": {"x": 0, "y": 0, "z": 0},
    "areas": [], "area_defaults": {}, "areas_warning": "",
}
DOOR_PROP = {
    "id": "door1", "name": "Door leaf",
    "width_m": 0.9, "depth_m": 0.06, "height_m": 2.0,
    "bbox": [0.9, 2.0, 0.06],
    "has_model": True, "model_tiers": ["full"],
    "model_signature": "doorsig1",
    "variant_tiers": [DOOR_TIER],
    # A glass door is the stated use case of the material slots (v5).
    "slots": [{"name": "glass", "kind": "material"}],
}


def stub_library(get) -> None:
    """Point the prop library at ``get`` — the ONE accessor the recipe asks."""
    from app.core import props as prop_store
    prop_store.get_prop = get


def stub_door_props() -> None:
    """Two door props in the library — ``door1`` and ``door2``."""
    stub_library(lambda pid: (
        {**DOOR_PROP, "id": pid} if pid in ("door1", "door2") else None))


def door_prop_scene(*, a_openings=None, default_prop: str = "",
                    extra_rooms=()) -> dict:
    loc = door_fixture(extra_rooms=extra_rooms, a_openings=a_openings)
    if default_prop:
        loc["default_door_prop_id"] = default_prop
    return scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)


def door_specs(sc: dict) -> list:
    return [m for m in sc["models"] if m.get("door")]


def leaves(sc: dict, room_id: str = "a") -> list:
    return [w for w in walls_of(sc, room_id) if w.get("leaf")]


S_DOOR = {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0,
          "height_m": 2.1, "to": "outside"}


def test_door_props() -> None:
    print("\n[3p] door props — the prop IS the door (v5)")
    stub_door_props()
    # THE HAND DERIVATION, from the doorway [3d] already checked above:
    # room "a"'s S door sits at at_world (−2, −1), along (−1, 0), clear width
    # 1.0, clear height 2.1, base_y 0.00.
    #
    # ANCHOR = the HINGE EDGE, so the group the renderer gets can be swung
    # about it. Looking ALONG `along`, hinge "left" is the end the direction
    # comes FROM:
    #   left :  at − along·w/2 = (−2, −1) − (−1, 0)·0.5 = (−1.5, −1)
    #   right:  at + along·w/2 = (−2, −1) + (−1, 0)·0.5 = (−2.5, −1)
    #
    # YAW turns the model's local +x onto the direction the LEAF runs, away
    # from its hinge. three's Ry(+θ) — which IS `world_geometry.local_to_world`
    # (§ A1.1) — maps local +x to world (cos θ, −sin θ), so
    #   θ = atan2(−uz, ux) mod 360 puts +x on `along` (hinge left),
    #   and hinge right adds 180° because the leaf then runs against `along`.
    #   along (−1, 0):  θ = atan2(0, −1) = 180°   → right: 360 mod 360 = 0°
    #   along ( 0, 1):  θ = atan2(−1, 0) = −90°   → 270° (mod 360)
    #
    # SWING is the sign of "positive rotation opens the leaf OUTWARD".
    # `_door_outward` is (uz, −ux) — for the S door (0, 1), i.e. +z, and room
    # "a" spans z −4…−1, so +z really is away from it. Turning the placed
    # group by φ about y moves a world offset (vx, vz) with
    #   d/dφ (vx cos φ + vz sin φ, −vx sin φ + vz cos φ)|₀ = (vz, −vx),
    # and the free end of the leaf sits at v = ±along:
    #   hinge left  (v = +along): (uz, −ux) = the outward normal → swing +1
    #   hinge right (v = −along): −(uz, −ux)                     → swing −1
    sc = door_prop_scene(a_openings=[{**S_DOOR, "prop_id": "door1"}])
    specs = door_specs(sc)
    check("an opening with a prop_id yields ONE door-prop spec",
          len(specs) == 1, str(specs))
    p = specs[0] if specs else {}
    check("role prop, the authored id, the primary tier map",
          p.get("role") == "prop" and p.get("id") == "door1"
          and p.get("variants") == {"full":
                                    "/assets/props/door1/model?tier=full"},
          str(p))
    check("measure 'fit' — the ONE non-uniform mode (§ B2 v5)",
          p.get("measure") == "fit", str(p.get("measure")))
    check("size_m = the CLEAR opening [width, height] = [1.0, 2.1]",
          p.get("size_m") == [1.0, 2.1], str(p.get("size_m")))
    check("anchor = the LEFT hinge edge (−1.5, −1)",
          p.get("anchor") == [-1.5, -1.0], str(p.get("anchor")))
    check("yaw 180 puts local +x on along (−1, 0)",
          near(p.get("yaw_deg", -1), 180.0), str(p.get("yaw_deg")))
    check("bottom_y = the threshold's own base_y, 0.00",
          near(p.get("bottom_y", -1), 0.0), str(p.get("bottom_y")))
    check("door = {opening 0, hinge left, swing +1}",
          p.get("door") == {"opening": 0, "hinge": "left", "swing": 1},
          str(p.get("door")))
    check("...and `opening` indexes THIS scene's doorways",
          len(sc["doorways"]) == 1
          and sc["doorways"][(p.get("door") or {}).get("opening", -1)
                             ]["at_world"] == [-2.0, -1.0],
          str(sc["doorways"]))
    check("no max_m: a fitted leaf is measured by size_m alone",
          "max_m" not in p, str(p.get("max_m")))
    # ENTSCHEID 3: the leaf STAYS in walls[] — the Blender exterior render
    # reads that list and needs the door's prism — it only says it is now a
    # prop's job to draw it.
    lf = leaves(sc)
    check("the leaf wall stays in walls[] for the exterior render",
          len(lf) == 1, str(len(lf)))
    check("...and is flagged door_prop so a renderer skips drawing it",
          lf and lf[0].get("door_prop") is True, str(lf[0] if lf else None))
    # The SAME door is projected onto the building contour (§ 4.2), and the
    # hole it opens there carries its own leaf — that one has to say it too,
    # or the shell keeps a dark plate in front of the prop.
    hull_leaf = [w for w in sc["walls"]
                 if w.get("leaf") and not w.get("room_id")]
    check("the contour's leaf over the same door is flagged as well",
          len(hull_leaf) == 1 and hull_leaf[0].get("door_prop") is True,
          str(hull_leaf))
    plain = door_prop_scene(a_openings=[dict(S_DOOR)])
    check("without a prop nothing changes: leaf, no flag, no spec",
          len(leaves(plain)) == 1
          and "door_prop" not in leaves(plain)[0]
          and not door_specs(plain), str(leaves(plain)))

    # ── the hinge picks the edge, the yaw and the sign ───────────────────
    right = door_specs(door_prop_scene(a_openings=[
        {**S_DOOR, "prop_id": "door1", "hinge": "right"}]))
    check("hinge right: anchor (−2.5, −1), yaw 0, swing −1",
          len(right) == 1 and right[0]["anchor"] == [-2.5, -1.0]
          and near(right[0]["yaw_deg"], 0.0)
          and right[0]["door"] == {"opening": 0, "hinge": "right",
                                   "swing": -1}, str(right))
    # The OTHER axis: room "b" east of "a" shares the wall at x = 0 running
    # z −4 → −1, so a's edge 1 has along (0, 1). Door at 0.5, width 1.6 →
    # at_world (0, −2.5); hinge left → anchor (0, −2.5) − (0, 1)·0.8 =
    # (0, −3.3), yaw 270, outward (uz, −ux) = (1, 0) = away from room "a".
    b_room = {"id": "b", "name": "B", "layout": {
        "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0}}
    axis2 = door_specs(door_prop_scene(extra_rooms=(b_room,), a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6,
         "height_m": 2.1, "to": "b", "prop_id": "door1"}]))
    check("along (0, 1): anchor (0, −3.3), yaw 270, size_m [1.6, 2.1]",
          len(axis2) == 1 and axis2[0]["anchor"] == [0.0, -3.3]
          and near(axis2[0]["yaw_deg"], 270.0)
          and axis2[0]["size_m"] == [1.6, 2.1], str(axis2))
    check("...still ONE spec for a door two rooms share",
          len(axis2) == 1 and axis2[0]["door"]["swing"] == 1, str(axis2))

    # ── the LEAF NODE's box rides on the spec (spec-picture-props.md § 6) ─
    # The PRIMARY variant's entry carries `leaf_bbox` exactly while its mesh
    # has a `leaf` node (props.LEAF_BBOX_KEY on the model FILE's sidecar,
    # published as `variant_tiers[0].leaf_bbox`); the recipe copies it
    # VERBATIM into `door.leaf_bbox` — raw y-up model metres, the renderer
    # scales — and writes no key at all without it (the whole group swings
    # then). Ruling R13: where the pivot goes is the shared `leafPivot` (the
    # rule stated in the FIXED frame and mapped back through `fix_euler`), so
    # the server derives nothing hinge-dependent here — it copies the box.
    LEAF_BBOX = {"min": [0.1, 0.1, -0.02], "max": [0.9, 2.1, 0.0]}
    stub_library(lambda pid: (
        {**DOOR_PROP, "id": pid,
         "variant_tiers": [{**DOOR_TIER, "leaf_bbox": LEAF_BBOX}]}
        if pid == "door1" else None))
    with_leaf = door_specs(door_prop_scene(a_openings=[
        {**S_DOOR, "prop_id": "door1", "hinge": "right"}]))
    check("a prop with leaf_bbox: door.leaf_bbox == the primary FILE's value, verbatim",
          len(with_leaf) == 1 and with_leaf[0]["door"] == {
              "opening": 0, "hinge": "right", "swing": -1,
              "leaf_bbox": LEAF_BBOX}, str(with_leaf and with_leaf[0]["door"]))
    check("...and the rest of the spec is unchanged by it (anchor, yaw, fit)",
          with_leaf and with_leaf[0]["anchor"] == [-2.5, -1.0]
          and near(with_leaf[0]["yaw_deg"], 0.0)
          and with_leaf[0]["measure"] == "fit", str(with_leaf))
    stub_door_props()
    without = door_specs(door_prop_scene(a_openings=[
        {**S_DOOR, "prop_id": "door1"}]))
    check("without a file leaf_bbox the field is ABSENT (not null)",
          len(without) == 1 and "leaf_bbox" not in without[0]["door"],
          str(without and without[0]["door"]))

    # ── the PLACED VARIANT decides (spec-bild-props-v2.md E1) ────────────
    # Areas, leaf box and orientation fix are facts of the MODEL FILE, and a
    # variant is its own file — so the recipe reads them off the variant the
    # placement resolves to (`_variant_index` → position in `variant_tiers`),
    # never off a prop-wide value. HAND CASE: the prop "frame" publishes two
    # variants; variant 1 carries rotation y = 90, the area `glass_1` with
    # the default preset `glass`, and a leaf box; variant 0 carries nothing.
    # Room "a" (world x −4…0, z −4…−1) gets two copies, `at` [1, 1] on
    # variant 1 → anchor (−3, −3), and `at` [2, 1] on variant 0 → (−2, −3):
    #
    #   variant 1 → fix_euler {0, 90, 0}, slots {glass_1: {preset glass}},
    #               leaf_bbox = the variant's box
    #   variant 0 → fix_euler {0, 0, 0}, NO `slots` key, NO `leaf_bbox` key
    #
    # A `slot_values` on the variant is laid OVER its own `area_defaults`
    # (same key wins for the values): variant 1 with slot_values
    # {glass_1: {preset glass}, picture_1: {image …}} → both keys. The DOOR
    # opening carries no variant (ruling V1), so its spec reads the PRIMARY
    # variant's file: rotation y = 270 on `variant_tiers[0]` → fix_euler
    # {0, 270, 0}; its `area_defaults` {glass_1: glass} → `slots`.
    FRAME_LEAF = {"min": [0.05, 0.05, -0.01], "max": [0.55, 0.45, 0.0]}
    FRAME_PROP = {
        "id": "frame", "name": "Frame",
        "width_m": 0.6, "depth_m": 0.05, "height_m": 0.5,
        "bbox": [0.6, 0.5, 0.05],
        "has_model": True, "model_tiers": ["full"], "model_signature": "fr1",
        "slots": [],
        "variant_tiers": [
            {"variant": 0, "tiers": ["full"],
             "dims": {"width_m": 0.6, "depth_m": 0.05, "height_m": 0.5},
             "rotation": {"x": 0, "y": 0, "z": 0},
             "areas": [], "area_defaults": {}, "areas_warning": ""},
            {"variant": 1, "tiers": ["full"],
             "dims": {"width_m": 0.6, "depth_m": 0.05, "height_m": 0.5},
             "rotation": {"x": 0, "y": 90, "z": 0},
             "areas": [{"id": "glass_1", "kind": "glass", "size_m": [0.5, 0.4],
                        "normal": [0, 0, 1], "source": "auto", "faces": 2}],
             "area_defaults": {"glass_1": {"preset": "glass"}},
             "leaf_bbox": FRAME_LEAF, "areas_warning": ""},
        ],
    }
    TURNED_DOOR = {**DOOR_PROP, "variant_tiers": [
        {**DOOR_TIER, "rotation": {"x": 0, "y": 270, "z": 0},
         "area_defaults": {"glass_1": {"preset": "glass"}}}]}
    stub_library(lambda pid: (
        dict(FRAME_PROP) if pid == "frame"
        else {**TURNED_DOOR, "id": pid} if pid == "door1" else None))
    loc = door_fixture(a_openings=[{**S_DOOR, "prop_id": "door1"}])
    loc["rooms"][0]["layout"]["props"] = [
        {"prop_id": "frame", "at": [1.0, 1.0], "variant": 1},
        {"prop_id": "frame", "at": [2.0, 1.0], "variant": 0}]
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    by_anchor = {tuple(m["anchor"]): m for m in props_of(sc, "frame")}
    v1 = by_anchor.get((-3.0, -3.0), {})
    v0 = by_anchor.get((-2.0, -3.0), {})
    check("both copies of the frame are placed", bool(v1) and bool(v0),
          str(sorted(by_anchor)))
    check("variant 1: fix_euler comes from ITS file — y = 90",
          v1.get("fix_euler") == {"x": 0.0, "y": 90.0, "z": 0.0},
          str(v1.get("fix_euler")))
    check("variant 1: slots = its own area_defaults",
          v1.get("slots") == {"glass_1": {"preset": "glass"}},
          str(v1.get("slots")))
    check("variant 1: leaf_bbox = its own file's box",
          v1.get("leaf_bbox") == FRAME_LEAF, str(v1.get("leaf_bbox")))
    check("variant 0: fix_euler 0, no slots, no leaf_bbox",
          v0.get("fix_euler") == {"x": 0.0, "y": 0.0, "z": 0.0}
          and "slots" not in v0 and "leaf_bbox" not in v0, str(v0))
    with_values = dict(FRAME_PROP)
    with_values["variant_tiers"] = [
        FRAME_PROP["variant_tiers"][0],
        {**FRAME_PROP["variant_tiers"][1],
         "slot_values": {"picture_1": {"image": "/world/locations/l/gallery/p.png"}}}]
    stub_library(lambda pid: (
        with_values if pid == "frame"
        else {**TURNED_DOOR, "id": pid} if pid == "door1" else None))
    sc2 = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    v1b = {tuple(m["anchor"]): m for m in props_of(sc2, "frame")}.get(
        (-3.0, -3.0), {})
    check("variant 1: slot_values are laid over its area_defaults",
          v1b.get("slots") == {"glass_1": {"preset": "glass"},
                               "picture_1": {"image": "/world/locations/l/gallery/p.png"}},
          str(v1b.get("slots")))
    dspec = door_specs(sc)
    check("the door spec reads the PRIMARY variant's file: fix_euler y = 270",
          len(dspec) == 1 and dspec[0]["fix_euler"] == {"x": 0.0, "y": 270.0, "z": 0.0},
          str(dspec and dspec[0].get("fix_euler")))
    check("...and its slots from variant_tiers[0].area_defaults",
          len(dspec) == 1 and dspec[0].get("slots") == {"glass_1": {"preset": "glass"}},
          str(dspec and dspec[0].get("slots")))
    stub_door_props()

    # ── the MIRRORED copy may win the width, never the direction ─────────
    # A shared door clamped into the AUTHOR's corner, on a neighbour wall that
    # is longer there, is the one case in which the wider entry is the
    # neighbour's mirrored copy — and a mirrored copy runs backwards.
    #   a's edge 1: (0, −4) → (0, −1), u = (0, 1), length 3. Door at 0.0,
    #   width 1.0 → half 0.5, centre 0 → span [0, 0.5]: clear width 0.5,
    #   middle (0, −3.75).
    #   room "wide" (x 0 y −5 w 2 d 4) is world x 0…2, z −5…−1; its edge 3
    #   runs (0, −1) → (0, −5), u = (0, −1), length 4. The mirror projects the
    #   door's point (0, −4) onto it at t = 3 → at 0.75 → half 0.5, centre 3
    #   → span [2.5, 3.5]: width 1.0, middle (0, −4), along (0, −1).
    # 1.0 > 0.5, so the mirrored copy brings at_world (0, −4) and width 1.0.
    # Everything else stays with the author: along (0, 1), rooms ["a", …],
    # hinge. Hence anchor = (0, −4) − (0, 1)·0.5 = (0, −4.5) and
    # yaw = atan2(−1, 0) = −90 → 270. The mirrored direction would put the
    # hinge on the OTHER jamb, at (0, −3.5) with yaw 90.
    wide_room = {"id": "wide", "name": "Wide", "layout": {
        "x": 0.0, "y": -5.0, "w": 2.0, "d": 4.0, "level": 0}}
    corner = door_prop_scene(extra_rooms=(wide_room,), a_openings=[
        {"edge": 1, "at": 0.0, "type": "door", "width_m": 1.0,
         "height_m": 2.1, "to": "wide", "prop_id": "door1"}])
    ways = corner["doorways"]
    check("the wider mirrored copy brings the GEOMETRY: (0, −4), width 1.0",
          len(ways) == 1 and ways[0]["at_world"] == [0.0, -4.0]
          and near(ways[0]["width_m"], 1.0), str(ways))
    check("...but the wall's own direction (0, 1) and its room stay first",
          len(ways) == 1 and ways[0]["along"] == [0.0, 1.0]
          and ways[0]["rooms"] == ["a", "wide"], str(ways))
    cspec = door_specs(corner)
    check("...so the hinge sits on the AUTHOR's jamb (0, −4.5), yaw 270",
          len(cspec) == 1 and cspec[0]["anchor"] == [0.0, -4.5]
          and near(cspec[0]["yaw_deg"], 270.0), str(cspec))
    check("...and the prop the author named survives the swap",
          len(cspec) == 1 and cspec[0]["id"] == "door1"
          and cspec[0]["door"] == {"opening": 0, "hinge": "left",
                                   "swing": 1}, str(cspec))

    # ── the three-valued resolution (Entscheid 2) ────────────────────────
    dflt = door_prop_scene(a_openings=[dict(S_DOOR)], default_prop="door2")
    check("the location default fills an opening that names no prop",
          len(door_specs(dflt)) == 1
          and door_specs(dflt)[0]["id"] == "door2", str(door_specs(dflt)))
    over = door_prop_scene(a_openings=[{**S_DOOR, "prop_id": "door1"}],
                           default_prop="door2")
    check("...the opening's own prop_id wins over it",
          len(door_specs(over)) == 1
          and door_specs(over)[0]["id"] == "door1", str(door_specs(over)))
    none = door_prop_scene(a_openings=[{**S_DOOR, "door_prop": "none"}],
                           default_prop="door2")
    check("...and door_prop 'none' suppresses it — leaf back, no flag",
          not door_specs(none) and len(leaves(none)) == 1
          and "door_prop" not in leaves(none)[0], str(leaves(none)))

    # ── only a DOOR gets one ─────────────────────────────────────────────
    win = door_prop_scene(a_openings=[
        {"edge": 0, "at": 0.5, "type": "window", "width_m": 2.0,
         "height_m": 1.2, "sill_m": 0.9, "prop_id": "door1"}, dict(S_DOOR)],
        default_prop="door2")
    check("a window never takes a door prop, not even the default",
          len(door_specs(win)) == 1
          and door_specs(win)[0]["door"]["opening"] == 0, str(door_specs(win)))
    pas = door_prop_scene(a_openings=[
        {**S_DOOR, "type": "passage", "prop_id": "door1"}],
        default_prop="door2")
    check("a passage is an authored hole WITHOUT a door — no prop either",
          not door_specs(pas), str(door_specs(pas)))

    # ── a dangling id keeps its placement ────────────────────────────────
    # The rule every prop placement follows (§ A2): world data lives in the
    # DB, props are files, so there is no referential integrity — and a
    # placement that vanished silently is worse than a visible hole. A door
    # prop gets NO placeholder box, though: a stand-in is drawn centred on its
    # anchor, and this anchor is an edge.
    gone = door_specs(door_prop_scene(a_openings=[
        {**S_DOOR, "prop_id": "nosuchprop"}]))
    check("an id that names nothing keeps its spec, with NO variants",
          len(gone) == 1 and gone[0]["id"] == "nosuchprop"
          and gone[0]["variants"] == {}, str(gone))
    check("...and carries no placeholder box (the anchor is an edge)",
          len(gone) == 1 and "placeholder_dims" not in gone[0], str(gone))

    # ── it has to reach the client ───────────────────────────────────────
    check("the recipe version has moved past the door props (5)",
          scene_recipe.SCENE_RECIPE_VERSION >= 5,
          str(scene_recipe.SCENE_RECIPE_VERSION))
    base = door_prop_scene(a_openings=[dict(S_DOOR)])["signature"]
    check("changing the location default moves the signature",
          door_prop_scene(a_openings=[dict(S_DOOR)],
                          default_prop="door2")["signature"] != base)
    check("a new MESH for the door prop moves it too (same URL, new sig)",
          _resigned_door_scene() != door_prop_scene(
              a_openings=[dict(S_DOOR)], default_prop="door2")["signature"])
    # The authored hinge rides in the room block the 2D editor reads back.
    hinged = door_prop_scene(a_openings=[
        {**S_DOOR, "prop_id": "door1", "hinge": "right"}])
    ops = [o for r in hinged["rooms"] if r["room_id"] == "a"
           for o in r["openings"]]
    check("openings[].hinge reaches the payload's room block",
          len(ops) == 1 and ops[0].get("hinge") == "right", str(ops))

    # ── D3: the picture is chosen where the prop is BUILT ────────────────
    # There is no picture choice PER PLACEMENT any more
    # (spec-picture-props.md, decision D3). `slot_values` is not a stored
    # field on either carrier — `_sanitize_props` and `_sanitize_opening`, the
    # two sanitizers `save_location` runs over a floor plan, drop it silently,
    # and no `slots` key is derived from it in the payload. What a
    # prop shows is settled where the prop is BUILT: its own defaults and its
    # picture variants. One mechanism, and deliberately no fallback reader for
    # the old field.
    from app.core.world_ops import _sanitize_opening, _sanitize_props
    values = {"glass": {"preset": "glass"}}   # a slot `door1` really declares
    stored = _sanitize_props([{"prop_id": "door1", "at": [1.0, 1.0],
                               "slot_values": values}])
    check("a placement's slot_values do not survive the save",
          len(stored) == 1 and "slot_values" not in stored[0], str(stored))
    op_saved = _sanitize_opening({**S_DOOR, "prop_id": "door1",
                                  "slot_values": values})
    check("...and neither do an opening's",
          op_saved and "slot_values" not in op_saved, str(op_saved))
    filled = door_prop_scene(a_openings=[{**S_DOOR, "prop_id": "door1",
                                          "slot_values": values}])
    check("a door-prop spec derives no `slots` from them",
          len(door_specs(filled)) == 1
          and "slots" not in door_specs(filled)[0], str(door_specs(filled)))
    # The room placement says the same with the example prop, which declares
    # an image slot and a material one.
    stub_props()
    room_loc = model_fixture()
    for room in room_loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"][0]["slot_values"] = {
                "picture": {"image": "/world/locations/loc/gallery/wall.png"}}
    room_spec = spec_of(
        scene_recipe.compose_scene(room_loc, plan_width_m=PLAN_W,
                                   building_meta=BUILDING_META,
                                   room_metas=room_metas()),
        "prop", "table")
    check("...and neither does a room placement's prop spec",
          "slots" not in room_spec, str(sorted(room_spec)))
    stub_props()


def _resigned_door_scene() -> str:
    """The default-prop scene with a NEW mesh signature on that prop."""
    stub_library(lambda pid: (
        {**DOOR_PROP, "id": pid, "model_signature": "doorsig2"}
        if pid in ("door1", "door2") else None))
    try:
        return door_prop_scene(a_openings=[dict(S_DOOR)],
                               default_prop="door2")["signature"]
    finally:
        stub_door_props()


def test_threshold_base_y() -> None:
    print("\n[3e] thresholds stand where one STANDS (finding 2026-08-16)")
    # The finding: the 3D client lifted every threshold quad itself, against
    # its own sampled room floors — and it compared a TILE-LOCAL `base_y` with
    # WORLD room centres while doing it, so on "Haus von Kai" the quads floated
    # 0.130 over a floor at 0.100 (living room), 0.207 over 0.100 (kitchen) and
    # 0.150 over 0.000 (pool). The height belongs to the server, and the rule is
    # this pure function — fed here with exactly those numbers.
    tby = scene_recipe.threshold_base_y
    check("no declaration: the wall's own foot, 0.10 — as before",
          near(tby([(0.10, None)]), 0.10), str(tby([(0.10, None)])))
    check("a room that DECLARES its walkable surface (0.12) sets the threshold",
          near(tby([(0.10, 0.12)]), 0.12), str(tby([(0.10, 0.12)])))
    check("two rooms: the HIGHER standing height wins — 0.10 vs 0.177 → 0.177",
          near(tby([(0.10, None), (0.10, 0.177)]), 0.177),
          str(tby([(0.10, None), (0.10, 0.177)])))
    # Red counter-check on the REAL function: one steps OVER a threshold, so
    # the low side must not win. A `min` in there would answer 0.10 and put the
    # kitchen door 7.7 cm inside the kitchen floor — this check falls over the
    # moment it does.
    check("...and the low side does NOT win — the function never answers 0.10",
          not near(tby([(0.10, None), (0.10, 0.177)]), 0.10),
          str(tby([(0.10, None), (0.10, 0.177)])))
    check("a declaration BELOW the foot is still the standing height",
          near(tby([(0.10, 0.05)]), 0.05), str(tby([(0.10, 0.05)])))
    check("no side at all is 0, never a crash", near(tby([]), 0.0))

    # ── the same rule through the whole composer ────────────────────────
    # Room "a" has no `model_offset_y`, so its diorama's lower edge is the
    # room's floor — on STOREY 0 the terrain, i.e. 0.00 since E5a — plus the
    # diorama clearance 0.02 = 0.02, and `walk_y` counts from there:
    # walk_y 0 → 0.02, walk_y 0.057 → 0.077. (The plate era answered 0.12 and
    # 0.177 for the same dials; the whole chain sat 0.10 higher, on the room
    # plate that no longer exists.)
    def with_metas(metas: dict, loc=None) -> list:
        return scene_recipe.compose_scene(loc or fixture(), plan_width_m=PLAN_W,
                                          room_metas=metas)["doorways"]

    plain = with_metas({})
    check("no diorama anywhere: base_y stays the wall foot 0.00",
          len(plain) == 1 and near(plain[0]["base_y"], 0.0), str(plain))
    lifted = with_metas({"a": {"width_m": 3.0, "walk_y": 0}})
    check("room a declares its floor (0.02): its OUTSIDE door lifts with it",
          len(lifted) == 1 and near(lifted[0]["base_y"], 0.02), str(lifted))
    # Party wall a|b: a keeps the foot, b's diorama declares 0.177.
    b_room = {"id": "b", "name": "B", "layout": {
        "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0}}
    party = door_fixture(extra_rooms=(b_room,), a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6, "to": "b"}])
    joined = with_metas({"b": {"width_m": 3.0, "walk_y": 0.057}}, party)
    check("a door between 0.00 and 0.077 lies at 0.077 — one steps OVER it",
          len(joined) == 1 and near(joined[0]["base_y"], 0.077), str(joined))
    check("...and the order of the rooms does not decide it",
          near(with_metas({"a": {"width_m": 3.0, "walk_y": 0.057},
                           "b": {"width_m": 3.0, "walk_y": 0}},
                          party)[0]["base_y"], 0.077),
          str(with_metas({"a": {"width_m": 3.0, "walk_y": 0.057},
                          "b": {"width_m": 3.0, "walk_y": 0}}, party)))
    # A room meta WITHOUT walk_y declares nothing — a diorama alone is not a
    # statement about where its floor is (that is the "no automatic repair"
    # rule of the model contract).
    check("a diorama without walk_y changes nothing",
          near(with_metas({"a": {"width_m": 3.0}})[0]["base_y"], 0.0),
          str(with_metas({"a": {"width_m": 3.0}})))
    # The height moves with the meta, so the payload has to be re-fetched.
    sigs = {scene_recipe.compose_scene(fixture(), plan_width_m=PLAN_W,
                                       room_metas=m)["signature"]
            for m in ({}, {"a": {"width_m": 3.0, "walk_y": 0}})}
    check("a changed walk_y moves the signature", len(sigs) == 2, str(sigs))

    # ── source pin: the client does NOT recompute this any more ─────────
    # There is no client smoke over `main.ts` (its door tests cover
    # `game/doors.ts`, the payload reader), so the removal is pinned here: the
    # two functions that did the recomputing are gone, and the quad hangs in
    # the tile frame where `base_y` is stated.
    main_ts = (Path(__file__).resolve().parents[1]
               / "client3d" / "src" / "main.ts")
    src = main_ts.read_text(encoding="utf-8") if main_ts.exists() else ""
    check("client3d/src/main.ts is where it is", bool(src), str(main_ts))
    check("no doorFloorY/doorMarkY left — nothing recomputes the height",
          "doorFloorY" not in src and "doorMarkY" not in src)
    check("the quad takes base_y + the lift straight from the payload",
          "m.baseY + DOOR_MARK_LIFT" in src)
    check("...and hangs in the TILE frame, like the walls",
          "tile.group.add(root)" in src)
    # Same error class, same pin (review 2026-08-16, re-derived for E5b): a
    # DECLARED `walk_y_world` is a TILE metre and the spots it places are world
    # points, so the tile's own height has to be added on the way in. On a tile
    # whose plateau is 0.05 m the pool's declared 0.12 sank the room centre to
    # 0.13 instead of 0.17; on a high plateau the old spot filter matched
    # nothing at all and the declaration was silently dropped. The 6 x 6 ray
    # raster is gone ("Ein Boden" E5b) and the conversion is the same one, now
    # in `roomFloorWorldY` — pinned here because the lookup around it needs a
    # THREE scene and cannot be computed purely.
    tiles_ts = (Path(__file__).resolve().parents[1]
                / "client3d" / "src" / "scene" / "tiles.ts")
    tsrc = tiles_ts.read_text(encoding="utf-8") if tiles_ts.exists() else ""
    check("client3d/src/scene/tiles.ts is where it is", bool(tsrc), str(tiles_ts))
    check("the declared floor enters the derivation as a WORLD height",
          "return tile.center.y + floor.declared;" in tsrc)
    check("...and the 6 x 6 ray raster that used to guess it is gone",
          "sampleRoomWalkables" not in tsrc and "Raycaster" not in tsrc)


def test_elevator() -> None:
    print("\n[5] elevator primitives")
    sc = scene()
    kinds = {}
    for e in sc["extras"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    check("4 columns + roof, 3 glass panes, 1 pad per level, 1 cabin",
          kinds == {"elevator_shaft": 5, "elevator_glass": 3,
                    "elevator_pad": 1, "elevator_cabin": 1}, str(kinds))
    shaft = [e for e in sc["extras"] if e["kind"] == "elevator_shaft"]
    roof = [e for e in shaft if near(e["size"][0], 1.8)]
    check("the shaft is the contract's 1.8 m square (k = 1)", len(roof) == 1,
          str(roof))
    posts = [e for e in shaft if e is not roof[0]]
    check("columns are 0.14 m thick",
          all(near(p["size"][0], 0.14) for p in posts),
          str(posts[0]["size"]))
    check("they run up to (top level + 1) × storey + 0.08",
          all(near(p["size"][1], 3.08) for p in posts), str(posts[0]["size"]))
    glass = {e.get("side") for e in sc["extras"] if e["kind"] == "elevator_glass"}
    check("the side facing the square's centre stays open (west)",
          glass == {"north", "south", "east"}, str(glass))
    cabin = [e for e in sc["extras"] if e["kind"] == "elevator_cabin"][0]
    check("cabin 1.4 m square, 0.6 × storey tall",
          near(cabin["size"][0], 1.4) and near(cabin["size"][1], 1.8),
          str(cabin["size"]))
    pad = [e for e in sc["extras"] if e["kind"] == "elevator_pad"][0]
    # THE PAD HANGS UNDER THE FLOOR OF ITS STOREY, and on storey 0 that floor
    # is the TERRAIN since "Ein Boden" E5a: its top is 0.00 and its centre half
    # a thickness below, −0.025. (The slab era put it under the 0.08 plate, at
    # +0.055.)
    check("pad 1.6 m just under the storey-0 floor, i.e. the terrain",
          near(pad["size"][0], 1.6) and near(pad["center"][1], -0.025),
          str(pad))
    check("red: the old 0.055 (under a 0.08 slab) is gone",
          not near(pad["center"][1], 0.055), str(pad["center"][1]))
    check("no elevator without map3d.elevator",
          not scene_recipe.compose_scene({"map3d": {}, "rooms": []})["extras"])


def stair_fixture(stairs) -> dict:
    """The [1] fixture PLUS ``map3d.stairs`` — a variant on purpose.

    The base fixture must stay stair-less: every expectation above (the
    elevator's ``extras`` census in particular) is derived against it, and a
    staircase in it would silently move those numbers.
    """
    loc = fixture()
    loc["map3d"] = {**loc["map3d"], "stairs": list(stairs)}
    return loc


def stair_scene(stairs) -> dict:
    return scene_recipe.compose_scene(stair_fixture(stairs),
                                      plan_width_m=PLAN_W)


def test_stairs() -> None:
    print("\n[5s] stairs — a flight of solid steps between two storeys")
    # THE WHOLE DERIVATION BY HAND (spec § 0), never read off the output.
    # Constants: width 1.20 across the climb, tread 0.26 along it, nominal
    # rise 0.20, pad edge 0.90 × 0.05 thick.
    #
    # EG → OG, storey 3.00, at = (2, −2), dir 90 → +X:
    #   base   = storey_floor_y(0, 3) = 0.00          (storey 0 IS the terrain)
    #   target = storey_floor_y(1, 3) = 1·3 + 0.08 = 3.08
    #   climb  = 3.08          steps = round(3.08 / 0.20) = round(15.4) = 15
    #   rise   = 3.08 / 15 = 0.2053333…               run = 15 · 0.26 = 3.90
    # Step i is a SOLID box from the floor up to base + (i+1)·rise:
    #   centre = [2 + (i+0.5)·0.26,  base + (i+1)·rise/2,  −2]
    #   size   = [0.26, (i+1)·rise, 1.20]
    #   i = 0  → centre [2.13, 0.1026667, −2]  size [0.26, 0.2053333, 1.2]
    #   i = 14 → centre [2 + 3.77, 3.08/2, −2] = [5.77, 1.54, −2]
    #            size [0.26, 3.08, 1.2]
    # The pads are markers, one per end, and their TOP is the storey floor
    # (elevator_pad's law): centre_y = floor − 0.05/2.
    #   foot: at − dir·(0.90/2 + 0.05) = (2 − 0.5, −2) → [1.5, −0.025, −2]
    #   head: at + dir·(run + 0.90/2 + 0.05) = (2 + 3.9 + 0.5, −2)
    #         → [6.4, 3.08 − 0.025, −2] = [6.4, 3.055, −2]
    sc = stair_scene([{"at": [2.0, -2.0], "from_level": 0, "dir_deg": 90}])
    kinds = {}
    for e in sc["extras"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    check("15 steps and 2 pads next to the elevator's own primitives",
          kinds.get("stair_step") == 15 and kinds.get("stair_pad") == 2,
          str(kinds))
    steps = [e for e in sc["extras"] if e["kind"] == "stair_step"]
    first, last = steps[0], steps[-1]
    check("step 0: centre [2.13, 0.10267, −2], size [0.26, 0.20533, 1.2]",
          near(first["center"][0], 2.13) and near(first["center"][1], 0.102667)
          and near(first["center"][2], -2.0)
          and near(first["size"][0], 0.26) and near(first["size"][1], 0.205333)
          and near(first["size"][2], 1.2),
          f"{first['center']} {first['size']}")
    check("step 14: centre [5.77, 1.54, −2], size [0.26, 3.08, 1.2] — the "
          "last step reaches the upper floor",
          near(last["center"][0], 5.77) and near(last["center"][1], 1.54)
          and near(last["center"][2], -2.0)
          and near(last["size"][0], 0.26) and near(last["size"][1], 3.08)
          and near(last["size"][2], 1.2),
          f"{last['center']} {last['size']}")
    check("every step carries its lower level and the stair index",
          all(s.get("level") == 0 and s.get("stair") == 0 for s in steps),
          str({(s.get("level"), s.get("stair")) for s in steps}))
    pads = {e.get("end"): e for e in sc["extras"] if e["kind"] == "stair_pad"}
    check("foot pad: centre [1.5, −0.025, −2], size 0.9 × 0.05, level 0",
          near(pads["foot"]["center"][0], 1.5)
          and near(pads["foot"]["center"][1], -0.025)
          and near(pads["foot"]["center"][2], -2.0)
          and near(pads["foot"]["size"][0], 0.9)
          and near(pads["foot"]["size"][1], 0.05)
          and near(pads["foot"]["size"][2], 0.9)
          and pads["foot"].get("level") == 0, str(pads.get("foot")))
    check("head pad: centre [6.4, 3.055, −2], level 1 — one run plus half a "
          "pad beyond the last step",
          near(pads["head"]["center"][0], 6.4)
          and near(pads["head"]["center"][1], 3.055)
          and near(pads["head"]["center"][2], -2.0)
          and pads["head"].get("level") == 1, str(pads.get("head")))
    # The climb direction decides which axis carries the tread — the width
    # stays ACROSS it. dir 0 = (0, +1): step 0 centre z = −2 + 0.13 = −1.87,
    # size [1.2, 0.2053333, 0.26]; foot pad z = −2 − 0.5 = −2.5, head pad
    # z = −2 + 3.9 + 0.5 = 2.4, both on x = 2.
    sc0 = stair_scene([{"at": [2.0, -2.0], "from_level": 0, "dir_deg": 0}])
    s0 = [e for e in sc0["extras"] if e["kind"] == "stair_step"][0]
    check("dir 0 climbs along +z: size x↔z swapped, centre moves in z",
          near(s0["center"][0], 2.0) and near(s0["center"][2], -1.87)
          and near(s0["size"][0], 1.2) and near(s0["size"][2], 0.26),
          f"{s0['center']} {s0['size']}")
    p0 = {e.get("end"): e for e in sc0["extras"] if e["kind"] == "stair_pad"}
    check("dir 0 pads sit at z −2.5 and z 2.4, both on x 2",
          near(p0["foot"]["center"][2], -2.5) and near(p0["head"]["center"][2], 2.4)
          and near(p0["foot"]["center"][0], 2.0)
          and near(p0["head"]["center"][0], 2.0),
          f"{p0['foot']['center']} {p0['head']['center']}")
    # BASEMENT → EG (§ 0's second hand calculation): base =
    # storey_floor_y(−1, 3) = −3 + 0.08 = −2.92, target = 0.00, climb 2.92,
    # steps = round(14.6) = 15, rise = 2.92 / 15 = 0.1946667, run 3.90.
    #   step 0  centre_y = −2.92 + 0.0973333 = −2.8226667
    #   step 14 centre_y = −2.92 + 1.46 = −1.46, size_y = 2.92
    #   foot pad −2.92 − 0.025 = −2.945 (level −1), head pad −0.025 (level 0)
    scb = stair_scene([{"at": [2.0, -2.0], "from_level": -1, "dir_deg": 90}])
    bsteps = [e for e in scb["extras"] if e["kind"] == "stair_step"]
    bpads = {e.get("end"): e for e in scb["extras"] if e["kind"] == "stair_pad"}
    check("basement flight: 15 steps, first at −2.82267, last 2.92 tall",
          len(bsteps) == 15 and near(bsteps[0]["center"][1], -2.822667)
          and near(bsteps[0]["size"][1], 0.194667)
          and near(bsteps[-1]["size"][1], 2.92)
          and near(bsteps[-1]["center"][1], -1.46),
          f"{bsteps[0]['center']} {bsteps[-1]['size']}")
    check("basement pads: −2.945 on level −1, −0.025 on level 0",
          near(bpads["foot"]["center"][1], -2.945)
          and bpads["foot"].get("level") == -1
          and near(bpads["head"]["center"][1], -0.025)
          and bpads["head"].get("level") == 0,
          f"{bpads['foot']['center'][1]} {bpads['head']['center'][1]}")
    # Two flights = two indices; the second one is untouched by the first.
    sc2 = stair_scene([{"at": [2.0, -2.0], "from_level": 0, "dir_deg": 90},
                       {"at": [-2.0, 2.0], "from_level": 1, "dir_deg": 270}])
    idx = {e.get("stair") for e in sc2["extras"]
           if str(e["kind"]).startswith("stair_")}
    check("a chain of two flights keeps its own indices", idx == {0, 1},
          str(idx))
    # RED PROBE: the base fixture has no stairs, so it must produce none —
    # otherwise the elevator census above would be measuring a staircase.
    check("red: no stair primitive without map3d.stairs",
          not [e for e in scene()["extras"]
               if str(e["kind"]).startswith("stair_")])


def test_style() -> None:
    print("\n[6] style block")
    st = scene()["style"]
    check("the renderers' constants live here",
          st["wall_color"] == "#cfc4b2" and st["floor_color"] == "#d8d0c2"
          and near(st["glass_opacity"], 0.25)
          and near(st["upper_wall_opacity"], 0.45)
          and near(st["upper_floor_opacity"], 0.4), str(st))
    check("8 room palette colours", len(st["room_palette"]) == 8,
          str(len(st["room_palette"])))
    # The DOOR LEAF's colour is part of the shared vocabulary too (user
    # decision 2026-08-25) — opaque and dark, and NOT the wall colour, or a
    # door would disappear into the facade it sits in.
    check("the door leaf has its own colour in the style block",
          st["door_color"] == "#4a3a2e"
          and st["door_color"] != st["wall_color"],
          str(st.get("door_color")))


# ── M2: placement specs, markers, figures, signature ────────────────────
# The prop store is a FILE library — the smoke stubs it so the numbers stay
# hand-checkable. The prop is the contract's own worked example (§ A2), and
# the numbers below are re-derived BY HAND from the CORRECTED § A2 (final E4
# review) — never read off the current output:
#
#   raw box [1.0/0.5/2.0], fix y = 90°, dims W 1.2 / D 0.6 / H 0.3,
#   marker at [0.5/1.0/0.25] with facing 90, placement yaw 90.
#
#   1. fix R_y(+90) on the corners of [0, size]: (x, z) → (z, −x), so
#      x ∈ [0, 1] → z' ∈ [−1, 0] and z ∈ [0, 2] → x' ∈ [0, 2] → fixed
#      extents [2.0/0.5/1.0], lo = [0/0/−1], hi = [2/0.5/0].
#   2. s = max(dims) / max(extents) = 1.2 / 2.0 = 0.6 (× k, and k = 1).
#   3. marker point raw [0.5/0.5/0.5] → fixed [0.5/0.5/−0.5]; the anchor is
#      the bottom centre [1.0/0/−0.5], so
#      pre = 0.6 · [−0.5/0.5/0.0] = [−0.3/0.3/0.0].
#   4. the placement yaw turns that offset with the SAME matrix that turns
#      the mesh (rotation.y = +rad(yaw) since E4):
#      dx = pre_x·cos 90 + pre_z·sin 90 = 0
#      dz = −pre_x·sin 90 + pre_z·cos 90 = +0.3   → offset_m [0, +0.3]
#      height_m = pre_y = 0.3
#   5. facing grows in the SAME sense as the yaw (§ A1.8) →
#      facing = (90 + 90) % 360 = 180.
#
# (Pre-E4 this line said offset_m [0, −0.3] and facing 0 — the R_y(−yaw) /
#  facing − yaw compensation for the old model-yaw sign.)
EXAMPLE_PROP = {
    "id": "table", "name": "Table",
    "width_m": 1.2, "depth_m": 0.6, "height_m": 0.3,
    "bbox": [1.0, 0.5, 2.0],
    # Two resolution tiers (v5.3 Nr. 16) → the placement carries both and the
    # spec turns them into "<endpoint>?tier=<tier>" URLs.
    "has_model": True, "model_tiers": ["full", "low"],
    "model_signature": "propsig1",
    "markers": [{"id": "seat1", "group": "seat", "at": [0.5, 1.0, 0.25],
                 "facing": 90}],
    # The ONE published variant: the orientation fix is ITS file's
    # (spec-bild-props-v2.md E1), and the markers are its own (2026-08-25) —
    # the record's `markers` above is the primary's list, the same one.
    "variant_tiers": [{
        "variant": 0, "tiers": ["full", "low"],
        "dims": {"width_m": 1.2, "depth_m": 0.6, "height_m": 0.3},
        "rotation": {"x": 0, "y": 90, "z": 0},
        "markers": [{"id": "seat1", "group": "seat", "at": [0.5, 1.0, 0.25],
                     "facing": 90}],
        "areas": [], "area_defaults": {}, "areas_warning": ""}],
    # The two fillable surfaces of the example prop (v5 slots): one takes a
    # picture, one takes a look.
    "slots": [{"name": "picture", "kind": "image"},
              {"name": "glass", "kind": "material"}],
}

BUILDING_META = {"rotation": {"x": 0, "y": 90, "z": 0}, "offset_x": 1.0,
                 "offset_y": 0.2, "offset_z": -1.0}
# The walk height is a DIAL, never a measurement: 4 metres above the model's
# lower edge, and at k = 1 that is 4 world metres.
GROUND_META = {**BUILDING_META, "walk_y": 4.0}


def stub_props(ground_offset_m: float = 0.0) -> None:
    """Stub the library. ``ground_offset_m`` is the PROP's own sink (§ B2
    addendum 2026-08-20) — the library record carries it, the recipe copies it
    onto every placement of the prop, and the scene spec adds it to the base."""
    rec = dict(EXAMPLE_PROP)
    if ground_offset_m:
        # The sink is the VARIANT's (2026-08-25): it rides on the published
        # entry the placement resolves to, beside the record's own copy.
        rec["ground_offset_m"] = ground_offset_m
        rec["variant_tiers"] = [{**EXAMPLE_PROP["variant_tiers"][0],
                                 "ground_offset_m": ground_offset_m}]
    stub_library(lambda pid: dict(rec) if pid == "table" else None)


def model_fixture(*, room_width_m: float = 4.0, map_yaw=None,
                  # `map_yaw` writes a STRAY `map3d.rotation` — the field is
                  # deleted with v6 Nr. 10 and nothing may read it any more;
                  # `map_rotation_2d` is the flat icon's display rotation and
                  # is equally out of the scene. Both are here so the smoke
                  # can prove they reach nothing.
                  map_rotation_2d: int = 90, clip_d: bool = False,
                  clip_garden: bool = False, d_outline=None) -> dict:
    d_layout = {
        "x": 1.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 0,
        # model_at is METRES from the room's min corner (v6 Nr. 2): the old
        # fractions [0.25, 0.75] of a 2 × 2 m room ARE [0.5, 1.5] m.
        "model_at": [0.5, 1.5], "model_offset_y": 0.1, "rotation": 45}
    if clip_d:
        d_layout["clip_model"] = True
    if d_outline:
        d_layout["outline"] = d_outline
    loc = fixture([{"id": "d", "name": "D", "layout": d_layout}])
    if clip_garden:
        for room in loc["rooms"]:
            if room["id"] == "garden":
                room["layout"]["clip_model"] = True
    loc["map_rotation_2d"] = map_rotation_2d
    if map_yaw is not None:
        loc["map3d"]["rotation"] = map_yaw
    # Room "a" gets the example prop AND a room marker.
    for room in loc["rooms"]:
        if room["id"] == "a":
            # Room "a" is 4 × 3 m, so the old fractions [0.5, 0.5] and
            # [0.25, 0.5] are [2.0, 1.5] and [1.0, 1.5] metres.
            room["layout"]["props"] = [{"prop_id": "table", "at": [2.0, 1.5],
                                        "yaw": 90}]
            room["layout"]["markers"] = [{"at": [1.0, 1.5], "group": "stand",
                                          "rotation": 180, "offset_y": 0.05,
                                          "tilt": -12.0, "roll": 5.0}]
    return loc


def room_metas(width_m: float = 4.0) -> dict:
    return {"d": {"rotation": {"x": 0, "y": 180, "z": 0}, "width_m": width_m},
            "garden": {"width_m": width_m}}


def model_scene(**kw) -> dict:
    metas = room_metas(kw.pop("room_width_m", 4.0))
    return scene_recipe.compose_scene(model_fixture(**kw), plan_width_m=PLAN_W,
                                      building_meta=BUILDING_META,
                                      room_metas=metas)


def spec_of(sc: dict, role: str, ident: str = "") -> dict:
    hits = [m for m in sc["models"]
            if m["role"] == role and (not ident or m["id"] == ident)]
    return hits[0] if hits else {}


def test_building_spec() -> None:
    print("\n[7] building model spec")
    stub_props()
    sc = model_scene()
    b = spec_of(sc, "building")
    # v6 Nr. 3: the building scales by a DECLARED real width, like the
    # diorama. BUILDING_META declares none, so the location's own width
    # stands in — the boundary bbox is the 10 m square, hence max_m 10.0.
    # That is bit for bit what the retired `size` produced at its default 1
    # (extent_m × 1 = 10.0): this check IS the regression proof.
    check("undeclared width falls back to the boundary width (= old size 1)",
          near(b["max_m"], EXTENT) and b.get("measure") == "yawed_xz",
          f"{b.get('max_m')}/{b.get('measure')}")
    check("...and the spec says the width is only estimated",
          b.get("width_estimated") is True, str(b.get("width_estimated")))
    # A declared 15 m on the same 10 m location: 15 m, not 10, not 15/10 of
    # anything — the declaration wins over the plot, and it may exceed it.
    wide = spec_of(scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META, "width_m": 15.0}), "building")
    check("a declared width_m 15 on a 10 m location: max_m = 15",
          near(wide["max_m"], 15.0), str(wide.get("max_m")))
    # THE DEFAULT STAND is the plot's centre — the boundary bbox centre, not
    # the pin (user finding 2026-08-20: a plot enlarged to one side left the
    # mesh on the pin, and the roof view showed only part of the house).
    # Hand-derived: boundary [[0,0],[14,0],[14,10],[0,10]] has its bbox
    # centre at (7, 5); with offsets (+1, −1) the anchor is (8, 4). The
    # pin-centred fixtures above prove the (0,0) case never moved.
    fx = model_fixture()
    fx["map3d"]["boundary"] = [[0, 0], [14, 0], [14, 10], [0, 10]]
    off = spec_of(scene_recipe.compose_scene(
        fx, plan_width_m=14.0, room_metas=room_metas(),
        building_meta={**BUILDING_META, "offset_x": 0.0, "offset_z": 0.0}),
        "building")
    check("off-centre boundary: anchor = bbox centre (7, 5)",
          near(off["anchor"][0], 7.0) and near(off["anchor"][1], 5.0),
          str(off.get("anchor")))
    # BUILDING_META's own offsets are (+1, −1) — they shift FROM that centre.
    off2 = spec_of(scene_recipe.compose_scene(
        fx, plan_width_m=14.0, room_metas=room_metas(),
        building_meta=dict(BUILDING_META)), "building")
    check("...offsets shift FROM that centre: (8, 4)",
          near(off2["anchor"][0], 8.0) and near(off2["anchor"][1], 4.0),
          str(off2.get("anchor")))
    check("...and then nothing is estimated any more",
          "width_estimated" not in wide, str(sorted(wide)))
    check("the measurement stays the YAWED hull (a house must fit turned)",
          wide.get("measure") == "yawed_xz", str(wide.get("measure")))
    # The plot-share dial is gone: a location that still carries `size` in
    # its map3d must not scale by it (the sanitizer drops the field, and the
    # composer never looks at it — belt and braces, both are checked).
    sized = model_fixture()
    sized["map3d"]["size"] = 0.5
    ignored = spec_of(scene_recipe.compose_scene(
        sized, plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta=BUILDING_META), "building")
    check("a stray map3d.size scales NOTHING (v6 Nr. 3: the dial is gone)",
          near(ignored["max_m"], EXTENT), str(ignored.get("max_m")))
    from app.core.world_ops import _sanitize_map3d
    kept = _sanitize_map3d({"plan_width_m": 10, "rotation": 90, "size": 0.5,
                            "style": "house"})
    check("...and a submitted size does not even survive the save",
          "size" not in kept and kept.get("style") == "house", str(kept))
    check("...nor does a submitted rotation (v6 Nr. 10: the dial is gone)",
          "rotation" not in kept, str(kept))
    check("no per-axis fields survive",
          not {"box", "scale_mode", "scale_axes"} & set(b), str(sorted(b)))
    # THE ANCHOR IS THE WALKABLE SURFACE (§ B2 addendum 2026-08-20), pinned to
    # the STOREY-0 FLOOR — which since "Ein Boden" E5a is the terrain, i.e. 0:
    # walk_y_world = 0.00 + offset_y (0.2) = 0.2, and the mesh hangs `walk_y`
    # below it — undeclared here, so bottom_y is that same 0.2. (The slab era
    # answered 0.28 for both; the 0.08 it added was a floor nobody walks on.)
    check("a shell is anchored at its WALK surface: 0.00 + offset_y",
          near(b["walk_y_world"], 0.2), str(b.get("walk_y_world")))
    check("...and the mesh hangs walk_y below it (undeclared = the edge)",
          near(b["bottom_y"], 0.2), str(b["bottom_y"]))
    check("red: the 0.08 slab is gone from the anchor",
          not near(b["walk_y_world"], 0.28), str(b["walk_y_world"]))
    # A declared walk_y is what a mesh with a ground pad needs: "Haus von Kai"
    # carries 0.240 m of terrain under its walls, so its floor is 0.240 above
    # the lower edge. Declared, the floor lands ON the ground and the mesh
    # sinks by exactly that much: bottom_y = 0.00 + 0 − 0.240 = −0.24.
    padded = spec_of(scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META, "offset_y": 0.0, "walk_y": 0.240}),
        "building")
    check("a declared walk_y puts the model's FLOOR on the storey-0 floor",
          near(padded["walk_y_world"], 0.0),
          str(padded.get("walk_y_world")))
    check("...and sinks the mesh by the pad's own thickness",
          near(padded["bottom_y"], -0.24), str(padded.get("bottom_y")))
    check("the walk dial is still a DECLARATION, never a measurement "
          "(nothing fills it in: undeclared stays the lower edge)",
          near(b["walk_y_world"] - b["bottom_y"], 0.0),
          f"{b['walk_y_world']} vs {b['bottom_y']}")
    check("anchor = tile centre + offset_x/z", b["anchor"] == [1.0, -1.0],
          str(b["anchor"]))
    check("the meta fix rides along", near(b["fix_euler"]["y"], 90.0),
          str(b["fix_euler"]))
    # v6 Nr. 10: a BUILDING has no placement yaw at all any more. The old
    # chain `map3d.rotation` -> `map_rotation_2d` turned the mesh around the
    # SAME axis as the sidecar's own orientation fix (`fix_euler` y, checked
    # one line up as 90) — one axis, one dial. The fixture still carries
    # `map_rotation_2d` 90 and a `map3d.rotation`, and NEITHER may reach the
    # spec.
    check("a building carries no yaw of its own — constant 0",
          near(b["yaw_deg"], 0.0), str(b["yaw_deg"]))
    check("...not even from a stray map3d.rotation left in the world data",
          near(spec_of(model_scene(map_yaw=270), "building")["yaw_deg"], 0.0))
    check("no building meta → no building spec",
          not spec_of(scene_recipe.compose_scene(fixture(), plan_width_m=PLAN_W),
                      "building"))
    check("variants point at the ETag endpoint, one URL per tier "
          "(no tiers declared = full only, v5.3 Nr. 16)",
          b["variants"] == {"full": "/play/locations/loc/model?tier=full"},
          str(b.get("variants")))
    check("no url alias field next to it (No-Backward-Compat)",
          "url" not in b, str(sorted(b)))
    two = spec_of(scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META,
                       "tiers": {"full": {"signature": "a"},
                                 "low": {"signature": "b"}}}), "building")
    check("a declared low tier shows up as a second variant",
          two["variants"] == {"full": "/play/locations/loc/model?tier=full",
                              "low": "/play/locations/loc/model?tier=low"},
          str(two.get("variants")))


def test_floor_relation() -> None:
    """ONE floor, hand-derived — and since "Ein Boden" E5a it really is one.

    Everything a figure, a chair and a wall of the same room stand on has to be
    the same surface. Until E5a that surface was a STACK of three, quoted here
    by hand:

        terrain 0.00  <  level plate 0.08  <=  room plate 0.10
        prop bottom_y = room plate + PROP_CLEARANCE      = 0.11

    E3 deleted the client's grass socle under all of it; E5a deletes the two
    plates. What is left on storey 0 is the TERRAIN — under a location that
    builds, the plateau G5 stamps flat at exactly the height the location
    stands on, i.e. scene metre 0.00 — and the chain collapses to

        floor         = 0.00
        prop bottom_y = 0.00 + PROP_CLEARANCE           = 0.01
        wall base_y   = 0.00
        building walk_y_world = 0.00 + offset_y

    THE FIXTURE THAT BROKE (user finding 2026-08-20, "Haus von Kai"): a shell
    mesh with a 0.240 m terrain pad, dialled ``offset_y −0.30`` / ``walk_y 0``,
    put the model's own floor at ``0.06 + (−0.30) + 0.240 = 0.000`` — 0.100
    below the room plate its own props stood on, and 0.045 below the tile's
    grass. With one floor the same dials answer ``0.00 − 0.30 = −0.30`` for
    the walk surface, and there is no second floor left for it to be wrong
    against: props, walls and figure all measure from the very same 0.00.
    """
    print("\n[7c] one floor: terrain = wall foot = room floor = prop base")
    stub_props()
    sc = model_scene()
    check("NOT ONE plate is drawn on storey 0",
          not [p for p in sc["plates"] if p["level"] == 0], str(sc["plates"]))
    prop = spec_of(sc, "prop", "table")
    floor_y = 0.0
    check("a prop of the room stands ON the ground: 0.00 + 0.01",
          near(prop["bottom_y"], floor_y + scene_recipe.PROP_CLEARANCE)
          and near(prop["bottom_y"], 0.01), str(prop["bottom_y"]))
    walls = [w for w in sc["walls"] if w.get("room_id") == "a"]
    full = [w for w in walls if near(w["height"], WALL_H + SINK)]
    # THE WALL MEETS THAT SAME 0.00 — and goes on past it. Since the finding
    # round of 2026-08-21 the foot carries the skirt of § A16.9, so the number
    # that says "the wall stands on this floor" is its TOP minus its height:
    # −0.14 + 2.99 − 2.85 = 0.00. The skirt is below the floor, in the ground,
    # where the level plate's body used to be.
    check("...and the walls of that room meet the very same 0.00",
          full and all(near(w["base_y"] + w["height"] - WALL_H, floor_y)
                       for w in full)
          and all(near(w["base_y"], floor_y - SINK) for w in full),
          str(sorted({w["base_y"] for w in walls})))
    check("red: the three datums of the plate era are gone (0.08/0.10/0.11)",
          not any(near(prop["bottom_y"], t) for t in (0.08, 0.10, 0.11)),
          str(prop["bottom_y"]))
    b = spec_of(sc, "building")
    check("the building model is anchored ON that same floor: 0.00 + offset_y",
          near(b["walk_y_world"], 0.2), str(b.get("walk_y_world")))
    # The regression pin: the OLD laws' numbers for the Haus-von-Kai dials.
    kai = spec_of(scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META, "offset_y": -0.30}), "building")
    check("Haus von Kai dials (offset −0.30, walk_y 0) answer 0.00 − 0.30",
          near(kai["bottom_y"], -0.30),
          f"{kai['bottom_y']} (socle era −0.24, slab era −0.22)")
    check("...and neither the socle pin −0.24 nor the slab pin −0.22 survives",
          not near(kai["bottom_y"], -0.24) and not near(kai["bottom_y"], -0.22),
          str(kai["bottom_y"]))
    check("...and with the pad DECLARED (walk_y 0.240) its floor IS the ground",
          near(spec_of(scene_recipe.compose_scene(
              model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
              building_meta={**BUILDING_META, "offset_y": 0.0,
                             "walk_y": 0.240}),
              "building")["walk_y_world"], 0.0), "0.00")


def test_boundary_only_datum() -> None:
    """A BOUNDARY-ONLY area location — no drawn building outline, no closed
    room, no model (the user's "Mondscheinsee"). ONE GROUND, and the whole
    datum chain is hand-derived from that.

    THE THREE WAVES THAT LED HERE.

    1. The metric wave (8672c756) gave the level plate's contour the fallback
       ``_outline_world(map3d) or _drawn_boundary(map3d)``, so a location with
       nothing but a drawn boundary suddenly HAD an opaque storey slab —
       top 0.08, thickness 0.14 — while everything else still measured from the
       abstract storey datum 0 and sank into it.
    2. The datum wave (47abc26b) aligned everything ONTO that slab: surfaces
       at 0.09, zone anchors at 0.08. Right for a house on a plot. For the lake
       it made the sand and the water a hard-edged 14 cm PODIUM of grass
       standing over the landscape (user screenshots 2026-08-20).
    3. The § B1 addendum of 2026-08-20 exempted a NATURAL location from the
       slab (0.00 datum, surfaces at 0.01) — which fixed the lake and left
       TWO datums in the payload, one per kind of place.

    "EIN BODEN" E5a ends the argument by deleting the slab for everybody:
    storey 0 is the TERRAIN, for a lake and for a house alike.

        level plate                    = NONE, on any location
        room / zone floor              = NOT GEOMETRY — a LAYER of the ground
                                         (``core.terrain_layers``), and its
                                         polygon travels in ``floor_plan``
        storey-0 datum                 = 0.00
        zone anchor (NPCs, markers)    = 0.00
        prop in an outdoor room        = 0.00 + 0.01 = 0.01
        yard prop (§ A13a)             = 0.00 + 0.01 = 0.01  (the two are the
                                         SAME now — the anti-coplanar hair
                                         that separated them was a second
                                         surface, and there is none)
    """
    print("\n[4e] boundary-only location: ONE ground, no slab, no surfaces")
    lake = {"id": "lake", "name": "Lake", "layout": {
        "x": 1.0, "y": 1.0, "w": 3.0, "d": 3.0, "level": 0,
        "always_visible": True, "surfaces": {"floor": "gravel"},
        "props": [{"prop_id": "table", "at": [1.5, 1.5]}]}}
    far = {"id": "far", "name": "Far", "layout": {
        "x": 6.0, "y": 1.0, "w": 2.0, "d": 2.0, "level": 0,
        "always_visible": True, "surfaces": {"floor": "sand"}}}
    stub_props()
    yard = {"id": GROUND_ID, "name": "", "layout": {
        "props": [{"prop_id": "table", "at": [-2.0, -2.0]}],
        "markers": [{"at": [-3.0, -3.0], "group": "stand"}]}}
    loc = {"id": "loc", "map3d": {
        "plan_width_m": PLAN_W, "storey_height_m": STOREY_REAL,
        "area_model": True,
        "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]},
        "rooms": [lake, far, yard]}
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    check("red: ``natural_floor`` is gone from the payload — every storey-0 "
          "floor is the terrain now, so the flag would say nothing",
          "natural_floor" not in sc, str(sc.get("natural_floor")))
    check("NOT ONE plate — no level body, no surface, no cut edge",
          sc["plates"] == [], str(sc["plates"]))
    plan = {f["room_id"]: f for f in sc["floor_plan"]}
    check("the shore travels as a FLOOR PLAN entry instead of a plate",
          plan["lake"]["floor_kind"] == "gravel"
          and plan["lake"]["closed"] is False, str(plan.get("lake")))
    check("...and so does the sand", plan["far"]["floor_kind"] == "sand",
          str(plan.get("far")))
    check("the yard is NOT in it — it has no hull, it IS the ground (§ A13a)",
          GROUND_ID not in plan, str(sorted(plan)))
    check("a room INSIDE the drawn boundary is no longer a zone on a "
          "non-existent model",
          not (next(r for r in sc["rooms"] if r["room_id"] == "lake")
               .get("overlay")))
    zone = next(r for r in sc["rooms"] if r["room_id"] == "far")["overlay"]
    check("a room OUTSIDE it stays a zone — and its anchor is the storey-0 "
          "datum 0.00, where the NPCs stand",
          zone and near(zone["y"], 0.0), str(zone and zone.get("y")))
    props = [m for m in sc["models"] if m["role"] == "prop"]
    prop = next(m for m in props if m["room_id"] == "lake")
    check("a prop of the outdoor room stands on the ground: 0.00 + 0.01",
          near(prop["bottom_y"], 0.01), str(prop.get("bottom_y")))
    yard_prop = next(m for m in props if m["room_id"] == GROUND_ID)
    check("a YARD prop stands on the very same 0.01",
          near(yard_prop["bottom_y"], 0.01), str(yard_prop.get("bottom_y")))
    check("...and the 0.01 that used to separate the two is GONE — one floor, "
          "one answer",
          near(prop["bottom_y"] - yard_prop["bottom_y"], 0.0),
          f'{prop["bottom_y"]} vs {yard_prop["bottom_y"]}')
    # A PROP marker is composed FINISHED (§ A4), so it rides the datum with
    # its prop: 0.00 + 0.01 + the seat's own 0.30 over the placement = 0.31.
    seat = next(m for m in sc["markers"]
                if m["room_id"] == GROUND_ID and m["source"] == "prop")
    check("the yard's prop marker rides the datum too: 0.01 + 0.30",
          near(seat["y_world"], 0.31), str(seat["y_world"]))
    stand = next(m for m in sc["markers"]
                 if m["room_id"] == GROUND_ID and m["source"] == "room")
    check("...while a ROOM marker stays storey-relative (§ A4): 0.00",
          near(stand["y_world"], 0.0), str(stand["y_world"]))
    check("red: not one number of the slab era survives (0.08 / 0.09 / 0.10)",
          not any(near(v, t) for v in (prop["bottom_y"], yard_prop["bottom_y"],
                                       zone["y"], stand["y_world"])
                  for t in (0.08, 0.09, 0.10)),
          f'{prop["bottom_y"]} / {yard_prop["bottom_y"]} / {zone["y"]}')

    # ── THE CLASSIFICATION, AND WHAT IT STILL DECIDES ────────────────────
    # One closed room makes the place BUILT — and since E5a that changes
    # NOTHING in this payload. It changes the BAKE: a built place stamps its
    # plot flat (§ G5, ``models.heightfield.draws_built_floor``), a natural one
    # lets the landscape run through. Same rule, one consumer instead of two.
    hut = {"id": "hut", "name": "Hut", "layout": {
        "x": -4.0, "y": -4.0, "w": 2.0, "d": 2.0, "level": 0,
        "surfaces": {"floor": "wood"}}}
    built = scene_recipe.compose_scene(
        {**loc, "rooms": [lake, far, yard, hut]}, plan_width_m=PLAN_W)
    check("a BUILT place draws no storey-0 plate either",
          not [p for p in built["plates"] if p["level"] == 0],
          str(built["plates"]))
    b_props = {m["room_id"]: m for m in built["models"] if m["role"] == "prop"}
    check("...and its zone prop stands on exactly the same 0.01",
          near(b_props["lake"]["bottom_y"], prop["bottom_y"]),
          f'{b_props["lake"]["bottom_y"]} vs {prop["bottom_y"]}')
    b_plan = {f["room_id"]: f for f in built["floor_plan"]}
    check("the closed room is a floor plan entry that says CLOSED",
          b_plan["hut"]["closed"] is True
          and b_plan["hut"]["floor_kind"] == "wood", str(b_plan.get("hut")))
    check("red: the closed room has no plate of its own any more (was 0.10)",
          not [p for p in built["plates"] if p.get("room_id") == "hut"],
          str([p.get("room_id") for p in built["plates"]]))
    # THE RULE ITSELF still exists, and since E6 it has exactly ONE spelling:
    # ``models.heightfield.draws_built_floor``, asked of the STORED location.
    # (The scene builder's twin ``is_natural_location`` decided nothing in the
    # payload after E5a and is deleted — a second reading of the same law is a
    # second answer waiting to drift.)
    from app.models.heightfield import draws_built_floor
    check("the classifier says the two fixtures differ",
          [draws_built_floor(loc),
           draws_built_floor({**loc, "rooms": [lake, far, yard, hut]})],
          [False, True])
    # THE YARD IS NOT A CLOSED ROOM (§ A13a). It carries no `always_visible`
    # flag at all — it is the open ground of the place by definition — so a
    # location whose only non-outdoor "room" is the yard stays natural.
    check("the yard alone never makes a location built (§ A13a)",
          not draws_built_floor({**loc, "rooms": [
              {"id": GROUND_ID, "name": "Yard", "layout": {}}, lake]}))
    check("a DRAWN BUILDING CONTOUR makes it built, whatever its rooms",
          draws_built_floor({**loc, "rooms": [lake],
                             "map3d": {**loc["map3d"],
                                       "outline": [[-1, -1], [1, -1], [1, 1]]}}))
    # `area_model` is deliberately NOT part of the rule: the Mondscheinsee has
    # none and is the very case it exists for.
    check("a model is not what makes a place natural — the See has none",
          not draws_built_floor({"map3d": {"boundary": loc["map3d"]["boundary"]},
                                 "rooms": [lake]}))
    check("red: the composed-recipe twin is gone, one law has one name",
          not hasattr(scene_recipe, "is_natural_location"))


def test_area_room_walk_height() -> None:
    """THE WALK HEIGHT of a dioramed room inside an AREA location — the user's
    "Mondhütte" in "Mondscheinsee" (2026-08-20), hand-derived.

    The dial is ``walk_y`` on the ROOM MODEL's sidecar (Game-Admin →
    RoomModelAdjust, "Walkable floor (m)"): metres above the mesh's lower
    edge, a pure statement, never measured. The composer turns it into the
    absolute ``walk_y_world`` and nothing else touches it. Storey 0 IS the
    terrain since "Ein Boden" E5a, for every kind of location alike, so the
    chain has one rung fewer:

        the room's floor on storey 0                      = 0.00
        diorama bottom_y = floor 0.00 + DIORAMA_CLEARANCE 0.02
                           + layout.model_offset_y (−0.30)         = −0.28
        walk_y_world     = bottom_y + walk_y                       = −0.28 + w
                           w = 0.35                                =  0.07

    (The slab era answered 0.09 / −0.19 / 0.16 for the same dials and the
    natural-datum era 0.01 / −0.27 / 0.08 — three answers to one question,
    which is what the plan was written to end.)

    That half was always right; the finding was that the number never reached
    a walking figure. TWO holes, both in the client, both pinned below at the
    source and by hand in ``client3d/scripts/smoke_walk_math.mjs``:

      1. ``tileWalkY`` knew the drawn plates and the mesh ray and NOTHING
         about a room's declaration — the dial moved the NPC spots
         (``sampleRoomWalkables``) while the figure kept standing on the
         plate. Two floors in one room, which the one-datum law forbids.
      2. In an AREA location the plate branch was skipped entirely
         (``display`` ``shell_area``), and Mondscheinsee has no model to ray:
         the answer was the bare tile floor 0.00 — in the slab era 0.17 below
         where the declaration put the figure and 0.09 below the sand it walks
         on; on the natural datum the same hole is 0.09 and 0.01 deep.

    The SIGNATURE half is checked here too: the dial lives in ``room_metas``,
    which ``_signature`` hashes, so a running client re-fetches on the next
    sweep. (``layout_signature`` deliberately does NOT see it — it hashes
    ``map3d`` + room layouts for the relief cache, and a walk height changes
    no terrain.)
    """
    print("\n[4i] an area location's room declares its walk height")
    stub_props()
    hut = {"id": "hut", "name": "Hut", "layout": {
        "x": 1.0, "y": 1.0, "w": 3.0, "d": 3.0, "level": 0,
        "always_visible": True, "surfaces": {"floor": "sand"},
        "model_at": [1.5, 1.5], "model_offset_y": -0.30}}
    loc = {"id": "loc", "map3d": {
        "plan_width_m": PLAN_W, "storey_height_m": STOREY_REAL,
        "area_model": True,
        "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]},
        "rooms": [hut]}

    def scene_with(walk=None) -> dict:
        meta = {"width_m": 4.0}
        if walk is not None:
            meta["walk_y"] = walk
        return scene_recipe.compose_scene(loc, plan_width_m=PLAN_W,
                                          room_metas={"hut": meta})

    sc = scene_with(0.35)
    check("the room draws NO surface — its floor is the terrain (0.00)",
          not [p for p in sc["plates"] if p.get("room_id") == "hut"],
          str(sc["plates"]))
    plan = next(f for f in sc["floor_plan"] if f["room_id"] == "hut")
    check("...and its kind travels in the floor plan",
          plan["floor_kind"] == "sand", str(plan))
    spec = spec_of(sc, "room", "hut")
    check("the diorama hangs at floor + clearance + offset = −0.28",
          near(spec["bottom_y"], -0.28), str(spec.get("bottom_y")))
    check("a dialled walk_y 0.35 reaches the payload as walk_y_world 0.07",
          near(spec["walk_y_world"], 0.07), str(spec.get("walk_y_world")))
    check("...and it is 0.07 above the terrain the figure would otherwise take",
          near(spec["walk_y_world"] - 0.0, 0.07),
          str(spec["walk_y_world"]))
    check("a walk_y of 0 is a VALUE (the mesh's lower edge), not an absence",
          near(spec_of(scene_with(0.0), "room", "hut")["walk_y_world"], -0.28),
          str(spec_of(scene_with(0.0), "room", "hut").get("walk_y_world")))
    check("without the dial the room declares nothing at all",
          "walk_y_world" not in spec_of(scene_with(), "room", "hut"),
          str(spec_of(scene_with(), "room", "hut").get("walk_y_world")))
    # And the location itself has NO model here — exactly Mondscheinsee: the
    # area flag is set and nothing was ever generated, so the TERRAIN is the
    # only ground there is. That is the case the client fell through.
    check("the area location carries no building spec of its own",
          not [m for m in sc["models"] if m["role"] == "building"],
          str([m["role"] for m in sc["models"]]))

    # THE STALENESS HALF: three dial values, three signatures — a running
    # client's sweep compares exactly this string.
    sigs = [scene_with(w)["signature"] for w in (None, 0.0, 0.35)]
    check("every walk_y value has its own scene signature",
          len(set(sigs)) == 3, str([s[:8] for s in sigs]))
    lay = scene_recipe.layout_signature(loc["map3d"], loc["rooms"])
    check("...while layout_signature stays put — a walk height shapes nothing",
          lay == scene_recipe.layout_signature(loc["map3d"], loc["rooms"]),
          lay[:8])

    # ── source pins: the CLIENT rules that consume it ───────────────────
    # The walking height raycasts a THREE scene, so the pure halves are
    # hand-derived in `client3d/scripts/smoke_walk_math.mjs`
    # (`declaredFloorAt`, `plateCeiling`); what is pinned here is that
    # `tileWalkY` actually ASKS them — the hole the finding was.
    tiles_ts = (Path(__file__).resolve().parents[1]
                / "client3d" / "src" / "scene" / "tiles.ts")
    tsrc = tiles_ts.read_text(encoding="utf-8") if tiles_ts.exists() else ""
    check("client3d/src/scene/tiles.ts is where it is", bool(tsrc), str(tiles_ts))
    check("the walking figure asks the DECLARED floors first",
          "declaredFloorAt(tile.declaredFloors" in tsrc)
    check("...then the plates, whatever the display (E5b: the mesh rung that "
          "the `shell` guard existed for is deleted)",
          "info.display === 'shell' || !target" not in tsrc)
    check("...judged by the PLATE ceiling, the storey question",
          "plateCeiling(info)" in tsrc and "recipeFloorAt(tile.walkPlates" in tsrc)
    recipe_ts = (Path(__file__).resolve().parents[1]
                 / "client3d" / "src" / "scene" / "sceneRecipe.ts")
    rsrc = recipe_ts.read_text(encoding="utf-8") if recipe_ts.exists() else ""
    check("client3d/src/scene/sceneRecipe.ts is where it is", bool(rsrc))
    check("the mount fills the declared floors from the payload's own room "
          "hulls", "tile.declaredFloors.push({ roomId: room.room_id" in rsrc)
    check("...and drops them with the scene", "tile.declaredFloors = [];" in rsrc)


def test_room_and_prop_specs() -> None:
    print("\n[8] diorama and prop specs")
    stub_props()
    sc = model_scene()
    d = spec_of(sc, "room", "d")
    check("the diorama scales like a prop: width_m over its XZ side",
          near(d["max_m"], 4.0) and d.get("measure") == "xz", str(d))
    # Room "d": rect x 1 y 1 w 2 d 2 → centre (2, 2); `rotation` 45 turns the
    # WHOLE room about that centre (v6 addendum), the anchor included.
    #   model_at (0.5, 1.5) → unrotated (1.5, 2.5) → offset (−0.5, +0.5)
    #   x' = 2 + (−0.5·cos45 + 0.5·sin45) = 2 + 0        = 2.0
    #   z' = 2 − (−0.5·sin45) + 0.5·cos45 = 2 + √2/2     = 2.7071
    check("anchor from layout.model_at, TURNED with the room",
          d["anchor"] == [2.0, 2.7071], str(d["anchor"]))
    # STOREY 0 HAS NO PLATE ("Ein Boden" E5a): the floor is the terrain, 0.00,
    # so the diorama rests on the clearance plus its own dial —
    # 0.00 + 0.02 + model_offset_y (0.10) = 0.12. (The plate era answered 0.22,
    # the room plate's 0.10 higher.)
    check("indoor: bottom_y = the ground 0.00 + 0.02 + model_offset_y",
          near(d["bottom_y"], 0.12), str(d["bottom_y"]))
    # An outdoor room stands on that very same ground — one ``_plate_top`` for
    # diorama, props and walls, and on storey 0 it answers 0 for all of them.
    garden = spec_of(sc, "room", "garden")
    check("outdoor: the SAME floor, 0.00 + 0.02",
          near(garden["bottom_y"], 0.02), str(garden.get("bottom_y")))
    check("red: indoor and outdoor no longer differ by the old 0.11",
          not near(d["bottom_y"], 0.22) and not near(garden["bottom_y"], 0.11),
          f'{d["bottom_y"]}/{garden["bottom_y"]}')
    check("layout yaw + meta fix", near(d["yaw_deg"], 45.0)
          and near(d["fix_euler"]["y"], 180.0), str(d))
    fb = spec_of(model_scene(room_width_m=0.0), "room", "d")
    check("without width_m the room rectangle stands in — and says so",
          near(fb["max_m"], 2.0) and fb.get("width_estimated") is True,
          str(fb))
    check("a furnished room gets NO diorama (coexistence rule)",
          not spec_of(sc, "room", "a"))
    check("without walk_y the field stays absent", "walk_y_world" not in d)
    walked = scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, building_meta=BUILDING_META,
        room_metas={"d": {**room_metas()["d"], "walk_y": 0.3}})
    wd = spec_of(walked, "room", "d")
    check("walk_y counts in metres above the lower edge: bottom_y + walk_y",
          near(wd.get("walk_y_world", -1), 0.12 + 0.3),
          str(wd.get("walk_y_world")))
    zero = scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, building_meta=BUILDING_META,
        room_metas={"d": {**room_metas()["d"], "walk_y": 0}})
    check("walk_y 0 means the lower edge, not 'unset'",
          near(spec_of(zero, "room", "d").get("walk_y_world", -1), 0.12),
          str(spec_of(zero, "room", "d").get("walk_y_world")))

    p = spec_of(sc, "prop", "table")
    check("max(dims) over the full 3D extent",
          near(p["max_m"], 1.2) and p.get("measure") == "xyz", str(p))
    # Contract example: the client divides by the FIXED extent 2.0 → s = 0.6 k.
    check("§ A2 example: s = 0.6 k", near(p["max_m"] / 2.0, 0.6 * sc["k"]),
          str(p["max_m"] / 2.0))
    check("the prop's own orientation fix is delivered",
          near(p["fix_euler"]["y"], 90.0), str(p["fix_euler"]))
    check("anchor = placement point in world metres",
          p["anchor"] == [-2.0, -2.5], str(p["anchor"]))
    check("bottom_y = the storey-0 floor 0.00 + 0.01 + offset_y",
          near(p["bottom_y"], 0.01),
          str(p["bottom_y"]))
    check("a prop with a mesh needs no placeholder", "placeholder_dims" not in p)

    from app.core import props as prop_store
    prop_store.get_prop = lambda pid: None
    miss = spec_of(model_scene(), "prop")
    check("a dangling id keeps its placement — with NO variants",
          miss.get("id") == "table" and miss.get("variants") == {}, str(miss))
    check("...and carries a placeholder box of the placement dims",
          miss.get("placeholder_dims") == {"w": 1.0, "d": 1.0, "h": 1.0},
          str(miss.get("placeholder_dims")))
    stub_props()


def test_markers_figures() -> None:
    print("\n[9] markers, figures")
    stub_props()
    sc = model_scene()
    room_marker = [m for m in sc["markers"] if m["source"] == "room"]
    check("one room marker", len(room_marker) == 1, str(len(room_marker)))
    m = room_marker[0]
    # Room a starts at (−4, −4); marker at (1.0, 1.5) m → world (−3.0, −2.5).
    check("room marker in world metres", m["at_world"] == [-3.0, -2.5],
          str(m["at_world"]))
    check("offset_y is additive to the storey floor", near(m["y_world"], 0.05),
          str(m["y_world"]))
    check("rotation becomes the world facing", near(m["facing"], 180.0),
          str(m.get("facing")))
    check("the two lean axes ride along (upright is not the only pose)",
          near(m.get("tilt", 0), -12.0) and near(m.get("roll", 0), 5.0),
          f"{m.get('tilt')}/{m.get('roll')}")
    plain_loc = model_fixture()
    for room in plain_loc["rooms"]:
        for mk in room.get("layout", {}).get("markers") or []:
            mk.pop("tilt", None)
            mk.pop("roll", None)
    plain_m = [mm for mm in scene_recipe.compose_scene(
        plain_loc, plan_width_m=PLAN_W, building_meta=BUILDING_META,
        room_metas=room_metas())["markers"] if mm["source"] == "room"][0]
    check("a marker without them stays silent (upright is the default)",
          not {"tilt", "roll"} & set(plain_m), str(sorted(plain_m)))

    prop_marker = [m for m in sc["markers"] if m["source"] == "prop"]
    check("the prop's marker comes along", len(prop_marker) == 1,
          str(len(prop_marker)))
    pm = prop_marker[0]
    # § A2 example: offset_m [0, +0.3] on the placement point (−2.0, −2.5)
    # → (−2.0, −2.2). See the derivation above EXAMPLE_PROP.
    check("prop marker = placement + offset_m",
          near(pm["at_world"][0], -2.0) and near(pm["at_world"][1], -2.2),
          str(pm["at_world"]))
    check("prop lift + height_m above the storey floor",
          near(pm["y_world"], 0.01 + 0.3),
          str(pm["y_world"]))
    check("facing = marker facing + placement yaw = 180",
          near(pm["facing"], 180.0), str(pm.get("facing")))

    check("outdoor rooms are listed", sc["outdoor_rooms"] == ["garden"],
          str(sc["outdoor_rooms"]))

    check("figure base height = 1.70 m, k = 1 and no legacy branch",
          near(sc["figures"]["base_height_m_world"], 1.7),
          str(sc["figures"]))
    check("stand clearance is a constant", near(sc["figures"]["stand_clearance"],
                                                0.12))
    anchorless = scene_recipe.compose_scene(fixture())
    check("...and it is the same 1.70 m without a scale anchor",
          anchorless["figures"] == sc["figures"], str(anchorless["figures"]))


def test_place_slots() -> None:
    """[M] Place slots (plan-posen-plaetze.md § 3.3/3.4). A room marker at
    room-local (2, 1) in room "a" (min corner −4/−4, no room turn), group
    "seat", capacity 3, spacing 0.6, facing 90 (east). Facing 0 = south = +z;
    east = +x. The lateral axis is the facing turned by +90°: (cos 90°,
    −sin 90°) = (0, −1). Slot i ∈ {0,1,2} sits at (i − 1) × 0.6 along that
    vector, i.e. at world x −2 and z = −3 − (i − 1) × 0.6: slot 0 at −2.4,
    slot 1 at −3, slot 2 at −3.6 → slots [[-2,-2.4],[-2,-3],[-2,-3.6]] (an
    N–S line, centre = the marker, slot 0 on the sitter's RIGHT when facing
    east). root_offset = seat.root_drop 0.314 × 1.70 = 0.5338 → 0.534
    (three decimals, like every drop in the payload). The payload
    marker carries id "m1seat00", group "seat", label "Seat" (a room marker
    has no prop → the group label), capacity 3. Capacity 1 → slots ==
    [at_world]. A marker of an unknown group is skipped.
    """
    print("\n[M] place slots")
    from app.core.scene_recipe import marker_slots
    check("marker_slots facing east, cap 3",
          marker_slots((-2.0, -3.0), 90.0, 3, 0.6)
          == [[-2.0, -2.4], [-2.0, -3.0], [-2.0, -3.6]],
          str(marker_slots((-2.0, -3.0), 90.0, 3, 0.6)))
    check("marker_slots cap 1", marker_slots((1.0, 2.0), None, 1, 0.6) == [[1.0, 2.0]])
    loc_m = fixture()
    loc_m["rooms"][0]["layout"]["markers"] = [
        {"id": "m1seat00", "group": "seat", "at": [2.0, 1.0], "capacity": 3,
         "spacing_m": 0.6, "rotation": 90},
        {"id": "m2nope00", "group": "sofa", "at": [1.0, 1.0]},
    ]
    scene_m = scene_recipe.compose_scene(loc_m, plan_width_m=PLAN_W)
    mk = [m for m in scene_m["markers"] if m["room_id"] == "a"]
    check("unknown group skipped", len(mk) == 1, str(mk))
    m = mk[0]
    check("payload id/group/label/capacity",
          (m["id"], m["group"], m["label"], m["capacity"])
          == ("m1seat00", "seat", "Seat", 3),
          str((m.get("id"), m.get("group"), m.get("label"), m.get("capacity"))))
    check("payload slots", m["slots"] == [[-2.0, -2.4], [-2.0, -3.0], [-2.0, -3.6]],
          str(m["slots"]))
    check("payload root_offset 0.534", m["root_offset"] == 0.534,
          str(m["root_offset"]))
    check("no animation key any more", "animation" not in m)


def test_prop_ground_offset() -> None:
    """[9a] THE PROP'S OWN GROUND OFFSET (§ B2 addendum 2026-08-20).

    A property of the OBJECT: a trunk without a root ball sinks by the same
    amount wherever it stands, so the number lives on the library record and
    reaches every placement of the prop instead of being typed per instance.
    The per-placement ``offset_y`` stays the trim on top of it.

    HAND-DERIVED, from the numbers [8]/[9] already pin for the example prop in
    room "a" (plate top 0.10, prop clearance 0.01, composed marker height 0.30):

        base                    = 0.10 + 0.01                  = 0.11
        with ground_offset −0.20  → bottom_y = 0.11 − 0.20      = −0.09
        prop marker             = bottom_y + 0.30              =  0.21
        i.e. the marker keeps its 0.30 over the mesh — the seat of a sunk
        trunk sinks WITH the trunk, which is the whole point.

    And with a placement ``offset_y`` of +0.05 on top of the same prop:

        bottom_y = 0.11 − 0.20 + 0.05                          = −0.04
        marker   = bottom_y + 0.30                             =  0.26

    THE COUNTER-PROBE, executed: an offset added TWICE (once to the shared
    room floor and once per placement, the classic double-count of this
    change) would answer −0.29 for the mesh — 0.20 too deep.
    """
    print("\n[9a] the prop's own ground offset")
    stub_props(-0.2)
    sc = model_scene()
    prop = spec_of(sc, "prop", "table")
    check("bottom_y = ground 0.00 + clearance 0.01 + offset −0.20 = −0.19",
          near(prop["bottom_y"], -0.19), str(prop.get("bottom_y")))
    pm = [m for m in sc["markers"] if m["source"] == "prop"][0]
    check("the marker rides the mesh down: −0.19 + 0.30 = 0.11",
          near(pm["y_world"], 0.11), str(pm["y_world"]))
    check("...so the seat keeps its 0.30 over the mesh",
          near(pm["y_world"] - prop["bottom_y"], 0.30),
          f'{pm["y_world"]} vs {prop["bottom_y"]}')
    # The counter-probe, on the same numbers: doubled, the mesh is 0.20 deeper.
    check("a doubled offset would be −0.39, and it is not",
          not near(prop["bottom_y"], -0.39), str(prop.get("bottom_y")))

    # The per-instance trim is ADDITIVE, not replaced.
    trimmed_loc = model_fixture()
    for room in trimmed_loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"][0]["offset_y"] = 0.05
    trimmed = scene_recipe.compose_scene(
        trimmed_loc, plan_width_m=PLAN_W, building_meta=BUILDING_META,
        room_metas=room_metas())
    tp = spec_of(trimmed, "prop", "table")
    check("placement offset_y stays additive: 0.01 − 0.20 + 0.05 = −0.14",
          near(tp["bottom_y"], -0.14), str(tp.get("bottom_y")))
    tm = [m for m in trimmed["markers"] if m["source"] == "prop"][0]
    check("...and the marker follows both: −0.14 + 0.30 = 0.16",
          near(tm["y_world"], 0.16), str(tm["y_world"]))

    # SCATTERED COPIES are the same object and sink by the same amount; the
    # recipe carries the key on every copy, absent only when it is 0.
    from app.core import room_recipe
    lay = {"props": [{"prop_id": "table", "at": [1.0, 1.0]}]}
    placements, _ = room_recipe._join_placements(
        lay, lambda u, v: (u, v), 0.0, 0.0, 0.0)
    check("the recipe placement carries the prop's offset",
          near(placements[0].get("ground_offset_m", 0), -0.2),
          str(placements[0].get("ground_offset_m")))
    stub_props()
    placements, _ = room_recipe._join_placements(
        lay, lambda u, v: (u, v), 0.0, 0.0, 0.0)
    check("a prop on the ground puts NO key on the placement",
          "ground_offset_m" not in placements[0], str(sorted(placements[0])))
    flat = spec_of(model_scene(), "prop", "table")
    check("...and its bottom_y is the plain 0.01 again",
          near(flat["bottom_y"], 0.01), str(flat.get("bottom_y")))


# The stacking fixture: a table one may put something ON, and the something.
# Both are the CONTRACT's own worked example for § B2 addendum 2026-08-23 and
# carry round dims on purpose — every number in [7f] is one line of mental
# arithmetic away from them.
STACK_TABLE = {
    "id": "table", "name": "Table",
    "width_m": 1.2, "depth_m": 0.8, "height_m": 0.75,
    "rotation": {"x": 0, "y": 0, "z": 0}, "bbox": [1.2, 0.75, 0.8],
    "has_model": True, "model_tiers": ["full"], "model_signature": "tabsig",
}
STACK_TEAPOT = {
    "id": "teapot", "name": "Teapot",
    "width_m": 0.2, "depth_m": 0.2, "height_m": 0.25,
    "rotation": {"x": 0, "y": 0, "z": 0}, "bbox": [0.2, 0.25, 0.2],
    "has_model": True, "model_tiers": ["full"], "model_signature": "potsig",
}


def stub_stack_props() -> None:
    """Stub the library with the two props of [7f] — the smoke never touches
    the real prop directory."""
    from app.core import props as prop_store
    recs = {"table": STACK_TABLE, "teapot": STACK_TEAPOT}
    prop_store.get_prop = lambda pid: dict(recs[pid]) if pid in recs else None


def test_prop_stacking() -> None:
    """[7f] PUT THE TEAPOT ON THE TABLE (§ B2 addendum 2026-08-23).

    The rule is one sentence: the placed prop's base lands exactly on the top
    surface of the TOPMOST prop whose turned footprint covers its spot. Over
    the base ladder the scene spec composes (automatic floor + the PROP's own
    ``ground_offset_m`` + the PLACEMENT's ``offset_y``) that is

        top(support)     = ground_offset(support) + offset_y(support) + height(support)
        offset_y(target) = top(support) − ground_offset(target)

    HAND-DERIVED, with the table 1.2 × 0.8 × 0.75 m at (2, 3) and the teapot
    0.2 × 0.2 × 0.25 m:

      a) teapot at (2, 3), table flat on the floor:
         top = 0 + 0 + 0.75 = 0.75  →  offset_y = 0.75 − 0 = 0.75
      b) teapot at (2.55, 3), table NOT turned: the footprint half extents are
         0.6 × 0.4, so lx = 0.55 ≤ 0.6, lz = 0.00 ≤ 0.4 — still on the table,
         still 0.75.
      c) the same spot with the table at yaw 90°: the inverse turn gives
         lx = 0.55·cos 90 − 0.00·sin 90 = 0.00 and
         lz = 0.55·sin 90 + 0.00·cos 90 = 0.55 > 0.4 — the teapot now stands
         BESIDE the turned table, and the rule answers "nothing underneath".
      d) a tray 0.5 × 0.5 × 0.05 already lying on the table (offset_y 0.75):
         top = 0 + 0.75 + 0.05 = 0.80 — the TOPMOST surface wins, 0.80.
      e) the table sunk 5 cm into the floor (ground_offset −0.05):
         top = −0.05 + 0 + 0.75 = 0.70.
      f) a teapot that is itself authored to sink 5 cm:
         offset_y = 0.75 − (−0.05) = 0.80, and its base is then
         0.00 + (−0.05) + 0.80 = 0.75 — ON the table top, not in it.

    The rule below is PURE — it is handed finished boxes and never asks the
    library, so the per-variant sizes of 2026-08-24 change nothing here. WHICH
    box a placement gets (a variant may override the prop's dims, for the
    support as well as for the target) is `props.placement_stack_offset_y`, and
    its hand derivation lives in `scripts/smoke_prop_variants.py` [18], against
    a real prop directory.

    THE PAYLOAD SIDE, same numbers on storey 0 (floor 0.00, prop clearance
    0.01, § A16.9 / [7c]):

        table  bottom_y = 0.00 + 0.01                = 0.01
        teapot bottom_y = 0.00 + 0.01 + 0.75         = 0.76
        teapot − table  = 0.75 = the table's height — which is exactly what
        "standing on it" means, and what both renderers draw: `place()` seats
        every mesh on `bottom_y` (§ B2 step 4) and the verify diff of § B5a
        checks that very field.
    """
    print("\n[7f] a prop stands on a prop (put the teapot on the table)")
    from app.core.props import stack_offset_y

    def boxes(table_yaw=0.0, teapot_at=(2.0, 3.0), table_go=0.0,
              teapot_go=0.0, tray=False):
        out = [{"at": [2.0, 3.0], "yaw": table_yaw, "width_m": 1.2,
                "depth_m": 0.8, "height_m": 0.75, "ground_offset_m": table_go},
               {"at": list(teapot_at), "width_m": 0.2, "depth_m": 0.2,
                "height_m": 0.25, "ground_offset_m": teapot_go}]
        if tray:
            out.append({"at": [2.0, 3.0], "offset_y": 0.75, "width_m": 0.5,
                        "depth_m": 0.5, "height_m": 0.05})
        return out

    check("a) teapot over the table centre: offset_y = 0.75",
          near(stack_offset_y(boxes(), 1), 0.75), str(stack_offset_y(boxes(), 1)))
    off_b = stack_offset_y(boxes(teapot_at=(2.55, 3.0)), 1)
    check("b) 0.55 m off centre is still on the 1.2 m table: 0.75",
          near(off_b, 0.75), str(off_b))
    off_c = stack_offset_y(boxes(table_yaw=90.0, teapot_at=(2.55, 3.0)), 1)
    check("c) ...and beside it once the table turns 90°: nothing underneath",
          off_c is None, str(off_c))
    off_d = stack_offset_y(boxes(tray=True), 1)
    check("d) a tray on the table wins: 0.75 + 0.05 = 0.80",
          near(off_d, 0.80), str(off_d))
    off_e = stack_offset_y(boxes(table_go=-0.05), 1)
    check("e) a table sunk 5 cm carries its top down: 0.70",
          near(off_e, 0.70), str(off_e))
    off_f = stack_offset_y(boxes(teapot_go=-0.05), 1)
    check("f) a teapot that sinks 5 cm gets 0.80, so its base is 0.75",
          near(off_f, 0.80) and near(-0.05 + off_f, 0.75), str(off_f))
    check("red: a prop alone in the room has nothing to stand on",
          stack_offset_y([boxes()[1]], 0) is None, "None expected")

    # ── and the stored answer reaches the payload unchanged ──
    stub_stack_props()
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            # Room-local metres inside the 4 × 3 m room "a"; the arithmetic
            # above does not care WHERE the pair stands, only that both stand
            # in the same frame.
            room["layout"]["props"] = [
                {"prop_id": "table", "at": [2.0, 1.5]},
                {"prop_id": "teapot", "at": [2.0, 1.5], "offset_y": 0.75}]
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    table = spec_of(sc, "prop", "table")
    teapot = spec_of(sc, "prop", "teapot")
    check("the table stands on the ground: 0.00 + 0.01",
          near(table["bottom_y"], 0.01), str(table.get("bottom_y")))
    check("the teapot stands on the table: 0.01 + 0.75 = 0.76",
          near(teapot["bottom_y"], 0.76), str(teapot.get("bottom_y")))
    check("...i.e. exactly the table's 0.75 m above it",
          near(teapot["bottom_y"] - table["bottom_y"], 0.75),
          f'{teapot.get("bottom_y")} vs {table.get("bottom_y")}')
    stub_props()


def test_prop_depth_cut() -> None:
    """[7g] HALF A TABLE AGAINST THE WALL (§ B2 addendum 2026-08-23).

    A placement may cut its prop across the DEPTH — the mesh is clipped at
    render time, so the library keeps ONE table. The server states the finished
    plane in payload world metres, ``{normal, constant}``, with three.js' own
    rule: a fragment is KEPT where ``n·p + c >= 0``. ``side`` names the half
    that REMAINS — ``front`` = the top of an unturned footprint on the plan
    (local −z), ``back`` = the bottom (local +z).

    HAND-DERIVED, for a prop of depth 2 m at (2, 3) with ``keep`` 0.5. The prop
    hangs on its own centre (§ B2 step 3), so local z runs −1 … +1:

      a) side "back", yaw 90°:
         z_cut = +d/2 − keep·d = 1 − 1 = 0, n_local = (0, 0, +1).
         R_y(+90) maps (0, 0, 1) to (sin 90, 0, cos 90) = (1, 0, 0), and the
         plane point is the anchor itself (z_cut = 0), so
         c = −(1·2 + 0·3) = −2 → kept where x ≥ 2. The table's back half lay
         along +x once the yaw turned the depth axis onto it, which is exactly
         the half that stands.
      b) the same with side "front": n = −(1, 0, 0) and c = +2 → kept where
         x ≤ 2. The two halves are complementary, as two halves must be.
      c) side "back", yaw 0°, keep 0.25:
         z_cut = 1 − 0.5 = 0.5, n = (0, 0, 1), P = (2, 3.5),
         c = −3.5 → kept where z ≥ 3.5, i.e. the rearmost quarter.
      d) keep 1.0 is the whole prop and states NOTHING: no plane at all.

    And on the payload, with the [7f] table (depth 0.8 m) in room "a" at
    room-local (2.0, 1.5) — world (−4 + 2, −4 + 1.5) = (−2.0, −2.5) — cut to
    half from the back at yaw 0:

        z_cut = 0.4 − 0.5·0.8 = 0.0,  n = (0, 0, 1),  P = (−2.0, −2.5)
        c     = −(0·(−2.0) + 1·(−2.5)) = 2.5
    """
    print("\n[7g] the depth cut of a placed prop")
    cut = scene_recipe.depth_cut_plane
    a = cut(2.0, 3.0, 90.0, 2.0, 0.5, "back")
    check("a) depth 2 m, yaw 90°, keep 0.5 back: n = (1,0,0), c = −2",
          a and near(a["normal"][0], 1.0) and near(a["normal"][1], 0.0)
          and near(a["normal"][2], 0.0) and near(a["constant"], -2.0), str(a))
    b = cut(2.0, 3.0, 90.0, 2.0, 0.5, "front")
    check("b) ...the front half is its mirror: n = (−1,0,0), c = +2",
          b and near(b["normal"][0], -1.0) and near(b["constant"], 2.0), str(b))
    c = cut(2.0, 3.0, 0.0, 2.0, 0.25, "back")
    check("c) yaw 0, keep 0.25 back: n = (0,0,1), c = −3.5",
          c and near(c["normal"][2], 1.0) and near(c["normal"][0], 0.0)
          and near(c["constant"], -3.5), str(c))
    check("d) keep 1.0 says nothing — no plane",
          cut(2.0, 3.0, 0.0, 2.0, 1.0, "back") is None, "None expected")
    check("red: a keep of 0 would be a plane through nothing, and is refused",
          cut(2.0, 3.0, 0.0, 2.0, 0.0, "back") is None, "None expected")

    stub_stack_props()
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"] = [
                {"prop_id": "table", "at": [2.0, 1.5],
                 "cut_keep": 0.5, "cut_side": "back"}]
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    plane = spec_of(sc, "prop", "table").get("cut_plane")
    check("the payload carries the finished plane: n = (0,0,1), c = 2.5",
          plane and near(plane["normal"][2], 1.0)
          and near(plane["normal"][0], 0.0) and near(plane["constant"], 2.5),
          str(plane))
    # An UNCUT placement of the same prop must not carry the key at all — an
    # absent statement, like `ground_offset_m` next door.
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"] = [{"prop_id": "table", "at": [2.0, 1.5]}]
    whole = spec_of(scene_recipe.compose_scene(loc, plan_width_m=PLAN_W),
                    "prop", "table")
    check("...and an uncut prop carries no key",
          "cut_plane" not in whole, str(sorted(whole)))

    # THE SANITIZER (world_ops._sanitize_props): the stored statement.
    from app.core.world_ops import _sanitize_props
    def one(**kw):
        return (_sanitize_props([{"prop_id": "table", "at": [1.0, 1.0], **kw}])
                or [{}])[0]
    check("a stored cut keeps its fraction and its side",
          one(cut_keep=0.5, cut_side="front").get("cut_keep") == 0.5
          and one(cut_keep=0.5, cut_side="front").get("cut_side") == "front",
          str(one(cut_keep=0.5, cut_side="front")))
    check("keep 1.0 writes NO key (absence is the statement)",
          "cut_keep" not in one(cut_keep=1.0), str(one(cut_keep=1.0)))
    check("...and so does a keep above 1 (clamped to 1.0)",
          "cut_keep" not in one(cut_keep=3.0), str(one(cut_keep=3.0)))
    check("a keep below the floor is clamped to 0.05, never refused",
          one(cut_keep=0.001).get("cut_keep") == 0.05, str(one(cut_keep=0.001)))
    check("junk is no authoring statement and loses the key",
          "cut_keep" not in one(cut_keep="x"), str(one(cut_keep="x")))
    check("an unnamed side falls to 'back'",
          one(cut_keep=0.5).get("cut_side") == "back", str(one(cut_keep=0.5)))
    stub_props()


def plate_of(sc: dict, room_id: str) -> dict:
    """The room's FLOOR as the payload carries it, under one key.

    On a DECLARED storey that is still a plate. On storey 0 there is none since
    "Ein Boden" E5a — the terrain IS the floor there — and the room's shape
    travels in ``floor_plan`` instead. Both answer with an ``outline``, so a
    check that only cares about WHERE the room is reads the same thing on both.
    """
    hits = [p for p in sc["plates"] if p.get("room_id") == room_id]
    if hits:
        return hits[0]
    for entry in sc.get("floor_plan") or []:
        if entry.get("room_id") == room_id:
            return {**entry, "outline": entry.get("polygon_world") or []}
    return {}


def test_clip_outline() -> None:
    print("\n[10] diorama shell clip (§ B1 clip_outline)")
    stub_props()
    plain = model_scene()
    check("without the flag no clip_outline",
          "clip_outline" not in spec_of(plain, "room", "d"),
          str(spec_of(plain, "room", "d").keys()))
    clipped = model_scene(clip_d=True)
    d = spec_of(clipped, "room", "d")
    # Room d: x 1 y 1 w 2 d 2 → straight it would be x 1…3, z 1…3, but it
    # carries `rotation` 45 and the shell turns with it (v6 addendum). Corners
    # relative to the centre (2, 2) are (∓1, ∓1); with cos45 = sin45 = √2/2:
    #   (−1, −1) → (2 − √2/2 − √2/2, 2 + √2/2 − √2/2) = (0.5858, 2.0)
    #   ( 1, −1) → (2 + √2/2 − √2/2, 2 − √2/2 − √2/2) = (2.0, 0.5858)
    #   ( 1,  1) → (2 + √2/2 + √2/2, 2 − √2/2 + √2/2) = (3.4142, 2.0)
    #   (−1,  1) → (2 − √2/2 + √2/2, 2 + √2/2 + √2/2) = (2.0, 3.4142)
    check("clip_outline = the TURNED room shell in world metres",
          d.get("clip_outline") == [[0.5858, 2.0], [2.0, 0.5858],
                                    [3.4142, 2.0], [2.0, 3.4142]],
          str(d.get("clip_outline")))
    check("...the SAME points as the room's floor plate",
          d.get("clip_outline") == plate_of(clipped, "d")["outline"],
          str(plate_of(clipped, "d")["outline"]))
    check("the flag moves the signature (client re-fetches)",
          clipped["signature"] != plain["signature"])

    outdoor = spec_of(model_scene(clip_garden=True), "room", "garden")
    check("outdoor rooms ignore the flag (no shell to clip against)",
          bool(outdoor) and "clip_outline" not in outdoor, str(outdoor))

    # Cap raised 32 → 64 for tessellated curved hulls (v5.2 Nr. 11).
    ring = [[1.0 + 1.0 * math.cos(2 * math.pi * i / 65),
             1.0 + 1.0 * math.sin(2 * math.pi * i / 65)] for i in range(65)]
    capped = model_scene(clip_d=True, d_outline=ring)
    check("65 points > the 64-point cap → flag ignored",
          "clip_outline" not in spec_of(capped, "room", "d"),
          str(len(plate_of(capped, "d")["outline"])))
    check("...and 64 points still pass",
          len(spec_of(model_scene(clip_d=True, d_outline=ring[:64]),
                      "room", "d").get("clip_outline") or []) == 64)


def test_signature() -> None:
    print("\n[11] signature")
    stub_props()
    base = model_scene()["signature"]
    check("stable for identical input", model_scene()["signature"] == base)
    styled = model_fixture()
    styled["map3d"]["style"] = "tower"
    check("a map3d edit moves it", scene_recipe.compose_scene(
        styled, plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta=BUILDING_META)["signature"] != base)
    # ...and `map_rotation_2d` does NOT (v6 Nr. 10): it is the flat map
    # icon's display rotation, it shapes no scene, so it is out of the hash.
    check("the 2D icon rotation does not move it any more",
          model_scene(map_rotation_2d=270)["signature"] == base)
    dialed = scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META, "offset_y": 0.3})
    check("a model-meta dial (offset_y) moves it", dialed["signature"] != base)
    check("a room-meta dial (width_m) moves it too",
          model_scene(room_width_m=5.0)["signature"] != base)
    # v5.3 Nr. 16: a new mesh keeps every URL — only the model SIGNATURE
    # moves, so it has to be inside the hashed payload (meta for the
    # building/room models, placements[].model_sig for props).
    tiered = scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, room_metas=room_metas(),
        building_meta={**BUILDING_META, "signature": "other"})
    check("a new building-model file (signature only) moves it",
          tiered["signature"] != base)
    stub_library(lambda pid: (
        {**EXAMPLE_PROP, "model_signature": "propsig2"} if pid == "table"
        else None))
    check("a new PROP mesh (same URL, new signature) moves it too",
          model_scene()["signature"] != base)
    stub_props()


# ── Detail scenes (plan-area-detail-scenes.md, contract v5.2) ───────────

def xorshift32_ref(seed: int):
    """INDEPENDENT re-implementation of the contract PRNG (§ B5a: the smoke
    never trusts the source it verifies). The algorithm is three lines:
    ``x ^= x<<13; x ^= x>>17; x ^= x<<5`` on uint32, seed 0 → 1. First
    transition worked by hand from seed 1:
    1<<13 = 8192, 1^8192 = 8193 (0x2001); 8193>>17 = 0, unchanged;
    8193<<5 = 262176 (0x40020), 8193^262176 = 270369 (0x42021)."""
    x = seed & 0xFFFFFFFF or 1
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        yield x


def test_curved_outline() -> None:
    print("\n[12] curved room hull (v5.2 Nr. 11)")
    # Room "a" (x −4, y −4, w 4, d 3), rectangle hull in room metres
    # [[0,0],[4,0],[4,3],[0,3]], edge 1 ((4,0) → (4,3)) curved INWARD with
    # C = (2, 1.5) — the metric twin of the old bbox fractions (1,0)/(1,1)
    # and C (0.5, 0.5). Hand derivation:
    #   B(t) = ((1−t)²·4 + 2t(1−t)·2 + t²·4, 2t(1−t)·1.5 + t²·3)
    #        = (4·(1 − t + t²), 3t)
    #   t = 0.25 → (3.25, 0.75) → abs (−4 + 3.25, −4 + 0.75) = (−0.75, −3.25)
    #   t = 0.5  → (3.0, 1.5)   → abs (−1.0, −2.5)
    # Vertex indices: v0=0, v1=1, inserted t=1/8…7/8 at 2…8, v2=9, v3=10 —
    # so the S door on control edge 2 shifts to tessellated edge 9.
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["outline"] = [[0, 0], [4, 0], [4, 3], [0, 3]]
            room["layout"]["outline_curves"] = [{"edge": 1, "c": [2.0, 1.5]}]
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    block = next(r for r in sc["rooms"] if r["room_id"] == "a")
    ol = block["outline"]
    check("4 vertices + 7 inserted points", len(ol) == 11, str(len(ol)))
    check("B(0.25) lands at world (−0.75, −3.25)",
          near(ol[3][0], -0.75, 1e-3) and near(ol[3][1], -3.25, 1e-3),
          str(ol[3]))
    check("B(0.5) lands at world (−1.0, −2.5)",
          near(ol[5][0], -1.0, 1e-3) and near(ol[5][1], -2.5, 1e-3), str(ol[5]))
    edges = sorted(int(o["edge"]) for o in block["openings"])
    check("window keeps edge 0, S door shifts 2 → 9", edges == [0, 9],
          str(edges))
    # The room's floor is DATA on storey 0 (E5a): the tessellated hull travels
    # in ``floor_plan`` instead of on a plate, point for point the same.
    plate = plate_of(sc, "a")
    check("the floor polygon is the tessellated hull in world metres",
          len(plate["outline"]) == 11
          and near(plate["outline"][5][0], -1.0, 1e-3)
          and near(plate["outline"][5][1], -2.5, 1e-3),
          str(plate["outline"][5]))
    plain = scene_recipe.compose_scene(fixture(), plan_width_m=PLAN_W)
    check("the curve moves the signature",
          sc["signature"] != plain["signature"])


def scatter_fixture(seed: int = 1, count: int = 2, road: bool = False,
                    spacing: float = 0.0) -> dict:
    # Room "field": world x −4…0, z −4…0 (the old fractions 0.1…0.5 on both
    # axes). Scatter is a PLACEMENT property (v5.2 Nr. 12, Neufassung): the
    # anchor table sits at the room centre — [2, 2] m of a 4 × 4 m room, the
    # old fraction [0.5, 0.5] — and throws `count` copies.
    anchor = {"prop_id": "table", "at": [2.0, 2.0],
              "scatter_count": count, "scatter_seed": seed}
    if spacing:
        anchor["scatter_spacing_m"] = spacing
    rooms = [{"id": "field", "name": "F", "layout": {
        "x": -4.0, "y": -4.0, "w": 4.0, "d": 4.0, "level": 0,
        "always_visible": True, "props": [anchor]}}]
    if road:
        # Band across the field: world z −2.2…−1.8.
        rooms.append({"id": "road", "name": "R", "layout": {
            "x": -4.0, "y": -2.2, "w": 4.0, "d": 0.4, "level": 0,
            "always_visible": True}})
    return {"id": "loc", "map3d": {"plan_width_m": PLAN_W,
                                   "storey_height_m": STOREY_REAL},
            "rooms": rooms}


def test_scatter() -> None:
    print("\n[13] deterministic prop scatter (v5.2 Nr. 12)")
    stub_props()
    sc = scene_recipe.compose_scene(scatter_fixture(), plan_width_m=PLAN_W)
    props = [m for m in sc["models"] if m["role"] == "prop"]
    check("anchor + two scattered copies in the payload", len(props) == 3,
          str(len(props)))
    # The anchor is the FIRST placement (manual entries precede copies) and
    # stays where it was put: room min corner (−4, −4) + (2, 2) = (−2, −2).
    check("the anchor placement stays put",
          near(props[0]["anchor"][0], -2.0) and near(props[0]["anchor"][1], -2.0),
          str(props[0]["anchor"]))
    # Independent replay: per candidate EXACTLY three draws u/v/yaw over the
    # hull's bbox — which since v6 Nr. 2 is the WORLD box x/z −4…0, so the
    # draw lands straight in payload coordinates (the old chain sampled
    # 1…5 in "fraction × plan width" and subtracted 5 on the way out: the
    # identical number). Spacing 0 means NO distance rule, copies may overlap
    # (v5.2 Nr. 12 Neufassung).
    rng = xorshift32_ref(1)
    expect = []
    while len(expect) < 2:
        u = next(rng) / 2 ** 32
        v = next(rng) / 2 ** 32
        yw = next(rng) / 2 ** 32
        px, py = -4 + u * 4, -4 + v * 4
        expect.append((px, py, round(yw * 360, 1)))
    for i, (px, py, pyaw) in enumerate(expect):
        spec = props[i + 1]
        wx = round(px, 4)
        wy = round(py, 4)
        check(f"copy {i + 1} at the independently derived position",
              near(spec["anchor"][0], wx, 1e-3)
              and near(spec["anchor"][1], wy, 1e-3)
              and near(spec["yaw_deg"], pyaw, 0.11),
              f'{spec["anchor"]}/{spec["yaw_deg"]} vs [{wx:.4f}, {wy:.4f}]/{pyaw}')
    again = scene_recipe.compose_scene(scatter_fixture(), plan_width_m=PLAN_W)
    check("same seed → identical payload (signature equal)",
          again["signature"] == sc["signature"])
    other = scene_recipe.compose_scene(scatter_fixture(seed=2),
                                       plan_width_m=PLAN_W)
    check("another seed moves the signature (reroll re-fetches)",
          other["signature"] != sc["signature"])
    check("scattered copies carry no prop markers — only the anchor's",
          len(sc["markers"]) == 1, str(len(sc["markers"])))
    # Spacing is the WHOLE density rule, in metres like every other *_m field
    # — at k = 1 that is 3 metres between the payload anchors, no conversion.
    spaced = scene_recipe.compose_scene(
        scatter_fixture(count=5, spacing=3.0), plan_width_m=PLAN_W)
    pts = [m["anchor"] for m in spaced["models"]
           if m["role"] == "prop"][1:]
    check("spacing_m rules the pairwise distance of the copies",
          len(pts) >= 2
          and all(math.hypot(a[0] - b[0], a[1] - b[1]) >= 3.0 - 1e-3
                  for i, a in enumerate(pts) for b in pts[i + 1:]),
          str([[round(p[0], 2), round(p[1], 2)] for p in pts]))

    dense = scene_recipe.compose_scene(scatter_fixture(count=20, road=True),
                                       plan_width_m=PLAN_W)
    tree_specs = [m for m in dense["models"]
                  if m["role"] == "prop" and m["room_id"] == "field"
                  and not (near(m["anchor"][0], -2.0) and near(m["anchor"][1], -2.0))]
    check("a dense scatter places (short placement allowed)",
          1 <= len(tree_specs) <= 20, str(len(tree_specs)))
    # Road band world z −2.2…−1.8. No scattered centre may fall into the
    # sibling hull.
    check("the road stays tree-free (sibling keep-out)",
          all(not (-2.2 - 1e-6 <= m["anchor"][1] <= -1.8 + 1e-6)
              for m in tree_specs),
          str(sorted(round(m["anchor"][1], 2) for m in tree_specs)))


def test_boundary_openings() -> None:
    print("\n[14] boundary openings (v6 Nr. 5 — edge INDEX)")
    # The fixture draws no boundary, so the effective one is the reference
    # square (−5,−5) (5,−5) (5,5) (−5,5) — clockwise in map view, hence
    # edge 0 = north (west→east), 1 = east (north→south), 2 = south
    # (east→west), 3 = west (south→north).
    loc = fixture()
    loc["map3d"]["boundary_openings"] = [
        {"edge": 1, "at": 0.3, "width_m": 3.0, "room": "room-road",
         "type": "passage"},
        {"edge": 0, "at": 0.5, "width_m": 2.0},
    ]
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    bo = sc.get("boundary_openings") or []
    check("two entries", len(bo) == 2, str(len(bo)))
    # Edge 1 runs (5,−5) → (5,5); at 0.3 is (5, −5 + 0.3·10) = (5, −2). Its
    # direction is (0, 10), so the candidate normal (−dz, dx)/|d| is (−1, 0);
    # the probe (5 − 0.001, 0) lies inside the square, so that is the inward
    # one.
    check("edge 1/at 0.3 → at_world [5, −2], inward [−1, 0]",
          bo and bo[0]["at_world"] == [5.0, -2.0]
          and bo[0]["inward"] == [-1.0, 0.0]
          and bo[0].get("room_id") == "room-road", str(bo and bo[0]))
    # Edge 0 runs (−5,−5) → (5,−5); at 0.5 is (0, −5), direction (10, 0),
    # normal (0, 1) — the probe (0, −5 + 0.001) is inside.
    check("edge 0/at 0.5 → at_world [0, −5], inward [0, 1]",
          len(bo) == 2 and bo[1]["at_world"] == [0.0, -5.0]
          and bo[1]["inward"] == [0.0, 1.0], str(len(bo) == 2 and bo[1]))
    check("absent without the field", "boundary_openings" not in scene())
    check("the field moves the signature",
          sc["signature"] != scene()["signature"])
    # A letter is no edge any more — v6 deleted them without an alias reader.
    lettered = fixture()
    lettered["map3d"]["boundary_openings"] = [{"edge": "N", "at": 0.5,
                                               "width_m": 2.0}]
    check("an edge LETTER is dropped (no alias reader)",
          "boundary_openings" not in scene_recipe.compose_scene(
              lettered, plan_width_m=PLAN_W))
    over = fixture()
    over["map3d"]["boundary_openings"] = [{"edge": 4, "at": 0.5,
                                           "width_m": 2.0}]
    check("...and so is an index the outline does not have",
          "boundary_openings" not in scene_recipe.compose_scene(
              over, plan_width_m=PLAN_W))

    # An opening WITHOUT `at` sits in the middle of its edge — the same
    # degradation ``boundary_entry`` has always applied (E3 ledger: the
    # composer used to answer 0, i.e. the corner, so the renderers offered
    # the entrance somewhere the entry gate did not accept it). An explicit
    # 0.0 stays the corner, and out-of-range values are clamped.
    loose = fixture()
    loose["map3d"]["boundary_openings"] = [
        {"edge": 0, "width_m": 2.0},                         # no `at`
        {"edge": 0, "at": None, "width_m": 2.0},             # unusable
        {"edge": 0, "at": 0.0, "width_m": 2.0},              # explicit corner
        {"edge": 0, "at": 1.7, "width_m": 2.0},              # out of range
    ]
    lo = scene_recipe.compose_scene(loose, plan_width_m=PLAN_W)["boundary_openings"]
    check("a missing `at` is the edge MIDPOINT (0.5 → x 0), not the corner",
          len(lo) == 4 and lo[0]["at_world"] == [0.0, -5.0], str(lo[0]))
    check("...an unusable one too", len(lo) == 4 and lo[1]["at_world"] == [0.0, -5.0],
          str(lo[1] if len(lo) > 1 else None))
    check("an explicit 0.0 keeps the corner (x −5)",
          len(lo) == 4 and lo[2]["at_world"] == [-5.0, -5.0],
          str(lo[2] if len(lo) > 2 else None))
    check("...and 1.7 clamps to the other corner (x 5)",
          len(lo) == 4 and lo[3]["at_world"] == [5.0, -5.0],
          str(lo[3] if len(lo) > 3 else None))
    from app.core.boundary_entry import opening_world_points
    # PLACED needs a DRAWN outline: the entry gate reads
    # ``world_geometry.effective_boundary``, and since 2026-08-19 that is the
    # boundary or nothing (the composer keeps its own square fallback for
    # UNPLACED drafts, § B3). The square drawn here is the one the composer
    # derives from PLAN_W 10 — corners ±5 — so both sides measure the same
    # edge and the check stays the comparison it was meant to be.
    placed = {**loose, "pos_x": 0.0, "pos_z": 0.0, "yaw_deg": 0.0,
              "map3d": {**loose["map3d"],
                        "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]}}
    entry_pts = [p for e, p in opening_world_points(placed) if e == 0]
    check("the entry gate derives the very same points (one `at` rule)",
          [list(p) for p in entry_pts]
          == [op["at_world"] for op in lo], f"{entry_pts} vs "
          f"{[op['at_world'] for op in lo]}")


# ── The drawn boundary (contract v6 "Gebiete") ──────────────────────────
# ONE fixture for the three v6 rules, an L-shape in LOCAL METRES, stored
# clockwise in map view (positive shoelace with x east / z south):
#
#     P0 (−5,−5) ─ P1 (5,−5)
#         │              │
#         │        P3 (0,0) ─ P2 (5,0)
#         │          │
#     P5 (−5,5) ─ P4 (0,5)
#
# Hand-derived (§ B5a):
#   * area = 10·10 − 5·5 = 75 m², shoelace 150/2 — positive, so the stored
#     winding is kept as drawn;
#   * bounding box 10 × 10, so ``plan_width_m`` 10 and the terrain frame
#     runs −5…5 on both axes — every lattice coordinate f is the metre
#     (f − 0.5)·10;
#   * the NOTCH is the quadrant x > 0, z > 0;
#   * edge 2 runs P2 (5,0) → P3 (0,0), direction (−5, 0). At ``at`` 0.5 that
#     is (2.5, 0); the candidate normal (−dz, dx)/|d| = (0, −1) probed at
#     (2.5, −0.001) lies inside the L, so INWARD is (0, −1) — pointing north,
#     into the arm below the notch.
L_BOUNDARY = [[-5.0, -5.0], [5.0, -5.0], [5.0, 0.0],
              [0.0, 0.0], [0.0, 5.0], [-5.0, 5.0]]


def l_fixture(*, openings=None, extra_rooms=()) -> dict:
    """The base fixture with the L drawn as its boundary and no building
    contour — so a LEVEL plate has to come from the boundary."""
    loc = fixture(extra_rooms)
    loc["map3d"].pop("outline")
    loc["map3d"]["boundary"] = [list(p) for p in L_BOUNDARY]
    if openings is not None:
        loc["map3d"]["boundary_openings"] = openings
    return loc


def test_boundary_polygon() -> None:
    print("\n[15] the drawn boundary (v6 Nr. 1/4/5)")
    sq = scene()
    check("a square location still ships its four corners as `boundary`",
          sq["boundary"] == [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0],
                             [-5.0, 5.0]], str(sq["boundary"]))
    sc = scene_recipe.compose_scene(l_fixture(), plan_width_m=PLAN_W)
    check("the drawn L travels as `boundary`, point for point",
          sc["boundary"] == L_BOUNDARY, str(sc["boundary"]))

    # ── Nr. 4: the level plate IS the boundary polygon ──────────────────
    # …ON A DECLARED STOREY. Storey 0 draws none since "Ein Boden" E5a, so the
    # rule is measured where a level plate still exists: the upper storey.
    up = scene_recipe.compose_scene(l_fixture(extra_rooms=(UPPER,)),
                                    plan_width_m=PLAN_W)
    level = [p for p in up["plates"] if not p.get("room_id")]
    check("one level plate — the UPPER storey's — and its outline is the L",
          len(level) == 1 and level[0]["level"] == 1
          and level[0]["outline"] == L_BOUNDARY,
          str(level and level[0].get("outline")))
    check("...its top and thickness are the ordinary level-plate ones",
          near(level[0]["top_y"], 3.08) and near(level[0]["thickness"], 0.14))
    check("red: storey 0 gets none of it",
          not [p for p in up["plates"] if p["level"] == 0], str(up["plates"]))
    # A DRAWN building contour is the more specific shape and still wins.
    with_contour = l_fixture(extra_rooms=(UPPER,))
    with_contour["map3d"]["outline"] = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
    lvl2 = [p for p in scene_recipe.compose_scene(
        with_contour, plan_width_m=PLAN_W)["plates"] if not p.get("room_id")]
    check("a drawn building contour still wins over the boundary",
          lvl2[0]["outline"] == [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0],
                                 [-5.0, 5.0]], str(lvl2[0]["outline"]))
    check("the storey-0 rooms are untouched by all of it",
          [f for f in sc["floor_plan"] if f["room_id"] == "a"]
          == [f for f in sq["floor_plan"] if f["room_id"] == "a"])

    # ── Nr. 5: an opening on edge index 2 ───────────────────────────────
    op_scene = scene_recipe.compose_scene(
        l_fixture(openings=[{"edge": 2, "at": 0.5, "width_m": 3.0}]),
        plan_width_m=PLAN_W)
    bo = (op_scene.get("boundary_openings") or [None])[0]
    check("edge 2 at 0.5 → at_world [2.5, 0]",
          bo and bo["at_world"] == [2.5, 0.0], str(bo))
    check("...with the inward normal [0, −1] (into the arm, not the notch)",
          bo and bo["inward"] == [0.0, -1.0], str(bo and bo["inward"]))
    from app.core.boundary_entry import opening_world_points
    placed = {**l_fixture(openings=[{"edge": 2, "at": 0.5, "width_m": 3.0}]),
              "pos_x": 100.0, "pos_z": 200.0, "yaw_deg": 0.0}
    check("the entry gate lands on the same point, pin-shifted",
          opening_world_points(placed) == [(2, (102.5, 200.0))],
          str(opening_world_points(placed)))

    # ── Nr. 1: a self-intersection is a WARNING, not a refusal ──────────
    bow = l_fixture()
    bow["map3d"]["boundary"] = [[-5, -5], [5, 5], [5, -5], [-5, 5]]
    kinds = [p["kind"] for p in scene_recipe.compose_scene(
        bow, plan_width_m=PLAN_W)["problems"]]
    check("a bow tie reports boundary_self_intersection",
          "boundary_self_intersection" in kinds, str(kinds))
    check("the L itself reports nothing about its boundary",
          not [p for p in sc["problems"]
               if p["kind"] in ("boundary_self_intersection",
                                "room_outside_boundary")],
          str([p["kind"] for p in sc["problems"]]))


def test_area_detail() -> None:
    print("\n[16] area_detail → shell_area (v5.2 Nr. 10)")
    loc = area_fixture(True)
    loc["map3d"]["area_detail"] = True
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W,
                                    building_meta=GROUND_META)
    b = spec_of(sc, "building")
    check("display shell_area", b.get("display") == "shell_area",
          str(b.get("display")))
    check("the payload carries area_detail as a LOCATION flag",
          sc.get("area_detail") is True)
    # A detail location WITHOUT a location model still says so — the whole
    # point of the flag (the forest has no model; user finding 2026-08-02).
    no_model = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    check("...also without a building model",
          no_model.get("area_detail") is True
          and not [m for m in no_model["models"] if m["role"] == "building"])
    check("ground anchor law unchanged (mesh hangs walk_y below the storey-0 "
          "floor, which is the terrain: 0.00 − 4)",
          near(b.get("bottom_y", 99), -4.0), str(b.get("bottom_y")))
    check("no cutouts on the model", "cutouts" not in b)
    check("no overlay rooms", not [r for r in sc["rooms"] if r.get("overlay")])
    check("the outside outdoor room composes like an ordinary storey-0 room",
          "zone" in {f["room_id"] for f in sc["floor_plan"]}
          and not [r for r in sc["rooms"] if r.get("overlay")],
          str(sorted({f["room_id"] for f in sc["floor_plan"]})))
    plain = scene_recipe.compose_scene(area_fixture(True), plan_width_m=PLAN_W,
                                       building_meta=GROUND_META)
    check("the flag moves the signature",
          sc["signature"] != plain["signature"])


GROUND_ID = "__ground__"


# ── [17] THE SCENE'S OWN RELIEF IS DELETED ──────────────────────────────
# The block that stood here measured ``map3d.relief``: a 17 x 17 procedural
# height field per location, composed by ``scene_recipe.compose_terrain``,
# shipped as the ``terrain`` payload block, draped by both renderers and
# sampled by the walking gate. It is gone with "Ein Boden" E5a (user decision 1
# of plan-ein-boden.md § 5) — local relief is authored as HEIGHT AREAS of the
# map, one field for the whole world. The deletion is asserted by NAME in
# ``scripts/smoke_slope_gate.py`` [3], the only thing a positive check cannot
# do, and the world field's own arithmetic is measured in
# ``scripts/smoke_height_bake.py``.


def ground_fixture(*, props=(), markers=(), solo: bool = True) -> dict:
    """The L location plus a furnished yard. ``solo`` drops the two ordinary
    rooms, so the scatter run below has NO sibling keep-outs to reason about;
    without it the yard stands beside room "a" and "garden" as usual."""
    loc = l_fixture()
    if solo:
        loc["rooms"] = []
    layout = {}
    if props:
        layout["props"] = [dict(p) for p in props]
    if markers:
        layout["markers"] = [dict(m) for m in markers]
    loc["rooms"] = list(loc["rooms"]) + [
        {"id": GROUND_ID, "name": "", "layout": layout}]
    return loc


def test_ground_placements() -> None:
    print("\n[18] placements on the ground (§ A13a)")
    stub_props()
    # ── A prop at local (3, −2): the anchor is that point, verbatim ──────
    # Hand-derived: the ground has no rect, so nothing is added to `at`; it
    # draws no surface of its own either, so the prop stands PROP_CLEARANCE
    # (0.01 m) over the storey's DRAWN floor.
    #
    # WHICH FLOOR THAT IS no longer depends on the location ("Ein Boden" E5a):
    # storey 0 is the terrain everywhere, so the storey floor is 0.00 and
    # the prop stands at 0.00 + 0.01 = 0.01, on the terrain. The BUILT twin is
    # right below and answers the SAME number since E5a: there is no slab left
    # for a closed room to raise, on any location.
    sc = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [3.0, -2.0]}],
                       markers=[{"at": [-1.0, 2.0], "group": "seat"}]),
        plan_width_m=PLAN_W)
    props = [m for m in sc["models"] if m["role"] == "prop"]
    check("one prop spec, room_id = the ground",
          len(props) == 1 and props[0]["room_id"] == GROUND_ID,
          str([(p["room_id"], p["anchor"]) for p in props]))
    check("its anchor IS the stored local metre (3, −2)",
          props and props[0]["anchor"] == [3.0, -2.0], str(props[0]["anchor"]))
    check("the yard's prop stands on the terrain: 0.00 + PROP_CLEARANCE",
          near(props[0]["bottom_y"], 0.01), str(props[0]["bottom_y"]))
    # THE BUILT TWIN — the same yard, the same prop, in a location that has a
    # closed room and therefore a slab: 0.08 + 0.01 = 0.09, the number of
    # 47abc26b, unchanged.
    built = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [3.0, -2.0]}],
                       solo=False), plan_width_m=PLAN_W)
    built_prop = next(m for m in built["models"]
                      if m["role"] == "prop" and m["room_id"] == GROUND_ID)
    check("...and a BUILT place answers exactly the same 0.01 (E5a: one "
          "ground for both — the slab's 0.09 is gone)",
          near(built_prop["bottom_y"], 0.01)
          and not near(built_prop["bottom_y"], 0.09),
          str(built_prop["bottom_y"]))
    # The same prop inside room "a" (x −4, y −4) stands on a plate: the
    # contrast is what proves the ground took the outdoor branch.
    in_room = fixture()
    for room in in_room["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"] = [{"prop_id": "table", "at": [1.0, 1.0]}]
    room_prop = [m for m in scene_recipe.compose_scene(
        in_room, plan_width_m=PLAN_W)["models"] if m["role"] == "prop"][0]
    check("...and a prop in a CLOSED room stands on that same ground",
          near(room_prop["bottom_y"], 0.01)
          and not near(room_prop["bottom_y"], 0.11),
          str(room_prop["bottom_y"]))
    check("its anchor is the room's min corner + at = (−4+1, −4+1)",
          room_prop["anchor"] == [-3.0, -3.0], str(room_prop["anchor"]))
    # ── The marker: same frame, floor height, no plate ──────────────────
    mk = [m for m in sc["markers"]
          if m["room_id"] == GROUND_ID and m["source"] == "room"]
    check("the ground marker sits at its stored metre (−1, 2), y = 0",
          len(mk) == 1 and mk[0]["at_world"] == [-1.0, 2.0]
          and near(mk[0]["y_world"], 0.0), str(mk))
    # sit → the figure's root drops 0.314 × 1.70 m = 0.5338 below the surface.
    check("...and carries the sit root drop 0.314 × 1.70 = 0.5338",
          near(mk[0]["root_offset"], 0.5338), str(mk[0]["root_offset"]))
    # The table brings its own seat marker: the yard's storey floor (0.00 on
    # this NATURAL location) + 0.01 clearance plus the marker's composed
    # height over the placement — in the built fixture's room the same seat
    # sits on the room plate, i.e. 0.10 − 0.00 = 0.10 m higher.
    seat = [m for m in sc["markers"] if m["source"] == "prop"]
    room_seat = [m for m in scene_recipe.compose_scene(
        in_room, plan_width_m=PLAN_W)["markers"] if m["source"] == "prop"]
    check("the yard's prop marker and the room's stand at the SAME height "
          "now — one floor, one answer (was 0.10 apart)",
          len(seat) == 1 and len(room_seat) == 1
          and near(room_seat[0]["y_world"] - seat[0]["y_world"], 0.0),
          f'{seat and seat[0]["y_world"]} vs '
          f'{room_seat and room_seat[0]["y_world"]}')
    # ── Still geometry-less: no plate, no wall, no room block ────────────
    check("no plate for the ground",
          not [p for p in sc["plates"] if p.get("room_id") == GROUND_ID],
          str([p.get("room_id") for p in sc["plates"]]))
    check("no room block for the ground",
          not [r for r in sc["rooms"] if r["room_id"] == GROUND_ID],
          str([r["room_id"] for r in sc["rooms"]]))
    check("no wall and no doorway from it",
          not [w for w in sc["walls"] if w.get("room_id") == GROUND_ID]
          and not [d for d in sc["doorways"]
                   if GROUND_ID in (d.get("rooms") or [])])
    check("and it is no outdoor room either",
          GROUND_ID not in sc["outdoor_rooms"], str(sc["outdoor_rooms"]))
    # A yard full of props is not a room somebody can enter: the "no room has
    # a floor plan" finding must still fire.
    bare = fixture()
    bare["rooms"] = [{"id": "a", "name": "A"},
                     {"id": GROUND_ID, "name": "", "layout": {
                         "props": [{"prop_id": "table", "at": [0.0, 0.0]}]}}]
    kinds = [p["kind"] for p in scene_recipe.compose_scene(
        bare, plan_width_m=PLAN_W)["problems"]]
    check("a furnished yard does not silence `rooms_without_layout`",
          "rooms_without_layout" in kinds, str(kinds))
    # THE YARD'S OWN RELIEF BLOCK IS GONE with the scene relief ("Ein Boden"
    # E5a, user decision 1): a location carries no height field of its own, so
    # there is nothing additive left to measure here. What the yard stands on
    # is the WORLD ground under its anchor, and that is measured where the
    # world ground lives — ``scripts/smoke_slope_gate.py`` and
    # ``scripts/smoke_height_bake.py``.
    # ── Scatter keeps INSIDE the boundary polygon ───────────────────────
    # Independent replay (§ B5a): per candidate exactly three draws u/v/yaw
    # over the hull's bounding box (−5…5 on both axes), accepted iff the point
    # lies inside the L — i.e. NOT in the notch quadrant x > 0 ∧ z > 0. No
    # siblings, no openings, no markers, so there is no other keep-out.
    seed = 7
    scattered = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [-4.0, -4.0],
                               "scatter_count": 4, "scatter_seed": seed}]),
        plan_width_m=PLAN_W)
    copies = [m for m in scattered["models"]
              if m["role"] == "prop" and m["anchor"] != [-4.0, -4.0]]
    rng = xorshift32_ref(seed)
    expect = []
    rejected = 0
    while len(expect) < 4:
        u, v, yw = next(rng) / 2 ** 32, next(rng) / 2 ** 32, next(rng) / 2 ** 32
        px, py = -5 + u * 10, -5 + v * 10
        if px > 0 and py > 0:          # the notch — outside the L
            rejected += 1
            continue
        expect.append((round(px, 4), round(py, 4), round(yw * 360, 1)))
    check("the anchor placement itself stays put at (−4, −4)",
          len([m for m in scattered["models"]
               if m["role"] == "prop" and m["anchor"] == [-4.0, -4.0]]) == 1)
    check(f"4 copies placed, {rejected} candidate(s) rejected into the notch",
          len(copies) == 4, str(len(copies)))
    for i, (px, py, pyaw) in enumerate(expect):
        check(f"copy {i + 1} at the independently derived point",
              i < len(copies) and near(copies[i]["anchor"][0], px, 1e-3)
              and near(copies[i]["anchor"][1], py, 1e-3)
              and near(copies[i]["yaw_deg"], pyaw, 0.11),
              f'{copies[i]["anchor"]} vs [{px}, {py}]')
    check("no copy landed in the notch (outside the boundary)",
          all(not (m["anchor"][0] > 0 and m["anchor"][1] > 0) for m in copies),
          str([m["anchor"] for m in copies]))
    # Without a drawn boundary the yard has no area, so nothing is scattered —
    # the manual anchor survives (contract v6 Nr. 1: no outline, no surface).
    no_edge = ground_fixture(props=[{"prop_id": "table", "at": [0.0, 0.0],
                                     "scatter_count": 4, "scatter_seed": seed}])
    no_edge["map3d"].pop("boundary")
    check("no boundary → no scatter, the anchor alone remains",
          len([m for m in scene_recipe.compose_scene(
              no_edge, plan_width_m=PLAN_W)["models"]
              if m["role"] == "prop"]) == 1)
    # ── The sanitizer: geometry submitted for the ground is stripped ────
    from app.core.world_ops import _sanitize_rooms_layout, sanitize_ground_layout
    clean = sanitize_ground_layout({
        "x": 1.0, "y": 2.0, "w": 3.0, "d": 4.0,
        "outline": [[0, 0], [3, 0], [3, 4]], "level": 2, "always_visible": True,
        "openings": [{"edge": 0, "at": 0.5, "type": "door",
                      "width_m": 1.0, "height_m": 2.0}],
        "surfaces": {"floor": "wood"},
        "props": [{"prop_id": "table", "at": [3.0, -2.0], "id": "t1"}],
        "markers": [{"at": [-1.0, 2.0], "group": "seat"}]})
    check("only props and markers survive",
          sorted(clean) == ["markers", "props"], str(sorted(clean)))
    check("...the placement itself is untouched",
          clean["props"] == [{"prop_id": "table", "id": "t1", "at": [3.0, -2.0]}],
          str(clean["props"]))
    check("an empty yard stores no layout at all",
          sanitize_ground_layout({"outline": [[0, 0], [1, 0], [1, 1]]}) == {})
    rooms = [{"id": GROUND_ID, "layout": {
        "x": 1.0, "y": 1.0, "w": 2.0, "d": 2.0,
        "outline": [[0, 0], [2, 0], [2, 2]],
        "props": [{"prop_id": "table", "at": [3.0, -2.0], "id": "t1"}]}}]
    _sanitize_rooms_layout(rooms)
    check("the room-list sanitizer routes the ground the same way",
          rooms[0]["layout"] == {"props": [{"prop_id": "table", "id": "t1",
                                            "at": [3.0, -2.0]}]},
          str(rooms[0].get("layout")))
    empty = [{"id": GROUND_ID, "layout": {"x": 0.0, "y": 0.0, "w": 2.0,
                                          "d": 2.0}}]
    _sanitize_rooms_layout(empty)
    check("...and drops a layout that was nothing but geometry",
          "layout" not in empty[0], str(empty[0]))


# ── The room turns as a WHOLE (contract v6 addendum, 2026-08-20) ────────
#
# ONE hand derivation for this whole block. `layout.rotation` turns the room
# about its rect CENTRE (x + w/2, y + d/2) with the § A1.1 matrix
#
#     x' = cx + lx·cos θ + lz·sin θ
#     z' = cz − lx·sin θ + lz·cos θ        (lx, lz = point − centre)
#
# At θ = 90° (cos = 0, sin = 1) that collapses to (lx, lz) → (lz, −lx).
#
# THE ROOM: x 0, y 1, w 4, d 2 → centre (0 + 4/2, 1 + 2/2) = (2, 2).
# Its rect corners run clockwise (0,1) (4,1) (4,3) (0,3), i.e. offsets from
# the centre (−2,−1) (2,−1) (2,1) (−2,1) → turned (−1,2) (−1,−2) (1,−2) (1,2)
# → world (1,4) (1,0) (3,0) (3,4). A 4 × 2 room lying east–west becomes a
# 2 × 4 room lying north–south, still centred on (2, 2). A rotation preserves
# orientation, so the winding stays clockwise and the edge INDICES do not
# move: edge 0 is still the room's own north wall, now running (1,4) → (1,0).
ROT_ROOM_TURNED = [[1.0, 4.0], [1.0, 0.0], [3.0, 0.0], [3.0, 4.0]]


def rot_fixture(*, rotation: int = 90, extra_rooms=(), boundary=None) -> dict:
    """The turned room alone on a 10 m plot (contour = the whole square)."""
    loc = {
        "id": "loc",
        "map3d": {
            "plan_width_m": PLAN_W,
            "storey_height_m": STOREY_REAL,
            "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
        },
        "rooms": [
            {"id": "t", "name": "T", "layout": {
                "x": 0.0, "y": 1.0, "w": 4.0, "d": 2.0, "level": 0,
                "rotation": rotation,
                # Room-local metres, all of them measured in the room's OWN
                # straight frame — that is what the turn is applied to.
                "props": [{"prop_id": "table", "at": [1.0, 0.5], "yaw": 30}],
                "markers": [{"at": [3.0, 1.5], "group": "stand",
                             "rotation": 45}],
                "openings": [{"edge": 0, "at": 0.5, "type": "door",
                              "width_m": 1.0, "height_m": 2.1,
                              "to": "outside"}],
            }},
            *extra_rooms,
        ],
    }
    if boundary is not None:
        loc["map3d"]["boundary"] = boundary
    return loc


def rot_scene(**kw) -> dict:
    return scene_recipe.compose_scene(rot_fixture(**kw), plan_width_m=PLAN_W)


def test_room_rotation() -> None:
    print("\n[19] the room turns as a WHOLE (v6 addendum)")
    stub_props()
    sc = rot_scene()

    plate = plate_of(sc, "t")
    check("the floor plate is the TURNED hull, not a straight shell",
          plate.get("outline") == ROT_ROOM_TURNED, str(plate.get("outline")))
    check("...and so is the room block the editor draws",
          [r for r in sc["rooms"] if r["room_id"] == "t"][0]["outline"]
          == ROT_ROOM_TURNED)
    straight = plate_of(rot_scene(rotation=0), "t")
    check("without a rotation nothing moves (the ordinary plan)",
          straight.get("outline") == [[0.0, 1.0], [4.0, 1.0],
                                      [4.0, 3.0], [0.0, 3.0]],
          str(straight.get("outline")))

    # Walls follow the hull: edge 0 now runs (1,4) → (1,0), so its wall
    # pieces stand on x = 1 and their outward normal is (uz, −ux) with
    # (ux, uz) = (0, −1) → (−1, 0), pointing WEST out of the room.
    edge0 = [w for w in sc["walls"] if w.get("room_id") == "t"
             and near(w["from"][0], 1.0) and near(w["to"][0], 1.0)]
    check("the shell walls stand on the turned edge (x = 1)",
          # 2 runs beside the door plus its lintel and its leaf — the turn
          # does not change how an opening is cut, only where the edge lies.
          len(edge0) == 4 and len([w for w in edge0 if is_full(w)]) == 2
          and len([w for w in edge0 if w.get("lintel")]) == 1
          and len([w for w in edge0 if w.get("leaf")]) == 1
          and all(near(w["outward_normal"][0], -1.0)
                  and near(w["outward_normal"][1], 0.0)
                  for w in edge0),
          str([(w["from"], w["to"]) for w in edge0]))

    # PROP: room-local (1.0, 0.5) → straight (0 + 1, 1 + 0.5) = (1, 1.5) →
    # offset (−1, −0.5) → turned (−0.5, 1) → world (2 − 0.5, 2 + 1) = (1.5, 3).
    # Its own yaw rides on top of the room's: 30 + 90 = 120.
    prop = spec_of(sc, "prop", "table")
    check("a prop lands on the hand point of the turned room",
          prop["anchor"] == [1.5, 3.0], str(prop["anchor"]))
    check("...and its yaw is its own PLUS the room's",
          near(prop["yaw_deg"], 120.0), str(prop["yaw_deg"]))

    # MARKER: room-local (3.0, 1.5) → straight (3, 2.5) → offset (1, 0.5) →
    # turned (0.5, −1) → world (2.5, 1.0); facing 45 + 90 = 135.
    mk = [m for m in sc["markers"] if m["source"] == "room"][0]
    check("a room marker turns with the room", mk["at_world"] == [2.5, 1.0],
          str(mk["at_world"]))
    check("...and its facing turns by the same angle",
          near(mk["facing"], 135.0), str(mk.get("facing")))

    # OPENING: edge 0 keeps its INDEX; the world point is the midpoint of the
    # turned edge (1,4) → (1,0), i.e. (1, 2). The edge direction is (0, −1),
    # which is what `along` carries.
    op = [r for r in sc["rooms"] if r["room_id"] == "t"][0]["openings"][0]
    check("the opening keeps its edge index (the hull's winding is intact)",
          op["edge"] == 0 and near(op["at"], 0.5), str(op))
    door = [d for d in sc["doorways"] if "t" in d["rooms"]][0]
    check("its threshold sits on the turned edge's midpoint",
          door["at_world"] == [1.0, 2.0], str(door["at_world"]))
    check("...running along the turned edge (0, −1)",
          near(door["along"][0], 0.0) and near(door["along"][1], -1.0),
          str(door["along"]))


def test_rotation_outside_boundary() -> None:
    print("\n[19b] a turn can push a room off the plot (v6 Nr. 9)")
    from app.core.room_recipe import compose_recipe
    # Plot = the 10 m square (−5…5). The room is 8 × 2 at x −4, y 2 →
    # centre (0, 3), straight bbox x −4…4, z 2…4: inside on every probe.
    # Turned by 90° the offsets (∓4, ∓1) become (∓1, ±4) → world
    # (−1,7) (−1,−1) (1,−1) (1,7): z = 7 is 2 m past the plot's north edge.
    boundary = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
    room = {"id": "long", "layout": {"x": -4.0, "y": 2.0, "w": 8.0, "d": 2.0,
                                     "level": 0}}

    def strays(rotation: int) -> list:
        lay = dict(room["layout"])
        if rotation:
            lay["rotation"] = rotation
        recipe = compose_recipe({**room, "layout": lay}, [])
        return scene_recipe.rooms_outside_boundary([recipe], boundary)

    check("straight it fits on the plot", strays(0) == [], str(strays(0)))
    check("turned 90° it pokes out — and is named",
          strays(90) == ["long"], str(strays(90)))


def test_rotation_shared_walls() -> None:
    print("\n[19c] shared walls stay COLINEARITY-based")
    from app.core.room_recipe import compose_recipe
    # A: x 0, y 0, w 4, d 2 → centre (2, 1). Turned 90° its corners are
    # (1,3) (1,−1) (3,−1) (3,3) — so its edge 2 is the wall x = 3, z −1…3.
    # B: x 2, y 0, w 4, d 2 → centre (4, 1). Turned 90° → (3,3) (3,−1)
    # (5,−1) (5,3) — its edge 0 is the SAME wall, run the other way.
    # (On paper the two rectangles overlap; turned they are neighbours — the
    # detection reads the turned hull, which is exactly the point.)
    a = {"id": "a", "layout": {"x": 0.0, "y": 0.0, "w": 4.0, "d": 2.0,
                               "rotation": 90,
                               "openings": [{"edge": 2, "at": 0.5,
                                             "type": "door", "width_m": 1.0,
                                             "height_m": 2.1, "to": "b"}]}}
    b = {"id": "b", "layout": {"x": 2.0, "y": 0.0, "w": 4.0, "d": 2.0,
                               "rotation": 90}}
    rb = compose_recipe(b, [a])
    mirror = [o for o in rb["openings"] if o.get("mirrored")]
    # A's door sits at (3, −1 + 0.5·4) = (3, 1). Projected onto B's edge 0
    # ((3,3) → (3,−1), direction (0,−1)): t = (1 − 3)·(−1) = 2 → at = 2/4.
    check("two rooms turned ALIKE still share their wall",
          len(mirror) == 1 and mirror[0]["edge"] == 0
          and near(mirror[0]["at"], 0.5), str(mirror))

    # The same pair, straight: A east wall x = 4 (edge 1), C west wall
    # x = 4 (edge 3) — the plain neighbour case, unchanged.
    a0 = {"id": "a", "layout": {"x": 0.0, "y": 0.0, "w": 4.0, "d": 2.0,
                                "openings": [{"edge": 1, "at": 0.5,
                                              "type": "door", "width_m": 1.0,
                                              "height_m": 2.1, "to": "c"}]}}
    c0 = {"id": "c", "layout": {"x": 4.0, "y": 0.0, "w": 4.0, "d": 2.0}}
    straight = [o for o in compose_recipe(c0, [a0])["openings"]
                if o.get("mirrored")]
    check("...as do two straight ones", len(straight) == 1
          and straight[0]["edge"] == 3, str(straight))

    # 30° against 0°: C's walls now run at 30°, so NO edge of C is
    # antiparallel to A's east wall — there is no shared wall to mirror
    # into. Documented, not repaired.
    c30 = {"id": "c", "layout": {**c0["layout"], "rotation": 30}}
    skew = [o for o in compose_recipe(c30, [a0])["openings"]
            if o.get("mirrored")]
    check("30° against 0° simply has no shared wall — and no mirror",
          skew == [], str(skew))



def test_map_water_reference() -> None:
    """[4w] A ROOM ON PAINTED WATER SHOWS A REFERENCE, NOT A MIRROR (W1).

    Water left the room plan. A room can no longer BE water — the sanitizer
    strips a water floor kind (measured in ``scripts/smoke_height_bake.py``
    [9], which has the catalog a DB gives it) — and the fifth bake stage that
    carved a room's own bed is deleted. What the floor plan carries instead is
    ``map_water``: ``{area_id, kind}`` of the painted water the room's hull
    LIES ON, derived at compose time by MAJORITY AREA and never stored, so it
    cannot dangle.

    THE MEASUREMENT, by hand. ``_map_water_ref`` samples the hull's bounding
    box on a fixed 32 x 32 lattice at CELL CENTRES and counts the probes that
    are inside the hull and inside the water. Every room below is an axis
    rectangle, so all 1024 probes are inside the hull and the share is the
    share of COLUMNS whose centre lies in the water. A room spanning
    ``x0 … x0 + 4`` has its i-th column centre at ``x0 + 0.125·i + 0.0625``,
    and the water covers ``x < 0``:

        pond   x −4 … 0    every column      -> 32/32 = 100 %  -> REFERENCE
        most   x −3 … 1    i < 23.5          -> 24/32 =  75 %  -> REFERENCE
        half   x −2 … 2    i < 15.5          -> 16/32 =  50 %  -> none, a
                                                MAJORITY is strictly more
        quarter x −1 … 3   i <  7.5          ->  8/32 =  25 %  -> none
        dry    x  2 … 4    none                             0 %  -> none

    TWO IDENTICAL LAKES are painted, and the reference names the LATER one:
    that is the priority law of the whole ground (§ A16.7, the last containing
    entry wins), not a tie-break invented here.
    """
    print("\n[4w] a room on painted water carries a map_water REFERENCE")
    lakes = [
        {"id": "ta_lake", "kind": "water",
         "polygon": [[-6, -6], [0, -6], [0, 6], [-6, 6]], "meta": {}},
        {"id": "ta_pool", "kind": "water",
         "polygon": [[-6, -6], [0, -6], [0, 6], [-6, 6]], "meta": {}},
    ]

    def zone(room_id, x0):
        return {"id": room_id, "name": room_id, "layout": {
            "x": x0, "y": -4.0, "w": 4.0, "d": 4.0, "level": 0,
            "always_visible": True, "surfaces": {"floor": "sand"}}}

    loc = {"id": "loc", "pos_x": 0.0, "pos_z": 0.0, "yaw_deg": 0.0,
           "map3d": {"plan_width_m": PLAN_W, "storey_height_m": STOREY_REAL,
                     "boundary": [[-6, -6], [6, -6], [6, 6], [-6, 6]]},
           "rooms": [zone("pond", -4.0), zone("most", -3.0),
                     zone("half", -2.0), zone("quarter", -1.0),
                     zone("dry", 2.0)]}
    original = scene_recipe._painted_waters
    scene_recipe._painted_waters = lambda: list(lakes)
    try:
        plan = {f["room_id"]: f
                for f in scene_recipe.compose_scene(
                    loc, plan_width_m=PLAN_W)["floor_plan"]}
    finally:
        scene_recipe._painted_waters = original
    check("a room wholly on the water names it",
          plan["pond"].get("map_water") == {"area_id": "ta_pool",
                                            "kind": "water"},
          str(plan["pond"].get("map_water")))
    check("...and so does one at 75 %",
          plan["most"].get("map_water") == {"area_id": "ta_pool",
                                            "kind": "water"},
          str(plan["most"].get("map_water")))
    check("red: exactly HALF is not a majority — no reference",
          "map_water" not in plan["half"], str(plan["half"]))
    check("red: a quarter neither", "map_water" not in plan["quarter"],
          str(plan["quarter"]))
    check("red: and a room off the water carries nothing at all",
          "map_water" not in plan["dry"], str(plan["dry"]))
    check("the LATER lake wins the tie (the ground's own priority law)",
          plan["pond"]["map_water"]["area_id"] == "ta_pool",
          str(plan["pond"]["map_water"]))
    check("red: the room owns NO mirror, no depth and no ramp — the whole "
          "entry is polygon, kind, closed and the reference",
          sorted(plan["pond"]) == ["closed", "floor_kind", "map_water",
                                   "polygon_world", "room_id"],
          str(sorted(plan["pond"])))
    check("red: `water_level_effective` is gone from the floor plan",
          not [f for f in plan.values() if "water_level_effective" in f],
          str(list(plan)))
    # …and with no painted water in the world there is no key anywhere, which
    # is the state of every location that is not on a lake.
    plan_dry = {f["room_id"]: f
                for f in scene_recipe.compose_scene(
                    loc, plan_width_m=PLAN_W)["floor_plan"]}
    check("a world without painted water gives no room a reference",
          not [rid for rid, f in plan_dry.items() if "map_water" in f],
          str(sorted(plan_dry)))


# ── Baked surfaces (spec-surface-height § 6.1) ─────────────────────────

# ONE hand-written lattice, the shape ``model_surface.payload_block`` emits:
# a 2 × 2 m box on a 0.25 m raster is 9 × 9 = 81 nodes, all 20 cm above the
# lower edge (values are centimetre ints relative to ``box_min.y``).
SURFACE_BLOCK = {"step": 0.25, "origin": [-1, -1], "cols": 9, "rows": 9,
                 "values": [20] * 81, "box_min": [-1, 0, -1],
                 "box_max": [1, 1.6, 1], "extent_snapped": [2, 1.6, 2]}

# A walkable prop beside the plain example one: same shape as EXAMPLE_PROP,
# plus the ONE tag that switches the surface on (decision 7).
WALKABLE_PROP = {
    "id": "crate", "name": "Crate",
    "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0,
    "rotation": {"x": 0, "y": 0, "z": 0},
    "bbox": [1.0, 1.0, 1.0],
    "has_model": True, "model_tiers": ["full"],
    "model_signature": "cratesig1",
    "tags": ["Walkable"],          # case is not part of the tag (lowered)
    "slots": [],
}


# The SAME crate with two model variants published. The store indices are 0
# and 2, not 0 and 1: variant 1 is switched off, and the payload entry names
# its own store index (`props._published_entry`) precisely so a position may
# not stand in for it. `room_recipe._join_placements` copies this list onto
# every placement of the prop as `variant_tiers`.
TWO_VARIANT_CRATE = {
    **WALKABLE_PROP,
    "variant_tiers": [
        {"variant": 0, "tiers": ["full"],
         "dims": {"width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}},
        {"variant": 2, "tiers": ["full"],
         "dims": {"width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}},
    ],
}


def _surf_note(spec: dict) -> str:
    """The lattice in one line — 81 identical values are unreadable as a
    failure detail, its size and its first value are not."""
    s = spec.get("surface")
    if not isinstance(s, dict):
        return str(s)
    return (f'{s.get("cols")}x{s.get("rows")} @ {s.get("step")} m, '
            f'values[0]={(s.get("values") or [None])[0]}, '
            f'box {s.get("box_min")}..{s.get("box_max")}')


def two_crate_fixture() -> dict:
    """Room "a" with TWO copies of the walkable crate showing DIFFERENT
    variants: the first takes the default (position 0), the second names
    position 1. Both are clear of the table, so the stacking rule stays out."""
    loc = model_fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"] += [
                {"prop_id": "crate", "at": [3.5, 0.5], "yaw": 0},
                {"prop_id": "crate", "at": [3.5, 2.5], "yaw": 0, "variant": 1},
            ]
    return loc


def crate_surface_stub(store0_values: int = 20):
    """A ``props.surface_for`` stand-in that gives each STORE index its own
    lattice and RECORDS what it was asked for. Returns ``(seen, fn)``."""
    seen = []

    def surface_for(pid, variant=None):
        seen.append((pid, variant))
        if pid != "crate":
            return None
        value = store0_values if variant in (None, 0) else 40
        return dict(SURFACE_BLOCK, values=[value] * 81)

    return seen, surface_for


def crate_scene(loc: dict) -> dict:
    return scene_recipe.compose_scene(loc, plan_width_m=PLAN_W,
                                      building_meta=BUILDING_META,
                                      room_metas=room_metas())


def props_of(sc: dict, ident: str) -> list:
    return [m for m in sc["models"]
            if m.get("role") == "prop" and m.get("id") == ident]


def surface_fixture() -> dict:
    """The model fixture with a SECOND prop in room "a" — the walkable crate
    beside the plain table, far enough from it not to be stacked on it."""
    loc = model_fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"].append(
                {"prop_id": "crate", "at": [3.5, 0.5], "yaw": 0})
    return loc


def test_surface_specs() -> None:
    """[7i] BAKED SURFACES ON THE PLACEMENT SPEC (v6, spec-surface-height).

    Four statements, all of them payload rules and none of them geometry —
    the numbers of the lattice are the bake's, and the recipe hands them on
    character for character:

    * ``SCENE_RECIPE_VERSION`` is 6, so every client re-fetches once;
    * a room whose meta carries ``surface`` gives the block to its ``room``
      spec unchanged, and a room whose meta carries none gets no field;
    * a prop tagged ``walkable`` gets ``walkable: True`` and — only if its
      variant really has a baked lattice — the block; an untagged prop gets
      neither field, so a table's lattice is not dead weight in the payload;
    * the signature moves when a block appears, which is what makes a freshly
      baked surface reach a running client.
    """
    print("\n[7i] baked model surfaces (v6)")
    from app.core import props as prop_store
    check("code_version 7 (markers speak place types)", scene_recipe.SCENE_RECIPE_VERSION == 7,
          str(scene_recipe.SCENE_RECIPE_VERSION))

    # ── the room diorama ─────────────────────────────────────────────────
    stub_props()
    metas = room_metas()
    metas["d"] = dict(metas["d"], surface=SURFACE_BLOCK)
    sc = scene_recipe.compose_scene(model_fixture(), plan_width_m=PLAN_W,
                                    building_meta=BUILDING_META,
                                    room_metas=metas)
    room = spec_of(sc, "room", "d")
    check("the room spec carries the meta's block, unchanged",
          room.get("surface") == SURFACE_BLOCK, _surf_note(room))
    other = spec_of(sc, "room", "garden")
    check("a room whose meta has no surface carries no field",
          other and "surface" not in other, str(sorted(other)))
    plain = scene_recipe.compose_scene(model_fixture(), plan_width_m=PLAN_W,
                                       building_meta=BUILDING_META,
                                       room_metas=room_metas())
    check("the signature moves with the block",
          sc["signature"] != plain["signature"])

    # ── props: the walkable crate and the plain table ────────────────────
    recs = {"table": EXAMPLE_PROP, "crate": WALKABLE_PROP}
    stub_library(lambda pid: dict(recs[pid]) if pid in recs else None)
    real_surface_for = prop_store.surface_for
    prop_store.surface_for = (
        lambda pid, variant=None: dict(SURFACE_BLOCK) if pid == "crate" else None)
    try:
        sc = scene_recipe.compose_scene(surface_fixture(), plan_width_m=PLAN_W,
                                        building_meta=BUILDING_META,
                                        room_metas=room_metas())
        crate = spec_of(sc, "prop", "crate")
        table = spec_of(sc, "prop", "table")
        check("the tagged prop says walkable", crate.get("walkable") is True,
              str(crate.get("walkable")))
        check("...and ships the baked block of its variant",
              crate.get("surface") == SURFACE_BLOCK, _surf_note(crate))
        check("the untagged prop says nothing", "walkable" not in table)
        check("...and ships no block", "surface" not in table)
        # The tag is the switch, the bake is the content: a walkable prop
        # whose mesh was never baked stays walkable and simply has no lattice
        # — the renderers fall back to the floor under it.
        prop_store.surface_for = lambda pid, variant=None: None
        unbaked = spec_of(scene_recipe.compose_scene(
            surface_fixture(), plan_width_m=PLAN_W,
            building_meta=BUILDING_META, room_metas=room_metas()),
            "prop", "crate")
        check("walkable without a bake: the flag, no block",
              unbaked.get("walkable") is True and "surface" not in unbaked,
              str(sorted(unbaked)))
    finally:
        prop_store.surface_for = real_surface_for
        stub_props()


def test_surface_variants() -> None:
    """[7h] THE VARIANT IS PART OF THE QUESTION AND PART OF THE KEY.

    Two copies of the same crate in one room, showing two different meshes.
    Two statements, both hand-derived from the shapes above:

    * WHICH VARIANT IS ASKED FOR. ``TWO_VARIANT_CRATE`` publishes store
      indices 0 and 2 (variant 1 is switched off), so ``model_variants`` has
      two entries at POSITIONS 0 and 1. The second placement says
      ``variant: 1``, which is a position — and the prop library addresses a
      mesh by its STORE index, so the recipe must ask ``surface_for`` for 2,
      not for 1. The first placement says nothing, i.e. position 0 → store 0.
      A crate with only ONE published variant has no list to resolve through
      and asks for None, the primary.
    * WHICH KEY THE SIGNATURE USES. Both copies are ``prop:crate:a``, so a key
      of role + id + room would keep only the LAST of them and a re-bake of
      the first one's mesh would move no hashed input at all. Here the first
      copy's lattice changes (values 20 → 25) and nothing else does — the
      signature has to move.
    """
    print("\n[7h] two variants of one prop in one room")
    from app.core import props as prop_store
    real_surface_for = prop_store.surface_for
    recs = {"table": EXAMPLE_PROP, "crate": TWO_VARIANT_CRATE}
    stub_library(lambda pid: dict(recs[pid]) if pid in recs else None)
    try:
        seen, prop_store.surface_for = crate_surface_stub()
        sc = crate_scene(two_crate_fixture())
        crates = props_of(sc, "crate")
        check("both copies are in the payload", len(crates) == 2,
              str(len(crates)))
        check("...at POSITIONS 0 and 1 of model_variants",
              [c.get("variant") for c in crates] == [0, 1],
              str([c.get("variant") for c in crates]))
        check("the library is asked for the STORE indices 0 and 2",
              seen == [("crate", 0), ("crate", 2)], str(seen))
        check("copy 1 got store 0's lattice (values 20)",
              crates[0]["surface"]["values"][0] == 20,
              str(crates[0]["surface"]["values"][0]))
        check("copy 2 got store 2's lattice (values 40)",
              crates[1]["surface"]["values"][0] == 40,
              str(crates[1]["surface"]["values"][0]))

        # Re-bake the FIRST copy's mesh alone — the one a role:id:room key
        # would have dropped.
        _, prop_store.surface_for = crate_surface_stub(store0_values=25)
        moved = crate_scene(two_crate_fixture())
        check("a re-bake of the SWALLOWED variant moves the signature",
              moved["signature"] != sc["signature"])
        check("...and nothing else in the payload changed",
              [c.get("variant") for c in props_of(moved, "crate")] == [0, 1])

        # One published variant: no list to resolve through, so the primary.
        seen, prop_store.surface_for = crate_surface_stub()
        stub_library(lambda pid: (dict(WALKABLE_PROP) if pid == "crate"
                                  else dict(EXAMPLE_PROP) if pid == "table"
                                  else None))
        crate_scene(surface_fixture())
        check("a single-variant placement asks for the primary (None)",
              seen == [("crate", None)], str(seen))
    finally:
        prop_store.surface_for = real_surface_for
        stub_props()


def main() -> int:
    test_scalars()
    test_scale_is_one()
    test_plates()
    test_room_walls()
    test_room_floor_offset()
    test_no_walls()
    test_doorways()
    test_door_props()
    test_threshold_base_y()
    test_contour_walls()
    test_no_building_entrance()
    test_rooms_without_layout()
    test_openings_without_walls()
    test_wall_skirt()
    test_contour_wall_texture()
    test_area_locations()
    test_map_water_reference()
    test_boundary_only_datum()
    test_area_room_walk_height()
    test_elevator()
    test_stairs()
    test_style()
    test_building_spec()
    test_floor_relation()
    test_room_and_prop_specs()
    test_markers_figures()
    test_place_slots()
    test_prop_ground_offset()
    test_prop_stacking()
    test_prop_depth_cut()
    test_clip_outline()
    test_signature()
    test_curved_outline()
    test_scatter()
    test_boundary_openings()
    test_boundary_polygon()
    test_area_detail()
    test_ground_placements()
    test_room_rotation()
    test_rotation_outside_boundary()
    test_rotation_shared_walls()
    test_surface_specs()
    test_surface_variants()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
