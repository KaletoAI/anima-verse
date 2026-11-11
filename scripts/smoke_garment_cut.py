#!/usr/bin/env python3
"""The subtract hair method's cut (app/core/garment_cut.py; plan
docs/superpowers/plans/2026-11-10-hair-subtract-method.md, Task 1) on synthetic meshes and images.

Usage:
    ./.venv/bin/python scripts/smoke_garment_cut.py

No server, no world, no hub, no GPU: numpy/scipy geometry against numbers derived by hand below.

GEOMETRY (unrigged units; the rigged body is 1.7 x unrigged + (0, 0.05, 0), so k = 1.7 m per unit)
  B (bald base): head sphere R 0.100 at C = (0, 0.9, 0) on a 3-degree polar grid (theta from +y, 61 rows,
  120 longitudes), a nose sphere r 0.02 at (0, 0.88, 0.095) and ONE ear sphere r 0.02 at (0.095, 0.87, 0.02)
  (with the nose alone the head is still symmetric about the C-nose axis — a roll the ICP cannot see), a closed
  torso cylinder r 0.12, y 0 .. 0.8. Head + nose weighted Head, torso Spine2.
  H (haired, the truth in B's frame): the same head grid with radius 0.112 for theta <= 60 deg (rows 0..20 =
  the CAP) and 0.100 below, plus the same nose and torso. H as delivered = 2 x truth + (0.3, -0.2, 0.1)
  (the mesher's own frame). Cap thickness 0.012 units = 2.04 cm (> LOOSE_EPS_M 1.5 cm: the growth covers it).
  Welded cap vertices: the pole (row 0, 120 duplicates -> 1) + rows 1..20 x 120 = 2401.
IMAGES 1024 x 1200, 1000 px per unit: column 512 = x 0, row 100 = y 1.0 (pixel centre (c + .5, r + .5)).
  bald  = grey 128 + skin (200,160,140): head disc r 0.1 at (0, 0.9) + torso x +-0.12, y 0..0.8
          -> bbox rows [100, 1100) = B's bbox y [0, 1.0], cols [392, 632) = x +-0.12.
  haired = bald + hair (90,60,30) where x^2 + (y-0.9)^2 <= 0.112^2 and y >= 0.956 (the cap's front silhouette:
          its lowest silhouette point is the theta-60 ring at y 0.9 + 0.112 cos 60 = 0.956) -> rows 88..143;
          haired bbox rows [88, 1100) = H's bbox y [0, 1.012]. Back view = the same images.
  So the framing maps H onto B exactly: s_H = 2.024 / 1012 = 0.002, s_B = 0.001, px = 594 - (y - 0.506) /
  0.001 and y_B = 0.5 - (px - 600) x 0.001 = y (x, z centred on the torso, symmetric) -> placement = truth.

EXPECTED, BY HAND
[a] hair_mask_2d on smoke_garment_chain's images (hair rect rows [92, 200) cols [404, 620) on the head disc
    r 100 at (512, 200)): front priors cut the face box rows 150 .. 229 (y0 100 + 0.05 / 0.13 x Hb 1000),
    cols 512 +- 0.85 x 98 = [428, 595] (the disc half-width at row 180 is sqrt(100^2 - 20^2) = 98) ->
    23328 - 50 x 168 = 14928 px (+-1.5 % for the corners the opening rounds); (110, 512) hair, (175, 512)
    not, (175, 410) hair. The back view keeps the whole rect: 23328 +-1.5 %.
[b] pad_into: a base 712 wide into a haired frame 844 wide (both 1536 high): shift = (1536 - 712) // 2 -
    (1536 - 844) // 2 = 412 - 346 = 66 -> base column 10 lands on column 76.
[c] register: the truth perturbed by 2 deg about x, 1.5 deg about y, scale 1.01 about C and a shift of
    (4, -3, 5) mm / 1.7: after ICP_ITERATIONS every vertex within 1 mm of the truth (x k) and the scale of the
    recovered placement vs the truth within 0.1 %.
[d] cut_hair (cut): registration p95 0.0 cm (the non-hair vertices ARE B's vertices; the gate measures the
    Head-weighted part); label = the 2401 cap vertices minus the 25 front-facing theta-60 vertices in the face
    zone that neither mask keeps (derivation at [k]) = 2376, every outer-sheet vertex at theta <= 60 deg + one
    grid step (the edge rings feather inward, never outward); hairline: 2D last hair row 143 -> y_of_row(143) =
    0.506 + (594 - 143) x 0.001 = 0.957, 3D the theta-57 ring in the front strip y 0.9 + 0.112 cos 57 = 0.9610
    -> 0.0040 x 1.7 = 0.68 cm (+-0.1); holes 0; hair area 2 pi r^2 (1 - cos 60) = pi (0.112 x 1.7)^2 =
    1138.8 cm^2 minus the 57..60-degree band cells at the 25 vertices: the band is 2 pi R^2 (cos 57 - cos 60) =
    101.7 cm^2 = 0.847 per longitude, a removed vertex takes the cell to its left whole and the last one half ->
    25.5 cells = 21.6 cm^2 -> 1117.2 cm^2 (+-2 %: chordal grid); the result is ONE closed component (welded: no
    open edge); gates pass; the edge rolled onto the head: ring 0 re-seated at RIM_M = 1.0 mm by the closest point
    (rim_p95_mm 1.0 +-0.05, CUT_VERSION 6); fit params (RIM_M 0.001 m, SPREAD_M).
[e] cut_hair (shell, 5 mm): outer sheet median distance to the head sphere 5.0 mm (+-0.3), max <= 5.3 mm; inner
    sheet median 1.0 mm (+-0.3); a 512 x 512 PNG base colour; closed; gates pass; fit params (0.001 m, 0).
[f] fill_label_holes: the cap minus a 2 x 4 patch of rows 5..6 -> one island filled, label == cap again; a
    floater component (a separate sphere) touching no label stays out; an island above HOLE_FILL_MAX_M2 stays.
[g] majority: a one-vertex tooth on the cap edge (a row-21 vertex) goes, the cap stays.
[h] shapes: thickness outside 2..15 mm or an unknown shape is a ValueError.
[e'] shell rim: ring 0 re-seated SHELL_INNER_M over the scalp -> report shell_rim rim p50 = max = 1.0 mm.
[i] recolour_texture on a 20 x 20 hair texture (90,60,30): a 2 x 3 skin patch (200,160,140) with one texel outside
    the cover, a 1 x 4 white run (240,240,240), a 2 x 2 lighter hair patch (100,68,36; Delta E ~4 < OFF_MIN_DE 12)
    -> 9 texels recoloured, painted with the hair colour; all 9 count as skin-like (the white, L* 95, is nearer to
    the skin, L* 69 / Delta E ~33, than to the dark hair, L* 28 / Delta E ~71); the uncovered skin texel and the
    lighter hair stay. Without a skin colour only the 4 white texels go (the skin, C* ~20 > 15, is no white).
[j] outer wall: a double-walled sphere (outer R 0.100 outward, inner R 0.095 wound inward) -> outer_faces keeps
    none of the inner wall's faces and the outer wall's (its pole rows' degenerate faces may drop, at most
    2 x 120); ExactNearSdf: a point at R 0.093 (2 mm inside the INNER wall) reads 0.093 - 0.100 = -7.0 mm (not
    +2 mm), a point at R 0.101 reads +1.0 mm (+-0.2: the chordal grid).
[k] geometry label (blonde over light skin, Kira e2e 2026-11-10): the [d] case with the hair painted in SKIN
    colour in the BACK view only -> the back mask finds no colour change on the head, the front view still votes
    the front of the cap. The cap stands 0.012 x 1.7 = 2.04 cm outside B everywhere > GEO_MIN_M 1.2 cm, on
    Head-weighted B -> every cap vertex outside the face zone is a geometry seed. The face zone: below the 2D
    hairline y 0.957 (only the theta-60 ring, y 0.956) AND facing forward (B's normal z = sin 60 cos phi > 0.7
    -> |phi| < 36.1 deg: phi = 0, +-3 .. +-36 = 25 vertices; the low zone ends 3 cm / 1.7 above the eye row
    y 0.93, at 0.948 < 0.956). Those 25 lie on the 2D mask's lowest row: the front mask's opening does not keep
    them, so colour does not call them hair either -> label 2401 - 25 = 2376; the 3D hairline in the front
    strip is the theta-57 ring, y 0.9 + 0.112 cos 57 = 0.9610 vs 2D 0.957 -> 0.0040 x 1.7 = 0.68 cm (+-0.1);
    holes 0; gates pass. With the geometry off (GEO_MIN_M 10 m) and no growth (GROW_RINGS 0) the label is what
    the masks see: fewer than 2376.
[l] fill_enclosed on the [k] cap grid (weld: the pole's 120 duplicates -> 1): the crown patch rows 3..14 x
    longitudes 0..29 (360 vertices, far over HOLE_FILL_MAX_M2) taken out of the cap label; barrier = the rows
    >= 40 (the body). The lower head (rows 21..39) touches the barrier -> stays; the patch touches the label only
    -> filled. Its outside 1-ring (neighbours (i, j+-1), (i+-1, j), (i+1, j+1), (i-1, j-1)): row 2 j -1..29 =
    31, row 15 j 0..30 = 31, columns -1 and 30 rows 3..14 = 2 x 12 -> 86 label contacts. One barrier vertex on
    row 2 (j 10): 85 label contacts + 1 barrier -> leak share 0: open; 0.05 x 85 = 4.25 >= 1: enclosed.
[m] small_loops (the caps of the hair sheet's holes): the cap's faces minus the 6 faces around vertex (5, 7) ->
    one loop of its 6 neighbours, 6 boundary edges, each in its face's direction (its reverse is no face edge,
    so a cap face (b, a, centre) continues the winding). Perimeter on R = 0.112 x 1.7 = 0.1904 m, a row step
    R pi / 60 = 0.997 cm, a longitude step R sin(theta) pi / 60: loop (4,6)-(4,7)-(5,8)-(6,8)-(6,7)-(5,6) ->
    0.207 (row 4) + sqrt(0.997^2 + 0.233^2) 1.024 + 0.997 + 0.308 (row 6) + sqrt(0.997^2 + 0.283^2) 1.036 +
    0.997 = 4.57 cm (+-0.05) < CAP_LOOP_MAX_M 25 cm.
[n] tinted_hair (CUT_VERSION 5): hair reference 25 vertices at L*a*b* (60, 10, 30), skin 25 at (50, 20, 20) ->
    separation sqrt(3 x 10^2) = 17.32 >= TINT_MIN_SEPARATION_DE 10. On the line hair + t (skin - hair): distance
    to the hair 17.32 t, to the skin 17.32 (1 - t), margin 17.32 (1 - 2 t) > TINT_MARGIN_DE 3 <=> t < 0.4134:
    (58, 11, 29) -> 2.45 vs 15.03 (hair); t 0.4 (56, 14, 26) -> margin 3.46 (hair); t 0.42 (55.8, 14.2, 25.8) ->
    2.77 (not); t 0.5 (55, 15, 25) -> 0 (not); a hair-coloured vertex not allowed -> not. Skin reference at
    (55, 15, 25): separation 8.66 < 10 -> off, nothing; a reference of 19 vertices (< TINT_MIN_N 20) -> off.
[o] flat hair the masks miss (Kira 2026-11-10: lit blonde lying 0.6 cm on the scalp): the [d] head with a cap of
    radius 0.103 (0.003 x 1.7 = 5.1 mm outside B < GEO_MIN_M 12 mm, < LOOSE_EPS_M: neither geometry nor growth),
    H's texture HAIR on the cap vertices and SKIN elsewhere (a 2 x 1 texture, u 0.25 / 0.75), the back view
    blind (hair painted in skin colour). Images: cap disc r 0.103 with y >= 0.952 -> haired bbox rows [97, 1100)
    = H's y [0, 1.003] (s 0.001, centre row 598.5, mid y 0.5015); the 2D hairline is row 147 -> y 0.5015 +
    (598.5 - 147) x 0.001 = 0.953; the theta-60 ring (y 0.9515, row 148.5) lies under it -> the same 25 face-zone
    vertices as [k]. The colour seeds are then exactly [k]'s geometry seeds (every cap vertex outside the face
    zone) -> label 2376, geo_seeds 0; hairline: the theta-57 ring y 0.9 + 0.103 cos 57 = 0.9561 vs 0.953 ->
    0.0031 x 1.7 = 0.53 cm (+-0.1). With the colour label off (TINT_MARGIN_DE 1e9) only the front votes: < 2376.
    The sheets (5.1 mm hair < INNER_OFFSET_M 6 + INNER_GAP_M 1): inner sheet at 6.0 mm, outer lifted to 7.0 mm
    (medians over the vertices off the edge, +-0.2 mm: chordal grid), every snapped vertex lifted. The temple
    flood (CUT_VERSION 6) takes none of the 25 hair-coloured face-zone vertices: they face forward (front-facing
    theta-60 ring, B's normal z > PROTECT_FACING) -> temple 0.
[p] side_coverage (CUT_VERSION 7), metres: head sphere R 0.1 at (0, 1.6, 0) (top 1.7), ear spheres r 0.02 at
    (+-0.105, 1.55, -0.01). The ear search band y 1.54 .. 1.64: the outermost point is the ear's (lateral 0.125;
    the head reaches 0.1), the ear = lateral >= 0.117 = the ear sphere's disc x - 0.105 >= 0.012, radius
    sqrt(0.02^2 - 0.012^2) = 0.016 -> ear top 1.566 (+-1 mm: 1 mm samples), z within -0.026 .. 0.006. Band y
    1.571 .. 1.601 (15 rows of 2 mm), z from the ear's back edge to 25 mm in front of its front edge; the head
    sphere is there at every cell (|z| <= 0.031 < its xz radius >= 0.0957). Hair = a sphere cap R 0.106 above y_c:
    y_c 1.50 -> 1.0 both sides; y_c 1.62 (above the band) -> 0.0; y_c 1.588 keeps the faces from the latitude -6
    ring up (rings every 2 degrees; -8 is y 1.5852): y 1.6 - 0.106 sin 6 = 1.5889 -> rows floor((1.5889 - 1.571) /
    0.002) = 9 .. 14 = 6 / 15 = 0.4 (+- 1/15, the ear top's 1 mm); the y_c 1.50 cap on x < 0 only -> left 0.0,
    right 1.0, min 0.0. The band holds whole cells only (its z end rounded up to the cell).
    The [d]/[e]/[o]/[k] fixtures (a cap down to theta 60 only, the head sphere R 0.17 m) are refused by this gate
    alone: their search band (1.54 .. 1.64 m) holds no ear (the ear sphere tops out at 1.513 m), the head's
    outermost point is at the band's foot (y 1.54, lateral 0.1697), within 8 mm up to y 1.53 + sqrt(0.17^2 -
    0.1617^2) = 1.582 -> band 1.587 .. 1.617; the cap's lowest edge on the scalp (theta 60) is at 1.53 + 0.17 x 0.5
    = 1.615 (+1 mm rim; the chordal seat may reach row 13, 1.6134 .. 1.6154) -> side_coverage <= 2/15; every
    other gate passes.
"""
import io
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
K = 1.7
C = np.array([0.0, 0.9, 0.0])
EAR = (0.095, 0.87, 0.02)   # one ear only: with the nose alone the head is symmetric about the C-nose axis
GREY, SKIN, HAIR = (128, 128, 128), (200, 160, 140), (90, 60, 30)
W, H = 1024, 1200


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and math.isfinite(got) and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} +- {tol})")
    if not ok:
        FAILS.append(label)


# --- geometry ------------------------------------------------------------------------

def head_grid(radius_of_row, centre=C, step=3, nlon=120):
    """Polar grid: row i at theta = i x step deg (0 .. 180), nlon longitudes (phi 0 = +z, the front)."""
    rows = 180 // step + 1
    th = np.radians(np.arange(rows) * step)
    ph = np.radians(np.arange(nlon) * 360 / nlon)
    T, Pp = np.meshgrid(th, ph, indexing="ij")
    r = np.array([radius_of_row(i) for i in range(rows)])[:, None]
    P = np.stack([r * np.sin(T) * np.sin(Pp), r * np.cos(T), r * np.sin(T) * np.cos(Pp)], -1).reshape(-1, 3)
    P = P + centre
    F = []
    for i in range(rows - 1):
        for j in range(nlon):
            a, b = i * nlon + j, i * nlon + (j + 1) % nlon
            c, d = (i + 1) * nlon + (j + 1) % nlon, (i + 1) * nlon + j
            F += [(a, c, b), (a, d, c)]
    return P, np.array(F, np.int64), rows, nlon


def bodies():
    import smoke_garment_fit as fx
    hP, hF, _r, _n = head_grid(lambda i: 0.100)
    nP, nF = fx.uv_sphere(0.02, (0.0, 0.88, 0.095), nlat=12, nlon=24)
    eP, eF = fx.uv_sphere(0.02, EAR, nlat=12, nlon=24)
    tP, tF = fx.cylinder(0.12, 0.0, 0.8)
    P, F = fx.merge((hP, hF), (nP, nF), (eP, eF), (tP, tF))
    head = np.arange(len(P)) < len(hP) + len(nP) + len(eP)
    return P, F, head


def haired_truth(cap_r=0.112):
    import smoke_garment_fit as fx
    hP, hF, rows, nlon = head_grid(lambda i: cap_r if i <= 20 else 0.100)
    nP, nF = fx.uv_sphere(0.02, (0.0, 0.88, 0.095), nlat=12, nlon=24)
    eP, eF = fx.uv_sphere(0.02, EAR, nlat=12, nlon=24)
    tP, tF = fx.cylinder(0.12, 0.0, 0.8)
    P, F = fx.merge((hP, hF), (nP, nF), (eP, eF), (tP, tF))
    cap = np.zeros(len(P), bool)
    cap[: 21 * nlon] = True
    return P, F, cap


def glbs():
    import smoke_garment_chain as cx
    import smoke_garment_fit as fx
    from app.core.rig_contract import BASE_JOINT_NAMES
    P, F, head = bodies()
    n = len(P)
    U = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    names = list(BASE_JOINT_NAMES)
    J = np.zeros((n, 4), np.int64)
    J[:, 0] = np.where(head, names.index("Head"), names.index("Spine2"))
    Wt = np.zeros((n, 4))
    Wt[:, 0] = 1.0
    unrigged = fx.make_glb(P, F, U, image=cx.solid_png((90, 90, 90)))
    rigged = cx.rigged_glb(K * P + np.array([0, 0.05, 0]), F, U, J, Wt, cx.solid_png(SKIN))
    return unrigged, rigged, P, F


def images(cap_r=0.112, cap_low=0.956):
    yy, xx = np.mgrid[0:H, 0:W]
    x = (xx + 0.5 - 512) / 1000.0
    y = 1.0 - (yy + 0.5 - 100) / 1000.0
    head = x ** 2 + (y - 0.9) ** 2 <= 0.1 ** 2
    torso = (np.abs(x) <= 0.12) & (y >= 0) & (y <= 0.8)
    cap = (x ** 2 + (y - 0.9) ** 2 <= cap_r ** 2) & (y >= cap_low)
    bald = np.zeros((H, W, 3), np.float32)
    bald[:] = GREY
    bald[head | torso] = SKIN
    haired = bald.copy()
    haired[cap] = HAIR
    return bald, head | torso, haired, head | torso | cap


def views():
    from app.core.garment_cut import View
    bald, bald_mask, haired, haired_mask = images()
    v = View(haired, haired_mask, bald, bald_mask)
    return {"front": v, "back": v}


# --- tests ---------------------------------------------------------------------------

def test_mask():
    print("[a] hair_mask_2d")
    import smoke_garment_chain as cx
    from app.core.garment_cut import hair_mask_2d
    base = cx.BASE.astype(np.float32)
    haired = cx.HAIRED.astype(np.float32)
    base_mask = (np.abs(cx.BASE.astype(int) - 128) > 2).any(2)
    haired_mask = (np.abs(cx.HAIRED.astype(int) - 128) > 2).any(2)
    front, info = hair_mask_2d(base, base_mask, haired, haired_mask, "front")
    near("front hair px", int(front.sum()), 14928, 14928 * 0.015)
    check("front (110, 512) hair", bool(front[110, 512]), True)
    check("front (175, 512) face box", bool(front[175, 512]), False)
    check("front (175, 410) hair", bool(front[175, 410]), True)
    check("front colour source", info["sure_source"], "grown")
    back, _ = hair_mask_2d(base, base_mask, haired, haired_mask, "back")
    near("back hair px", int(back.sum()), 23328, 23328 * 0.015)


def test_pad():
    print("[b] pad_into")
    from app.core.garment_cut import pad_into
    rgb = np.zeros((1536, 712, 3), np.float32)
    mask = np.zeros((1536, 712), bool)
    mask[700, 10] = True
    rgb[700, 10] = (1, 2, 3)
    out_rgb, out_mask = pad_into(rgb, mask, (1536, 844))
    check("shifted marker", np.argwhere(out_mask).tolist(), [[700, 76]])
    check("shifted colour", out_rgb[700, 76].tolist(), [1.0, 2.0, 3.0])


def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def test_register():
    print("[c] register")
    from app.core import garment_cut as gc, garment_fit as gf
    Pb, Fb, _head = bodies()
    Pt, Ft, cap = haired_truth()
    R = rot("x", 2.0) @ rot("y", 1.5)
    Q0 = 1.01 * (Pt - C) @ R.T + C + np.array([0.004, -0.003, 0.005]) / K
    Q, _tree, _d, rep = gc.register(Q0, Pb, Fb, cap, K)
    err = float(np.abs(Q - Pt).max()) * K * 1000
    print(f"       ICP {rep}")
    near("max |Q - truth| (mm)", round(err, 3), 0.0, 1.0)
    s, _R, _a, _b = gf.similarity(Q0, Q)
    near("recovered scale vs 1/1.01", round(s * 1.01, 5), 1.0, 0.001)


def test_cut():
    print("[d] cut_hair: cut")
    from app.core import garment_cut as gc, garment_fit as gf
    from app.core.glb_mesh import static_arrays
    unrigged, rigged, Pb, Fb = glbs()
    Pt, Ft, cap = haired_truth()
    import smoke_garment_fit as fx
    import smoke_garment_chain as cx
    Hfile = 2.0 * Pt + np.array([0.3, -0.2, 0.1])
    U = np.stack([(np.arange(len(Pt)) % 997) / 997.0, (np.arange(len(Pt)) // 997) / 997.0], 1)
    haired_glb = fx.make_glb(Hfile, Ft, U, image=cx.solid_png(HAIR))
    res = gc.cut_hair(haired_glb, unrigged, rigged, views(), shape="cut")
    print(f"       metrics {res.metrics}; label {res.report['label']}; edge {res.report['edge']}")
    print(f"       hairline {res.report['hairline']}; closed {res.report['closed']}")
    check("gates: only the side coverage refuses ([p])", (res.ok, [r for r in res.reasons if not r.startswith("side_coverage")]), (False, []))
    check("side coverage <= 2/15 (the cap ends in the band's top rows, [p])", res.metrics["side_coverage"] <= 2 / 15 + 1e-9, True)
    near("registration p95 (cm)", res.metrics["registration_p95_cm"], 0.0, 0.05)
    check("label = 2401 cap vertices - 25 in the face zone", res.report["label"]["vertices"], 2376)
    near("hairline (cm)", res.metrics["hairline_cm"], 0.68, 0.1)
    check("holes", res.metrics["label_holes"], 0)
    near("hair area (cm2)", res.metrics["hair_area_cm2"], 1117.2, 1117.2 * 0.02)
    check("closed: no open edge, one component", (res.report["closed"]["open_edges"],
                                                  res.report["closed"]["components"]), (0, 1))
    near("rim p95 (mm): ring 0 at RIM_M", res.metrics["rim_p95_mm"], 1.0, 0.05)
    check("fit params", (res.clearance_m, res.spread_m), (0.001, gf.SPREAD_M))
    P, F, _U, image, mime, _mat = static_arrays(res.glb)
    outer = P[: len(P) // 2]
    theta = np.degrees(np.arccos(np.clip((outer[:, 1] - C[1]) / np.linalg.norm(outer - C, axis=1), -1, 1)))
    check("outer sheet within theta <= 63 deg", bool((theta <= 63.0 + 1e-6).all()), True)
    check("H's texture kept", (mime, len(image) > 0), ("image/png", True))
    return res


def test_shell():
    print("[e] cut_hair: shell 5 mm")
    from app.core import garment_cut as gc
    from app.core.glb_mesh import static_arrays
    from PIL import Image
    unrigged, rigged, Pb, Fb = glbs()
    Pt, Ft, cap = haired_truth()
    import smoke_garment_fit as fx
    import smoke_garment_chain as cx
    Hfile = 2.0 * Pt + np.array([0.3, -0.2, 0.1])
    U = np.zeros((len(Pt), 2))
    res = gc.cut_hair(fx.make_glb(Hfile, Ft, U, image=cx.solid_png(HAIR)), unrigged, rigged, views(),
                      shape="shell", thickness_m=0.005)
    print(f"       metrics {res.metrics}; shell {res.report.get('shell')}; closed {res.report['closed']}")
    check("gates: only the side coverage refuses ([p])", (res.ok, [r for r in res.reasons if not r.startswith("side_coverage")]), (False, []))
    P, F, _U, image, mime, _mat = static_arrays(res.glb)
    half = len(P) // 2
    d_out = (np.linalg.norm(P[:half] - C, axis=1) - 0.1) * K * 1000
    d_in = (np.linalg.norm(P[half:] - C, axis=1) - 0.1) * K * 1000
    near("outer median (mm)", round(float(np.median(d_out)), 3), 5.0, 0.3)
    print(f"       outer p05 {np.percentile(d_out, 5):.2f} max {d_out.max():.2f}; argmax {P[np.argmax(d_out)]}")
    check("outer max <= 5.3 mm", round(float(d_out.max()), 3) <= 5.3, True)
    near("inner median (mm)", round(float(np.median(d_in)), 3), 1.0, 0.3)
    with Image.open(io.BytesIO(image)) as im:
        check("texture", (mime, im.size), ("image/png", (512, 512)))
    check("closed", (res.report["closed"]["open_edges"], res.report["closed"]["components"]), (0, 1))
    check("fit params", (res.clearance_m, res.spread_m), (0.001, 0.0))
    rim = res.report.get("shell_rim") or {}
    check("rim seated 1.0 mm on the scalp", (rim.get("rim_p50_mm"), rim.get("rim_max_mm")), (1.0, 1.0))


def test_colour_mend():
    print("[i] colour mend")
    from app.core import garment_cut as gc
    tex = np.tile(np.array(HAIR, float), (20, 20, 1))
    tex[2:4, 2:5] = SKIN
    tex[10, 5:9] = (240, 240, 240)
    tex[15:17, 15:17] = (100, 68, 36)
    cover = np.ones((20, 20), bool)
    cover[2, 2] = False
    hair_lab, skin_lab = gc.lab(np.array(HAIR, float)), gc.lab(np.array(SKIN, float))
    out, rep = gc.recolour_texture(tex, cover, hair_lab, skin_lab)
    check("counts", (rep["recoloured_texels"], rep["skin_texels"], rep["white_texels"]), (9, 9, 0))
    _out, rep0 = gc.recolour_texture(tex, cover, hair_lab, None)
    check("no skin colour: the white only", (rep0["recoloured_texels"], rep0["skin_texels"], rep0["white_texels"]),
          (4, 0, 4))
    check("skin + white painted with hair", (out[2:4, 2:5][cover[2:4, 2:5]] == HAIR).all()
          and (out[10, 5:9] == HAIR).all(), True)
    check("outside the cover untouched", tuple(out[2, 2]), tuple(float(c) for c in SKIN))
    check("lighter hair kept", tuple(out[15, 15]), (100.0, 68.0, 36.0))
    # pale: HAIR (90,60,30) = L* 28.11, C* 25.46. (80,76,70) = L* 32.52, C* 4.18, dE 21.93 -> not lighter by 8
    # (white needs L* > 36.11), not nearer SKIN (L* ~69), but L* >= 28.11, C* < 0.6 * 25.46 = 15.28, dE > 12: pale.
    # (50,48,45) = L* 19.97, C* 2.24: as grey but DARKER than the hair (a shadow between strands) -> kept.
    tex2 = np.tile(np.array(HAIR, float), (20, 20, 1))
    tex2[5, 5:8] = (80, 76, 70)
    tex2[12, 3:5] = (50, 48, 45)
    out2, rep2 = gc.recolour_texture(tex2, np.ones((20, 20), bool), hair_lab, skin_lab)
    check("pale counts", (rep2["recoloured_texels"], rep2["skin_texels"], rep2["white_texels"], rep2["pale_texels"]),
          (3, 0, 0, 3))
    check("pale painted with hair", (out2[5, 5:8] == HAIR).all(), True)
    check("darker grey kept", tuple(out2[12, 3]), (50.0, 48.0, 45.0))


def test_outer_wall():
    print("[j] outer wall")
    from app.core import garment_fit as gf
    oP, oF, _r, _n = head_grid(lambda i: 0.100, centre=np.zeros(3))
    iP, iF, _r, _n = head_grid(lambda i: 0.095, centre=np.zeros(3))
    P = np.concatenate([oP, iP])
    F = np.concatenate([oF, iF[:, ::-1] + len(oP)])      # the inner wall faces inward
    sdf = gf.body_sdf(P, F, vox=0.002, bounds=(np.full(3, -0.15), np.full(3, 0.15)))
    outer = gf.outer_faces(P, F, sdf)
    check("no inner-wall face", int(outer[len(oF):].sum()), 0)
    check("every non-degenerate outer face", int(outer[:len(oF)].sum()) >= len(oF) - 2 * 120, True)
    ex = gf.ExactNearSdf(sdf, P, F, 0.03)
    X = np.array([[0.0, 0.093, 0.0], [0.0, 0.0, 0.101]])
    near("2 mm inside the inner wall reads 7 mm inside the skin (mm)", round(float(ex.sample(X)[0]) * 1000, 2),
         -7.0, 0.2)
    near("1 mm outside the skin (mm)", round(float(ex.sample(X)[1]) * 1000, 2), 1.0, 0.2)


def test_fill_and_majority():
    print("[f] fill_label_holes / [g] majority")
    from app.core import garment_cut as gc, garment_fit as gf
    import smoke_garment_fit as fx
    Pt, Ft, cap = haired_truth()
    fP, fF = fx.uv_sphere(0.01, (0.5, 0.5, 0.5), nlat=6, nlon=8)
    P, F = fx.merge((Pt, Ft), (fP, fF))
    Pw, Fw, inv = gf.weld(P, F)
    cap_w = np.zeros(len(Pw), bool)
    cap_w[inv[np.nonzero(np.concatenate([cap, np.zeros(len(fP), bool)]))[0]]] = True
    adj = gf._adjacency(Fw, len(Pw))
    nlon = 120
    hole = cap_w.copy()
    hole_idx = inv[[i * nlon + j for i in (5, 6) for j in range(4)]]
    hole[hole_idx] = False
    filled, count = gc.fill_label_holes(Fw, Pw * K, hole, adj, gc.HOLE_FILL_MAX_M2)
    check("one island filled", count, 1)
    check("label == cap again", bool((filled == cap_w).all()), True)
    floater = inv[len(Pt):]
    check("floater stays out", bool(filled[floater].any()), False)
    big = cap_w.copy()
    big[inv[[i * nlon + j for i in range(3, 15) for j in range(30)]]] = False
    _f, count_big = gc.fill_label_holes(Fw, Pw * K, big, adj, gc.HOLE_FILL_MAX_M2)
    check("a 12 x 30 island (> 25 cm2) stays", count_big, 0)
    tooth = cap_w.copy()
    tooth[inv[21 * nlon + 7]] = True
    smoothed = gc.majority(tooth, adj, 2)
    check("tooth gone, cap kept", bool((smoothed == cap_w).all()), True)


def test_args():
    print("[h] shapes")
    from app.core import garment_cut as gc
    for kw in ({"shape": "shell", "thickness_m": 0.001}, {"shape": "shell", "thickness_m": 0.02},
               {"shape": "helmet"}):
        try:
            gc.cut_hair(b"", b"", b"", {}, **kw)
            check(f"{kw} refused", "no error", "ValueError")
        except ValueError:
            check(f"{kw} refused", "ValueError", "ValueError")


def test_geometry_label():
    print("[k] geometry label: skin-coloured hair in the back view")
    from app.core import garment_cut as gc
    import smoke_garment_fit as fx
    import smoke_garment_chain as cx
    unrigged, rigged, Pb, Fb = glbs()
    Pt, Ft, cap = haired_truth()
    Hfile = 2.0 * Pt + np.array([0.3, -0.2, 0.1])
    U = np.stack([(np.arange(len(Pt)) % 997) / 997.0, (np.arange(len(Pt)) // 997) / 997.0], 1)
    haired_glb = fx.make_glb(Hfile, Ft, U, image=cx.solid_png(HAIR))
    bald, bald_mask, haired, haired_mask = images()
    blonde = haired.copy()
    blonde[np.all(haired == np.array(HAIR, np.float32), axis=2)] = SKIN
    vs = {"front": gc.View(haired, haired_mask, bald, bald_mask), "back": gc.View(blonde, haired_mask, bald, bald_mask)}
    res = gc.cut_hair(haired_glb, unrigged, rigged, vs, shape="cut")
    print(f"       metrics {res.metrics}; label {res.report['label']}")
    check("gates: only the side coverage refuses ([p])", (res.ok, [r for r in res.reasons if not r.startswith("side_coverage")]), (False, []))
    check("label = 2401 cap vertices - 25 front-facing theta-60 vertices", res.report["label"]["vertices"], 2376)
    check("geometry seeds beyond the votes", res.report["label"]["geo_only"] > 0, True)
    check("holes", res.metrics["label_holes"], 0)
    near("hairline (cm)", res.metrics["hairline_cm"], 0.68, 0.1)
    old = gc.GEO_MIN_M, gc.GROW_RINGS
    gc.GEO_MIN_M, gc.GROW_RINGS = 10.0, 0
    try:
        off = gc.cut_hair(haired_glb, unrigged, rigged, vs, shape="cut")
    finally:
        gc.GEO_MIN_M, gc.GROW_RINGS = old
    print(f"       masks only: label {off.report['label']['vertices']}")
    check("the masks alone label less", off.report["label"]["vertices"] < 2376, True)


def test_fill_enclosed():
    print("[l] fill_enclosed")
    from app.core import garment_cut as gc, garment_fit as gf
    P, F, rows, nlon = head_grid(lambda i: 0.112 if i <= 20 else 0.100)
    Pw, Fw, inv = gf.weld(P, F)
    adj = gf._adjacency(Fw, len(Pw))
    cap_w = np.zeros(len(Pw), bool)
    cap_w[inv[: 21 * nlon]] = True
    patch = np.zeros(len(Pw), bool)
    patch[inv[[i * nlon + j for i in range(3, 15) for j in range(30)]]] = True
    body = np.zeros(len(Pw), bool)
    body[inv[40 * nlon:]] = True
    label = cap_w & ~patch
    filled, n, top = gc.fill_enclosed(label, ~body, body, adj)
    print(f"       components {top}")
    check("crown patch filled, the lower head not", (n, bool((filled == cap_w).all())), (1, True))
    check("patch contacts", [(c["n"], c["hair"], c["barrier"]) for c in top if c["filled"]], [(360, 86, 0)])
    barrier = body.copy()
    barrier[inv[2 * nlon + 10]] = True
    label_b = label & ~barrier
    _f, n0, top0 = gc.fill_enclosed(label_b, ~barrier, barrier, adj)
    check("one barrier contact, share 0 -> open", n0, 0)
    check("contacts with the barrier vertex", [(c["n"], c["hair"], c["barrier"]) for c in top0 if c["n"] == 360],
          [(360, 85, 1)])
    _f, n1, _t = gc.fill_enclosed(label_b, ~barrier, barrier, adj, 0.05)
    check("share 0.05 -> enclosed", n1, 1)


def test_small_loops():
    print("[m] small_loops")
    from app.core import garment_cut as gc, garment_fit as gf
    P, F, rows, nlon = head_grid(lambda i: 0.112 if i <= 20 else 0.100)
    Pw, Fw, inv = gf.weld(P, F)
    cap = np.zeros(len(Pw), bool)
    cap[inv[: 21 * nlon]] = True
    patch = gc.faces_all(Fw, cap)
    v = inv[5 * nlon + 7]
    patch = patch[~(patch == v).any(1)]
    loops = gc.small_loops(patch, Pw * K, gc.CAP_LOOP_MAX_M)
    check("one small loop", len(loops), 1)
    edges, verts, per = loops[0]
    check("6 vertices, 6 edges", (len(verts), len(edges)), (6, 6))
    face_edges = {tuple(e) for f in patch.tolist() for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0]))}
    check("edges run as their faces do", all(tuple(e) in face_edges and (e[1], e[0]) not in face_edges
                                           for e in edges.tolist()), True)
    near("perimeter (cm)", round(per * 100, 3), 4.57, 0.05)


def test_tinted():
    print("[n] tinted_hair")
    from app.core import garment_cut as gc
    hair, skin = np.array([60.0, 10.0, 30.0]), np.array([50.0, 20.0, 20.0])
    probe = np.array([[58, 11, 29], hair + 0.4 * (skin - hair), hair + 0.42 * (skin - hair),
                      hair + 0.5 * (skin - hair), [58, 11, 29]], float)
    tint = np.concatenate([np.tile(hair, (25, 1)), np.tile(skin, (25, 1)), probe])
    n = len(tint)
    hair_ref = np.zeros(n, bool)
    hair_ref[:25] = True
    skin_ref = np.zeros(n, bool)
    skin_ref[25:50] = True
    allowed = np.zeros(n, bool)
    allowed[50:54] = True                       # the last probe (hair-coloured) is not allowed
    out, rep = gc.tinted_hair(tint, hair_ref, skin_ref, allowed)
    check("probes: hair, t 0.4 hair, t 0.42 not, t 0.5 not, not allowed", out[50:].tolist(),
          [True, True, False, False, False])
    near("separation (dE)", rep["separation_de"], 17.32, 0.05)
    tint2 = tint.copy()
    tint2[25:50] = hair + 0.5 * (skin - hair)
    out2, rep2 = gc.tinted_hair(tint2, hair_ref, skin_ref, allowed)
    check("references 8.66 apart -> off", (rep2["used"], int(out2.sum())), (False, 0))
    few = skin_ref.copy()
    few[25:31] = False                          # 19 skin vertices
    out3, rep3 = gc.tinted_hair(tint, hair_ref, few, allowed)
    check("19 reference vertices -> off", (rep3["used"], int(out3.sum())), (False, 0))
    check("no texture -> off", gc.tinted_hair(None, hair_ref, skin_ref, allowed)[1], {"used": False})


def test_flat_hair():
    print("[o] flat hair the masks miss: colour label + inner sheet at the clearance")
    import io as _io
    from PIL import Image
    from app.core import garment_cut as gc
    from app.core.glb_mesh import static_arrays
    import smoke_garment_fit as fx
    unrigged, rigged, Pb, Fb = glbs()
    Pt, Ft, cap = haired_truth(0.103)
    Hfile = 2.0 * Pt + np.array([0.3, -0.2, 0.1])
    tex = Image.new("RGB", (2, 1))
    tex.putpixel((0, 0), HAIR)
    tex.putpixel((1, 0), SKIN)
    buf = _io.BytesIO()
    tex.save(buf, format="PNG")
    U = np.stack([np.where(cap, 0.25, 0.75), np.full(len(Pt), 0.5)], 1)
    haired_glb = fx.make_glb(Hfile, Ft, U, image=buf.getvalue())
    bald, bald_mask, haired, haired_mask = images(0.103, 0.952)
    blind = haired.copy()
    blind[np.all(haired == np.array(HAIR, np.float32), axis=2)] = SKIN
    vs = {"front": gc.View(haired, haired_mask, bald, bald_mask), "back": gc.View(blind, haired_mask, bald, bald_mask)}
    res = gc.cut_hair(haired_glb, unrigged, rigged, vs, shape="cut")
    lab_rep = res.report["label"]
    print(f"       metrics {res.metrics}; label {lab_rep}; cut {res.report['cut']}")
    check("gates: only the side coverage refuses ([p])", (res.ok, [r for r in res.reasons if not r.startswith("side_coverage")]), (False, []))
    check("no geometry seed (5.1 mm < 12 mm)", lab_rep["geo_seeds"], 0)
    check("colour label used", lab_rep["tint"]["used"], True)
    check("temple flood: none of the forward-facing face-zone vertices", lab_rep["temple"], 0)
    check("label = 2401 cap vertices - 25 in the face zone", lab_rep["vertices"], 2376)
    near("hairline (cm)", res.metrics["hairline_cm"], 0.53, 0.1)
    check("holes", res.metrics["label_holes"], 0)
    P = static_arrays(res.glb)[0]
    half = len(P) // 2
    d_out = (np.linalg.norm(P[:half] - C, axis=1) - 0.1) * K * 1000
    d_in = (np.linalg.norm(P[half:] - C, axis=1) - 0.1) * K * 1000
    off_edge = np.abs(d_out - d_in) > 0.6            # ring 0 (sheets meet) and ring 1 (halfway) excluded
    near("inner sheet median (mm)", round(float(np.median(d_in[off_edge])), 3), 6.0, 0.2)
    near("outer sheet median, lifted (mm)", round(float(np.median(d_out[off_edge])), 3), 7.0, 0.2)
    check("every snapped vertex lifted", res.report["cut"]["thin_lifted_share"], res.report["cut"]["snapped_share"])
    old = gc.TINT_MARGIN_DE
    gc.TINT_MARGIN_DE = 1e9
    try:
        off = gc.cut_hair(haired_glb, unrigged, rigged, vs, shape="cut")
    finally:
        gc.TINT_MARGIN_DE = old
    print(f"       colour label off: label {off.report['label']['vertices']}")
    check("without the colour label the front votes only", off.report["label"]["vertices"] < 2376, True)


def test_side_coverage():
    print("[p] side coverage of the temple band")
    from app.core import garment_cut as gc
    import smoke_garment_fit as fx
    hP, hF = fx.uv_sphere(0.1, (0.0, 1.6, 0.0), nlat=90, nlon=180)
    parts = [(hP, hF)]
    for sx in (1, -1):
        parts.append(fx.uv_sphere(0.02, (sx * 0.105, 1.55, -0.01), nlat=24, nlon=48))
    P = np.vstack([q for q, _ in parts])
    F = np.vstack([f + sum(len(q) for q, _ in parts[:i]) for i, (_, f) in enumerate(parts)])
    head = np.ones(len(P), bool)
    cP, cF = fx.uv_sphere(0.106, (0.0, 1.6, 0.0), nlat=90, nlon=180)

    def cap(y_c, side=None):
        keep = (cP[cF, 1] >= y_c).all(1)
        if side is not None:
            keep &= (side * cP[cF, 0] > 0).all(1)
        return cP, cF[keep]
    full = gc.side_coverage(P, F, head, *cap(1.50))
    print(f"       full cap {full}")
    near("ear top (m)", full["left_band"]["ear_top_y"], 1.566, 0.0011)
    check("cap from y 1.50: both sides 1.0", (full["left"], full["right"]), (1.0, 1.0))
    above = gc.side_coverage(P, F, head, *cap(1.62))
    check("cap from y 1.62 (above the band): 0.0", (above["left"], above["right"]), (0.0, 0.0))
    half = gc.side_coverage(P, F, head, *cap(1.588))
    near("cap from the y 1.5889 ring: 6 / 15 rows (left)", half["left"], 6 / 15, 1 / 15)
    near("cap from the y 1.5889 ring: 6 / 15 rows (right)", half["right"], 6 / 15, 1 / 15)
    one = gc.side_coverage(P, F, head, *cap(1.50, side=-1))
    check("cap on x < 0 only: left 0, right 1, min 0", (one["left"], one["right"], one["min"]), (0.0, 1.0, 0.0))
    check("gate side_coverage", gc.CUT_GATES["side_coverage"], ("min", 0.4, "hair over the temples in the side views"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-cut-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        test_mask()
        test_pad()
        test_register()
        test_cut()
        test_shell()
        test_colour_mend()
        test_outer_wall()
        test_fill_and_majority()
        test_geometry_label()
        test_fill_enclosed()
        test_small_loops()
        test_tinted()
        test_flat_hair()
        test_args()
        test_side_coverage()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
