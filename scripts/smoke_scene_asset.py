#!/usr/bin/env python3
"""Numeric check of the SCENE-ASSET pipeline — mask maths, crop, size, yaw, contact.

Usage:
    ./.venv/bin/python scripts/smoke_scene_asset.py

No server, no world DB, no GPU, no Blender: only the pure parts of
``app/core/scene_asset.py``. Design: ``docs/scene-asset-pipeline.md``; the plate
camera is the one from ``scripts/smoke_scene_context.py``, so the two documents
share their numbers instead of each inventing some.

──────────────────────────────────────────────────────────────────────────
FIXTURE — the same plate as the context smoke: a 4 m × 4 m footprint on flat
ground at the local point (3, −2), yaw 0, height 0; lens 50 mm on a 36 mm
sensor; elevation 35°, azimuth offset 45°, fill 0.40, 1024 × 1024 px. From
there: span = 2·√(2²+2²) = 5.656854 m, d = 50·5.656854/(36·0.40) = 19.641855 m,
fx = fy = 1024·50/36 = 1422.222222, and the four projected footprint corners
are (512.00, 406.93), (716.80, 512.00), (512.00, 645.18), (307.20, 512.00).

1. EXPECTED PIXEL SIZE. The mask hull IS the expected box, so its bbox is
   [307.20, 406.93, 716.80, 645.18]:
       width  = 716.80 − 307.20 = 409.60 px
       height = 645.18 − 406.93 = 238.25 px
   The width is not a coincidence and is the check that the framing rule
   survives into this stage: the two side corners lie exactly abeam the target
   centre, hence at the framing distance d, and they are the sphere span apart:
       409.60 = fy · span / d = 1422.222222 · 5.656854 / 19.641855
              = H · fill      = 1024 · 0.40
   An object drawn at half that height gives a ratio of 0.5 and passes the
   0.40 band; at a third (79.42 px) it gives 0.333 and fails.

2. MASK GROW. margin 0.12 of the bbox's LONGER side:
       grow_px = 0.12 · 409.60 = 49.152 px
   The growth itself, on the unit square (0,0)…(10,10) so the arithmetic is
   visible: centroid (5,5), every vertex direction is a diagonal
   (±0.7071068, ±0.7071068), grow 0.12·10 = 1.2 px, so a corner moves by
   1.2·0.7071068 = 0.8485281 px outward:
       (0,0) → (−0.8485281, −0.8485281),  (10,10) → (10.8485281, 10.8485281)

3. RASTERISATION on PIXEL CENTRES. The square (2,2)…(7,7) covers the centres
   x + 0.5 ∈ [2,7], i.e. columns 2…6 and rows 2…6 — a 5 × 5 = 25-pixel block.
   Asking about pixel CORNERS instead would shift the region half a pixel,
   which is exactly the seam a cutout shows later.

4. DIFFERENCE MASK on an 8 × 8 plate, threshold 12/255. ``after`` differs from
   ``before`` in four places:
       a 5 × 5 block  rows 2…6 × cols 2…6, all channels +200  → changed
       a speck        (0,0),               all channels +200  → changed
       a colour-only  (1,6), R +20 only                       → changed
                      (the distance is the LARGEST channel, so a pure hue
                       shift counts; an average would have read 20/3 = 6.7)
       a noise pixel  (7,7), all channels +8                  → NOT changed
   → 27 changed pixels. Restricting to the region polygon (2,2)…(7,7) leaves
   the block alone: 25.
   MORPHOLOGY, exact sets:
       open (erode → dilate) on {block ∪ speck}: erosion keeps only pixels
       whose full 3 × 3 neighbourhood is inside, i.e. rows 3…5 × cols 3…5
       (9 px) — the speck at the corner has neighbours outside the image and
       dies. Dilating those 9 px gives rows 2…6 × cols 2…6 back: the block
       exactly, 25 px.
       close (dilate → erode) on {block minus its centre (4,4)}: the dilation
       covers rows 1…7 × cols 1…7 (the hole fills, it has neighbours), the
       erosion takes the border row/column back off (row 7 and column 7 touch
       the image edge) and leaves rows 2…6 × cols 2…6: 25 px, hole filled.

5. CROP AFFINE. A cutout bbox of [307, 407, 717, 645] in the 1024 plate:
       side  = max(717−307, 645−407) · (1 + 2·0.15) = 410 · 1.3 = 533.0
       centre= ((307+717)/2, (407+645)/2) = (512, 526)
       x0    = 512 − 266.5 = 245.5     y0 = 526 − 266.5 = 259.5
       scale = 1024 / 533 = 1.9212008
   The plate centre maps to the patch centre because 266.5 · 1024/533 = 512
   exactly, and the equivalent intrinsics follow:
       fx' = 1422.222222 · 1024/533 = 52428800/19188 = 2732.3744
       cx' = (512 − 245.5) · 1024/533 = 512.0
   Round trip: (512, 526) → (512, 512) → (512, 526).

6. YAW. The plate camera stands at map azimuth ψ AS SEEN FROM THE TARGET
   (``position = centre + d·(cos ε·sin ψ, sin ε, cos ε·cos ψ)``). Image-to-3D
   reconstructs in the input view's frame, so what the picture showed faces
   local +Z — the glTF convention ("the front of an asset faces +Z") and our
   contract's prop convention (front = south = facing 0) are the same
   direction, because the scene frame is x east, y up, z SOUTH. ``rot_y(yaw)``
   turns local south to map azimuth ``yaw``, so the front points at ``yaw``,
   and it has to point at the camera:
       yaw = ψ           ψ = 45°  → 45°     (NOT 225°: ψ+180 is the direction
       yaw = ψ mod 360   ψ = 370° → 10°      the camera LOOKS, and turning the
                         ψ = −30° → 330°     object into it shows the picture
                                             from behind)
   With the plate's azimuth offset at 0 the formula returns the AUTHORED yaw
   unchanged — the 45° offset IS the whole difference between the authored
   orientation and the drawn one, and the drawn one is what the mesh shows.

7. CONTACT AND SINK. A 2 m × 2 m footprint at the anchor (0,0), yaw 0, gives
   the 3 × 3 lattice x, z ∈ {−1, 0, 1}; tolerance 0.05 m, required ratio 0.60.
       A — flat ground (0.00 everywhere), authored offset_y +0.30:
           bottom 0.30, every gap 0.30 > 0.05  → ratio 0/9 = 0.0, floating
           sink: lift = 0.30 − 0.00 → offset_y 0.00, bottom 0.00
           after: every gap 0.00                → ratio 9/9 = 1.0   PASS
       B — gentle slope g(x,z) = 0.02·x → samples −0.02, 0.00, +0.02 (3 each),
           authored offset_y +0.30:
           before: gaps 0.32/0.30/0.28          → ratio 0/9 = 0.0
           sink: lift = 0.30 − (−0.02) = 0.32 → offset_y = 0.30 − 0.32 = −0.02
           after: gaps 0.00 / −0.02 / −0.04     → ratio 9/9 = 1.0   PASS
           slope 0.04 m < 0.10 m                → no levelling suggestion
       C — real slope g(x,z) = 0.10·x → samples −0.10, 0.00, +0.10, offset 0:
           before: gaps +0.10 / 0.00 / −0.10    → ratio 3/9 = 0.3333
           sink: lift = 0.10 → offset_y −0.10, bottom −0.10
           after: gaps 0.00 / −0.10 / −0.20     → ratio 3/9 = 0.3333  FAIL
           Sinking cannot flatten a slope — which is precisely why the result
           carries a levelling SUGGESTION (drop 0.20 m > 0.10 m) instead of
           quietly reshaping the terrain.
       D — ONE DATUM (§ B1 addendum): the sampler stands on the placement's
           own floor, so a yard prop at bottom_y 0.09 over a 0.08 floor plate
           has a 0.01 gap (in contact) instead of a 0.09 one (floating).
       E — A DIALLED SINK IS NOT A DEFECT (§ B2 addendum 2026-08-20). The
           prop declares ``ground_offset_m``, which the payload has already
           put into ``bottom_y``, so it belongs to the EXPECTED base:
             floor 0.08, offset −0.20 → sampler −0.12, bottom_y
             0.08 + 0.01 − 0.20 = −0.11, gap 0.01                → 9/9 PASS
           RED PROBE, both directions: against the offset-BLIND sampler (0.08)
           the same prop reads 0/9 and fails the 0.60 gate — nothing is
           "corrected", because a bottom below its own ground is left to the
           author, so the damage is a wrong VERDICT on a correct placement.
           The mirror case does move: a prop dialled +0.20 (bottom_y 0.29)
           is in contact with its own base 0.28, while the blind sampler
           reads a 0.21 gap and sinks it by −0.21 — undoing the author's lift.

8. RETRY BUDGET. retries 2 = up to three attempts; an attempt that raises is a
   failed attempt, not a failed run. A fake chain that succeeds on the SECOND
   seed leaves two records and reports ok.

9. THE CACHE SENTINEL. ``backend.generate`` may answer with the string
   "NO_NEW_IMAGE" instead of image bytes; indexing that string yields "N" and
   the cutout stage would die far from the cause. Every shape of it must come
   back as "no image".

10. BEFORE AND AFTER — what the run replaces, and how the replacement is
    marked. Two vocabularies of § B2 meet here, in the direction the rest of
    the pipeline does not need: a placement's ``variant`` is a POSITION in the
    prop's ACTIVE, MESHED variants, while a store index is what addresses a
    file. HAND CASE — a prop with three variants, the middle one switched off,
    so ``active_variant_tiers`` answers the store indices [0, 2]:

        placement variant 0  → position 0 → store 0
        placement variant 1  → position 1 → store 2   (NOT store 1 — that one
                                                       is switched off)
        placement without the field → position 0 → store 0
        placement variant 3  → 3 mod 2 = 1 → store 2
        placement variant 5  → 5 mod 2 = 1 → store 2

    The MODULO is not defensiveness: both renderers resolve the index that way
    (§ B2-Nachtrag, "Der Index wird MODULO gerechnet, nicht geklemmt"), so the
    "before" picture has to be the one that was actually on screen. A prop with
    no meshed variant at all has no before — a first generation replaces
    nothing.

    Three wirings decide whether that picture and its marker are true, and none
    of them can be seen from a pure function — they are read out of the source:

    a) the cutout is handed to the store WITH the origin (``**origin``). A
       dropped kwarg would make every scene variant read as a product shot;
    b) ``origin_ts`` is the run's OWN ``record["started_at"]``. A fresh clock
       read would put the badge and the run directory a few seconds apart, and
       findings here are numbers, not approximations;
    c) the before picture is COPIED into the run directory BEFORE
       ``run_attempts`` runs. A run that refines the very variant the placement
       pointed at overwrites the original a moment later, so a live URL — or a
       copy taken afterwards — would show the after in both frames.
──────────────────────────────────────────────────────────────────────────
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np                                            # noqa: E402

from app.core import scene_asset as sa                        # noqa: E402
from app.core import scene_context as sc                      # noqa: E402

PX_TOL = 0.01
failures = []


def check(label, got, want, tol=0.0):
    ok = abs(float(got) - float(want)) <= tol if tol else got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def check_vec(label, got, want, tol):
    ok = len(got) == len(want) and all(abs(float(g) - float(w)) <= tol
                                       for g, w in zip(got, want))
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got "
          f"{[round(float(g), 4) for g in got]}, want {want}")
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
    return sc.solve_camera(ANCHOR, span, ground_y=0.0, height_m=0.0,
                           yaw_deg=0.0, width=1024, height=1024)


# ── [1] Expected pixel size ─────────────────────────────────────────────

def part_expected():
    print("\n[1] Expected pixel size — the plate camera decides how big the "
          "object must look")
    cam = camera_fixture()
    box = sa.expected_px_bbox(FOOTPRINT, 0.0, 0.0, cam)
    check_vec("expected bbox", box, [307.20, 406.93, 716.80, 645.18], 0.02)
    width = box[2] - box[0]
    height = box[3] - box[1]
    check("expected width (= H · fill)", width, 409.60, 0.02)
    check("expected width (= fy · span / d)", width,
          cam["fy"] * cam["span_m"] / cam["distance_m"], 0.02)
    check("expected height", height, 238.25, 0.02)
    # The ratio the insert step is judged by.
    check("ratio of an exactly right cutout",
          sa.px_size_ratio([0, 0, 0, height], box), 1.0, 1e-9)
    check("ratio of a half-height cutout",
          sa.px_size_ratio([0, 0, 0, height / 2], box), 0.5, 1e-9)
    check_true("half height passes the 0.40 band",
               sa.px_size_ratio([0, 0, 0, height / 2], box) >= 0.40)
    check_true("a third of the height fails it",
               sa.px_size_ratio([0, 0, 0, height / 3], box) < 0.40,
               f"{height / 3:.2f} px")


# ── [2] Mask grow ───────────────────────────────────────────────────────

def part_mask_grow():
    print("\n[2] Mask grow — margin 0.12 of the bbox's longer side")
    cam = camera_fixture()
    hull = sc.mask_polygon(FOOTPRINT, 0.0, 0.0, cam)
    check("grow_px for the plate mask", sa.grow_px_for(hull, 0.12),
          49.152, 1e-3)
    square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    check("grow_px for the unit square", sa.grow_px_for(square, 0.12),
          1.2, 1e-9)
    grown = sa.grow_polygon(square, 1.2)
    check_vec("grown corner (0,0)", grown[0],
              [-0.8485281, -0.8485281], 1e-6)
    check_vec("grown corner (10,10)", grown[2],
              [10.8485281, 10.8485281], 1e-6)
    check_true("a margin of 0 leaves the polygon alone",
               sa.grow_polygon(square, 0.0) == square)


# ── [3] Rasterisation ───────────────────────────────────────────────────

def part_raster():
    print("\n[3] Rasterisation — pixel CENTRES, not corners")
    mask = sa.rasterize_polygon([[2, 2], [7, 2], [7, 7], [2, 7]], 8, 8)
    check("pixels inside (2,2)…(7,7) on an 8×8 plate", int(mask.sum()), 25)
    check_true("rows 2…6 × cols 2…6 exactly",
               bool(mask[2:7, 2:7].all()) and int(mask.sum()) == 25)
    check_true("row 1 empty", not bool(mask[1].any()))
    check_true("row 7 empty", not bool(mask[7].any()))
    big = sa.rasterize_polygon([[0, 0], [10, 0], [10, 10], [0, 10]], 12, 12)
    check("a 10×10 square rasterises to 100 px", int(big.sum()), 100)


# ── [4] Difference mask and morphology ──────────────────────────────────

def plate_fixture():
    before = np.zeros((8, 8, 3), dtype=np.uint8)
    after = before.copy()
    after[2:7, 2:7] = 200          # the object
    after[0, 0] = 200              # a speck outside the region
    after[1, 6, 0] = 20            # colour-only change
    after[7, 7] = 8                # under the threshold
    return before, after


def part_difference():
    print("\n[4] Difference mask — 8×8 plate, threshold 12/255")
    before, after = plate_fixture()
    diff = sa.difference_mask(before, after, 12)
    check("changed pixels", int(diff.sum()), 27)
    check_true("the colour-only pixel counts", bool(diff[1, 6]),
               "max channel 20 ≥ 12 (an average would read 6.7)")
    check_true("the under-threshold pixel does not", not bool(diff[7, 7]))
    region = sa.rasterize_polygon([[2, 2], [7, 2], [7, 7], [2, 7]], 8, 8)
    inside = diff & region
    check("inside the region", int(inside.sum()), 25)

    speckled = np.zeros((8, 8), dtype=bool)
    speckled[2:7, 2:7] = True
    speckled[0, 0] = True
    eroded = sa._shifted_all(speckled)
    check("erosion of block+speck", int(eroded.sum()), 9)
    check_true("erosion keeps rows 3…5 × cols 3…5",
               bool(eroded[3:6, 3:6].all()))
    opened = sa.morph_open(speckled)
    check("open() = the block, speck gone", int(opened.sum()), 25)
    check_true("open() is exactly the block",
               bool(opened[2:7, 2:7].all()) and not bool(opened[0, 0]))

    holed = np.zeros((8, 8), dtype=bool)
    holed[2:7, 2:7] = True
    holed[4, 4] = False
    check("block with a pinhole", int(holed.sum()), 24)
    closed = sa.morph_close(holed)
    check("close() fills the hole", int(closed.sum()), 25)
    check_true("close() is exactly the block",
               bool(closed[2:7, 2:7].all()) and not bool(closed[1].any()))
    check_vec("mask bbox", sa.mask_bbox(closed), [2, 2, 6, 6], 0)


# ── [5] Crop affine ─────────────────────────────────────────────────────

def part_crop():
    print("\n[5] Crop affine — cutout bbox [307, 407, 717, 645] in a 1024 plate")
    aff = sa.crop_affine([307, 407, 717, 645], 1024, 1024,
                         out_px=1024, margin=0.15)
    check("side", aff["side"], 533.0, 1e-9)
    check("x0", aff["x0"], 245.5, 1e-9)
    check("y0", aff["y0"], 259.5, 1e-9)
    check("scale", aff["scale"], 1024 / 533, 1e-12)
    u, v = sa.to_patch(512, 526, aff)
    check("plate centre → patch u", u, 512.0, 1e-9)
    check("plate centre → patch v", v, 512.0, 1e-9)
    back = sa.to_plate(u, v, aff)
    check("round trip u", back[0], 512.0, 1e-9)
    check("round trip v", back[1], 526.0, 1e-9)
    corner = sa.to_plate(*sa.to_patch(307.0, 645.0, aff), aff)
    check_vec("round trip of a bbox corner", corner, [307.0, 645.0], 1e-9)
    cam = camera_fixture()
    intr = sa.equivalent_intrinsics(cam, aff)
    check("equivalent fx", intr["fx"], 52428800 / 19188, 1e-6)
    check("equivalent cx", intr["cx"], 512.0, 1e-9)
    # A bbox at the plate edge must not crop outside the picture.
    edge = sa.crop_affine([0, 0, 100, 100], 1024, 1024, out_px=512,
                          margin=0.15)
    check("edge crop x0 clamped to 0", edge["x0"], 0.0, 1e-9)
    check_true("edge crop stays inside the plate",
               edge["x0"] + edge["side"] <= 1024.0 + 1e-9)


# ── [6] Yaw ─────────────────────────────────────────────────────────────

def part_yaw():
    print("\n[6] Yaw — the mesh's front turns back to the plate camera")
    check("ψ = 45° → yaw", sa.placement_yaw_deg(45.0), 45.0, 1e-9)
    check("ψ = 370° → yaw", sa.placement_yaw_deg(370.0), 10.0, 1e-9)
    check("ψ = −30° → yaw", sa.placement_yaw_deg(-30.0), 330.0, 1e-9)
    check_true("NOT ψ + 180 (that is where the camera LOOKS)",
               abs(sa.placement_yaw_deg(45.0) - 225.0) > 1e-6)
    # The plate camera's own ψ, and the identity that makes the offset visible.
    cam = sc.solve_camera([0.0, 0.0], 4.0, yaw_deg=110.0,
                          azimuth_offset_deg=0.0)
    check("azimuth offset 0 → the authored yaw survives",
          sa.placement_yaw_deg(cam["azimuth_deg"]), 110.0, 1e-9)
    cam45 = sc.solve_camera([0.0, 0.0], 4.0, yaw_deg=110.0,
                            azimuth_offset_deg=45.0)
    check("the default 45° offset turns it by exactly 45°",
          sa.placement_yaw_deg(cam45["azimuth_deg"]), 155.0, 1e-9)
    # The front direction the yaw produces must BE the direction to the camera.
    front = sc.mat_apply(sc.rot_y(sa.placement_yaw_deg(cam45["azimuth_deg"])),
                         (0.0, 0.0, 1.0))
    to_cam = (cam45["position"][0] - 0.0, cam45["position"][2] - 0.0)
    n = (to_cam[0] ** 2 + to_cam[1] ** 2) ** 0.5
    check_vec("front direction = direction to the camera",
              [front[0], front[2]], [to_cam[0] / n, to_cam[1] / n], 1e-9)


# ── [7] Contact and sink ────────────────────────────────────────────────

def part_contact():
    print("\n[7] Contact and sink — 2 m × 2 m footprint, tolerance 0.05 m")
    pts = sa.footprint_samples([0.0, 0.0], 2.0, 2.0, 0.0)
    check("nine samples", len(pts), 9)
    check_vec("first sample (−w, −d)", pts[0], [-1.0, -1.0], 1e-9)
    check_vec("centre sample", pts[4], [0.0, 0.0], 1e-9)
    check_vec("last sample (+w, +d)", pts[8], [1.0, 1.0], 1e-9)
    turned = sa.footprint_samples([0.0, 0.0], 2.0, 4.0, 90.0)
    check_vec("yawed 90°: (−1, 0, −2) → (−2, 1)", turned[0], [-2.0, 1.0], 1e-9)

    print("  A — flat ground, authored offset_y +0.30")
    ground = [0.0] * 9
    before = sa.contact_check(0.30, ground, tolerance_m=0.05)
    check("ratio before", before["contact_ratio"], 0.0, 1e-9)
    check_true("reported as floating", before["floating"])
    new_off = sa.sink_offset_y(0.30, ground, 0.30, tolerance_m=0.05)
    check("sunk offset_y", new_off, 0.0, 1e-9)
    after = sa.contact_check(0.0 + new_off, ground, tolerance_m=0.05)
    check("ratio after", after["contact_ratio"], 1.0, 1e-9)

    print("  B — gentle slope 0.02 m/m, authored offset_y +0.30")
    ground = [0.02 * p[0] for p in pts]
    check_vec("ground samples", sorted(set(ground)), [-0.02, 0.0, 0.02], 1e-9)
    before = sa.contact_check(0.30, ground, tolerance_m=0.05)
    check("ratio before", before["contact_ratio"], 0.0, 1e-9)
    new_off = sa.sink_offset_y(0.30, ground, 0.30, tolerance_m=0.05)
    check("sunk offset_y", new_off, -0.02, 1e-9)
    after = sa.contact_check(0.0 + new_off, ground, tolerance_m=0.05)
    check("ratio after", after["contact_ratio"], 1.0, 1e-9)
    check("slope under the footprint", after["slope_m"], 0.04, 1e-9)
    check_true("below the levelling threshold", after["slope_m"] < 0.10)

    print("  C — real slope 0.10 m/m, offset_y 0")
    ground = [0.10 * p[0] for p in pts]
    before = sa.contact_check(0.0, ground, tolerance_m=0.05)
    check("ratio before", before["contact_ratio"], 3 / 9, 1e-9)
    check_true("not floating (part of it is buried)", not before["floating"])
    new_off = sa.sink_offset_y(0.0, ground, 0.0, tolerance_m=0.05)
    check("sunk offset_y", new_off, -0.10, 1e-9)
    after = sa.contact_check(0.0 + new_off, ground, tolerance_m=0.05)
    check("ratio after (sinking cannot flatten a slope)",
          after["contact_ratio"], 3 / 9, 1e-9)
    check("slope under the footprint", after["slope_m"], 0.20, 1e-9)
    check_true("above the levelling threshold → suggestion",
               after["slope_m"] > 0.10)
    check_true("and below the required contact ratio",
               after["contact_ratio"] < 0.60)
    check_true("an already grounded placement is not sunk",
               sa.sink_offset_y(0.0, [0.0] * 9, 0.0, tolerance_m=0.05) is None)
    check_true("a buried placement is reported, not lifted",
               sa.sink_offset_y(-1.0, [0.0] * 9, -1.0,
                                tolerance_m=0.05) is None)

    # ── D — ONE DATUM (§ B1 addendum 2026-08-20) ────────────────────────
    # `place()` compares the payload's own `bottom_y` (target.ground_y)
    # against this sampler. Since the drawn storey floor became the datum, a
    # yard placement's bottom_y is 0.08 (level plate) + 0.01 (clearance) =
    # 0.09 while the terrain under it is flat 0 — so the sampler has to
    # answer on the SAME floor or the check reads 0.09 as a gap: 0.09 > the
    # 0.05 tolerance means nothing in contact, and the run sinks a correctly
    # standing prop by 0.09 back into the slab it stands on.
    print("  D — the floor datum: sampler and payload speak one frame")
    flat_loc = {"id": "loc"}          # no pin, no boundary: world 0, relief 0
    bare = sa.ground_sampler(flat_loc)
    check("without a floor the sampler is the bare terrain", bare(3.0, -2.0),
          0.0, 1e-9)
    yard = sa.ground_sampler(flat_loc, 0.08)
    check("on the yard's drawn floor it answers 0.08", yard(3.0, -2.0),
          0.08, 1e-9)
    room = sa.ground_sampler(flat_loc, 0.10)
    check("in a built room, the room plate 0.10", room(1.0, 1.0), 0.10, 1e-9)
    lifted = [yard(p[0], p[1]) for p in pts]
    check("a yard prop at bottom_y 0.09 is IN CONTACT with it",
          sa.contact_check(0.09, lifted, tolerance_m=0.05)["contact_ratio"],
          1.0, 1e-9)
    check_true("...and is therefore not sunk",
               sa.sink_offset_y(0.09, lifted, 0.0, tolerance_m=0.05) is None)
    # The regression pin: the same placement against the OLD, floor-blind
    # sampler — every sample out of contact, and a −0.09 sink on top.
    blind = [bare(p[0], p[1]) for p in pts]
    check("floor-blind, the same prop is 'floating' (0/9)",
          sa.contact_check(0.09, blind, tolerance_m=0.05)["contact_ratio"],
          0.0, 1e-9)
    check("...and would be sunk by the floor's own height",
          sa.sink_offset_y(0.09, blind, 0.0, tolerance_m=0.05), -0.09, 1e-9)

    # ── E — A DELIBERATE SINK IS NOT A DEFECT (§ B2 addendum 2026-08-20) ──
    # The prop itself may declare how deep it stands (`ground_offset_m`, e.g.
    # a trunk without a root ball at −0.20). The payload puts that into
    # `bottom_y`, so the yard prop above now composes 0.08 + 0.01 − 0.20 =
    # −0.11. It is EXPECTED to be there, so the sampler carries the same term:
    # expected base = floor 0.08 + sink (−0.20) = −0.12, and the remaining
    # 0.01 is the clearance the tolerance was always meant to swallow.
    print("  E — a prop dialled into the ground stands where it should")
    sunk_sampler = sa.ground_sampler(flat_loc, 0.08, -0.20)
    check("floor + the prop's own sink", sunk_sampler(3.0, -2.0), -0.12, 1e-9)
    sunk_ground = [sunk_sampler(p[0], p[1]) for p in pts]
    check("the sunk prop is IN CONTACT at its sunk base (9/9)",
          sa.contact_check(-0.11, sunk_ground,
                           tolerance_m=0.05)["contact_ratio"], 1.0, 1e-9)
    check_true("...and is therefore not 'corrected'",
               sa.sink_offset_y(-0.11, sunk_ground, 0.0,
                                tolerance_m=0.05) is None)
    # THE RED PROBE: the offset-blind sampler of the day before. It answers
    # the bare floor 0.08 while the payload states −0.11, so the bottom is
    # 0.19 BELOW every sample. `sink_offset_y` does not touch it (a bottom
    # under its own ground is left to the author, by design), so the damage is
    # not a wrong number but a VERDICT: 0/9 in contact is below the required
    # 0.60 ratio, and the run rejects a placement that stands exactly where it
    # was told to. The offset must therefore be part of the expected base.
    blind_sunk = [yard(p[0], p[1]) for p in pts]
    check("offset-blind, the same prop reads 0/9 in contact",
          sa.contact_check(-0.11, blind_sunk,
                           tolerance_m=0.05)["contact_ratio"], 0.0, 1e-9)
    check_true("...which fails the 0.60 contact gate the run demands",
               sa.contact_check(-0.11, blind_sunk,
                                tolerance_m=0.05)["contact_ratio"] < 0.60)
    check_true("(nothing is 'corrected' either — a bottom below its ground "
               "is the author's business)",
               sa.sink_offset_y(-0.11, blind_sunk, 0.0,
                                tolerance_m=0.05) is None)
    # The mirror case, where the blind sampler DOES move the prop: a prop
    # dialled 0.20 m UP (a lamp on a hidden base). Seen against the informed
    # sampler it is in contact; seen against the blind one it floats 0.20 m
    # and is sunk by exactly the author's lift.
    lift_sampler = sa.ground_sampler(flat_loc, 0.08, 0.20)
    lifted_ground = [lift_sampler(p[0], p[1]) for p in pts]
    check("a prop dialled 0.20 m UP is in contact with its own base",
          sa.contact_check(0.29, lifted_ground,
                           tolerance_m=0.05)["contact_ratio"], 1.0, 1e-9)
    check("...while the blind sampler sinks it by the author's 0.20 m",
          sa.sink_offset_y(0.29, blind_sunk, 0.0, tolerance_m=0.05),
          -0.21, 1e-9)


# ── [8] Retry budget ────────────────────────────────────────────────────

def part_retries():
    print("\n[8] Retry budget — bounded loop with injected attempts")
    calls = []

    def chain(attempt, seed):
        calls.append((attempt, seed))
        return {"ok": attempt == 1, "failures": [] if attempt == 1 else ["no"]}

    res = sa.run_attempts(chain, retries=2, seeds=[11, 22, 33])
    check_true("succeeds on the second seed", res["ok"])
    check("attempts run", len(res["attempts"]), 2)
    check("seed of attempt 2", res["attempts"][1]["seed"], 22)
    check("no failures reported", res["failures"], [])

    res = sa.run_attempts(lambda a, s: {"ok": False, "failures": ["nope"]},
                          retries=2, seeds=[1, 2, 3])
    check("exhausted budget runs 1 + retries", len(res["attempts"]), 3)
    check("failure list survives", res["failures"], ["nope"])

    def raising(attempt, seed):
        if attempt == 0:
            raise RuntimeError("gateway hiccup")
        return {"ok": True}

    res = sa.run_attempts(raising, retries=1, seeds=[7, 8])
    check_true("a raising attempt is a failed attempt, not a failed run",
               res["ok"])
    check("both attempts recorded", len(res["attempts"]), 2)

    res = sa.run_attempts(lambda a, s: {"ok": False}, retries=0, seeds=[5])
    check("retries 0 = exactly one attempt", len(res["attempts"]), 1)


# ── [9] Backend contract ────────────────────────────────────────────────

class _Stub:
    def __init__(self, category="", api_type=""):
        self.category = category
        self.api_type = api_type


def part_backend():
    print("\n[9] Backend contract — who can take a mask, and the cache sentinel")
    check_true("category 'inpaint' takes a mask",
               sa.backend_takes_mask(_Stub(category="inpaint")))
    check_true("openai_diffusion takes a mask whatever its category",
               sa.backend_takes_mask(_Stub(category="txt2img",
                                           api_type="openai_diffusion")))
    check_true("a Together backend does NOT",
               not sa.backend_takes_mask(_Stub(category="img2img",
                                               api_type="together")))
    check_true("an A1111 backend does NOT",
               not sa.backend_takes_mask(_Stub(api_type="a1111")))

    check_true("bare 'NO_NEW_IMAGE' is not an image",
               sa._first_image("NO_NEW_IMAGE") is None)
    check_true("['NO_NEW_IMAGE'] is not an image",
               sa._first_image(["NO_NEW_IMAGE"]) is None)
    check_true("an empty list is not an image", sa._first_image([]) is None)
    check_true("None is not an image", sa._first_image(None) is None)
    check("real bytes come through", sa._first_image([b"PNG"]), b"PNG")


# ── [10] Before / after ─────────────────────────────────────────────────

def _fn_ast(name):
    """The AST of ONE top-level function of ``app/core/scene_asset.py``."""
    src = Path(__file__).resolve().parents[1] / "app" / "core" / "scene_asset.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _origin_kwarg_passed():
    """(a) ``_attempt`` unpacks the origin into ``save_source_image``."""
    fn = _fn_ast("_attempt")
    for node in ast.walk(fn) if fn else ():
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "save_source_image"):
            continue
        for kw in node.keywords:
            if kw.arg is not None:          # a ** unpacking has no name
                continue
            if any(isinstance(n, ast.Name) and n.id == "origin"
                   for n in ast.walk(kw.value)):
                return True
    return False


def _origin_ts_from_record():
    """(b) the origin's ``origin_ts`` is ``record["started_at"]``."""
    fn = _fn_ast("generate")
    for node in ast.walk(fn) if fn else ():
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "origin_ts"):
                continue
            return (isinstance(value, ast.Subscript)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "record"
                    and isinstance(value.slice, ast.Constant)
                    and value.slice.value == "started_at")
    return False


def _before_copied_before_attempts():
    """(c) the before picture is written before the attempt loop starts."""
    fn = _fn_ast("generate")
    if fn is None:
        return False
    copy_line = 0
    loop_line = 0
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_bytes"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "before_png"):
            copy_line = node.lineno
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "run_attempts"):
            loop_line = node.lineno
    return bool(copy_line and loop_line and copy_line < loop_line)


def part_before_after():
    print("\n[10] Before and after — which variant this spot showed, and the "
          "origin the new one carries")
    from app.core import props as prop_store

    original = prop_store.active_variant_tiers
    try:
        # Three variants, the middle one switched off: the payload lists the
        # store indices 0 and 2, and a placement's number indexes THAT list.
        prop_store.active_variant_tiers = lambda pid: [
            {"variant": 0, "tiers": ["full"]}, {"variant": 2, "tiers": ["full"]}]
        check("position 0 → store 0", sa.previous_variant("p", {"variant": 0}), 0)
        check("position 1 → store 2 (variant 1 is switched off)",
              sa.previous_variant("p", {"variant": 1}), 2)
        check("no variant field → the primary one",
              sa.previous_variant("p", {}), 0)
        check("position 3 wraps: 3 mod 2 = 1 → store 2",
              sa.previous_variant("p", {"variant": 3}), 2)
        check("position 5 wraps the same way",
              sa.previous_variant("p", {"variant": 5}), 2)
        check("junk in the field reads as the primary one",
              sa.previous_variant("p", {"variant": "left"}), 0)
        prop_store.active_variant_tiers = lambda pid: []
        check_true("a prop with no meshed variant has no before",
                   sa.previous_variant("p", {"variant": 0}) is None)
    finally:
        prop_store.active_variant_tiers = original

    loc = {"rooms": [
        {"id": "hall", "layout": {"props": [
            {"prop_id": "chair", "variant": 1, "offset_y": 0.25},
            {"prop_id": "table"}]}},
        {"id": "__ground__", "layout": {"props": []}}]}
    got = sa.authored_placement(loc, "hall", 0)
    check("the stored placement of hall#0", got.get("prop_id"), "chair")
    check("...with its own variant", got.get("variant"), 1)
    check("its offset_y is what the placement step starts from",
          sa._authored_offset_y({"target": {"room_id": "hall", "index": 0}}, loc),
          0.25, 1e-9)
    check("a placement without offset_y starts at 0",
          sa._authored_offset_y({"target": {"room_id": "hall", "index": 1}}, loc),
          0.0, 1e-9)
    check_true("an index the room does not have is empty",
               sa.authored_placement(loc, "hall", 7) == {})
    check_true("a room the location does not have is empty",
               sa.authored_placement(loc, "cellar", 0) == {})
    check_true("the yard is an ordinary room, empty of props here",
               sa.authored_placement(loc, "__ground__", 0) == {})

    check_true("the cutout is handed to the store WITH the origin",
               _origin_kwarg_passed())
    check_true("origin_ts is the run's own started_at, not a fresh clock read",
               _origin_ts_from_record())
    check_true("the before picture is copied BEFORE the attempt loop runs",
               _before_copied_before_attempts())


def main():
    part_expected()
    part_mask_grow()
    part_raster()
    part_difference()
    part_crop()
    part_yaw()
    part_contact()
    part_retries()
    part_backend()
    part_before_after()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
