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
    check("...and the DRAWN contour does not move with it (still ±5)",
          [p for p in wide["plates"] if not p.get("room_id")][0]["outline"][2]
          == [5.0, 5.0],
          str([p for p in wide["plates"] if not p.get("room_id")][0]["outline"]))
    # map3d.extent_m was the world-metre dial of the tile era. It is not read
    # any more — an old blob carrying it composes exactly like one without.
    stale = scene_recipe.compose_scene(
        {**fixture(), "map3d": {**fixture()["map3d"], "extent_m": 40.0}},
        plan_width_m=PLAN_W)
    check("a leftover map3d.extent_m changes NOTHING",
          near(stale["extent_m"], PLAN_W) and near(stale["k"], 1.0)
          and stale["plates"] == sc["plates"],
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


def test_plates() -> None:
    print("\n[2] plates")
    sc = scene()
    level = [p for p in sc["plates"] if not p.get("room_id")]
    check("one contour plate per used level", len(level) == 1, str(len(level)))
    p = level[0]
    check("top at level × storey + 0.08", near(p["top_y"], 0.08), str(p["top_y"]))
    check("thickness 0.14", near(p["thickness"], 0.14), str(p["thickness"]))
    check("level_floors kind wins", p["texture_kind"] == "parquet",
          str(p.get("texture_kind")))
    check("contour in world metres (±5 = the 10 m square)",
          p["outline"][0] == [-5.0, -5.0] and p["outline"][2] == [5.0, 5.0],
          str(p["outline"]))
    check("ground floor is opaque", p["opacity_role"] == "ground")

    room_a = [q for q in sc["plates"] if q.get("room_id") == "a"]
    check("the room has its own plate", len(room_a) == 1)
    check("with the room's floor kind", room_a[0].get("texture_kind") == "wood",
          str(room_a[0].get("texture_kind")))
    check("a body above the level plate",
          near(room_a[0]["top_y"], 0.10) and room_a[0]["thickness"] > 0,
          str(room_a[0]))

    garden = [q for q in sc["plates"] if q.get("room_id") == "garden"]
    check("an outdoor room is a texture surface, thickness 0",
          len(garden) == 1 and near(garden[0]["thickness"], 0.0)
          and near(garden[0]["top_y"], 0.0), str(garden))
    check("...and still carries its floor kind",
          garden[0].get("texture_kind") == "grass")

    no_contour = scene_recipe.compose_scene(
        {"map3d": {"plan_width_m": PLAN_W}, "rooms": fixture()["rooms"]},
        plan_width_m=PLAN_W)
    check("without map3d.outline there is no level plate",
          not [q for q in no_contour["plates"] if not q.get("room_id")])


def test_room_walls() -> None:
    print("\n[3] room shell walls — splits, window band, outdoor")
    sc = scene()
    a = walls_of(sc, "a")
    check("outdoor rooms have no shell", not walls_of(sc, "garden"))
    check("wall height max(0.6, storey − 0.15)",
          all(near(w["height"], WALL_H) or w.get("glass")
              or w["height"] < WALL_H for w in a))
    check("thickness 0.07 on solid walls",
          all(near(w["thickness"], 0.07) for w in a if not w.get("glass")))
    check("the wall texture kind rides along",
          all(w.get("texture_kind") == "plaster" for w in a if not w.get("glass")))
    check("base_y = storey floor + 0.10 for full-height pieces",
          all(near(w["base_y"], 0.10) for w in a
              if near(w["height"], WALL_H) and not w.get("glass")))

    # Room a in world metres: x −4…0 (4 wide), z −4…−1 (3 deep).
    north = [w for w in a if near(w["from"][1], -4.0) and near(w["to"][1], -4.0)]
    check("north edge yields 2 solids + sill + head + glass = 5",
          len(north) == 5, str(len(north)))
    # Window: width_m 2.0 IS 2 world metres (k = 1), centred at t = 2.0 on the
    # 4 m edge → span [1.0, 3.0].
    solid_n = sorted([w for w in north if near(w["height"], WALL_H)],
                     key=lambda w: w["from"][0])
    check("the opening is the declared 2 metres wide",
          len(solid_n) == 2 and near(solid_n[0]["to"][0], -4.0 + 1.0)
          and near(solid_n[1]["from"][0], -4.0 + 3.0),
          str([[w["from"], w["to"]] for w in solid_n]))
    glass = [w for w in north if w.get("glass")]
    check("exactly one glass pane", len(glass) == 1)
    check("glass sits at sill_m 0.9 and is height_m 1.2 tall",
          len(glass) == 1 and near(glass[0]["base_y"], 0.10 + 0.9)
          and near(glass[0]["height"], 1.2), str(glass))
    check("glass is thinner than the wall and carries no texture kind",
          glass and near(glass[0]["thickness"], 0.042)
          and "texture_kind" not in glass[0], str(glass))
    band = sorted([w for w in north if not w.get("glass")
                   and not near(w["height"], WALL_H)],
                  key=lambda w: w["base_y"])
    check("sill segment 0 → 0.9 and head segment 2.1 → 2.85",
          len(band) == 2 and near(band[0]["height"], 0.9)
          and near(band[1]["base_y"], 0.10 + 2.1)
          and near(band[1]["height"], WALL_H - 2.1), str(band))

    south = [w for w in a if near(w["from"][1], -1.0) and near(w["to"][1], -1.0)]
    check("a door is a plain gap: 2 segments, no glass",
          len(south) == 2 and not [w for w in south if w.get("glass")],
          str(len(south)))
    check("the door gap is the declared 1 metre wide",
          len(south) == 2
          and near(abs(south[0]["to"][0] - south[1]["from"][0]), 1.0),
          str([[w["from"], w["to"]] for w in south]))
    check("9 wall segments in total for the room", len(a) == 9, str(len(a)))
    check("outward normals point away from the room (north edge → −z)",
          all(near(w["outward_normal"][1], -1.0) for w in north),
          str(north[0]["outward_normal"]))


def contour_pieces(sc: dict, level: int = 0) -> list:
    """The contour wall pieces of one level (no room_id), in emission order."""
    return [w for w in sc["walls"]
            if not w.get("room_id") and w["level"] == level]


def edge_pieces(sc: dict, *, z: float = None, x: float = None,
                level: int = 0) -> list:
    """The contour pieces lying on ONE straight contour line, sorted along the
    edge direction (the south edge runs −x, the east edge +z)."""
    if z is not None:
        out = [w for w in contour_pieces(sc, level)
               if near(w["from"][1], z) and near(w["to"][1], z)]
        return sorted(out, key=lambda w: -w["from"][0])
    out = [w for w in contour_pieces(sc, level)
           if near(w["from"][0], x) and near(w["to"][0], x)]
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
    sc = scene()
    check("4 edges, the south one split by the door's projection",
          len(contour_pieces(sc)) == 5, str(len(contour_pieces(sc))))
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
                         and near(w["to"][1], 5.0)],
                        key=lambda w: -w["from"][0])
    check("the room's own wall carries the 1.0 m entrance at x −0.5 … −1.5",
          len(room_south) == 2 and near(room_south[0]["to"][0], -0.5)
          and near(room_south[1]["from"][0], -1.5),
          str([[w["from"], w["to"]] for w in room_south]))

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
    check("every contour piece carries the shell kind",
          len(contour) == 5 and all(w.get("texture_kind") == "brick"
                                    for w in contour),
          f"{len(contour)} pieces, "
          f"{sorted({w.get('texture_kind') for w in contour})}")
    check("room walls keep their own surfaces.wall kind",
          all(w.get("texture_kind") == "plaster" for w in walls_of(sc, "a")
              if not w.get("glass")),
          str(sorted({w.get("texture_kind") for w in walls_of(sc, "a")
                      if not w.get("glass")})))
    check("glass panes stay untextured",
          all("texture_kind" not in w for w in sc["walls"] if w.get("glass")))
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

    print("\n[4d] overlay zones instead of plates")
    plates = {p.get("room_id") for p in withb["plates"] if p.get("room_id")}
    check("the outdoor room OUTSIDE the plan has no plate",
          "zone" not in plates, str(sorted(plates)))
    check("the outdoor room INSIDE keeps its § A5 plate", "yard" in plates)
    yard = [p for p in withb["plates"] if p.get("room_id") == "yard"][0]
    check("...still with thickness 0", near(yard["thickness"], 0.0))
    check("both indoor rooms keep their plates",
          {"in", "out"} <= plates, str(sorted(plates)))
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
    check("the ground of an area location IS the level-0 floor",
          ov and near(ov["y"], 0.0), str(ov and ov["y"]))
    check("...and the mesh hangs below it by walk_y",
          near(building["bottom_y"], -4.0),
          f"{building['bottom_y']} (walk_y 4 m, k = 1)")
    check("offset_y does NOT apply — a level-0 square cannot sink to level −1",
          near(spec_of(area_scene(meta={**GROUND_META, "offset_y": -3.0}),
                       "building")["bottom_y"], -4.0),
          str(spec_of(area_scene(meta={**GROUND_META, "offset_y": -3.0}),
                      "building")["bottom_y"]))
    check("without the dial a ground model sits with its underside on 0",
          near(spec_of(area_scene(meta=BUILDING_META), "building")["bottom_y"],
               0.0),
          str(spec_of(area_scene(meta=BUILDING_META), "building")["bottom_y"]))
    check("without a building model it falls back to the storey floor",
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

    # A zone WITH a declared floor kind: the surface is laid at the zone's own
    # height instead of being dropped. That is what turns a drawn area into a
    # lake — a room over the water, floor kind "water", and the material class
    # does the rest. Expected: exactly one plate, thickness 0 (texture only),
    # at overlay.y + OVERLAY_SURFACE_LIFT (0.01), carrying the kind.
    import copy
    lake = copy.deepcopy(area_fixture(True))
    for r in lake["rooms"]:
        if r["id"] == "zone":
            r["layout"]["surfaces"] = {"floor": "water"}
    lake_sc = scene_recipe.compose_scene(lake, plan_width_m=PLAN_W,
                                         building_meta=GROUND_META)
    zp = [pl for pl in lake_sc["plates"] if pl.get("room_id") == "zone"]
    lake_ov = next(r["overlay"] for r in lake_sc["rooms"]
                   if r["room_id"] == "zone")
    check("a zone with a floor kind gets ONE texture surface",
          len(zp) == 1, str(len(zp)))
    if zp:
        check("thickness 0 — texture, no body", zp[0]["thickness"] == 0.0,
              str(zp[0]["thickness"]))
        check("at the zone's own height + the 0.01 z-fight lift",
              near(zp[0]["top_y"], lake_ov["y"] + 0.01),
              f'{zp[0]["top_y"]} vs {lake_ov["y"]} + 0.01')
        check("carrying the declared kind", zp[0]["texture_kind"] == "water",
              str(zp[0].get("texture_kind")))
    check("the zone keeps its overlay as well", bool(lake_ov))

    print("\n[4e] without the flag nothing changes")
    check("no cutouts on the building spec",
          "cutouts" not in [m for m in scene_recipe.compose_scene(
              area_fixture(False), plan_width_m=PLAN_W,
              building_meta=BUILDING_META)["models"]
              if m["role"] == "building"][0])
    check("no overlay on any room",
          not [r for r in plain["rooms"] if r.get("overlay")])
    check("the outdoor room outside the plan keeps its plate",
          "zone" in {p.get("room_id") for p in plain["plates"]})
    check("the flag moves the signature (clients re-fetch)",
          sc["signature"] != plain["signature"],
          f"{sc['signature'][:8]} vs {plain['signature'][:8]}")


def test_room_floor_offset() -> None:
    print("\n[3c] per-room floor offset (rooms that cut into a location model)")
    base = scene()
    loc = fixture()
    for room in loc["rooms"]:
        if room["id"] == "a":
            room["layout"]["floor_offset_y"] = 2.0   # metres, k = 1
    sc = scene_recipe.compose_scene(loc, plan_width_m=PLAN_W)
    lift = 2.0
    plate = [p for p in sc["plates"] if p.get("room_id") == "a"][0]
    before = [p for p in base["plates"] if p.get("room_id") == "a"][0]
    check("the room plate rises by floor_offset_y",
          near(plate["top_y"], before["top_y"] + lift),
          f"{before['top_y']} -> {plate['top_y']}")
    walls = [w for w in sc["walls"] if w.get("room_id") == "a"]
    check("its walls stand on the moved plate",
          all(near(w["base_y"], wb["base_y"] + lift)
              for w, wb in zip(walls, walls_of(base, "a"))),
          f"{walls[0]['base_y']} vs {walls_of(base, 'a')[0]['base_y']}")
    check("the LEVEL plate does not move (it belongs to the building)",
          near([p for p in sc["plates"] if not p.get("room_id")][0]["top_y"],
               [p for p in base["plates"] if not p.get("room_id")][0]["top_y"]))
    check("a neighbouring room does not move",
          near([p for p in sc["plates"] if p.get("room_id") == "garden"][0]["top_y"],
               [p for p in base["plates"] if p.get("room_id") == "garden"][0]["top_y"]))
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
    check("its floor plate is still there",
          len([p for p in sc["plates"] if p.get("room_id") == "a"]) == 1)
    check("its openings stay in the rooms block (the 2D editor draws them)",
          len([r for r in sc["rooms"]
               if r["room_id"] == "a"][0].get("openings") or []) == 2,
          str(len([r for r in sc["rooms"]
                   if r["room_id"] == "a"][0].get("openings") or [])))

    # A room without a shell has no wall, hence no door — and the hull takes
    # its holes from the doors. So the contour closes here (5 pieces before,
    # 4 whole edges now) instead of keeping the gap the door used to cut.
    # `no_building_entrance` has nothing to report: no walled room is left on
    # level 0, and an outdoor zone is not a building one puts a door into.
    # The lost openings are what `openings_without_walls` says instead ([4h]).
    contour_before = [w for w in base["walls"] if not w.get("room_id")]
    contour = [w for w in sc["walls"] if not w.get("room_id")]
    check("the shell-less room takes its hull hole with it",
          len(contour_before) == 5 and len(contour) == 4,
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
    # world (0 − 2, −1) = (−2, −1). base_y = level 0 × 3 + 0.10 (room plate).
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
    check("base_y = the wall's own foot, 0.10", near(d.get("base_y", -1), 0.10),
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
    # leaves exactly two solid pieces in room a's east wall.
    east_a = [w for w in walls_of(both, "a")
              if near(w["from"][0], 0.0) and near(w["to"][0], 0.0)]
    check("...and the wall really has ONE gap there (2 pieces)",
          len(east_a) == 2, str([[w["from"], w["to"]] for w in east_a]))
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
    # Room "a" has no `model_offset_y`, so its diorama's lower edge is the room
    # plate 0.10 plus the diorama clearance 0.02 = 0.12, and `walk_y` counts
    # from there: walk_y 0 → 0.12, walk_y 0.057 → 0.177.
    def with_metas(metas: dict, loc=None) -> list:
        return scene_recipe.compose_scene(loc or fixture(), plan_width_m=PLAN_W,
                                          room_metas=metas)["doorways"]

    plain = with_metas({})
    check("no diorama anywhere: base_y stays the wall foot 0.10",
          len(plain) == 1 and near(plain[0]["base_y"], 0.10), str(plain))
    lifted = with_metas({"a": {"width_m": 3.0, "walk_y": 0}})
    check("room a declares its floor (0.12): its OUTSIDE door lifts with it",
          len(lifted) == 1 and near(lifted[0]["base_y"], 0.12), str(lifted))
    # Party wall a|b: a keeps the foot, b's diorama declares 0.177.
    b_room = {"id": "b", "name": "B", "layout": {
        "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0}}
    party = door_fixture(extra_rooms=(b_room,), a_openings=[
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.6, "to": "b"}])
    joined = with_metas({"b": {"width_m": 3.0, "walk_y": 0.057}}, party)
    check("a door between 0.10 and 0.177 lies at 0.177 — one steps OVER it",
          len(joined) == 1 and near(joined[0]["base_y"], 0.177), str(joined))
    check("...and the order of the rooms does not decide it",
          near(with_metas({"a": {"width_m": 3.0, "walk_y": 0.057},
                           "b": {"width_m": 3.0, "walk_y": 0}},
                          party)[0]["base_y"], 0.177),
          str(with_metas({"a": {"width_m": 3.0, "walk_y": 0.057},
                          "b": {"width_m": 3.0, "walk_y": 0}}, party)))
    # A room meta WITHOUT walk_y declares nothing — a diorama alone is not a
    # statement about where its floor is (that is the "no automatic repair"
    # rule of the model contract).
    check("a diorama without walk_y changes nothing",
          near(with_metas({"a": {"width_m": 3.0}})[0]["base_y"], 0.10),
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
    # Same error class, same pin (review 2026-08-16): the walkability sampler
    # let a DECLARED `walk_y_world` — a tile metre — stand in for `floor`, which
    # is a world ray hit and is written back as one (`center.setY`). On a tile
    # whose plateau is 0.05 m the pool's declared 0.12 sank the room centre to
    # 0.13 instead of 0.17; on a high plateau the spot filter (|y − floor| <
    # 0.12) matched nothing at all and the declaration was silently dropped.
    # The sampler raycasts a THREE scene, so there is nothing pure to compute
    # here — the conversion is pinned instead.
    tiles_ts = (Path(__file__).resolve().parents[1]
                / "client3d" / "src" / "scene" / "tiles.ts")
    tsrc = tiles_ts.read_text(encoding="utf-8") if tiles_ts.exists() else ""
    check("client3d/src/scene/tiles.ts is where it is", bool(tsrc), str(tiles_ts))
    check("the declared walk height enters the sampler as a WORLD height",
          "floor = tile.center.y + declaredFloor" in tsrc)
    check("...and never raw, in the payload's own frame",
          "floor = declaredFloor" not in tsrc)


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
    check("pad 1.6 m just below the plate top",
          near(pad["size"][0], 1.6) and near(pad["center"][1], 0.055),
          str(pad))
    check("no elevator without map3d.elevator",
          not scene_recipe.compose_scene({"map3d": {}, "rooms": []})["extras"])


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
    "rotation": {"x": 0, "y": 90, "z": 0},
    "bbox": [1.0, 0.5, 2.0],
    # Two resolution tiers (v5.3 Nr. 16) → the placement carries both and the
    # spec turns them into "<endpoint>?tier=<tier>" URLs.
    "has_model": True, "model_tiers": ["full", "low"],
    "model_signature": "propsig1",
    "markers": [{"at": [0.5, 1.0, 0.25], "animation": "sit", "facing": 90}],
}

BUILDING_META = {"rotation": {"x": 0, "y": 90, "z": 0}, "offset_x": 1.0,
                 "offset_y": 0.2, "offset_z": -1.0}
# The walk height is a DIAL, never a measurement: 4 metres above the model's
# lower edge, and at k = 1 that is 4 world metres.
GROUND_META = {**BUILDING_META, "walk_y": 4.0}


def stub_props() -> None:
    from app.core import props as prop_store
    prop_store.get_prop = lambda pid: dict(EXAMPLE_PROP) if pid == "table" else None


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
            room["layout"]["markers"] = [{"at": [1.0, 1.5], "animation": "idle",
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
    check("a shell STANDS on the ground: bottom_y = 0.06 + offset_y",
          near(b["bottom_y"], 0.26), str(b["bottom_y"]))
    check("a shell's walk height is its lower edge (no auto-measuring)",
          near(b["walk_y_world"], 0.26), str(b.get("walk_y_world")))
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
    check("indoor: bottom_y = room plate 0.10 + 0.02 + model_offset_y",
          near(d["bottom_y"], 0.22), str(d["bottom_y"]))
    # An outdoor room has NO plate (§ A5): its diorama rests on the storey
    # floor, exactly like the props in that room.
    garden = spec_of(sc, "room", "garden")
    check("outdoor: bottom_y = storey floor + 0.02, no phantom plate",
          near(garden["bottom_y"], 0.02), str(garden.get("bottom_y")))
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
          near(wd.get("walk_y_world", -1), 0.22 + 0.3),
          str(wd.get("walk_y_world")))
    zero = scene_recipe.compose_scene(
        model_fixture(), plan_width_m=PLAN_W, building_meta=BUILDING_META,
        room_metas={"d": {**room_metas()["d"], "walk_y": 0}})
    check("walk_y 0 means the lower edge, not 'unset'",
          near(spec_of(zero, "room", "d").get("walk_y_world", -1), 0.22),
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
    check("bottom_y = room plate top + 0.01 + offset_y",
          near(p["bottom_y"], 0.11),
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
          near(pm["y_world"], 0.11 + 0.3),
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


def plate_of(sc: dict, room_id: str) -> dict:
    hits = [p for p in sc["plates"] if p.get("room_id") == room_id]
    return hits[0] if hits else {}


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
    from app.core import props as prop_store
    prop_store.get_prop = lambda pid: (
        {**EXAMPLE_PROP, "model_signature": "propsig2"} if pid == "table"
        else None)
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
    plate = [p for p in sc["plates"] if p.get("room_id") == "a"][0]
    check("the floor plate is the tessellated hull in world metres",
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


def l_fixture(*, relief: bool = False, openings=None) -> dict:
    """The base fixture with the L drawn as its boundary and no building
    contour — so the LEVEL plate has to come from the boundary."""
    loc = fixture()
    loc["map3d"].pop("outline")
    loc["map3d"]["boundary"] = [list(p) for p in L_BOUNDARY]
    if relief:
        loc["map3d"]["area_detail"] = True
        loc["map3d"]["relief"] = {"amplitude_m": 2.0, "seed": 1}
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
    level = [p for p in sc["plates"] if not p.get("room_id")]
    check("one level plate, and its outline is the L",
          len(level) == 1 and level[0]["outline"] == L_BOUNDARY,
          str(level and level[0]["outline"]))
    check("...its top and thickness are the ordinary level-plate ones",
          near(level[0]["top_y"], 0.08) and near(level[0]["thickness"], 0.14))
    # A DRAWN building contour is the more specific shape and still wins.
    with_contour = l_fixture()
    with_contour["map3d"]["outline"] = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
    lvl2 = [p for p in scene_recipe.compose_scene(
        with_contour, plan_width_m=PLAN_W)["plates"] if not p.get("room_id")]
    check("a drawn building contour still wins over the boundary",
          lvl2[0]["outline"] == [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0],
                                 [-5.0, 5.0]], str(lvl2[0]["outline"]))
    check("the room plates are untouched by all of it",
          [p for p in sc["plates"] if p.get("room_id") == "a"]
          == [p for p in sq["plates"] if p.get("room_id") == "a"])

    # ── Nr. 4: the relief is clipped at the polygon ─────────────────────
    # The grid is the default 16 cells → 17 support points per side, point
    # (i, j) at lattice (i/16, j/16) of the terrain frame — the square of
    # edge 10 over the L's bounding box, which is centred on the pin, so the
    # metre is ((i/16)−0.5)·10 exactly as before.
    #   i = j = 12  →  (2.5, 2.5): inside the NOTCH, so outside the L → 0.
    #   i = 4, j = 12 → (−2.5, 2.5): inside the L (and inside the outdoor
    #     "garden", which is a RELIEF room, so nothing else pins it) → the
    #     unclipped value survives unchanged.
    clipped = scene_recipe.compose_scene(l_fixture(relief=True),
                                         plan_width_m=PLAN_W)["terrain"]["grid"]
    plain = scene_recipe.compose_scene(
        {**l_fixture(relief=True),
         "map3d": {k: v for k, v in l_fixture(relief=True)["map3d"].items()
                   if k != "boundary"}},
        plan_width_m=PLAN_W)["terrain"]["grid"]
    check("the notch point (2.5, 2.5) would carry a height without the L",
          plain[12][12] != 0.0, str(plain[12][12]))
    check("...and is pinned to 0 by the boundary clip",
          clipped[12][12] == 0.0, str(clipped[12][12]))
    check("a point INSIDE the L keeps its unclipped height",
          clipped[12][4] == plain[12][4] and plain[12][4] != 0.0,
          f"{clipped[12][4]} vs {plain[12][4]}")
    check("the rim stays pinned as before",
          all(clipped[0][i] == 0.0 and clipped[16][i] == 0.0
              for i in range(17)))

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
    check("ground anchor law unchanged (mesh hangs walk_y below level 0)",
          near(b.get("bottom_y", 99), -4.0), str(b.get("bottom_y")))
    check("no cutouts on the model", "cutouts" not in b)
    check("no overlay rooms", not [r for r in sc["rooms"] if r.get("overlay")])
    check("the outside outdoor room gets its § A5 plate back",
          "zone" in {p.get("room_id") for p in sc["plates"]},
          str(sorted({p.get("room_id") for p in sc["plates"] if p.get("room_id")})))
    plain = scene_recipe.compose_scene(area_fixture(True), plan_width_m=PLAN_W,
                                       building_meta=GROUND_META)
    check("the flag moves the signature",
          sc["signature"] != plain["signature"])


def relief_fixture(seed: int = 1, amplitude: float = 2.0, *,
                   relief: bool = True, road_flat: bool = True) -> dict:
    """Detail scene on the scatter fixture: field (relief) + road (flat).

    The sanitizer is bypassed on purpose — compose_scene is the unit under
    test here, and the fixture feeds it the already-clean map3d a saved
    location would carry (area_model + area_detail + relief, v5.2 Nr. 14).
    The road gets a prop of its own so the "flat rooms do not move by a
    single digit" rule has something to measure.
    """
    loc = scatter_fixture(road=True)
    loc["map3d"]["area_model"] = True
    loc["map3d"]["area_detail"] = True
    if relief:
        loc["map3d"]["relief"] = {"amplitude_m": amplitude, "seed": seed}
    for room in loc["rooms"]:
        if room["id"] == "road":
            if road_flat:
                room["layout"]["relief_flat"] = True
            # (1.2, 0.12) m from the road's min corner (−4, −2.2) is world
            # (−2.8, −2.08), inside the band — the metric twin of the old
            # rect fraction [0.3, 0.3].
            room["layout"]["props"] = [{"prop_id": "table",
                                        "at": [1.2, 0.12]}]
    return loc


def test_terrain() -> None:
    print("\n[17] terrain relief (v5.2 Nr. 14)")
    stub_props()
    from app.core.scatter_curves import terrain_height
    sc = scene_recipe.compose_scene(relief_fixture(), plan_width_m=PLAN_W)
    flat_sc = scene_recipe.compose_scene(relief_fixture(relief=False),
                                         plan_width_m=PLAN_W)
    terrain = sc.get("terrain") or {}
    grid = terrain.get("grid") or []
    check("17 × 17 support points",
          len(grid) == 17 and all(len(row) == 17 for row in grid),
          f'{len(grid)} rows')
    # step = extent / 16 = 10 / 16 = 0.625 metres; the amplitude is the
    # authored 2.0 m, k = 1.
    check("step = extent/16 = 0.625, amplitude = the authored 2.0 m",
          near(terrain.get("step", 0), 0.625)
          and near(terrain.get("amplitude_m", 0), 2.0),
          f'{terrain.get("step")}/{terrain.get("amplitude_m")}')
    check("no relief field without map3d.relief", "terrain" not in flat_sc)
    # Rand = 0: the whole outer ring, so neighbouring tiles meet seamlessly.
    border = ([grid[0][i] for i in range(17)] + [grid[16][i] for i in range(17)]
              + [row[0] for row in grid] + [row[16] for row in grid])
    check("the border ring is zero", all(h == 0.0 for h in border),
          str(sorted({abs(h) for h in border})))
    # Interior point (i=1, j=1), independently derived: the per-point seed is
    # (1 + 1·73856093 + 1·19349663) & 0xFFFFFFFF = 93205757; ONE xorshift32
    # draw, mapped [0,1) → [−1,1), × amplitude 2.0.
    ref = next(xorshift32_ref(1 + 73856093 + 19349663))
    expect_11 = round((ref / 2 ** 32 * 2 - 1) * 2.0, 4)
    check("interior point (1,1) = hash draw × amplitude",
          near(grid[1][1], expect_11, 1e-9),
          f'{grid[1][1]} vs {expect_11}')
    # Flat hull = 0: (i=3, j=5) sits at lattice (0.1875, 0.3125) = world
    # (−3.125, −1.875), inside the road band (x −4…0, z −2.2…−1.8) that
    # carries relief_flat.
    check("a point inside the relief_flat road hull is zero",
          grid[5][3] == 0.0, str(grid[5][3]))
    unflagged = scene_recipe.compose_scene(relief_fixture(road_flat=False),
                                           plan_width_m=PLAN_W)
    check("without relief_flat that very point carries a height",
          unflagged["terrain"]["grid"][5][3] != 0.0,
          str(unflagged["terrain"]["grid"][5][3]))
    # Bilinear at the centre of one cell: tx = ty = 0.5 turns the weights
    # (1−tx)(1−ty), tx(1−ty), (1−tx)ty, tx·ty all into ¼ — the plain mean of
    # the four corners. Cell (i=1, j=1) → u = v = 1.5/16 = 0.09375.
    mid = terrain_height(grid, 1.5 / 16, 1.5 / 16)
    mean = (grid[1][1] + grid[1][2] + grid[2][1] + grid[2][2]) / 4
    check("bilinear midpoint of a 2×2 patch = the corner average",
          near(mid, mean, 1e-9), f'{mid} vs {mean}')
    # The field's manual anchor is the room centre: layout at [2, 2] m of a
    # room at (−4, −4) → world (−2, −2), i.e. lattice coordinate
    # (−2 + 5)/10 = 0.3 of the terrain frame.
    # 0.3 × 16 = 4.8, so the sample sits in cell (4, 4) at tx = ty = 0.8 and
    # the bilinear weights are 0.04 / 0.16 / 0.16 / 0.64. The two southern
    # corners (j = 5 → v = 0.3125) lie in the flat road band and are 0, so by
    # hand the lift is 0.04·grid[4][4] + 0.16·grid[4][5].
    def prop_of(scene_dict, room_id, anchor_world=None):
        return [m for m in scene_dict["models"] if m["role"] == "prop"
                and m["room_id"] == room_id
                and (anchor_world is None
                     or (near(m["anchor"][0], anchor_world[0])
                         and near(m["anchor"][1], anchor_world[1])))][0]

    check("the road band flattens the two southern corners of that cell",
          grid[5][4] == 0.0 and grid[5][5] == 0.0,
          f'{grid[5][4]}/{grid[5][5]}')
    lift_anchor = (0.04 * grid[4][4] + 0.16 * grid[4][5]
                   + 0.16 * grid[5][4] + 0.64 * grid[5][5])
    field_anchor = prop_of(sc, "field", (-2.0, -2.0))
    field_flat = prop_of(flat_sc, "field", (-2.0, -2.0))
    check("a prop in the relief room stands on the field: base + lift",
          near(field_anchor["bottom_y"],
               round(field_flat["bottom_y"] + lift_anchor, 4), 1e-9),
          f'{field_anchor["bottom_y"]} vs '
          f'{field_flat["bottom_y"]} + {round(lift_anchor, 4)}')
    check("the hand-weighted lift equals the bilinear sampler",
          near(lift_anchor, terrain_height(grid, 0.3, 0.3), 1e-9),
          f'{lift_anchor} vs {terrain_height(grid, 0.3, 0.3)}')
    # The prop's marker rides with it — sampled at the PLACEMENT anchor, so
    # mesh and seat rise by the same amount.
    marker = [m for m in sc["markers"] if m["room_id"] == "field"][0]
    marker_flat = [m for m in flat_sc["markers"] if m["room_id"] == "field"][0]
    check("its prop marker rises by the same lift",
          near(marker["y_world"],
               round(marker_flat["y_world"] + lift_anchor, 4), 1e-9),
          f'{marker["y_world"]} vs {marker_flat["y_world"]} '
          f'+ {round(lift_anchor, 4)}')
    # A scattered copy: its anchor is a world metre, back to a plan fraction
    # via frac = anchor/extent + 0.5 (rounding of the payload anchor keeps
    # this within a ten-thousandth of a metre).
    scattered = [m for m in sc["models"] if m["role"] == "prop"
                 and m["room_id"] == "field" and m is not field_anchor][0]
    su = scattered["anchor"][0] / EXTENT + 0.5
    sv = scattered["anchor"][1] / EXTENT + 0.5
    scattered_flat = prop_of(flat_sc, "field", scattered["anchor"])
    check("a scattered copy is lifted at ITS own anchor too",
          near(scattered["bottom_y"],
               scattered_flat["bottom_y"] + terrain_height(grid, su, sv), 1e-3),
          f'{scattered["bottom_y"]} vs {scattered_flat["bottom_y"]} + '
          f'{round(terrain_height(grid, su, sv), 4)}')
    # The flat road: NOT ONE number may move against the relief-free compose.
    road = prop_of(sc, "road")
    road_flat = prop_of(flat_sc, "road")
    check("a prop in the relief_flat road is bit-identical without relief",
          road == road_flat,
          f'{road["bottom_y"]} vs {road_flat["bottom_y"]}')
    plates = {p.get("room_id"): p for p in sc["plates"] if p.get("room_id")}
    check("the relief room's plate is flagged for draping",
          plates["field"].get("relief") is True
          and "relief" not in plates["road"],
          str({r: p.get("relief") for r, p in plates.items()}))
    check("level plates are never flagged",
          all("relief" not in p for p in sc["plates"] if not p.get("room_id")))
    check("no plate is flagged without a relief",
          all("relief" not in p for p in flat_sc["plates"]))
    base = sc["signature"]
    check("the same seed and amplitude reproduce the scene",
          scene_recipe.compose_scene(relief_fixture(),
                                     plan_width_m=PLAN_W)["signature"] == base)
    check("a reroll (seed) moves the signature",
          scene_recipe.compose_scene(relief_fixture(seed=2),
                                     plan_width_m=PLAN_W)["signature"] != base)
    check("a new amplitude moves the signature",
          scene_recipe.compose_scene(relief_fixture(amplitude=1.0),
                                     plan_width_m=PLAN_W)["signature"] != base)
    check("relief_flat rides in the room signature",
          scene_recipe.compose_scene(relief_fixture(road_flat=False),
                                     plan_width_m=PLAN_W)["signature"] != base)


# ── The yard: placements on the ground (§ A13a) ─────────────────────────
# The ground room `__ground__` carries a REDUCED layout: props and markers
# only, and their `at` is a LOCATION-LOCAL metre — there is no room rectangle
# to add a min corner from. Everything else about the ground is unchanged: no
# plate, no wall, no room block, no doorway.
#
# The fixture is the L boundary of block [15] (bounding box −5…5 on both axes,
# the notch is the quadrant x > 0 ∧ z > 0), so the numbers below can be read
# off the same picture.
GROUND_ID = "__ground__"


def ground_fixture(*, props=(), markers=(), relief: bool = False,
                   solo: bool = True) -> dict:
    """The L location plus a furnished yard. ``solo`` drops the two ordinary
    rooms, so the scatter run below has NO sibling keep-outs to reason about;
    without it the yard stands beside room "a" and "garden" as usual."""
    loc = l_fixture(relief=relief)
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
    # has no plate either, so the prop stands PROP_CLEARANCE (0.01 m) over
    # the storey-0 floor — 0.10 m lower than the same prop in a built room
    # (ROOM_PLATE_TOP), and exactly as an outdoor room's prop stands.
    sc = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [3.0, -2.0]}],
                       markers=[{"at": [-1.0, 2.0], "animation": "sit"}]),
        plan_width_m=PLAN_W)
    props = [m for m in sc["models"] if m["role"] == "prop"]
    check("one prop spec, room_id = the ground",
          len(props) == 1 and props[0]["room_id"] == GROUND_ID,
          str([(p["room_id"], p["anchor"]) for p in props]))
    check("its anchor IS the stored local metre (3, −2)",
          props and props[0]["anchor"] == [3.0, -2.0], str(props[0]["anchor"]))
    check("bottom_y = 0 + PROP_CLEARANCE (no plate on the ground) = 0.01",
          near(props[0]["bottom_y"], 0.01), str(props[0]["bottom_y"]))
    # The same prop inside room "a" (x −4, y −4) stands on a plate: the
    # contrast is what proves the ground took the outdoor branch.
    in_room = fixture()
    for room in in_room["rooms"]:
        if room["id"] == "a":
            room["layout"]["props"] = [{"prop_id": "table", "at": [1.0, 1.0]}]
    room_prop = [m for m in scene_recipe.compose_scene(
        in_room, plan_width_m=PLAN_W)["models"] if m["role"] == "prop"][0]
    check("...while a room prop keeps its plate: 0.10 + 0.01 = 0.11",
          near(room_prop["bottom_y"], 0.11), str(room_prop["bottom_y"]))
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
    # The table brings its own seat marker: 0.01 (clearance, no plate) plus
    # the marker's composed height over the placement — in a room the same
    # seat sits ROOM_PLATE_TOP = 0.10 m higher.
    seat = [m for m in sc["markers"] if m["source"] == "prop"]
    room_seat = [m for m in scene_recipe.compose_scene(
        in_room, plan_width_m=PLAN_W)["markers"] if m["source"] == "prop"]
    check("the yard's prop marker rides 0.10 lower than the room's",
          len(seat) == 1 and len(room_seat) == 1
          and near(room_seat[0]["y_world"] - seat[0]["y_world"], 0.10),
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
    # ── On the relief the yard IS the terrain ───────────────────────────
    # Terrain frame = the boundary's bounding box, edge 10 centred on the pin,
    # so x0 = z0 = −5 and the 16-cell lattice coordinate of (3, −2) is
    # u = (3 + 5)/10 = 0.8, v = (−2 + 5)/10 = 0.3.
    # u·16 = 12.8 → i = 12, tx = 0.8;  v·16 = 4.8 → j = 4, ty = 0.8.
    rel = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [3.0, -2.0]}],
                       relief=True), plan_width_m=PLAN_W)
    grid = rel["terrain"]["grid"]
    north = grid[4][12] * 0.2 + grid[4][13] * 0.8
    south = grid[5][12] * 0.2 + grid[5][13] * 0.8
    lift = north * 0.2 + south * 0.8
    check("the hand-weighted lift is not flat (the fixture would prove "
          "nothing at 0)", abs(lift) > 1e-6, str(lift))
    rel_prop = [m for m in rel["models"] if m["role"] == "prop"][0]
    check("the yard prop stands on the terrain: 0.01 + the bilinear sample",
          near(rel_prop["bottom_y"], round(0.01 + lift, 4), 1e-3),
          f'{rel_prop["bottom_y"]} vs {round(0.01 + lift, 4)}')
    # The ground pins NOTHING flat: the notch is zero because it is outside
    # the boundary, never because a yard hull flattened it. Compared against
    # the very same location WITHOUT the yard — rooms and all, so the only
    # difference is the furnished ground.
    beside = scene_recipe.compose_scene(
        ground_fixture(props=[{"prop_id": "table", "at": [3.0, -2.0]}],
                       relief=True, solo=False),
        plan_width_m=PLAN_W)["terrain"]["grid"]
    plain = scene_recipe.compose_scene(l_fixture(relief=True),
                                       plan_width_m=PLAN_W)["terrain"]["grid"]
    check("the field is bit-identical with and without the furnished yard",
          beside == plain)
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
        "props": [{"prop_id": "table", "at": [3.0, -2.0]}],
        "markers": [{"at": [-1.0, 2.0], "animation": "sit"}]})
    check("only props and markers survive",
          sorted(clean) == ["markers", "props"], str(sorted(clean)))
    check("...the placement itself is untouched",
          clean["props"] == [{"prop_id": "table", "at": [3.0, -2.0]}],
          str(clean["props"]))
    check("an empty yard stores no layout at all",
          sanitize_ground_layout({"outline": [[0, 0], [1, 0], [1, 1]]}) == {})
    rooms = [{"id": GROUND_ID, "layout": {
        "x": 1.0, "y": 1.0, "w": 2.0, "d": 2.0,
        "outline": [[0, 0], [2, 0], [2, 2]],
        "props": [{"prop_id": "table", "at": [3.0, -2.0]}]}}]
    _sanitize_rooms_layout(rooms)
    check("the room-list sanitizer routes the ground the same way",
          rooms[0]["layout"] == {"props": [{"prop_id": "table",
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
                "markers": [{"at": [3.0, 1.5], "animation": "idle",
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
          len(edge0) == 2 and all(near(w["outward_normal"][0], -1.0)
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


def main() -> int:
    test_scalars()
    test_scale_is_one()
    test_plates()
    test_room_walls()
    test_room_floor_offset()
    test_no_walls()
    test_doorways()
    test_threshold_base_y()
    test_contour_walls()
    test_no_building_entrance()
    test_rooms_without_layout()
    test_openings_without_walls()
    test_contour_wall_texture()
    test_area_locations()
    test_elevator()
    test_style()
    test_building_spec()
    test_room_and_prop_specs()
    test_markers_figures()
    test_clip_outline()
    test_signature()
    test_curved_outline()
    test_scatter()
    test_boundary_openings()
    test_boundary_polygon()
    test_area_detail()
    test_terrain()
    test_ground_placements()
    test_room_rotation()
    test_rotation_outside_boundary()
    test_rotation_shared_walls()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
