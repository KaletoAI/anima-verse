"""Round 2026-11-25 (Lirien's leather top, track D): a top with straps and a straight or sweetheart edge is the corset
top's shell (``corset_shell``, ``cup_edge``, ``underarm_edge``) plus two straps on the bra's path (``shell_straps``),
no longer a bodice yoke cut down to the band (stair steps, spikes under the arms, a back 5-8 cm off the body). The
helpers are taken out of the Blender script by ``ast`` and run on analytic bodies (``gd.body_radius`` /
``btree.find_nearest`` stubbed). No server, no world DB, no Blender. Every number below is derived by hand.

[1] ``underarm_edge``'s roof (a corset top with straps only). 5 columns, row_y[0] 1.30, no drops, front column 2
    with chest tissue (locked), no dip. Ring: back 0..4 (angles 0, pi/4, pi/2, 3pi/4, pi), front 1..3 (5pi/4, 3pi/2,
    7pi/4). Bodies (``r`` metres, ``a`` = angle):
    - back 2 (within 0.1 rad of pi/2): the fold to the arm r = 0.10 + 10 (z - 1.25)^2 over 1.25 (as in
      smoke_corset_underarm.py [2]: its need is 0.036);
    - front 1 and front 3 (within 0.1 rad of 5pi/4, 7pi/4): the underside of the chest's outer part, r = 0.10 +
      clamp(z - 1.249, 0, 0.03) — 0.10 under 1.249, 0.13 over 1.279, rising 1 : 1 between;
    - 0.10 everywhere else.
    Front 1 at its own edge 1.30: r0 0.13, r1 (1.285) 0.13, r2 (1.27) 0.121 -> flare 0.13 - (0.13 + 0.009) < 0, slope
    (0.13 - 0.121) / 0.03 = 0.3 <= 0.6: its own need 0. The roof scans down in 2 mm steps while the NEXT height is
    clear: over 1.279 with the point 3 cm under it in the band, slope = (0.13 - (0.10 + z - 0.03 - 1.249)) / 0.03
    = (1.309 - z) / 0.03: z 1.298 -> 0.367, 1.296 -> 0.433, 1.294 -> 0.5, 1.292 -> 0.567 (each flare < 0: at 1.292 r1
    (1.277) 0.128, r2 (1.262) 0.113 -> 0.13 - 0.143), 1.290 -> 0.633 > 0.6 (the fold) -> roof 0.008 (mirror front 3
    the same). The spread from back 2 reaches front 1 (3 ring steps) with 0.5 (1 + cos(0.3 pi)) x 0.036 = 0.02858 ->
    capped at 0.008; every smoothing pass averages front 1 with back 4 and the locked front 2: even in the limit
    (back 2 at 0.036, front 1 at 0.008, back 3 / back 4 linear between: 0.02667 / 0.01733) the average
    (0.01733 + 2 x 0.008 + 0) / 4 = 0.00833 lies past the roof -> held at 0.008. Front 1 and front 3: 0.008.
    WITHOUT straps (strapless, unchanged): the spread's 0.02858 puts the edge at 1.27142, where the slope is
    (0.12242 - 0.10) / 0.03 = 0.747 (the fold) -> on down in 2 mm steps until it is clear under the fold: slope
    (z - 1.249) / 0.03 <= 0.6 needs z <= 1.267, and the flare (r0 - r1 with r1, r2 under 1.249 = 0.10) <= 0.0025
    needs z <= 1.2515 -> 1.30 - 0.02858 - 0.002 k <= 1.2515 -> k = 10, a drop of 0.04858 (the 4.9 cm V of the
    review, 8 cm on Lirien's body).
[2] ``cup_edge``'s angle cap (straps only): a body with chest tissue all round (r 0.15 at the apex height, 0.10
    elsewhere: 0.15 - 0.10 = 0.05 >= tissue_m 0.03), 41 columns at off-front pi |c - 20| / 40: with straps
    the columns up to CUP_TISSUE_OFF_RAD 58 degrees, |c - 20| x 4.5 <= 58 -> |c - 20| <= 12 -> columns 8..32, 25 of
    them; strapless all 41 (unchanged).
[3] ``seam_mid``: 2 rows x 3 columns, panels [front, back]; front ids 0..5 (row r, column c: 3 r + c), back 6..11.
    The seams: back column 0 with front column 2, back column 2 with front column 0, each row. Front (0,0,0)
    (0.1,0,0) (0.2,0,0) / (0,0,1) (0.1,0,1) (0.2,0,1); back (0.2,0.004,0) (0.1,0.1,0) (0,0.002,0) / (0.2,0.004,1)
    (0.1,0.1,1) (0,0.002,1) -> front 2 = back 0 = (0.2, 0.002, 0), front 0 = back 2 = (0, 0.001, 0), the same at z 1;
    front 1 and back 1 unchanged.
[4] ``_strap_outside`` on the plane z = 0 (normal +z), clear 0.0015: a point 2 mm under it -> z 0.0015; a point
    3 mm over it -> unchanged; on a corner of two faces (z = 0 for x <= 0, normal +z; x = 0 for z <= 0, normal +x)
    the point (-0.0005, 0, -0.0004) lies 0.4 mm from z = 0 and 0.5 mm from x = 0: it moves out along +z by
    0.0015 + 0.0004 to z 0.0015; there z = 0 lies 1.5 mm off, x = 0's edge hypot(0.5, 1.5) = 1.58 mm -> done.
[5] Keys pinned to f70077f3c (``git archive`` of that commit, run in a subprocess): a strapless corset top keeps its
    drape key (``tsig``) and its cut key (``cut_sig``) byte for byte; a top with straps changes both (it carries
    ``corset_straps``) — and its prompt kind is "strapless" (a corset's panels), its piece name "corset top with
    shoulder straps".

Usage: ./.venv/bin/python scripts/smoke_corset_top_straps.py
"""
import ast
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-top-straps-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


BUILD = ROOT / "app" / "blender" / "scripts" / "garment_template_build.py"
WANT = {"skin_flare", "skin_slope", "underarm_edge", "side_blend", "_smoothstep", "_angle_off", "chest_tissue",
        "edge_clears", "cup_edge", "seam_mid", "_strap_outside"}
CONSTS = {"UNDERARM_FLARE_M", "UNDERARM_BELOW_M", "UNDERARM_STEP_M", "UNDERARM_DROP_MAX_M", "UNDERARM_SLOPE_MAX",
          "UNDERARM_SMOOTH_PASSES", "UNDERARM_SPREAD_COLS", "SIDE_BLEND_RAD", "SIDE_CUP_DROP_M", "SIDE_BLEND_PASSES",
          "CUP_EDGE_STEP_M", "CUP_EDGE_LOOK_M", "CUP_UNDER_M", "CUP_TISSUE_OFF_RAD", "SHELL_STRAP_OUT_ROUNDS"}


def load(src):
    tree = ast.parse(src)
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in WANT)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in n.targets))]
    gd = types.SimpleNamespace(body_radius=None)
    ns = {"math": math, "np": np, "gd": gd, "Vector": lambda v: np.asarray(v, float)}
    exec(compile(ast.Module(nodes, []), str(BUILD), "exec"), ns)
    return ns, gd


ns, gd = load(BUILD.read_text())
check("helpers present", WANT <= set(ns), sorted(WANT - set(ns)))
check("constants", (ns["UNDERARM_SPREAD_COLS"], ns["UNDERARM_SMOOTH_PASSES"], round(math.degrees(ns["CUP_TISSUE_OFF_RAD"]), 6))
      == (10, 8, 58.0))


# [1]
def body1(_bt, _c, a, z):
    if abs(a - math.pi / 2) < 0.1:
        return 0.10 + 10 * max(0.0, z - 1.25) ** 2
    if abs(a - 5 * math.pi / 4) < 0.1 or abs(a - 7 * math.pi / 4) < 0.1:
        return 0.10 + min(0.03, max(0.0, z - 1.249))
    return 0.10


def spec5(straps):
    s = {"cols": 5, "row_y": [1.30], "top_drop": {"front": [0.0] * 5, "back": [0.0] * 5},
         "cup_edge": {"tissue_cols": [2], "dip": [0.0] * 5}}
    if straps:
        s["corset_straps"] = {"style": "corset"}
    return s


gd.body_radius = body1
s1 = spec5(True)
ns["underarm_edge"](s1, None, None)
f1 = s1["top_drop"]["front"]
check("[1] straps: front 1 / front 3 held at the roof 0.008", abs(f1[1] - 0.008) < 1e-6 and abs(f1[3] - 0.008) < 1e-6,
      f1)
check("[1] straps: the fold to the arm still lowers back 2 by its need 0.036",
      abs(s1["top_drop"]["back"][2] - 0.036) < 1e-6, s1["top_drop"]["back"])
check("[1] straps: the tissue column untouched", f1[2] == 0.0, f1)
s0 = spec5(False)
ns["underarm_edge"](s0, None, None)
f0 = s0["top_drop"]["front"]
check("[1] strapless (unchanged): front 1 / front 3 go on under the fold, >= 0.04858",
      f0[1] >= 0.04858 - 1e-6 and abs(f0[1] - f0[3]) < 1e-9, f0)

# [2]
APEX = 1.25


def body2(_bt, _c, _a, z):
    return 0.15 if abs(z - APEX) < 1e-9 else 0.10


gd.body_radius = body2


def spec41(straps):
    s = {"cols": 41, "row_y": [1.30], "top_drop": {"front": [0.0] * 41},
         "cup_edge": {"apex_y": APEX, "tissue_m": 0.03, "recede_m": 0.002, "spill_m": 0.001, "dip": [0.0] * 41}}
    if straps:
        s["corset_straps"] = {"style": "corset"}
    return s


s2 = spec41(True)
ns["cup_edge"](s2, None, (0.0, 0.0))
check("[2] straps: tissue columns 8..32", s2["cup_edge"]["tissue_cols"] == list(range(8, 33)),
      s2["cup_edge"]["tissue_cols"])
s2 = spec41(False)
ns["cup_edge"](s2, None, (0.0, 0.0))
check("[2] strapless: all 41 (unchanged)", s2["cup_edge"]["tissue_cols"] == list(range(41)))

# [3]
verts = [(0, 0, 0), (0.1, 0, 0), (0.2, 0, 0), (0, 0, 1), (0.1, 0, 1), (0.2, 0, 1),
         (0.2, 0.004, 0), (0.1, 0.1, 0), (0, 0.002, 0), (0.2, 0.004, 1), (0.1, 0.1, 1), (0, 0.002, 1)]
ns["seam_mid"](verts, {"rows": 2, "cols": 3, "panels": [{"name": "front"}, {"name": "back"}]})


def near(a, b):
    return all(abs(x - y) < 1e-12 for x, y in zip(a, b))


check("[3] seam copies at their middle", near(verts[2], (0.2, 0.002, 0)) and near(verts[6], (0.2, 0.002, 0))
      and near(verts[0], (0, 0.001, 0)) and near(verts[8], (0, 0.001, 0)) and near(verts[5], (0.2, 0.002, 1))
      and near(verts[9], (0.2, 0.002, 1)) and near(verts[3], (0, 0.001, 1)) and near(verts[11], (0, 0.001, 1)), verts)
check("[3] the middle columns untouched", near(verts[1], (0.1, 0, 0)) and near(verts[7], (0.1, 0.1, 0)))


# [4]
class Plane:
    def find_nearest(self, q):
        return np.array([q[0], q[1], 0.0]), np.array([0.0, 0.0, 1.0]), 0, abs(q[2])


class Corner:
    """z = 0 for x < 0 (normal +z) and x = 0 for z < 0 (normal +x): the nearer face."""
    def find_nearest(self, q):
        dz = abs(q[2]) if q[0] <= 0 else math.hypot(q[0], q[2])
        dx = abs(q[0]) if q[2] <= 0 else math.hypot(q[0], q[2])
        if dz <= dx:
            return np.array([min(q[0], 0.0), q[1], 0.0]), np.array([0.0, 0.0, 1.0]), 0, dz
        return np.array([0.0, q[1], min(q[2], 0.0)]), np.array([1.0, 0.0, 0.0]), 1, dx


q = ns["_strap_outside"](Plane(), (0.0, 0.0, -0.002), 0.0015)
check("[4] 2 mm under the plane -> 1.5 mm over it", abs(q[2] - 0.0015) < 1e-12, q)
q = ns["_strap_outside"](Plane(), (0.0, 0.0, 0.003), 0.0015)
check("[4] 3 mm over it -> unchanged", abs(q[2] - 0.003) < 1e-12, q)
q = ns["_strap_outside"](Corner(), (-0.0005, 0.0, -0.0004), 0.0015)
check("[4] corner: out over the nearer face z = 0", abs(q[2] - 0.0015) < 1e-12 and abs(q[0] + 0.0005) < 1e-12, q)

# [5]
STRAPLESS = {"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.1, "length_m": 0.4}
STRAPS = {"kind": "top", "shoulders": "straps", "neckline": "sweetheart", "fit": 0.4, "length_m": 0.27,
          "fabric": "leather_rough"}
PROBE = r"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.core import paths
t = Path(tempfile.mkdtemp())
paths.init(t / "world"); paths.init_instance(t / "instance")
from app.core import garment_template as gt, garment_template_cut as gtc
out = {}
for name, raw in json.loads(sys.argv[2]).items():
    p, _e = gt.validate_params(raw)
    out[name] = [gt.tsig(p, base_sha="base0", texture_sha="tex0", lower=["item_a"]),
                 gtc.cut_sig(p, base_sha="base0", lower=["item_a"])]
print(json.dumps(out))
"""
OLD = "f70077f3c"


def keys(repo):
    r = subprocess.run([sys.executable, "-c", PROBE, str(repo), json.dumps({"strapless": STRAPLESS, "straps": STRAPS})],
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(repo)})
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


old_dir = _SCRATCH / "old"
arc = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", OLD, "app", "shared/templates",
                      "shared/languages"], capture_output=True)
if arc.returncode != 0:
    print(f"SKIP [5] {OLD} not in this checkout")
else:
    old_dir.mkdir()
    tar = _SCRATCH / "old.tar"
    tar.write_bytes(arc.stdout)
    with tarfile.open(tar) as tf:
        tf.extractall(old_dir, filter="data")
    new_k, old_k = keys(ROOT), keys(old_dir)
    check(f"[5] strapless corset: tsig as at {OLD}", new_k["strapless"][0] == old_k["strapless"][0],
          (new_k["strapless"], old_k["strapless"]))
    check(f"[5] strapless corset: cut_sig as at {OLD}", new_k["strapless"][1] == old_k["strapless"][1],
          (new_k["strapless"], old_k["strapless"]))
    check(f"[5] straps: both keys differ from {OLD}", new_k["straps"][0] != old_k["straps"][0]
          and new_k["straps"][1] != old_k["straps"][1], (new_k["straps"], old_k["straps"]))
p_straps, _e = gt.validate_params(STRAPS)
check("[5] straps: a corset top, no bodice, a panel piece", gt.corset_top(p_straps) and gt.corset_straps(p_straps)
      and not gt.has_bodice(p_straps) and gt.panel_piece(p_straps))
check("[5] prompt kind / piece name", gct.prompt_kind(p_straps) == "strapless"
      and gct.piece_name_of(p_straps) == "corset top with shoulder straps")
p_sl, _e = gt.validate_params(STRAPLESS)
check("[5] strapless: no corset_straps", not gt.corset_straps(p_sl) and gt.corset_top(p_sl))

print()
print("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
