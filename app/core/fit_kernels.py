"""Grid kernels of the garment / footwear fits (``garment_fit.body_sdf``).

- ``fill_slices`` is the 2-D hole fill of every slice of a voxel mask along one axis, done as ONE labelling of the
  whole grid instead of a Python loop over the slices (plan 2026-11-12 fit-sdf-speed-drape, Task 1).
- ``fill_holes`` is ``ndimage.binary_fill_holes`` as one labelling of the background (Task 2).
- ``band_distance`` is the exact point-triangle distance of the field's outside band, a numba kernel that gives the
  same bits as ``garment_fit.point_triangle_distance(...).min(1)`` (Task 2).
- ``threads`` / ``set_threads`` is the fit's thread budget: numba's thread count and the ``workers=`` of the fits'
  KD-tree queries. A refit worker sets it from the pool initializer (``refit_pool._initializer``); elsewhere it is 4.
  Every one of these kernels gives the same result for any thread count.
"""
from __future__ import annotations

import threading

import numpy as np

_THREADS = 4


def threads() -> int:
    """The fit's thread budget (numba kernels, KD-tree ``workers=``); 4 unless ``set_threads`` changed it."""
    return _THREADS


def set_threads(n: int) -> None:
    """Set the fit's thread budget (at least 1). numba's own thread count follows it on every kernel call (it is
    per calling thread there), capped at the pool numba started with."""
    global _THREADS
    _THREADS = max(1, int(n))


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """``ndimage.binary_fill_holes(mask)`` with the default structure, as one labelling of the background: a
    background component (face connectivity, the cross ``binary_fill_holes`` propagates its outside with) that
    touches a face of the grid stays background, every other one is a hole and is filled."""
    from scipy import ndimage
    mask = np.asarray(mask, bool)
    labels, n = ndimage.label(~mask)
    if n == 0:
        return mask.copy()
    border = np.zeros(n + 1, bool)
    for axis in range(mask.ndim):
        for end in (0, -1):
            border[np.take(labels, end, axis=axis)] = True
    border[0] = False                                           # label 0 = the mask itself
    return ~border[labels]


def fill_slices(surf: np.ndarray, axis: int) -> np.ndarray:
    """``surf`` plus the holes of every 2-D slice perpendicular to ``axis`` — equal to
    ``ndimage.binary_fill_holes`` applied to each slice ``surf[..., j, ...]`` on its own.

    One ``ndimage.label(~surf, structure=s)`` call, where ``s`` is the 2-D cross in the plane perpendicular to
    ``axis`` (zero along ``axis``), so no component reaches across slices. A background component that touches
    one of the slice's four in-plane borders is outside (``binary_fill_holes`` seeds its outside from the border
    with the same cross connectivity); every other background component is a hole and is filled.
    """
    from scipy import ndimage
    surf = np.asarray(surf, bool)
    if surf.ndim != 3:
        raise ValueError("fill_slices needs a 3-D mask")
    axis = int(axis) % 3
    s = np.zeros((3, 3, 3), bool)
    centre = [slice(1, 2)] * 3
    for other in range(3):
        if other == axis:
            continue
        line = list(centre)
        line[other] = slice(None)
        s[tuple(line)] = True
    labels, n = ndimage.label(~surf, structure=s)
    if n == 0:
        return surf.copy()
    border = np.zeros(n + 1, bool)
    for other in range(3):
        if other == axis:
            continue
        for end in (0, -1):
            border[np.take(labels, end, axis=other)] = True
    border[0] = True                                            # label 0 = the surface itself
    return surf | ~border[labels]


# --- the exact band (numba) ---------------------------------------------------------------------------------------
# The two kernels are plain Python here and compiled on the first ``band_distance`` call, so importing this module
# never imports numba. ``cache=True`` keeps the machine code in ``__pycache__`` beside this file, or — numba's own
# fallback — in its user-wide cache directory when the tree is read-only.
# Every operation below mirrors ``garment_fit.point_triangle_closest`` / ``point_triangle_distance`` in the same
# order (numpy sums a length-3 last axis left to right; ``fastmath=False`` keeps numba from contracting or
# reassociating), so the result is bit for bit the numpy one.

def _pt_tri_py(px, py, pz, ax, ay, az, bx, by, bz, cx, cy, cz):  # pragma: no cover - compiled by numba
    """Distance of point p to triangle (a, b, c): Ericson's closest-point regions, a degenerate triangle (normal
    length <= 1e-18) by the nearest of its three edges."""
    abx, aby, abz = bx - ax, by - ay, bz - az
    acx, acy, acz = cx - ax, cy - ay, cz - az
    apx, apy, apz = px - ax, py - ay, pz - az
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    bpx, bpy, bpz = px - bx, py - by, pz - bz
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    cpx, cpy, cpz = px - cx, py - cy, pz - cz
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    eps = 1e-30
    nx = aby * acz - abz * acy
    ny = abz * acx - abx * acz
    nz = abx * acy - aby * acx
    if np.sqrt(nx * nx + ny * ny + nz * nz) <= 1e-18:
        best = np.inf
        for e in range(3):
            if e == 0:
                sx, sy, sz, ex, ey, ez = ax, ay, az, bx, by, bz
            elif e == 1:
                sx, sy, sz, ex, ey, ez = ax, ay, az, cx, cy, cz
            else:
                sx, sy, sz, ex, ey, ez = bx, by, bz, cx, cy, cz
            dx, dy, dz = ex - sx, ey - sy, ez - sz
            t = ((px - sx) * dx + (py - sy) * dy + (pz - sz) * dz) / max(dx * dx + dy * dy + dz * dz, eps)
            t = min(max(t, 0.0), 1.0)
            qx, qy, qz = px - (sx + dx * t), py - (sy + dy * t), pz - (sz + dz * t)
            dd = np.sqrt(qx * qx + qy * qy + qz * qz)
            if dd < best:                                       # strict: the first edge wins a tie (argmin)
                best = dd
        return best
    if d1 <= 0 and d2 <= 0:
        qx, qy, qz = ax, ay, az
    elif d3 >= 0 and d4 <= d3:
        qx, qy, qz = bx, by, bz
    elif d6 >= 0 and d5 <= d6:
        qx, qy, qz = cx, cy, cz
    elif vc <= 0 and d1 >= 0 and d3 <= 0:
        t = min(max(d1 / max(abx * abx + aby * aby + abz * abz, eps), 0.0), 1.0)
        qx, qy, qz = ax + abx * t, ay + aby * t, az + abz * t
    elif vb <= 0 and d2 >= 0 and d6 <= 0:
        t = min(max(d2 / max(acx * acx + acy * acy + acz * acz, eps), 0.0), 1.0)
        qx, qy, qz = ax + acx * t, ay + acy * t, az + acz * t
    elif va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        ex, ey, ez = cx - bx, cy - by, cz - bz
        t = (bpx * ex + bpy * ey + bpz * ez) / max(ex * ex + ey * ey + ez * ez, eps)
        t = min(max(t, 0.0), 1.0)
        qx, qy, qz = bx + ex * t, by + ey * t, bz + ez * t
    else:
        den = va + vb + vc
        if not abs(den) > eps:
            den = eps
        v = vb / den
        w = vc / den
        qx, qy, qz = ax + abx * v + acx * w, ay + aby * v + acy * w, az + abz * v + acz * w
    qx, qy, qz = px - qx, py - qy, pz - qz
    return np.sqrt(qx * qx + qy * qy + qz * qz)


_PT_TRI = _pt_tri_py                                            # the compiled kernel after ``_kernel()``


def _band_py(X, P, tris):  # pragma: no cover - compiled by numba
    n, k = tris.shape[0], tris.shape[1]
    out = np.empty(n)
    for i in _prange(n):
        best = np.inf
        for j in range(k):
            a, b, c = tris[i, j, 0], tris[i, j, 1], tris[i, j, 2]
            d = _PT_TRI(X[i, 0], X[i, 1], X[i, 2], P[a, 0], P[a, 1], P[a, 2], P[b, 0], P[b, 1], P[b, 2],
                        P[c, 0], P[c, 1], P[c, 2])
            if d < best:
                best = d
        out[i] = best
    return out


_prange = range                                                 # numba.prange after ``_kernel()``
_BAND = None
_BUILD_LOCK = threading.Lock()
_CALL_LOCK = threading.Lock()
_SERIAL = True                                                  # until numba's threading layer is known


def _kernel():
    """The compiled band kernel (built once per process; numba is imported here, not at module import)."""
    global _BAND, _PT_TRI, _prange
    if _BAND is None:
        with _BUILD_LOCK:
            if _BAND is None:
                import numba
                _prange = numba.prange
                _PT_TRI = numba.njit(cache=True, fastmath=False)(_pt_tri_py)
                _BAND = numba.njit(parallel=True, cache=True, fastmath=False)(_band_py)
    return _BAND


def band_distance(X: np.ndarray, P: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Per row i, the smallest exact distance of point ``X[i]`` to the triangles ``P[tris[i, k]]`` over k ->
    ``(n,)`` float64; equal bit for bit to ``garment_fit.point_triangle_distance(X[:, None], A, B, C).min(1)``.

    ``X`` (n, 3) float, ``P`` (m, 3) float, ``tris`` (n, k, 3) integer vertex indices. Runs on ``threads()``
    numba threads; the rows are independent, so the thread count never changes the result."""
    global _SERIAL
    X = np.ascontiguousarray(X, np.float64)
    P = np.ascontiguousarray(P, np.float64)
    tris = np.ascontiguousarray(tris, np.int64)
    if tris.ndim != 3 or tris.shape[2] != 3 or len(tris) != len(X):
        raise ValueError("band_distance needs tris of shape (len(X), k, 3)")
    if len(X) == 0:
        return np.empty(0)
    if tris.shape[1] == 0:
        return np.full(len(X), np.inf)
    kernel = _kernel()
    import numba
    numba.set_num_threads(min(_THREADS, numba.config.NUMBA_NUM_THREADS))
    if not _SERIAL:
        return kernel(X, P, tris)
    # numba's "workqueue" threading layer must never be entered from two threads at once (the server can run two
    # fits in threads); tbb / omp can. Serialised until the first call has told which layer this process uses.
    with _CALL_LOCK:
        out = kernel(X, P, tris)
        _SERIAL = numba.threading_layer() == "workqueue"
    return out
