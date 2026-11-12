#!/usr/bin/env python3
"""One body field per body: the solid cached per body content on a body lattice, the crop's distance field from
it (``app/core/body_field.py``; plan 2026-11-12 fit-sdf-speed-drape, Task 5). Expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_body_field_cache.py

No world, no server, no storage: every mesh is built in ``smoke_body_field.py`` (imported). The body is that smoke's
[F1] open double-walled tube along x (outer r 0.05, inner r 0.04 reversed, x -0.20 .. +0.20), vox 0.004 throughout.
Before this task there is no ``app/core/body_field`` (every [C*] check fails with ImportError at commit eaa0fd58,
this task's BASE); ``garment_fit.body_sdf`` there laid its grid on the crop's own ``lo``.

The lattice: ``body_solid`` puts its grid at ``L = floor((P.min(0) - 2 vox) / vox) * vox`` and ``field`` snaps a
crop ``(lo, hi)`` outward to it: first cell index ``floor((lo - L) / vox)``, last ``ceil((hi - L) / vox)``.

[C1] Two ``body_sdf`` calls on the [F1] body with different bounds (the [F1] bounds +-(0.25, 0.08, 0.08) and a crop
     of its right half, x 0 .. 0.25): the cache key is ``sha1(P bytes + F bytes + repr(vox))``, equal for both ->
     builds +1, hits +1 (counted from an emptied cache: builds 1, hits 1).
[C2] The same body with ONE vertex moved by 1e-4 along x: other bytes -> another key -> builds 2. The original body
     again -> still in the cache (2 of ``BODY_CACHE_SIZE`` 4) -> builds 2, hits 2. Content, never a path, is the key.
[C3] Sub-voxel bounds: crop lo at ``L + (m + 0.2) vox`` and hi at ``L + (m' + 0.2) vox`` (m = -10, m' = the grid's
     last index + 10: the crop reaches 10 voxels beyond the cached grid on every side), then both shifted by 0.3 vox
     to ``+ 0.5``: floor(m + 0.2) = floor(m + 0.5) = m and ceil(m' + 0.2) = ceil(m' + 0.5) = m' + 1 -> the same snapped
     crop, the same ``Sdf.lo`` (a lattice point: (lo - L) / vox an integer), the same cells -> the field sampled at
     200 fixed world points (seed 11, uniform in the body's box +- 0.03) is ``np.array_equal``. Fails at eaa0fd58:
     there the grid starts AT the bounds, two lattices 0.3 vox apart, and the trilinear samples differ.
[C3b] Bounds shifted by 1.3 voxels instead (floor(m + 1.5) = m + 1: the crop loses one cell on the low side and
     gains one on the high side). Both crops contain the cached grid and 10 - 1 = 9 voxels around it, so every
     inside cell and every outside cell within the band lies in both, and each EDT measures to the same nearest
     cell, the band's KD query sees the same samples (the band cells are the same) -> the overlapping cells are
     ``np.array_equal``.
[C4] Against the Task-2 field (``app/core/garment_fit.py`` at commit 20ebbd27, loaded as its own module; its
     ``body_sdf`` is unchanged up to eaa0fd58), on lattice-aligned bounds ``L - 10 vox .. L + (n_last + 10) vox`` —
     the old grid starts at its bounds, so both grids lie on the same lattice; cells are matched by
     ``round((lo_a - lo_b) / vox)``:
     - raw fields (``exact_band_vox=0``): the same inside, the same EDT — 20ebbd27 takes scipy's
       ``distance_transform_edt``, this task ``sqrt`` of ``edt.edtsq`` (integer squared distances, exact in float32
       below 2^24) in float64 -> |delta| <= 1e-6 m everywhere (the brief's bound; measured 0);
     - full fields, cells outside the band (raw field <= 0 or > 6 vox): |delta| <= 1e-6 m;
     - band cells (raw field in (0, 6 vox]): |delta| <= 0.002 m — pykdtree's choice among equally near samples can
       pick another set of 8 triangles; the profile measured up to 2 mm per cell.
[C5] ``BODY_CACHE_SIZE`` patched to 1, two bodies (the [F1] tube and the [C2] moved one) alternating A B A B: each
     call evicts the other -> 4 builds, 0 hits.
[F1]-[F4] ``smoke_body_field``'s solid checks run again through the cached field (its own docstring derives them;
     the fails-on-old halves still load its pinned f55e4b2c).
"""
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_body_field as sbf  # noqa: E402

BASE = "eaa0fd58"
T2 = "20ebbd27"
VOX = 0.004
F1_BOUNDS = (np.array([-0.25, -0.08, -0.08]), np.array([0.25, 0.08, 0.08]))
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def module_at(rev):
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:app/core/garment_fit.py"])
    mod = types.ModuleType(f"garment_fit_{rev}")
    mod.__file__ = f"<{rev}:app/core/garment_fit.py>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def tube():
    return sbf.open_tube_x(0.05, 0.04, -0.20, 0.20)


def delta(info0, info1):
    return {k: info1[k] - info0[k] for k in ("builds", "hits")}


def overlap(a, b):
    """The common cells of two fields on one lattice -> (view of a, view of b)."""
    off = np.round((b.lo - a.lo) / a.vox).astype(np.int64)    # b's cell 0 in a's indices
    sa, sb = [], []
    for k in range(3):
        start = max(0, int(off[k]))
        stop = min(a.field.shape[k], int(off[k]) + b.field.shape[k])
        sa.append(slice(start, stop))
        sb.append(slice(start - int(off[k]), stop - int(off[k])))
    return a.field[tuple(sa)], b.field[tuple(sb)]


def test_c1_c2(gf, bf):
    P, F = tube()
    bf.clear_cache()
    i0 = bf.cache_info()
    gf.body_sdf(P, F, vox=VOX, bounds=F1_BOUNDS)
    gf.body_sdf(P, F, vox=VOX, bounds=(np.array([0.0, -0.08, -0.08]), np.array([0.25, 0.08, 0.08])))
    d = delta(i0, bf.cache_info())
    check(d == {"builds": 1, "hits": 1}, f"[C1] two bounds on one body: 1 build, 1 hit ({d})")
    P2 = P.copy()
    P2[0, 0] += 1e-4
    gf.body_sdf(P2, F, vox=VOX, bounds=F1_BOUNDS)
    d = delta(i0, bf.cache_info())
    check(d["builds"] == 2, f"[C2] one vertex moved by 1e-4: a new build ({d})")
    gf.body_sdf(P, F, vox=VOX, bounds=F1_BOUNDS)
    d = delta(i0, bf.cache_info())
    check(d == {"builds": 2, "hits": 2}, f"[C2] the original body again: a hit ({d})")


def snapped_bounds(solid, shift):
    last = solid.inside.shape[0] - 1, solid.inside.shape[1] - 1, solid.inside.shape[2] - 1
    lo = solid.lo + (-10 + 0.2 + shift) * solid.vox
    hi = solid.lo + (np.array(last) + 10 + 0.2 + shift) * solid.vox
    return lo, hi


def test_c3(gf, bf, old):
    P, F = tube()
    solid = bf.body_solid(P, F, vox=VOX)
    rng = np.random.default_rng(11)
    X = rng.uniform(P.min(0) - 0.03, P.max(0) + 0.03, (200, 3))
    a = gf.body_sdf(P, F, vox=VOX, bounds=snapped_bounds(solid, 0.0))
    b = gf.body_sdf(P, F, vox=VOX, bounds=snapped_bounds(solid, 0.3))
    k = (a.lo - solid.lo) / VOX
    check(np.array_equal(a.lo, b.lo) and np.allclose(k, np.round(k), atol=1e-9, rtol=0),
          f"[C3] bounds +0.3 vox: the same snapped crop lo, on the body lattice ({np.round(k).astype(int).tolist()} "
          "cells from L)")
    check(np.array_equal(a.sample(X), b.sample(X)), "[C3] bounds +0.3 vox: 200 samples np.array_equal")
    oa = old.body_sdf(P, F, vox=VOX, bounds=snapped_bounds(solid, 0.0))
    ob = old.body_sdf(P, F, vox=VOX, bounds=snapped_bounds(solid, 0.3))
    diff = float(np.abs(oa.sample(X) - ob.sample(X)).max())
    check(diff > 0, f"[C3] {BASE} (grid on the bounds): the samples differ (max |delta| {diff:.2e} m)")
    c = gf.body_sdf(P, F, vox=VOX, bounds=snapped_bounds(solid, 1.3))
    fa, fc = overlap(a, c)
    check(np.array_equal(np.round((c.lo - a.lo) / VOX), np.ones(3)) and np.array_equal(fa, fc),
          f"[C3b] bounds +1.3 vox: crop moved by one cell, the {fa.size} common cells np.array_equal")


def test_c4(gf, bf):
    from app.core.garment_fit import SDF_EXACT_BAND_VOX
    ref_mod = module_at(T2)
    P, F = tube()
    solid = bf.body_solid(P, F, vox=VOX)
    last = np.array(solid.inside.shape) - 1
    bounds = (solid.lo - 10 * VOX, solid.lo + (last + 10) * VOX)
    raw_new = gf.body_sdf(P, F, vox=VOX, bounds=bounds, exact_band_vox=0)
    raw_ref = ref_mod.body_sdf(P, F, vox=VOX, bounds=bounds, exact_band_vox=0)
    rn, rr = overlap(raw_new, raw_ref)
    check(rn.shape == raw_ref.field.shape and np.array_equal(rn < 0, rr < 0),
          f"[C4] lattice-aligned: {T2}'s grid {raw_ref.field.shape} lies in the new one {raw_new.field.shape}, "
          f"the same inside ({int((rr < 0).sum())} cells)")
    d_raw = float(np.abs(rn - rr).max())
    check(d_raw <= 1e-6, f"[C4] raw field (EDT only) vs {T2}: max |delta| {d_raw:.2e} m <= 1e-6")
    new = gf.body_sdf(P, F, vox=VOX, bounds=bounds)
    ref = ref_mod.body_sdf(P, F, vox=VOX, bounds=bounds)
    fn, fr = overlap(new, ref)
    band = (rr > 0) & (rr <= SDF_EXACT_BAND_VOX * VOX)
    d_edt = float(np.abs(fn - fr)[~band].max())
    d_band = np.abs(fn - fr)[band]
    check(d_edt <= 1e-6, f"[C4] full field outside the band vs {T2}: max |delta| {d_edt:.2e} m <= 1e-6")
    check(float(d_band.max()) <= 0.002,
          f"[C4] band cells vs {T2}: max |delta| {float(d_band.max()):.2e} m <= 0.002 "
          f"({int((d_band > 1e-12).sum())} of {int(band.sum())} cells differ by more than 1e-12 m)")


def test_c5(gf, bf):
    P, F = tube()
    P2 = P.copy()
    P2[0, 0] += 1e-4
    saved = bf.BODY_CACHE_SIZE
    try:
        bf.BODY_CACHE_SIZE = 1
        bf.clear_cache()
        i0 = bf.cache_info()
        for body in (P, P2, P, P2):
            gf.body_sdf(body, F, vox=VOX, bounds=F1_BOUNDS)
        d = delta(i0, bf.cache_info())
        check(d == {"builds": 4, "hits": 0}, f"[C5] BODY_CACHE_SIZE 1, A B A B: 4 builds, 0 hits ({d})")
    finally:
        bf.BODY_CACHE_SIZE = saved
        bf.clear_cache()


def main():
    from app.core import garment_fit as gf
    try:
        from app.core import body_field as bf
    except ImportError as exc:
        check(False, f"[C1..C5] app.core.body_field: {exc}")
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    old = module_at(BASE)
    test_c1_c2(gf, bf)
    test_c3(gf, bf, old)
    test_c4(gf, bf)
    test_c5(gf, bf)
    base = sbf.base_module()
    sbf.test_f1(gf, base)
    sbf.test_f2(gf, base)
    sbf.test_f3(gf, base)
    sbf.test_f4(gf)
    FAILS.extend(sbf.FAILS)
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
