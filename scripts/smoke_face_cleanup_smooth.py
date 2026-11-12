#!/usr/bin/env python3
"""Face cleanup version 4 — pockets closed, spikes smoothed, the eyeball kept (``face_cleanup._smooth_face``) — on a
synthetic head, expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_smooth.py

No world, no server, no hub, no Blender. The fixture is the head of ``smoke_face_cleanup.py`` (sphere R = 0.055 units
= 95.9 mm at y = 0.42, one millimetre = 0.975 / 1700 units, 160 rings x 320 segments: ~1.9 mm between neighbouring
vertices on the face; lash paint ellipses 22 x 7 mm at x = +-34.9 mm, y = 0.415; lips painted 20 x 6 mm at 1.0 eye
separation below the eye line) WITHOUT its lash ridge, carrying three defects:

- LEFT eye (x = +0.02): a POCKET — the front vertices within 4 mm of the eye centre pushed 8 mm back along -z (the
  view axis: the floor is in plain sight, its walls stand edge-on to the rays);
- RIGHT eye (x = -0.02): an EYEBALL cap — the front vertices within 6 mm pushed in by 2.2 + 0.8 (r / 6 mm)^2 mm (the
  centre 2.2 mm below the sphere like Lirien's eyeball, the rim 3.0 mm: convex, bulging toward the viewer);
- a SPIKE on the right eye's upper lid ring: the front vertex nearest (x = -0.02, y = eye line + 10 mm) pushed 3 mm
  IN — a dent. (A single vertex standing OUT of the lid surface is a flap the fold of version 2 already folds; the
  smoothing is for what the fold leaves.)

The fold runs first, unchanged since b6476661: around the pocket's rim it folds a few vertices (the lid surface it
fits dips into the pit, so the rim reads proud) — the expectations below are therefore stated against the OLD code's
output, which is exactly what the fold alone does.

Hand-derived expectations (constants of face_cleanup):
- POCKET: the closing disc (DEPRESSION_CLOSE_MM 5) is wider than the 8 mm pit, so the pit is a depression; the
  membrane its ring spans lies on the sphere (within the sphere's sag over the pit, 4^2 / (2 * 95.9) = 0.08 mm), so
  the floor reads ~7.4 mm (8 mm along z, measured along the radius) below it > POCKET_MM 3.5 -> a pocket, enclosed by
  the region. Its target is spanned by the pocket's own ring: the cells around it that are NOT pockets (the wall
  cells) read at most 3.5 mm below the membrane, so by the maximum principle every lifted floor vertex ends at most
  3.5 mm under the sphere — plus half a millimetre for the 1 mm cells (SMOOTH_CELL_MM) the membrane is sampled on —
  so >= -4.0 mm, and rose at least 7.4 - 4.0 = 3.4 mm; the lift (<= 8 mm) is under the cap MOVE_CAP_SEPARATION *
  69.7 mm = 10.5 mm. The rays see a floor vertex through its NEAREST cell; a floor vertex at the very foot of the wall
  whose nearest cell centre already lies outside the floor polygon reads the rim, counts as unseen and stays where it
  is (at most one of the 16 here). Re-measured against the same membrane no visible vertex is left in a pocket.
- EYEBALL: the cap lies 2.2 .. 3.0 mm below the sphere; the membrane over it never rises above its ring on the
  sphere (maximum principle), so no cell reads more than 3.0 + 0.19 (sag over 12 mm) = 3.19 mm < 3.5 below it: not a
  pocket, and its smooth surface (dihedral at the 3 mm rim step atan(3 / 1.9) = 58 degrees < SPIKE_DEG 120,
  curvature ratio well under SPIKE_RATIO) holds no spike — every cap vertex keeps its exact bytes.
- SPIKE: the dent lies 3 mm below a ring of edges ~1.9 mm (its own edges sqrt(1.9^2 + 3^2) = 3.55 mm): umbrella
  curvature 3 / 3.55 = 0.85 > SPIKE_RATIO 0.75; its neighbours see it as one of six ring members (0.5 mm over
  ~2.0 mm, 0.25) and stand out not. Only the dent moves: each Taubin pass keeps (1 - 0.5)(1 + 0.53) = 0.765 of its
  depth below the fixed ring mean, 10 passes 0.765^10 = 0.069 -> 3 * 0.069 = 0.21 mm below the ring mean (which lies
  ~0.02 mm under the sphere): -0.40 .. -0.15 mm after, moved 2.6 .. 2.9 mm; then it no longer stands out, so the
  next round smooths nothing. Spikes: the right eye counts 1 before, 0 after.
- NOTHING ELSE: against the old code's output the moved vertices are exactly the lifted pocket floor plus the dent;
  every vertex outside the eye and mouth regions keeps its exact POSITION and NORMAL bytes; vertex count, order (index
  buffer) and UVs are unchanged; normals are recomputed (unit length) only where a triangle moved; the result passes
  ``validate_source``; the mouth region (a smooth sphere) is skipped; a second run gives the same bytes.
- OLD CODE: ``app/core/face_cleanup.py`` at b6476661 (the base of this change) leaves the pocket floor and the dent
  where they are — the proof that this smoke tests the new step.
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
BASE_COMMIT = "b6476661"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


R, HEAD_Y, EYE_Y, EYE_X, MM = base.R, base.HEAD_Y, base.EYE_Y, base.EYE_X, base.MM


def build():
    """The head with the three defects; returns ``(glb, P, F, U, masks)``."""
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
    radial = (P - np.array([0, HEAD_Y, 0])) / R
    r_left = np.hypot(P[:, 0] - EYE_X, P[:, 1] - EYE_Y)
    r_right = np.hypot(P[:, 0] + EYE_X, P[:, 1] - EYE_Y)
    pocket = front & (r_left < 4 * MM)
    cap = front & (r_right < 6 * MM)
    target = np.array([-EYE_X, EYE_Y + 10 * MM])
    apex = np.zeros(len(P), bool)
    apex[np.flatnonzero(front)[np.argmin(np.hypot(P[front, 0] - target[0], P[front, 1] - target[1]))]] = True
    offset = np.zeros(len(P))
    offset[cap] = -(2.2 + 0.8 * (r_right[cap] / (6 * MM)) ** 2) * MM
    offset[apex] = -3 * MM
    P = P + radial * offset[:, None]
    P[pocket, 2] -= 8 * MM
    box = np.array([(sx * 0.12, y, sz * 0.06) for y in (base.BOTTOM, 0.33) for sx in (-1, 1) for sz in (-1, 1)])
    box_f = np.array([(0, 1, 2), (1, 3, 2), (4, 6, 5), (5, 6, 7), (0, 4, 1), (1, 4, 5),
                      (2, 3, 6), (3, 7, 6), (0, 2, 4), (2, 6, 4), (1, 5, 3), (3, 5, 7)], np.int64) + len(P)
    P = np.vstack([P, box])
    U = np.vstack([U, np.full((8, 2), (0.5, 0.95))])
    F = np.vstack([F, box_f])
    N = P - np.array([0, HEAD_Y, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    pad = np.zeros(8, bool)
    masks = {"pocket": np.concatenate([pocket, pad]), "cap": np.concatenate([cap, pad]),
             "apex": np.concatenate([apex, pad])}
    return base.pack(P, N, U, F, base.texture_png(True)), P, F, U, masks


def sphere_height_mm(Q):
    """Radial height of each point above the undisturbed sphere, in mm."""
    return (np.linalg.norm(Q - np.array([0, HEAD_Y, 0]), axis=1) - R) / MM


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
    from app.core.model_overview import _face_cleanup_step

    glb, _P, _F, _U, masks = build()
    pocket, cap, apex = masks["pocket"], masks["cap"], masks["apex"]
    check(validate_source(glb)["ok"], "fixture passes validate_source")
    check(pocket.sum() >= 10 and cap.sum() >= 25 and apex.sum() == 1,
          f"fixture: {int(pocket.sum())} pocket floor, {int(cap.sum())} eyeball cap, {int(apex.sum())} apex vertices")

    out, record = fc.clean_face(glb)
    old = old_module()
    out_old, record_old = old.clean_face(glb)
    smooth = record.get("smooth") or {}
    check(record["version"] == 4 and smooth.get("status") == "applied", f"version 4, smoothing applied: {smooth.get('status')}")
    regions = {r["region"]: r for r in smooth.get("regions") or []}
    left, right, mouth = regions.get("eye_left") or {}, regions.get("eye_right") or {}, regions.get("mouth") or {}
    P1, F1, U1, _img1, *_ = static_arrays(out)
    P0, F0, U0, _img0, *_ = static_arrays(glb)
    Po, *_ = static_arrays(out_old)
    folded = np.any(Po != P0, axis=1)
    check(not (folded & (pocket | cap | apex)).any(),
          f"the fold (old code) moves {int(folded.sum())} rim vertices, none of the pocket floor, cap or dent")
    check(np.array_equal(P1[folded], Po[folded]), "the folded vertices keep the fold's positions")
    h0, h1 = sphere_height_mm(P0), sphere_height_mm(P1)
    new = np.any(P1 != Po, axis=1)

    # Pocket.
    lifted = pocket & new
    pb = (left.get("pockets") or {}).get("before") or {}
    pa = (left.get("pockets") or {}).get("after") or {}
    check(lifted.sum() >= pocket.sum() - 1, f"pocket floor lifted: {int(lifted.sum())} of {int(pocket.sum())} (at most one unseen)")
    check(pb.get("vertices") == int(lifted.sum()) and pb.get("area_mm2", 0) > 30,
          f"left eye: pocket before {pb.get('vertices')} visible vertices, {pb.get('area_mm2')} mm^2 (> 30)")
    check(pa.get("vertices") == 0, f"left eye: no visible vertex left in a pocket ({pa.get('vertices')}, {pa.get('area_mm2')} mm^2)")
    rise = (P1[lifted, 2] - P0[lifted, 2]) / MM
    check(np.all(h1[lifted] >= -4.0) and np.all(rise >= 3.4) and np.all(rise <= 8.0),
          f"lifted floor ends {h1[lifted].min():.2f} .. {h1[lifted].max():.2f} mm on the sphere (>= -4.0), "
          f"rose {rise.min():.2f} .. {rise.max():.2f} mm (3.4 .. 8.0)")
    # Eyeball.
    check(np.array_equal(P1[cap], P0[cap]), "right eye: the eyeball cap keeps its exact bytes")
    rb = (right.get("pockets") or {}).get("before") or {}
    check(rb.get("vertices") == 0, f"right eye: the eyeball is no pocket ({rb.get('vertices')} vertices, {rb.get('area_mm2')} mm^2)")
    # Spike.
    sp = right.get("spikes") or {}
    check(sp.get("before") == 1 and sp.get("after") == 0, f"right eye: spikes {sp.get('before')} -> {sp.get('after')} (1 -> 0)")
    shift = float(np.linalg.norm(P1[apex] - P0[apex]) / MM)
    check(-0.40 <= float(h1[apex][0]) <= -0.15 and 2.6 <= shift <= 2.9,
          f"dent {h0[apex][0]:.2f} -> {h1[apex][0]:.2f} mm on the sphere (-0.40 .. -0.15), moved {shift:.2f} mm (2.6 .. 2.9)")
    # Nothing else.
    check(np.array_equal(new, lifted | apex), f"moved beyond the fold = lifted floor + dent ({int(new.sum())} of {int((lifted | apex).sum())})")
    check(mouth.get("status") == "skipped" and mouth.get("moved_vertices") == 0, f"mouth region: {mouth.get('status')} ({mouth.get('reason')})")
    from app.core.glb_mesh import _parse
    n0 = _normals(_parse(glb, "S"))
    n1 = _normals(_parse(out, "S"))
    outside = np.ones(len(P0), bool)
    for cx in (EYE_X, -EYE_X):
        outside &= ((P0[:, 0] - cx) / (34 * MM)) ** 2 + ((P0[:, 1] - EYE_Y) / (27 * MM)) ** 2 >= 1
    outside &= ~((np.abs(P0[:, 0]) < 31 * MM) & (np.abs(P0[:, 1] - base.MOUTH_Y) < 17 * MM))
    check(np.array_equal(P1[outside], P0[outside]) and np.array_equal(n1[outside], n0[outside]),
          f"outside the regions: positions and normals byte-identical ({int(outside.sum())} vertices)")
    changed_n = np.any(n1 != n0, axis=1)
    check(changed_n.any() and np.allclose(np.linalg.norm(n1[changed_n], axis=1), 1.0, atol=1e-5),
          f"normals recomputed where triangles moved: {int(changed_n.sum())}, unit length")
    check(len(P1) == len(P0) and np.array_equal(F1, F0) and np.array_equal(U1, U0), "vertex count, index order and UVs unchanged")
    check(validate_source(out)["ok"], "the result passes validate_source")
    check(smooth["moved_vertices"] == int(new.sum()) and smooth["displacement_max_mm"] >= 3.4,
          f"record totals: {smooth['moved_vertices']} moved, max {smooth['displacement_max_mm']} / p95 {smooth['displacement_p95_mm']} mm")
    row = _face_cleanup_step({"face_cleanup": record})
    check("smoothing:" in row["detail"] and row["numbers"].get("spikes_after") == 0, f"overview row: {row['detail']}")
    check("smoothing:" in fc.summary(record), f"summary: {fc.summary(record)}")
    again, _rec2 = fc.clean_face(glb)
    check(again == out, "deterministic: a second run gives the same bytes")

    # Old code: nothing of this happens.
    check(np.array_equal(Po[pocket], P0[pocket]) and np.array_equal(Po[apex], P0[apex]) and "smooth" not in record_old,
          f"face_cleanup at {BASE_COMMIT} leaves the pocket floor and the dent where they are")

    print()
    print("FAILED" if FAILS else "ALL OK", f"({len(FAILS)} failures)")
    sys.exit(1 if FAILS else 0)


def _normals(parsed):
    from app.core.glb_mesh import accessor_array
    prim = parsed["gltf"]["meshes"][0]["primitives"][0]
    return np.asarray(accessor_array(parsed, prim["attributes"]["NORMAL"]), np.float32)


if __name__ == "__main__":
    main()
