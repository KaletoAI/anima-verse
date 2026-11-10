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
[d] cut_hair (cut): registration p95 0.0 cm (the non-hair vertices ARE B's vertices); label = the 2401 cap
    vertices, every outer-sheet vertex at theta <= 60 deg + one grid step (the edge rings feather inward, never
    outward); hairline: 2D last hair row 143 -> y_of_row(143) = 0.506 + (594 - 143) x 0.001 = 0.957, 3D the
    theta-60 ring y 0.956 -> |0.001| x 1.7 = 0.17 cm (< 0.4: +-1 px of morphology); holes 0; hair area
    2 pi r^2 (1 - cos 60) = pi (0.112 x 1.7)^2 = 1138.8 cm^2 (+-2 %: chordal grid); the result is ONE closed
    component (welded: no open edge); gates pass; fit params (0.006 m, SPREAD_M).
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


def haired_truth():
    import smoke_garment_fit as fx
    hP, hF, rows, nlon = head_grid(lambda i: 0.112 if i <= 20 else 0.100)
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


def images():
    yy, xx = np.mgrid[0:H, 0:W]
    x = (xx + 0.5 - 512) / 1000.0
    y = 1.0 - (yy + 0.5 - 100) / 1000.0
    head = x ** 2 + (y - 0.9) ** 2 <= 0.1 ** 2
    torso = (np.abs(x) <= 0.12) & (y >= 0) & (y <= 0.8)
    cap = (x ** 2 + (y - 0.9) ** 2 <= 0.112 ** 2) & (y >= 0.956)
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
    check("ok", (res.ok, res.reasons), (True, []))
    near("registration p95 (cm)", res.metrics["registration_p95_cm"], 0.0, 0.05)
    check("label = the 2401 cap vertices", res.report["label"]["vertices"], 2401)
    near("hairline (cm)", res.metrics["hairline_cm"], 0.17, 0.25)
    check("holes", res.metrics["label_holes"], 0)
    near("hair area (cm2)", res.metrics["hair_area_cm2"], 1138.8, 1138.8 * 0.02)
    check("closed: no open edge, one component", (res.report["closed"]["open_edges"],
                                                  res.report["closed"]["components"]), (0, 1))
    check("fit params", (res.clearance_m, res.spread_m), (0.006, gf.SPREAD_M))
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
    check("ok", (res.ok, res.reasons), (True, []))
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
        test_args()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
