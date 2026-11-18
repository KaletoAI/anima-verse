"""Smoke: the geodesic walks of the clothing fit count each mesh edge once — A199 bumps clothing to 20 and keeps
every fit that never walked current (``garment_fit.walk_may_change``; review 06#9).

Usage:
    ./.venv/bin/python scripts/smoke_fit_walk_version.py

No server, no world DB. Every expectation derived by hand:

  Walk (``sleeve_cuffs``, ``SLEEVE_CUFF_REACH_M`` = 0.10 m, k = 1): a row t0..t4 at x = 0, 0.03, .., 0.12 m, one
  row 0.2 m above and one 0.2 m below. Each edge t_i -> t_i+1 is listed as (t_i, t_i+1) by BOTH its faces
  (the upper face and the lower face wind opposite ways). t0 is the sleeve, everything else a cuff candidate, all
  on arm part 1. A detour through the other rows is >= 0.4 m, beyond the reach. Each edge once: t1..t3 lie at
  0.03 / 0.06 / 0.09 <= 0.10 -> 3 cuff vertices; t4 (0.12) is out. Each edge twice (the old sum): 0.06 / 0.12 -> 1.
  [W1] cuffs == {t1, t2, t3}.
  [W2] ``_walk_edges`` lists each undirected edge once: 2 faces (0,1,2), (0,1,3) -> 5 edges.

  Version rule (clothing 20; 19 = ``CLOTHING_WALK_UNCHANGED``):
    [1] v19, transfer sleeve_vertices 12                 -> due: 20
    [2] v19, sleeve_vertices 0, sleeves.blend present    -> due: 20
    [3] v19, sleeve_vertices 0, trunk.blend present      -> due: 20
    [4] v19, sleeve_vertices 0, no blend                 -> current: 19
    [5] v19, no transfer report                          -> due: 20
    [6] v19 shell (no transfer)                          -> current: 19
    [7] v18 room-free, never walked                      -> the room rule keeps 18
    [8] v18 room-free, sleeve_vertices 5                 -> due: 20
    [9] v20 anything                                     -> 20

Pre-fix proof: at 26977eda5 FIT_VERSION["clothing"] == 19 and [W1] gives only t1 (the doubled edges).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_fit as gf  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


check("FIT_VERSION clothing 20", gf.FIT_VERSION["clothing"] == 20, gf.FIT_VERSION)
check("CLOTHING_WALK_UNCHANGED 19", gf.CLOTHING_WALK_UNCHANGED == 19)
check("reach 0.10 m (the walk below assumes it)", abs(gf.SLEEVE_CUFF_REACH_M - 0.10) < 1e-12, gf.SLEEVE_CUFF_REACH_M)

# --- the walk -----------------------------------------------------------------------------------------------------
xs = [0.0, 0.03, 0.06, 0.09, 0.12]
T = [(x, 0.0, 0.0) for x in xs]
U = [(x, 0.2, 0.0) for x in xs]
B = [(x, -0.2, 0.0) for x in xs]
Q = np.array(T + U + B, np.float64)
t, u, b = (lambda i: i), (lambda i: 5 + i), (lambda i: 10 + i)
faces = []
for i in range(4):
    faces += [(t(i), t(i + 1), u(i)), (u(i), t(i + 1), u(i + 1)),     # upper face lists (t_i, t_i+1)
              (t(i), t(i + 1), b(i)), (b(i), t(i + 1), b(i + 1))]     # lower face lists it the same way
sleeve = np.zeros(len(Q), bool)
sleeve[t(0)] = True
upper = np.zeros(len(Q), bool)
cuff = gf.sleeve_cuffs(Q, np.zeros((1, 3)), np.array([1]), np.array(faces), upper, sleeve, 1.0)
check("[W1] cuffs t1, t2, t3", sorted(np.nonzero(cuff)[0].tolist()) == [1, 2, 3], np.nonzero(cuff)[0].tolist())
E = gf._walk_edges(np.array([[0, 1, 2], [0, 1, 3]]))
check("[W2] 5 undirected edges", len(E) == 5 and len({tuple(e) for e in E.tolist()}) == 5, E.tolist())


# --- the version rule ---------------------------------------------------------------------------------------------
def rec(v, transfer=None, shell=False, settings=None):
    inputs = {}
    if shell:
        inputs["mesh_shape"] = "shell"
    if settings is not None:
        inputs["fit_settings"] = settings
    r = {"kind": "clothing", "fit_version": v, "inputs": inputs, "report": {}}
    if transfer is not None:
        r["report"]["transfer"] = transfer
    return r


free = {"allowance": "auto", "depth": 0}
cases = [
    ("[1] sleeve vertices", rec(19, {"sleeve_vertices": 12}), 20),
    ("[2] sleeve blend", rec(19, {"sleeve_vertices": 0, "sleeves": {"blend": {"band_vertices": 3}}}), 20),
    ("[3] trunk blend", rec(19, {"sleeve_vertices": 0, "trunk": {"blend": {"band_vertices": 3}}}), 20),
    ("[4] never walked", rec(19, {"sleeve_vertices": 0, "trunk": {"applied": "generated"}}), 19),
    ("[5] no transfer report", rec(19), 20),
    ("[6] shell", rec(19, shell=True), 19),
    ("[7] v18 room-free, never walked", rec(18, {"sleeve_vertices": 0, "sleeve_share": 0.3}, settings=free), 18),
    ("[8] v18 room-free, sleeve vertices", rec(18, {"sleeve_vertices": 5}, settings=free), 20),
    ("[9] v20", rec(20, {"sleeve_vertices": 7}), 20),
]
for label, r, want in cases:
    got = gf.expected_fit_version(r)
    check(f"{label} -> {want}", got == want, got)

print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL OK")
sys.exit(1 if FAILED else 0)
