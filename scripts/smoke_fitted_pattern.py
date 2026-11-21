"""Smoke: the fitted kinds' pattern pieces (``app/blender/scripts/fitted_pattern.py``, step 3a) on synthetic shapes.

Usage:
    ./.venv/bin/python scripts/smoke_fitted_pattern.py

No server, no world DB, no Blender: ``fitted_pattern`` and ``uv_pattern`` are numpy only and imported through
``sys.path`` (as ``scripts/smoke_uv_pattern.py``). The shapes are built so their seam lines already lie on vertex
columns — what ``build_fitted``'s ``bisect_plane`` makes of a real collider. Every expectation is derived by hand
below (Blender Z-up metres, front = -Y, the wearer's left = +X, cx = cy = 0).

[1] Leg plane (trousers): a tube r 0.08 round the axis from the hip joint (0.09, 0, 0.88) to the ankle joint
    (0.10, 0.02, 0.10), 48 columns at angle k * 2 pi / 48 in the frame e1 = X made orthogonal to the axis, e2 = axis x
    e1, so columns 0 and 24 lie on the leg plane (through the axis, spanned by X), 6 face rings. ``parts`` splits it
    into two halves of 24 faces per ring: the -Y half is ``front_l`` (x > cx: the wearer's left), the +Y half
    ``back_l``. Each half flattens (``pattern_uv`` with ``axes``) to a rectangle: the chord sum 24 * 2 * 0.08 *
    sin(pi / 48) = 3.84 * 0.0654031 = 0.251148 m wide and |ankle - hip| = sqrt(0.01^2 + 0.02^2 + 0.78^2) = 0.780320 m
    high (+-1e-3 + 1 px), measured along the island's own principal axes (``orient`` turns the mean of +Z to +v; the
    leg axis stands 1.6 deg off Z, so the atlas bbox is a few mm wider).
[2] Centre seam: a front half ring r 0.30 (y < 0), 24 columns from angle pi to 2 pi (column 12 at x = 0), 2 rings:
    every face whose centroid has x > 0 is ``front_l``, x < 0 ``front_r`` — no corner of a ``front_l`` face lies at
    x < 0 and none of a ``front_r`` face at x > 0 (the bisected centre line is a vertex column).
[3] Gusset box (briefs): crotch point (0, 0.01, 0.811), cy 0; the gusset spans the whole crotch (no x bound — its
    sides are the leg openings): a face at (0.02, -0.02, 0.80) -> ``gusset`` (-0.03 < y < 0.09, z < 0.841);
    (0.02, -0.04, 0.80) -> ``front`` (y < 0.01 - 0.04 = -0.03); (0.04, 0.0, 0.85) -> not the gusset (z >= 0.841;
    y 0 is not < cy 0: ``back``); (0.12, 0.0, 0.80) -> ``gusset`` (x far off the centre, inside the box).
[4] Tube cut reaches the border: a tube r 0.06, 0.60 high (32 columns, 12 face rings) closed by a hemisphere cap
    (6 rings + the pole), opened by ``plane_cut`` on the plane y = 0, half x < 0 (the inner line, column 16), from the
    rim down over the cap to the pole -> ONE island, ``area_ratio`` 0.97..1.03. The same tube with the cut starting
    5 cm under the rim (a slit that reaches no border: the Kira failure, 0.94 / p95 1.83 measured) has Euler
    characteristic 0 (a hole) -> ``open_islands`` adds the shortest path from the slit to the rim: the 5 cm column
    (0.05 m / (0.60 / 12) = 1 edge) and the island becomes a disk again (``area_ratio`` 0.97..1.03).
[5] Ring cut: a ring of 64 quads (r 0.10, 0.04 high, part 14 ``waistband``), ``plane_cut`` on x = 0, half y > 0 (the
    centre back) -> exactly 1 edge (the vertical edge of column 16 at (0, 0.10)); ``split_islands`` then gives ONE
    island (the ring opened).
[6] Glove planes: a left hand as a box 0.18 x 0.09 x 0.03 (x 0.70..0.88, y +-0.045, z 1.385..1.415; 6 x 3 quads on top
    and bottom) on the X axis, palm down (Index1 (0.79, -0.03, 1.4), Pinky1 (0.79, 0.03, 1.4): the hand normal
    (Index1 - Hand) x (Pinky1 - Hand) = (0, 0, 0.0054) = +Z, dorsal): ``parts`` gives ``glove_back_l`` (27) for every
    +Z face and ``palm_l`` (29) for every -Z face; the side faces (centroid on the hand plane, not on its + side) go
    to the palm; nothing else.
[8] A zero-area face in the seam plane (Kira's tights, 2026-11-21: ``bisect_plane`` left 21 single-face slivers on the
    inseam): the closed tube of [4], the cut edge (112, 144) of column 16 (x = -r, y = 0, rows 3 and 4) gets its
    midpoint m (vertex 577 = 18 rows * 32 + the pole + 1, on the plane); the face k = 15 on the +Y side (centroid angle 15.5 / 32 * 2 pi < pi)
    becomes the pentagon (111, 112, m, 144, 143) and the collinear triangle (144, m, 112) fills the gap to the face
    k = 16 on the -Y side. All three of the triangle's edges lie on the plane. A face whose centroid lies on the plane
    (within ``FACE_ON_PLANE_M`` 1e-6) counts to the -normal side, so the cut takes 112-m and m-144 (pentagon + /
    triangle -), not 112-144 (triangle - / face k = 16 -): len(full) - 1 + 2 = len(full) + 1 edges, ONE island, no
    sliver (the old rule, both ends on the plane, cut all three and left the triangle as a 1-face island).
    Second, m 40 um off the plane at +Y (what Kira's tights had: a third corner 10..300 um off, inside ``ON_PLANE_M``
    1e-4 so all three edges still count as on the plane): the triangle's centroid lies 40 / 3 = 13.3 um on the + side
    > 1e-6, so it keeps its side (+, with the pentagon) and the cut is exactly ``full`` (112-144 between the triangle
    and face k = 16) — one island, no sliver.
[7] Rows / axes / rings: ``rows("briefs", {leg_length_m: 0.1})`` are the boxers' (trousers') rows; ``rows("bra",
    {style: bandeau})`` the bandeau's; every part id ``parts`` can emit has a name in ``uv_pattern.PARTS``; ``rings``
    gives the waistband the vertical axis through (cx, cy) opened at +Y.
"""
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import fitted_pattern as fp  # noqa: E402
import uv_pattern as up  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def legs_joints():
    j = {}
    for s, sd in ((1, "Left"), (-1, "Right")):
        j[sd + "UpLeg"] = np.array([0.09 * s, 0.0, 0.88])
        j[sd + "Foot"] = np.array([0.10 * s, 0.02, 0.10])
        j[sd + "Leg"] = np.array([0.095 * s, 0.01, 0.49])
        j[sd + "ToeBase"] = np.array([0.10 * s, -0.12, 0.02])
    return j


def centroids(xyz, faces):
    return np.array([xyz[list(f)].mean(0) for f in faces])


# [1] leg plane
J = legs_joints()
hip, ank = J["LeftUpLeg"], J["LeftFoot"]
d = (ank - hip) / np.linalg.norm(ank - hip)
e1 = np.array([1.0, 0, 0]) - d[0] * d
e1 /= np.linalg.norm(e1)
e2 = np.cross(d, e1)
NS, NR = 48, 6
L = np.linalg.norm(ank - hip)
xyz1 = np.array([hip + d * (L * r / NR) + 0.08 * (math.cos(2 * math.pi * k / NS) * e1 + math.sin(2 * math.pi * k / NS) * e2)
                 for r in range(NR + 1) for k in range(NS)])
f1 = [(r * NS + k, r * NS + (k + 1) % NS, (r + 1) * NS + (k + 1) % NS, (r + 1) * NS + k) for r in range(NR) for k in range(NS)]
info1 = {"cx": 0.0, "cy": 0.0}
spec1 = {"top_y": 2.0, "waistband_m": 0.0, "hem": "plain"}
p1 = fp.parts("trousers", spec1, centroids(xyz1, f1), J, info1)
names1 = {up.PARTS[int(p)] for p in p1}
check("[1] two halves front_l / back_l", names1 == {"front_l", "back_l"}, names1)
per_ring = [int(np.sum(p1[r * NS:(r + 1) * NS] == fp.P["front_l"])) for r in range(NR)]
check("[1] 24 front faces per ring", per_ring == [24] * NR, per_ring)
fr = [k for k in range(NS) if p1[k] == fp.P["front_l"]]
check("[1] the front half lies at -Y", all(centroids(xyz1, [f1[k]])[0][1] < 0 for k in fr))
r1 = up.pattern_uv(f1, p1, set(), xyz1, axes=fp.axes("trousers", spec1, J, info1), rows=fp.rows("trousers", spec1))
s1 = r1["payload"]["px_per_cm"]
for isl in r1["payload"]["islands"]:
    q = np.array(isl["verts_px"]) / s1 / 100
    q = q - q.mean(0)
    _u, _s, vt = np.linalg.svd(q, full_matrices=False)
    ext = np.ptp(q @ vt.T, axis=0)
    h, w = float(max(ext)), float(min(ext))
    check(f"[1] {isl['name']} 0.251148 x 0.780320", abs(w - 0.251148) < 1e-3 + 1 / s1 / 100
          and abs(h - 0.780320) < 1e-3 + 1 / s1 / 100, (round(w, 5), round(h, 5)))

# [2] centre seam
NS2 = 24
xyz2 = np.array([(0.30 * math.cos(math.pi + math.pi * k / NS2), 0.30 * math.sin(math.pi + math.pi * k / NS2), z)
                 for z in (1.0, 1.1) for k in range(NS2 + 1)])
f2 = [(k, k + 1, NS2 + 1 + k + 1, NS2 + 1 + k) for k in range(NS2)]
p2 = fp.parts("trousers", {"top_y": 2.0, "waistband_m": 0.0, "hem": "plain"}, centroids(xyz2, f2),
              {**J, "LeftUpLeg": np.array([0.09, 0.0, 1.5]), "RightUpLeg": np.array([-0.09, 0.0, 1.5])}, info1)
bad = [i for i, (f, p) in enumerate(zip(f2, p2))
       if (up.PARTS[int(p)].endswith("_l") and xyz2[list(f), 0].min() < -1e-12)
       or (up.PARTS[int(p)].endswith("_r") and xyz2[list(f), 0].max() > 1e-12)]
check("[2] no face straddles the centre line", not bad and {up.PARTS[int(p)] for p in p2} == {"front_l", "front_r"},
      (bad, {up.PARTS[int(p)] for p in p2}))

# [3] gusset box
info3 = {"cx": 0.0, "cy": 0.0, "crotch_z": 0.811, "crotch_y": 0.01}
spec3 = {"top_y": 1.0, "waistband_m": 0.0, "gusset_half_m": 0.03}
p3 = fp.parts("briefs", spec3, np.array([(0.02, -0.02, 0.80), (0.02, -0.04, 0.80), (0.04, 0.0, 0.85),
                                         (0.12, 0.0, 0.80)]), J, info3)
check("[3] gusset / front / not the gusset / wide gusset",
      [up.PARTS[int(p)] for p in p3] == ["gusset", "front", "back", "gusset"],
      [up.PARTS[int(p)] for p in p3])


# [4] tube cut
def closed_tube(ns=32, nr=12, nc=6, r=0.06, h=0.60):
    pts = [(r * math.cos(2 * math.pi * k / ns), r * math.sin(2 * math.pi * k / ns), h - h * j / nr)
           for j in range(nr + 1) for k in range(ns)]
    for j in range(1, nc):
        a = 0.5 * math.pi * j / nc
        pts += [(r * math.cos(a) * math.cos(2 * math.pi * k / ns), r * math.cos(a) * math.sin(2 * math.pi * k / ns),
                 -r * math.sin(a)) for k in range(ns)]
    pole = len(pts)
    pts.append((0.0, 0.0, -r))
    rows = nr + nc
    fs = [(j * ns + k, j * ns + (k + 1) % ns, (j + 1) * ns + (k + 1) % ns, (j + 1) * ns + k)
          for j in range(rows - 1) for k in range(ns)]
    fs += [((rows - 1) * ns + k, (rows - 1) * ns + (k + 1) % ns, pole) for k in range(ns)]
    return np.array(pts), fs


x4, f4 = closed_tube()
pa4 = np.full(len(f4), fp.P["leg_l"])
Y = np.array([0.0, 1.0, 0.0])
X = np.array([1.0, 0.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])
full = fp.plane_cut(f4, pa4, x4, fp.P["leg_l"], np.zeros(3), Y, np.zeros(3), Z, -X)
r4 = up.pattern_uv(f4, pa4, full, x4)
isl4 = r4["payload"]["islands"]
check("[4] full cut: one island", len(isl4) == 1, [i["name"] for i in isl4])
ar4 = isl4[0]["distortion"]["area_ratio"]
check("[4] full cut: area ratio 0.97..1.03", 0.97 <= ar4 <= 1.03, isl4[0]["distortion"])
short = {e for e in full if min(x4[e[0], 2], x4[e[1], 2]) < 0.60 - 0.05 - 1e-9}
check("[4] the short cut leaves the top edge (1 edge fewer)", len(full) - len(short) == 1, (len(full), len(short)))
chi = fp._euler(up.split_islands(len(x4), f4, pa4, short, xyz=x4)[0])
check("[4] a slit that reaches no border: Euler characteristic 0", chi == 0, chi)
r4s = up.pattern_uv(f4, pa4, short, x4)
print(f"     [4] short cut as is: {r4s['payload']['islands'][0]['distortion']}")
check("[4] the short cut as is flattens badly (area ratio < 0.97)",
      r4s["payload"]["islands"][0]["distortion"]["area_ratio"] < 0.97, r4s["payload"]["islands"][0]["distortion"])
opened, rep4 = fp.open_islands(f4, pa4, x4, short)
check("[4] open_islands adds the 1 edge to the rim", rep4 and rep4[0]["added"] == 1 and len(opened) == len(full),
      rep4)
r4o = up.pattern_uv(f4, pa4, opened, x4)
ar4o = r4o["payload"]["islands"][0]["distortion"]["area_ratio"]
check("[4] opened: a disk with area ratio 0.97..1.03",
      fp._euler(up.split_islands(len(x4), f4, pa4, opened, xyz=x4)[0]) == 1 and 0.97 <= ar4o <= 1.03, ar4o)

# [8] a zero-area face in the seam plane
x8 = np.vstack([x4, 0.5 * (x4[112] + x4[144])])
m8 = len(x4)
f8 = [f for f in f4 if f not in ((111, 112, 144, 143), (112, 113, 145, 144))]
f8 += [(111, 112, m8, 144, 143), (144, m8, 112), (112, 113, 145, 144)]
check("[8] the edits hit the faces of [4]", len(f8) == len(f4) + 1 and abs(x8[m8, 1]) < 1e-12, len(f8))
pa8 = np.full(len(f8), fp.P["leg_l"])
c8 = fp.plane_cut(f8, pa8, x8, fp.P["leg_l"], np.zeros(3), Y, np.zeros(3), Z, -X)
check("[8] cut: 112-m and m-144, not 112-144",
      c8 == (full - {(112, 144)}) | {(112, m8), (144, m8)}, sorted(c8 ^ ((full - {(112, 144)}) | {(112, m8), (144, m8)})))
isl8 = up.split_islands(len(x8), f8, pa8, c8, xyz=x8)
check("[8] one island, no sliver", len(isl8) == 1 and fp.slivers(f8, pa8, x8, c8) == [],
      [(i.name, len(i.faces)) for i in isl8])

x8b = x8.copy()
x8b[m8, 1] = 4e-5
c8b = fp.plane_cut(f8, pa8, x8b, fp.P["leg_l"], np.zeros(3), Y, np.zeros(3), Z, -X)
check("[8] m 40 um at +Y: the triangle keeps its side, the cut is exactly full", c8b == full, sorted(c8b ^ full))
check("[8] m 40 um at +Y: one island, no sliver",
      len(up.split_islands(len(x8b), f8, pa8, c8b, xyz=x8b)) == 1 and fp.slivers(f8, pa8, x8b, c8b) == [])

# [5] ring cut
x5 = np.array([(0.10 * math.cos(2 * math.pi * k / 64), 0.10 * math.sin(2 * math.pi * k / 64), z)
               for z in (1.0, 1.04) for k in range(64)])
f5 = [(k, (k + 1) % 64, 64 + (k + 1) % 64, 64 + k) for k in range(64)]
pa5 = np.full(64, fp.P["waistband"])
c5 = fp.plane_cut(f5, pa5, x5, fp.P["waistband"], np.zeros(3), X, np.zeros(3), Z, Y)
check("[5] exactly the edge of column 16", c5 == {(16, 80)}, c5)
check("[5] one island", len(up.split_islands(len(x5), f5, pa5, c5, xyz=x5)) == 1)
c5all = fp.cuts("briefs", {"waistband_m": 0.02}, f5, pa5, x5, J, {"cx": 0.0, "cy": 0.0})
check("[5] cuts() opens the waistband at the centre back", c5all == {(16, 80)}, c5all)

# [6] glove planes
GJ = {}
for s, sd in ((1, "Left"), (-1, "Right")):
    def P3(x, y, z=1.4):
        return np.array([s * x, y, z])
    GJ.update({sd + "Arm": P3(0.2, 0), sd + "ForeArm": P3(0.45, 0), sd + "Hand": P3(0.70, 0),
               sd + "HandThumb1": P3(0.72, -0.04), sd + "HandThumb2": P3(0.75, -0.06), sd + "HandThumb3": P3(0.78, -0.07)})
    for fn, y in (("Index", -0.03), ("Middle", -0.01), ("Ring", 0.01), ("Pinky", 0.03)):
        for k in (1, 2, 3):
            GJ[f"{sd}Hand{fn}{k}"] = P3(0.79 + 0.03 * (k - 1), y)
xs, ys = np.linspace(0.70, 0.88, 7), np.linspace(-0.045, 0.045, 4)
c6, want6 = [], []
for z, part in ((1.415, 27), (1.385, 29)):
    for i in range(6):
        for j in range(3):
            c6.append(((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2, z))
            want6.append(part)
for x in (0.75, 0.83):
    for y in (-0.045, 0.045):
        c6.append((x, y, 1.4))
        want6.append(29)
c6.append((0.88, 0.0, 1.4))
want6.append(29)
p6 = fp.parts("gloves", {"cuff": "none"}, np.array(c6), GJ, {"cx": 0.0, "cy": 0.0})
check("[6] +Z faces back of the hand, -Z and sides palm, nothing else", list(p6) == want6,
      [(c, int(p)) for c, p, w in zip(c6, p6, want6) if p != w])

# [7] rows / axes / rings
check("[7] boxers take the trousers' rows", fp.rows("briefs", {"leg_length_m": 0.1}) == up.ROWS["trousers"])
check("[7] a bandeau its own rows", fp.rows("bra", {"style": "bandeau"}) == up.ROWS["bandeau"])
check("[7] every fitted part id is named", all(i in up.PARTS for i in range(10, 37)))
rg = fp.rings("briefs", {}, J, {"cx": 0.0, "cy": 0.0})
check("[7] waistband ring: vertical axis through (cx, cy), opened at +Y",
      rg[fp.P["waistband"]] == ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)), rg[fp.P["waistband"]])

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
