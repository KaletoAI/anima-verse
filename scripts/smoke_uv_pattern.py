"""Smoke: the pure-numpy sewing-pattern UV of a garment template (``app/blender/scripts/uv_pattern.py``).

Usage:
    ./.venv/bin/python scripts/smoke_uv_pattern.py

No server, no world DB, no Blender: ``uv_pattern`` is numpy only and imported through ``sys.path`` the way
``scripts/smoke_bake_register.py`` imports ``bake_register``. Every expectation is derived by hand below (metres).

[1] Plane: a flat 0.30 x 0.20 m grid of 6 x 4 quads in the XZ plane (y = 0), wound so the normal is -Y
    ((b - a) x (c - a) of (0,0,0), (1,0,0), (1,0,1) = (0, -1, 0)). A plane is developable: ``lscm`` + ``arap`` give an
    isometry, so after ``orient(up=+Z, axis = the vertical line through (0.15, 1, 0))`` (outward = the horizontal
    radial from that line = -Y for every face) the bbox is 0.300 x 0.200 (+-1e-6) and the area ratio 1.000. Seen from
    -Y (the camera looks along +Y with +Z up, its right = +Y x +Z = +X) the character's left (+X) is at image right:
    u increases with +X.
[2] Cylinder halves: r = 0.15, h = 0.50, 40 segments (column k at angle k * 2 pi / 40, x = r cos, y = r sin), 10 face
    rings (11 vertex rings), axis Z, all faces part 1, ``seam_edges`` = the vertical edges of the columns at angle 0
    (k = 0) and pi (k = 20). Expected: two islands. A half is 20 flat facets of chord 2 r sin(pi / 40), so its
    developed width = 20 * 2 * 0.15 * sin(4.5 deg) = 6 sin 4.5 deg = 0.470755 (the chord sum, not pi r = 0.4712);
    height 0.500; each +-1e-3. ``area_ratio`` 1.000 +- 0.005, ``stretch_p95`` <= 1.01. Outward = the horizontal radial
    from the Z axis. The half at -Y is seen from -Y (right = +X): u increases with +X; the half at +Y is seen from
    +Y (right = -Y x +Z = -X): u increases with -X.
[3] Grain + outside: a sleeve-like cone frustum along -X, r = 0.08 at the shoulder end x = 0 to 0.05 at x = -0.45,
    24 segments, 9 face rings, cut along its bottom generatrix (z = -r, the underarm) by ``seam_edges`` — ONE island
    whose seam vertices are duplicated. ``axis_p = 0``, ``axis_d = (-1, 0, 0)``, ``up = +X`` (hand -> shoulder).
    The cone's apex lies at x = -0.45 - 0.05 / (0.03 / 0.45) = -1.2, so it develops into an annular sector whose
    OUTER arc is the shoulder ring; ``orient`` turns the mean grain to +v, so by symmetry the arc's middle (the top
    generatrix, z = +r) is the highest point: the shoulder ring's max v = the island's max v (+-1 % of the height) and
    the top generatrix lies at the island's u middle (+-2 % of the width). The same frustum with every face wound
    the other way gives the same UV (+-1e-5): the outside test reads geometry (the normal and the UV area both flip),
    not winding.
[4] Split from labels alone: the 6 x 4 grid of [1] (7 x 5 = 35 vertices), columns 0..2 part 1, 3..5 part 2, no
    seams -> 2 islands; the part border (the vertex column x = 3) is 5 vertices long -> 35 + 5 = 40 island vertices.
    Plus a seam along the vertex row z = 2 across part 1 (vertices (0,2), (1,2), (2,2), (3,2): 3 edges, 4 vertices)
    -> 3 islands; each of those 4 vertices gains one more copy ((3,2) already had two, one per part, and its part-1
    copy splits again) -> 35 + 5 + 4 = 44.
[5] (a) A ring of 8 quads (vertex column k at angle k * 45 deg, x = cos, two vertex rings), all part 1. With the
    face between columns 7 and 0 missing (an open front) the 7 faces are ONE component. With faces 2 and 5 missing:
    faces {6, 7, 0, 1} (vertex columns 6, 7, 0, 1, 2: mean x = (0 + .707 + 1 + .707 + 0) / 5 > 0) and {3, 4}
    (columns 3, 4, 5: mean x < 0) -> two islands named ``front`` (the +X one, {6, 7, 0, 1}) and ``front_2``, both
    still part 1.
    (b) ``strip_uv`` of a flat annulus (z = 0, inner r 0.080, outer r 0.095, 16 segments, cut at angle 0: 17 vertex
    columns): the mid line (r 0.0875) is 16 chords of 2 * 0.0875 * sin(pi / 16) -> u length = 0.546252 (+-1e-4);
    v = 0 on the outer edge, 0.095 - 0.080 = 0.015 on the inner edge (+-1e-6); u increases with the order of rows.
[6] Performance: a 60 x 40 = 2400-vertex island (a 120 deg cylinder sector, r 0.2, h 0.5) through ``lscm`` +
    ``arap(iters=40)`` — printed, soft bound 8 s (a WARN, not a failure; the number goes to the ledger).
[7] Packing (T-shirt boxes in cm, rectangles of 4 vertices in metres): front 50 x 47, back 50 x 45, sleeves 34 x 25
    each, band 44 x 4, margin 1.5. Rows by ``ROW_ORDER``: A = front, back: 1.5 + 50 + 1.5 + 50 + 1.5 = 104.5;
    B = sleeves: 1.5 + 34 + 1.5 + 34 + 1.5 = 72.5; C = band: 1.5 + 44 + 1.5 = 47. H = 1.5 + 47 + 1.5 + 25 + 1.5 + 4 +
    1.5 = 82. max = 104.5 -> px_per_cm = floor_0.01(2048 / 104.5 = 19.598) = 19.59. Row A is the widest, so its
    centring offset is 0: the front bbox left edge = 1.5 * 19.59 = 29.39 px (+-0.5), its top (row A starts at the top
    margin, islands top-aligned) = 29.39 px. Every vertex lies inside the 2048 atlas.
[8] Long sleeves (34 x 60): H = 1.5 + 47 + 1.5 + 60 + 1.5 + 4 + 1.5 = 117 > 104.5 -> 2048 / 117 = 17.504 -> 17.50
    px/cm. The bbox of every island in px divided by its size in cm is 17.50 +- 0.01 (one density).
[10] Seam samples: the two cylinder halves of [2], packed: 2 seams (the columns at angle 0 and pi), each 0.50 m long
    in 3D -> 50 / 1 + 1 = 51 samples per seam, 102 pairs. Both halves have the same height and sit top-aligned in
    row A, so the image-row coordinate of the two sides of a pair agrees within 1 px. The frustum of [3] has one
    seam inside ONE island (the underarm); its slant length is sqrt(0.45^2 + 0.03^2) = 0.450999 m -> floor(45.0999) +
    1 = 46 pairs, both sides ``sleeve_l``, the two sides mirror images about the top generatrix -> their rows agree
    within 1 px.
[11] Payload purity: two ``islands_payload`` calls on the same input give byte-identical
    ``json.dumps(sort_keys=True)`` output; the payload carries version 1, atlas_px 2048, the island names, and per
    island ``verts_px`` / ``tris`` / ``loops_px`` / ``bbox_px`` / ``area_cm2`` / ``distortion``. The plane of [1]
    (0.30 x 0.20 m) packs alone: area_cm2 = 30 * 20 = 600 (+-0.5), one boundary loop of 2 * (6 + 4) = 20 vertices.
[12] Cap height: v in cm of a hand island, shoulder v = 12, underarm ends v = 15 and 13 -> 12 - 14 = -2.0 (inverted);
    a shoulder id outside the loop raises ValueError.
[13] ``pattern_uv`` — the whole pipeline ``garment_template_build.run()`` calls (split, flatten or strip, orient, cap,
    pack, payload, per-corner Blender UV), on a hand-made top (plan Task 3):
    (a) a torso cylinder r 0.15, 16 columns at the build's angles (column c at 1.5 pi + c * 2 pi / 16: c = 0 is the
    front centre, -Y), 6 vertex rings z = 0.5 .. 0 (row 0 on top), parts by the construction rule (c < 4 or c >= 12
    front, else back), plus a flat band ring on top (outer edge = the torso's row 0, inner edge r 0.12 at z 0.5,
    part 5, cut at the back centre c = 8; strip rows c = 8 .. 24 mod 16). Islands front, back, band. The front is ONE
    island across c = 0: 8 facets of chord 2 * 0.15 * sin(pi / 16) -> width 0.468217 m, height 0.5 (+-1e-3). The band
    strip: 16 chords of the mid line r 0.135 -> 0.842790 m long, 0.03 m wide. Packing: row A = 1.5 + 46.8217 + 1.5 +
    46.8217 + 1.5 = 98.1434 cm, H = 1.5 + 50 + 1.5 + 3 + 1.5 = 57.5 -> px_per_cm = floor_0.01(2048 / 98.1434 =
    20.867) = 20.86; the front's bbox is 46.8217 * 20.86 = 976.70 px wide (+-2.1 px = the 1e-3 m tolerance), the
    band's 84.2790 * 20.86 = 1758.06 px wide (+-2.1) and 3 * 20.86 = 62.58 px high (+-0.1). Every corner UV is
    exactly (x / 2048, 1 - y / 2048) of its island vertex in the payload. The band's two copies of the back-centre
    vertex sit at its left and right ends; the front-centre vertex (c = 0) at its u middle (8 of 16 chords: 0.5
    +-1e-3). The front's u increases with +X (seen from -Y), the back's with -X (seen from +Y); image rows fall as z
    rises (grain up).
    (b) Robustness to a vertex ``dissolve_degenerate`` merged away: the band's inner vertex of column 4 merged into
    column 5's (face 3 now uses column 5's inner vertex, face 4 is the triangle row0[4], row0[5], inner[5]). Column 4
    of the strip rows is dropped; its surviving outer vertex is placed between columns 3 and 5 on the outer edge. Still
    ONE band island, every band corner UV finite and inside [0, 1], no band triangle with zero UV area; the mid line
    now runs 14 single chords plus ONE chord over two steps from column 3 to 5: 14 * 2 * 0.135 * sin(pi / 16) +
    2 * 0.135 * sin(pi / 8) = 0.737440 + 0.103324 = 0.840765 m (+-1e-3; the end columns stay).
    (c) ``caps``: the frustum of [3] as part 3 with caps = (its shoulder ring, the top generatrix vertex at x = 0, the
    underarm vertex at x = 0). It develops into an annular sector of outer radius Ro = sqrt(1.2^2 + 0.08^2) =
    1.202664 (apex at x = -1.2) and angle = the chord sum 24 * 2 * 0.08 * sin(pi / 24) = 0.501220 over Ro = 0.416759
    rad; the shoulder point is the arc's middle, the two underarm copies its ends -> cap = Ro (1 - cos(0.208380)) =
    2.60 cm (+-0.1), POSITIVE (a bell; the build's sleeves give their own sign).
[14] ``garment_template_drape.island_mask`` names its ``polys`` parameter (Task 2's latent NameError: the body read
    ``polys`` without a parameter of that name).
[15] ``shoulder_seam``: centre (0, 0.005). The left seam runs (0.20, 0.00) -> (0.15, -0.02) -> (0.10, -0.04) (shoulder
    end x = 0.20, neck end x = 0.10), the right one mirrored in x. The neck ring's left side: (0.100, -0.07),
    (0.100, -0.04), (0.100, -0.01), (0.095, 0.005) within 1 cm of the widest x 0.100, and (0.05, 0.04), (0, 0.04),
    (0, -0.14) beyond it; the right side mirrored. Side point y = (-0.07 + 0.005) / 2 = -0.0325 -> shoulder_dy =
    |0 - 0.005| = 0.50 cm, neck_dy = |-0.04 + 0.0325| = 0.75 cm, neck_fwd = 0.005 + 0.0325 = 3.75 cm, max_dy =
    |-0.04 - 0.005| = 4.50 cm, both sides. Without a ring the neck fields are None.
[16] Ring strip, cylinder (step 3a, ``ring_strip_uv``): r 0.10 m, h 0.04 m, 64 segments, one ring of quads (part 14,
    the waistband), cut at angle 0 (``rings`` = {14: (origin, +Z, +X)}) -> u length = the chord sum of the mid line
    64 * 2 * 0.10 * sin(pi / 64) = 12.8 * 0.0490677 = 0.628066 m (+-1e-4), v = 0.040 (+-1e-6), ``strip_stretch_p95``
    <= 1.001. The cut vertex's two copies sit at u = 0 and u = 0.628066; the vertex at angle pi / 2 (+Y) at a quarter
    (16 chords: 0.157017) — the angle grows from +X toward +Z x +X = +Y.
[17] Ring strip, cone (a waistband over the hip flare): r 0.11 at z 0 to 0.10 at z 0.04: mean r 0.105 -> u =
    64 * 0.21 * 0.0490677 = 0.659470 m (+-1e-4); its edge stretch is 0.105 / 0.10 = 1.05 at the top and
    0.11 / 0.105 = 1.0476 at the bottom -> ``strip_stretch_p95`` printed (recorded, not gated; 1.03..1.07 accepted).
    The same band flattened by LSCM + ARAP (part 1) is an annular sector instead (decision D6): slant s =
    sqrt(0.04^2 + 0.01^2) = 0.0412311, radii R1 = 0.10 s / 0.01 = 0.412311 (top) and R2 = 0.453542, developed angle
    phi = 64 * 2 asin(sin(pi / 64) * 0.10 / R1) = 1.523305 rad; with the grain up the sector is symmetric about the
    vertical, so its bbox height = R2 - R1 cos(phi / 2) = 0.453542 - 0.412311 * 0.723784 = 0.155120 m (+-0.002) —
    3.9 x the band's 0.04 (the plan's "> 4 x" was a guess: hand-derived it is 3.88 x).
[18] Box UV against the pattern (the glove bug): a flat 1.62 x 0.12 m rectangle in the XZ plane (60 x 6 quads) with
    the old box rule (u = 0.02 + 0.47 x / 1.62, v = 0.02 + 0.96 z / 0.12) has sigma_u = 0.47 / 1.62 = 0.290123 and
    sigma_v = 0.96 / 0.12 = 8.0 per metre -> texel anisotropy sigma_1 / sigma_2 = 27.574 (+-0.01) on every triangle;
    ``pattern_uv`` of the same rectangle -> 1.000 +- 0.001.
[19] Rows (``pack(rows=ROWS[kind])``): trousers boxes front_r 31.9 x 94.9, front_l 32.8 x 94.5, back_l 35.1 x 93.9,
    back_r 35.2 x 94.3, waistband 65.0 x 4.0, margin 1.5: row A = 1.5 + 135.0 + 4 * 1.5 = 142.5, H = 1.5 + 94.9 + 1.5 +
    4.0 + 1.5 = 103.4 -> px_per_cm = floor_0.01(2048 / 142.5 = 14.372) = 14.37; left to right front_r, front_l,
    back_l, back_r, the waistband under them. Gloves boxes back_r 17.7, back_l 15.8, palm_l 17.7, palm_r 18.9 x 48.5:
    1.5 + 70.1 + 4 * 1.5 = 77.6 (H = 1.5 + 48.5 + 1.5 = 51.5) -> floor_0.01(26.392) = 26.39. ``rows=None`` keeps
    ``ROW_ORDER`` (the [7] boxes give 19.59 again).
[20] Adaptive ARAP: the 2400-vertex sector of [6] with ``tol=1e-3`` stops in <= 15 iterations and its
    ``stretch_p95`` is within 0.005 of the 40-iteration result (the iteration count is printed for the ledger).
[21] Tops unchanged: ``pattern_uv`` of the hand-made top of [13] gives a byte-identical payload
    (``json.dumps(sort_keys=True)``) with this module and with ``uv_pattern.py`` at the base commit c926b67f0
    (read with ``git show``; skipped with a note when git is not available).
[22] Ring cut off theta 0: the cylinder of [16] with ``cut_dir`` turned 30 deg (cos 30, sin 30, 0) while its cut stays
    at +X (vertex 0): theta = 0 follows the cut copies, so u length 0.628066, the copies at u 0 and 0.628066 and the
    +Y vertex at 0.157017 exactly as in [16] (theta from ``cut_dir`` alone put the vertices between +X and 30 deg at
    the far end and stretched their faces across the strip).
[23] Banded direct solve (``_Banded``): the 1-D Poisson system 2 x_i - x_(i-1) - x_(i+1) = 1, i = 1..50, x_0 = x_51 = 0,
    given in a shuffled order (seed 7) -> x_i = i (51 - i) / 2: x_1 = 25, x_25 = 325, x_50 = 25 (+-1e-9); an extra
    unknown no entry touches keeps its x0 (3.5).
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import uv_pattern as up  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if not (isinstance(detail, str) and detail == "") else ""))
    if not ok:
        FAILS.append(label)


def tris_of(island):
    return np.array([t for poly in island.corner_vid for t in up.fan(poly)], dtype=np.int64)


def flatten(island, xyz, upv, axis_p, axis_d=None):
    lx = xyz[island.vmap]
    tris = tris_of(island)
    uv = up.lscm(lx, tris)
    uv = up.arap(lx, tris, uv, iters=40)
    uv = up.orient(uv, lx, tris, np.asarray(upv, float), np.asarray(axis_p, float),
                   None if axis_d is None else np.asarray(axis_d, float))
    return uv, lx, tris


def grid(nx=6, nz=4, w=0.30, h=0.20):
    xyz = np.array([(w * i / nx, 0.0, h * j / nz) for j in range(nz + 1) for i in range(nx + 1)])
    vid = lambda i, j: j * (nx + 1) + i  # noqa: E731
    faces = [(vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)) for j in range(nz) for i in range(nx)]
    return xyz, faces, vid


# [1] plane
xyz, faces, vid = grid()
isl = up.split_islands(len(xyz), faces, np.ones(len(faces), int), set(), xyz=xyz)
check("[1] one island", len(isl) == 1, len(isl))
uv, lx, tris = flatten(isl[0], xyz, (0, 0, 1), (0.15, 1.0, 0.0))
ext = uv.max(0) - uv.min(0)
check("[1] bbox 0.300 x 0.200", abs(ext[0] - 0.3) < 1e-6 and abs(ext[1] - 0.2) < 1e-6, ext)
d = up.distortion(uv, lx, tris)
check("[1] area ratio 1.000", abs(d["area_ratio"] - 1.0) < 1e-6, d)
check("[1] u increases with +X", np.corrcoef(uv[:, 0], lx[:, 0])[0, 1] > 0.999, np.corrcoef(uv[:, 0], lx[:, 0])[0, 1])
check("[1] v increases with +Z", np.corrcoef(uv[:, 1], lx[:, 2])[0, 1] > 0.999)

# [2] cylinder halves
R, H, S, NR = 0.15, 0.50, 40, 10
xyz = np.array([(R * math.cos(2 * math.pi * k / S), R * math.sin(2 * math.pi * k / S), H * j / NR)
                for j in range(NR + 1) for k in range(S)])
cv = lambda k, j: j * S + (k % S)  # noqa: E731
faces = [(cv(k, j), cv(k + 1, j), cv(k + 1, j + 1), cv(k, j + 1)) for j in range(NR) for k in range(S)]
seams = {tuple(sorted((cv(k, j), cv(k, j + 1)))) for k in (0, S // 2) for j in range(NR)}
isl = up.split_islands(len(xyz), faces, np.ones(len(faces), int), seams, xyz=xyz)
check("[2] two islands", len(isl) == 2, len(isl))
want_w = 6 * math.sin(math.radians(4.5))
cyl_xyz, cyl_isl, cyl_uv = xyz, isl, {}
for i in isl:
    uv, lx, tris = flatten(i, xyz, (0, 0, 1), (0, 0, 0))
    cyl_uv[i.name] = uv
    ext = uv.max(0) - uv.min(0)
    side = "-Y" if lx[:, 1].mean() < 0 else "+Y"
    check(f"[2] half {side}: width {want_w:.6f} x height 0.500",
          abs(ext[0] - want_w) < 1e-3 and abs(ext[1] - H) < 1e-3, ext)
    d = up.distortion(uv, lx, tris)
    check(f"[2] half {side}: area ratio 1 +- 0.005, stretch_p95 <= 1.01",
          abs(d["area_ratio"] - 1) < 0.005 and d["stretch_p95"] <= 1.01, d)
    c = np.corrcoef(uv[:, 0], lx[:, 0])[0, 1]
    check(f"[2] half {side}: u increases with {'+X' if side == '-Y' else '-X'}", c > 0.9 if side == "-Y" else c < -0.9, c)

# [3] frustum
S, NR = 24, 9


def frustum(reverse=False):
    pts = []
    for j in range(NR + 1):
        x = -0.45 * j / NR
        r = 0.08 + (0.05 - 0.08) * j / NR
        for k in range(S):
            a = 2 * math.pi * k / S
            pts.append((x, r * math.sin(a), -r * math.cos(a)))  # k = 0: z = -r (the underarm)
    fv = lambda k, j: j * S + (k % S)  # noqa: E731
    fs = [(fv(k, j), fv(k + 1, j), fv(k + 1, j + 1), fv(k, j + 1)) for j in range(NR) for k in range(S)]
    if reverse:
        fs = [tuple(reversed(f)) for f in fs]
    sm = {tuple(sorted((fv(0, j), fv(0, j + 1)))) for j in range(NR)}
    return np.array(pts), fs, sm, fv


fx, ff, fsm, fv = frustum()
isl = up.split_islands(len(fx), ff, np.full(len(ff), 3), fsm, xyz=fx)
check("[3] one sleeve island", len(isl) == 1 and isl[0].name == "sleeve_l", [i.name for i in isl])
check("[3] the underarm seam is duplicated", len(isl[0].vmap) == len(fx) + NR + 1, len(isl[0].vmap))
uv3, lx3, _ = flatten(isl[0], fx, (1, 0, 0), (0, 0, 0), (-1, 0, 0))
hgt = uv3[:, 1].max() - uv3[:, 1].min()
wid = uv3[:, 0].max() - uv3[:, 0].min()
shoulder = np.abs(lx3[:, 0]) < 1e-9
check("[3] the shoulder end is at max v", abs(uv3[shoulder, 1].max() - uv3[:, 1].max()) <= 0.01 * hgt,
      (uv3[shoulder, 1].max(), uv3[:, 1].max(), hgt))
top = np.isin(isl[0].vmap, [fv(S // 2, j) for j in range(NR + 1)])
mid = 0.5 * (uv3[:, 0].max() + uv3[:, 0].min())
check("[3] the top generatrix lies at the u middle", np.abs(uv3[top, 0] - mid).max() <= 0.02 * wid,
      (np.abs(uv3[top, 0] - mid).max(), wid))
rx, rf, rsm, _ = frustum(reverse=True)
risl = up.split_islands(len(rx), rf, np.full(len(rf), 3), rsm, xyz=rx)
ruv, _, _ = flatten(risl[0], rx, (1, 0, 0), (0, 0, 0), (-1, 0, 0))
same = np.array_equal(risl[0].vmap, isl[0].vmap) and np.abs(ruv - uv3).max() < 1e-5
check("[3] reversed winding gives the same UV", same,
      np.abs(ruv - uv3).max() if np.array_equal(risl[0].vmap, isl[0].vmap) else "vmap differs")

# [4] split from labels
xyz, faces, vid = grid()
part = np.array([1 if i < 3 else 2 for j in range(4) for i in range(6)])
isl = up.split_islands(len(xyz), faces, part, set(), xyz=xyz)
check("[4] labels alone: 2 islands", len(isl) == 2, [i.name for i in isl])
check("[4] 35 + 5 = 40 island vertices", sum(len(i.vmap) for i in isl) == 40, sum(len(i.vmap) for i in isl))
seam = {tuple(sorted((vid(i, 2), vid(i + 1, 2)))) for i in range(3)}
isl = up.split_islands(len(xyz), faces, part, seam, xyz=xyz)
check("[4] plus a seam through part 1: 3 islands", len(isl) == 3, [i.name for i in isl])
check("[4] 35 + 5 + 4 = 44 island vertices", sum(len(i.vmap) for i in isl) == 44, sum(len(i.vmap) for i in isl))
check("[4] names", sorted(i.name for i in isl) == ["back", "front", "front_2"], [i.name for i in isl])

# [5a] ring components
rv = np.array([(math.cos(math.pi * k / 4), math.sin(math.pi * k / 4), z) for z in (0.0, 0.1) for k in range(8)])
rid = lambda k, j: j * 8 + (k % 8)  # noqa: E731
ring = {k: (rid(k, 0), rid(k + 1, 0), rid(k + 1, 1), rid(k, 1)) for k in range(8)}
open_front = [ring[k] for k in range(7)]
isl = up.split_islands(len(rv), open_front, np.ones(7, int), set(), xyz=rv)
check("[5a] an open front is ONE component", len(isl) == 1 and isl[0].name == "front", [i.name for i in isl])
keep = [k for k in range(8) if k not in (2, 5)]
isl = up.split_islands(len(rv), [ring[k] for k in keep], np.ones(len(keep), int), set(), xyz=rv)
by = {i.name: sorted(keep[f] for f in i.faces) for i in isl}
check("[5a] two components: front = {6,7,0,1}, front_2 = {3,4}", by == {"front": [0, 1, 6, 7], "front_2": [3, 4]}, by)
check("[5a] no face changes part", all(i.part == 1 for i in isl))

# [5b] band strip
n = 16
ann = []
for r in (0.095, 0.080):
    for k in range(n + 1):
        a = 2 * math.pi * k / n
        ann.append((r * math.cos(a), r * math.sin(a), 0.0))
ann = np.array(ann)
outer = list(range(n + 1))
inner = list(range(n + 1, 2 * (n + 1)))
st = up.strip_uv([outer, inner], ann)
us = [st[v][0] for v in outer]
want_u = 16 * 2 * 0.0875 * math.sin(math.pi / 16)
check(f"[5b] u length {want_u:.6f}", abs(us[-1] - us[0] - want_u) < 1e-4, us[-1] - us[0])
check("[5b] v: outer 0, inner 0.015", all(abs(st[v][1]) < 1e-9 for v in outer)
      and all(abs(st[v][1] - 0.015) < 1e-6 for v in inner))
check("[5b] u increases with the order of rows", all(b > a for a, b in zip(us, us[1:])))

# [6] performance
NX, NZ = 60, 40
pv = np.array([(0.2 * math.cos(math.radians(-150 + 120 * i / (NX - 1))), 0.2 * math.sin(math.radians(-150 + 120 * i / (NX - 1))),
                0.5 * j / (NZ - 1)) for j in range(NZ) for i in range(NX)])
pf = [(j * NX + i, j * NX + i + 1, (j + 1) * NX + i + 1, (j + 1) * NX + i) for j in range(NZ - 1) for i in range(NX - 1)]
isl = up.split_islands(len(pv), pf, np.ones(len(pf), int), set(), xyz=pv)
t0 = time.perf_counter()
uv6, lx6, tr6 = flatten(isl[0], pv, (0, 0, 1), (0, 0, 0))
dt = time.perf_counter() - t0
d6 = up.distortion(uv6, lx6, tr6)
print(f"     [6] 2400-vertex island lscm + arap(40) + orient: {dt:.2f} s  {d6}")
if dt >= 8.0:
    print("WARN [6] slower than the 8 s soft bound")
check("[6] the sector stays isometric", abs(d6["area_ratio"] - 1) < 0.005 and d6["stretch_p95"] <= 1.01, d6)

# [7] packing, T-shirt boxes
def rect(w_cm, h_cm):
    return np.array([(0, 0), (w_cm / 100, 0), (w_cm / 100, h_cm / 100), (0, h_cm / 100)], float)


boxes = {"front": (50, 47), "back": (50, 45), "sleeve_l": (34, 25), "sleeve_r": (34, 25), "band": (44, 4)}
packed, s7 = up.pack({k: rect(*v) for k, v in boxes.items()}, 2048, 1.5)
check("[7] px_per_cm 19.59", abs(s7 - 19.59) < 1e-9, s7)
fx0, fy0 = packed["front"].min(0)
check("[7] front bbox left/top 29.39 px", abs(fx0 - 29.39) <= 0.5 and abs(fy0 - 29.39) <= 0.5, (fx0, fy0))
allp = np.concatenate(list(packed.values()))
check("[7] every vertex inside the atlas", allp.min() >= 0 and allp.max() <= 2048, (allp.min(), allp.max()))
check("[7] back right of front, sleeves below, band last",
      packed["back"][:, 0].min() > packed["front"][:, 0].max()
      and packed["sleeve_l"][:, 1].min() > packed["front"][:, 1].max()
      and packed["band"][:, 1].min() > packed["sleeve_l"][:, 1].max())

# [8] long sleeves: one density
boxes8 = dict(boxes, sleeve_l=(34, 60), sleeve_r=(34, 60))
packed8, s8 = up.pack({k: rect(*v) for k, v in boxes8.items()}, 2048, 1.5)
check("[8] px_per_cm 17.50", abs(s8 - 17.50) < 1e-9, s8)
ratios = {k: tuple((packed8[k].max(0) - packed8[k].min(0)) / np.array(v, float)) for k, v in boxes8.items()}
check("[8] every island at 17.50 +- 0.01 px/cm",
      all(abs(r - 17.50) <= 0.01 for rr in ratios.values() for r in rr), ratios)

# [10] seam samples
cpx, _ = up.pack(cyl_uv, 2048, 1.5)
pairs = up.seam_samples(cyl_isl, cpx, cyl_xyz, step_cm=1.0)
check("[10] cylinder: 102 pairs", len(pairs) == 102, len(pairs))
check("[10] cylinder: 2 seams of 51", sorted({p["seam"] for p in pairs}) == [0, 1]
      and all(sum(p["seam"] == s for p in pairs) == 51 for s in (0, 1)))
check("[10] cylinder: the halves pair up", all({p["a"], p["b"]} == {"front", "front_2"} for p in pairs))
dv = max(abs(p["uv_a_px"][1] - p["uv_b_px"][1]) for p in pairs) if pairs else None
check("[10] cylinder: rows agree within 1 px", dv is not None and dv <= 1.0, dv)
fisl = up.split_islands(len(fx), ff, np.full(len(ff), 3), fsm, xyz=fx)
fpx, _ = up.pack({"sleeve_l": uv3}, 2048, 1.5)
fpairs = up.seam_samples(fisl, fpx, fx, step_cm=1.0)
check("[10] frustum: 46 pairs inside sleeve_l", len(fpairs) == 46 and all(p["a"] == p["b"] == "sleeve_l" for p in fpairs),
      len(fpairs))
fdv = max(abs(p["uv_a_px"][1] - p["uv_b_px"][1]) for p in fpairs) if fpairs else None
check("[10] frustum: rows agree within 1 px", fdv is not None and fdv <= 1.0, fdv)
fdu = min(abs(p["uv_a_px"][0] - p["uv_b_px"][0]) for p in fpairs) if fpairs else None
check("[10] frustum: the two sides are apart in u", fdu is not None and fdu > 10, fdu)

# [11] payload purity
xyz, faces, vid = grid()
isl = up.split_islands(len(xyz), faces, np.ones(len(faces), int), set(), xyz=xyz)
uv11, _, _ = flatten(isl[0], xyz, (0, 0, 1), (0.15, 1.0, 0.0))
pl1 = up.islands_payload(isl, {"front": uv11}, xyz)
pl2 = up.islands_payload(isl, {"front": uv11}, xyz)
check("[11] byte-identical payloads", json.dumps(pl1, sort_keys=True) == json.dumps(pl2, sort_keys=True))
check("[11] header", pl1.get("version") == 1 and pl1.get("atlas_px") == 2048 and pl1.get("margin_cm") == 1.5
      and [i["name"] for i in pl1.get("islands", [])] == ["front"], {k: pl1.get(k) for k in ("version", "atlas_px")})
i11 = pl1["islands"][0] if pl1.get("islands") else {}
check("[11] island keys", {"name", "part", "bbox_px", "loops_px", "verts_px", "tris", "area_cm2", "distortion"} <= set(i11),
      sorted(i11))
check("[11] area_cm2 600", abs(i11.get("area_cm2", 0) - 600) <= 0.5, i11.get("area_cm2"))
check("[11] one boundary loop of 20 vertices", [len(lp) for lp in i11.get("loops_px", [])] == [20],
      [len(lp) for lp in i11.get("loops_px", [])])
check("[11] tris index verts_px", len(i11.get("tris", [])) == 48
      and max(max(t) for t in i11["tris"]) < len(i11["verts_px"]))

# [12] cap height
cuv = np.array([(0, 12.0), (-5, 15.0), (5, 13.0), (0, 0.0)])
check("[12] cap height -2.0", abs(up.cap_height(cuv, [0, 1, 2], 0, [1, 2]) + 2.0) < 1e-9)
try:
    up.cap_height(cuv, [1, 2], 0, [1, 2])
    check("[12] shoulder outside the loop raises", False)
except ValueError:
    check("[12] shoulder outside the loop raises", True)

# [13] pattern_uv on a hand-made top
N13, R13 = 16, 0.15
v13, tid13 = [], {}
for r in range(6):
    for c in range(N13):
        a = 1.5 * math.pi + c * 2 * math.pi / N13
        tid13[r, c] = len(v13)
        v13.append((R13 * math.cos(a), R13 * math.sin(a), 0.5 - 0.1 * r))
iid13 = {}
for c in range(N13):
    a = 1.5 * math.pi + c * 2 * math.pi / N13
    iid13[c] = len(v13)
    v13.append((0.12 * math.cos(a), 0.12 * math.sin(a), 0.5))
v13 = np.array(v13)
f13, p13 = [], []
for r in range(5):
    for c in range(N13):
        f13.append((tid13[r, c], tid13[r, (c + 1) % N13], tid13[r + 1, (c + 1) % N13], tid13[r + 1, c]))
        p13.append(1 if c < N13 // 4 or c >= 3 * N13 // 4 else 2)
band_faces = {}
for c in range(N13):
    band_faces[c] = len(f13)
    f13.append((tid13[0, c], tid13[0, (c + 1) % N13], iid13[(c + 1) % N13], iid13[c]))
    p13.append(5)
seam13 = {(tid13[0, 8], iid13[8])}
rows13 = [[tid13[0, c % N13] for c in range(8, 8 + N13 + 1)], [iid13[c % N13] for c in range(8, 8 + N13 + 1)]]
axes13 = {1: ((0, 0, 1), (0, 0, 0), None), 2: ((0, 0, 1), (0, 0, 0), None)}
if not hasattr(up, "pattern_uv"):
    check("[13] uv_pattern.pattern_uv exists", False)
else:
    res = up.pattern_uv(f13, p13, seam13, v13, axes=axes13, strips={5: rows13})
    pl = res["payload"]
    by13 = {i["name"]: i for i in pl["islands"]}
    check("[13a] islands front, back, band", [i["name"] for i in pl["islands"]] == ["front", "back", "band"],
          [i["name"] for i in pl["islands"]])
    check("[13a] px_per_cm 20.86", abs(pl["px_per_cm"] - 20.86) < 1e-9, pl["px_per_cm"])
    bw = lambda n: by13[n]["bbox_px"][2] - by13[n]["bbox_px"][0]  # noqa: E731
    bh = lambda n: by13[n]["bbox_px"][3] - by13[n]["bbox_px"][1]  # noqa: E731
    check("[13a] front 976.70 x 1043 px", abs(bw("front") - 976.70) <= 2.1 and abs(bh("front") - 50 * 20.86) <= 2.1,
          (bw("front"), bh("front")))
    check("[13a] band 1758.06 x 62.58 px", abs(bw("band") - 1758.06) <= 2.1 and abs(bh("band") - 62.58) <= 0.1,
          (bw("band"), bh("band")))
    # corner UVs = payload pixels / size, Blender frame
    isl13 = up.split_islands(len(v13), f13, p13, seam13, xyz=v13)
    worst = 0.0
    for isl in isl13:
        vp = np.array(by13[isl.name]["verts_px"])
        for fi, corner in zip(isl.faces, isl.corner_vid):
            want = [(vp[l][0] / 2048, 1 - vp[l][1] / 2048) for l in corner]
            worst = max(worst, float(np.abs(np.array(res["corner_uv"][fi]) - np.array(want)).max()))
    check("[13a] corner UV = (x / 2048, 1 - y / 2048) of the payload", worst < 1e-12, worst)
    bisl = next(i for i in isl13 if i.name == "band")
    bvp = np.array(by13["band"]["verts_px"])
    x0, x1 = by13["band"]["bbox_px"][0], by13["band"]["bbox_px"][2]
    starts = sorted(float(bvp[l][0]) for l in range(len(bisl.vmap)) if bisl.vmap[l] == tid13[0, 8])
    check("[13a] the back-centre vertex: two copies at the band's ends", len(starts) == 2
          and abs(starts[0] - x0) < 1e-6 and abs(starts[1] - x1) < 1e-6, (starts, x0, x1))
    fc = [float(bvp[l][0]) for l in range(len(bisl.vmap)) if bisl.vmap[l] == tid13[0, 0]]
    check("[13a] the front centre at the band's u middle", len(fc) == 1 and abs((fc[0] - x0) / (x1 - x0) - 0.5) < 1e-3,
          fc)
    for name, sign in (("front", 1), ("back", -1)):
        isl = next(i for i in isl13 if i.name == name)
        vp = np.array(by13[name]["verts_px"])
        cx = np.corrcoef(vp[:, 0], v13[isl.vmap, 0])[0, 1]
        cz = np.corrcoef(vp[:, 1], v13[isl.vmap, 2])[0, 1]
        check(f"[13a] {name}: u with {'+X' if sign > 0 else '-X'}, image rows fall as z rises",
              cx * sign > 0.9 and cz < -0.99, (cx, cz))

    # (b) a vertex merged away
    fb = list(f13)
    fb[band_faces[3]] = (tid13[0, 3], tid13[0, 4], iid13[5], iid13[3])
    fb[band_faces[4]] = (tid13[0, 4], tid13[0, 5], iid13[5])
    rb = up.pattern_uv(fb, p13, seam13, v13, axes=axes13, strips={5: rows13})
    plb = rb["payload"]
    bb = [i for i in plb["islands"] if i["part"] == 5]
    check("[13b] still ONE band island", len(bb) == 1, [i["name"] for i in bb])
    band_uv = np.array([uv for fi, uv in enumerate(rb["corner_uv"]) if p13[fi] == 5 for uv in uv], float)
    check("[13b] every band corner UV finite, inside [0, 1]", np.all(np.isfinite(band_uv))
          and band_uv.min() >= 0 and band_uv.max() <= 1, (band_uv.min(), band_uv.max()))
    if bb:
        lb = (bb[0]["bbox_px"][2] - bb[0]["bbox_px"][0]) / plb["px_per_cm"] / 100
        check("[13b] the band 0.840765 m long (one chord over columns 3..5)", abs(lb - 0.840765) < 1e-3, lb)
        bv = np.array(bb[0]["verts_px"])
        bt = np.array(bb[0]["tris"])
        q = bv[bt]
        a2 = np.abs((q[:, 1, 0] - q[:, 0, 0]) * (q[:, 2, 1] - q[:, 0, 1]) - (q[:, 1, 1] - q[:, 0, 1]) * (q[:, 2, 0] - q[:, 0, 0]))
        check("[13b] no band triangle with zero UV area", a2.min() > 1e-3, a2.min())

    # (c) caps
    fx13, ff13, fsm13, fv13 = frustum()
    rc = up.pattern_uv(ff13, np.full(len(ff13), 3), fsm13, fx13, axes={3: ((1, 0, 0), (0, 0, 0), (-1, 0, 0))},
                       caps={3: ([fv13(k, 0) for k in range(S)], fv13(S // 2, 0), fv13(0, 0))})
    cap = rc["cap_height_cm"].get("sleeve_l")
    check("[13c] cap height +2.60 cm (a bell)", cap is not None and abs(cap - 2.60) <= 0.1, cap)
    pc = {i["name"]: i for i in rc["payload"]["islands"]}
    check("[13c] the payload carries it", abs(pc["sleeve_l"].get("cap_height_cm", 0) - (cap or 0)) < 1e-3)

# [14] island_mask(obj, size, polys=None)
import ast  # noqa: E402
tree = ast.parse((ROOT / "app" / "blender" / "scripts" / "garment_template_drape.py").read_text())
im = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "island_mask"), None)
check("[14] island_mask names its polys parameter", im is not None and "polys" in [a.arg for a in im.args.args],
      [a.arg for a in im.args.args] if im else None)

# [15] shoulder_seam
sm = getattr(up, "shoulder_seam", None)
if sm is None:
    check("[15] uv_pattern.shoulder_seam exists", False)
else:
    half = [(0.20, 0.00), (0.15, -0.02), (0.10, -0.04)]
    ring_l = [(0.100, -0.07), (0.100, -0.04), (0.100, -0.01), (0.095, 0.005), (0.05, 0.04)]
    pts = [(x, y, 1.5) for x, y in half] + [(-x, y, 1.5) for x, y in half]
    ring0 = len(pts)
    pts += [(x, y, 1.55) for x, y in ring_l] + [(-x, y, 1.55) for x, y in ring_l] + [(0, 0.04, 1.55), (0, -0.14, 1.5)]
    ss = sm(np.array(pts), list(range(6)), (0.0, 0.005), list(range(ring0, len(pts))) + [-1])
    want = {"shoulder_dy_cm": 0.50, "neck_dy_cm": 0.75, "neck_fwd_cm": 3.75, "max_dy_cm": 4.50}
    for side in ("l", "r"):
        got = ss.get(side, {})
        check(f"[15] {side}: shoulder 0.50, neck 0.75, forward 3.75, max 4.50 cm",
              all(got.get(k) is not None and abs(got[k] - v) < 1e-6 for k, v in want.items()), got)
    nr = sm(np.array(pts), list(range(6)), (0.0, 0.005), None)
    check("[15] no ring: neck fields None", all(nr[s_]["neck_dy_cm"] is None and nr[s_]["neck_fwd_cm"] is None
                                                and abs(nr[s_]["max_dy_cm"] - 4.5) < 1e-6 for s_ in ("l", "r")), nr)

# [16] ring strip, cylinder
def ring_mesh(r_bot, r_top, h, n=64, part=14):
    pts = [(r_bot * math.cos(2 * math.pi * k / n), r_bot * math.sin(2 * math.pi * k / n), 0.0) for k in range(n)]
    pts += [(r_top * math.cos(2 * math.pi * k / n), r_top * math.sin(2 * math.pi * k / n), h) for k in range(n)]
    fs = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
    return np.array(pts), fs, np.full(n, part), {(0, n)}


rx16, rf16, rp16, rs16 = ring_mesh(0.10, 0.10, 0.04)
r16 = up.pattern_uv(rf16, rp16, rs16, rx16, rings={14: ((0, 0, 0), (0, 0, 1), (1, 0, 0))})
i16 = r16["payload"]["islands"]
s16 = r16["payload"]["px_per_cm"]
isl16 = up.split_islands(len(rx16), rf16, rp16, rs16, xyz=rx16)
uv16 = up.ring_strip_uv(isl16[0], rx16, (0, 0, 0), (0, 0, 1), (1, 0, 0))
want16 = 64 * 2 * 0.10 * math.sin(math.pi / 64)
check("[16] one island 'waistband'", [i["name"] for i in i16] == ["waistband"], [i["name"] for i in i16])
check(f"[16] u length {want16:.6f}", abs(np.ptp(uv16[:, 0]) - want16) < 1e-4, np.ptp(uv16[:, 0]))
check("[16] v 0.040", abs(np.ptp(uv16[:, 1]) - 0.04) < 1e-6, np.ptp(uv16[:, 1]))
check("[16] strip_stretch_p95 <= 1.001", r16["strip_stretch_p95"]["waistband"] <= 1.001, r16["strip_stretch_p95"])
cut16 = sorted(uv16[isl16[0].vmap == 0, 0])
check("[16] the cut vertex's copies at u 0 and the full length",
      len(cut16) == 2 and abs(cut16[0]) < 1e-9 and abs(cut16[1] - want16) < 1e-4, cut16)
q16 = uv16[isl16[0].vmap == 16, 0]
check("[16] the +Y vertex at a quarter (0.157017)", len(q16) == 1 and abs(q16[0] - want16 / 4) < 1e-4, q16)

# [17] ring strip, cone; the same band by ARAP
rx17, rf17, rp17, rs17 = ring_mesh(0.11, 0.10, 0.04)
r17 = up.pattern_uv(rf17, rp17, rs17, rx17, rings={14: ((0, 0, 0), (0, 0, 1), (1, 0, 0))})
isl17 = up.split_islands(len(rx17), rf17, rp17, rs17, xyz=rx17)
uv17 = up.ring_strip_uv(isl17[0], rx17, (0, 0, 0), (0, 0, 1), (1, 0, 0))
want17 = 64 * 0.21 * math.sin(math.pi / 64)
check(f"[17] cone u length {want17:.6f}", abs(np.ptp(uv17[:, 0]) - want17) < 1e-4, np.ptp(uv17[:, 0]))
st17 = r17["strip_stretch_p95"]["waistband"]
print(f"     [17] cone strip_stretch_p95 {st17:.4f} (recorded)")
check("[17] cone strip stretch within 1.03..1.07", 1.03 <= st17 <= 1.07, st17)
a17 = up.pattern_uv(rf17, np.ones(64, int), rs17, rx17, axes={1: ((0, 0, 1), (0, 0, 0), None)})
bb17 = a17["payload"]["islands"][0]["bbox_px"]
h17 = (bb17[3] - bb17[1]) / a17["payload"]["px_per_cm"] / 100.0
check("[17] the same band by ARAP: an arc 0.155120 m high", abs(h17 - 0.155120) < 0.002, h17)


# [18] box UV against the pattern
def aniso(uv, xyz, tris):
    loc, a2 = up._local_frames(np.asarray(xyz, float), np.asarray(tris))
    q = np.asarray(uv, float)[np.asarray(tris)]
    f = np.stack([q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]], axis=2)
    x = np.stack([loc[:, 1] - loc[:, 0], loc[:, 2] - loc[:, 0]], axis=2)
    sv = np.linalg.svd(f @ np.linalg.inv(x), compute_uv=False)
    return sv[:, 0] / sv[:, 1]


gx18 = np.array([(1.62 * i / 60, 0.0, 0.12 * j / 6) for j in range(7) for i in range(61)])
gf18 = [(j * 61 + i, j * 61 + i + 1, (j + 1) * 61 + i + 1, (j + 1) * 61 + i) for j in range(6) for i in range(60)]
gt18 = np.array([t for f_ in gf18 for t in up.fan(f_)])
box18 = np.stack([0.02 + 0.47 * gx18[:, 0] / 1.62, 0.02 + 0.96 * gx18[:, 2] / 0.12], axis=1)
an18 = aniso(box18, gx18, gt18)
check("[18] box UV anisotropy 27.574", abs(an18.min() - 27.574) < 0.01 and abs(an18.max() - 27.574) < 0.01,
      (an18.min(), an18.max()))
p18 = up.pattern_uv(gf18, np.full(len(gf18), 27), set(), gx18, axes={27: ((1, 0, 0), (0.81, 1.0, 0.06), None)})
cuv18 = np.zeros((len(gx18), 2))
for f_, cu in zip(gf18, p18["corner_uv"]):
    for v_, c_ in zip(f_, cu):
        cuv18[v_] = c_
an18p = aniso(cuv18, gx18, gt18)
check("[18] pattern UV anisotropy 1.000", abs(an18p.min() - 1) < 1e-3 and abs(an18p.max() - 1) < 1e-3,
      (an18p.min(), an18p.max()))

# [19] per-kind rows
tb = {"front_r": (31.9, 94.9), "front_l": (32.8, 94.5), "back_l": (35.1, 93.9), "back_r": (35.2, 94.3),
      "waistband": (65.0, 4.0)}
pk19, s19 = up.pack({k: rect(*v) for k, v in tb.items()}, 2048, 1.5, rows=up.ROWS["trousers"])
check("[19] trousers px_per_cm 14.37", abs(s19 - 14.37) < 1e-9, s19)
xs19 = [pk19[n][:, 0].min() for n in ("front_r", "front_l", "back_l", "back_r")]
check("[19] front_r, front_l, back_l, back_r left to right, waistband under them",
      xs19 == sorted(xs19) and pk19["waistband"][:, 1].min() > max(pk19[n][:, 1].max() for n in tb if n != "waistband"))
gb = {"glove_back_r": (17.7, 48.5), "glove_back_l": (15.8, 48.5), "palm_l": (17.7, 48.5), "palm_r": (18.9, 48.5)}
_pk, s19g = up.pack({k: rect(*v) for k, v in gb.items()}, 2048, 1.5, rows=up.ROWS["gloves"])
check("[19] gloves px_per_cm 26.39", abs(s19g - 26.39) < 1e-9, s19g)
_pk, s19t = up.pack({k: rect(*v) for k, v in boxes.items()}, 2048, 1.5, rows=None)
check("[19] rows=None keeps ROW_ORDER (19.59)", abs(s19t - 19.59) < 1e-9, s19t)

# [20] adaptive ARAP
st20 = {}
isl20 = up.split_islands(len(pv), pf, np.ones(len(pf), int), set(), xyz=pv)[0]
lx20 = pv[isl20.vmap]
tr20 = tris_of(isl20)
t0 = time.perf_counter()
uv20 = up.arap(lx20, tr20, up.lscm(lx20, tr20), iters=40, tol=1e-3, stats=st20)
dt20 = time.perf_counter() - t0
uv20f = up.arap(lx20, tr20, up.lscm(lx20, tr20), iters=40)
p20, p20f = up.distortion(uv20, lx20, tr20)["stretch_p95"], up.distortion(uv20f, lx20, tr20)["stretch_p95"]
print(f"     [20] adaptive ARAP: {st20.get('iters')} iterations, {dt20:.2f} s, p95 {p20:.5f} vs 40 it. {p20f:.5f}")
check("[20] stops in <= 15 iterations", st20.get("iters", 99) <= 15, st20)
check("[20] p95 within 0.005 of 40 iterations", abs(p20 - p20f) <= 0.005, (p20, p20f))

# [21] tops byte-identical against the base commit
import importlib.util  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
BASE = "c926b67f0"
try:
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:app/blender/scripts/uv_pattern.py"],
                         capture_output=True, text=True, check=True).stdout
except (OSError, subprocess.CalledProcessError) as e:
    src = None
    print(f"NOTE [21] skipped: git show {BASE} failed ({e})")
if src is not None:
    with tempfile.TemporaryDirectory() as td:
        bp = Path(td) / "uv_pattern_base.py"
        bp.write_text(src)
        spec = importlib.util.spec_from_file_location("uv_pattern_base", bp)
        ub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ub)
        new21 = up.pattern_uv(f13, p13, seam13, v13, axes=axes13, strips={5: rows13})["payload"]
        old21 = ub.pattern_uv(f13, p13, seam13, v13, axes=axes13, strips={5: rows13})["payload"]
        check(f"[21] a top's payload is byte-identical to {BASE}'s",
              json.dumps(new21, sort_keys=True) == json.dumps(old21, sort_keys=True))

# [22] ring cut off theta 0
uv22 = up.ring_strip_uv(isl16[0], rx16, (0, 0, 0), (0, 0, 1),
                        (math.cos(math.radians(30)), math.sin(math.radians(30)), 0))
check(f"[22] u length {want16:.6f} with cut_dir 30 deg off", abs(np.ptp(uv22[:, 0]) - want16) < 1e-4,
      np.ptp(uv22[:, 0]))
cut22 = sorted(uv22[isl16[0].vmap == 0, 0])
check("[22] the cut copies at u 0 and the full length",
      len(cut22) == 2 and abs(cut22[0]) < 1e-9 and abs(cut22[1] - want16) < 1e-4, cut22)
q22 = uv22[isl16[0].vmap == 16, 0]
check("[22] the +Y vertex at a quarter (0.157017)", len(q22) == 1 and abs(q22[0] - want16 / 4) < 1e-4, q22)

# [23] banded direct solve
N23 = 50
rr, cc, vv = [], [], []
for i in range(N23):
    rr.append(i)
    cc.append(i)
    vv.append(2.0)
    if i + 1 < N23:
        rr += [i, i + 1]
        cc += [i + 1, i]
        vv += [-1.0, -1.0]
sh = np.random.default_rng(7).permutation(N23)          # unknown i is stored as sh[i]
rr, cc = sh[np.array(rr)], sh[np.array(cc)]
b23 = up._Banded(N23 + 1, rr, cc, np.array(vv))
x23 = b23.solve(np.concatenate([np.ones(N23), [0.0]])[:, None], np.full((N23 + 1, 1), 3.5))[:, 0]
got23 = [float(x23[sh[i - 1]]) for i in (1, 25, 50)]
check("[23] x_1 25, x_25 325, x_50 25", b23.ok and all(abs(g - w) < 1e-9 for g, w in zip(got23, (25, 325, 25))),
      got23)
check("[23] the untouched unknown keeps x0 3.5", abs(x23[N23] - 3.5) < 1e-12, x23[N23])

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
