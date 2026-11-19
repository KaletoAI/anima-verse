#!/usr/bin/env python3
"""Smoke: the A208 mouth fixes — the chin edge, the cut skin's shading, the lips kept apart by the extension bones.

Usage:
    ./.venv/bin/python scripts/smoke_mouth_a208.py

No server, no world, no Blender (the extension-bones helper is read out of its file with ``ast``). Every expected
number is derived by hand here. The pre-fix proofs read the pinned commit ffe2bc03c (``git show``).

[1] chin_row, rows 4 mm apart, index 0 lowest, nose at row 9 (depth 0), drop 0.05, jump 0.02, rows_up 1, reach 7 rows
    (28 mm). A
    RECEDING chin (one measured face, rounded): depths from the bottom 0.112, 0.063, 0.060, 0.057, 0.054, 0.042,
    0.030, 0.017, 0.005, 0. Going down from row 9: row 4 (0.054) is the first past 0.05; it lies 0.012 behind
    row 5 (< 0.02), rows 3, 2, 1 lie 0.003 behind the row above; row 0 lies 0.112 - 0.063 = 0.049 behind row 1
    -> row 0, the real edge. The drop-only rule before gave row 4: on the chin's front, and the lip search starts
    1 cm above the chin row, so the lips below it were never searched.
    A face with a sharp under-chin: 0.096 at row 3, 0.041 at row 4 (0.041 < 0.05) -> row 3, as before (0.055 >=
    0.02). A chin without a step (0.06, 0.065, 0.07 below rows of 0.04): the first row past drop -> as before.
    No face under row 2 (NaN) and nothing past drop above it -> row 2.
    Reach: 21 rows, first past drop at row 20 (0.06 there and below), a deep crack (0.2) at row 12 and NaN at row 2:
    rows 19..13 lie 0..7 rows below 20 without a step, row 12 lies 8 > 7 rows below -> row 20 (the crack and the
    hole are too far down to be the chin).
[2] barycentric: (0.25, 0.25, 0.7) over the triangle (0,0,0) (1,0,0) (0,1,0) projects to (0.25, 0.25, 0) ->
    (0.5, 0.25, 0.25); a corner -> (1, 0, 0) at a, the midpoint of b c -> (0, 0.5, 0.5); a degenerate triangle ->
    (1, 0, 0).
[3] extension_bones leaves a coincident group alone only when it holds a vertex of the mouth channel's pouch
    (material ``mouth_channel``, equal to mouth_part.INSIDE_MATERIAL); the Blender case with numbers is
    scripts/smoke_extension_rig_coincident.py Part A.
[4] Pre-fix proofs at ffe2bc03c: mouth_part's chin is the drop-only ``next(...)`` rule, the cut has no
    ``restore_shading``, the pouch has no push behind the skin, the standing rule has no visible-skin guard,
    and extension_bones' ``unify_coincident_weights`` averages every coincident group (no mouth rule).
"""
import ast
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import mouth_math as mm  # noqa: E402

failed = 0


def check(label, ok, got=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "  got: %r" % (got,)))
    failed += 0 if ok else 1


receding = np.array([.112, .063, .060, .057, .054, .042, .030, .017, .005, 0.])
check("[1] receding chin -> row 0", mm.chin_row(receding, 9, 0., .05, .02, 1, 7) == 0,
      mm.chin_row(receding, 9, 0., .05, .02, 1, 7))
old = next(i for i in range(9, -1, -1) if not np.isfinite(receding[i]) or receding[i] > .05)
check("[1] the drop-only rule gave row 4", old == 4, old)
sharp = np.array([.11, .105, .1, .096, .041, .03, .02, .01, .005, 0.])
check("[1] sharp under-chin -> row 3", mm.chin_row(sharp, 9, 0., .05, .02, 1, 7) == 3, mm.chin_row(sharp, 9, 0., .05, .02, 1, 7))
gentle = np.array([.07, .065, .06, .04, .04, .03, .02, .01, .005, 0.])
check("[1] no step -> first past drop (row 2)", mm.chin_row(gentle, 9, 0., .05, .02, 1, 7) == 2,
      mm.chin_row(gentle, 9, 0., .05, .02, 1, 7))
holed = np.array([np.nan, np.nan, np.nan, .04, .04, .03, .02, .01, .005, 0.])
far = np.full(22, .06)
far[12], far[2] = .2, np.nan
far[21] = 0.
far[20:21] = .06
check("[1] crack and hole beyond reach -> row 20", mm.chin_row(far, 21, 0., .05, .02, 1, 7) == 20,
      mm.chin_row(far, 21, 0., .05, .02, 1, 7))
check("[1] no face -> row 2", mm.chin_row(holed, 9, 0., .05, .02, 1, 7) == 2, mm.chin_row(holed, 9, 0., .05, .02, 1, 7))

a, b, c = np.array([0., 0, 0]), np.array([1., 0, 0]), np.array([0., 1, 0])
got = [mm.barycentric(np.array([.25, .25, .7]), a, b, c), mm.barycentric(a, a, b, c),
       mm.barycentric(np.array([.5, .5, 0]), a, b, c), mm.barycentric(np.array([.3, .3, .3]), a, a, a)]
want = [[.5, .25, .25], [1, 0, 0], [0, .5, .5], [1, 0, 0]]
check("[2] barycentric", all(np.allclose(g, w, atol=1e-12) for g, w in zip(got, want)), got)

source = (ROOT / "app/blender/scripts/extension_bones.py").read_text()
mp_source = (ROOT / "app/blender/scripts/mouth_part.py").read_text()
check("[3] the material names agree", "MOUTH_INSIDE_MATERIAL = 'mouth_channel'" in source
      and "INSIDE_MATERIAL = 'mouth_channel'" in mp_source)
check("[3] unify skips mouth groups", "in mouth.get(owners[i][0].name, ())" in source)

PIN = "ffe2bc03c"


def pinned(path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN}:{path}"], capture_output=True, text=True,
                          check=True).stdout


mp_old, eb_old = pinned("app/blender/scripts/mouth_part.py"), pinned("app/blender/scripts/extension_bones.py")
check("[4] pinned: drop-only chin rule", "column[i] > nose_y + P['chin_drop']), None)" in mp_old)
check("[4] pinned: no shading restore", "restore_shading" not in mp_old)
check("[4] pinned: no pouch push behind the skin", "'pouch': .003" not in mp_old)
check("[4] pinned: no visible-skin guard in the standing rule", "'surface': .001" not in mp_old)
check("[4] pinned: unify averages every coincident group", "mouth_channel_vertices" not in eb_old
      and "def unify_coincident_weights" in eb_old)

print("FAILED (%d)" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
