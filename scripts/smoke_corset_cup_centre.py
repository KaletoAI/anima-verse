"""Corset v8 (review 2026-11-23 of v7: the painted seam under the cups formed an "M" whose two arcs met the centre front
at different heights, with a kink, and a short spike rose from the meeting point): the seam's rows are mirror-symmetric
(``under_cup_rows``), meet the centre front under the end of the centre cut (``corset_darts.centre_cup_rows``) and are
drawn as two halves that share the centre point (``corset_darts.cup_seams``); each half is smoothed on its own with
its ends held (``cut_texture_post._forward_points`` / ``_smooth_points``). No server, no world DB, no Blender. Every
number below is derived by hand.

[1] ``centre_rows(27)`` = round(26 / 3) = round(8.667) = 9: the centre cut of a 27 x 41 front (``dart_seams``) runs
    from row 0 down to row 9 of column 20 — its last edge is (8 x 41 + 20, 9 x 41 + 20) = (348, 389), and no cut edge
    reaches row 10. ``CUP_CENTRE_BELOW_ROWS`` 1, ``CUP_CENTRE_CLEAR_COLS`` 2.
[2] ``centre_cup_rows(27, 41, rows)``: the lowest row allowed k columns off the centre is 9 + 1 - max(0, k - 2):
    k 0..2 -> 10, k 3 -> 9, k 4 -> 8, k 5 -> 7. Rows {15: 7, 16: 7, 17: 8, 18: 8, 19: 12, 20: 8, 21: 8, 22: 8, 23: 7,
    24: 7, 25: 7} -> {15: 7, 16: 8, 17: 9, 18: 10, 19: 12 (already lower, kept), 20: 10, 21: 10, 22: 10, 23: 9, 24: 8,
    25: 7}. A row is never raised; {} stays {}.
[3] ``cup_seams(41, ...)`` of the rows of [2] with column 19 on row 10 as well (a mirror-symmetric line): the run 15..25
    crosses the centre column 20, so it is split there into two lines that both hold the centre vertex 10 x 41 + 20 =
    430: seam_cup_0 = columns 15..20 = [7 x 41 + 15, 8 x 41 + 16, 9 x 41 + 17, 10 x 41 + 18, 10 x 41 + 19, 430] =
    [302, 344, 386, 428, 429, 430]; seam_cup_1 = columns 20..25 = [430, 431, 432, 9 x 41 + 23, 8 x 41 + 24,
    7 x 41 + 25] = [430, 431, 432, 392, 352, 312]. The left half's last id is the right half's first id (the shared
    point); column 20 - k of the left half and 20 + k of the right half lie on the same row (the mirror). Each half's
    columns rise one by one: neither half turns back across the panel. A run that ends ON the centre column (15..20)
    or does not reach it stays one line.
[4] Drawing (``draw_seams``: ``_smooth_points(_forward_points(px), SEAM_CROSS_SMOOTH)``, 6 rounds of (1, 2, 1) / 4, the
    ends held): the left half [(0, 0), (5, 8), (10, 4)] and its mirror about x = 10, [(10, 4), (15, 8), (20, 0)].
    ``_forward_points`` keeps every point (x rises). The one inner point m moves to m' = (a + 2 m + b) / 4, so
    m' - (a + b) / 2 = (m - (a + b) / 2) / 2: after 6 rounds m = (a + b) / 2 + (m0 - (a + b) / 2) / 64.
    Left: (a + b) / 2 = (5, 2), m0 - it = (0, 6) -> (5, 2 + 6 / 64) = (5, 2.09375). Right: (15, 2) + (0, 6) / 64 =
    (15, 2.09375). The shared point (10, 4) stays the end of both. The tangents there: the left half arrives along
    (10, 4) - (5, 2.09375) = (5, 1.90625), the right half leaves along (15, 2.09375) - (10, 4) = (5, -1.90625) — the
    mirror of the arrival (the same x, the opposite y): no kink, a soft point.
    v7's single line (b309f93ec), its points over columns 17..23 measured on Rosi's atlas: (410.098, 309.381),
    (421.642, 323.915), (431.760, 335.561), (422.107, 348.281), (427.696, 317.391), (439.141, 304.171),
    (451.305, 258.225); ``_forward_points`` drops x 422.107 and 427.696 (not past 431.760), so the left arc ended at
    (431.760, 335.561) and the right arc went on from (439.141, 304.171): 335.561 - 304.171 = 31.39 px higher, 1.63 cm
    at 19.21 px/cm — the kink of the review.
[5] ``under_cup_rows`` (taken out of the build script by ``ast``, ``gd.body_radius`` stubbed) on a front of 5 columns,
    rows at [1.30, 1.25, 1.20, 1.15, 1.10] (no drop), tissue in columns 1 (angle 1.25 pi) and 3 (1.75 pi), apex 1.25,
    an UNEVEN body: r = 0.10 + 0.03 max(0, 1 - ((z - 1.25) / s)^2), s = 0.10 on column 1's side, 0.05 on column 3's.
    The rib cage (1.25 - ``CUP_UNDER_M`` 0.12 = 1.13) 0.10 on both. Column 1: ((z - 1.25) / 0.10)^2 >= 0.8 ->
    z <= 1.16056, the 2 mm scan from 1.28 gives 1.160. Column 3: ((z - 1.25) / 0.05)^2 >= 0.8 -> z <= 1.20528:
    1.206 gives 0.7744 (not yet), 1.204 gives 0.8464 -> 1.204. Column 2 between them: 1.182.
    3 rounds of (1, 2, 1) / 4, an end column counted with its own height:
    round 1 [1.1655, 1.182, 1.1985], round 2 [1.169625, 1.182, 1.194375], round 3 [1.17271875, 1.182, 1.19128125].
    The mirror (v8): columns 1 and 3 take (1.17271875 + 1.19128125) / 2 = 1.182, column 2 keeps 1.182 -> the nearest
    row 2 (1.20, 1.8 cm off; 1.15 is 3.2 cm off) in all three -> {1: 2, 2: 2, 3: 2}.
    Without the mirror (b309f93ec): column 1 at 1.1727 is nearer 1.15 (2.27 cm) than 1.20 (2.73 cm) -> row 3, columns
    2 and 3 row 2 -> {1: 3, 2: 2, 3: 2}, one arc a row lower than the other.
[6] ``CORSET_VERSION`` 9 (v9 only narrows the cleavage's closing disc, ``smoke_corset_bridge.py``; v8 brought this
    seam); ``SEAM_VERSION`` stays 3 (the drawing is unchanged, the cut's marks change).
[7] Fails on the old code: at b309f93ec (v7, the review's BEFORE) ``corset_darts`` has no ``centre_cup_rows``, its
    ``cup_seams`` draws [3] as ONE line through all 11 columns (no shared point), and its ``under_cup_rows`` gives
    {1: 3, 2: 2, 3: 2} for [5].

Usage: ./.venv/bin/python scripts/smoke_corset_cup_centre.py
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

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-cup-centre-"))
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
DARTS = "app/blender/scripts/corset_darts.py"
WANT = {"under_cup_rows"}
CONSTS = {"CUP_UNDER_M", "CUP_SEAM_ABOVE_M", "CUP_SEAM_BELOW_M", "CUP_SEAM_TISSUE_SHARE", "CUP_SEAM_SMOOTH"}


def load_build(src):
    tree = ast.parse(src)
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in WANT)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in n.targets))]
    gd = types.SimpleNamespace(body_radius=None)
    ns = {"math": math, "np": np, "gd": gd}
    exec(compile(ast.Module(nodes, []), str(BUILD), "exec"), ns)
    return ns, gd


def uneven(bt, c, a, z):
    s = 0.10 if a < 1.5 * math.pi else 0.05
    return 0.10 + 0.03 * max(0.0, 1.0 - ((z - 1.25) / s) ** 2)


SPEC5 = {"rows": 5, "cols": 5, "row_y": [1.30, 1.25, 1.20, 1.15, 1.10], "top_drop": {"front": [0.0] * 5},
         "cup_edge": {"tissue_cols": [1, 3], "apex_y": 1.25}}
ROWS2 = {15: 7, 16: 7, 17: 8, 18: 8, 19: 12, 20: 8, 21: 8, 22: 8, 23: 7, 24: 7, 25: 7}
WANT2 = {15: 7, 16: 8, 17: 9, 18: 10, 19: 12, 20: 10, 21: 10, 22: 10, 23: 9, 24: 8, 25: 7}

# [1]
missing = [n for n in ("centre_rows", "centre_cup_rows", "CUP_CENTRE_BELOW_ROWS", "CUP_CENTRE_CLEAR_COLS")
           if not hasattr(cdarts, n)]
check("[1] corset_darts has the v8 centre helpers", not missing, missing)
if missing:
    print(f"\n{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
check("[1] centre_rows(27) = 9", cdarts.centre_rows(27) == 9, cdarts.centre_rows(27))
ds = cdarts.dart_seams(27, 41)
centre = [e for e in ds if e[0] % 41 == 20 and e[1] % 41 == 20]
check("[1] the centre cut's last edge (348, 389), none reaches row 10",
      centre[-1] == (348, 389) and all(e[1] < 10 * 41 for e in centre), centre[-1:])
check("[1] CUP_CENTRE_BELOW_ROWS 1, CUP_CENTRE_CLEAR_COLS 2",
      (cdarts.CUP_CENTRE_BELOW_ROWS, cdarts.CUP_CENTRE_CLEAR_COLS) == (1, 2))

# [2]
got2 = cdarts.centre_cup_rows(27, 41, ROWS2)
check("[2] centre_cup_rows: 10 / 9 / 8 / 7 off the centre, a lower row kept", got2 == WANT2, got2)
check("[2] {} stays {}", cdarts.centre_cup_rows(27, 41, {}) == {})

# [3]
sym = dict(WANT2)
sym[19] = 10
cs = cdarts.cup_seams(41, sym)
check("[3] two halves", sorted(cs) == ["seam_cup_0", "seam_cup_1"], sorted(cs))
check("[3] seam_cup_0 = [302, 344, 386, 428, 429, 430]", cs.get("seam_cup_0") == (1, [302, 344, 386, 428, 429, 430]),
      cs.get("seam_cup_0"))
check("[3] seam_cup_1 = [430, 431, 432, 392, 352, 312]", cs.get("seam_cup_1") == (1, [430, 431, 432, 392, 352, 312]),
      cs.get("seam_cup_1"))
left, right = cs["seam_cup_0"][1], cs["seam_cup_1"][1]
check("[3] the shared centre point 430", left[-1] == right[0] == 430)
check("[3] mirror: column 20 - k and 20 + k on the same row",
      all(left[-1 - k] // 41 == right[k] // 41 and left[-1 - k] % 41 == 20 - k and right[k] % 41 == 20 + k
          for k in range(6)))
check("[3] no back-step: each half's columns rise one by one",
      all(b % 41 - a % 41 == 1 for h in (left, right) for a, b in zip(h, h[1:])))
check("[3] a run ending on the centre column stays one line",
      cdarts.cup_seams(41, {c: 8 for c in range(15, 21)}) == {"seam_cup_0": (1, [8 * 41 + c for c in range(15, 21)])})
check("[3] a run not reaching it stays one line",
      cdarts.cup_seams(41, {c: 8 for c in range(2, 6)}) == {"seam_cup_0": (1, [8 * 41 + c for c in range(2, 6)])})

# [4]
check("[4] SEAM_CROSS_SMOOTH 6", ctp.SEAM_CROSS_SMOOTH == 6)
lh = [(0, 0), (5, 8), (10, 4)]
rh = [(20 - x, y) for x, y in lh[::-1]]
check("[4] the right half is the mirror: [(10, 4), (15, 8), (20, 0)]", rh == [(10, 4), (15, 8), (20, 0)])
check("[4] _forward_points keeps every point of both halves",
      np.allclose(ctp._forward_points(lh), lh) and np.allclose(ctp._forward_points(rh), rh))
dl = ctp._smooth_points(ctp._forward_points(lh), ctp.SEAM_CROSS_SMOOTH)
dr = ctp._smooth_points(ctp._forward_points(rh), ctp.SEAM_CROSS_SMOOTH)
check("[4] left half drawn [(0, 0), (5, 2.09375), (10, 4)]", np.allclose(dl, [[0, 0], [5, 2.09375], [10, 4]]), dl)
check("[4] right half drawn [(10, 4), (15, 2.09375), (20, 0)]", np.allclose(dr, [[10, 4], [15, 2.09375], [20, 0]]), dr)
check("[4] one shared end point (10, 4)", np.allclose(dl[-1], dr[0]) and np.allclose(dl[-1], [10, 4]))
t_in, t_out = dl[-1] - dl[-2], dr[1] - dr[0]
check("[4] mirrored tangents (5, 1.90625) / (5, -1.90625)",
      np.allclose(t_in, [5, 1.90625]) and np.allclose(t_out, [5, -1.90625]), (t_in, t_out))
v7 = [(410.098, 309.381), (421.642, 323.915), (431.760, 335.561), (422.107, 348.281), (427.696, 317.391),
      (439.141, 304.171), (451.305, 258.225)]
f7 = ctp._forward_points(v7)
check("[4] v7's line: the two back-stepping points dropped",
      np.allclose(f7, [v7[0], v7[1], v7[2], v7[5], v7[6]]), f7)
check("[4] v7's kink: the arcs met 31.39 px (1.63 cm) apart in height",
      abs((335.561 - 304.171) - 31.39) < 1e-9 and abs(31.39 / 19.21 - 1.634) < 1e-3)

# [5]
ns, gd = load_build(BUILD.read_text())
check("[5] CUP_UNDER_M 0.12", ns.get("CUP_UNDER_M") == 0.12, ns.get("CUP_UNDER_M"))
gd.body_radius = uneven
got5 = ns["under_cup_rows"](SPEC5, None, (0.0, 0.0))
check("[5] an uneven body: the mirror puts both arcs on row 2", got5 == {1: 2, 2: 2, 3: 2}, got5)

# [6]
check("[6] CORSET_VERSION 9, SEAM_VERSION 3", gt.CORSET_VERSION == 9 and ctp.SEAM_VERSION == 3,
      (gt.CORSET_VERSION, ctp.SEAM_VERSION))

# [7]
OLD = "b309f93ec"
r_d = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{DARTS}"], capture_output=True, text=True)
r_b = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/blender/scripts/garment_template_build.py"],
                     capture_output=True, text=True)
if r_d.returncode != 0 or r_b.returncode != 0:
    print(f"SKIP [7] {OLD} not in this checkout")
else:
    old_d = {}
    exec(compile(r_d.stdout, f"{OLD}:{DARTS}", "exec"), old_d)
    check(f"[7] {OLD}: no centre_cup_rows", "centre_cup_rows" not in old_d)
    old_cs = old_d["cup_seams"](41, sym)
    check(f"[7] {OLD}: one line through all 11 columns, no shared point",
          sorted(old_cs) == ["seam_cup_0"] and len(old_cs["seam_cup_0"][1]) == 11, old_cs)
    ons, ogd = load_build(r_b.stdout)
    ogd.body_radius = uneven
    old5 = ons["under_cup_rows"](SPEC5, None, (0.0, 0.0))
    check(f"[7] {OLD}: under_cup_rows uneven {{1: 3, 2: 2, 3: 2}}", old5 == {1: 3, 2: 2, 3: 2}, old5)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
