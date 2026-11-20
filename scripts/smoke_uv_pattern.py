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

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
