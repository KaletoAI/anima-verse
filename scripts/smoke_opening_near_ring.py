"""Smoke: a recess opening's seed lies behind the ring's front NEAR it, not only behind the ring's median (Ruling A114).

Usage:
    ./.venv/bin/python scripts/smoke_opening_near_ring.py

No server, no world DB, no hub. ``garment_fit.opening_lining`` on synthetic meshes plus ``opening_may_change`` /
``expected_fit_version``. Every number below is derived by hand.

FRAME (as smoke_opening_shallow_lining). Garment x -0.20 .. 0.20, y 0 .. 0.60, grid step 0.005; masks 400 x 400,
the garment rows 50 .. 349, cols 100 .. 299 -> 0.002 m per px; the opening rows 150 .. 299, cols 175 .. 224
(x -0.05 .. 0.048, y 0.10 .. 0.40), 7476 px after the 3 px opening. A BACK panel at z -0.10 everywhere.

[1] THE OPEN JACKET (Kai's ``def323f99985``, reduced): a FRONT panel with a hole only |x| < 0.02, 0.10 < y < 0.40 —
    its edges overlap the opening by 0.03 m a side, as the mesher's panel edges overlap the worn view's opening — at
    z(y) = 0.10 for y <= 0.25 and 0.10 - (y - 0.25) above (the collar curving back toward the neck: -0.05 at
    the top of the opening, -0.25 at the top of the panel). Through the opening the only real inside is the back panel, one layer.
    The ring's median front is the chest (most of the ring lies at y <= 0.25 or beside it); the inside's median
    front lies behind it, the recess is >= OPEN_RECESS_PX: ``by: recess``. A collar vertex at y = 0.25 + d is
    deep (old rule) once 0.10 - z = d >= 0.5 * recess px * 0.002 m. Near ring: the ring's front within
    OPEN_LOCAL_PX 40 px (0.08 m) of it follows the same linear z(y), so its mean is the vertex's own depth
    except where the window reaches below y 0.25 (z clipped at 0.10): that excess averages
    (0.08 - d)^2 / 0.32 m at most; with the recess >= 42.5 px measured here a deep vertex has d >= 0.0425 -> excess <= 0.0375^2 / 0.32 = 0.0044 m = 2.2 px < OPEN_STEP_PX 10.
    So: old code -> seeds > 0 and faces > 0 left out of the collar (the hole); new code -> 0 seeds, 0 faces.
[2] A REAL INSIDE (the deep V): a flat front z 0.10 with the hole |x| < 0.05, 0.10 < y < 0.40, an inside panel at
    z 0.0, x -0.06 .. 0.06, y 0.10 .. 0.40 (25 x 61 = 1525 vertices). Its depth is
    0.10 / 0.002 = 50 px behind the ring (recess 50 >= 15, deep: 50 >= 25) and 50 px behind the ring near it
    (>= 10): every one of its vertices on the front in the opening is a seed — x -0.045 .. 0.045 (19 columns; at
    |x| = 0.05 the front panel's rim covers it), y 0.105 .. 0.395 (59 rows; y 0.40 is under the rim, y 0.10 outside
    the opening): 19 x 59 = 1121 vertices, 18 x 58 x 2 = 2088 faces; the rest of the panel lies under the front and
    is no front-most surface, so the growth stops there — old and new the same vertices.
[3] Due rule: FIT_VERSION clothing 18; a version 17 record is current unless its opening report has a recess
    component with a seed (or without a ``seeds`` number): {seeds 450} -> 18, {seeds 0} -> 17, a ``shown``
    component -> 17, no opening report -> 17, version 16 with sleeves -> 18.
"""
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import garment_fit as gf  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail != "" else ""))
    if not ok:
        FAILED.append(label)


STEP = 0.005


def grid(zf, skip=None, x0=-0.2, x1=0.2, y0=0.0, y1=0.6):
    xs = np.round(np.arange(x0, x1 + 1e-9, STEP), 4)
    ys = np.round(np.arange(y0, y1 + 1e-9, STEP), 4)
    X, Y = np.meshgrid(xs, ys)
    P = np.stack([X.ravel(), Y.ravel(), zf(X.ravel(), Y.ravel())], 1)
    nx, F = len(xs), []
    for j in range(len(ys) - 1):
        for i in range(nx - 1):
            if skip and skip((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2):
                continue
            a = j * nx + i
            F += [[a, a + 1, a + nx + 1], [a, a + nx + 1, a + nx]]
    F = np.array(F)
    used = np.unique(F)
    new = np.full(len(P), -1)
    new[used] = np.arange(len(used))
    return P[used], new[F]


def join(*parts):
    P, F, n = [], [], 0
    for p, f in parts:
        P.append(p)
        F.append(f + n)
        n += len(p)
    return np.vstack(P), np.vstack(F)


gm = np.zeros((400, 400), bool)
gm[50:350, 100:300] = True
op = np.zeros_like(gm)
op[150:300, 175:225] = True
back = grid(lambda x, y: np.full_like(x, -0.10))

# [1] the open jacket
front = grid(lambda x, y: 0.10 - np.clip(y - 0.25, 0, None), skip=lambda x, y: abs(x) < 0.02 and 0.10 < y < 0.40)
P, F = join(front, back)
lin, rep = gf.opening_lining(P, F, op, gm, None)
comp = rep["components"][0] if rep["components"] else {}
check("[1] the opening is a recess one (>= 21.25 px)", comp.get("by") == "recess" and comp["recess_px"] >= 21.25, comp)
check("[1] new: no seed", comp.get("seeds") == 0, comp)
check("[1] new: no face left out of the collar", rep["faces"] == 0, rep["faces"])

# the old rule (pinned commit, before Ruling A114)
OLD = "bb531a59d"
import importlib.util  # noqa: E402
import subprocess  # noqa: E402
src = subprocess.run(["git", "show", f"{OLD}:app/core/garment_fit.py"], cwd=ROOT, capture_output=True, text=True,
                     check=True).stdout
spec = importlib.util.spec_from_loader("garment_fit_before_a114", loader=None)
old = importlib.util.module_from_spec(spec)
sys.modules["garment_fit_before_a114"] = old
exec(compile(src, f"{OLD}:app/core/garment_fit.py", "exec"), old.__dict__)
lin_o, rep_o = old.opening_lining(P, F, op, gm, None)
comp_o = rep_o["components"][0]
check(f"[1] old ({OLD}): seeds on the collar and faces left out (the hole)",
      comp_o.get("seeds", 0) > 0 and rep_o["faces"] > 0, (comp_o, rep_o["faces"]))

# [2] a real inside
front2 = grid(lambda x, y: np.full_like(x, 0.10), skip=lambda x, y: abs(x) < 0.05 and 0.10 < y < 0.40)
inside = grid(lambda x, y: np.full_like(x, 0.0), x0=-0.06, x1=0.06, y0=0.10, y1=0.40)
P2, F2 = join(front2, inside, back)
lin2, rep2 = gf.opening_lining(P2, F2, op, gm, None)
n_front = len(front2[0])
check("[2] 1121 inside-panel vertices exactly", int(lin2.sum()) == 1121
      and int(lin2[n_front:n_front + 1525].sum()) == 1121, int(lin2.sum()))
check("[2] 2088 faces left out", rep2["faces"] == 2088, rep2["faces"])
lin2o, rep2o = old.opening_lining(P2, F2, op, gm, None)
check("[2] old: the same vertices", bool((lin2o == lin2).all()), (int(lin2o.sum()), rep2o))

# [3] due rule
def rec(v, opening=None, share=0.3):
    r = {"kind": "clothing", "fit_version": v, "report": {"transfer": {"sleeve_share": share}}}
    if opening is not None:
        r["report"]["opening"] = opening
    return r


seeded = {"components": [{"by": "recess", "dropped": True, "seeds": 450}], "faces": 1181}
unseeded = {"components": [{"by": "recess", "dropped": True, "seeds": 0}], "faces": 0}
shown = {"components": [{"by": "shown", "dropped": True}], "faces": 2880}
nonum = {"components": [{"by": "recess", "dropped": True}], "faces": 12}
cases = [(rec(17, seeded), 18), (rec(17, unseeded), 17), (rec(17, shown), 17), (rec(17), 17),
         (rec(17, nonum), 18), (rec(16), 18), (rec(18, seeded), 18)]
got = [gf.expected_fit_version(r) for r, _w in cases]
check("[3] FIT_VERSION clothing 18", gf.FIT_VERSION["clothing"] == 18, gf.FIT_VERSION)
check("[3] due rule", got == [w for _r, w in cases], got)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
