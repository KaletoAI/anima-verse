#!/usr/bin/env python3
"""Smoke (no Blender, no server, no world): stage "geometry" — a skirt's / dress's rows below the crotch are wrapped
round the legs' own middle (``garment_template_build.leg_centres`` / ``centre_at``, ``LEG_VERSION``).

Usage:
    ./.venv/bin/python scripts/smoke_geometry_leg_centres.py

The builder imports ``bpy``; its constants and the two functions are read from the source (``ast``) and run with
numpy, on a hand-built body and hand-built girths. Expected values, by hand:

[1] Body: three points on the centre line (x = cx = 0.0), the lowest at z 0.80 -> the crotch; rows from
    0.80 - CROTCH_BELOW_M 0.01 = 0.79 down are re-centred. Rows z = [1.00, 0.82, 0.78, 0.70]. ``radii_of`` gives a
    regular 40-gon round the centre handed in, radius 0.10 for the rows over the crotch and 0.10 + |y - (cy + 0.06)|
    under it (legs 6 cm behind the waist's centre). A regular N-gon of radius R has the girth 2 N R sin(pi / N);
    N = 40: 6.276729 x R. Rows 2 and 3: the shortest girth is at shift +0.06 (0.005 x 12, one of CENTRE_SHIFTS_M),
    0.627673; at shift 0 it is 6.276729 x 0.16 = 1.004277 -> gain 0.376604 >= GIRTH_GAIN_MIN_M 0.02. Shifts before
    the slope: [0, 0, 0.06, 0.06]. Backward pass (SHIFT_SLOPE 0.5): row 1 against row 2, lim = 0.5 x 0.04 = 0.02,
    0.06 - 0.02 = 0.04 > 0 -> row 1 = 0.04; row 0 against row 1, lim 0.5 x 0.18 = 0.09, 0.04 - 0.09 < 0 -> stays 0.
    Forward pass: row 2 against row 1, 0.04 - 0.02 = 0.02 < 0.06 -> stays. Result: row 0 IS the centre object handed in
    (identity, not a copy: its float32 arithmetic stays the same), rows 1..3 = (0, cy + 0.04 / 0.06 / 0.06).
[2] ``centre_at``: z 0.80 lies halfway between row 1 (0.82, +0.04) and row 2 (0.78, +0.06) -> cy + 0.05; z 0.60
    under the last row holds it (+0.06); z 1.20 over the first holds row 0 (+0).
[3] Gate: legs at cy + 0.0025 — shift 0 and shift 0.005 give the same girth (|offset| 0.0025 either way), the
    smallest |shift| of the ties is 0 -> no row gains -> None (the piece keeps its mesh byte for byte).
    Legs at cy + 0.01: gain 6.276729 x 0.01 = 0.062767 >= 0.02 -> re-centred, rows 2 and 3 at +0.01.
[4] A body with no vertex on the centre line (|x - cx| >= CROTCH_X_M 0.015 everywhere) -> None.
"""
import ast
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app" / "blender" / "scripts" / "garment_template_build.py").read_text(encoding="utf-8")
FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


tree = ast.parse(SRC)
ns = {"np": np, "math": math}
want = {"CROTCH_X_M", "CROTCH_BELOW_M", "CENTRE_SHIFTS_M", "GIRTH_TOL_M", "GIRTH_GAIN_MIN_M", "SHIFT_SLOPE"}
for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in want for t in node.targets):
        exec(compile(ast.Module([node], []), "consts", "exec"), ns)
    if isinstance(node, ast.FunctionDef) and node.name in ("leg_centres", "centre_at"):
        exec(compile(ast.Module([node], []), node.name, "exec"), ns)
check("constants read", want <= set(ns), sorted(want - set(ns)))
check("CROTCH_BELOW_M 0.01, SHIFT_SLOPE 0.5, GIRTH_GAIN_MIN_M 0.02, 0.06 is a shift",
      (ns["CROTCH_BELOW_M"], ns["SHIFT_SLOPE"], ns["GIRTH_GAIN_MIN_M"]) == (0.01, 0.5, 0.02)
      and 0.06 in ns["CENTRE_SHIFTS_M"] and 0.0 in ns["CENTRE_SHIFTS_M"])
leg_centres, centre_at = ns["leg_centres"], ns["centre_at"]

CY = -0.03
centre = np.array([0.0, CY], np.float32)
bco = np.array([[0.0, CY, 0.80], [0.0, CY, 1.0], [0.0, CY, 1.2], [0.3, CY, 0.5]])
ROWS = [1.00, 0.82, 0.78, 0.70]
ANG = np.linspace(0.0, 2 * math.pi, 40, endpoint=False)


def girths(legs):
    def radii_of(cen, r):
        rad = 0.10 if ROWS[r] >= 0.79 else 0.10 + abs(cen[1] - (CY + legs))
        return ANG, np.full(40, rad)
    return radii_of


# [1]
rc = leg_centres(bco, centre, ROWS, girths(0.06))
check("[1] re-centred", rc is not None)
shifts = [round(float(c[1]) - CY, 6) for c in rc]
check("[1] shifts [0, 0.04, 0.06, 0.06]", np.allclose(shifts, [0.0, 0.04, 0.06, 0.06], atol=1e-9), shifts)
check("[1] row 0 is the centre object itself", rc[0] is centre)
# [2]
at = centre_at(rc, ROWS)
check("[2] z 0.80 -> +0.05", abs(at(0.80)[1] - (CY + 0.05)) < 1e-9, at(0.80))
check("[2] z 0.60 -> +0.06, z 1.20 -> +0", abs(at(0.60)[1] - (CY + 0.06)) < 1e-9 and abs(at(1.20)[1] - CY) < 1e-6)
# [3]
check("[3] legs at +0.0025 -> None", leg_centres(bco, centre, ROWS, girths(0.0025)) is None)
rc3 = leg_centres(bco, centre, ROWS, girths(0.01))
check("[3] legs at +0.01 -> rows 2, 3 at +0.01", rc3 is not None
      and np.allclose([float(c[1]) - CY for c in rc3[2:]], [0.01, 0.01], atol=1e-9))
# [4]
check("[4] no vertex on the centre line -> None",
      leg_centres(bco + np.array([0.02, 0.0, 0.0]), centre, ROWS, girths(0.06)) is None)

print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
