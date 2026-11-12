#!/usr/bin/env python3
"""The fit kernels give the same bits as the code they replace (``app/core/fit_kernels.py``; plan 2026-11-12
fit-sdf-speed-drape, Task 2).

Usage: ./.venv/bin/python scripts/smoke_fit_kernels.py

No world, no server, no storage: every array is built in this file. The kernels are speed work only, so every
expectation is EQUALITY with the code they replace — scipy, the numpy point-triangle distance, and the field of
commit 8e67362b (Task 1 and its fix round, the last ``body_sdf`` before this task) — not a recorded output.

[K1] ``fill_holes(mask)`` equals ``ndimage.binary_fill_holes(mask)`` (``np.array_equal``) on 3 random 48^3 masks
     (seeds 1, 2, 3; 35 / 50 / 65 % set, the first one dilated once so it has real enclosed holes).
[K2] ``band_distance(X, P, tris)`` equals ``garment_fit.point_triangle_distance(X[:, None], A, B, C).min(1)`` BIT FOR
     BIT (the float64 bit patterns) on 10 000 random points x 8 random triangles of 400 random vertices (seed 5).
     50 of the triangles are degenerate, at random rows / columns, each with a normal of length exactly 0 so both
     sides take the edge path: 20 with a repeated vertex (a, a, b), 10 with one vertex three times (a, a, a), 20
     collinear on an axis-parallel line with dyadic coordinates (a, a + 0.5 e_x, a + 0.25 e_x — the cross product is
     exactly 0 in floating point). The points spread 0.3 beyond the vertices, so every closest-point region occurs.
     The region counts of the reference are printed: each of the 7 must occur (else the check proves less), and
     at least the 50 planted pairs are degenerate — the random triangles add their own, a triangle drawing one of
     the 400 vertices twice: 1 - 399 * 398 / 400^2 = 0.75 % of the other 79 950, about 600. The 50 planted ones
     are also compared alone (k = 1), so no nearer triangle of their row hides them.
[K3] ``garment_fit.body_sdf`` of smoke_body_field's [F1] body (open double-walled tube along x, outer r 0.05, inner r
     0.04 reversed, x -0.20 .. +0.20; vox 0.004, bounds +-(0.25, 0.08, 0.08)) equals the field of
     ``app/core/garment_fit.py`` at 8e67362b, loaded as its own module: ``np.array_equal`` of ``field``, equal ``lo``
     and ``vox``. The field holds the label fill (``fill_holes``) and the exact band (``band_distance``).
[K4] ``set_threads(1)`` and ``set_threads(4)`` give equal ``band_distance`` output (bits) on 200 000 rows: the rows are
     independent, the thread count only splits them. ``threads()`` reads back 1 and 4.
[K5] ``refit_pool._initializer(None, 3)`` leaves ``fit_kernels.threads() == 3`` — in a child process, since the
     initializer disables sqlite and lowers the priority of the process it runs in. The same child first reads the
     default ``threads() == 4``.
"""
import math
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

T1 = "8e67362b"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def same_bits(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return a.shape == b.shape and bool(np.array_equal(a.view(np.uint64), b.view(np.uint64)))


# --- [K1] ---------------------------------------------------------------------------------------------------------

def test_k1(fk):
    from scipy import ndimage
    for seed, share in ((1, 0.35), (2, 0.50), (3, 0.65)):
        rng = np.random.default_rng(seed)
        mask = rng.random((48, 48, 48)) < share
        if seed == 1:
            mask = ndimage.binary_dilation(mask)
        ref = ndimage.binary_fill_holes(mask)
        got = fk.fill_holes(mask)
        holes = int(ref.sum() - mask.sum())
        check(got.dtype == bool and np.array_equal(got, ref),
              f"[K1] seed {seed} ({share:.0%}): fill_holes == binary_fill_holes ({holes} hole voxels filled)")


# --- [K2] / [K4] ----------------------------------------------------------------------------------------------------

def random_band(n, seed, degenerate=0):
    rng = np.random.default_rng(seed)
    m = 400
    P = rng.uniform(-1.0, 1.0, (m, 3))
    # dyadic vertices for the exact collinear triangles: a, a + 0.5 e_x, a + 0.25 e_x
    base = np.round(rng.uniform(-1.0, 1.0, (20, 3)) * 64) / 64
    P = np.concatenate([P, base, base + [0.5, 0, 0], base + [0.25, 0, 0]])
    tris = rng.integers(0, m, (n, 8, 3))
    slots = rng.choice(n * 8, degenerate, replace=False)
    for i, s in enumerate(slots):
        r, c = divmod(int(s), 8)
        if i < 20:                                   # repeated vertex (a, a, b)
            a, b = rng.choice(m, 2, replace=False)
            tris[r, c] = (a, a, b)
        elif i < 30:                                 # a point (a, a, a)
            a = rng.integers(0, m)
            tris[r, c] = (a, a, a)
        else:                                        # collinear, exact
            j = i - 30
            tris[r, c] = (m + j, m + 20 + j, m + 40 + j)
    lo, hi = P.min(0) - 0.3, P.max(0) + 0.3
    X = rng.uniform(lo, hi, (n, 3))
    # half of the points near a triangle of their row (on its plane +- a little), so the regions are all hit
    near = rng.random(n) < 0.5
    t0 = tris[near, 0]
    w = rng.dirichlet((1, 1, 1), int(near.sum())) * 1.6 - 0.2
    X[near] = (w[:, :, None] * P[t0]).sum(1) + rng.normal(0, 0.02, (int(near.sum()), 3))
    return X, P, tris, slots


def regions(X, A, B, C):
    """The reference's closest-point region per pair: 0..5 Ericson's vertex / edge regions, 6 interior,
    7 degenerate (the same predicates as ``point_triangle_closest``)."""
    ab, ac, ap = B - A, C - A, X - A
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = X - B
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = X - C
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    conds = [(d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (d6 >= 0) & (d5 <= d6),
             (vc <= 0) & (d1 >= 0) & (d3 <= 0), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
             (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)]
    out = np.full(d1.shape, 6)
    for k in range(5, -1, -1):
        out = np.where(conds[k], k, out)
    out = np.where(np.linalg.norm(np.cross(ab, ac), axis=-1) <= 1e-18, 7, out)
    return out


def test_k2(fk, gf):
    X, P, tris, slots = random_band(10_000, 5, degenerate=50)
    A, B, C = P[tris[..., 0]], P[tris[..., 1]], P[tris[..., 2]]
    ref = gf.point_triangle_distance(X[:, None, :], A, B, C).min(1)
    got = fk.band_distance(X, P, tris)
    reg = regions(X[:, None, :], A, B, C)
    counts = np.bincount(reg.ravel(), minlength=8)
    print(f"     regions (A, B, C, AB, AC, BC, interior, degenerate): {counts.tolist()}")
    check((counts[:7] > 0).all() and counts[7] >= 50,
          f"[K2] every closest-point region occurs, >= 50 degenerate pairs ({int(counts[7])})")
    check(np.isfinite(ref).all(), "[K2] reference finite")
    check(same_bits(got, ref), f"[K2] band_distance == point_triangle_distance(...).min(1) bit for bit "
                               f"(10 000 x 8; max |d| {float(np.abs(got - ref).max()):.3g})")
    # the degenerate rows alone, each pair individually (not hidden by a nearer triangle of the row)
    r, c = np.divmod(slots, 8)
    single = tris[r, c][:, None, :]
    ref1 = gf.point_triangle_distance(X[r][:, None, :], P[single[..., 0]], P[single[..., 1]], P[single[..., 2]])
    check(same_bits(fk.band_distance(X[r], P, single), ref1.min(1)) and len(r) == 50,
          "[K2] the 50 degenerate triangles alone (k = 1): bit for bit")


def test_k4(fk):
    X, P, tris, _ = random_band(200_000, 9)
    before = fk.threads()
    try:
        fk.set_threads(1)
        t1 = fk.threads()
        one = fk.band_distance(X, P, tris)
        fk.set_threads(4)
        t4 = fk.threads()
        four = fk.band_distance(X, P, tris)
    finally:
        fk.set_threads(before)
    check(t1 == 1 and t4 == 4, f"[K4] threads() reads back 1 / 4 ({t1} / {t4})")
    check(same_bits(one, four), "[K4] set_threads(1) and set_threads(4): equal band_distance (200 000 x 8)")


# --- [K3] ------------------------------------------------------------------------------------------------------------

def grid_faces(rows, cols):
    F = []
    for i in range(rows - 1):
        for j in range(cols):
            a, b = i * cols + j, i * cols + (j + 1) % cols
            c, d = (i + 1) * cols + (j + 1) % cols, (i + 1) * cols + j
            F += [(a, b, c), (a, c, d)]
    return F


def open_tube_x(r_out, r_in, x0, x1, nseg=64, nrings=41):
    """smoke_body_field's [F1] body: outer side r_out, inner side r_in (reversed), annular caps at both ends."""
    xs = np.linspace(x0, x1, nrings)
    ang = np.arange(nseg) * 2 * np.pi / nseg
    parts = []

    def side(r):
        return np.array([(x, r * math.cos(a), r * math.sin(a)) for x in xs for a in ang])
    parts.append((side(r_out), np.array(grid_faces(nrings, nseg))))
    parts.append((side(r_in), np.array(grid_faces(nrings, nseg))[:, ::-1]))
    for x in (x0, x1):
        P = np.array([(x, r * math.cos(a), r * math.sin(a)) for r in np.linspace(r_out, r_in, 4) for a in ang])
        parts.append((P, np.array(grid_faces(4, nseg))))
    Ps, Fs, n = [], [], 0
    for P, F in parts:
        Ps.append(P)
        Fs.append(F + n)
        n += len(P)
    return np.concatenate(Ps), np.concatenate(Fs)


def module_at(rev):
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:app/core/garment_fit.py"])
    mod = types.ModuleType(f"garment_fit_{rev}")
    mod.__file__ = f"<{rev}:app/core/garment_fit.py>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def test_k3(gf):
    old = module_at(T1)
    P, F = open_tube_x(0.05, 0.04, -0.20, 0.20)
    bounds = (np.array([-0.25, -0.08, -0.08]), np.array([0.25, 0.08, 0.08]))
    new = gf.body_sdf(P, F, vox=0.004, bounds=bounds)
    ref = old.body_sdf(P, F, vox=0.004, bounds=bounds)
    band = int(((ref.field > 0) & (ref.field <= gf.SDF_EXACT_BAND_VOX * 0.004)).sum())
    check(np.array_equal(new.lo, ref.lo) and new.vox == ref.vox and new.field.shape == ref.field.shape,
          f"[K3] [F1] body: same grid as {T1} ({ref.field.shape})")
    check(np.array_equal(new.field, ref.field),
          f"[K3] [F1] body: body_sdf field == {T1}'s (np.array_equal; {band} exact-band cells, "
          f"{int((ref.field < 0).sum())} inside)")


def test_k5():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from app.core import fit_kernels, refit_pool\n"
            "d = fit_kernels.threads()\n"
            "refit_pool._initializer(None, 3)\n"
            "print(d, fit_kernels.threads())\n") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    got = out.stdout.split()
    check(out.returncode == 0 and got == ["4", "3"],
          f"[K5] default threads() 4, after refit_pool._initializer(None, 3) -> 3 (child said {got or out.stderr[-300:]})")


def main():
    from app.core import fit_kernels as fk
    from app.core import garment_fit as gf
    for fn, args in ((test_k1, (fk,)), (test_k2, (fk, gf)), (test_k3, (gf,)), (test_k4, (fk,)), (test_k5, ())):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001 - a missing kernel is a FAIL, not a crash
            check(False, f"{fn.__name__}: {type(e).__name__}: {e}")
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
