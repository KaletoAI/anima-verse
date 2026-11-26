#!/usr/bin/env python3
"""Smoke: the footbed of a HOLLOW platform sole (``footwear_insole.footbed_fill``, INSOLE_VERSION 12) and its use in
the insole step (``footwear_source._strip_cap_of``) — 2026-11-26, the black platform boots: the mesher left the
platform an open box, every ray through the opening met the outsole's own skin, ``insole_cover`` 0.17.

Usage:  ./.venv/bin/python scripts/smoke_footwear_footbed.py

No storage, no hub, no server, no Blender: hand-made meshes in metres (mesh axes: x heel -> toe, y up, z across).

The hollow platform shoe (``hollow(stack=False)``), length 0.26, width 0.09 (z +-0.045):
- outsole: underside (facing down) and its skin 2 mm above (facing up) — the heel block x 0 .. 0.07 at y 0 / 0.002,
  the arch x 0.07 .. 0.12 raised to 0.012 / 0.014, the forepart x 0.12 .. 0.26 at 0 / 0.002;
- the platform's outer walls (x = 0, x = 0.26, z = +-0.045) from y 0 to 0.04, and its top only as a SHELF along the
  rim: y 0.04 facing up, x 0 .. 0.007 and 0.245 .. 0.26 at the ends;
- the shelf runs z 0.030 .. 0.045 (15 mm) on both sides;
- the upper standing on the shelf (from y 0.035, tucked 5 mm into the platform): side walls z = +-0.030 up to 0.10,
  the heel wall x = 0.007 up to 0.10, a toe box roof y 0.07 over x 0.16 .. 0.245 (facing up), its toe wall x = 0.245
  and the throat wall x = 0.16 from 0.07 to 0.10; open on top between x 0.007 and 0.16; a collar flange y 0.10
  facing up from z +-0.030 out to +-0.045 (the topline reads walls with |z| >= TOPLINE_SIDE_SHARE 0.75 x 0.045).

Expected, by hand (L = 0.26, AIR = 0.025 L = 6.5 mm, TOL = 0.035 L = 9.1 mm, 240 stations, 83 lateral columns
1.0976 mm apart):

[B1] The shoe as the mesher made it is refused for ``insole_cover``: the only up-facing floor is the skin, and it
     steps 12 mm (> TOL) at x 0.07 and 0.12 — the tracking cannot follow the floor from the arch to the heel or the
     forepart, so less than 0.8 of the outsole is tracked (the real boots: 0.17).
     (The width of the shelf matters: the per-side median needs it in more than half of the outer quarter.)
[B2] footbed_fill: every outsole column meets the skin first (within AIR of the underside); in each station the
     outer quarter of the columns (83 // 4 = 20 per side) reaches z +-0.0241 .. 0.045: the 14 columns with
     |z| >= 0.030 meet the shelf at 0.04 first, the other 6 nothing (the opening) or the toe box roof at 0.07 (the
     forepart) -> the median of each side's first sheets = 0.04, every station; the quadratic through 0.04 is 0.04
     -> heel and toe 0.04. The middle columns are empty between the floor + AIR and the footbed - AIR
     (0.0085 / 0.0205 .. 0.0335). The cross-section at 0.04 crosses the upper's side walls at z = +-0.030 (they run
     0.035 .. 0.10; the platform walls end AT 0.04, the innermost crossing is taken) -> rows from -0.030 + 0.004 L
     to 0.030 - 0.004 L = +-0.02896, 16 points, every vertex at y 0.04, every face facing up, 2 x 15 faces per pair
     of rows, a row for every station whose shelf both sides read (at least 0.9 x 240; the ends lose a few).
[B3] The filled mesh passes every insole gate, is not flipped (the stack is 0.04 at both ends), and its heel seat and
     ball height are 0.04 m (k = 0.26 / L = 1: nominal = raw).
[B4] Not hollow — the same shoe with a REAL stack in the middle (``stack=True``: a sheet at y 0.02 facing up, z +-0.02,
     under the opening) -> footbed_fill None (the middle columns are not empty
     between 0.0085 .. 0.0335). A shoe whose own analysis passes is never filled (``_strip_cap_of`` fills only an
     analysis refused for ``insole_cover``): the flat-floored shoe (``hollow(step=False)``: no arch step, the skin
     tracked as the insole) passes on its own -> no ``footbed``, no changed GLB.
[B5] footwear_source._strip_cap_of on the hollow shoe written as a GLB (float32: the rows are those of
     footbed_fill on the file's own arrays): the analysis passes, ``footbed`` = {added_faces = that footbed's faces,
     stations = its rows, heel_h_m = toe_h_m = 0.04}, a changed GLB is returned whose triangles are the mesh's plus
     the footbed's; no shaft cap was removed (0).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def quads(rects, tile=0.01):
    """(axis, value, (a0, a1), (b0, b1), up) -> (positions, faces); the two other axes in order; tiles of at most
    ``tile`` m; ``up`` True turns a horizontal (axis 1) quad's faces to face +y, False to face -y."""
    P, F = [], []
    for axis, value, (a0, a1), (b0, b1), up in rects:
        others = [i for i in range(3) if i != axis]
        na, nb = max(1, int(np.ceil((a1 - a0) / tile - 1e-9))), max(1, int(np.ceil((b1 - b0) / tile - 1e-9)))
        for i in range(na):
            for j in range(nb):
                ta0, ta1 = a0 + (a1 - a0) * i / na, a0 + (a1 - a0) * (i + 1) / na
                tb0, tb1 = b0 + (b1 - b0) * j / nb, b0 + (b1 - b0) * (j + 1) / nb
                base = len(P)
                for a, b in ((ta0, tb0), (ta1, tb0), (ta1, tb1), (ta0, tb1)):
                    v = [0.0, 0.0, 0.0]
                    v[axis], v[others[0]], v[others[1]] = value, a, b
                    P.append(v)
                # axis 1, others (x, z): (00, 10, 11) has the normal (0, -dx dz, 0) -> down; reversed for up
                tris = [[base, base + 1, base + 2], [base, base + 2, base + 3]]
                if up:
                    tris = [[t[0], t[2], t[1]] for t in tris]
                F += tris
    return np.array(P, np.float64), np.array(F, np.int64)


def hollow(stack=False, step=True):
    L, W, S, U = 0.26, 0.045, 0.04, 0.030
    arch = 0.012 if step else 0.0
    r = [(1, 0.0, (0.0, 0.07), (-W, W), False), (1, 0.002, (0.0, 0.07), (-W, W), True),
         (1, arch, (0.07, 0.12), (-W, W), False), (1, arch + 0.002, (0.07, 0.12), (-W, W), True),
         (1, 0.0, (0.12, L), (-W, W), False), (1, 0.002, (0.12, L), (-W, W), True),
         (0, 0.07, (0.0, arch), (-W, W), False), (0, 0.12, (0.0, arch), (-W, W), False),
         # platform walls and the shelf
         (0, 0.0, (0.0, S), (-W, W), False), (0, L, (0.0, S), (-W, W), False),
         (2, W, (0.0, L), (0.0, S), False), (2, -W, (0.0, L), (0.0, S), False),
         (1, S, (0.0, L), (U, W), True), (1, S, (0.0, L), (-W, -U), True),
         (1, S, (0.0, 0.007), (-U, U), True), (1, S, (0.245, L), (-U, U), True),
         # the upper
         (2, U, (0.007, 0.245), (0.035, 0.10), False), (2, -U, (0.007, 0.245), (0.035, 0.10), False),
         (0, 0.007, (0.035, 0.10), (-U, U), False), (0, 0.245, (0.035, 0.07), (-U, U), False),
         (1, 0.07, (0.16, 0.245), (-U, U), True), (0, 0.16, (0.07, 0.10), (-U, U), False),
         # the collar flange along the top of the side walls, out to the platform's width
         (1, 0.10, (0.007, 0.245), (U, W), True), (1, 0.10, (0.007, 0.245), (-W, -U), True)]
    if stack:
        r.append((1, 0.02, (0.007, 0.245), (-0.02, 0.02), True))
    return quads(r)


def main() -> int:
    from app.core import footwear_insole as fi, footwear_source as fs, glb_mesh

    P, F = hollow()
    plain = fi.analyse_arrays(P, F)
    check(not plain["gates"]["ok"] and any(r.startswith("insole_cover") for r in plain["gates"]["reasons"]),
          f"[B1] the hollow shoe is refused for insole_cover ({plain['gates']['insole_cover']:.3f})")

    bed = fi.footbed_fill(P, F)
    check(bed is not None, "[B2] footbed_fill finds the hollow platform")
    if bed is None:
        print(f"\n{len(FAILS)} FAILED: {FAILS}")
        return 1
    V, T = np.asarray(bed["positions"]), np.asarray(bed["faces"])
    check(abs(bed["heel_h_raw"] - 0.04) < 1e-6 and abs(bed["toe_h_raw"] - 0.04) < 1e-6,
          f"[B2] heel {bed['heel_h_raw']:.6f}, toe {bed['toe_h_raw']:.6f} (want 0.04)")
    check(np.allclose(V[:, 1], 0.04, atol=1e-6), "[B2] every footbed vertex at y 0.04")
    zmax = 0.030 - 0.004 * 0.26
    check(abs(V[:, 2].max() - zmax) < 1e-6 and abs(V[:, 2].min() + zmax) < 1e-6,
          f"[B2] across {V[:, 2].min():.5f} .. {V[:, 2].max():.5f} (want +-{zmax:.5f})")
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    rows = bed["stations"]
    check((n[:, 1] > 0).all() and len(T) == (rows - 1) * 30 and len(V) == rows * 16 and rows >= 216,
          f"[B2] {len(T)} faces facing up over {rows} rows of 16 (want (rows - 1) x 30, rows >= 0.9 x 240)")

    P2 = np.concatenate([P, V])
    F2 = np.concatenate([F, T + len(P)])
    filled = fi.analyse_arrays(P2, F2)
    nom = filled["nominal"]
    check(filled["gates"]["ok"] and not filled["frame"]["flipped"]
          and abs(nom["heel_seat_h_m"] - 0.04) < 1e-4 and abs(nom["insole_ball_h_m"] - 0.04) < 1e-4,
          f"[B3] filled: ok {filled['gates']['ok']} {filled['gates']['reasons']}, flipped {filled['frame']['flipped']}, "
          f"seat {nom['heel_seat_h_m']}, ball {nom['insole_ball_h_m']}")

    Ps, Fs = hollow(stack=True)
    check(fi.footbed_fill(Ps, Fs) is None, "[B4] a real stack in the middle: no footbed")

    with tempfile.TemporaryDirectory() as tmp:
        for name, (Pm, Fm), want in (("hollow", (P, F), True), ("flat floor", hollow(step=False), False)):
            path = Path(tmp) / f"{name}.glb"
            path.write_bytes(glb_mesh.static_glb(Pm, Fm, np.zeros((len(Pm), 2))))
            res, removed, blob, _p, _f = fs._strip_cap_of(path)
            if not want:
                check(res["gates"]["ok"] and "footbed" not in res and blob is None and removed == 0,
                      f"[B4] {name}: passes on its own ({res['gates']['ok']}), not filled")
                continue
            fb = res.get("footbed") or {}
            back = glb_mesh.static_arrays(blob)[1] if blob is not None else np.zeros((0, 3))
            # the GLB holds float32: the footbed of the file's own arrays
            p32, f32 = glb_mesh.static_arrays(path.read_bytes())[:2]
            own = fi.footbed_fill(np.asarray(p32, np.float64).reshape(-1, 3), np.asarray(f32).reshape(-1, 3))
            T = own["faces"]
            check(res["gates"]["ok"] and removed == 0 and fb.get("added_faces") == len(T)
                  and fb.get("stations") == own["stations"] and abs(fb.get("heel_h_m", 0) - 0.04) < 1e-4
                  and abs(fb.get("toe_h_m", 0) - 0.04) < 1e-4 and len(np.asarray(back).reshape(-1, 3)) == len(F) + len(T),
                  f"[B5] {name}: ok {res['gates']['ok']}, footbed {fb}, triangles {len(np.asarray(back).reshape(-1, 3))}")

    print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
