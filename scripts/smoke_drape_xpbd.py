#!/usr/bin/env python3
"""XPBD drape engine (``app/core/drape.py``) on analytic grids — no mesh SDF, no world, no server.

Usage: ./.venv/bin/python scripts/smoke_drape_xpbd.py

Plan 2026-11-12 fit-sdf-speed-drape, Task 9. Every field below is a closed-form signed distance sampled on a grid
(``garment_fit.Sdf``), so the expected numbers follow from the geometry alone (metres, +y up):

[X1] A 0.20 x 0.20 m cloth, 10 mm grid (21 x 21 vertices), lying flat in the plane y = 0.5 (x 0 .. 0.20,
     z 0 .. 0.20), pinned along its row z = 0; gravity 9.81, 1500 substeps of 1 ms, no body (a field that is
     +1 m everywhere). Inextensible (a_stretch 0) under gravity it swings down and hangs from the pinned row:
     its far row ends 0.20 below the pins -> the lowest vertex at 0.5 - 0.20 = 0.30 +- 0.01, and no mesh edge
     more than 2 % longer than its rest length (the rest is the start, rest scale c = 1). A soft cloth, a_bend 1e-6:
     with one Gauss-Seidel sweep per substep the bend constraints take a share of every sweep, and the edges near
     the pins (they carry the cloth's weight) keep a residual stretch — measured on this cloth 3.4 % at a_bend 1e-4,
     2.6 % at 1e-5, 1.45 % at 1e-6 (the same with the cloth started hanging, so it is the load, not the fold).
[X2] A 5 x 5 patch (10 mm grid, 4 cm wide, all free) centred over a sphere of radius 0.10 at the origin, dropped
     from 5 cm above its top (y = 0.15); the field |p| - 0.10 on a 2 mm grid, clear 0.004. Gravity lays it on the
     sphere; every vertex ends at |p| >= 0.10 + 0.004 - 0.001 = 0.103 (1 mm: the grid's trilinear slack).
[X3] X1's pinned row: displacement exactly 0 (the result carries the input's float64 bits, not an f32 round trip).
[X4] anchor_m 0.01 against the half-space field d = y (body below y = 0), a 5 x 5 patch at y = -0.03, gravity 0,
     max_push 0.05 per substep: the field asks for 0.03 + 0.004 = 0.034 of push, the anchor allows 0.010 ->
     max displacement <= 0.010 + 1e-6 (the anchor's f32 rounding), and > 0.009 (it was pushed to the bound).
[X5] Determinism: X2's case with refinement (lmax 0.006), a pinned corner and LRA run twice in this process ->
     ``array_equal``; and once more in a child process that calls ``fit_kernels.set_threads(1)`` before Taichi
     starts (Taichi's CPU pool size is fixed at its init, once per process), against this process's 4 threads ->
     ``array_equal``.
[X6] ``refine`` of one right triangle with 40 mm legs at lmax 0.015: round 1 splits all three edges (40, 40, 56.6 mm)
     -> 4 triangles with legs 20 mm, hypotenuse 28.3 mm; round 2 splits all again -> 16 triangles, legs 10 mm,
     hypotenuse 14.14 mm <= 15 -> stop. 15 vertices (a 5-per-side triangular grid), max edge 0.01414 <= 0.015; the
     original 3 vertices keep indices 0..2 and their positions; a bool array is AND-ed on new vertices, an int array
     takes the edge's first end, a float array the mean.
Timings (JIT, run per case) are printed.
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
TIMES = {}


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def grid(nx, nz, step, origin):
    """A flat (x, z) grid at y = origin[1] -> (X, F)."""
    xs, zs = np.meshgrid(np.arange(nx) * step, np.arange(nz) * step, indexing="ij")
    X = np.stack([xs.ravel(), np.zeros(nx * nz), zs.ravel()], 1) + np.asarray(origin, np.float64)
    F = []
    for i in range(nx - 1):
        for k in range(nz - 1):
            a, b, c, d = i * nz + k, (i + 1) * nz + k, (i + 1) * nz + k + 1, i * nz + k + 1
            F += [[a, b, c], [a, c, d]]
    return X, np.array(F, np.int64)


def field(fn, lo, hi, vox):
    from app.core.garment_fit import Sdf
    lo = np.asarray(lo, np.float64)
    n = np.ceil((np.asarray(hi) - lo) / vox).astype(int) + 1
    ax = [lo[i] + vox * np.arange(n[i]) for i in range(3)]
    gx, gy, gz = np.meshgrid(*ax, indexing="ij")
    return Sdf(field=fn(gx, gy, gz).astype(np.float64), lo=lo, vox=vox)


def params(**kw):
    from app.core import drape
    base = dict(substeps=1500, dt=1e-3, gravity=9.81, a_stretch=0.0, a_bend=1e-4, damp=0.02, mu=0.6, grow=0.0,
                max_push=0.001, lmax=0.0)
    base.update(kw)
    return drape.DrapeParams(**base)


def sphere_field():
    return field(lambda x, y, z: np.sqrt(x * x + y * y + z * z) - 0.10, (-0.14, -0.14, -0.14), (0.14, 0.20, 0.14),
                 0.002)


def x5_case():
    """X2's patch, refined, one corner pinned, LRA on -> the drape's X."""
    from app.core import drape
    X, F = grid(5, 5, 0.01, (-0.02, 0.15, -0.02))
    pinned = np.zeros(len(X), bool)
    pinned[0] = True
    res = drape.run(X, F, X.copy(), pinned, sphere_field(), params(lmax=0.006, substeps=600), clear=0.004, lra=True)
    return res


def child(out: str, n_threads: int) -> int:
    from app.core import fit_kernels
    fit_kernels.set_threads(n_threads)
    res = x5_case()
    np.save(out, res.X)
    return 0


def main() -> int:
    from app.core import drape, fit_kernels
    from app.core.garment_fit import Sdf

    # [X6] refine
    X = np.array([[0.0, 0.0, 0.0], [0.04, 0.0, 0.0], [0.0, 0.04, 0.0]])
    F = np.array([[0, 1, 2]])
    Xr, Fr, A = drape.refine(X, F, {"b": np.array([True, True, False]), "i": np.array([7, 8, 9]),
                                    "f": np.array([0.0, 1.0, 2.0])}, 0.015)
    E = np.concatenate([Fr[:, [0, 1]], Fr[:, [1, 2]], Fr[:, [2, 0]]])
    L = np.linalg.norm(Xr[E[:, 0]] - Xr[E[:, 1]], axis=1)
    check(len(Fr) == 16 and len(Xr) == 15, f"[X6] 16 triangles, 15 vertices: {len(Fr)}, {len(Xr)}")
    check(L.max() <= 0.015 and abs(L.max() - 0.04 / 4 * np.sqrt(2)) < 1e-12,
          f"[X6] max edge {L.max():.5f} <= 0.015 (0.01414)")
    check(np.array_equal(Xr[:3], X) and np.array_equal(A["b"][:3], [True, True, False])
          and np.array_equal(A["i"][:3], [7, 8, 9]), "[X6] the original 3 vertices keep their indices and data")
    mid01 = int(np.flatnonzero(np.all(np.isclose(Xr, [0.02, 0.0, 0.0]), axis=1))[0])
    mid12 = int(np.flatnonzero(np.all(np.isclose(Xr, [0.02, 0.02, 0.0]), axis=1))[0])
    check(bool(A["b"][mid01]) and not bool(A["b"][mid12]) and A["i"][mid01] in (7, 8)
          and abs(A["f"][mid12] - 1.5) < 1e-12, "[X6] new vertices: bool AND, int of an end, float mean")

    # [X1] / [X3] hanging cloth, no body
    X, F = grid(21, 21, 0.01, (0.0, 0.5, 0.0))
    pinned = np.isclose(X[:, 2], 0.0)
    far = Sdf(field=np.ones((4, 4, 4)), lo=np.array([-1.0, -1.0, -1.0]), vox=1.0)
    t = time.time()
    res = drape.run(X, F, X.copy(), pinned, far, params(a_bend=1e-6), clear=0.004)
    TIMES["X1"] = (res.report["t_jit_s"], res.report["t_run_s"], time.time() - t)
    Y = res.X
    E = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1), axis=0)
    stretch = np.linalg.norm(Y[E[:, 0]] - Y[E[:, 1]], axis=1) / np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1)
    check(abs(Y[:, 1].min() - 0.30) <= 0.01, f"[X1] lowest vertex {Y[:, 1].min():.4f} (0.30 +- 0.01)")
    check(stretch.max() <= 1.02, f"[X1] max edge stretch {stretch.max():.4f} <= 1.02")
    check(Y.shape == X.shape, f"[X1] the result holds the input vertices only: {Y.shape}")
    keys = {"n", "n_orig", "constraints", "colours", "t_jit_s", "t_run_s", "vmax_tail"}
    check(keys <= set(res.report), f"[X1] report keys: {sorted(res.report)}")
    print("       X1 report " + json.dumps({k: res.report[k] for k in sorted(keys)}))
    check(np.array_equal(Y[pinned], X[pinned]), "[X3] pinned vertices: displacement exactly 0")

    # [X2] patch dropped on a sphere
    X, F = grid(5, 5, 0.01, (-0.02, 0.15, -0.02))
    t = time.time()
    res = drape.run(X, F, X.copy(), np.zeros(len(X), bool), sphere_field(), params(), clear=0.004)
    TIMES["X2"] = (res.report["t_jit_s"], res.report["t_run_s"], time.time() - t)
    r = np.linalg.norm(res.X, axis=1)
    check(r.min() >= 0.103, f"[X2] every vertex at |p| >= 0.103: min {r.min():.5f}, max {r.max():.5f}")
    check(res.X[:, 1].min() < 0.12, f"[X2] the patch fell onto the sphere: lowest y {res.X[:, 1].min():.4f}")

    # [X4] the anchor
    X, F = grid(5, 5, 0.01, (-0.02, -0.03, -0.02))
    half = field(lambda x, y, z: y, (-0.1, -0.1, -0.1), (0.1, 0.1, 0.1), 0.004)
    t = time.time()
    res = drape.run(X, F, X.copy(), np.zeros(len(X), bool), half, params(gravity=0.0, max_push=0.05, anchor_m=0.01,
                                                                          substeps=300), clear=0.004, anchor=X)
    TIMES["X4"] = (res.report["t_jit_s"], res.report["t_run_s"], time.time() - t)
    disp = np.linalg.norm(res.X - X, axis=1)
    check(disp.max() <= 0.010 + 1e-6 and disp.min() > 0.009,
          f"[X4] displacement {disp.min():.7f} .. {disp.max():.7f} (<= 0.010 + 1e-6, pushed to the bound)")

    # [X5] determinism
    a = x5_case()
    b = x5_case()
    TIMES["X5"] = (a.report["t_jit_s"], a.report["t_run_s"], None)
    check(a.report["n"] > a.report["n_orig"], f"[X5] refined: n {a.report['n']} > n_orig {a.report['n_orig']}")
    check(np.array_equal(a.X, b.X), "[X5] two runs in one process: array_equal")
    check(fit_kernels.threads() == 4, f"[X5] this process runs 4 threads: {fit_kernels.threads()}")
    with tempfile.TemporaryDirectory(prefix="drape-xpbd-") as tmp:
        out = str(Path(tmp) / "one.npy")
        proc = subprocess.run([sys.executable, __file__, "--child", out, "1"], capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout[-2000:], proc.stderr[-2000:])
        check(proc.returncode == 0 and np.array_equal(np.load(out), a.X),
              "[X5] set_threads(1) in a child process vs 4 threads here: array_equal")

    for k, (tj, tr, tw) in TIMES.items():
        print(f"       timing {k}: t_jit_s {tj:.3f}, t_run_s {tr:.3f}" + (f", wall {tw:.3f}" if tw else ""))
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        sys.exit(child(sys.argv[2], int(sys.argv[3])))
    sys.exit(main())
