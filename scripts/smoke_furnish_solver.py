#!/usr/bin/env python3
"""Smoke run for the furnishing solver v2 (plan-furnish-v2.md § 2, task 2).

Pure geometry: no world, no DB, no LLM, no GPU — ``furnish_solver.solve`` is
called directly and every expected number below is derived BY HAND from the
rule, never read off a previous run.

Usage:  ./.venv/bin/python scripts/smoke_furnish_solver.py

THE FIXTURE (used by most rows)

    outline   [[0,0],[6,0],[6,4],[0,4]]  — 6 m east/west × 4 m north/south,
              x → east, z → south, centroid (3, 2), area 24 m²
    door      edge 2 (the south edge, running (6,4) → (0,4)) at 0.5,
              width 1.0, height 2.1
    window    edge 0 (the north edge, running (0,0) → (6,0)) at 0.5,
              width 1.2, sill 0.9, height 1.2
    storey    3.0 m

    door strip    midpoint (3, 4), depth max(0.6, 1.0) = 1.0 into the room,
                  width 1.0 + 0.4 = 1.4  →  x 2.3…3.7, z 3.0…4.0, y 0…2.1
    window strip  midpoint (3, 0), depth 0.6, width 1.2 + 0.4 = 1.6
                  →  x 2.2…3.8, z 0…0.6, y 0.9…2.1

    props   table 1.6×0.8×0.75 floor   chair 0.5×0.5×0.9 floor
            picture 0.8×0.05×0.6 wall  sofa 2.0×0.9×0.85 floor
            lamp 0.4×0.4×1.0 ceiling   candle 0.1×0.1×0.3 surface
            rug 2.0×1.5×0.02 floor     wardrobe 1.2×0.6×2.0 floor
            curtain 1.6×0.1×2.2 wall   shelf 0.8×0.25×0.3 wall
            mug 0.08×0.08×0.1 surface (2 variants)

THE TURN (ruling 2026-09-06, fixes a v1 bug). Yaw turns like the renderer,
``R_y(+yaw)``: a local ``(x, z)`` lands at ``(x·cos r + z·sin r,
−x·sin r + z·cos r)``. Two hand checks below:

* a table at yaw 90 has its FRONT at compass 90 = east, so a chair
  ``in_front_of`` it stands EAST of it (row T1);
* a wall piece looks into the room, so its yaw is the compass of the opposite
  direction:  wall_n → 0 (S), wall_e → 270 (W), wall_s → 180 (N),
  wall_w → 90 (E)  — row T2 checks all four against the edges' inward normals.

ROW BY ROW — the arithmetic

1 around.  ``table center facing s`` lands on the centre-most cell of the
  walkway grid (see row 10): cell 2.5 × 1.7 m, 2 × 2 cells over the 6 × 4 box
  at (1.5, 1.0), (4.5, 1.0), (1.5, 3.0), (4.5, 3.0); all four are 1.803 m from
  the centroid, so the north-west one wins → table at [1.5, 1.0], yaw 0.
  Seats: capacity per side = floor((L + 0.1) / (0.5 + 0.1)); front and back
  are the 1.6 m sides → floor(1.7/0.6) = 2, left and right the 0.8 m sides →
  floor(0.9/0.6) = 1; total 2+2+1+1 = 6. The six chairs are handed out one at
  a time to the side with the lowest assigned/capacity (ties: longer side, then
  front, right, back, left) → front, back, right, left, front, back.
  Distance from the table centre = half extent of that side + 0.5/2 + 0.05:
  front/back 0.4 + 0.25 + 0.05 = 0.70, left/right 0.8 + 0.25 + 0.05 = 1.10.
  Even spread along a side of length L for k seats: seat i at
  (i+1)·L/(k+1) − L/2, i.e. ±(1.6/3)/2 = ±0.2667 for the two front chairs and
  0 for a single one. So:
      front  [1.5 − 0.2667, 1.0 + 0.70] = [1.23, 1.70]  and  [1.77, 1.70],
             both facing the table → yaw 180
      back   [1.23, 0.30] and [1.77, 0.30], yaw 0
      right  [1.5 − 1.10, 1.0] = [0.40, 1.00], yaw 90
      left   [2.60, 1.00], yaw 270
  A seventh chair finds no side with capacity left → unplaced,
  "no seat around … (capacity 6) — lower the count or use beside".

2 picture over the sofa (fixture WITHOUT the window — with it the picture
  would have to dodge the window strip, which is row 8's subject).
  ``sofa wall_n facing room`` → yaw 0, pushed off the wall by 0.9/2 + 0.05 =
  0.5, centred on the 6 m wall: x = 1.0 + 0.5·(6 − 2.0) = 3.0 → [3.0, 0.5],
  box y 0…0.85.  ``picture wall_above sofa``: the sofa's back edge midpoint is
  (3.0, 0.5 − 0.45) = (3.0, 0.05), 0.05 m from the north edge ≤ 0.15 → wall n;
  x = the sofa's x = 3.0; base = sofa top 0.85 + 0.2 = 1.05 (inside the clamp
  [0.3, 3.0 − 0.6 = 2.4]); z = 0 + 0.05/2 + 0.02 = 0.045.
  The two QUADS overlap (picture x 2.6…3.4, z 0.02…0.07 lies inside the sofa's
  x 2.0…4.0, z 0.05…0.95) but the BOXES do not: 0.85 ≤ 1.05.

3 picture base defaults.  ``picture wall_e`` without base_m → centred at
  1.5 m → base 1.5 − 0.6/2 = 1.2.  base_m 2.9 → clamped to 3.0 − 0.6 = 2.4.
  base_m 0.1 → clamped up to 0.3.

4 candle on the table.  Raster over the table top, step 0.15, inset by the
  child's half extent 0.05: x ticks over ±(0.8 − 0.05) = ±0.75 →
  floor(0.75/0.15) = 5 steps each way, z ticks over ±(0.4 − 0.05) = ±0.35 → 2.
  Order is centre first, x fastest → candle 1 at [0, 0], candle 2 at [0.15, 0]
  (both CHILD FRAME: on = the table's id, yaw 0, no offset_y).
  props.stack_on_support(table, candle) = 0 + 0 + 0.75 − 0 = 0.75.

5 surface budget / raster.  60 mugs on the table: the budget is
  0.4 · 1.6 · 0.8 = 0.512 m² against 60 · 0.08² = 0.384 m², so the budget never
  bites — the RASTER does. Inset 0.04 → x over ±0.76: floor(0.76/0.15) = 5 →
  11 positions (−0.75 … 0.75), z over ±0.36: floor(0.36/0.15) = 2 → 5
  positions → 55 cells. 55 mugs placed, 5 unplaced with "surface … is full".
  The mug has 2 variants → variant = ordinal mod 2 = 0, 1, 0, 1, …

6 pendant lamp.  ``lamp above table`` → at = the table's centre, base =
  max(1.9, 3.0 − 1.0) = 2.0.

7 door clearance.  Room [[0,0],[4,0],[4,3],[0,3]] (4 m of south wall, 3 m
  deep), door centred on the south edge, width 1.0 → strip x 1.3…2.7,
  z 2.0…3.0.  ``wardrobe wall_s`` → yaw 180, z = 3 − (0.3 + 0.05) = 2.65,
  usable stretch 4 − 1.2 = 2.8, x = 4 − (0.6 + f·2.8).  The wardrobe clears the
  strip only for x ≤ 0.7 (f ≥ 0.9643) or x ≥ 3.3 (f ≤ 0.0357). centred_offsets
  walks 0.5, then ±k·0.25/2.8/2 = ±k·0.044643, and the first k that reaches
  either end is k = 11 → f = 0.991071 first → x = 4 − (0.6 + 2.775) = 0.625.
  → wardrobe at [0.625, 2.65].

8 window.  (a) ``wardrobe wall_n``: its box 0…2.0 cuts the window strip's
  0.9…2.1, so the centred spot x = 3.0 is out. It clears the strip for
  x ≤ 1.6 (f ≤ 0.2083) or x ≥ 4.4 (f ≥ 0.7917); with usable 4.8 the step is
  0.25/4.8/2 = 0.026042 and k = 12 is the first to reach either end → f =
  0.8125 first → x = 0.6 + 0.8125·4.8 = 4.5 → [4.5, 0.35].
  (b) ``shelf wall_n base_m 2.3`` → box 2.3…2.6 clears 0.9…2.1 → the centred
  spot stands: x = 0.4 + 0.5·(6 − 0.8) = 3.0, z = 0.25/2 + 0.02 = 0.145.
  (c) ``curtain at_opening window`` → centred on the window midpoint (3, 0),
  base = 0.9 + 1.2 + 0.15 − 2.2 = 0.05, z = 0.1/2 + 0.02 = 0.07; the window's
  own zone is ignored for this piece. Wall budget of the north wall:
  0.6 · (6 − 1.2) = 2.88 m ≥ curtain 1.6 + shelf 0.8 = 2.4 m.
  Curtain box 0.05…2.25 and shelf box 2.3…2.6 do not meet, so both stand on
  the same stretch of wall.

9 rug.  ``rug under table`` → centred on the table, the table's yaw, height
  0.02 ≤ 0.05 → an underlay: no occupancy, no floor budget. A chair placed
  ``around`` the table afterwards therefore still finds its front seat at
  [1.5, 1.70].

10 center group.  Three tables, all ``center``: cell = footprint + 0.9 m
  gangway = 2.5 × 1.7 m; the 6 × 4 bounding box takes floor(6/2.5) = 2 by
  floor(4/1.7) = 2 whole cells, spread evenly → centres x ∈ {1.5, 4.5},
  z ∈ {1.0, 3.0}. All four are equidistant (1.803 m) from the centroid, so the
  order is north-west first: (1.5,1.0), (4.5,1.0), (1.5,3.0), (4.5,3.0).
  Default facing is `door`, so each table looks at the door midpoint (3, 4):
  yaw 26.57°, 333.43°, 56.31°. The third one's turned hull reaches x ≤ 2.277
  (1.6·cos56.31 + 0.8·sin56.31 = 1.553 wide) and stops short of the door
  strip's x 2.3. Three tables placed, centre distances 3.0 / 2.0 / 3.606 m.

11 wrong pass.  A wall piece with anchor `center` → unplaced in pass "wall"
  with "a wall piece needs a wall anchor"; a floor piece with anchor `on` →
  "anchor 'on' is for surface pieces". (A yard without walls is not the
  solver's business — the needs validator strikes wall pieces there.)

12 determinism.  Row 1 solved twice → byte-identical JSON.

13 existing occupancy.  An existing composed child (candle, offset_y 0.75,
  on the table) sits exactly on the first raster cell, so a new candle skips to
  [0.15, 0].
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import furnish_geometry as fg  # noqa: E402
from app.core import furnish_solver as fs  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a: float, b: float, tol: float = 0.011) -> bool:
    return abs(float(a) - float(b)) <= tol


def at_near(at, x: float, z: float, tol: float = 0.011) -> bool:
    return near(at[0], x, tol) and near(at[1], z, tol)


OUTLINE = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
DOOR = {"edge": 2, "at": 0.5, "width_m": 1.0, "height_m": 2.1, "type": "door"}
WINDOW = {"edge": 0, "at": 0.5, "width_m": 1.2, "height_m": 1.2,
          "sill_m": 0.9, "type": "window"}
OPENINGS = [DOOR, WINDOW]

PROPS = {
    "table": {"width_m": 1.6, "depth_m": 0.8, "height_m": 0.75, "mount": "floor"},
    "chair": {"width_m": 0.5, "depth_m": 0.5, "height_m": 0.9, "mount": "floor"},
    "picture": {"width_m": 0.8, "depth_m": 0.05, "height_m": 0.6, "mount": "wall"},
    "sofa": {"width_m": 2.0, "depth_m": 0.9, "height_m": 0.85, "mount": "floor"},
    "lamp": {"width_m": 0.4, "depth_m": 0.4, "height_m": 1.0, "mount": "ceiling"},
    "candle": {"width_m": 0.1, "depth_m": 0.1, "height_m": 0.3, "mount": "surface"},
    "rug": {"width_m": 2.0, "depth_m": 1.5, "height_m": 0.02, "mount": "floor"},
    "wardrobe": {"width_m": 1.2, "depth_m": 0.6, "height_m": 2.0, "mount": "floor"},
    "curtain": {"width_m": 1.6, "depth_m": 0.1, "height_m": 2.2, "mount": "wall"},
    "shelf": {"width_m": 0.8, "depth_m": 0.25, "height_m": 0.3, "mount": "wall"},
    "mug": {"width_m": 0.08, "depth_m": 0.08, "height_m": 0.1,
            "mount": "surface", "variants": 2},
}


def run(plan, *, outline=None, openings=None, existing=None, storey=3.0):
    return fs.solve(outline_m=outline or OUTLINE,
                    openings=OPENINGS if openings is None else openings,
                    existing=existing or [], plan=plan, props=PROPS,
                    storey_height_m=storey)


def by_prop(placed, prop_id):
    return [p for p in placed if p["prop_id"] == prop_id]


def reasons(unplaced):
    return " | ".join(u["reason"] for u in unplaced)


# ── T1/T2 turn direction ────────────────────────────────────────────────

def row_turn_direction() -> None:
    print("\nT — turn direction (R_y(+yaw), front compass = yaw)")
    out = run([{"prop": "table", "count": 1, "anchor": "center", "facing": "e"},
               {"prop": "chair", "count": 1, "anchor": "in_front_of",
                "ref": "table"}])
    table = by_prop(out["placed"], "table")
    chair = by_prop(out["placed"], "chair")
    check("the yaw-90 table and its chair are placed",
          len(table) == 1 and len(chair) == 1, reasons(out["unplaced"]))
    if table and chair:
        check("a yaw-90 table faces EAST", near(table[0]["yaw"], 90.0, 0.05),
              json.dumps(table[0]))
        # Front half extent 0.4 + chair half 0.25 + first gap 0.15 = 0.80 east.
        check("the chair in front of it stands EAST of it",
              at_near(chair[0]["at"], table[0]["at"][0] + 0.80,
                      table[0]["at"][1]),
              json.dumps(chair[0]["at"]))
        check("and it looks back west at the table",
              near(chair[0]["yaw"], 270.0, 0.05), json.dumps(chair[0]))

    # The wall table, derived from the front rule for all four walls: the front
    # points into the room, so it equals the edge's INWARD normal.
    for wall, want in (("n", 0.0), ("e", 270.0), ("s", 180.0), ("w", 90.0)):
        out = run([{"prop": "picture", "count": 1, "anchor": f"wall_{wall}"}],
                  openings=[DOOR])
        got = by_prop(out["placed"], "picture")
        ok = len(got) == 1 and near(got[0]["yaw"], want, 0.05)
        inward = fg.compass_vec(want)
        edge = fg.wall_edges(fg.normalize_outline(OUTLINE)[0], (3.0, 2.0),
                             wall)[0]
        want_n = fg.edge_geometry(fg.normalize_outline(OUTLINE)[0],
                                 (3.0, 2.0), edge)[2]
        check(f"wall_{wall} → yaw {want:.0f}, front into the room",
              ok and near(inward[0], want_n[0]) and near(inward[1], want_n[1]),
              json.dumps(got))


# ── 1 around ────────────────────────────────────────────────────────────

def row_around() -> None:
    print("\n1 — chairs around a table")
    plan = [{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
            {"prop": "chair", "count": 6, "anchor": "around", "ref": "table"}]
    out = run(plan)
    table = by_prop(out["placed"], "table")
    chairs = by_prop(out["placed"], "chair")
    check("the table takes the centre-most walkway cell",
          len(table) == 1 and at_near(table[0]["at"], 1.5, 1.0)
          and near(table[0]["yaw"], 0.0, 0.05), json.dumps(table))
    check("six chairs placed", len(chairs) == 6,
          f"{len(chairs)}: {reasons(out['unplaced'])}")
    want = sorted([(1.23, 1.70, 180.0), (1.77, 1.70, 180.0),
                   (1.23, 0.30, 0.0), (1.77, 0.30, 0.0),
                   (0.40, 1.00, 90.0), (2.60, 1.00, 270.0)])
    got = sorted((round(c["at"][0], 2), round(c["at"][1], 2), c["yaw"])
                 for c in chairs)
    check("2 + 2 + 1 + 1 seats, each facing the table",
          len(got) == len(want)
          and all(near(g[0], w[0]) and near(g[1], w[1]) and near(g[2], w[2], 0.05)
                  for g, w in zip(got, want)), json.dumps(got))

    plan[1]["count"] = 7
    out7 = run(plan)
    check("a seventh chair has no seat", len(by_prop(out7["placed"], "chair")) == 6
          and len(out7["unplaced"]) == 1, reasons(out7["unplaced"]))
    check("and the reason names the capacity and an alternative",
          bool(out7["unplaced"])
          and "capacity 6" in out7["unplaced"][0]["reason"]
          and out7["unplaced"][0]["reason"].endswith("use beside")
          and out7["unplaced"][0]["pass"] == "floor",
          reasons(out7["unplaced"]))


# ── 2 picture over the sofa ─────────────────────────────────────────────

def row_wall_above() -> None:
    print("\n2 — a picture over the sofa (3D occupancy)")
    out = run([{"prop": "sofa", "count": 1, "anchor": "wall_n",
                "facing": "room"},
               {"prop": "picture", "count": 1, "anchor": "wall_above",
                "ref": "sofa"}], openings=[DOOR])
    sofa = by_prop(out["placed"], "sofa")
    pic = by_prop(out["placed"], "picture")
    check("the sofa stands centred on the north wall",
          len(sofa) == 1 and at_near(sofa[0]["at"], 3.0, 0.5),
          json.dumps(sofa))
    check("the picture hangs over it at base 0.85 + 0.2 = 1.05",
          len(pic) == 1 and near(pic[0]["at"][0], 3.0)
          and near(pic[0].get("offset_y", -1), 1.05),
          json.dumps(pic) + reasons(out["unplaced"]))
    if sofa and pic:
        quad_s = fg.rect_corners(sofa[0]["at"][0], sofa[0]["at"][1],
                                 2.0, 0.9, sofa[0]["yaw"])
        quad_p = fg.rect_corners(pic[0]["at"][0], pic[0]["at"][1],
                                 0.8, 0.05, pic[0]["yaw"])
        check("their quads overlap but their height intervals do not",
              fg.rects_overlap(quad_s, quad_p)
              and not fg.spans_overlap(0.0, 0.85, 1.05, 1.65))


# ── 3 wall base clamp ───────────────────────────────────────────────────

def row_wall_base() -> None:
    print("\n3 — the wall base and its clamp")
    for base_m, want in ((None, 1.2), (2.9, 2.4), (0.1, 0.3)):
        item = {"prop": "picture", "count": 1, "anchor": "wall_e"}
        if base_m is not None:
            item["base_m"] = base_m
        out = run([item])
        got = by_prop(out["placed"], "picture")
        check(f"base_m {base_m} → {want}",
              len(got) == 1 and near(got[0].get("offset_y", -1), want, 1e-6),
              json.dumps(got) + reasons(out["unplaced"]))
    check("and it hangs 0.045 m off the east wall (0.05/2 + 0.02)",
          at_near(by_prop(run([{"prop": "picture", "count": 1,
                                "anchor": "wall_e"}])["placed"],
                          "picture")[0]["at"], 5.955, 2.0))


# ── 4 candle on the table ───────────────────────────────────────────────

def row_on_support() -> None:
    print("\n4 — candles on the table (child frame)")
    out = run([{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
               {"prop": "candle", "count": 2, "anchor": "on", "ref": "table"}])
    table = by_prop(out["placed"], "table")
    candles = by_prop(out["placed"], "candle")
    check("both candles are children of the table",
          len(candles) == 2 and all(c.get("on") == table[0]["id"]
                                    for c in candles), json.dumps(candles))
    check("the first sits on the centre cell, the second 0.15 m beside it",
          len(candles) == 2 and candles[0]["at"] == [0.0, 0.0]
          and candles[1]["at"] == [0.15, 0.0], json.dumps(candles))
    check("a child stores no offset_y and a relative yaw of 0",
          all("offset_y" not in c and c["yaw"] == 0.0 for c in candles))
    from app.core.props import stack_on_support
    composed = stack_on_support(
        {"ground_offset_m": 0.0, "offset_y": 0.0, "height_m": 0.75},
        {"ground_offset_m": 0.0})
    check("their composed base would be the table top 0.75",
          near(composed, 0.75, 1e-9), str(composed))


# ── 5 surface raster and budget ─────────────────────────────────────────

def row_surface_budget() -> None:
    print("\n5 — 60 mugs on a table with 55 raster cells")
    out = run([{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
               {"prop": "mug", "count": 60, "anchor": "on", "ref": "table"}])
    mugs = by_prop(out["placed"], "mug")
    check("11 × 5 = 55 mugs stand, 5 do not", len(mugs) == 55
          and len(out["unplaced"]) == 5, f"{len(mugs)} / {len(out['unplaced'])}")
    check("the reason names the support and an alternative",
          bool(out["unplaced"])
          and out["unplaced"][0]["reason"].startswith("surface of 'table' is full")
          and out["unplaced"][0]["pass"] == "surface",
          reasons(out["unplaced"])[:120])
    check("the 2 variants alternate 0, 1, 0, 1 …",
          [m.get("variant") for m in mugs[:4]] == [0, 1, 0, 1],
          json.dumps([m.get("variant") for m in mugs[:4]]))
    xs = sorted({round(m["at"][0], 2) for m in mugs})
    zs = sorted({round(m["at"][1], 2) for m in mugs})
    check("the raster runs −0.75…0.75 by −0.3…0.3",
          len(xs) == 11 and len(zs) == 5 and near(xs[0], -0.75)
          and near(xs[-1], 0.75) and near(zs[0], -0.3) and near(zs[-1], 0.3),
          json.dumps([xs, zs]))


# ── 6 pendant lamp ──────────────────────────────────────────────────────

def row_ceiling() -> None:
    print("\n6 — a pendant lamp over the table")
    out = run([{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
               {"prop": "lamp", "count": 1, "anchor": "above", "ref": "table"}])
    lamp = by_prop(out["placed"], "lamp")
    check("it hangs over the table's centre at 3.0 − 1.0 = 2.0",
          len(lamp) == 1 and at_near(lamp[0]["at"], 1.5, 1.0)
          and near(lamp[0].get("offset_y", -1), 2.0, 1e-6),
          json.dumps(lamp) + reasons(out["unplaced"]))


# ── 7 door clearance ────────────────────────────────────────────────────

def row_door_clearance() -> None:
    print("\n7 — the wardrobe dodges the door leaf")
    outline = [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]
    out = run([{"prop": "wardrobe", "count": 1, "anchor": "wall_s"}],
              outline=outline, openings=[DOOR])
    got = by_prop(out["placed"], "wardrobe")
    check("it slides to x = 4 − (0.6 + 0.991071·2.8) = 0.625",
          len(got) == 1 and at_near(got[0]["at"], 0.625, 2.65),
          json.dumps(got) + reasons(out["unplaced"]))
    if got:
        quad = fg.rect_corners(got[0]["at"][0], got[0]["at"][1], 1.2, 0.6,
                               got[0]["yaw"])
        strip = [(1.3, 2.0), (2.7, 2.0), (2.7, 3.0), (1.3, 3.0)]
        check("and stays clear of the 1.0 × 1.4 m door strip",
              not fg.rects_overlap(quad, strip))


# ── 7b wall series ──────────────────────────────────────────────────────

def row_wall_series() -> None:
    print("\n7b — two pieces on one wall keep 0.3 m")
    out = run([{"prop": "wardrobe", "count": 2, "anchor": "wall_n"}],
              openings=[DOOR])
    got = by_prop(out["placed"], "wardrobe")
    # Usable stretch 6 − 1.2 = 4.8, x = 0.6 + f·4.8, first candidate f = 0.5 →
    # x = 3.0. The second needs |Δx| ≥ 1.2 + 0.3 = 1.5, i.e. x ≥ 4.5 (f ≥
    # 0.8125) or x ≤ 1.5 (f ≤ 0.1875); the step is 0.25/4.8/2 = 0.026042, so
    # k = 12 is the first to reach either end and +f comes first → x = 4.5.
    check("the second wardrobe stands 1.5 m from the first, gap 0.3 m",
          len(got) == 2 and at_near(got[0]["at"], 3.0, 0.35)
          and at_near(got[1]["at"], 4.5, 0.35),
          json.dumps([g["at"] for g in got]) + reasons(out["unplaced"]))


# ── 8 window ────────────────────────────────────────────────────────────

def row_window() -> None:
    print("\n8 — the window strip is a height interval")
    out = run([{"prop": "wardrobe", "count": 1, "anchor": "wall_n"},
               {"prop": "shelf", "count": 1, "anchor": "wall_n",
                "base_m": 2.3},
               {"prop": "curtain", "count": 1, "anchor": "at_opening",
                "ref": "window"}])
    ward = by_prop(out["placed"], "wardrobe")
    shelf = by_prop(out["placed"], "shelf")
    curtain = by_prop(out["placed"], "curtain")
    check("the 2 m wardrobe cannot stand under the window and slides to 4.5",
          len(ward) == 1 and at_near(ward[0]["at"], 4.5, 0.35),
          json.dumps(ward) + reasons(out["unplaced"]))
    check("a shelf at base 2.3 hangs ABOVE the window, centred at x 3.0",
          len(shelf) == 1 and at_near(shelf[0]["at"], 3.0, 0.145)
          and near(shelf[0].get("offset_y", -1), 2.3, 1e-6),
          json.dumps(shelf) + reasons(out["unplaced"]))
    check("the curtain takes the window itself, base 0.9+1.2+0.15−2.2 = 0.05",
          len(curtain) == 1 and at_near(curtain[0]["at"], 3.0, 0.07)
          and near(curtain[0].get("offset_y", -1), 0.05, 1e-6),
          json.dumps(curtain) + reasons(out["unplaced"]))


# ── 9 rug ───────────────────────────────────────────────────────────────

def row_underlay() -> None:
    print("\n9 — a rug occupies nothing")
    out = run([{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
               {"prop": "rug", "count": 1, "anchor": "under", "ref": "table"},
               {"prop": "chair", "count": 1, "anchor": "around",
                "ref": "table"}])
    rug = by_prop(out["placed"], "rug")
    chair = by_prop(out["placed"], "chair")
    check("the rug lies centred under the table with its yaw",
          len(rug) == 1 and at_near(rug[0]["at"], 1.5, 1.0)
          and near(rug[0]["yaw"], 0.0, 0.05), json.dumps(rug))
    check("and the chair still finds its front seat at [1.5, 1.70]",
          len(chair) == 1 and at_near(chair[0]["at"], 1.5, 1.70),
          json.dumps(chair) + reasons(out["unplaced"]))


# ── 10 center group ─────────────────────────────────────────────────────

def row_center_group() -> None:
    print("\n10 — three tables with a gangway")
    out = run([{"prop": "table", "count": 3, "anchor": "center"}])
    tables = by_prop(out["placed"], "table")
    check("all three stand", len(tables) == 3, reasons(out["unplaced"]))
    want = [(1.5, 1.0), (4.5, 1.0), (1.5, 3.0)]
    check("on the cells (1.5,1.0), (4.5,1.0), (1.5,3.0)",
          len(tables) == 3 and all(at_near(t["at"], w[0], w[1])
                                   for t, w in zip(tables, want)),
          json.dumps([t["at"] for t in tables]))
    dists = [math.hypot(a["at"][0] - b["at"][0], a["at"][1] - b["at"][1])
             for i, a in enumerate(tables) for b in tables[i + 1:]]
    check("no two are closer than the 0.9 m gangway",
          bool(dists) and min(dists) >= 0.9, json.dumps([round(d, 3)
                                                         for d in dists]))
    strip = [(2.3, 3.0), (3.7, 3.0), (3.7, 4.0), (2.3, 4.0)]
    check("and none reaches into the door strip",
          all(not fg.rects_overlap(
              fg.rect_corners(t["at"][0], t["at"][1], 1.6, 0.8, t["yaw"]),
              strip) for t in tables),
          json.dumps([[round(t["at"][0], 2), round(t["at"][1], 2), t["yaw"]]
                      for t in tables]))


# ── 11 anchors of the wrong pass ────────────────────────────────────────

def row_wrong_pass() -> None:
    print("\n11 — an anchor that belongs to another pass")
    out = run([{"prop": "picture", "count": 1, "anchor": "center"}])
    check("a wall piece with anchor center is refused, in pass 'wall'",
          not out["placed"] and len(out["unplaced"]) == 1
          and out["unplaced"][0]["pass"] == "wall"
          and "wall piece needs a wall anchor" in out["unplaced"][0]["reason"],
          reasons(out["unplaced"]))
    check("and the text names an alternative",
          bool(out["unplaced"])
          and out["unplaced"][0]["reason"].endswith("at_opening"),
          reasons(out["unplaced"]))
    out = run([{"prop": "table", "count": 1, "anchor": "on", "ref": "x"}])
    check("a floor piece with anchor 'on' is sent back to a floor anchor",
          not out["placed"]
          and out["unplaced"][0]["reason"]
          == "anchor 'on' is for surface pieces — use wall_n… or center",
          reasons(out["unplaced"]))
    out = run([{"prop": "candle", "count": 1, "anchor": "on", "ref": "nope"}])
    check("an unplaceable reference is named with an alternative",
          not out["placed"] and out["unplaced"][0]["pass"] == "surface"
          and out["unplaced"][0]["reason"].endswith("or use center"),
          reasons(out["unplaced"]))


# ── 12 determinism ──────────────────────────────────────────────────────

def row_determinism() -> None:
    print("\n12 — determinism")
    plan = [{"prop": "table", "count": 1, "anchor": "center", "facing": "s"},
            {"prop": "chair", "count": 6, "anchor": "around", "ref": "table"}]
    first = json.dumps(run(plan), sort_keys=True)
    second = json.dumps(run(plan), sort_keys=True)
    check("the same plan solves to byte-identical JSON", first == second)


# ── 13 existing occupancy ───────────────────────────────────────────────

def row_existing() -> None:
    print("\n13 — an existing child blocks its raster cell")
    existing = [
        {"prop_id": "table", "id": "tbl", "at": [1.5, 1.0], "yaw": 0,
         "offset_y": 0},
        # Composed by the caller: on the table, so its base is the table top.
        {"prop_id": "candle", "id": "cdl", "at": [1.5, 1.0], "yaw": 0,
         "offset_y": 0.75, "on": "tbl"},
    ]
    out = run([{"prop": "candle", "count": 1, "anchor": "on", "ref": "tbl"}],
              existing=existing)
    got = by_prop(out["placed"], "candle")
    check("the new candle skips to the second cell [0.15, 0]",
          len(got) == 1 and got[0]["at"] == [0.15, 0.0]
          and got[0].get("on") == "tbl",
          json.dumps(got) + reasons(out["unplaced"]))


def main() -> int:
    print("furnish solver v2 — pure geometry")
    row_turn_direction()
    row_around()
    row_wall_above()
    row_wall_base()
    row_on_support()
    row_surface_budget()
    row_ceiling()
    row_door_clearance()
    row_wall_series()
    row_window()
    row_underlay()
    row_center_group()
    row_wrong_pass()
    row_determinism()
    row_existing()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
