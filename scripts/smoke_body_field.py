#!/usr/bin/env python3
"""The body field's solid (``garment_fit.body_sdf``, ``fit_kernels.fill_slices``) on synthetic shells, expectations
derived by hand (plan 2026-11-12 fit-sdf-speed-drape, Task 1).

Usage: ./.venv/bin/python scripts/smoke_body_field.py

No world, no server, no storage: every mesh is built in this file. Probes are read with ``Sdf.sample``.

The solid is the 3-D hole fill + seal of the dilated surface, united with the 2-D hole fill of every slice along
x, y and z of the full grid. The fails-on-old proof loads ``app/core/garment_fit.py`` of commit f55e4b2c (the
plan's BASE, before Task 1: 3-D fill + seal, the y-slices only behind ``fill_slices=True``) as a module and runs
the same probes through it.

[F1] Open double-walled arm, vox 0.004. Outer cylinder r 0.05 and inner cylinder r 0.04 with REVERSED winding, axis
     along x from -0.20 to +0.20, their ends joined by annular caps; the core (r < 0.04) is open at both ends.
     Probe (0, 0, 0) on the axis.
     - BASE f55e4b2c: the 3-D fill reaches the core through the open ends and the seal finds nothing enclosed
       along x -> outside; the probe is 0.04 from the inner wall -> > +0.02. With ``fill_slices=True`` too: the
       y-slice through the axis is a strip open at both ends -> still > +0.02.
     - New: every x-slice is two rings, the core disc is enclosed -> inside; the nearest outside is the outer wall
       0.05 away -> < -0.04.
[F2] Closed sphere with an inverted inner shell, vox 0.002. Outer UV sphere R 0.10 and inner sphere R 0.09 with
     reversed winding (1 cm inside). Probe between the shells at r 0.095 (equator) -> <= -0.002 (0.005 from the
     outer wall); centre -> <= -0.08 (0.10 from the outer wall). Passes at BASE too (the 3-D fill closes it): a
     guard that the winding never matters.
[F3] As [F2], the outer sphere's polar cap above 73 deg elevation removed (face centroids; the rings lie every
     3.75 deg, so the hole's rim is the 71.25 deg ring, 2 * 0.10 * cos 71.25 deg = 6.4 cm across).
     Probe at the equator, r 0.095.
     - BASE: the gap between the shells reaches the outside through the hole; the seal needs 21 voxels of thickness
       and the gap is 5 -> outside; the probe lies in the exact band, 0.005 from both walls -> >= +0.003.
     - New: the equatorial y-slice is two closed rings -> inside, 0.005 from the outer wall -> <= -0.002.
[F4] Concavity guard, vox 0.004. Two vertical cylinders r 0.06 at x = +-0.07 (y 0.0 .. 0.80), joined at the top by a
     box (y 0.80 .. 0.95, x +-0.13, z +-0.06). The gap probe (0, 0.40, 0) must stay OUTSIDE: the z-slice is a
     PI open at the bottom, the y-slice is two separate discs, the x-slice at 0 misses both cylinders (inner walls
     at |x| 0.01), and the seal finds the gap open downwards. It lies in the exact band, 1 cm from each inner wall
     (a cylinder vertex sits exactly at x = +-0.01, z 0) -> +0.010 +- 0.002.
[F5] ``fill_slices(surf, axis)`` equals ``ndimage.binary_fill_holes`` of every slice ⟂ axis: a random 40^3 mask (seed
     7, 30 % filled, then dilated once) for axis 0, 1 and 2 -> ``np.array_equal``.
"""
import math
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BASE = "f55e4b2c"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- synthetic meshes --------------------------------------------------------

def grid_faces(rows, cols, start=0, wrap=True):
    """Quads of a ``rows x cols`` vertex grid (columns wrap around when ``wrap``) as triangle pairs."""
    F = []
    span = cols if wrap else cols - 1
    for i in range(rows - 1):
        for j in range(span):
            a, b = start + i * cols + j, start + i * cols + (j + 1) % cols
            c, d = start + (i + 1) * cols + (j + 1) % cols, start + (i + 1) * cols + j
            F += [(a, b, c), (a, c, d)]
    return F


def merge(*parts):
    Ps, Fs, n = [], [], 0
    for P, F in parts:
        Ps.append(np.asarray(P, float))
        Fs.append(np.asarray(F, np.int64) + n)
        n += len(P)
    return np.concatenate(Ps), np.concatenate(Fs)


def open_tube_x(r_out, r_in, x0, x1, nseg=64, nrings=41):
    """[F1]: outer side r_out, inner side r_in (reversed winding), both along x; annular caps join their ends."""
    xs = np.linspace(x0, x1, nrings)
    ang = np.arange(nseg) * 2 * np.pi / nseg
    def side(r):
        return np.array([(x, r * math.cos(a), r * math.sin(a)) for x in xs for a in ang])
    outer = (side(r_out), np.array(grid_faces(nrings, nseg)))
    inner = (side(r_in), np.array(grid_faces(nrings, nseg))[:, ::-1])
    caps = []
    for x in (x0, x1):
        P = np.array([(x, r * math.cos(a), r * math.sin(a)) for r in np.linspace(r_out, r_in, 4) for a in ang])
        caps.append((P, np.array(grid_faces(4, nseg))))
    return merge(outer, inner, *caps)


def uv_sphere(radius, nlat=48, nlon=96, flip=False):
    lat = np.linspace(-np.pi / 2, np.pi / 2, nlat + 1)
    lon = np.linspace(0, 2 * np.pi, nlon, endpoint=False)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    P = np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], -1).reshape(-1, 3) * radius
    F = np.array(grid_faces(nlat + 1, nlon))
    return P, (F[:, ::-1] if flip else F)


def cylinder_y(radius, cx, y0, y1, nseg=64, nrings=81):
    """Closed cylinder around the vertical line x = cx, z = 0 (side + fan caps of concentric rings)."""
    ys = np.linspace(y0, y1, nrings)
    ang = np.arange(nseg) * 2 * np.pi / nseg
    P = [(cx + radius * math.cos(a), y, radius * math.sin(a)) for y in ys for a in ang]
    F = grid_faces(nrings, nseg)
    for y, ring in ((y0, 0), (y1, nrings - 1)):
        prev = ring * nseg
        for r in np.linspace(radius, 0, 8)[1:]:
            start = len(P)
            P += [(cx + r * math.cos(a), y, r * math.sin(a)) for a in ang]
            for j in range(nseg):
                a, b = prev + j, prev + (j + 1) % nseg
                F += [(a, b, start + (j + 1) % nseg), (a, start + (j + 1) % nseg, start + j)]
            prev = start
    return np.array(P), np.array(F)


def box(lo, hi, step=0.01):
    """Closed axis-aligned box, every face a grid of about ``step`` spacing."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    parts = []
    for axis in range(3):
        u, v = [a for a in range(3) if a != axis]
        nu = max(2, int(math.ceil((hi[u] - lo[u]) / step)) + 1)
        nv = max(2, int(math.ceil((hi[v] - lo[v]) / step)) + 1)
        for value in (lo[axis], hi[axis]):
            P = np.zeros((nu * nv, 3))
            uu, vv = np.meshgrid(np.linspace(lo[u], hi[u], nu), np.linspace(lo[v], hi[v], nv), indexing="ij")
            P[:, axis], P[:, u], P[:, v] = value, uu.ravel(), vv.ravel()
            parts.append((P, np.array(grid_faces(nu, nv, wrap=False))))
    return merge(*parts)


# --- the field at BASE --------------------------------------------------------

def base_module():
    """``app/core/garment_fit.py`` of commit BASE, loaded as its own module."""
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{BASE}:app/core/garment_fit.py"])
    mod = types.ModuleType(f"garment_fit_{BASE}")
    mod.__file__ = f"<{BASE}:app/core/garment_fit.py>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def at(sdf, *points):
    return [float(v) for v in sdf.sample(np.array(points, float))]


# --- cases ----------------------------------------------------------------------

def test_f1(gf, old):
    P, F = open_tube_x(0.05, 0.04, -0.20, 0.20)
    bounds = (np.array([-0.25, -0.08, -0.08]), np.array([0.25, 0.08, 0.08]))
    (v,) = at(gf.body_sdf(P, F, vox=0.004, bounds=bounds), (0, 0, 0))
    check(v < -0.04, f"[F1] open double-walled arm: the core is inside (sdf {v:+.4f} < -0.04)")
    (b,) = at(old.body_sdf(P, F, vox=0.004, bounds=bounds), (0, 0, 0))
    check(b > 0.02, f"[F1] BASE {BASE}: the core reads outside (sdf {b:+.4f} > +0.02)")
    (by,) = at(old.body_sdf(P, F, vox=0.004, bounds=bounds, fill_slices=True), (0, 0, 0))
    check(by > 0.02, f"[F1] BASE {BASE} with fill_slices=True (y only): still outside (sdf {by:+.4f} > +0.02)")


def spheres(hole_above_deg=None):
    outer = uv_sphere(0.10)
    if hole_above_deg is not None:
        P, F = outer
        c = P[F].mean(1)
        elev = np.degrees(np.arcsin(c[:, 1] / np.linalg.norm(c, axis=1)))
        outer = (P, F[elev <= hole_above_deg])
    return merge(outer, uv_sphere(0.09, flip=True))


SPHERE_BOUNDS = (np.full(3, -0.12), np.full(3, 0.12))


def test_f2(gf, old):
    P, F = spheres()
    for name, mod in (("new", gf), (f"BASE {BASE}", old)):
        between, centre = at(mod.body_sdf(P, F, vox=0.002, bounds=SPHERE_BOUNDS), (0.095, 0, 0), (0, 0, 0))
        check(between <= -0.002, f"[F2] {name}: closed sphere, between the shells inside (sdf {between:+.4f} <= -0.002)")
        check(centre <= -0.08, f"[F2] {name}: closed sphere, centre inside (sdf {centre:+.4f} <= -0.08)")


def test_f3(gf, old):
    P, F = spheres(hole_above_deg=73.0)
    _, F_closed = spheres()
    check(len(F) < len(F_closed), f"[F3] the polar cap is removed ({len(F_closed) - len(F)} faces)")
    (v,) = at(gf.body_sdf(P, F, vox=0.002, bounds=SPHERE_BOUNDS), (0.095, 0, 0))
    check(v <= -0.002, f"[F3] opened sphere: between the shells inside (sdf {v:+.4f} <= -0.002)")
    (b,) = at(old.body_sdf(P, F, vox=0.002, bounds=SPHERE_BOUNDS), (0.095, 0, 0))
    check(b >= 0.003, f"[F3] BASE {BASE}: between the shells reads outside (sdf {b:+.4f} >= +0.003)")


def test_f4(gf):
    P, F = merge(cylinder_y(0.06, -0.07, 0.0, 0.80), cylinder_y(0.06, 0.07, 0.0, 0.80),
                 box((-0.13, 0.80, -0.06), (0.13, 0.95, 0.06)))
    bounds = (np.array([-0.20, -0.05, -0.10]), np.array([0.20, 1.00, 0.10]))
    (v,) = at(gf.body_sdf(P, F, vox=0.004, bounds=bounds), (0, 0.40, 0))
    check(abs(v - 0.010) <= 0.002, f"[F4] concavity: the gap stays outside (sdf {v:+.4f} = +0.010 +- 0.002)")


def test_f5():
    from scipy import ndimage
    from app.core import fit_kernels
    rng = np.random.default_rng(7)
    mask = ndimage.binary_dilation(rng.random((40, 40, 40)) < 0.30)
    for axis in range(3):
        want = mask.copy()
        for j in range(mask.shape[axis]):
            sl = [slice(None)] * 3
            sl[axis] = j
            want[tuple(sl)] = ndimage.binary_fill_holes(mask[tuple(sl)])
        got = fit_kernels.fill_slices(mask, axis)
        check(np.array_equal(got, want),
              f"[F5] fill_slices axis {axis} == per-slice binary_fill_holes ({int(want.sum() - mask.sum())} filled)")


def main():
    from app.core import garment_fit as gf
    old = base_module()
    test_f1(gf, old)
    test_f2(gf, old)
    test_f3(gf, old)
    test_f4(gf)
    test_f5()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
