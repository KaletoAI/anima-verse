#!/usr/bin/env python3
"""Numeric check of the BLENDER EXTERIOR RENDER — prisms, roof heuristic, job.

Usage:
    ./.venv/bin/python scripts/smoke_exterior_render.py

No server, no world DB, no store: every fixture is a literal dict and the
extractor is pure. The Blender section at the end runs only when a Blender
binary is available and says so loudly when it is not.

Design: `development_instructions/plan-blender-aussenansicht.md` (decision of
2026-08-25) and `app/core/exterior_render.py`. Every number below is derived
BY HAND from the § B1 constants of `docs/schnittstellen-3d.md`, never recorded
from a run.

──────────────────────────────────────────────────────────────────────────
FIXTURE — the same building contour `smoke_roof_model` uses: corners (0,0),
(10,0), (10,8), (0,8) in local metres, deliberately NOT centred on the anchor
pin so a wrong anchor shows up as an offset. Storey height 3.00 m. Two shapes
of it: BARE (no rooms) and TWO-STOREY (one room on level 0, one on level 1,
each 4 x 3 m at (2,2) — small enough that no room hull touches the contour, so
no contour piece yields to a room wall).

1. THE PRISM LAW. Every body in this mesh is a prism over a polygon: 2N
   vertices (the ring at both heights) and N+2 faces (two n-gon caps plus one
   quad per edge). A wall run is a 4-corner rectangle, so a wall is
       8 vertices, 6 faces
   and a plate over an N-corner outline is 2N / N+2.

2. THE WALLS the composer publishes (§ B1). A contour edge yields one piece per
   USED level when no door and no room hull cuts it:
       BARE:       4 edges x 1 level                       =  4 pieces
       TWO-STOREY: 4 edges x 2 levels + 4 edges x 2 rooms  = 16 pieces
   Their numbers, straight off the § B1 constants:
       height   = max(WALL_MIN_HEIGHT 0.6, storey 3.00 - WALL_HEAD_ROOM 0.15)
                = 2.85, plus WALL_SINK_M 0.14 on storey 0  = 2.99
       base_y   = storey floor 0.00 - WALL_SINK_M 0.14     = -0.14
       thickness= WALL_THICKNESS                           = 0.07
   (the sink is storey 0 only: the wall goes into the ground so no relief can
   open a gap under it, and the TOP edge stays where it was.)

3. THE PLATES. Storey 0 draws none since E5a — the terrain is its floor. The
   TWO-STOREY fixture therefore has exactly two:
       level plate, level 1: top = 1 x 3.00 + LEVEL_PLATE_TOP 0.08 = 3.08,
                             thickness LEVEL_PLATE_THICKNESS      = 0.14
       room plate r1:        top = 3.00 + ROOM_PLATE_TOP 0.10     = 3.10,
                             thickness ROOM_PLATE_THICKNESS       = 0.02
   Both over 4-corner outlines -> 8 vertices / 6 faces each.

4. THE GROUND PLATE is this module's own addition (E5a took storey 0's plate
   into the terrain, and an isolated render has no terrain). It is laid at the
   composer's own constants over the drawn contour:
       top    = LEVEL_PLATE_TOP                            =  0.08
       bottom = 0.08 - LEVEL_PLATE_THICKNESS 0.14          = -0.06
   -> 8 vertices, 6 faces. Note -0.06 is ABOVE the wall foot at -0.14, so the
   body's lowest point is the wall, not the plate.

5. THE ROOF HEURISTIC (no new location field — the plan's decision):
       area >= 400 m²          -> flat
       length / depth >= 1.2   -> gable
       otherwise               -> flat
   The 10 x 8 contour is aspect 1.25 over 80 m² -> GABLE at 35°, overhang
   0.40 m, ridge axis `auto`. `auto` runs the ridge along the LONG side, so
   the two slopes face the two long walls:
       ridge points at z = 4 (the centre across the 8 m span), x = -0.4 and
       10.4 (half the 10 m length plus the 0.40 m overhang at either end)
   and the ridge stands, over the wall line,
       (8/2) x tan 35° = 4 x 0.70020754 = 2.800830 m
   The base plane is the eaves minus EAVES_SINK 0.10:
       BARE (1 storey):       3.00 - 0.10 = 2.90 -> ridge at 5.700830
       TWO-STOREY (2 storeys):6.00 - 0.10 = 5.90 -> ridge at 8.700830
   6 vertices, 5 faces either way (2 slopes + 2 gable ends + 1 underside).

6. THE TOTALS then follow without a single recorded number:
       BARE:       4x8 + 8 + 6            =  46 vertices
                   4x6 + 6 + 5            =  35 faces
       TWO-STOREY: 16x8 + 2x8 + 8 + 6     = 158 vertices
                   16x6 + 2x6 + 6 + 5     = 119 faces

6b. A DOOR (finding 2026-08-25 — the render had none). Third shape of the
   fixture: ONE room on level 0, 4 x 3 m at (2,2), with a 1.0 x 2.1 m door in
   its south wall leading outside. Its hull is wound clockwise, so edge 2 runs
   (6,5) -> (2,5), u = (-1,0), 4 m long; the door at 0.5 spans t 1.5…2.5,
   i.e. world x 4.5 … 3.5 with its middle at (4,5) and its outward normal +z.
   That ray meets the south contour edge (10,8) -> (0,8) at x = 4, i.e. t = 6
   on a 10 m edge, so the hull opens over t 5.5…6.5 — the SAME world x
   4.5 … 3.5. Both walls are cut the same way and BOTH keep a lintel:

       wall              pieces                              base_y  height
       room edge 2       x 6.0 … 4.5   (solid)                -0.14   2.99
                         x 3.5 … 2.0   (solid)                -0.14   2.99
                         x 4.5 … 3.5   LINTEL                  2.10   0.75
       contour edge 2    x 10.0 … 4.5  (solid)                -0.14   2.99
                         x 3.5 … 0.0   (solid)                -0.14   2.99
                         x 4.5 … 3.5   LINTEL                  2.10   0.75

   The lintel's foot is the door's own height_m over the wall's floor (0.00 on
   storey 0) and its top is the shell's 2.85 — 2.85 - 2.10 = 0.75. So the same
   house WITHOUT the door has 4 + 4 = 8 wall pieces, with it 12:
       PLAIN ROOM: 8x8 + 8 + 6            =  78 vertices
                   8x6 + 6 + 5            =  59 faces
       ONE DOOR:  12x8 + 8 + 6            = 110 vertices
                  12x6 + 6 + 5            =  83 faces
   and the BOUNDS do not move by a millimetre: a lintel hangs inside the wall
   it belongs to.

7. THE BODY'S BOUNDS, BARE, in the scene frame:
       x  -0.4 .. 10.4   (the roof overhang past both gable ends)
       y  -0.14 .. 5.700830   (the sunk wall foot .. the ridge)
       z  -0.4 ..  8.4   (the roof overhang past both eaves)
   TWO-STOREY is the same box with y reaching 8.700830.

8. THE CAMERA distance, checked against the picture Blender really takes. The
   job speaks the BLENDER frame ((x, y, z)_scene -> (x, -z, y)), so the BARE
   body's box there is
       x -0.4..10.4, y -8.4..0.4, z -0.14..5.700830
       diagonal = sqrt(10.8² + 8.8² + 5.8408²) = sqrt(228.19494) = 15.106123
       radius   = 7.553061
   and with an 85 mm lens on a 36 mm sensor, using
       sin(atan(x)) = x / sqrt(1 + x²)   with x = 18 / 85 = 0.21176471
       sin(half fov) = 0.21176471 / sqrt(1.04484429) = 0.20717044
       distance = 7.553061 x 1.15 / 0.20717044 = 41.92693 m
   i.e. nearly four building-widths back — "orthographic-ish" by construction,
   not by adjective.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import exterior_render as ex                        # noqa: E402
from app.core import scene_recipe as sr                           # noqa: E402

failures = []

TAN35 = 0.7002075382097097


def check(label, got, want, tol=0.0):
    ok = abs(float(got) - float(want)) <= tol if tol else got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def check_vec(label, got, want, tol):
    ok = len(got) == len(want) and all(abs(float(g) - float(w)) <= tol
                                       for g, w in zip(got, want))
    shown = [round(float(g), 4) for g in got]
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {shown}, want {want}")
    if not ok:
        failures.append(label)


def check_true(label, ok, note=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {note}' if note else ''}")
    if not ok:
        failures.append(label)


def outward_normals(verts, faces):
    """Does every face of a CONVEX body point away from it? (worst dot)

    The same test `smoke_roof_model` uses, and for the same reason: the
    renderers and the meshers cull back faces, so a body wound inward is
    simply invisible — a hole that no vertex count and no bounding box shows.
    Applied here per PRISM, because a prism is convex while the union of forty
    of them is not.
    """
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    cz = sum(v[2] for v in verts) / len(verts)
    worst = (1e9, -1)
    for fi, face in enumerate(faces):
        nx = ny = nz = 0.0
        for i in range(len(face)):
            a, b = verts[face[i]], verts[face[(i + 1) % len(face)]]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        fx = sum(verts[i][0] for i in face) / len(face) - cx
        fy = sum(verts[i][1] for i in face) / len(face) - cy
        fz = sum(verts[i][2] for i in face) / len(face) - cz
        dot = nx * fx + ny * fy + nz * fz
        if dot < worst[0]:
            worst = (dot, fi)
    return worst


OUTLINE = [[0, 0], [10, 0], [10, 8], [0, 8]]
ROOMS = [{"id": "r0", "name": "Ground",
          "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 0}},
         {"id": "r1", "name": "Upper",
          "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 1}}]
#: The same ground-floor room alone — once shut, once with the 1 x 2.1 m
#: outside door of the docstring's § 6b.
PLAIN_ROOM = [{"id": "r0", "name": "Ground",
               "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 0}}]
DOOR_ROOM = [{"id": "r0", "name": "Ground",
              "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 0,
                         "openings": [{"edge": 2, "at": 0.5, "type": "door",
                                       "width_m": 1.0, "height_m": 2.1,
                                       "to": "outside"}]}}]


def fixture(rooms=()):
    """The 10 x 8 m building of the docstring; ``rooms`` makes it two-storey."""
    return {
        "id": "exterior-demo",
        "name": "Demo House",
        "description": "A plain house.",
        "map3d": {"outline": [list(p) for p in OUTLINE], "plan_width_m": 10.0,
                  "storey_height_m": 3.0},
        "rooms": [dict(r) for r in rooms],
    }


# ── [1] The prism law ───────────────────────────────────────────────────

def part_prism():
    print("\n[1] Prism — 2N vertices, N+2 faces, wound outward")
    square = [(0, 0), (4, 0), (4, 3), (0, 3)]
    verts, faces = ex.prism(square, 0.0, 2.0)
    check("square prism vertices", len(verts), 8)
    check("square prism faces", len(faces), 6)
    check("two caps are n-gons", [len(f) for f in faces[:2]], [4, 4])
    check("every side is a quad", {len(f) for f in faces[2:]}, {4})
    worst, fi = outward_normals(verts, faces)
    check_true("every face wound outward", worst > 0,
               f"worst face {fi}, dot {worst:.3f}")

    # The winding of the INPUT must not matter — plate outlines come from
    # author-drawn shapes whose direction nobody controls.
    rev_v, rev_f = ex.prism(list(reversed(square)), 0.0, 2.0)
    worst_r, fi_r = outward_normals(rev_v, rev_f)
    check_true("reversed input still wound outward", worst_r > 0,
               f"worst face {fi_r}, dot {worst_r:.3f}")

    hexagon = [(0, 0), (2, 0), (3, 1), (2, 2), (0, 2), (-1, 1)]
    hv, hf = ex.prism(hexagon, 1.0, 1.5)
    check("hexagon prism vertices (2N)", len(hv), 12)
    check("hexagon prism faces (N+2)", len(hf), 8)
    worst_h, fi_h = outward_normals(hv, hf)
    check_true("hexagon wound outward", worst_h > 0,
               f"worst face {fi_h}, dot {worst_h:.3f}")

    # Degenerate input produces NOTHING, never a sliver: a zero-thickness
    # plate is a texture surface on the level below, not a body.
    check("zero height -> no body", ex.prism(square, 1.0, 1.0)[1], [])
    check("two points -> no body", ex.prism([(0, 0), (1, 1)], 0, 1)[1], [])
    # A closed ring (first point repeated) must not produce a duplicate corner.
    ring = ex.prism(square + [(0, 0)], 0.0, 2.0)
    check("closed ring is not doubled", len(ring[0]), 8)

    # The index base lets several bodies share one vertex list.
    off_v, off_f = ex.prism(square, 0.0, 2.0, base=100)
    check("base offsets every index", min(i for f in off_f for i in f), 100)
    check("…and only by the base", max(i for f in off_f for i in f), 107)

    print("\n    Wall rectangle — the centre line, offset by half the thickness")
    rect = ex.wall_rect({"from": [0, 0], "to": [10, 0], "thickness": 0.07})
    check("a wall run is four corners", len(rect), 4)
    # The run goes a -> b along +x, so the left offset (+z here) comes first
    # and the rectangle closes back along the right one.
    check_vec("corner 0 = a + half the thickness", list(rect[0]),
              [0.0, 0.035], 1e-9)
    check_vec("corner 1 = b + half the thickness", list(rect[1]),
              [10.0, 0.035], 1e-9)
    check_vec("corner 2 = b - half the thickness", list(rect[2]),
              [10.0, -0.035], 1e-9)
    check_vec("corner 3 = a - half the thickness", list(rect[3]),
              [0.0, -0.035], 1e-9)
    check("the run is exactly WALL_THICKNESS wide",
          abs(rect[0][1] - rect[3][1]), sr.WALL_THICKNESS, 1e-9)
    check("a degenerate run has no body",
          ex.wall_rect({"from": [1, 1], "to": [1, 1], "thickness": 0.07}), [])


# ── [2] The roof heuristic ──────────────────────────────────────────────

def part_heuristic():
    print("\n[2] Roof heuristic — aspect 1.2, area cap 400 m²")
    table = [
        # (length, depth, form, why)
        (10.0, 8.0, "gable", "aspect 1.25, 80 m² — the fixture house"),
        (12.0, 10.0, "gable", "aspect 1.20 exactly — at the threshold"),
        (11.0, 10.0, "flat", "aspect 1.10 — square-ish, a block"),
        (8.0, 8.0, "flat", "aspect 1.00 — square"),
        (40.0, 5.0, "gable", "aspect 8.0, 200 m² — a long barn"),
        (24.0, 16.0, "gable", "384 m² — just under the area cap"),
        (25.0, 16.0, "flat", "400 m² exactly — at the cap, a hall"),
        (30.0, 20.0, "flat", "600 m² — over the cap despite aspect 1.5"),
        (0.0, 5.0, "flat", "degenerate — no width, no gable"),
        (5.0, 0.0, "flat", "degenerate — no depth, no gable"),
    ]
    for length, depth, want, why in table:
        check(f"{length} x {depth} m ({why})",
              ex.roof_form(length, depth), want)

    check("the constants are the ones documented",
          (ex.ROOF_ASPECT_GABLE, ex.ROOF_FLAT_AREA_M2, ex.ROOF_PITCH_DEG,
           ex.ROOF_OVERHANG_M, ex.ROOF_RIDGE_AXIS),
          (1.2, 400.0, 35.0, 0.4, "auto"))
    # The description goes through roof_model's own validator, so a rendered
    # roof and a BUILT roof are provably the same object.
    desc = ex.roof_description({"length": 10.0, "depth": 8.0})
    check("description form", desc["form"], "gable")
    check("description pitch", desc["pitch_deg"], 35.0)
    check("description overhang", desc["overhang_m"], 0.4)
    check("description ridge axis", desc["ridge_axis"], "auto")
    check("description material kind", desc["material"]["kind"], "shingle")
    check("description tone", desc["material"]["tone"], ex.ROOF_TONE)
    flat = ex.roof_description({"length": 8.0, "depth": 8.0})
    check("a flat roof carries no pitch", flat["pitch_deg"], 0.0)


# ── [3] The composer's walls and plates, as the extractor sees them ─────

def part_scene_numbers():
    print("\n[3] What the composer publishes — § B1 constants by hand")
    bare = sr.compose_scene(fixture(), plan_width_m=10.0)
    check("BARE: contour walls (4 edges x 1 level)", len(bare["walls"]), 4)
    check("BARE: storey 0 draws no plate (E5a)", len(bare["plates"]), 0)
    w = bare["walls"][0]
    check("wall base_y = floor 0 - WALL_SINK 0.14", w["base_y"], -0.14, 1e-9)
    check("wall height = max(0.6, 3.00 - 0.15) + 0.14", w["height"], 2.99, 1e-9)
    check("wall thickness", w["thickness"], sr.WALL_THICKNESS, 1e-9)

    two = sr.compose_scene(fixture(ROOMS), plan_width_m=10.0)
    check("TWO: 4 edges x 2 levels + 4 edges x 2 rooms", len(two["walls"]), 16)
    check("TWO: level plate + room plate on level 1", len(two["plates"]), 2)
    level_plate = [p for p in two["plates"] if not p.get("room_id")][0]
    room_plate = [p for p in two["plates"] if p.get("room_id")][0]
    check("level plate top = 1 x 3.00 + 0.08", level_plate["top_y"], 3.08, 1e-9)
    check("level plate thickness", level_plate["thickness"],
          sr.LEVEL_PLATE_THICKNESS, 1e-9)
    check("room plate top = 3.00 + 0.10", room_plate["top_y"], 3.10, 1e-9)
    check("room plate thickness", room_plate["thickness"],
          sr.ROOM_PLATE_THICKNESS, 1e-9)


# ── [4] The extracted body ──────────────────────────────────────────────

def part_extract():
    print("\n[4] Extraction — BARE: 4 walls + ground plate + gable roof")
    g = ex.extract_geometry(fixture(), "exterior-demo")
    check("ok", g["ok"], True)
    check("walls", g["parts"]["walls"], 4)
    check("plates (storey 0 has none)", g["parts"]["plates"], 0)
    check("ground plate laid", g["parts"]["ground_plate"], True)
    check("roof built", g["parts"]["roof"], True)
    check("vertices = 4x8 + 8 + 6", len(g["vertices"]), 46)
    check("faces = 4x6 + 6 + 5", len(g["faces"]), 35)
    check("one material index per face", len(g["face_material"]), 35)
    check("storeys (no room = one)", g["storeys"], 1)
    check("eaves height", g["eaves_height_m"], 3.0, 1e-9)

    check("roof form", g["roof"]["form"], "gable")
    check("roof base plane = eaves 3.00 - EAVES_SINK 0.10",
          g["roof"]["base_y"], 2.90, 1e-9)
    check("ridge = base + 4 x tan 35°", g["roof"]["ridge_y_world"],
          round(2.90 + 4 * TAN35, 4), 1e-3)
    check("roof vertices", g["roof"]["vertices"], 6)
    check("roof faces", g["roof"]["faces"], 5)
    check_vec("body bounds min", g["bounds"]["min"], [-0.4, -0.14, -0.4], 1e-4)
    check_vec("body bounds max", g["bounds"]["max"],
              [10.4, round(2.90 + 4 * TAN35, 4), 8.4], 1e-3)

    # THE GABLE ORIENTATION: `auto` runs the ridge along the LONG side, so the
    # two slopes face the two long walls. The ridge line is therefore at the
    # centre of the 8 m span (z = 4) and runs the full 10 m + overhang in x.
    ridge_y = g["roof"]["ridge_y_world"]
    ridge_pts = sorted([v for v in g["vertices"]
                        if abs(v[1] - ridge_y) < 1e-6], key=lambda v: v[0])
    check("the ridge is a line of two points", len(ridge_pts), 2)
    check_vec("ridge end A (x, z)", [ridge_pts[0][0], ridge_pts[0][2]],
              [-0.4, 4.0], 1e-4)
    check_vec("ridge end B (x, z)", [ridge_pts[1][0], ridge_pts[1][2]],
              [10.4, 4.0], 1e-4)
    check_true("the ridge runs along the LONG side (x), not across it",
               abs(ridge_pts[1][0] - ridge_pts[0][0]) > 10.0
               and abs(ridge_pts[1][2] - ridge_pts[0][2]) < 1e-6)

    print("\n    TWO-STOREY — 16 walls + 2 plates + ground plate + roof")
    t = ex.extract_geometry(fixture(ROOMS), "exterior-demo")
    check("walls", t["parts"]["walls"], 16)
    check("plates", t["parts"]["plates"], 2)
    check("vertices = 16x8 + 2x8 + 8 + 6", len(t["vertices"]), 158)
    check("faces = 16x6 + 2x6 + 6 + 5", len(t["faces"]), 119)
    check("storeys", t["storeys"], 2)
    check("eaves height = 2 x 3.00", t["eaves_height_m"], 6.0, 1e-9)
    check("roof base = 6.00 - 0.10", t["roof"]["base_y"], 5.90, 1e-9)
    check("ridge = 5.90 + 4 x tan 35°", t["roof"]["ridge_y_world"],
          round(5.90 + 4 * TAN35, 4), 1e-3)
    check("a taller house is the same box, higher",
          [t["bounds"]["size"][0], t["bounds"]["size"][2]], [10.8, 8.8])

    # Every face must reference a real vertex, and every vertex must be used —
    # a stray index is a broken mesh, a stray vertex a silent bounds error.
    n = len(t["vertices"])
    used = {i for f in t["faces"] for i in f}
    check_true("face indices in range",
               all(0 <= i < n for f in t["faces"] for i in f))
    check("every vertex used", len(used), n)
    check("materials used: wall, plate, roof",
          sorted(set(t["face_material"])),
          [ex.MATERIAL_WALL, ex.MATERIAL_ROOF, ex.MATERIAL_PLATE])
    # Each prism was appended as a unit, so every body on its own is still
    # wound outward (the union of them is not convex and cannot be tested).
    worst_all = 1e9
    at = 0
    while at < 4 * 8:                       # the four wall boxes of the BARE body
        body_v = g["vertices"][at:at + 8]
        body_f = [[i - at for i in f] for f in g["faces"]
                  if all(at <= i < at + 8 for i in f)]
        worst, _ = outward_normals(body_v, body_f)
        worst_all = min(worst_all, worst)
        at += 8
    check_true("every wall box wound outward", worst_all > 0,
               f"worst dot {worst_all:.3f}")

    print("\n    Nothing to render")
    empty = ex.extract_geometry({"id": "x", "name": "Void", "map3d": {},
                                 "rooms": []}, "x")
    check("a location with no geometry says so", empty["ok"], False)
    check("…and why", empty["error"], "no_geometry")


# ── [4b] The door — a hole with a lintel over it, in BOTH walls ─────────

def part_door():
    print("\n[4b] A door — the hull opens where it is, and closes above it")
    shut = sr.compose_scene(fixture(PLAIN_ROOM), plan_width_m=10.0)
    open_ = sr.compose_scene(fixture(DOOR_ROOM), plan_width_m=10.0)
    check("shut house: 4 contour + 4 room walls", len(shut["walls"]), 8)
    check("with a door: both cut walls become 2 runs + a lintel",
          len(open_["walls"]), 12)

    # The two pieces the door leaves in the CONTOUR (§ 6b of the docstring).
    contour = [w for w in open_["walls"] if not w.get("room_id")
               and abs(w["from"][1] - 8.0) < 1e-9
               and abs(w["to"][1] - 8.0) < 1e-9]
    runs = sorted([w for w in contour if w["base_y"] < 0], key=lambda w: -w["from"][0])
    heads = [w for w in contour if w["base_y"] > 0]
    check("the south facade is 2 runs + 1 lintel", len(contour), 3)
    check_vec("run A ends at the door, x 10.0 -> 4.5",
              [runs[0]["from"][0], runs[0]["to"][0]], [10.0, 4.5], 1e-9)
    check_vec("run B starts after it, x 3.5 -> 0.0",
              [runs[1]["from"][0], runs[1]["to"][0]], [3.5, 0.0], 1e-9)
    check("exactly one lintel over the hole", len(heads), 1)
    check_vec("the lintel spans the hole, x 4.5 -> 3.5",
              [heads[0]["from"][0], heads[0]["to"][0]], [4.5, 3.5], 1e-9)
    check("...standing on the door's own height", heads[0]["base_y"], 2.10, 1e-9)
    check("...and reaching the top of the shell, 2.85 - 2.10",
          heads[0]["height"], 0.75, 1e-9)

    # The ROOM wall the door was drawn into is cut identically — same x, same
    # lintel — so the hole goes right through the building.
    room = [w for w in open_["walls"] if w.get("room_id") == "r0"
            and abs(w["from"][1] - 5.0) < 1e-9 and abs(w["to"][1] - 5.0) < 1e-9]
    room_head = [w for w in room if w["base_y"] > 0]
    check("the room wall is 2 runs + 1 lintel too", len(room), 3)
    check_vec("its lintel sits over the same x 4.5 -> 3.5",
              [room_head[0]["from"][0], room_head[0]["to"][0]], [4.5, 3.5], 1e-9)
    check("...at the same head height", room_head[0]["base_y"], 2.10, 1e-9)
    # RED: the old picture was a slot from the ground to the eaves. If any
    # piece of these two walls were still missing above 2.10, this fails.
    check_vec("RED: no wall of the door line is open to the eaves",
              [w["base_y"] + w["height"] for w in contour + room],
              [2.85] * 6, 1e-9)

    print("\n    …and the Blender volume gets it for free")
    g_shut = ex.extract_geometry(fixture(PLAIN_ROOM), "exterior-demo")
    g = ex.extract_geometry(fixture(DOOR_ROOM), "exterior-demo")
    check("shut: vertices = 8x8 + 8 + 6", len(g_shut["vertices"]), 78)
    check("shut: faces = 8x6 + 6 + 5", len(g_shut["faces"]), 59)
    check("door: walls", g["parts"]["walls"], 12)
    check("door: vertices = 12x8 + 8 + 6", len(g["vertices"]), 110)
    check("door: faces = 12x6 + 6 + 5", len(g["faces"]), 83)
    check("one material index per face", len(g["face_material"]), 83)
    check_vec("the body's box does not move (a lintel is inside the wall)",
              g["bounds"]["min"] + g["bounds"]["max"],
              g_shut["bounds"]["min"] + g_shut["bounds"]["max"], 1e-9)
    # The mesh has to be sound with the extra bodies in it.
    n = len(g["vertices"])
    check_true("face indices in range",
               all(0 <= i < n for f in g["faces"] for i in f))
    check("every vertex used", len({i for f in g["faces"] for i in f}), n)


# ── [5] The Blender job ─────────────────────────────────────────────────

def part_job():
    print("\n[5] The job — frame conversion, materials, camera")
    from app.core.roof_model import tone_to_linear
    job = ex.build_job("exterior-demo", fixture())
    check("ok", job["ok"], True)
    check("kind", job["kind"], "exterior")
    check("mesh vertices", len(job["mesh"]["vertices"]), 46)
    check("mesh faces", len(job["mesh"]["faces"]), 35)
    check("expect states what was asked for", job["expect"]["faces"], 35)

    # The frame conversion, ONCE: (x, y, z)_scene -> (x, -z, y).
    geo = ex.extract_geometry(fixture(), "exterior-demo")
    scene_ridge = max(geo["vertices"], key=lambda v: v[1])
    blender_ridge = max(job["mesh"]["vertices"], key=lambda v: v[2])
    check_vec("scene -> blender frame", blender_ridge,
              [scene_ridge[0], -scene_ridge[2], scene_ridge[1]], 1e-6)

    check("three materials", len(job["materials"]), 3)
    check("wall material first", job["materials"][ex.MATERIAL_WALL]["tone"],
          ex.WALL_TONE)
    check("roof material second", job["materials"][ex.MATERIAL_ROOF]["tone"],
          ex.ROOF_TONE)
    check("plate material third", job["materials"][ex.MATERIAL_PLATE]["tone"],
          ex.PLATE_TONE)
    # A tone is named in sRGB and fed to Blender in linear light.
    check_vec("wall tone -> linear",
              job["materials"][ex.MATERIAL_WALL]["color"],
              tone_to_linear(ex.WALL_TONE), 1e-9)
    check("one roughness for the whole body",
          {m["roughness"] for m in job["materials"]}, {ex.SURFACE_ROUGHNESS})

    cam = job["camera"]
    check("camera elevation", cam["elevation_deg"], 35.0)
    check("three-quarter yaw", cam["yaw_deg"], 35.0)
    check("long lens", cam["lens_mm"], 85.0)
    check("frame margin", cam["margin"], 1.15)
    check("square render", job["render"]["size"], 1024)
    check("neutral background, not transparent",
          job["render"]["background"], [0.55, 0.55, 0.55])

    print("\n    Determinism")
    a = json.dumps(ex.build_job("exterior-demo", fixture()), sort_keys=True)
    b = json.dumps(ex.build_job("exterior-demo", fixture()), sort_keys=True)
    check_true("two builds produce the identical job JSON", a == b)
    c = json.dumps(ex.build_job("exterior-demo", fixture(ROOMS)),
                   sort_keys=True)
    check_true("a second storey changes the job", a != c)
    void = ex.build_job("x", {"id": "x", "map3d": {}, "rooms": []})
    check("nothing to render -> ok False", void["ok"], False)


# ── [6] The camera framing, by hand ─────────────────────────────────────

def expected_distance():
    """The distance the script must choose for the BARE body (docstring § 8)."""
    job = ex.build_job("exterior-demo", fixture())
    verts = job["mesh"]["vertices"]
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    radius = math.dist(lo, hi) / 2
    # sin(atan(x)) = x / sqrt(1 + x²) — written out so this stays an
    # independent derivation rather than a copy of the script's expression.
    x = 18.0 / 85.0
    return radius, radius * 1.15 / (x / math.sqrt(1.0 + x * x))


def part_framing():
    print("\n[6] Framing — the bounding sphere and the lens decide the distance")
    radius, distance = expected_distance()
    check("BARE body radius (blender frame)", round(radius, 4), 7.5531, 1e-4)
    check("camera distance = r x margin / sin(half fov)", round(distance, 4),
          41.9269, 1e-4)
    check_true("that is several building widths back — verticals stay vertical",
               distance / 10.8 > 3.0, f"{distance / 10.8:.1f} widths")


# ── [7] Blender end to end ──────────────────────────────────────────────

def part_blender():
    print("\n[7] Blender end to end")
    from app.blender import runner
    st = runner.status()
    if not st["executable"] or not st["version"]:
        print("  SKIP ─────────────────────────────────────────────────────")
        print("  SKIP  no Blender binary found — no image is rendered.")
        print("  SKIP  set image_generation.blender_executable or put one on")
        print("  SKIP  PATH to run this section.")
        print("  SKIP ─────────────────────────────────────────────────────")
        return
    print(f"  Blender: {st['executable']} {st['version']}")
    import tempfile

    # A small render: this section proves the WIRING and the numbers, not the
    # picture quality — 256 px at 8 samples is seconds instead of minutes.
    job = ex.build_job("exterior-demo", fixture(), size=256, samples=8)
    with tempfile.TemporaryDirectory(prefix="av-exterior-smoke-") as tmp:
        tmp_dir = Path(tmp)
        job_file = tmp_dir / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False),
                            encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        res = runner.run("exterior", inputs={"job": job_file},
                         out_dir=out_dir, timeout_s=600)
        check_true("render ok", bool(res.get("ok")), res.get("error", ""))
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        check("built vertices", data.get("vertices"), 46)
        check("built faces", data.get("faces"), 35)
        check("built materials", data.get("materials"), 3)
        check("render size", data.get("size"), 256)
        # The bbox comes back in the BLENDER frame: (x, -z, y) of the scene.
        check_vec("built bbox (blender frame)", data.get("bbox") or [],
                  [-0.4, -8.4, -0.14, 10.4, 0.4, round(2.90 + 4 * TAN35, 4)],
                  1e-3)
        _, want_distance = expected_distance()
        check("camera distance matches the hand derivation",
              data.get("camera_distance"), round(want_distance, 4), 1e-2)
        png = Path((res.get("outputs") or {}).get("png") or "")
        check_true("PNG written", png.is_file())
        if not png.is_file():
            return
        head = png.read_bytes()[:24]
        check("it is a PNG", head[:8], b"\x89PNG\r\n\x1a\n")
        # Width and height sit in the IHDR chunk, big-endian, at bytes 16..24.
        check("PNG width", int.from_bytes(head[16:20], "big"), 256)
        check("PNG height", int.from_bytes(head[20:24], "big"), 256)

        print("\n    Runner contract")
        bad = runner.run("exterior", inputs={}, out_dir=out_dir, timeout_s=60)
        check("no job -> ok False", bad["ok"], False)


def main():
    part_prism()
    part_heuristic()
    part_scene_numbers()
    part_extract()
    part_door()
    part_job()
    part_framing()
    part_blender()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
