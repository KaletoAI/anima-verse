"""Ruling A159: every extension capsule carries ``r_surface`` (collision v8, ``app/core/collision.py`` SURFACE RADIUS).

Usage: ./.venv/bin/python scripts/smoke_collision_surface_radius.py   (no server, no world, no storage)

Numbers by hand: one ``attached_part`` chain [J1, J2], J1 at the origin, J2 at (0, 0.1, 0); J1 owns 20 vertices at
y = 0.05 (inside the segment, so the distance is the radius), radii 0.010 + 0.001·i (i = 0…19); J2 owns 3 (< 16 =
MIN_VERTICES, skipped). numpy's linear quantile: p75 at index 0.75·19 = 14.25 → 0.024 + 0.25·0.001 = 0.02425;
p95 at 0.95·19 = 18.05 → 0.028 + 0.05·0.001 = 0.02805. Margin 0, scale 1, unit 1 → r 0.0242 (rounded to 4 places:
0.02425 → 0.0242 or 0.0243 — Python rounds half to even on the float, so compared at 1e-4), r_surface 0.0281 (0.02805 →
0.028 or 0.0281, the same tolerance). A scale of 1.5 gives 0.036375 and 0.042075. VERSION is 9 (A193: the mouth record).
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import collision  # noqa: E402  (pure module, no storage)

failed = 0


def check(label, ok, got=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got})"))
    if not ok:
        failed += 1


def fit(scale):
    names = ["mixamorig:J1", "mixamorig:J2"]
    positions = np.array([[0.0, 0.0, 0.0], [0.0, 0.1, 0.0]])
    own = [[0.010 + 0.001 * i, 0.05, 0.0] for i in range(20)]
    tip = [[0.0, 0.11, 0.0]] * 3
    body = np.array(own + tip)
    dominant = np.array([0] * 20 + [1] * 3)
    capsules, skipped = [], []
    scales = collision.validate_scales({"attached_part": scale})
    collision._fit_extension_capsules(
        [{"group": "g", "op": "attached_part", "chains": [names]}],
        index_of={"j1": 0, "j2": 1}, names=names, positions=positions, body_positions=body, dominant=dominant,
        unit=1.0, scales=scales, capsules=capsules, skipped=skipped)
    return capsules, skipped


check("VERSION 9", collision.VERSION == 9, collision.VERSION)
check("SURFACE_QUANTILE 0.95", collision.SURFACE_QUANTILE == 0.95)
caps, skipped = fit(1.0)
check("one capsule (J1), J2 skipped", len(caps) == 1 and len(skipped) == 1, (caps, skipped))
c = caps[0] if caps else {}
check("r = p75 0.02425", math.isclose(c.get("r", 0), 0.02425, abs_tol=1e-4), c.get("r"))
check("r_surface = p95 0.02805", math.isclose(c.get("r_surface", 0), 0.02805, abs_tol=1e-4), c.get("r_surface"))
check("r_surface > r", c.get("r_surface", 0) > c.get("r", 1))
caps2, _ = fit(1.5)
check("scale 1.5 multiplies both", caps2 and math.isclose(caps2[0]["r"], 0.036375, abs_tol=1e-4)
      and math.isclose(caps2[0]["r_surface"], 0.042075, abs_tol=1e-4), caps2)
print("smoke_collision_surface_radius: " + (f"{failed} FAILED" if failed else "OK"))
sys.exit(1 if failed else 0)
