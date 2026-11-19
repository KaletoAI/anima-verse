"""Smoke: A226 crotch bridge helpers in ``app/core/garment_shell.py`` (``crotch_run``, ``crotch_floor``,
``crotch_bridge``, ``crotch_source``) and the marched ``lift_over_surfaces``.

Usage:
    ./.venv/bin/python scripts/smoke_shell_crotch_bridge.py

No server, no world, no storage. Expected values derived by hand (CROTCH_BIN_M 0.004, CROTCH_CENTRE_M 0.006,
CROTCH_REACH_M 0.01, CROTCH_RISE_M 0.015, CROTCH_OVER_M 0.02, CROTCH_ABOVE_M 0.01, CROTCH_UNDER_M 0.005,
CROTCH_READ_M 0.02):
  [1] crotch_run, a front panel whose bottom edge is y = 0.80 + 2·x² / 0.01 (x in m), member for y ≥ that, points on a
      1 mm grid x -0.06..0.06, head-on everywhere down to y 0.795, xc 0: the edge rises 0.015 at x² = 0.015·0.01/2
      -> |x| = 0.0087; the columns are 4 mm wide centred on 0 (edges ±0.002, ±0.006, ±0.010 …), a column counts
      when its LOWEST member (its inner x) lies ≤ 0.815: inner |x| 0.006 (column 0.006..0.010) -> 0.80+2·0.000036/
      0.01 = 0.8072 in; next inner 0.010 -> 0.820 out. So x0 = -0.010, x1 = 0.010; edge height median 0.80..0.81;
      z_edge = the points' z = 0.05.
  [2] the same panel ending at y 0.82 at the middle (13+ mm above the head-on bottom 0.795 > CROTCH_REACH_M)
      -> None (a waist band is never bridged).
  [3] crotch_bridge, front (-0.02, 0.02, 0.80, 0.05), back (-0.04, 0.04, 0.80, -0.05), no floor: span 0.1.
      P (0, 0.79, 0) -> t 0.5, band -0.03..0.03, margin 0.03. P (0.025, 0.79, 0) -> margin 0.005.
      P (0.035, 0.79, 0) -> -0.005 (outside, > -0.01). P (0, 0.79, 0.065) -> t -0.15 (over 0.2 allowed): band
      -0.02..0.02, margin 0.02. P (0, 0.79, 0.08) -> t -0.3 -> -0.01 (off). P (0, 0.815, 0) -> top 0.81 -> off.
  [4] with floor y 0.80 everywhere: P (0, 0.79, 0) (10 mm under, > 5 mm) -> off; P (0, 0.797, 0) -> margin 0.03.
  [5] crotch_floor of points (0, 0.8 + z², z) for z in -0.07..0.07 step 1 mm, front z 0.05, back -0.05:
      at z 0 the floor is 0.80 (± 1e-4).
  [6] crotch_source: front edge y 0.80 z 0.05, P (0, 0.80, 0.045) (5 mm past) -> front y 0.805;
      P (0, 0.80, 0.025) (25 mm past, folds to 15) -> 0.815.
  [7] lift_over_surfaces (march): V origin, N +z, offset 6 mm, a 4 cm square at z 20 mm wound +z -> 26 mm; at
      z 38 mm -> 44 mm (within the 40 mm reach, the last march step).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_shell as gsh  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


xs = np.round(np.arange(-0.06, 0.0605, 0.001), 4)
ys = np.round(np.arange(0.795, 0.86, 0.001), 4)
X, Y = np.meshgrid(xs, ys)
x, y = X.ravel(), Y.ravel()
z = np.full(len(x), 0.05)
edge = 0.80 + 2 * x ** 2 / 0.01
r = gsh.crotch_run(x, y, z, y >= edge, np.ones(len(x), bool), 0.0)
check("[1] run x0 -0.010, x1 0.010", r is not None and abs(r[0] + 0.010) < 1e-6 and abs(r[1] - 0.010) < 1e-6, r)
check("[1] edge y 0.80..0.81, z 0.05", r is not None and 0.80 <= r[2] <= 0.81 and abs(r[3] - 0.05) < 1e-9, r)
r2 = gsh.crotch_run(x, y, z, y >= edge + 0.02, np.ones(len(x), bool), 0.0)
check("[2] a band 25 mm above the head-on bottom -> None", r2 is None, r2)

F = (-0.02, 0.02, 0.80, 0.05)
B = (-0.04, 0.04, 0.80, -0.05)
P = np.array([[0, 0.79, 0], [0.025, 0.79, 0], [0.035, 0.79, 0], [0, 0.79, 0.065], [0, 0.79, 0.08], [0, 0.815, 0]])
m, t = gsh.crotch_bridge(P, F, B)
want = [0.03, 0.005, -0.005, 0.02, -0.01, -0.01]
check("[3] margins", np.allclose(m, want, atol=1e-9), m)
check("[3] t at the middle 0.5", abs(t[0] - 0.5) < 1e-9, t[0])
fl = (np.array([-0.1, 0.1]), np.array([0.80, 0.80]))
m4, _ = gsh.crotch_bridge(np.array([[0, 0.79, 0], [0, 0.797, 0]]), F, B, fl)
check("[4] floor: 10 mm under off, 3 mm under on", np.allclose(m4, [-0.01, 0.03], atol=1e-9), m4)
zz = np.round(np.arange(-0.07, 0.0705, 0.001), 4)
Pf = np.c_[np.zeros(len(zz)), 0.8 + zz ** 2, zz]
f5 = gsh.crotch_floor(Pf, 0.0, F, B)
check("[5] floor at z 0 = 0.80", f5 is not None and abs(np.interp(0.0, f5[0], f5[1]) - 0.80) < 1e-4,
      f5 and np.interp(0.0, f5[0], f5[1]))
yf, _yb = gsh.crotch_source(np.array([[0, 0.80, 0.045], [0, 0.80, 0.025]]), None, F, B)
check("[6] source 5 mm -> 0.805, 25 mm -> 0.815", np.allclose(yf, [0.805, 0.815], atol=1e-9), yf)


def square(zh, up=True):
    P_ = np.array([[-0.02, -0.02, zh], [0.02, -0.02, zh], [0.02, 0.02, zh], [-0.02, 0.02, zh]])
    F_ = np.array([[0, 1, 2], [0, 2, 3]])
    return P_, (F_ if up else F_[:, ::-1])


V = np.zeros((1, 3))
N = np.array([[0.0, 0.0, 1.0]])
for zh, want_z in ((0.020, 0.026), (0.038, 0.044)):
    Xl, _l = gsh.lift_over_surfaces(V, N, 0.006, [(*square(zh), True)])
    check(f"[7] square at {zh * 1000:.0f} mm -> {want_z * 1000:.0f} mm", abs(Xl[0, 2] - want_z) < 1e-6, Xl[0, 2])

print("ALL OK" if not FAILED else f"{len(FAILED)} FAILED")
sys.exit(1 if FAILED else 0)
