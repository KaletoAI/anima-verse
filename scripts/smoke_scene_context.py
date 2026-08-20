#!/usr/bin/env python3
"""Numeric check of the CONTEXT RENDER — camera solve, projection, mask, sun.

Usage:
    ./.venv/bin/python scripts/smoke_scene_context.py

No server, no world DB. The Blender section at the end runs only when a
Blender binary is available and says so loudly when it is not.

Design: `docs/scene-context-render.md`. Every number below is derived BY HAND
from that document, never recorded from a run.

──────────────────────────────────────────────────────────────────────────
FIXTURE — a 4 m × 4 m footprint on flat ground at the local point (3, −2),
yaw 0, height 0; lens 50 mm on a 36 mm sensor; elevation 35°, azimuth offset
45°, fill 0.40, 1024 × 1024 px.

1. FRAMING. The camera frames the sphere around the target's centre that holds
   its footprint corners: r_h = √(2² + 2²) = 2.828427 m, height 0, so
       span = 2 · 2.828427 = 5.656854 m.
   An object of size s at distance d projects to fy · s / d pixels and
   fy = H · f / sensor, so asking for fill · H pixels gives
       d = f · s / (sensor · fill) = 50 · 5.656854 / (36 · 0.40)
         = 282.842712 / 14.4 = 19.641855 m.
   The resolution cancels — which is the point of the rule.

2. CAMERA POSITION. ψ = yaw + 45° = 45°, ε = 35°, and the camera stands in the
   direction (sin ψ, cos ψ) from the target:
       d·cos ε = 19.641855 · 0.81915204 = 16.089666
       horizontal = 16.089666 · 0.70710678 = 11.377112
       d·sin ε = 19.641855 · 0.57357644 = 11.266105
       P = (3 + 11.377112, 0 + 11.266105, −2 + 11.377112)
         = (14.377112, 11.266105, 9.377112)

3. THE CAMERA BASIS (rows = axes in scene coordinates), from
   back = unit(P − C) = (cos ε sin ψ, sin ε, cos ε cos ψ):
       back  = ( 0.5792279,  0.5735764,  0.5792279)
       right = ( 0.7071068,  0,         −0.7071068)   [unit(up × back)]
       up    = (−0.4055798,  0.8191520, −0.4055798)   [back × right]
   fx = fy = H · f / sensor = 1024 · 50 / 36 = 1422.222222, cx = cy = 512.

4. PROJECTED PIXELS. u = 512 + fx · (v·right)/depth, v = 512 − fy · (v·up)/depth
   with depth = −(v·back), v = Q − P.

   • ANCHOR (3, 0, −2) — the camera looks at it, so it lands on the principal
     point: (512.00, 512.00). No arithmetic can move it.
   • FAR corner (1, 0, −4): v = (−13.377112, −11.266105, −13.377112)
       v·right = 0.7071068·(−13.377112 + 13.377112) = 0     → u = 512.00
       v·back  = −2·7.7483881 − 6.4619695 = −21.9587457     → depth 21.958746
       v·up    = +2·5.4254853 − 9.2286620 = 1.6223086
       v_px    = 512 − 1422.222222 · 1.6223086 / 21.958746 = 512 − 105.074
             = 406.93                                       (it lies BEHIND
                                                             the anchor, so it
                                                             sits higher)
   • NEAR corner (5, 0, 0): v = (−9.377112, −11.266105, −9.377112)
       v·right = 0                                          → u = 512.00
       v·back  = −2·5.4314765 − 6.4619695 = −17.3249225     → depth 17.324923
       v·up    = +2·3.8031661 − 9.2286620 = −1.6223298
       v_px    = 512 + 1422.222222 · 1.6223298 / 17.324923 = 512 + 133.179
             = 645.18
   • SIDE corner (5, 0, −4): v = (−9.377112, −11.266105, −13.377112)
       v·right = 0.7071068 · 4 = 2.8284271
       v·back  = −22.7542234·0.5792279 − 6.4619695 = −19.6418341
                 → depth = 19.6418 = d  (this corner is exactly abeam the
                   target centre, so it must sit at the framing distance)
       v·up    = 3.8031661 + 5.4254853 − 9.2286620 = 0      → v_px = 512.00
       u = 512 + 1422.222222 · 2.8284271 / 19.641834 = 512 + 204.800 = 716.80
   • SIDE corner (1, 0, 0): mirrored → (307.20, 512.00)

5. MASK. The four corners are the hull (height 0 → no top ring), so the mask
   is exactly those four pixels and its bbox is
   [307.20, 406.93, 716.80, 645.18].

6. SUN. The default calendar runs 06:00 → 18:00 in every season, so daylight is
   720 minutes long.
       noon, mid-summer (12:00): f = (720 − 360)/720 = 0.5
           elevation = 60 · sin(90°) = 60.0   (the ceiling — noon is the peak)
           azimuth   = 90 − 180·0.5 = 0       (due south)
           direction = (cos 60 · sin 0, sin 60, cos 60 · cos 0)
                     = (0, 0.8660254, 0.5)
       09:00: f = 0.25 → elevation = 60 · sin 45° = 42.426407, azimuth = 45
       00:00: night is 1440 − 720 = 720 min long, 180 min after sunset ×2 →
           f = 360/720 = 0.5 → elevation = 28.0 (the moon ceiling), azimuth 0
──────────────────────────────────────────────────────────────────────────
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import scene_context as sc                      # noqa: E402
from app.core.game_time import GameTime                       # noqa: E402

PX_TOL = 0.5
M_TOL = 1e-4

failures = []


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


ANCHOR = [3.0, -2.0]
FOOTPRINT = sc.rect_footprint(ANCHOR, 4.0, 4.0, 0.0)


def camera_fixture():
    span = sc.target_span_m(FOOTPRINT, ANCHOR, 0.0)
    return span, sc.solve_camera(ANCHOR, span, ground_y=0.0, height_m=0.0,
                                 yaw_deg=0.0, width=1024, height=1024)


# ── [1] Framing and camera position ─────────────────────────────────────

def part_camera():
    print("\n[1] Camera solve — 4 m footprint at (3, −2), lens 50/36, ε 35°")
    span, cam = camera_fixture()
    check("span_m (sphere diameter)", span, 5.656854, 1e-5)
    check("distance_m", cam["distance_m"], 19.641855, 1e-5)
    check_vec("position", cam["position"],
              [14.377112, 11.266105, 9.377112], 1e-5)
    check("fx", cam["fx"], 1422.222222, 1e-5)
    check("fy", cam["fy"], 1422.222222, 1e-5)
    check("cx", cam["cx"], 512.0, 1e-9)
    check("azimuth_deg", cam["azimuth_deg"], 45.0, 1e-9)
    check("elevation_deg", cam["elevation_deg"], 35.0, 1e-9)
    # frame height = span / fill — the very identity the distance rule is
    # solved from, so it must come back out of the camera unchanged.
    check("frame_height_m", cam["frame_height_m"], 5.656854 / 0.4, 1e-5)
    check_vec("basis row 0 (right)", cam["rotation_matrix"][0],
              [0.7071068, 0.0, -0.7071068], 1e-6)
    check_vec("basis row 1 (up)", cam["rotation_matrix"][1],
              [-0.4055798, 0.8191520, -0.4055798], 1e-6)
    check_vec("basis row 2 (back)", cam["rotation_matrix"][2],
              [0.5792279, 0.5735764, 0.5792279], 1e-6)
    # The rows must be an orthonormal right-handed triple, or every pixel
    # below is meaningless.
    r, u, b = [tuple(row) for row in cam["rotation_matrix"]]
    check("basis orthonormal (r·u)", sc._v_dot(r, u), 0.0, 1e-9)
    check("basis orthonormal (r·b)", sc._v_dot(r, b), 0.0, 1e-9)
    check("basis right-handed (r×u = b)",
          sc._v_len(sc._v_sub(sc._v_cross(r, u), b)), 0.0, 1e-9)
    # Scene → Blender: (x, y, z) -> (x, −z, y), applied to the position.
    check_vec("position (Blender frame)", cam["position_blender"],
              [14.377112, -9.377112, 11.266105], 1e-5)
    q = cam["quaternion_blender"]
    check("camera quaternion is unit", math.sqrt(sum(c * c for c in q)),
          1.0, 1e-9)


# ── [2] Projection ──────────────────────────────────────────────────────

def part_projection():
    print("\n[2] Projection — hand-derived pixels")
    _span, cam = camera_fixture()

    def px(point):
        u, v, depth = sc.project(point, cam)
        return u, v, depth

    u, v, depth = px((3.0, 0.0, -2.0))
    check("anchor u", u, 512.0, PX_TOL)
    check("anchor v", v, 512.0, PX_TOL)
    check("anchor depth", depth, 19.641855, 1e-4)

    u, v, depth = px((1.0, 0.0, -4.0))
    check("far corner u", u, 512.0, PX_TOL)
    check("far corner v", v, 406.93, PX_TOL)
    check("far corner depth", depth, 21.958746, 1e-4)

    u, v, depth = px((5.0, 0.0, 0.0))
    check("near corner u", u, 512.0, PX_TOL)
    check("near corner v", v, 645.18, PX_TOL)
    check("near corner depth", depth, 17.324923, 1e-4)

    u, v, depth = px((5.0, 0.0, -4.0))
    check("side corner u", u, 716.80, PX_TOL)
    check("side corner v", v, 512.0, PX_TOL)
    check("side corner depth (= framing distance)", depth, 19.641834, 1e-4)

    u, v, _d = px((1.0, 0.0, 0.0))
    check("mirrored side corner u", u, 307.20, PX_TOL)
    check("mirrored side corner v", v, 512.0, PX_TOL)

    # A point BEHIND the camera must be reported as such; its pixels are
    # meaningless and a consumer has to see that from the depth alone.
    _u, _v, depth = px((3.0, 0.0, 40.0))
    check_true("point behind the camera has depth < 0", depth < 0,
               f"depth {depth:.3f}")


# ── [3] Mask polygon ────────────────────────────────────────────────────

def part_mask():
    print("\n[3] Mask polygon — the footprint projected to pixels")
    _span, cam = camera_fixture()
    poly = sc.mask_polygon(FOOTPRINT, 0.0, 0.0, cam)
    check("mask corner count", len(poly), 4)
    want = {(512.0, 406.93), (512.0, 645.18), (716.80, 512.0), (307.20, 512.0)}
    for wu, wv in want:
        hit = any(abs(p[0] - wu) <= PX_TOL and abs(p[1] - wv) <= PX_TOL
                  for p in poly)
        check_true(f"mask contains ({wu}, {wv})", hit)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    check_vec("mask bbox", [min(xs), min(ys), max(xs), max(ys)],
              [307.20, 406.93, 716.80, 645.18], PX_TOL)

    # A 2 m tall target adds a top ring; its hull must stay 4-8 points and
    # reach HIGHER up the image (smaller v) than the flat one.
    tall = sc.mask_polygon(FOOTPRINT, 0.0, 2.0, cam)
    check_true("tall target reaches higher in the image",
               min(p[1] for p in tall) < min(ys),
               f"{min(p[1] for p in tall):.1f} < {min(ys):.1f}")
    check_true("tall target hull stays a hull", 4 <= len(tall) <= 8,
               f"{len(tall)} points")

    # Dilation grows the hull about its own centroid — 10 px of it must move
    # every corner outward by exactly 10 px.
    grown = sc.mask_polygon(FOOTPRINT, 0.0, 0.0, cam, dilate_px=10.0)
    cxg = sum(p[0] for p in poly) / 4.0
    cyg = sum(p[1] for p in poly) / 4.0
    deltas = []
    for p in poly:
        near = min(grown, key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2)
        deltas.append(math.hypot(near[0] - p[0], near[1] - p[1]))
    check_vec("dilation moves every corner 10 px", deltas, [10.0] * 4, 0.02)
    # The centroid barely moves: the four outward unit vectors nearly cancel
    # (the two side corners tilt 2° downwards), so 10 px of dilation shifts it
    # by 10·0.068/4 ≈ 0.17 px — enough to say "about its own centroid", not
    # enough to call it exact.
    check("dilation keeps the centroid (x)",
          sum(p[0] for p in grown) / 4.0, cxg, 0.05)
    check("dilation keeps the centroid (y)",
          sum(p[1] for p in grown) / 4.0, cyg, 0.25)


# ── [4] Sun ─────────────────────────────────────────────────────────────

def part_sun():
    print("\n[4] Sun angles from game time (default calendar 06:00–18:00)")
    noon = GameTime.from_parts(1, 46, 12, 0)        # day 46 = mid-summer
    check("mid-summer is summer", noon.season, "summer")
    sun = sc.solve_sun(noon)
    check("noon elevation", sun["elevation_deg"], 60.0, 1e-9)
    check("noon azimuth (due south)", sun["azimuth_deg"], 0.0, 1e-9)
    check_vec("noon direction", sun["direction"], [0.0, 0.8660254, 0.5], 1e-6)
    check_true("noon is not night", not sun["night"])

    morning = sc.solve_sun(GameTime.from_parts(1, 46, 9, 0))
    check("09:00 elevation", morning["elevation_deg"], 42.426407, 1e-5)
    check("09:00 azimuth (south-east)", morning["azimuth_deg"], 45.0, 1e-9)

    evening = sc.solve_sun(GameTime.from_parts(1, 46, 15, 0))
    check("15:00 azimuth (south-west)", evening["azimuth_deg"], -45.0, 1e-9)
    check("15:00 mirrors 09:00 in elevation",
          evening["elevation_deg"], morning["elevation_deg"], 1e-9)

    midnight = sc.solve_sun(GameTime.from_parts(1, 46, 0, 0))
    check_true("midnight is night", midnight["night"])
    check("midnight elevation (moon ceiling)",
          midnight["elevation_deg"], 28.0, 1e-9)
    check("midnight azimuth", midnight["azimuth_deg"], 0.0, 1e-9)
    check_true("night trades sun for ambient",
               midnight["strength"] < sun["strength"]
               and midnight["sky_strength"] > sun["sky_strength"],
               f"sun {midnight['strength']} vs {sun['strength']}, "
               f"sky {midnight['sky_strength']} vs {sun['sky_strength']}")

    # Right at sunrise the arc is zero, so the floor must catch it — a light
    # lying flat on the ground lights nothing.
    dawn = sc.solve_sun(GameTime.from_parts(1, 46, 6, 0))
    check("sunrise elevation floor", dawn["elevation_deg"], 6.0, 1e-9)
    check("sunrise azimuth (due east)", dawn["azimuth_deg"], 90.0, 1e-9)

    # A unit direction, or the Blender lamp points somewhere else than the
    # sidecar says.
    for label, s in (("noon", sun), ("midnight", midnight)):
        check(f"{label} direction is unit", sc._v_len(s["direction"]),
              1.0, 1e-9)
        check_vec(f"{label} direction in the Blender frame",
                  s["direction_blender"],
                  [s["direction"][0], -s["direction"][2], s["direction"][1]],
                  1e-12)


# ── [5] Scene assembly ──────────────────────────────────────────────────

def fixture_location():
    return {"id": "ctx-demo", "pos_x": 100.0, "pos_z": -50.0, "yaw_deg": 30.0,
            "map3d": {}, "rooms": []}


def fixture_scene():
    """A hand-written scene payload: one room plate, one wall, one prop
    placement at the fixture anchor and one prop 40 m away."""
    return {
        "extent_m": 20.0, "storey_m": 3.0, "k": 1.0,
        "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]],
        "plates": [{"level": 0, "outline": [[0, -6], [8, -6], [8, 2], [0, 2]],
                    "top_y": 0.1, "thickness": 0.02, "room_id": "r1"}],
        "walls": [{"level": 0, "from": [0, -6], "to": [8, -6], "base_y": 0.0,
                   "height": 2.85, "thickness": 0.07, "room_id": "r1"}],
        "models": [
            {"role": "prop", "id": "table", "room_id": "r1", "level": 0,
             "variants": {"full": "/assets/props/table/model"},
             "fix_euler": {"x": 0, "y": 0, "z": 0}, "yaw_deg": 0.0,
             "max_m": 1.2, "measure": "xyz", "anchor": [3.0, -2.0],
             "bottom_y": 0.11},
            {"role": "prop", "id": "bench", "room_id": "r1", "level": 0,
             "variants": {"full": "/assets/props/bench/model"},
             "fix_euler": {"x": 0, "y": 0, "z": 0}, "yaw_deg": 0.0,
             "max_m": 1.6, "measure": "xyz", "anchor": [40.0, 40.0],
             "bottom_y": 0.11},
        ],
        "markers": [], "rooms": [], "doorways": [], "problems": [],
    }


def part_scene():
    print("\n[5] Scene assembly — synthetic location, no DB")
    placements = [
        {"prop_id": "table", "at": [3.0, -2.0], "yaw": 0.0,
         "dims": {"width_m": 4.0, "depth_m": 4.0, "height_m": 0.0}},
        {"prop_id": "bench", "at": [40.0, 40.0], "yaw": 0.0,
         "dims": {"width_m": 1.6, "depth_m": 0.5, "height_m": 0.9}},
    ]
    job = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "r1", "index": 0},
        location=fixture_location(), scene=fixture_scene(),
        placements=placements, game=GameTime.from_parts(1, 46, 12, 0),
        params={"width": 1024, "height": 1024},
        height_at=lambda x, z: 0.0, model_files={})
    side = job["sidecar"]

    # The target is the placement, and the placement's own numbers are used —
    # not the layout's, not the prop library's.
    check("target anchor x", side["target"]["anchor"][0], 3.0, M_TOL)
    check("target ground_y (= placement bottom_y)",
          side["target"]["ground_y"], 0.11, M_TOL)
    # THE FLOOR THE PLACEMENT STANDS ON (§ B1 addendum 2026-08-20): the room's
    # own plate, read off the payload — 0.11 − PROP_CLEARANCE 0.01 = 0.10.
    # The contact check lifts its ground sampler onto exactly this, or the
    # floor itself reads as a gap (`scene_asset.place`).
    check("target floor_y (= the room's plate top)",
          side["target"]["floor_y"], 0.10, M_TOL)
    # A YARD placement (the ground room, § A13a) draws no plate of its own:
    # its floor is the storey-0 LEVEL plate — 0.08 with the addendum's datum,
    # and the yard prop's bottom_y is that plus the clearance = 0.09.
    yard_scene = fixture_scene()
    yard_scene["plates"] = [
        {"level": 0, "outline": [[-10, -10], [10, -10], [10, 10], [-10, 10]],
         "top_y": 0.08, "thickness": 0.14},
        *yard_scene["plates"],
    ]
    for spec in yard_scene["models"]:
        spec["room_id"] = "__ground__"
        spec["bottom_y"] = 0.09
    yard = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "__ground__", "index": 0},
        location=fixture_location(), scene=yard_scene,
        placements=placements, game=GameTime.from_parts(1, 46, 12, 0),
        params={"width": 1024, "height": 1024},
        height_at=lambda x, z: 0.0, model_files={})
    yt = yard["sidecar"]["target"]
    check("yard target ground_y (= its bottom_y)", yt["ground_y"], 0.09, M_TOL)
    check("yard floor_y falls back to the storey-0 level plate",
          yt["floor_y"], 0.08, M_TOL)
    # The sidecar rounds its metres to 4 decimals (0.1 mm) — the tolerance
    # here is that rounding, not slack in the maths.
    check("target span_m", side["target"]["span_m"], 5.656854, 1e-4)
    check("mask corner count", len(side["mask"]["polygon_px"]), 4)

    # The camera is solved on the ground of the placement, so it rides 0.11 m
    # up with it — everything else is the [1] fixture.
    check("camera distance", side["camera"]["distance_m"], 19.641855, 1e-5)
    check_vec("camera position", side["camera"]["position"],
              [14.377112, 11.266105 + 0.11, 9.377112], 1e-5)

    # Terrain patch: 1.5 × the visible frame, 32 cells, so 33² vertices.
    patch = side["content"]["terrain_patch_m"]
    check("terrain patch (1.5 × frame height)", patch,
          round(5.656854 / 0.4 * 1.5, 3), 1e-3)
    terrain = next(p for p in job["primitives"] if p.get("name") == "terrain")
    check("terrain vertices", len(terrain["vertices"]), 33 * 33)
    check("terrain faces", len(terrain["faces"]), 32 * 32)
    lo_x = min(v[0] for v in terrain["vertices"])
    hi_x = max(v[0] for v in terrain["vertices"])
    check("terrain patch spans the anchor", (lo_x + hi_x) / 2.0, 3.0, 1e-6)
    check("terrain patch width", hi_x - lo_x, patch, 1e-3)

    # The reference figure stands 90° off the camera azimuth, at the target's
    # radius + 0.8 m: 2.828427 + 0.8 = 3.628427 m at ψ = 135°.
    fig = side["scale_reference"]["figure_at"]
    check_vec("figure position", fig, [3 + 3.628427 * 0.7071068,
                                       -2 - 3.628427 * 0.7071068], 1e-4)
    check("figure height", side["scale_reference"]["figure_height_m"], 1.70,
          1e-9)

    # Recipe primitives near the spot are built; the far prop is out of range
    # and the TARGET's own model is never in the picture.
    names = [p.get("name") for p in job["primitives"]]
    check_true("plate built", "plate_0" in names, str(names))
    check_true("wall built", "wall_0" in names)
    check_true("scale grid built", "scale_grid" in names)
    check_true("no model imported without files",
               not any(p.get("kind") == "model" for p in job["primitives"]))
    check("primitive kinds",
          sorted({p["kind"] for p in job["primitives"]}), ["figure", "mesh"])

    # Reach: what counts as "near the spot" is measured against the WHOLE
    # primitive, not against its corners. A big plate the target stands ON has
    # every corner outside the frame, and a long wall running past the spot has
    # both its ends outside it — both belong in the picture, and a far one does
    # not (patch radius here is 21.213/2 = 10.61 m).
    reach = fixture_scene()
    reach["plates"].append({"level": 0, "top_y": 0.0, "thickness": 0.14,
                            "outline": [[-40, -40], [40, -40], [40, 40],
                                        [-40, 40]]})
    reach["walls"].append({"level": 0, "from": [-40, -3], "to": [40, -3],
                           "base_y": 0.0, "height": 2.0, "thickness": 0.1})
    reach["walls"].append({"level": 0, "from": [-40, 60], "to": [40, 60],
                           "base_y": 0.0, "height": 2.0, "thickness": 0.1})
    wide = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "r1", "index": 0},
        location=fixture_location(), scene=reach, placements=placements,
        game=GameTime.from_parts(1, 46, 12, 0), height_at=lambda x, z: 0.0,
        model_files={})
    wide_names = [p.get("name") for p in wide["primitives"]]
    check_true("plate containing the spot is built", "plate_1" in wide_names,
               str(wide_names))
    check_true("long wall passing the spot is built", "wall_1" in wide_names)
    check_true("wall 62 m away is left out", "wall_2" not in wide_names)

    # Grid and figure are switchable, and switching them off must take both
    # the geometry AND the sidecar note with it.
    bare = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "r1", "index": 0},
        location=fixture_location(), scene=fixture_scene(),
        placements=placements, game=GameTime.from_parts(1, 46, 12, 0),
        params={"grid": False, "figure": False}, height_at=lambda x, z: 0.0,
        model_files={})
    bare_names = [p.get("name") for p in bare["primitives"]]
    check_true("grid off", "scale_grid" not in bare_names)
    check_true("figure off", not any(p["kind"] == "figure"
                                     for p in bare["primitives"]))
    check_true("sidecar records the reference state",
               bare["sidecar"]["scale_reference"]["figure_at"] is None)

    # The target model is EXCLUDED, its neighbours are not — the spot has to
    # be empty for the inpaint stage.
    with_files = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "r1", "index": 0},
        location=fixture_location(), scene=fixture_scene(),
        placements=placements, game=GameTime.from_parts(1, 46, 12, 0),
        height_at=lambda x, z: 0.0,
        model_files={"prop:r1:0": "/nope/table.glb",
                     "prop:r1:1": "/nope/bench.glb"})
    models = [p for p in with_files["primitives"] if p["kind"] == "model"]
    check("target model excluded, far model out of radius", len(models), 0)

    # Same call, same camera — the render must be reproducible.
    again = sc.build_context_scene(
        "ctx-demo", {"kind": "prop", "room_id": "r1", "index": 0},
        location=fixture_location(), scene=fixture_scene(),
        placements=placements, game=GameTime.from_parts(1, 46, 12, 0),
        params={"width": 1024, "height": 1024}, height_at=lambda x, z: 0.0,
        model_files={})
    check_true("camera is deterministic",
               again["sidecar"]["camera"] == side["camera"])

    # The other two target kinds resolve to the same five numbers.
    building = sc.build_context_scene(
        "ctx-demo", {"kind": "building"}, location=fixture_location(),
        scene=fixture_scene(), game=GameTime.from_parts(1, 46, 12, 0),
        height_at=lambda x, z: 0.0, model_files={})
    bt = building["sidecar"]["target"]
    check_vec("building anchor (boundary bbox centre)", bt["anchor"],
              [0.0, 0.0], 1e-9)
    # r_h = √(10² + 10²) = 14.142136, h = storey 3 → R = √(14.142136² + 1.5²)
    want_span = 2 * math.hypot(math.hypot(10.0, 10.0), 1.5)
    check("building span_m", bt["span_m"], round(want_span, 4), 1e-3)

    spot = sc.build_context_scene(
        "ctx-demo", {"kind": "spot", "at": [1.0, 1.0], "size_m": 2.0},
        location=fixture_location(), scene=fixture_scene(),
        game=GameTime.from_parts(1, 46, 12, 0),
        height_at=lambda x, z: 0.25, model_files={})
    st = spot["sidecar"]["target"]
    check_vec("spot anchor", st["anchor"], [1.0, 1.0], 1e-9)
    check("spot ground follows the terrain", st["ground_y"], 0.25, 1e-9)
    check("spot span_m", st["span_m"],
          round(2 * math.hypot(math.hypot(1.0, 1.0), 1.0), 4), 1e-3)

    # The frame record: the pin transform travels with the plate, or a local
    # metre cannot be turned back into a world metre.
    check_vec("pin recorded", [side["frame"]["pin"]["x"],
                              side["frame"]["pin"]["z"],
                              side["frame"]["pin"]["yaw_deg"]],
              [100.0, -50.0, 30.0], 1e-9)
    check("game time recorded", side["game_time"]["canonical"],
          "Y0001-D046T12:00:00")


# ── [6] Blender end to end ──────────────────────────────────────────────

def part_blender():
    print("\n[6] Blender end to end")
    from app.blender import runner
    st = runner.status()
    if not st["executable"] or not st["version"]:
        print("  SKIP ─────────────────────────────────────────────────────")
        print("  SKIP  no Blender binary found — the render is NOT checked.")
        print("  SKIP  set image_generation.blender_executable or put one on")
        print("  SKIP  PATH to run this section.")
        print("  SKIP ─────────────────────────────────────────────────────")
        return
    print(f"  Blender: {st['executable']} {st['version']}")
    import json
    import tempfile

    job = sc.build_context_scene(
        "ctx-demo", {"kind": "spot", "at": [3.0, -2.0], "size_m": 4.0,
                     "height_m": 0.0},
        location=fixture_location(), scene=fixture_scene(),
        game=GameTime.from_parts(1, 46, 12, 0),
        params={"width": 320, "height": 320, "samples": 8},
        height_at=lambda x, z: 0.0, model_files={})
    # A red patch at a point THIS side computed the pixel for. Whether the
    # Blender camera really is the sidecar camera cannot be argued from the
    # job file — it has to be measured in the finished picture, and a
    # mismatched frame convention (the camera's own axes are NOT converted,
    # a mesh's are) puts the whole scene out of frame without anything failing.
    # Off the room plate (z > 2) and just above the grid ribbons, so nothing
    # can hide it.
    patch_at = (4.4, 0.05, 4.0)
    half = 0.25
    job["primitives"].append(sc._mesh(
        "probe",
        [(patch_at[0] - half, patch_at[1], patch_at[2] - half),
         (patch_at[0] + half, patch_at[1], patch_at[2] - half),
         (patch_at[0] + half, patch_at[1], patch_at[2] + half),
         (patch_at[0] - half, patch_at[1], patch_at[2] + half)],
        [[0, 1, 2, 3]], (1.0, 0.0, 0.0), roughness=1.0))
    probe_u, probe_v, probe_d = sc.project(patch_at, job["sidecar"]["camera"])
    check_true("probe is in frame", probe_d > 0 and 0 < probe_u < 320
               and 0 < probe_v < 320,
               f"({probe_u:.1f}, {probe_v:.1f}) at {probe_d:.1f} m")
    with tempfile.TemporaryDirectory(prefix="smoke-context-") as tmp:
        out = sc.render_context("ctx-demo", {"kind": "spot"}, tmp, job=job)
        png = Path(out["png"])
        side_file = Path(out["sidecar"])
        check_true("png written", png.is_file() and png.stat().st_size > 0,
                   f"{png.name} {png.stat().st_size if png.is_file() else 0} B")
        check_true("sidecar written", side_file.is_file())
        if not side_file.is_file():
            return
        written = json.loads(side_file.read_text(encoding="utf-8"))
        check_true("sidecar camera is VERBATIM what was handed over",
                   written["camera"] == job["sidecar"]["camera"])
        check_true("sidecar target is VERBATIM",
                   written["target"] == job["sidecar"]["target"])
        check_true("sidecar sun is VERBATIM",
                   written["sun"] == job["sidecar"]["sun"])
        check("render width in the sidecar", written["render"]["width"], 320)
        check("render height in the sidecar", written["render"]["height"], 320)
        check_true("render records the Blender version",
                   bool(written["render"].get("blender_version")),
                   written["render"].get("blender_version", ""))
        built = written["render"]["objects"]
        check_true("meshes were built", built["mesh"] >= 3, str(built))
        check("figure built", built["figure"], 1)
        check("no model was expected", built["model"], 0)
        # A PNG header is four bytes; anything else means the render failed
        # in a way Blender still called a success.
        check_true("png is a real PNG",
                   png.read_bytes()[:4] == b"\x89PNG")
        _probe_pixel(png, probe_u, probe_v)
        _placed_model(st, tmp)


def _placed_model(st, tmp):
    """place() (§ B2) on a real GLB, checked against a hand-derived box.

    Fixture: a 2 × 2 × 2 m cube, spec ``max_m`` 1.0, ``measure`` "xyz",
    ``fix_euler`` 0, ``yaw_deg`` 0, anchor (3, −2), ``bottom_y`` 0.5.
      * measured extent = max(2, 2, 2) = 2 m  ->  scale = 1.0 / 2 = 0.5
      * the placed box is therefore 1 × 1 × 1 m,
      * centred on the anchor in XZ and standing with its bottom at 0.5 m.
    In Blender's frame (x, −z, y) the anchor (3, −2) is (3, 2), so the box is
        x ∈ [2.5, 3.5], y ∈ [1.5, 2.5], z ∈ [0.5, 1.5].
    """
    import subprocess
    fixture = Path(tmp) / "cube.py"
    fixture.write_text(
        'import bpy, sys\n'
        'out = sys.argv[sys.argv.index("--") + 1]\n'
        'bpy.ops.wm.read_factory_settings(use_empty=True)\n'
        'bpy.ops.mesh.primitive_cube_add(size=2)\n'
        'bpy.ops.export_scene.gltf(filepath=out + "/cube.glb", '
        'export_format="GLB")\n'
        'print("FIXTURE_OK")\n', encoding="utf-8")
    proc = subprocess.run([st["executable"], "--background", "--factory-startup",
                           "--python", str(fixture), "--", tmp],
                          capture_output=True, text=True, timeout=180)
    if "FIXTURE_OK" not in proc.stdout:
        check_true("cube fixture built", False, proc.stderr[-400:])
        return
    scene = fixture_scene()
    scene["models"][0].update({"max_m": 1.0, "measure": "xyz",
                               "bottom_y": 0.5})
    job = sc.build_context_scene(
        "ctx-demo", {"kind": "spot", "at": [3.0, -2.0], "size_m": 4.0},
        location=fixture_location(), scene=scene,
        game=GameTime.from_parts(1, 46, 12, 0),
        params={"width": 128, "height": 128, "samples": 2, "grid": False,
                "figure": False},
        height_at=lambda x, z: 0.0,
        model_files={"prop:r1:0": str(Path(tmp) / "cube.glb")})
    models = [p for p in job["primitives"] if p["kind"] == "model"]
    check("one model to place", len(models), 1)
    out = sc.render_context("ctx-demo", {"kind": "spot"},
                            Path(tmp) / "placed", job=job)
    placed = (out.get("data") or {}).get("placed") or []
    check("model placed", len(placed), 1)
    if placed:
        check_vec("placed bbox (Blender frame)", placed[0]["bbox"],
                  [2.5, 1.5, 0.5, 3.5, 2.5, 1.5], 1e-4)


def _probe_pixel(png, want_u, want_v):
    """THE camera check: where did the red patch actually land?

    The projection maths above proves the sidecar is self-consistent; only
    the picture proves that Blender's camera is the same camera. The patch is
    the only saturated red in the frame, so its centre of mass in redness is
    its position — measured, not eyeballed (§ B5a).
    """
    try:
        from PIL import Image
    except ImportError:                    # pragma: no cover
        print("  SKIP  no Pillow — the rendered pixel is NOT checked")
        return
    img = Image.open(png).convert("RGB")
    w, h = img.size
    px = img.load()
    total = 0.0
    su = sv = 0.0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            redness = r - max(g, b)
            if redness > 60:
                total += redness
                su += x * redness
                sv += y * redness
    if total <= 0:
        check_true("red probe visible in the render", False, "no red pixels")
        return
    got_u, got_v = su / total, sv / total
    # 2 px: the patch is half a metre across and its centre of mass carries
    # the anti-aliasing of its own edges.
    check("probe pixel u (rendered vs projected)", got_u, want_u, 2.0)
    check("probe pixel v (rendered vs projected)", got_v, want_v, 2.0)


def main():
    part_camera()
    part_projection()
    part_mask()
    part_sun()
    part_scene()
    part_blender()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
