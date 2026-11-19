"""Smoke: A220 shell construction helpers in ``app/core/garment_shell.py`` — the side bridge's run matching and
pattern source, the lift over extension parts, the back-seen wall and the arm-piece rule.

Usage:
    ./.venv/bin/python scripts/smoke_shell_bridge_parts_arms.py

No server, no world, no storage. Expected values derived by hand (BIN_M = 0.002 m, MATCH_M = 0.03 m):
  [1] match_runs([(10, 80)], [(0, 55)]): centres 45 and 27.5 bins = 0.035 m apart (> MATCH_M) but the ranges overlap
      by 46 bins -> [0]. (The pre-A220 centre-only rule left this pair unmatched — the bra's open side.)
  [2] match_runs([(0, 5)], [(20, 25)]): no overlap, centres 0.040 m apart -> [None].
  [3] match_runs([(0, 10)], [(5, 8), (0, 12)]): overlaps 4 and 11 -> the larger: [1].
  [4] extend_run((5, 7), wide = bins 2..8 True) -> (2, 8).
  [5] panel_source_angle (span 20): front edge 70, th 80 -> 60; th 100 (30 past: folds to 10) -> 60;
      back edge 120, th 100 (20 past) -> 140; other side front edge -70, th -80 -> -60.
  [6] arm_pieces: 4 trunk points x=0, 3 arm points x=+0.5 (1 covered: 1/3 >= 0.2), 3 arm points x=-0.5 (none)
      -> keep exactly the 3 points of the +x arm; shares {"+x": 0.333, "-x": 0.0}.
  [7] lift_over_surfaces: V = origin, N = +z, offset 6 mm, a 4 cm square at z = 20 mm wound toward +z -> X z = 26 mm
      (lift 20 mm); the same square wound toward -z -> 6 mm (it faces back); at z = 50 mm (past the 40 mm reach)
      -> 6 mm.
  [8] outer_faces_oriented on a closed tetrahedron: every face is front-most from a direction its outward normal
      faces, so all 4 are outer and none is back-seen — wound outward, and wound inward too (the volume's sign turns
      the normals outward again).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_shell as gsh  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


r = gsh.match_runs([(10, 80)], [(0, 55)])
check("[1] overlapping runs with distant centres match", r == [0], r)
r = gsh.match_runs([(0, 5)], [(20, 25)])
check("[2] no overlap, centres 4 cm apart -> None", r == [None], r)
r = gsh.match_runs([(0, 10)], [(5, 8), (0, 12)])
check("[3] the larger overlap wins", r == [1], r)

wide = np.zeros(10, bool)
wide[2:9] = True
r = gsh.extend_run((5, 7), wide)
check("[4] extend_run", r == (2, 8), r)

got = [float(gsh.panel_source_angle(80.0, 70.0, True)), float(gsh.panel_source_angle(100.0, 70.0, True)),
       float(gsh.panel_source_angle(100.0, 120.0, False)), float(gsh.panel_source_angle(-80.0, -70.0, True))]
check("[5] panel_source_angle", np.allclose(got, [60.0, 60.0, 140.0, -60.0]), got)

armw = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1, 1], float)
x = np.array([0, 0, 0, 0, .5, .5, .5, -.5, -.5, -.5])
seen = np.ones(10, bool)
cov = np.zeros(10, bool)
cov[4] = True
keep, shares = gsh.arm_pieces(armw, x, seen, cov)
check("[6] arm_pieces keeps the covered arm only", keep.tolist() == [False] * 4 + [True] * 3 + [False] * 3
      and shares == {"+x": 0.333, "-x": 0.0}, (keep.tolist(), shares))


def square(z, up=True):
    P = np.array([[-.02, -.02, z], [.02, -.02, z], [.02, .02, z], [-.02, .02, z]])
    F = np.array([[0, 1, 2], [0, 2, 3]]) if up else np.array([[0, 2, 1], [0, 3, 2]])
    return P, F


V = np.zeros((1, 3))
N = np.array([[0, 0, 1.0]])
res = []
for z, up in ((0.02, True), (0.02, False), (0.05, True)):
    P, F = square(z, up)
    X, _lift = gsh.lift_over_surfaces(V, N, 0.006, [(P, F, True)])
    res.append(round(float(X[0, 2]) * 1000, 1))
check("[7] lift_over_surfaces 26 / 6 / 6 mm", res == [26.0, 6.0, 6.0], res)

T = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.0]])
TF = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])   # outward
for name, F in (("outward", TF), ("inward", TF[:, ::-1])):
    outer, back = gsh.outer_faces_oriented(T, F, px=0.02, tol=0.01)
    check(f"[8] tetrahedron wound {name}: all outer, none back-seen", outer.all() and not back.any(),
          (outer.tolist(), back.tolist()))

print("ALL OK" if not FAILED else f"FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
