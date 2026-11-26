#!/usr/bin/env python3
"""Smoke: the bounded width taper (``footwear_fit.TAPER_SLOPE_MAX`` / ``TAPER_SHARE_SLOPE_MAX``) and the shoe's inside
seen from outside (``footwear_cut.inside_seen``, gate ``inside_seen_mm2``) — fit version 24, 2026-11-26.

Usage:  ./.venv/bin/python scripts/smoke_footwear_inside_seen.py

No storage, no hub, no server, no Blender: pure functions on hand-made arrays. The proof against the old code reads
``width_taper`` from main 8bea143b2 (``git show``; skipped with a note when git or that commit is not there).

Expected, by hand:

[I1] _bounded_back([0, 0.5, 0], x = [0, 1, 2], slope 0.1): from the last station backward, each value clipped to its
     successor +- 0.1 x 1: v2 = 0; v1 = clip(0.5, -0.1, 0.1) = 0.1; v0 = clip(0, 0.0, 0.2) = 0 -> [0, 0.1, 0].
     _majorant([0.8, 0.8, 1.0], x = [0, 0.01, 0.02], slope 5): max_j (v_j - 5 |x_i - x_j|):
     x0: max(0.8, 0.75, 0.9) = 0.9; x1: max(0.75, 0.8, 0.95) = 0.95; x2: 1.0 -> [0.9, 0.95, 1.0].
[I2] width_taper, stations 0 .. 5 (raw, k 1, width factor 1.25, ball at 4, clearance 0.002), insole -0.03 .. 0.03
     everywhere (middle m = 0, half 0.03), the foot's half 0.02 (x 1.25 = 0.025 in the shoe) at stations 1, 2, 3,
     its middle at station 2 at 0.5 (a stray reading), unmeasured at 0 and 5:
     need0 = (0.025 + 0.002) / 0.03 = 0.9 -> clamped to 1 -> share0 = 1 / 1.25 = 0.8 at 0 .. 3 (0 takes the first
     measured), 1 from the ball; w = (1 - 0.8) / (1 - 0.8) = 1 behind the ball.
     - main 8bea143b2: shift = 0.5 at station 2 (a step of 0.5 a unit), rest 0, share stays 0.8 ->
       share [0.8, 0.8, 0.8, 0.8, 1.0], centre [0, 0, 0.5, 0, 0];
     - now: the shift bounded backward from the ball by 0.1 a unit -> [0, 0, 0.1, 0, 0, 0]; at station 2 the rest
       |0.5 - 0.1| x 1.25 = 0.5, need1 = (0.025 + 0.5 + 0.002) / (0.03 x 1.25) = 14.05 -> x 1.25 clamped to 1.25 ->
       share 1 there (the walls stay wide where the shift does not reach the foot), running maximum ->
       share [0.8, 0.8, 1.0, 1.0, 1.0], centre [0, 0, 0.1, 0, 0], mid all 0, min_factor 0.8 x 1.25 = 1.0.
       The majorant (reach 0.03 -> 0.2 / 0.03 = 6.667 a unit) changes nothing at a station spacing of 1.
[I3] the share's majorant, stations 0, 0.01, .., 0.05 (ball 0.04), the foot's half 0.02 at 1, 2 and 0.024 at 3
     (x 1.25 = 0.03), middles 0: share0 = 0.8, 0.8, 0.8, (0.03 + 0.002) / 0.03 / 1.25 = 0.853333, 1 from the ball;
     the shift 0 -> share as share0.
     - main 8bea143b2: [0.8, 0.8, 0.8, 0.853333, 1.0];
     - now, reach 0.03 (no shoe given: the widest insole half): slope 6.6667 a unit: station 3 from the ball
       1 - 0.066667 = 0.933333; station 2: 1 - 0.133333 = 0.866667; station 1: max(0.8, 1 - 0.2) = 0.8; station 0: 0.8
       -> [0.8, 0.8, 0.866667, 0.933333, 1.0];
     - now, a shoe point at x 0, z 0.06 behind the ball: reach 0.06, slope 3.3333: 1 - 0.033333 x (4 - i) ->
       [0.866667, 0.9, 0.933333, 0.966667, 1.0], min_factor 0.866667 x 1.25 = 1.083333. Every share step x reach is
       at most 0.2 a unit; the share never falls below the measured need.
[I4] inside_seen on a box shoe (the outer skin x 0 .. 0.1, y 0 .. 0.05, z 0 .. 0.04, wound outward; the lining
     0.0025 inside it, wound inward — its face toward the cavity; every face cut into tiles of at most 10 mm), pixels of
     SKIN_SEEN_PX_M 1 mm from 4 px outside the lower corner:
     - whole: from every side the nearest face is the outer skin, turned toward the camera -> 0 mm2, worst 0;
     - the lining's back face (z 0.0025) pushed out to z -0.0005 (0.5 mm through the outer skin at z 0): from the back
       (camera at -z, columns = x, rows = y, lo = (-0.004, -0.004)) the lining's back face is nearer (depth 0.0005)
       than the outer skin (0) by more than SKIN_SEEN_EPS_M and turned away from the camera: columns
       floor((0.0025 + 0.004) / 0.001) = 6 .. floor((0.0975 + 0.004) / 0.001) = 101 (96), rows 6 .. floor((0.0475 +
       0.004) / 0.001) = 51 (46) -> 96 x 46 = 4416 mm2, a rectangle the 2 x 2 opening keeps. Front: the outer front
       face (z 0.04) is nearest -> 0. The sides: the 0.5 mm of lining behind the outer skin's edge lie in at most one
       column (z -0.0005 .. 0 against lo -0.0045) -> the opening drops it -> 0. Worst 4416, above the limit.
     The outer skin it came through lies 0.5 mm behind it, within SKIN_POKE_M 3 mm.
     - a shoe of ONE sheet (no lining; the outer skin without its top face, the back wall cut down to y 0.02): from the
       back the front wall's inside shows above the low back wall, turned away from the camera, with nothing turned
       toward it behind -> not counted: 0 from every side.
[I5] the gate: INSIDE_SEEN_MAX_MM2 (footwear_cut comment, the distribution through the routes), ("max", limit) in
     garment_footwear's closed-shoe cut gates; Auto answers it with heel room (AUTO_LENGTH_GATES).
"""
import ast
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
OLD = "8bea143b2"


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol=1e-6):
    return a is not None and len(a) == len(b) and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def old_width_taper():
    """``width_taper`` of footwear_fit.py at main ``OLD`` (None when git or the commit is not there)."""
    try:
        src = subprocess.run(["git", "show", f"{OLD}:app/core/footwear_fit.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "width_taper")
    ns: Dict[str, Any] = {"np": np, "Optional": Optional, "Dict": Dict, "Any": Any, "WIDTH_TAPER_MIN": 0.01}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "old_width_taper", "exec"), ns)
    return ns["width_taper"]


def box(lo, hi, outward=True, tile=0.01):
    """An axis-aligned box ``lo`` .. ``hi`` as tiles of at most ``tile`` m, wound outward (or inward)."""
    P, F = [], []
    for a in range(3):
        u, v = (a + 1) % 3, (a + 2) % 3          # e_u x e_v = e_a
        for s in (-1.0, 1.0):
            val = hi[a] if s > 0 else lo[a]
            nu = max(1, int(np.ceil((hi[u] - lo[u]) / tile - 1e-9)))
            nv = max(1, int(np.ceil((hi[v] - lo[v]) / tile - 1e-9)))
            for i in range(nu):
                for j in range(nv):
                    u0, u1 = lo[u] + (hi[u] - lo[u]) * i / nu, lo[u] + (hi[u] - lo[u]) * (i + 1) / nu
                    v0, v1 = lo[v] + (hi[v] - lo[v]) * j / nv, lo[v] + (hi[v] - lo[v]) * (j + 1) / nv
                    base = len(P)
                    for cu, cv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                        p = [0.0, 0.0, 0.0]
                        p[a], p[u], p[v] = val, cu, cv
                        P.append(p)
                    tri = [[base, base + 1, base + 2], [base, base + 2, base + 3]]
                    if (s > 0) != outward:
                        tri = [[t[0], t[2], t[1]] for t in tri]
                    F += tri
    return np.array(P, np.float64), np.array(F, np.int64)


def shoe(pushed: bool):
    from app.core import glb_mesh
    t = 0.0025
    Po, Fo = box((0.0, 0.0, 0.0), (0.1, 0.05, 0.04))
    Pl, Fl = box((t, t, -0.0005 if pushed else t), (0.1 - t, 0.05 - t, 0.04 - t), outward=False)
    P = np.concatenate([Po, Pl])
    F = np.concatenate([Fo, Fl + len(Po)])
    n = len(P)
    return glb_mesh.GarmentMesh(positions=P, normals=None, uvs=np.zeros((n, 2)), indices=F,
                                joints=np.zeros((n, 4), np.int64), weights=np.zeros((n, 4)), joint_names=[])


def one_sheet():
    from app.core import glb_mesh
    P, F = box((0.0, 0.0, 0.0), (0.1, 0.05, 0.04))
    top = np.all(np.isclose(P[F][:, :, 1], 0.05), axis=1)
    F = F[~top]
    back = np.all(np.isclose(P[F][:, :, 2], 0.0), axis=1) & (P[F][:, :, 1].min(1) >= 0.02 - 1e-9)
    F = F[~back]                                   # the back wall above y 0.02 (tiles of 10 mm: rows 0.02 .. 0.05)
    n = len(P)
    return glb_mesh.GarmentMesh(positions=P, normals=None, uvs=np.zeros((n, 2)), indices=F,
                                joints=np.zeros((n, 4), np.int64), weights=np.zeros((n, 4)), joint_names=[])


def main() -> int:
    from app.core import footwear_cut, footwear_fit as ff, garment_footwear
    old = old_width_taper()
    if old is None:
        print(f"note: main {OLD} not readable — the old-code proofs are skipped")

    print("[I1] the bounded profiles")
    check(near(ff._bounded_back(np.array([0.0, 0.5, 0.0]), np.array([0.0, 1.0, 2.0]), 0.1), [0.0, 0.1, 0.0], 1e-12),
          "[I1] _bounded_back -> [0, 0.1, 0]")
    check(near(ff._majorant(np.array([0.8, 0.8, 1.0]), np.array([0.0, 0.01, 0.02]), 5.0), [0.9, 0.95, 1.0], 1e-12),
          "[I1] _majorant -> [0.9, 0.95, 1.0]")
    check(ff.TAPER_SLOPE_MAX == 0.1 and ff.TAPER_SHARE_SLOPE_MAX == 0.2, "[I1] TAPER_SLOPE_MAX 0.1, TAPER_SHARE_SLOPE_MAX 0.2")

    print("[I2] a stray foot middle")
    st = np.arange(6, dtype=float)
    il = np.array([(-0.03, 0.03)] * 6)
    fl = np.array([(np.nan, np.nan), (-0.02, 0.02), (0.48, 0.52), (-0.02, 0.02), (-0.05, 0.05), (np.nan, np.nan)])
    tp = ff.width_taper(st, il, fl, 1.0, 1.25, 4.0, 0.002)
    check(tp is not None and tp["x_raw"] == [0.0, 1.0, 2.0, 3.0, 4.0], "[I2] x_raw 0 .. 4")
    check(tp is not None and near(tp["share"], [0.8, 0.8, 1.0, 1.0, 1.0]), f"[I2] share {tp and tp['share']}")
    check(tp is not None and near(tp["centre_raw"], [0.0, 0.0, 0.1, 0.0, 0.0]), f"[I2] centre {tp and tp['centre_raw']}")
    check(tp is not None and near(tp["mid_raw"], [0.0] * 5) and abs(tp["min_factor"] - 1.0) < 1e-9, "[I2] mid 0, min 1")
    if old is not None:
        to = old(st, il, fl, 1.0, 1.25, 4.0, 0.002)
        check(near(to["share"], [0.8, 0.8, 0.8, 0.8, 1.0]) and near(to["centre_raw"], [0.0, 0.0, 0.5, 0.0, 0.0]),
              f"[I2] main {OLD}: share {to['share']}, centre {to['centre_raw']} (a step of 0.5 a unit)")

    print("[I3] the share's majorant")
    st = np.arange(6, dtype=float) * 0.01
    fl = np.array([(np.nan, np.nan), (-0.02, 0.02), (-0.02, 0.02), (-0.024, 0.024), (-0.05, 0.05), (np.nan, np.nan)])
    tp = ff.width_taper(st, il, fl, 1.0, 1.25, 0.04, 0.002)
    check(tp is not None and near(tp["share"], [0.8, 0.8, 0.866667, 0.933333, 1.0]), f"[I3] share {tp and tp['share']}")
    tp = ff.width_taper(st, il, fl, 1.0, 1.25, 0.04, 0.002, shoe_xz=np.array([[0.0, 0.06], [0.045, 0.2]]))
    check(tp is not None and near(tp["share"], [0.866667, 0.9, 0.933333, 0.966667, 1.0]),
          f"[I3] share with a shoe reaching 0.06 {tp and tp['share']}")
    check(tp is not None and abs(tp["min_factor"] - 1.083333) < 1e-6, "[I3] min_factor 1.083333")
    if old is not None:
        to = old(st, il, fl, 1.0, 1.25, 0.04, 0.002)
        check(near(to["share"], [0.8, 0.8, 0.8, 0.853333, 1.0]), f"[I3] main {OLD}: share {to['share']}")

    print("[I4] inside_seen on a box shoe")
    clean = footwear_cut.inside_seen({"left": {"foot": shoe(False)}})
    check(clean["worst_mm2"] == 0.0 and all(v == 0.0 for v in clean["mm2"]["left"].values()),
          f"[I4] whole: 0 from every side {clean['mm2']}")
    seen = footwear_cut.inside_seen({"left": {"foot": shoe(True)}})
    check(abs(seen["mm2"]["left"]["back"] - 4416.0) < 1e-6, f"[I4] pushed: back 4416 mm2 ({seen['mm2']['left']['back']})")
    check(all(seen["mm2"]["left"][v] == 0.0 for v in ("front", "left", "right")), f"[I4] pushed: other sides 0 {seen['mm2']}")
    check(abs(seen["worst_mm2"] - 4416.0) < 1e-6 and seen["worst_mm2"] > footwear_cut.INSIDE_SEEN_MAX_MM2, "[I4] worst 4416, refused")

    sheet = footwear_cut.inside_seen({"left": {"foot": one_sheet()}})
    check(sheet["worst_mm2"] == 0.0, f"[I4] one sheet, low back wall: 0 {sheet['mm2']}")

    print("[I5] the gate")
    check(footwear_cut.INSIDE_SEEN_MAX_MM2 == 16.0, "[I5] INSIDE_SEEN_MAX_MM2 16 (twice the clean maximum 8, below the smallest defect 26; footwear_cut comment)")
    check("inside_seen_mm2" in garment_footwear.AUTO_LENGTH_GATES, "[I5] Auto answers inside_seen_mm2 with heel room")
    src = (ROOT / "app/core/garment_footwear.py").read_text()
    check('{"inside_seen_mm2": ("max", footwear_cut.INSIDE_SEEN_MAX_MM2' in src, "[I5] gated as ('max', limit)")

    print("FAIL" if FAILS else "OK", f"({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
