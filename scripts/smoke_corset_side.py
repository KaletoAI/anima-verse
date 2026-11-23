"""Corset v7 (review 2026-11-23 of v6: a vertical crease down each side of the cups, dihedral angles up to 91 degrees at
83-92 degrees off the front, outside the front fold gate's window; the cup's edge dropped 4.5 cm over the two columns
beside the side seam; a dark band under the cups with no seam there): the side blend of the top edge
(``side_blend``), the side blend of the strips' rise (``side_strip_blend``), the flatter quad diagonal
(``corset_diagonals``), the fold gate's windows (``fold_key``), the seam under the cups (``under_cup_rows``,
``corset_darts.cup_seams`` / ``seam_lines``, ``cut_texture_post._smooth_points``) and the gate rows (``judge_build``).
The Blender helpers are taken out of the build script by ``ast`` and run on analytic bodies (``gd.body_radius``
stubbed). No server, no world DB, no Blender. Every number below is derived by hand.

[1] ``side_blend`` on a ring of 5 columns (off-front 40, 70, 90, 100, 130 degrees; the first two front columns with
    chest tissue, locked; ``SIDE_BLEND_RAD`` 55..115, so columns 1..3 are in the window), one pass:
    top0 [1.30, 1.30, 1.25, 1.25, 1.25], lowering [0, 0, 0.02, 0.04, 0.04] = need -> z [1.30, 1.30, 1.23, 1.21, 1.21].
    Column 1 (70 degrees, tissue): t = (70 - 55) / (90 - 55) = 3/7, smoothstep t^2 (3 - 2t) = 9/49 x 15/7 = 135/343
    = 0.393586; its floor 1.30 - 0.025 x 0.393586 = 1.290160, ceiling 1.30; mean (1.30 + 2.60 + 1.23) / 4 = 1.2825
    -> the floor 1.290160 (lowering 0.009840).
    Column 2 (free): mean (1.30 + 2.46 + 1.21) / 4 = 1.2425, ceiling top0 - need = 1.23 -> 1.23 (0.02).
    Column 3 (free): mean (1.23 + 2.42 + 1.21) / 4 = 1.215, ceiling 1.21 -> 1.21 (0.04).
    -> lowering [0, 0.009840, 0.02, 0.04, 0.04], cols 1, max_cup_drop 0.0098.
    A free column under its ceiling comes down: column 3 with need 0 (ceiling 1.25, z 1.25), z [1.30, 1.30, 1.23,
    1.25, 1.21]: (1.23 + 2.50 + 1.21) / 4 = 1.235 -> lowering 0.015.
    A column the smoothing lifts above its lowering: column 3 lowered 0.04 (z 1.21) with need 0 (ceiling 1.25):
    (1.23 + 2.42 + 1.21) / 4 = 1.215 -> lowering 0.035; with ``bad`` true for column 3 it is put back to 0.04
    (refold 1).
[2] ``side_strip_blend`` on one front panel of 2 rows x 41 columns (column c at angle pi + pi c / 40, 4.5 degrees
    apart; body radius 0.10 everywhere, clear 0.002): the strip in column 38 (81 degrees off the front) rises 0.012
    over body + clear at row 1, every other column 0. ``SIDE_STRIP_IN`` 0 and ``SIDE_STRIP_BACK`` 0: the columns from
    81 - 2.25 to 90 + 2.25 degrees, 38, 39, 40 (the ends held). Row 0 at 1.20 (the edge), row 1 at 1.10, bot 1.0.
    One pass: column 39, row 1: (0.012 + 2 x 0 + 0) / 4 = 0.003; depth under its edge 0.10 = ``SIDE_STRIP_EDGE_M``
    -> weight smoothstep(1) = 1 -> rad 0.10 + 0.002 + 0.003 = 0.105; not over the fold (0.003 <= 0.004).
    30 passes: o = (0.012 + 2 o) / 4 has the fixed point 0.006, reached to 0.006 x 0.5^30.
    Row 1 at 1.15 instead (depth 0.05, t 0.5, smoothstep 0.5), one pass: 0.003 x 0.5 = 0.0015. The other side
    (columns 0..2, no strip) and the edge row do not move.
[3] ``corset_diagonals``: the quad a (0, 0, 0), b (1, 0, 0), c (1, 1, h), d (0, 1, 0), h = 1. Split a-c: normals
    (b - a) x (c - a) = (0, -1, 1), (c - a) x (d - a) = (-1, 0, 1): cos = 1 / 2 -> 60 degrees. Split b-d: (c - b) x
    (d - b) = (-1, -1, 1), (d - b) x (a - b) = (0, 0, 1): cos = 1 / sqrt 3 -> 54.7 degrees. b-d is flatter: the face
    turns to (b, c, d, a), turned 1. A flat quad stays as it is.
[4] ``fold_key``: 0.5 and 0.85 rad (``SHELL_HULL_RAD`` 0.6 + 0.3) -> front_fold; pi/2 (the side seam) and 110 degrees
    -> side_fold; 2.0 rad (115 degrees) -> None (the back). v6's crease at 83-92 degrees falls in side_fold.
[5] ``under_cup_rows`` on a front of 5 columns, rows at [1.30, 1.25, 1.20, 1.15, 1.10] (no drop), tissue in columns
    1 and 3, apex 1.25, the body r = 0.10 + 0.03 max(0, 1 - ((z - 1.25) / 0.10)^2) at every angle: the rib cage
    under the apex (1.13) 0.10, the fullest point 1.25 (depth 0.03); the tissue ends where r - 0.10 <= 0.2 x 0.03
    -> ((z - 1.25) / 0.10)^2 >= 0.8 -> z <= 1.25 - 0.08944 = 1.16056; scanned in 2 mm steps from 1.28: 1.162 gives
    0.7744 (not yet), 1.160 gives 0.81 -> 1.160 in columns 1 and 3, column 2 between them 1.160; the nearest row 3
    (1.15) -> {1: 3, 2: 3, 3: 3}.
    ``cup_seams(5, ...)``: one run 1..3 through the centre column 2, split there (corset v8,
    ``smoke_corset_cup_centre.py``) -> seam_cup_0 = (1, [3 x 5 + 1, + 2]) = [16, 17], seam_cup_1 = [17, 18]; ``seam_lines(5, 5,
    rows)``: front seams in columns round(8 x 4 / 40) = 1 and round(16 x 4 / 40) = 2 off the centre 2 -> 0, 1, 3, 4;
    column 1 starts at row 3: [16, 21]; column 0 runs from the top: [0, 5, 10, 15, 20]; runs of one column draw
    nothing.
    ``_smooth_points`` [(0, 0), (1, 4), (2, 0)], one round: the middle (0 + 2 + 2, 0 + 8 + 0) / 4 = (1, 2), the
    ends held. ``_forward_points`` [(0, 0), (4, 1), (6, 2), (5, 3), (5.5, 1), (7, 0), (10, 0)]: x 5 and 5.5 are not past
    6 -> [(0, 0), (4, 1), (6, 2), (7, 0), (10, 0)]; reversed (x falling) only 6 is not under 5 -> [(10, 0), (7, 0),
    (5.5, 1), (5, 3), (4, 1), (0, 0)].
[6] ``judge_build``: side_fold 56 > 55 fails (a gate), 48 passes; CORSET_VERSION 9 (v9: the cleavage's disc); SEAM_VERSION 3.
[7] Fails on the old code: at 6b076ad15 (v6, the review's BEFORE) the build script has no ``side_blend``, no
    ``side_strip_blend``, no ``corset_diagonals`` and no ``side_fold`` (its fold gate stopped at ``SHELL_HULL_RAD``
    + 0.3 rad = 51.6 degrees, so the 90.8-degree crease at 83.5 degrees passed at 34).

Usage: ./.venv/bin/python scripts/smoke_corset_side.py
"""
import ast
import math
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-side-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import cut_texture_post as ctp  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
import corset_darts as cdarts  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


BUILD = ROOT / "app" / "blender" / "scripts" / "garment_template_build.py"
WANT = {"side_blend", "_smoothstep", "_angle_off", "side_strip_blend", "corset_diagonals", "fold_key",
        "under_cup_rows"}
CONSTS = {"SIDE_BLEND_RAD", "SIDE_CUP_DROP_M", "SIDE_BLEND_PASSES", "SIDE_STRIP_IN", "SIDE_STRIP_BACK",
          "SIDE_STRIP_PASSES", "SIDE_STRIP_EDGE_M", "SHELL_BRIDGE_M", "SHELL_HULL_RAD", "FOLD_LIMIT_KEY",
          "SIDE_FOLD_KEY", "SIDE_FOLD_RAD", "CUP_UNDER_M", "CUP_SEAM_ABOVE_M", "CUP_SEAM_BELOW_M",
          "CUP_SEAM_TISSUE_SHARE", "CUP_SEAM_SMOOTH"}


def load(src):
    tree = ast.parse(src)
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in WANT)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in n.targets))]
    gd = types.SimpleNamespace(body_radius=None)
    ns = {"math": math, "np": np, "gd": gd}
    exec(compile(ast.Module(nodes, []), str(BUILD), "exec"), ns)
    return ns, gd


ns, gd = load(BUILD.read_text())
check("helpers present", WANT <= set(ns), sorted(WANT - set(ns)))
check("constants", (ns["SIDE_BLEND_RAD"], ns["SIDE_CUP_DROP_M"], ns["SIDE_STRIP_EDGE_M"], ns["SIDE_FOLD_RAD"])
      == ((math.radians(55.0), math.radians(115.0)), 0.025, 0.1, math.radians(110.0)))


def near(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b)) and len(a) == len(b)


# [1]
ring = [("front", 1, 1.5 * math.pi + math.radians(o)) for o in (40.0, 70.0)] + \
       [("back", c, 1.5 * math.pi + math.radians(o)) for c, o in ((0, 90.0), (1, 100.0), (2, 130.0))]
top0 = [1.30, 1.30, 1.25, 1.25, 1.25]
locked = [True, True, False, False, False]
ns["SIDE_BLEND_PASSES"] = 1
w = 135.0 / 343.0
out, info = ns["side_blend"](ring, top0, [0, 0, 0.02, 0.04, 0.04], [0, 0, 0.02, 0.04, 0.04], locked, {1})
check("[1] smoothstep(3/7) = 135/343", abs(ns["_smoothstep"](3.0 / 7.0) - w) < 1e-12)
check("[1] one pass: the outer cup column down to its floor, the free ones at their need",
      near(out, [0, 0.025 * w, 0.02, 0.04, 0.04]), out)
check("[1] cols 1, max_cup_drop 0.0098", info["cols"] == 1 and info["max_cup_drop_m"] == 0.0098, info)
out, info = ns["side_blend"](ring, top0, [0, 0, 0.02, 0.0, 0.04], [0, 0, 0.02, 0.0, 0.04], locked, {1})
check("[1] a free column under its ceiling comes down to the mean (0.015)", abs(out[3] - 0.015) < 1e-9, out)
out, info = ns["side_blend"](ring, top0, [0, 0, 0.02, 0.04, 0.04], [0, 0, 0.02, 0.0, 0.04], locked, {1})
check("[1] a column lifted by the smoothing: 0.035", abs(out[3] - 0.035) < 1e-9 and info["refold"] == 0, (out, info))
out, info = ns["side_blend"](ring, top0, [0, 0, 0.02, 0.04, 0.04], [0, 0, 0.02, 0.0, 0.04], locked, {1},
                             lambda k, z: k == 3)
check("[1] ... put back to 0.04 when it lands on the fold (refold 1)", abs(out[3] - 0.04) < 1e-12
      and info["refold"] == 1, (out, info))
ns["SIDE_BLEND_PASSES"] = 40

# [2]
gd.body_radius = None
R, C = 2, 41
ang = [math.pi + math.pi * c / (C - 1) for _r in range(R) for c in range(C)]
spec = {"rows": R, "cols": C}


def strip_case(z1, passes):
    ns["SIDE_STRIP_IN"], ns["SIDE_STRIP_BACK"], ns["SIDE_STRIP_PASSES"] = 0, 0, passes
    body = np.full(R * C, 0.10)
    rad = body + 0.002
    rad[1 * C + 38] += 0.012
    zz0 = [1.20] * C + [z1] * C
    strips = {(0, 38): [38, C + 38]}
    res = ns["side_strip_blend"](rad, body, zz0, ang, spec, 0.002, strips, set(range(C)), 1.0)
    return rad, res


rad, res = strip_case(1.10, 1)
check("[2] one pass: column 39 row 1 at 0.10 + 0.002 + 0.003", abs(rad[C + 39] - 0.105) < 1e-12, rad[C + 39])
check("[2] moved only that vertex, not over the fold", res["moved"] == [C + 39] and res["hollow"] == [], res)
check("[2] the strip and the seam column held, the edge row and the other side untouched",
      abs(rad[C + 38] - 0.114) < 1e-12 and abs(rad[C + 40] - 0.102) < 1e-12 and np.allclose(rad[:C], 0.102)
      and np.allclose(rad[C:C + 3], 0.102))
rad, res = strip_case(1.10, 30)
check("[2] 30 passes: the fixed point 0.006", abs(rad[C + 39] - 0.108) < 1e-9, rad[C + 39])
rad, res = strip_case(1.15, 1)
check("[2] 5 cm under the edge: half of it (0.0015)", abs(rad[C + 39] - 0.1035) < 1e-12, rad[C + 39])
ns["SIDE_STRIP_IN"], ns["SIDE_STRIP_BACK"], ns["SIDE_STRIP_PASSES"] = 2, 4, 30

# [3]
V = [(0, 0, 0), (1, 0, 0), (1, 1, 1), (0, 1, 0)]
faces, turned = ns["corset_diagonals"](V, [(0, 1, 2, 3)])
check("[3] the twisted quad splits along b-d (54.7 < 60 degrees)", faces == [(1, 2, 3, 0)] and turned == 1,
      (faces, turned))
faces, turned = ns["corset_diagonals"]([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1, 2, 3)])
check("[3] a flat quad stays", faces == [(0, 1, 2, 3)] and turned == 0, (faces, turned))
faces, turned = ns["corset_diagonals"]([(0, 0, 0), (1, 0, 1), (1, 1, 0), (0, 1, 0)], [(0, 1, 2, 3)])
check("[3] lifted at b instead: a-c is the flatter split, stays", faces == [(0, 1, 2, 3)] and turned == 0)

# [4]
fk = ns["fold_key"]
check("[4] 0.5 / 0.85 rad -> front_fold, 0.95 -> side_fold", fk(0.5) == "front_fold" and fk(0.85) == "front_fold"
      and fk(0.95) == "side_fold")
check("[4] the side seam and 110 degrees -> side_fold", fk(math.pi / 2) == "side_fold"
      and fk(math.radians(110.0)) == "side_fold" and fk(math.radians(83.5)) == "side_fold")
check("[4] 2.0 rad -> None (the back)", fk(2.0) is None)

# [5]
gd.body_radius = lambda bt, c, a, z: 0.10 + 0.03 * max(0.0, 1.0 - ((z - 1.25) / 0.10) ** 2)
spec5 = {"rows": 5, "cols": 5, "row_y": [1.30, 1.25, 1.20, 1.15, 1.10], "top_drop": {"front": [0.0] * 5},
         "cup_edge": {"tissue_cols": [1, 3], "apex_y": 1.25}}
rows = ns["under_cup_rows"](spec5, None, (0.0, 0.0))
check("[5] the cup seam on row 3 in columns 1..3", rows == {1: 3, 2: 3, 3: 3}, rows)
check("[5] no cup edge -> {}", ns["under_cup_rows"]({"rows": 5, "cols": 5, "row_y": [1.3]}, None, (0, 0)) == {})
cs = cdarts.cup_seams(5, rows)
check("[5] cup_seams: two halves [16, 17] / [17, 18]", cs == {"seam_cup_0": (1, [16, 17]), "seam_cup_1": (1, [17, 18])},
      cs)
check("[5] cup_seams: a run of one column draws nothing", cdarts.cup_seams(5, {1: 3, 3: 3}) == {})
sl = cdarts.seam_lines(5, 5, rows)
check("[5] seam_lines: the front seam in column 1 starts at row 3", sl["seam_front_1"] == (1, [16, 21]), sl)
check("[5] seam_lines: column 0 from the top", sl["seam_front_0"] == (1, [0, 5, 10, 15, 20]), sl)
check("[5] seam_lines without cup rows unchanged", cdarts.seam_lines(5, 5)["seam_front_1"] == (1, [1, 6, 11, 16, 21]))
sp = ctp._smooth_points([(0, 0), (1, 4), (2, 0)], 1)
check("[5] _smooth_points: (1, 2), ends held", np.allclose(sp, [[0, 0], [1, 2], [2, 0]]), sp)
fl = [(0, 0), (4, 1), (6, 2), (5, 3), (5.5, 1), (7, 0), (10, 0)]
fp = ctp._forward_points(fl)
check("[5] _forward_points drops the points stepping back", np.allclose(fp, [[0, 0], [4, 1], [6, 2], [7, 0], [10, 0]]), fp)
fr = ctp._forward_points(fl[::-1])
check("[5] _forward_points reversed: x falling", np.allclose(fr, [[10, 0], [7, 0], [5.5, 1], [5, 3], [4, 1], [0, 0]]), fr)

# [6]
rows6 = {x["check"]: x for x in gt.judge_build({"fit_gap": {"side_fold": {"max_deg": 56.0}}})}
check("[6] side_fold 56 > 55 fails (gate)", not rows6["side_fold_max_deg"]["ok"] and rows6["side_fold_max_deg"]["gate"])
rows6 = {x["check"]: x for x in gt.judge_build({"fit_gap": {"side_fold": {"max_deg": 48.0}}})}
check("[6] side_fold 48 ok", rows6["side_fold_max_deg"]["ok"])
check("[6] CORSET_VERSION 9, SEAM_VERSION 3", gt.CORSET_VERSION == 9 and ctp.SEAM_VERSION == 3)

# [7]
OLD = "6b076ad15"
r = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/blender/scripts/garment_template_build.py"],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(f"SKIP [7] {OLD} not in this checkout")
else:
    old = r.stdout
    check(f"[7] {OLD}: no side blend, no strip blend, no diagonals, no side fold",
          "def side_blend" not in old and "def side_strip_blend" not in old and "def corset_diagonals" not in old
          and "side_fold" not in old and "if off > SHELL_HULL_RAD + 0.3 or" in old)
    now = BUILD.read_text()
    check("[7] now: all four", all(k in now for k in ("def side_blend", "def side_strip_blend",
                                                         "def corset_diagonals", "SIDE_FOLD_KEY = \"side_fold\"")))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
