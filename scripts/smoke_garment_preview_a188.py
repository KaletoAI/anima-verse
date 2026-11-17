"""A188 — hand-derived checks of the template dialog's picture overlay (``app/core/garment_preview.py``).

Usage: ./.venv/bin/python scripts/smoke_garment_preview_a188.py   (no server, no world, no files)

A synthetic picture (numpy mask) and a synthetic measurement, numbers derived by hand:

* Picture 200 x 400 px; figure rows 40 .. 379 (feet_px = 380), so the figure spans 340 px.
  Body: height 1.70 m, floor 0 -> scale = 340 / 1.70 = 200 px/m.
  Torso: columns 80 .. 119 (40 px wide, centre 100) for rows 40 .. 239; legs: columns 70 .. 89 and 110 .. 129 below.
  Model centre x0 = mean(hips x 0.01, neck x 0.03) = 0.02 m.
* px(x0, 0)       = (100, 380)                         (the feet row, the centre column)
* px(x0, 1.70)    = (100, 380 - 1.70 * 200) = (100, 40)  (the head-top row)
* px(x0 + 0.1, 1.0) = (100 + 0.1 * 200, 380 - 200) = (120, 180)
* body_half(1.0): row 180 lies in the torso run 80 .. 120 -> 20 px either side = 0.10 m.
* body_half(0.3): row 320 is between the legs -> outer edges 70 and 130 -> 30 px = 0.15 m either side.
* neckline_curve: V at s = 0.5 is cut over 1 - 0.5 = 0.5 of the depth; round (crew/scoop/boat) over
  (1 - 0.25) ** 0.7 = 0.81767 of it; both reach the full depth at the centre and 0 at the rims.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="a188-smoke-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
import numpy as np  # noqa: E402

from app.core import garment_preview as gp  # noqa: E402

FAILS = []


def check(name, got, want, tol=0.51):
    ok = all(abs(a - b) <= tol for a, b in zip(got, want)) if isinstance(want, (list, tuple)) else abs(got - want) <= tol
    print(("ok  " if ok else "FAIL"), name, got, "want", want)
    if not ok:
        FAILS.append(name)


mask = np.zeros((400, 200), bool)
mask[40:240, 80:120] = True
mask[240:380, 70:90] = True
mask[240:380, 110:130] = True
frame = gp.frame_of_mask(mask)
check("top_px", frame["top_px"], 40)
check("feet_px", frame["feet_px"], 380)
meas = {"height": 1.70, "floor_y": 0.0, "hip_y": 0.9, "band_y": 1.3, "waist_y": 1.05,
        "joints": {"hips": [0.01, 0.95, 0.0], "neck": [0.03, 1.45, 0.0]}}
reg = gp.register(frame, meas)
check("scale", reg.scale, 200.0, 1e-6)
check("cx", reg.cx, 100.0)
check("px feet", reg.px(0.02, 0.0), (100, 380))
check("px head top", reg.px(0.02, 1.70), (100, 40))
check("px x0+0.1, 1.0", reg.px(0.12, 1.0), (120, 180))
check("body_half torso", reg.body_half(1.0, 1.0), (0.10, 0.10), 0.006)
check("body_half legs", reg.body_half(0.3, 1.0), (0.15, 0.15), 0.006)
check("body_half capped", reg.body_half(0.3, 0.12), (0.12, 0.12), 1e-6)
v = gp.neckline_curve("v", 0.0, 0.1, 1.0, 0.8)
r = gp.neckline_curve("crew", 0.0, 0.1, 1.0, 0.8)
n = gp.CURVE_N
check("v rim", v[0], (0.1, 1.0), 1e-9)
check("v centre", v[n // 2], (0.0, 0.8), 1e-9)
check("v at s=0.5", v[n // 4], (0.05, 1.0 - 0.2 * 0.5), 1e-9)
check("round at s=0.5", r[n // 4], (0.05, 1.0 - 0.2 * 0.75 ** 0.7), 1e-9)
check("round centre", r[n // 2], (0.0, 0.8), 1e-9)
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
