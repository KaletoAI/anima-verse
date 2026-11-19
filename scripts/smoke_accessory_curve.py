"""Smoke: Ruling A118 / A216 — the neck-curve helpers (``app/core/accessory_curve.py``) on an analytic cylinder.

Usage: ./.venv/bin/python scripts/smoke_accessory_curve.py   (no server, no world; pure numpy/scipy)

The surface: a closed cylinder of radius R = 0.06 m (a neck), axis y, from y = 0 to y = 0.2, 256 sides, capped.
Its facets sit at the apothem R cos(π/256) = 0.06 · 0.999925 = 0.0599955 m, so every distance below holds to
±0.01 mm against the round cylinder.

Expected values, derived by hand:

[1] ``ray_hits`` from the axis point (0, 0.1, 0) along +x, +z, −x: each hits the wall at t = 0.0599955…0.06
    (outermost hit = the only one); a ray along +y from (0, 0.1, 0) hits the top cap at t = 0.1; a ray from
    (0.5, 0.1, 0) along +x hits nothing within 0.25 → NaN, face −1.
[2] An outer wall wins over an inner one: the same cylinder plus a second one of radius 0.05 inside it — the ray
    along +x from the axis returns t ≈ 0.06 (not 0.05).
[3] ``resample`` of the closed unit square (4 corners) to 8 points: perimeter 4, spacing 0.5 → the corners and
    the edge midpoints, every consecutive distance 0.5 (±1e-9).
[4] ``weld``: two triangles sharing an edge but with duplicated vertices (6 vertices) → 4 vertices, faces
    re-indexed onto them.
[5] ``settle_out`` with clearance 1.7 mm: a ring of 48 points at y = 0.1 and radius 0.05 (1 cm INSIDE) and a ring
    at radius 0.075 (13 mm off) both end at radius R + 0.0017 = 0.0617 (±0.02 mm): the push moves a point to
    exactly the clearance along (point − its closest surface point), out of the skin or back toward it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from app.core import accessory_curve as ac  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def cylinder(radius, sides=256, h=0.2):
    a = 2 * np.pi * np.arange(sides) / sides
    ring = np.stack([radius * np.cos(a), np.zeros(sides), radius * np.sin(a)], 1)
    P = np.concatenate([ring, ring + [0, h, 0], [[0, 0, 0], [0, h, 0]]])
    lo, hi, cb, ct = 0, sides, 2 * sides, 2 * sides + 1
    F = []
    for i in range(sides):
        j = (i + 1) % sides
        F += [[lo + i, hi + i, lo + j], [lo + j, hi + i, hi + j], [cb, lo + i, lo + j], [ct, hi + j, hi + i]]
    return P, np.array(F, np.int64)


P, F = cylinder(0.06)
o = np.array([[0, 0.1, 0]] * 4 + [[0.5, 0.1, 0]], float)
d = np.array([[1, 0, 0], [0, 0, 1], [-1, 0, 0], [0, 1, 0], [1, 0, 0]], float)
t, f = ac.ray_hits(P, F, o, d)
check("[1] walls", bool(np.all((t[:3] >= 0.0599955 - 1e-7) & (t[:3] <= 0.06 + 1e-9))), True)
check("[1] cap", round(float(t[3]), 9), 0.1)
check("[1] miss", (bool(np.isnan(t[4])), int(f[4])), (True, -1))

P2, F2 = cylinder(0.05)
Pb = np.concatenate([P, P2])
Fb = np.concatenate([F, F2 + len(P)])
t, _ = ac.ray_hits(Pb, Fb, o[:1], d[:1])
check("[2] outer wall wins", bool(abs(float(t[0]) - 0.06) < 1e-4), True)

sq = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], float)
rs = ac.resample(sq, 8)
steps = np.linalg.norm(np.roll(rs, -1, 0) - rs, axis=1)
check("[3] 8 points", rs.shape, (8, 3))
check("[3] spacing 0.5", bool(np.allclose(steps, 0.5, atol=1e-9)), True)

Pd = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
Fd = np.array([[0, 1, 2], [3, 4, 5]])
Pw, Fw = ac.weld(Pd, Fd)
check("[4] welded vertices", len(Pw), 4)
check("[4] faces share the edge", len(set(Fw[0]) & set(Fw[1])), 2)

a = 2 * np.pi * np.arange(48) / 48
for r0 in (0.05, 0.075):
    ring = np.stack([r0 * np.cos(a), np.full(48, 0.1), r0 * np.sin(a)], 1)
    out = ac.settle_out(ring, P, F, 0.0017)
    rad = np.linalg.norm(out[:, [0, 2]], axis=1)
    print(f"       start {r0}: radius {rad.min():.6f} … {rad.max():.6f}")
    check(f"[5] start radius {r0} → 0.0617", bool(np.all(np.abs(rad - 0.0617) <= 2e-5)), True)

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
