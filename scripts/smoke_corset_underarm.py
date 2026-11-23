"""Corset v5/v6 (reviews 2026-11-23): the top edge under the arms runs under the fold to the arm (``underarm_edge``), the
front runs from the cup into the panel as a stiff strip (``bone_bend``), and the whole top edge and the front's bend
are gated (``judge_build``). The helpers are taken out of the Blender script by ``ast`` and run on an analytic body
(``gd.body_radius`` stubbed). No server, no world DB, no Blender. Every number below is derived by hand.

[1] ``skin_flare`` / ``skin_slope`` (UNDERARM_BELOW_M 0.015 / 0.03): a body whose radius grows linearly
    r = 0.10 + 0.5 (z - 1) has no flare (r0 - (r1 + (r1 - r2) x 0.015 / 0.015) = 0) and the slope 0.5. A body
    r = 0.10 + 10 (z - 1.2)^2 over 1.2 (0.10 under it) at z 1.23: r0 = 0.109, r1 (1.215) = 0.10225, r2 (1.20) = 0.10
    -> flare 0.109 - (0.10225 + 0.00225) = 0.0045, slope (0.109 - 0.10) / 0.03 = 0.3.
[2] ``underarm_edge`` (v6) on 5 columns (row_y[0] 1.30, no drops, front columns 1..3 with chest tissue, no dip). Ring:
    back 0..4 (angles 0, pi/4, pi/2, 3pi/4, pi), then front 1..3 (locked: tissue). The body is r = 0.10 everywhere but
    within 0.1 rad of pi/2 (back column 2), where it is 0.10 + 10 (z - 1.25)^2 over 1.25. Back column 2 from 1.30 down
    in 2 mm steps, a = z - 1.25: while all three points lie over 1.25 the flare is 10 x 2 x 0.015^2 = 0.0045 > 0.0025;
    a 0.016 (z 1.266): 10 x 0.016^2 - 2 x 10 x 0.001^2 = 0.00254 > 0.0025; a 0.014 (z 1.264, r1 and r2 under 1.25):
    10 x 0.014^2 = 0.00196 <= 0.0025, slope 0.00196 / 0.03 = 0.065 <= 0.6 -> need 1.30 - 1.264 = 0.036 (18 steps).
    needs [0, 0, 0.036, 0, 0 | 0, 0, 0]; back 2 is its own mirror (pi/2 -> pi/2), so the mirror max changes nothing.
    Spread by the raised cosine (``UNDERARM_SPREAD_COLS`` set to 2 here: weight 1 at 0 columns, 0.5 (1 + cos pi/2)
    = 0.5 at 1, 0 at 2): [0, 0.018, 0.036, 0.018, 0 | 0, 0, 0] (front columns locked: 0).
    Smooth the edge height (1, 2, 1) / 4 — in drops: the mean of the neighbours, never under the need; the ring wraps,
    so back 0's neighbours are front 3 (locked, 0) and back 1, back 4's are back 3 and front 1 (locked, 0):
      1st: back 0 (0 + 0 + 0.018) / 4 = 0.0045, back 1 (0 + 0.036 + 0.036) / 4 = 0.018, back 2 (0.018 + 0.072
           + 0.018) / 4 = 0.027 -> its need 0.036, back 3 0.018, back 4 0.0045
      2nd: back 0 (0 + 0.009 + 0.018) / 4 = 0.00675, back 1 (0.0045 + 0.036 + 0.036) / 4 = 0.019125, back 2 0.027 ->
           0.036, back 3 0.019125, back 4 0.00675.
    (two passes: ``UNDERARM_SMOOTH_PASSES`` is set to 2 for this derivation; the shipped 10 columns / 8 passes are
    checked for the shape: back 2 at its need, symmetric, falling away from it, wider than the derivation.)
    (corset v7's side blend — ``side_blend``, its own derivation in ``smoke_corset_side.py`` — is switched off here:
    ``SIDE_BLEND_RAD`` set to an empty window.)
    No smoothed column lies on the fold (the fold is at back 2 only) -> done. top_drop back
    [0.00675, 0.019125, 0.036, 0.019125, 0.00675]; the side seams: front 4 = back 0, front 0 = back 4 (0.00675);
    front 1..3 0. lowered_cols 5, max_drop_m 0.036. Mirror: the same fold at back 1 only (angle pi/4, mirror back 3)
    gives back 1 and back 3 the same drop.
[3] ``bone_bend`` on 5 heights 0.04 .. 0 (even 1 cm: the weights scale every row alike, the solution is that of the
    plain second differences), r0 fixed 0.01, r3 = r4 = 0 fixed, lo 0:
    E = (a - 2 r1 + r2)^2 + (r1 - 2 r2)^2 + r2^2; dE/dr1 = 0 -> 10 r1 - 8 r2 = 4a; dE/dr2 = 0 -> 2a - 8 r1 + 12 r2 = 0
    -> r2 = 3a/14 = 0.0021429, r1 = 4a/7 = 0.0057143 (both over lo: nothing pressed).
    With lo[2] 0.004: r2 is pressed at 0.004, r1 = (4a + 8 x 0.004) / 10 = 0.0072; dE/dr2 there
    = 2 (0.01 - 0.0144 + 0.004) - 4 (0.0072 - 0.008) + 2 x 0.004 = 0.0104 > 0 (it pushes down): stays pressed.
    v6 pull, on 3 heights 0.02, 0.01, 0 (h 0.01; the row of D is (1, -2, 1) / h^2 x sqrt(h) = (1e3, -2e3, 1e3)),
    r0 = a = 0.01 and r2 = 0 fixed, lo 0, r1's spacing 0.01: E = 1e6 (a - 2 r1)^2 + 0.01 pull r1^2;
    dE/dr1 = -4e6 (a - 2 r1) + 0.02 pull r1 = 0 -> r1 = 4e6 a / (8e6 + 0.02 pull): pull 0 -> a/2 = 0.005,
    pull 4e8 -> a/4 = 0.0025 (the same with the weights given per point, [0, 4e8, 0]).
[4] ``judge_build`` (garment_template): CORSET_VERSION 9; CORSET_FOLD_DEG 55: front_fold max 56 fails (a gate),
    47 ok; edge_loop_gap max 2.3 > 2 fails, edge_loop_flare max 1.12 <= 3 ok (gates on max_mm).
[5] Fails on the old code: at 65bf47a3a ``CORSET_MAX_MM`` had no edge_loop_gap / edge_loop_flare and the build script
    no ``underarm_edge`` — the flaps (a 5-17 mm flare under the arms) passed every gate there. At bbf0617eb (v5, the
    review's BEFORE) the build script spans the cleavage with the convex hull (``_hull_radius``), has no
    ``UNDERARM_SPREAD_COLS`` (each column's own need: the V beside the side seam) and no ``BONE_PULL``.

Usage: ./.venv/bin/python scripts/smoke_corset_underarm.py
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

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-underarm-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


BUILD = ROOT / "app" / "blender" / "scripts" / "garment_template_build.py"
WANT = {"skin_flare", "skin_slope", "underarm_edge", "bone_bend", "side_blend", "_smoothstep", "_angle_off"}
CONSTS = {"UNDERARM_FLARE_M", "UNDERARM_BELOW_M", "UNDERARM_STEP_M", "UNDERARM_DROP_MAX_M", "UNDERARM_SLOPE_MAX",
          "UNDERARM_SMOOTH_PASSES", "UNDERARM_SPREAD_COLS", "SIDE_BLEND_RAD", "SIDE_CUP_DROP_M", "SIDE_BLEND_PASSES"}


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
check("constants", (ns["UNDERARM_FLARE_M"], ns["UNDERARM_BELOW_M"], ns["UNDERARM_STEP_M"], ns["UNDERARM_DROP_MAX_M"],
                    ns["UNDERARM_SLOPE_MAX"], ns["UNDERARM_SMOOTH_PASSES"], ns["UNDERARM_SPREAD_COLS"])
      == (0.0025, (0.015, 0.03), 0.002, 0.08, 0.6, 8, 10))

# [1]
gd.body_radius = lambda bt, c, a, z: 0.10 + 0.5 * (z - 1.0)
check("[1] linear skin: no flare", abs(ns["skin_flare"](None, None, 0.0, 1.2)) < 1e-12)
check("[1] linear skin: slope 0.5", abs(ns["skin_slope"](None, None, 0.0, 1.2) - 0.5) < 1e-9)
gd.body_radius = lambda bt, c, a, z: 0.10 + 10 * max(0.0, z - 1.2) ** 2
f1 = ns["skin_flare"](None, None, 0.0, 1.23)
check("[1] curved skin: flare 0.0045", abs(f1 - 0.0045) < 1e-9, f1)
check("[1] curved skin: slope 0.3", abs(ns["skin_slope"](None, None, 0.0, 1.23) - 0.3) < 1e-9)

# [2]
gd.body_radius = lambda bt, c, a, z: 0.10 + (10 * max(0.0, z - 1.25) ** 2 if abs(a - math.pi / 2) < 0.1 else 0.0)
def spec5():
    return {"cols": 5, "row_y": [1.30], "top_drop": {"front": [0.0] * 5, "back": [0.0] * 5},
            "cup_edge": {"tissue_cols": [1, 2, 3], "dip": [0.0] * 5}}


spec = spec5()
SIDE = ns["SIDE_BLEND_RAD"]
ns["SIDE_BLEND_RAD"] = (math.pi, math.pi)  # v7's side blend left out of the v6 derivation (smoke_corset_side.py)
ns["UNDERARM_SMOOTH_PASSES"] = 2          # the hand derivation above: two passes, a spread of 2 columns
ns["UNDERARM_SPREAD_COLS"] = 2
res = ns["underarm_edge"](spec, None, None)
back = spec["top_drop"]["back"]
want = [0.00675, 0.019125, 0.036, 0.019125, 0.00675]
check("[2] back drops", all(abs(a - b) < 1e-5 for a, b in zip(back, want)), back)
front = spec["top_drop"]["front"]
check("[2] side seams synced, tissue columns untouched", abs(front[0] - 0.00675) < 1e-5
      and abs(front[4] - 0.00675) < 1e-5 and front[1:4] == [0.0, 0.0, 0.0], front)
check("[2] lowered_cols 5, max_drop 0.036", res["lowered_cols"] == 5 and abs(res["max_drop_m"] - 0.036) < 1e-6, res)
gd.body_radius = lambda bt, c, a, z: 0.10 + (10 * max(0.0, z - 1.25) ** 2 if abs(a - math.pi / 4) < 0.1 else 0.0)
specm = spec5()
ns["underarm_edge"](specm, None, None)
bm = specm["top_drop"]["back"]
check("[2] a fold on one side only (back 1) lowers its mirror (back 3) alike", abs(bm[1] - bm[3]) < 1e-9
      and bm[1] >= 0.036 - 1e-9, bm)
gd.body_radius = lambda bt, c, a, z: 0.10 + (10 * max(0.0, z - 1.25) ** 2 if abs(a - math.pi / 2) < 0.1 else 0.0)
ns["UNDERARM_SMOOTH_PASSES"] = 8          # the shipped passes and spread: one even scoop round the fold
ns["UNDERARM_SPREAD_COLS"] = 10
spec8 = spec5()
ns["underarm_edge"](spec8, None, None)
b8, f8 = spec8["top_drop"]["back"], spec8["top_drop"]["front"]
check("[2] 8 passes: back 2 keeps its need 0.036, symmetric, falling away from it, tissue columns 0",
      abs(b8[2] - 0.036) < 1e-6 and abs(b8[1] - b8[3]) < 1e-9 and abs(b8[0] - b8[4]) < 1e-9
      and b8[2] > b8[1] > b8[0] > 0 and f8[1:4] == [0.0, 0.0, 0.0], (b8, f8))
check("[2] 8 passes reach wider than 2 (back 0 lower)", b8[0] > want[0], (b8[0], want[0]))
spec0 = {"cols": 5, "row_y": [1.30], "top_drop": {"front": [0.0] * 5}}
check("[2] no back drops yet -> created", ns["underarm_edge"](spec0, None, None) is not None
      and len(spec0["top_drop"]["back"]) == 5)
check("[2] no top_drop -> None", ns["underarm_edge"]({"cols": 5, "row_y": [1.3]}, None, None) is None)

# [3]
z = [0.04, 0.03, 0.02, 0.01, 0.0]
r = ns["bone_bend"](z, [0.01, 0, 0, 0, 0], [0, 3, 4])
check("[3] free strip r1 4a/7, r2 3a/14", abs(r[1] - 0.04 / 7) < 1e-7 and abs(r[2] - 0.03 / 14) < 1e-7, r)
r = ns["bone_bend"](z, [0.01, 0, 0.004, 0, 0], [0, 3, 4])
check("[3] pressed r2 0.004, r1 0.0072", abs(r[2] - 0.004) < 1e-9 and abs(r[1] - 0.0072) < 1e-7, r)
z3 = [0.02, 0.01, 0.0]
r = ns["bone_bend"](z3, [0.01, 0, 0], [0, 2])
check("[3] v6 no pull: r1 a/2 0.005", abs(r[1] - 0.005) < 1e-9, r)
r = ns["bone_bend"](z3, [0.01, 0, 0], [0, 2], 4e8)
check("[3] v6 pull 4e8: r1 a/4 0.0025", abs(r[1] - 0.0025) < 1e-9, r)
r = ns["bone_bend"](z3, [0.01, 0, 0], [0, 2], [0.0, 4e8, 0.0])
check("[3] v6 pull per point [0, 4e8, 0]: r1 0.0025", abs(r[1] - 0.0025) < 1e-9, r)

# [4]
check("[4] CORSET_VERSION 9, CORSET_FOLD_DEG 55", (gt.CORSET_VERSION, gt.CORSET_FOLD_DEG) == (9, 55.0))
rows = {x["check"]: x for x in gt.judge_build({"fit_gap": {"front_fold": {"max_deg": 56.0}}})}
check("[4] fold 56 > 55 fails (gate)", not rows["front_fold_max_deg"]["ok"] and rows["front_fold_max_deg"]["gate"])
rows = {x["check"]: x for x in gt.judge_build({"fit_gap": {"front_fold": {"max_deg": 47.0}}})}
check("[4] fold 47 ok", rows["front_fold_max_deg"]["ok"])
rows = {x["check"]: x for x in gt.judge_build({"fit_gap": {"edge_loop_gap": {"max_mm": 2.3},
                                                            "edge_loop_flare": {"max_mm": 1.12}}})}
check("[4] edge_loop_gap 2.3 > 2 fails (gate)", not rows["gap_edge_loop_gap_max_mm"]["ok"]
      and rows["gap_edge_loop_gap_max_mm"]["gate"])
check("[4] edge_loop_flare 1.12 ok", rows["gap_edge_loop_flare_max_mm"]["ok"])
check("[4] no fold measure, no fold row", "front_fold_max_deg" not in {x["check"] for x in gt.judge_build({})})

# [5]
OLD = "65bf47a3a"


def show(path):
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


old_gt = show("app/core/garment_template.py")
old_build = show("app/blender/scripts/garment_template_build.py")
if old_gt is None or old_build is None:
    print(f"SKIP [5] {OLD} not in this checkout")
else:
    old_max = next(ast.literal_eval(n.value) for n in ast.parse(old_gt).body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "CORSET_MAX_MM" for t in n.targets))
    check(f"[5] {OLD}: no edge_loop gates", "edge_loop_gap" not in old_max and "edge_loop_flare" not in old_max)
    check(f"[5] {OLD}: no underarm_edge", "def underarm_edge" not in old_build)
V5 = "bbf0617eb"
r5 = subprocess.run(["git", "-C", str(ROOT), "show", f"{V5}:app/blender/scripts/garment_template_build.py"],
                    capture_output=True, text=True)
if r5.returncode != 0:
    print(f"SKIP [5] {V5} not in this checkout")
else:
    check(f"[5] {V5}: the hull over the cleavage, each column its own underarm need, no pull",
          "def _hull_radius" in r5.stdout and "UNDERARM_SPREAD_COLS" not in r5.stdout and "BONE_PULL" not in r5.stdout)
    now = BUILD.read_text()
    check("[5] now: the closed section, the spread, the pull", "def _hull_radius" not in now
          and "def _close_section" in now and "UNDERARM_SPREAD_COLS" in now and "BONE_PULL" in now)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
