#!/usr/bin/env python3
"""Face cleanup version 6 — a lump beside the mouth is lowered onto the skin around it, the lips are left alone
(``face_cleanup._bumps`` / ``_lower_bumps``) — on a synthetic head, expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_bump.py

No world, no server, no hub, no Blender. The fixture is the head of ``smoke_face_cleanup.py`` (sphere R = 0.055 units
= 95.9 mm centred at y = 0.42, one millimetre = 0.975 / 1700 units, 160 rings x 320 segments: ~1.9 mm between
neighbouring vertices on the face; lash paint ellipses 22 x 7 mm at x = +-34.9 mm, y = 0.415) WITHOUT its lash ridge,
with Lirien-sized lip paint (semi-axes 14 x 5 mm around (0, MOUTH_Y = 0.375); her paint reads 15 mm half width) and
carrying the defect of Lirien's mesher roll (hub job 1c6fd645: two ~12 mm lumps ~10-11 mm proud at the mouth corners)
next to two features that must stay:

- two LUMPS at x = +-32 mm, 2 mm above the lip centre: every front vertex within 5 mm of that point pushed along +z
  (the view axis of the mouth region: its centre lies on the mid-plane) by 10 (1 - (r / 5 mm)^2) mm — a dome 10 mm
  across, 10 mm high;
- a small BUMP on the mid-line 10 mm above the lip centre, inside the lip box (Kira's upper-lip tubercle,
  2026-11-20): the front vertices within 3.5 mm pushed along +z by 6 (1 - (r / 3.5 mm)^2) mm;
- the painted LIPS themselves: a ridge, the front vertices inside the paint ellipse pushed along +z by
  4 (1 - d2) mm (d2 = the paint ellipse's own normalised radius squared).

The mouth sits 78.5 mm below the sphere's centre, so the face there is steep and strongly curved — harder than a real
cheek. At a lump (x = 32, y = -76.5 mm from the centre): z = sqrt(95.9^2 - 32^2 - 76.5^2) = 48.2 mm, slopes
dz/dx = -0.66 and dz/dy = 1.59, second derivatives -(R^2 - y^2) / z^3 = -0.030 and -(R^2 - x^2) / z^3 = -0.073 / mm
(Laplacian -0.103 / mm), third derivative along y 3 |y| (R^2 - x^2) / z^5 = 0.0072 / mm^2.

Hand-derived expectations (constants of face_cleanup; MM = 1 mm of the 1.70 m reference):

- LIP PROTECTION: the paint's half axes are its 3..97 percentile extents — for a filled ellipse the 3 % tail starts at
  0.86 of the semi-axis: ~12 x ~4.3 mm; the box widened by LIP_PROTECT_MM 6: |x| < ~18, |y| < ~10.3 mm. The painted
  vertices dilated by 6 mm reach at most 14 + sqrt(6^2 - 2^2) = 19.7 mm at the lumps' height (y = +2), one cell more
  (``near_protected``) 20.7 mm.
- LUMP PATCH: the opening (BUMP_OPEN_MM 16, a disc of radius 8 cells) cannot fit inside the 10 mm dome, so a seed
  exists at its top. The patch (seed + BUMP_SKIRT_MM 2) grows by its foot while a rim cell stands more than
  FLAP_FOOT_MM 1 above the membrane of its ring: the dome is under 1 mm beyond r = 5 sqrt(0.9) = 4.7 mm, so the
  growth stops within a cell of the dome's edge: patch radius <= 5 + 1 (last cell) + 1 (8-neighbour step) + 0.7 (cell
  rounding) = 7.7 mm. Inner edge x >= 32 - 7.7 = 24.3 > 20.7: clear of the protection. Outer corner: (39.7 / 42)^4 +
  (9.7 / 16)^4 = 0.80 + 0.14 = 0.93 < 1: inside version 6's mouth region (|x / 42|^4 + |y / 16|^4 < 1); version 5's
  ellipse (30 x 16 mm) ended at 30 mm and had no bump rule. No ray misses there (the silhouette lies past x = 44).
- LUMP CORE: the harmonic membrane over the patch sags under the sphere by at most |Laplacian| r^2 / 4 = 0.103 *
  7.7^2 / 4 = 1.5 mm, so the core (> BUMP_MM 3 above it) is the part of the dome higher than 1.5..3 mm: r < 4.2..4.6,
  at most 2 * 4.6 + 1.4 (rounding) = 10.6 mm across <= BUMP_ACROSS_MM 15. It stands ~10 mm above the membrane: a BUMP.
  Count: 2.
- TARGET: the thin plate over the patch reproduces any quadratic surface, so it misses the sphere only by the cubic
  term: 0.0072 * 7.7^3 / 6 = 0.55 mm at the patch's edge, where the plate is pinned to the ring — inside well under
  that; say 0.5 mm. The record's ``before.max_mm`` (core height above the target) is the dome's peak cell, within
  0.7 mm of the centre: 10 (1 - (0.7 / 5)^2) = 9.8 .. 10, +- 0.5 for the plate: 10 +- 0.6.
- LOWERED: every patch vertex above the target goes down along the view normal onto it; the drop (<= 10.5 mm) stays
  under the cap MOVE_CAP_SEPARATION * 69.7 mm = 10.5 mm (beyond_cap 0). After, every dome vertex lies within 0.5 mm of
  the sphere, every dome vertex higher than 0.5 mm moved, and the record's ``after.max_mm`` (the cores re-measured
  against the same target) is < 1.0 — the acceptance "lumps from ~11 mm to < 1 mm". Sphere vertices inside the patch
  (r 5..7.7 mm) move only if above the plate: by at most 0.5 mm.
- TUBERCLE: its core (6 (1 - (r / 3.5)^2) > 3: r < 2.5 mm, y = 7.5..12.5) lies in the lip box (|y| < ~10.3) and in the
  dilated paint (up to 5 + 6 = 11 mm on the mid-line) but for a sliver above y ~11, whose patch touches the protection:
  LEFT ALONE (``left_alone.protected`` >= 1); every one of its vertices keeps its exact bytes.
- LIPS: the ridge is all inside the protection — no seed there; every lip vertex keeps its exact bytes. A ridge 4 mm
  high over 10 mm is no pocket and its dihedrals (atan(4 / 5) = 39 degrees at most) no spike.
- NOTHING ELSE: every vertex that moved lies within 7.7 mm (+ 0.5 for its own nearest cell) of a lump centre; vertex
  count, index buffer and UVs are unchanged; normals are unit length; the result passes ``validate_source``; a second
  run of the cleanup on the result finds no bump; the record says version 6.
- OLD CODE: ``app/core/face_cleanup.py`` at 76aa5cb1 (the base of this change, version 5) leaves every dome vertex
  where it is — the proof that this smoke tests the new rule.
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_face_cleanup as base  # noqa: E402  (fixture helpers; its main() runs only as a script)

FAILS = []
BASE_COMMIT = "76aa5cb1"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


R, HEAD_Y, MOUTH_Y, MM = base.R, base.HEAD_Y, base.MOUTH_Y, base.MM
LUMP_X, LUMP_DY, LUMP_R, LUMP_H = 32.0, 2.0, 5.0, 10.0
TUB_DY, TUB_R, TUB_H = 10.0, 3.5, 6.0
LIP_A, LIP_B, LIP_H = 14.0, 5.0, 4.0


def paint_class(x, y):
    """The fixture's paint: the lash ellipses of ``smoke_face_cleanup`` and Lirien-sized lips (semi-axes 14 x 5 mm;
    her paint reads 15 mm half width) — the base fixture's 20 mm lips would reach the lumps' patches."""
    for cx in (base.EYE_X, -base.EYE_X):
        if ((x - cx) / (22 * MM)) ** 2 + ((y - base.EYE_Y) / (7 * MM)) ** 2 < 1:
            return base.LASH
    if (x / (LIP_A * MM)) ** 2 + ((y - MOUTH_Y) / (LIP_B * MM)) ** 2 < 1:
        return base.LIPS
    return base.SKIN


base.paint_class = paint_class      # texture_png reads the module's paint_class


def build():
    """The head with the lumps, the tubercle and the lip ridge; returns ``(glb, P, masks)``."""
    rings, segments = 160, 320
    P, U = [], []
    for i in range(rings + 1):
        theta = np.pi * i / rings
        for j in range(segments):
            phi = 2 * np.pi * j / segments
            x, y, z = R * np.sin(theta) * np.sin(phi), HEAD_Y + R * np.cos(theta), R * np.sin(theta) * np.cos(phi)
            P.append((x, y, z))
            U.append(base.planar_uv(x, y, z >= 0))
    P, U = np.array(P, np.float64), np.array(U, np.float64)
    F = []
    for i in range(rings):
        for j in range(segments):
            a, b = i * segments + j, i * segments + (j + 1) % segments
            c, d = (i + 1) * segments + j, (i + 1) * segments + (j + 1) % segments
            F += [(a, c, b), (b, c, d)]
    F = np.array(F, np.int64)
    front = P[:, 2] > 0
    xm, ym = P[:, 0] / MM, (P[:, 1] - MOUTH_Y) / MM
    lump = np.zeros(len(P), bool)
    lift = np.zeros(len(P))
    for sx in (1, -1):
        r = np.hypot(xm - sx * LUMP_X, ym - LUMP_DY)
        m = front & (r < LUMP_R)
        lump |= m
        lift[m] = LUMP_H * (1 - (r[m] / LUMP_R) ** 2)
    r = np.hypot(xm, ym - TUB_DY)
    tub = front & (r < TUB_R)
    lift[tub] = TUB_H * (1 - (r[tub] / TUB_R) ** 2)
    d2 = (xm / LIP_A) ** 2 + (ym / LIP_B) ** 2
    lips = front & (d2 < 1)
    lift[lips] = LIP_H * (1 - d2[lips])
    P[:, 2] += lift * MM
    box = np.array([(sx * 0.12, y, sz * 0.06) for y in (base.BOTTOM, 0.33) for sx in (-1, 1) for sz in (-1, 1)])
    box_f = np.array([(0, 1, 2), (1, 3, 2), (4, 6, 5), (5, 6, 7), (0, 4, 1), (1, 4, 5),
                      (2, 3, 6), (3, 7, 6), (0, 2, 4), (2, 6, 4), (1, 5, 3), (3, 5, 7)], np.int64) + len(P)
    P = np.vstack([P, box])
    U = np.vstack([U, np.full((8, 2), (0.5, 0.95))])
    F = np.vstack([F, box_f])
    N = P - np.array([0, HEAD_Y, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    pad = np.zeros(8, bool)
    dome = np.concatenate([lift * lump, np.zeros(8)])
    masks = {"lump": np.concatenate([lump, pad]), "tub": np.concatenate([tub, pad]),
             "lips": np.concatenate([lips, pad]), "dome": dome}
    return base.pack(P, N, U, F, base.texture_png(True)), P, masks


def sphere_z_mm(Q):
    """Height along +z above the undisturbed sphere at each point's (x, y), in mm."""
    rho2 = Q[:, 0] ** 2 + (Q[:, 1] - HEAD_Y) ** 2
    return (Q[:, 2] - np.sqrt(np.maximum(R * R - rho2, 0.0))) / MM


def old_module():
    """``face_cleanup`` as of BASE_COMMIT, loaded from git under another name."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/face_cleanup.py"],
                            check=True, capture_output=True, text=True).stdout
    path = Path(tempfile.mkdtemp()) / "face_cleanup_old.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("face_cleanup_old", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import static_arrays
    from app.core.mesh_source import validate_source

    glb, _P, masks = build()
    lump, tub, lips, dome = masks["lump"], masks["tub"], masks["lips"], masks["dome"]
    check(validate_source(glb)["ok"], "fixture passes validate_source")
    check(lump.sum() >= 30 and tub.sum() >= 6 and lips.sum() >= 60,
          f"fixture: {int(lump.sum())} lump, {int(tub.sum())} tubercle, {int(lips.sum())} lip vertices")

    out, record = fc.clean_face(glb)
    smooth = record.get("smooth") or {}
    check(record["version"] == 6, f"version {record['version']}")
    mouth = {r["region"]: r for r in smooth.get("regions") or []}.get("mouth") or {}
    bumps = mouth.get("bumps") or {}
    check(mouth.get("located_by") == "paint", f"mouth located by {mouth.get('located_by')}")
    check(bumps.get("count") == 2, f"bumps found: {bumps.get('count')} (expected 2), left alone: {bumps.get('left_alone')}")
    check((bumps.get("left_alone") or {}).get("protected", 0) >= 1,
          f"the tubercle touches the lip protection and is left alone: {bumps.get('left_alone')}")
    before_max = (bumps.get("before") or {}).get("max_mm")
    check(before_max is not None and abs(before_max - 10.0) <= 0.6, f"bump height before {before_max} mm (10 +- 0.6)")
    after_max = (bumps.get("after") or {}).get("max_mm")
    check(after_max is not None and after_max < 1.0, f"bump height after {after_max} mm (< 1.0)")
    check(bumps.get("beyond_cap_vertices") == 0, f"none clamped by the cap: {bumps.get('beyond_cap_vertices')}")

    P0, F0, U0, *_ = static_arrays(glb)
    P1, F1, U1, *_ = static_arrays(out)
    moved = np.any(P1 != P0, axis=1)
    h1 = sphere_z_mm(P1)
    check(np.abs(h1[lump]).max() <= 0.5, f"every lump vertex within 0.5 mm of the sphere after: max |h| {np.abs(h1[lump]).max():.3f} mm")
    tall = lump & (dome > 0.5)
    check(moved[tall].all(), f"every lump vertex higher than 0.5 mm moved: {int(moved[tall].sum())} of {int(tall.sum())}")
    xm, ym = P0[:, 0] / MM, (P0[:, 1] - MOUTH_Y) / MM
    r = np.minimum(np.hypot(xm - LUMP_X, ym - LUMP_DY), np.hypot(xm + LUMP_X, ym - LUMP_DY))
    check(r[moved].max() <= 8.2, f"every moved vertex within 8.2 mm of a lump centre: max {r[moved].max():.2f} mm")
    shift = np.linalg.norm(P1 - P0, axis=1) / MM
    others = moved & ~lump
    check(not others.any() or shift[others].max() <= 0.5,
          f"{int(others.sum())} sphere vertices inside the patches moved by at most 0.5 mm: "
          f"{shift[others].max() if others.any() else 0:.3f} mm")
    check(not moved[tub].any() and not moved[lips].any(), "tubercle and lips keep their exact bytes")
    check(len(P1) == len(P0) and np.array_equal(F1, F0) and np.array_equal(U1, U0), "vertex count, indices and UVs unchanged")
    from app.core.glb_mesh import _parse
    _prims, _P, _F, _U, N1, _o = fc._body(_parse(out, "Source"))
    check(np.allclose(np.linalg.norm(N1, axis=1), 1.0, atol=1e-4), "normals unit length")
    check(validate_source(out)["ok"], "result passes validate_source")
    line = fc.smooth_line(smooth)
    check("2 bump(s)" in line, f"summary line: {line}")

    _again, record2 = fc.clean_face(out)
    m2 = {r["region"]: r for r in (record2.get("smooth") or {}).get("regions") or []}.get("mouth") or {}
    check((m2.get("bumps") or {}).get("count") == 0, f"a second run finds no bump: {m2.get('bumps')}")

    old = old_module()
    out_old, _record_old = old.clean_face(glb)
    Pold, *_ = static_arrays(out_old)
    check(np.array_equal(Pold[lump], P0[lump]), f"old code ({BASE_COMMIT}) leaves every lump vertex where it is")

    if FAILS:
        print(f"FAILED ({len(FAILS)} failures)")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
