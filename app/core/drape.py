"""XPBD drape of a triangle mesh against a body SDF, on Taichi's CPU backend (plan 2026-11-12 fit-sdf-speed-drape,
Task 9).

A port of the drape spike (``~/claude-out/drape-spike/src/drape.py`` + ``refine.py``):

- ``refine``: conforming red-green refinement — every edge longer than ``lmax`` is split at its midpoint until none
  is left; the original vertices keep their indices, new vertices are appended.
- Constraints (``constraints``): stretch along every mesh edge and bend as the distance between the two opposite
  vertices across every interior edge, rest = the rest shape scaled by c (the median ``|X0 edge| / |rest edge|``);
  optional glue of small components to the largest one (``glue_components``, clothing) and long-range attachments
  (``long_range``, hair: a free vertex is tethered to the nearest pinned vertex of its card, never farther than
  its rest distance or its start distance).
- Gauss-Seidel per graph colour (``colour``: greedy, constraints sharing a vertex get different colours): every
  colour is one parallel launch with no two writes to one vertex, so the result does not depend on the thread
  count or on the order of the threads.
- Per substep: ``predict`` (gravity) -> ``solve`` per colour -> ``solve_lra`` -> ``collide`` (the body grown from
  ``clear - grow`` to ``clear`` over the first 60 % of the substeps; the push per substep capped at
  ``max_push`` + the approach speed; Coulomb-like friction ``mu``) -> ``anchor`` (``anchor_m``: never farther than
  that from the anchor positions) -> ``update`` (velocities, damping).
- Early stop at rest (``rest_vmax`` / ``rest_substeps``, off by default): once the body has finished growing, the
  run ends when the largest vertex speed stayed below ``rest_vmax`` for ``rest_substeps`` substeps in a row
  (measured every substep from then on); ``report.substeps_run`` / ``report.rest_stop``.
- Strand mode (strand-hair spec 2026-11-13 § 6.3.1 step 2, the HAAR spike's ``drape.py``): ``run(con=...)`` takes
  the constraints from ``strand_constraints`` (stretch (i, i+1), bend (i, i+2) and (i, i+3) along each strand)
  instead of the triangles, and ``components`` names the strand of each point; the long-range attachments then tie
  every free point to the last pinned point before it on its strand with the ARC between them (an inextensible
  tether, never shorter than the strand). ``grow_from`` grows the body per point instead of as a whole: a point
  that starts inside (``grow_from`` < ``clear``) is held at that depth and released to ``clear`` over the first
  ``GROW_SHARE`` of the substeps, escaping toward its ``escape`` direction while it grows (``ESCAPE_W``; long hair
  that HAAR's body-less generator laid through the shoulders leaves on its own side), and a point that starts
  outside never falls in. ``keep_out = [x0, x1, y0, y1, z0]`` is the face box (open to the front, ``z > z0``):
  after the body, a free point inside it leaves by -x, +x or +y, never deeper than it started and released to
  the box's edge over the same ramp (``keep_out_kernel``, the spike's ``eyebox=2``).

Taichi is started once per process (``_ti``: CPU, f32, ``cpu_max_num_threads = fit_kernels.threads()`` at that
moment, the kernel cache in the temp directory, its version check off — no network); every kernel is compiled
once, on dummy arrays, at that start (``t_jit_s`` of the first run, 0 after). The kernels take ndarrays, so one
compiled kernel serves every mesh size. One drape runs at a time per process (``_RUN_LOCK``).
"""
# No ``from __future__ import annotations`` here: Taichi reads the kernels' annotations as objects.
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.core import fit_kernels

# The body grows from (clear - grow) to clear over this share of the substeps.
GROW_SHARE = 0.6
# The velocity trace samples every this many substeps; the report keeps the last VMAX_TAIL samples.
VMAX_EVERY = 25
VMAX_TAIL = 4
# Glue: candidate main-component vertices per small-component vertex, and the most small vertices one main vertex
# takes.
GLUE_K = 8
GLUE_MAX_LOAD = 2
# Strand mode: the weight of a growing point's escape direction against the SDF gradient (the spike's pref_w), and
# the cap of the keep-out push per substep as a multiple of ``max_push`` (the spike's ``maxpush * 4``).
ESCAPE_W = 1.5
KEEP_OUT_PUSH = 4.0


@dataclass(frozen=True)
class DrapeParams:
    """One drape's parameters: ``substeps`` of ``dt`` seconds, ``gravity`` (m/s^2, along -y), XPBD compliances
    ``a_stretch`` / ``a_bend``, velocity ``damp`` per substep, friction ``mu``, body growth ``grow`` (m), the push cap
    per substep ``max_push`` (m), refinement ``lmax`` (m, 0 = none), ``anchor_m`` (m, 0 = no anchor),
    ``self_clear`` / ``self_rebuild`` (self-collision; not in this engine yet, 0 = off), ``rest_vmax`` (m/s) /
    ``rest_substeps``: the early stop at rest (both > 0 = on; see the module docstring)."""
    substeps: int
    dt: float
    gravity: float
    a_stretch: float
    a_bend: float
    damp: float
    mu: float
    grow: float
    max_push: float
    lmax: float
    anchor_m: float = 0.0
    self_clear: float = 0.0
    self_rebuild: int = 50
    rest_vmax: float = 0.0
    rest_substeps: int = 0


@dataclass
class DrapeResult:
    """The draped positions of the INPUT vertices (refinement vertices dropped) and the run's report."""
    X: np.ndarray
    report: Dict[str, Any] = dc_field(default_factory=dict)


# --- mesh preparation (numpy) ------------------------------------------------------------------------------------

def refine(X, F, arrays: Dict[str, np.ndarray], lmax: float,
           max_rounds: int = 8) -> Tuple[np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
    """Red-green refinement: split every edge longer than ``lmax`` (in ``X``) at its midpoint until none is left
    (at most ``max_rounds`` rounds) -> ``(X, F, arrays)``. Original vertices keep their indices; a new vertex is
    appended per split edge, its data the mean of the edge's ends (bool: AND; integer: the first end's value)."""
    X = np.asarray(X, np.float64)
    arrays = {k: np.asarray(v) for k, v in arrays.items()}
    F = np.asarray(F, np.int64).reshape(-1, 3)
    for _ in range(max_rounds):
        if not len(F):
            break
        E = np.sort(np.stack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1), 2)      # (m, 3, 2)
        L = np.linalg.norm(X[E[..., 0]] - X[E[..., 1]], axis=2)
        longm = L > lmax
        if not longm.any():
            break
        le = np.unique(E[longm], axis=0)
        n0 = len(X)
        mid = n0 + np.arange(len(le))
        key = le[:, 0] * (n0 + 1) + le[:, 1]
        order = np.argsort(key)
        ks = key[order]

        def lookup(a, b):
            k = np.minimum(a, b) * (n0 + 1) + np.maximum(a, b)
            pos = np.clip(np.searchsorted(ks, k), 0, len(ks) - 1)
            return np.where(ks[pos] == k, mid[order[pos]], -1)
        X = np.concatenate([X, (X[le[:, 0]] + X[le[:, 1]]) / 2])
        for k, v in arrays.items():
            if v.dtype == bool:
                nv = v[le[:, 0]] & v[le[:, 1]]
            elif np.issubdtype(v.dtype, np.integer):
                nv = v[le[:, 0]]
            else:
                nv = (v[le[:, 0]].astype(np.float64) + v[le[:, 1]].astype(np.float64)) / 2
            arrays[k] = np.concatenate([v, nv.astype(v.dtype)])
        a, b, c = F[:, 0], F[:, 1], F[:, 2]
        mab, mbc, mca = lookup(a, b), lookup(b, c), lookup(c, a)
        cnt = (mab >= 0).astype(int) + (mbc >= 0) + (mca >= 0)
        out = [F[cnt == 0]]
        s = cnt == 3                                                    # red: four children
        out += [np.stack([a[s], mab[s], mca[s]], 1), np.stack([b[s], mbc[s], mab[s]], 1),
                np.stack([c[s], mca[s], mbc[s]], 1), np.stack([mab[s], mbc[s], mca[s]], 1)]
        for m_, p, q, r in ((mab, a, b, c), (mbc, b, c, a), (mca, c, a, b)):   # green: one split edge (p, q)
            s = (cnt == 1) & (m_ >= 0)
            out += [np.stack([p[s], m_[s], r[s]], 1), np.stack([m_[s], q[s], r[s]], 1)]
        # two splits: the unsplit edge (p, q), r opposite, midpoints m1 on (q, r) and m2 on (r, p)
        for keep, p, q, r, m1, m2 in ((mab, a, b, c, mbc, mca), (mbc, b, c, a, mca, mab), (mca, c, a, b, mab, mbc)):
            s = (cnt == 2) & (keep < 0)
            out += [np.stack([m1[s], r[s], m2[s]], 1), np.stack([p[s], q[s], m1[s]], 1),
                    np.stack([p[s], m1[s], m2[s]], 1)]
        F = np.concatenate(out)
    return X, F, arrays


def constraints(F, rest) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(pairs, lengths, kind)``: every unique mesh edge (kind 0, stretch), then the two vertices opposite each
    interior edge (an edge of exactly two faces; kind 1, bend); lengths measured in ``rest``."""
    F = np.asarray(F, np.int64).reshape(-1, 3)
    R = np.asarray(rest, np.float64)
    if not len(F):
        return np.zeros((0, 2), np.int64), np.zeros(0), np.zeros(0, np.int64)
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    Eu, inv_e, cnt_e = np.unique(E, axis=0, return_inverse=True, return_counts=True)
    inv_e = np.asarray(inv_e).ravel()
    opp = np.concatenate([F[:, 2], F[:, 0], F[:, 1]])
    order = np.argsort(inv_e, kind="stable")
    first = np.r_[0, np.cumsum(cnt_e)[:-1]]
    two = np.flatnonzero(cnt_e == 2)
    B = np.stack([opp[order[first[two]]], opp[order[first[two] + 1]]], 1)
    B = B[B[:, 0] != B[:, 1]]
    pairs = np.concatenate([Eu, B]).astype(np.int64)
    lengths = np.linalg.norm(R[pairs[:, 0]] - R[pairs[:, 1]], axis=1)
    kind = np.r_[np.zeros(len(Eu), np.int64), np.ones(len(B), np.int64)]
    return pairs, lengths, kind


def _components(F: np.ndarray, n: int) -> np.ndarray:
    """The connected component of each of the ``n`` vertices (edges of ``F``)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(F, np.int64).reshape(-1, 3)
    A = coo_matrix((np.ones(F.size), (F.ravel(), np.roll(F, 1, 1).ravel())), shape=(n, n))
    return connected_components(A, directed=False)[1]


def glue_components(X, F) -> np.ndarray:
    """``(k, 2)`` glue pairs: every vertex of a component other than the largest (zipper pulls, buttons, loose
    shells) to a near vertex of the largest — the first of its ``GLUE_K`` nearest that holds fewer than
    ``GLUE_MAX_LOAD`` glues (the last candidate when all are full)."""
    from scipy.spatial import cKDTree
    X = np.asarray(X, np.float64)
    comp = _components(F, len(X))
    if not len(X):
        return np.zeros((0, 2), np.int64)
    big = np.bincount(comp).argmax()
    small = np.flatnonzero(comp != big)
    if not len(small):
        return np.zeros((0, 2), np.int64)
    mainv = np.flatnonzero(comp == big)
    k = min(GLUE_K, len(mainv))
    _, kk = cKDTree(X[mainv]).query(X[small], k=k)
    kk = np.asarray(kk).reshape(len(small), k)
    load: Dict[int, int] = {}
    pick = np.empty(len(small), np.int64)
    for r_, row in enumerate(kk.tolist()):
        cand = row[-1]
        for cand in row:
            if load.get(cand, 0) < GLUE_MAX_LOAD:
                break
        load[cand] = load.get(cand, 0) + 1
        pick[r_] = mainv[cand]
    return np.stack([small, pick], 1)


def long_range(rest, pinned, card) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Long-range attachments ``(free, pin, length)``: per card with both pinned and free vertices, each free vertex
    to the nearest (in ``rest``) pinned vertex of its card; ``length`` = their rest distance."""
    from scipy.spatial import cKDTree
    R = np.asarray(rest, np.float64)
    pinned = np.asarray(pinned, bool)
    card = np.asarray(card, np.int64)
    ii, pp = [], []
    if len(R) and (~pinned).any():
        for cc in np.unique(card[~pinned]):
            mem = np.flatnonzero(card == cc)
            pin, free = mem[pinned[mem]], mem[~pinned[mem]]
            if not len(pin) or not len(free):
                continue
            _, k = cKDTree(R[pin]).query(R[free])
            ii.append(free)
            pp.append(pin[np.asarray(k).ravel()])
    if not ii:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0)
    i, p = np.concatenate(ii), np.concatenate(pp)
    return i, p, np.linalg.norm(R[i] - R[p], axis=1)


def strand_constraints(n_strands: int, n_pts: int, rest: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(pairs, lengths, kind)`` of ``n_strands`` strands of ``n_pts`` points each (strand-major, root first):
    stretch (i, i+1) kind 0, then bend (i, i+2) and (i, i+3) kind 1 — each offset strand by strand; lengths
    measured in ``rest`` (``(n_strands * n_pts, 3)`` or ``(n_strands, n_pts, 3)``)."""
    R = np.asarray(rest, np.float64).reshape(-1, 3)
    n_strands, n_pts = int(n_strands), int(n_pts)
    if len(R) != n_strands * n_pts:
        raise ValueError(f"strand_constraints: {len(R)} rest points for {n_strands} x {n_pts}")
    base = (np.arange(n_strands, dtype=np.int64) * n_pts)[:, None]
    parts, kinds = [], []
    for off, kind in ((1, 0), (2, 1), (3, 1)):
        if n_pts <= off:
            continue
        i = (base + np.arange(n_pts - off, dtype=np.int64)[None, :]).ravel()
        parts.append(np.stack([i, i + off], 1))
        kinds.append(np.full(len(i), kind, np.int64))
    if not parts:
        return np.zeros((0, 2), np.int64), np.zeros(0), np.zeros(0, np.int64)
    pairs = np.concatenate(parts)
    return pairs, np.linalg.norm(R[pairs[:, 0]] - R[pairs[:, 1]], axis=1), np.concatenate(kinds)


def chain_long_range(rest, pinned, chain) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strand mode's long-range attachments ``(free, pin, length)``: the points of each chain (``chain``: one id
    per point, a chain's points consecutive and root first) — every free point to the last pinned point before it
    on its chain, ``length`` = the rest ARC between them (the strand may bend, never stretch). A free point with no
    pinned point before it on its chain gets none."""
    R = np.asarray(rest, np.float64).reshape(-1, 3)
    pinned = np.asarray(pinned, bool).ravel()
    chain = np.asarray(chain, np.int64).ravel()
    n = len(R)
    if not n or not pinned.any():
        return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0)
    same = np.r_[False, chain[1:] == chain[:-1]]
    seg = np.where(same, np.r_[0.0, np.linalg.norm(np.diff(R, axis=0), axis=1)], 0.0)
    arc = np.cumsum(seg)
    start = np.flatnonzero(~same)
    first = np.repeat(start, np.diff(np.r_[start, n]))
    idx = np.arange(n)
    last_pin = np.maximum.accumulate(np.where(pinned, idx, -1))
    free = ~pinned & (last_pin >= first)
    i = idx[free]
    p = last_pin[free]
    return i, p, arc[i] - arc[p]


def box_depth(box, X) -> Tuple[np.ndarray, np.ndarray]:
    """``(depth, exit)`` of points ``X`` in the keep-out box ``[x0, x1, y0, y1, z0]`` (open to the front, z > z0):
    the depth to the nearest of the -x, +x and +y faces and that exit (0 = -x, 1 = +x, 2 = +y); outside: (0, -1).
    The numpy twin of the drape's keep-out kernel."""
    X = np.asarray(X, np.float64).reshape(-1, 3)
    b = np.asarray(box, np.float64)
    inside = (X[:, 0] > b[0]) & (X[:, 0] < b[1]) & (X[:, 1] > b[2]) & (X[:, 1] < b[3]) & (X[:, 2] > b[4])
    d = np.stack([X[:, 0] - b[0], b[1] - X[:, 0], b[3] - X[:, 1]], 1)
    e = np.argmin(d, 1)
    depth = np.where(inside, d[np.arange(len(X)), e], 0.0)
    return depth, np.where(inside, e, -1)


# --- colouring (numba) -------------------------------------------------------------------------------------------

def _colour_py(pairs, n, maxc):  # pragma: no cover - compiled by numba
    used = np.zeros((n, maxc), np.bool_)
    col = np.empty(pairs.shape[0], np.int64)
    for k in range(pairs.shape[0]):
        a, b = pairs[k, 0], pairs[k, 1]
        c = 0
        while used[a, c] or used[b, c]:
            c += 1
        col[k] = c
        used[a, c] = True
        used[b, c] = True
    return col


_COLOUR = None
_COLOUR_LOCK = threading.Lock()


def colour(pairs, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Greedy colouring in constraint order: each constraint takes the smallest colour neither of its vertices
    holds yet -> ``(order, starts)``: ``pairs[order]`` grouped by colour, colour c at ``starts[c]:starts[c + 1]``.
    A vertex in d constraints needs at most 2 d - 1 colours, which bounds the table."""
    global _COLOUR
    pairs = np.ascontiguousarray(np.asarray(pairs, np.int64).reshape(-1, 2))
    if not len(pairs):
        return np.zeros(0, np.int64), np.zeros(1, np.int64)
    if _COLOUR is None:
        with _COLOUR_LOCK:
            if _COLOUR is None:
                import numba
                _COLOUR = numba.njit(cache=True)(_colour_py)
    deg = np.bincount(pairs.ravel(), minlength=n)
    col = _COLOUR(pairs, int(n), int(2 * deg.max()))
    order = np.argsort(col, kind="stable")
    starts = np.r_[0, np.cumsum(np.bincount(col))].astype(np.int64)
    return order, starts


# --- Taichi ------------------------------------------------------------------------------------------------------

_TI: Optional[Dict[str, Any]] = None
_TI_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()


def _build_kernels(ti) -> Dict[str, Any]:
    V3 = ti.types.ndarray(dtype=ti.math.vec3, ndim=1)
    I2 = ti.types.ndarray(dtype=ti.math.ivec2, ndim=1)
    S1 = ti.types.ndarray(dtype=ti.f32, ndim=1)
    I1 = ti.types.ndarray(dtype=ti.i32, ndim=1)
    G3 = ti.types.ndarray(dtype=ti.f32, ndim=3)

    @ti.func
    def sample(sdf: ti.template(), p, lo, vox):
        dims = ti.Vector([sdf.shape[0], sdf.shape[1], sdf.shape[2]], ti.f32)
        q = (p - lo) / vox
        q = ti.max(ti.min(q, dims - 1.001), 0.0)
        i = ti.cast(ti.floor(q), ti.i32)
        f = q - i
        r = 0.0
        for a, b, c in ti.static(ti.ndrange(2, 2, 2)):
            wgt = (f[0] if a else 1 - f[0]) * (f[1] if b else 1 - f[1]) * (f[2] if c else 1 - f[2])
            r += wgt * sdf[i[0] + a, i[1] + b, i[2] + c]
        return r

    @ti.func
    def grad(sdf: ti.template(), p, lo, vox):
        h = vox
        gx = sample(sdf, p + ti.Vector([h, 0.0, 0.0]), lo, vox) - sample(sdf, p - ti.Vector([h, 0.0, 0.0]), lo, vox)
        gy = sample(sdf, p + ti.Vector([0.0, h, 0.0]), lo, vox) - sample(sdf, p - ti.Vector([0.0, h, 0.0]), lo, vox)
        gz = sample(sdf, p + ti.Vector([0.0, 0.0, h]), lo, vox) - sample(sdf, p - ti.Vector([0.0, 0.0, h]), lo, vox)
        g = ti.Vector([gx, gy, gz])
        return g / (g.norm() + 1e-9)

    @ti.kernel
    def predict(x: V3, xp: V3, v: V3, w: S1, dt: ti.f32, g: ti.f32):
        for i in range(x.shape[0]):
            xp[i] = x[i]
            if w[i] > 0:
                vi = v[i]
                vi[1] -= g * dt
                v[i] = vi
                x[i] += vi * dt

    @ti.kernel
    def solve(x: V3, w: S1, ci: I2, cl: S1, ck: I1, lam: S1, a: ti.i32, b: ti.i32, at_s: ti.f32, at_b: ti.f32):
        for k in range(a, b):
            i, j = ci[k][0], ci[k][1]
            wi, wj = w[i], w[j]
            at = at_s if ck[k] == 0 else at_b
            if wi + wj > 0:
                dvec = x[i] - x[j]
                L = dvec.norm()
                if L > 1e-9:
                    C = L - cl[k]
                    dl = (-C - at * lam[k]) / (wi + wj + at)
                    lam[k] += dl
                    nrm = dvec / L
                    x[i] += wi * dl * nrm
                    x[j] -= wj * dl * nrm

    @ti.kernel
    def solve_lra(x: V3, li: I2, ll: S1):
        for k in range(li.shape[0]):
            i, p = li[k][0], li[k][1]
            dvec = x[i] - x[p]
            L = dvec.norm()
            if L > ll[k]:
                x[i] -= (L - ll[k]) * dvec / L

    @ti.kernel
    def collide(x: V3, xp: V3, w: S1, sdf: G3, lox: ti.f32, loy: ti.f32, loz: ti.f32, vox: ti.f32, clr: ti.f32,
                mu: ti.f32, mp: ti.f32):
        lo = ti.Vector([lox, loy, loz])
        for i in range(x.shape[0]):
            if w[i] > 0:
                p = x[i]
                s = sample(sdf, p, lo, vox)
                if s < clr:
                    nrm = grad(sdf, p, lo, vox)
                    approach = ti.max(-(p - xp[i]).dot(nrm), 0.0)
                    pen = ti.min(clr - s, mp + approach)
                    p += pen * nrm
                    dx = p - xp[i]
                    tang = dx - dx.dot(nrm) * nrm
                    tl = tang.norm()
                    if tl < mu * pen:
                        p -= tang
                    elif tl > 1e-12:
                        p -= tang * (mu * pen / tl)
                    x[i] = p

    @ti.kernel
    def collide_grow(x: V3, xp: V3, w: S1, sdf: G3, lox: ti.f32, loy: ti.f32, loz: ti.f32, vox: ti.f32,
                     clr: ti.f32, mu: ti.f32, mp: ti.f32, thr0: S1, pref: V3, pref_w: ti.f32, ramp: ti.f32):
        # strand mode: per point the clearance grows from its own start (thr0) to clr; while growing, a point that
        # started inside escapes toward its preferred side (pref, horizontal) as well as along the gradient
        lo = ti.Vector([lox, loy, loz])
        for i in range(x.shape[0]):
            if w[i] > 0:
                p = x[i]
                s = sample(sdf, p, lo, vox)
                t0 = thr0[i]
                thr = clr
                if t0 < clr:
                    thr = t0 + (clr - t0) * ramp
                if s < thr:
                    nrm = grad(sdf, p, lo, vox)
                    if t0 < clr and ramp < 1.0:
                        q = nrm + pref_w * pref[i]
                        nrm = q / (q.norm() + 1e-9)
                    approach = ti.max(-(p - xp[i]).dot(nrm), 0.0)
                    pen = ti.min(thr - s, mp + approach)
                    p += pen * nrm
                    dx = p - xp[i]
                    tang = dx - dx.dot(nrm) * nrm
                    tl = tang.norm()
                    if tl < mu * pen:
                        p -= tang
                    elif tl > 1e-12:
                        p -= tang * (mu * pen / tl)
                    x[i] = p

    @ti.kernel
    def keep_out_kernel(x: V3, w: S1, bd0: S1, x0: ti.f32, x1: ti.f32, y0: ti.f32, y1: ti.f32, z0: ti.f32,
                        ramp: ti.f32, cap: ti.f32):
        # the face box, open to the front: a free point inside leaves by -x, +x or +y, never deeper than it started
        # (bd0), released to the edge over the ramp
        for i in range(x.shape[0]):
            if w[i] > 0:
                p = x[i]
                if p[0] > x0 and p[0] < x1 and p[1] > y0 and p[1] < y1 and p[2] > z0:
                    d = p[0] - x0
                    e = 0
                    if x1 - p[0] < d:
                        d = x1 - p[0]
                        e = 1
                    if y1 - p[1] < d:
                        d = y1 - p[1]
                        e = 2
                    thr = bd0[i] * (1.0 - ramp)
                    if d > thr:
                        pen = ti.min(d - thr, cap)
                        if e == 0:
                            p[0] -= pen
                        elif e == 1:
                            p[0] += pen
                        else:
                            p[1] += pen
                        x[i] = p

    @ti.kernel
    def anchor(x: V3, xa: V3, r: ti.f32):
        for i in range(x.shape[0]):
            dv = x[i] - xa[i]
            L = dv.norm()
            if L > r:
                x[i] = xa[i] + dv * (r / L)

    @ti.kernel
    def update(x: V3, xp: V3, v: V3, dt: ti.f32, damp: ti.f32):
        for i in range(x.shape[0]):
            v[i] = (x[i] - xp[i]) / dt * (1 - damp)

    @ti.kernel
    def vmax(v: V3) -> ti.f32:
        m = 0.0
        for i in range(v.shape[0]):
            ti.atomic_max(m, v[i].norm())
        return m

    return dict(predict=predict, solve=solve, solve_lra=solve_lra, collide=collide, collide_grow=collide_grow,
                keep_out=keep_out_kernel, anchor=anchor, update=update, vmax=vmax)


def _ti() -> Dict[str, Any]:
    """Taichi, started once per process, with every kernel compiled -> ``{"ti", "k": kernels, "t_jit_s"}``."""
    global _TI
    if _TI is not None:
        return _TI
    with _TI_LOCK:
        if _TI is None:
            os.environ.setdefault("ENABLE_TAICHI_HEADER_PRINT", "0")
            os.environ["TI_SKIP_VERSION_CHECK"] = "ON"            # ti.init would otherwise phone home
            import taichi as ti
            t0 = time.time()
            ti.set_logging_level(ti.WARN)
            ti.init(arch=ti.cpu, default_fp=ti.f32, cpu_max_num_threads=fit_kernels.threads(), offline_cache=True,
                    offline_cache_file_path=os.path.join(tempfile.gettempdir(), "anima-taichi-cache"),
                    fast_math=False, log_level=ti.WARN)
            k = _build_kernels(ti)
            # compile every kernel once, on a one-triangle dummy
            st = _state(ti, np.zeros((3, 3)), np.ones(3, bool), np.zeros((1, 2), np.int64), np.ones(1),
                        np.zeros(1, np.int64), np.zeros((1, 2), np.int64), np.ones(1), np.zeros((3, 3)),
                        np.ones((2, 2, 2)))
            _substep(k, st, 1e-3, 9.81, 0.0, 0.0, 0.004, 0.5, 0.001, 0.02, [(0, 1)], lra=True, anchor_r=0.01,
                     lo=(0.0, 0.0, 0.0), vox=1.0)
            _strand_state(ti, st, np.zeros(3), np.zeros((3, 3)), np.zeros(3))
            _substep(k, st, 1e-3, 9.81, 0.0, 0.0, 0.004, 0.5, 0.001, 0.02, [(0, 1)], lra=True, anchor_r=0.0,
                     lo=(0.0, 0.0, 0.0), vox=1.0, ramp=0.5, per_point=True, keep_out=(0.0, 1.0, 0.0, 1.0, 0.0))
            k["vmax"](st["v"])
            ti.sync()
            _TI = {"ti": ti, "k": k, "t_jit_s": time.time() - t0, "jit_reported": False}
    return _TI


def _state(ti, X, pinned, CON, LEN, KIND, LRA, LRA_L, XA, S) -> Dict[str, Any]:
    """The run's Taichi ndarrays (f32 / i32)."""
    n, nc, nl = len(X), max(len(CON), 1), max(len(LRA), 1)

    def vec3(a):
        out = ti.Vector.ndarray(3, ti.f32, len(a))
        out.from_numpy(np.ascontiguousarray(a, np.float32))
        return out

    def arr(a, dt, size):
        out = ti.ndarray(dt, size)
        if len(a):
            out.from_numpy(np.ascontiguousarray(a, np.int32 if dt == ti.i32 else np.float32))
        else:
            out.fill(0)
        return out

    def ivec2(a, size):
        out = ti.Vector.ndarray(2, ti.i32, size)
        if len(a):
            out.from_numpy(np.ascontiguousarray(a, np.int32))
        else:
            out.fill(0)
        return out

    st = {"x": vec3(X), "xp": vec3(X), "xa": vec3(XA), "v": ti.Vector.ndarray(3, ti.f32, n),
          "w": arr(np.where(pinned, 0.0, 1.0), ti.f32, n), "ci": ivec2(CON, nc), "cl": arr(LEN, ti.f32, nc),
          "ck": arr(KIND, ti.i32, nc), "lam": ti.ndarray(ti.f32, nc), "li": ivec2(LRA, nl),
          "ll": arr(LRA_L, ti.f32, nl), "sdf": ti.ndarray(ti.f32, S.shape)}
    st["v"].fill(0)
    st["lam"].fill(0)
    st["sdf"].from_numpy(np.ascontiguousarray(S, np.float32))
    return st


def _strand_state(ti, st: Dict[str, Any], thr0, pref, bd0) -> None:
    """Strand mode's per-point arrays on ``st``: the start clearance ``thr0``, the escape direction ``pref`` and the
    start depth in the keep-out box ``bd0``."""
    n = st["x"].shape[0]
    st["thr0"] = ti.ndarray(ti.f32, n)
    st["thr0"].from_numpy(np.ascontiguousarray(thr0, np.float32))
    st["pref"] = ti.Vector.ndarray(3, ti.f32, n)
    st["pref"].from_numpy(np.ascontiguousarray(pref, np.float32))
    st["bd0"] = ti.ndarray(ti.f32, n)
    st["bd0"].from_numpy(np.ascontiguousarray(bd0, np.float32))


def _substep(k, st, dt, g, at_s, at_b, clr, mu, mp, damp, seg, *, lra: bool, anchor_r: float, lo,
             vox: float, ramp: float = 1.0, per_point: bool = False,
             keep_out: Optional[Tuple[float, ...]] = None) -> None:
    """One substep: predict, the constraints colour by colour, the tethers, the body (``per_point``: strand mode's
    body grown per point, ``ramp`` of the way), the keep-out box, the anchor, the velocities."""
    k["predict"](st["x"], st["xp"], st["v"], st["w"], dt, g)
    st["lam"].fill(0)
    for a, b in seg:
        k["solve"](st["x"], st["w"], st["ci"], st["cl"], st["ck"], st["lam"], a, b, at_s, at_b)
    if lra:
        k["solve_lra"](st["x"], st["li"], st["ll"])
    if not per_point:
        k["collide"](st["x"], st["xp"], st["w"], st["sdf"], lo[0], lo[1], lo[2], vox, clr, mu, mp)
    else:
        k["collide_grow"](st["x"], st["xp"], st["w"], st["sdf"], lo[0], lo[1], lo[2], vox, clr, mu, mp, st["thr0"],
                          st["pref"], ESCAPE_W, ramp)
    if keep_out is not None:
        k["keep_out"](st["x"], st["w"], st["bd0"], *keep_out, ramp, KEEP_OUT_PUSH * mp)
    if anchor_r > 0:
        k["anchor"](st["x"], st["xa"], anchor_r)
    k["update"](st["x"], st["xp"], st["v"], dt, damp)


def run(X0, F, rest, pinned, field: "garment_fit.Sdf", params: DrapeParams, *, clear: float, lra: bool = False,  # noqa: F821
        glue: bool = False, anchor: Optional[np.ndarray] = None, con: Optional[Tuple[np.ndarray, ...]] = None,
        components: Optional[np.ndarray] = None, keep_out=None, grow_from: Optional[np.ndarray] = None,
        escape: Optional[np.ndarray] = None) -> DrapeResult:
    """Drape the mesh ``(X0, F)`` against ``field`` -> ``DrapeResult`` (the input vertices only).

    ``rest``: the rest shape (per vertex, same order as ``X0``), scaled by c = the median ``|X0 edge| / |rest edge|``;
    ``pinned`` vertices never move (their result is ``X0``'s bits); ``clear``: the distance kept from the body
    (``field`` < 0 inside), reached by growing the body from ``clear - params.grow`` over the first
    ``GROW_SHARE`` of the substeps; ``lra``: long-range attachments per connected component (a card); ``glue``: the
    small components glued to the largest; ``anchor``: the positions ``params.anchor_m`` bounds the displacement
    from (default ``X0``). Self-collision (``params.self_clear``) is not part of this engine yet: ValueError.

    Strand mode (module docstring): ``con`` = ``(pairs, lengths, kind)`` (``strand_constraints``) replaces the
    triangle constraints (``F`` may be empty; no refinement: ``params.lmax`` must be 0); ``components`` (one chain
    id per point) replaces ``_components(F)`` for the long-range attachments, which then follow the strand's arc
    (``chain_long_range``). ``grow_from`` (per point, m): the clearance a point starts with — below ``clear`` for a
    point that starts inside the body — grown to ``clear`` over the first ``GROW_SHARE`` of the substeps instead of
    ``params.grow``; ``escape`` (per point, unit or zero) its preferred way out while it grows. ``keep_out`` =
    ``[x0, x1, y0, y1, z0]``: the face box after the body (``box_depth``; the start depth of each point is the most
    it may keep, released over the same ramp)."""
    if params.self_clear > 0:
        raise ValueError("drape.run: self-collision (self_clear > 0) is not implemented yet")
    X0 = np.asarray(X0, np.float64).reshape(-1, 3)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    pinned_in = np.asarray(pinned, bool).ravel()
    n_orig = len(X0)
    arrays: Dict[str, np.ndarray] = {"rest": np.asarray(rest, np.float64).reshape(-1, 3), "pinned": pinned_in}
    use_anchor = params.anchor_m > 0
    if use_anchor:
        arrays["anchor"] = np.asarray(X0 if anchor is None else anchor, np.float64).reshape(-1, 3)
    X, Fr = X0, F
    if params.lmax > 0:
        if con is not None:
            raise ValueError("drape.run: strand mode (con) takes no refinement (params.lmax must be 0)")
        X, Fr, arrays = refine(X0, F, arrays, params.lmax)
    R, pin = arrays["rest"], arrays["pinned"]
    n = len(X)

    if con is not None:
        pairs, lengths, kind = (np.asarray(con[0], np.int64).reshape(-1, 2), np.asarray(con[1], np.float64).ravel(),
                                np.asarray(con[2], np.int64).ravel())
    else:
        pairs, lengths, kind = constraints(Fr, R)
    st_ = kind == 0
    le = np.linalg.norm(X[pairs[st_, 0]] - X[pairs[st_, 1]], axis=1)
    lr = lengths[st_]
    ok = lr > 1e-9
    c = float(np.median(le[ok] / lr[ok])) if ok.any() else 1.0
    lengths = lengths * c
    G = glue_components(X, Fr) if glue else np.zeros((0, 2), np.int64)
    if len(G):
        pairs = np.concatenate([pairs, G])
        lengths = np.concatenate([lengths, np.linalg.norm(X[G[:, 0]] - X[G[:, 1]], axis=1)])
        kind = np.concatenate([kind, np.zeros(len(G), np.int64)])
    li = lp = np.zeros(0, np.int64)
    lL = np.zeros(0)
    if lra and pin.any():
        if con is not None and components is not None:
            li, lp, lL = chain_long_range(R, pin, components)
        else:
            li, lp, lL = long_range(R, pin, _components(Fr, n) if components is None else components)
        lL = np.maximum(lL * c, np.linalg.norm(X[li] - X[lp], axis=1))
    order, starts = colour(pairs, n)
    pairs, lengths, kind = pairs[order], lengths[order], kind[order]
    seg = [(int(starts[k]), int(starts[k + 1])) for k in range(len(starts) - 1) if starts[k + 1] > starts[k]]

    T = _ti()
    ti, k = T["ti"], T["k"]
    t_jit = 0.0 if T["jit_reported"] else T["t_jit_s"]
    with _RUN_LOCK:
        T["jit_reported"] = True
        st = _state(ti, X, pin, pairs, lengths, kind, np.stack([li, lp], 1) if len(li) else np.zeros((0, 2)), lL,
                    arrays["anchor"] if use_anchor else X, np.asarray(field.field))
        per_point = grow_from is not None
        box = None
        if per_point or keep_out is not None:
            thr0 = (np.full(n, clear) if grow_from is None
                    else np.minimum(np.asarray(grow_from, np.float64).ravel(), clear))
            pref = np.zeros((n, 3)) if escape is None else np.asarray(escape, np.float64).reshape(-1, 3)
            bd0 = np.zeros(n)
            if keep_out is not None:
                box = tuple(float(v) for v in np.asarray(keep_out, np.float64).ravel())
                if len(box) != 5:
                    raise ValueError("drape.run: keep_out is [x0, x1, y0, y1, z0]")
                bd0 = box_depth(box, X)[0]
            _strand_state(ti, st, thr0, pref, bd0)
        lo = tuple(float(v) for v in np.asarray(field.lo, np.float64))
        vox = float(field.vox)
        dt = float(params.dt)
        at_s, at_b = params.a_stretch / dt ** 2, params.a_bend / dt ** 2
        N = int(params.substeps)
        trace = []
        rest_on = params.rest_vmax > 0 and params.rest_substeps > 0
        # the body is fully grown from this substep on (clr == clear); the early stop never cuts the growth short
        grown = int(np.ceil(GROW_SHARE * N)) if params.grow > 0 or per_point or box is not None else 0
        calm, ran, rest_stop = 0, N, False
        t0 = time.time()
        for s_ in range(N):
            clr = clear
            if params.grow > 0 and not per_point:
                clr = clear - params.grow * max(0.0, 1 - s_ / (GROW_SHARE * N))
            ramp = min(1.0, s_ / max(1.0, GROW_SHARE * N))
            _substep(k, st, dt, params.gravity, at_s, at_b, clr, params.mu, params.max_push, params.damp, seg,
                     lra=len(li) > 0,
                     anchor_r=params.anchor_m if use_anchor else 0.0, lo=lo, vox=vox,
                     ramp=ramp, per_point=per_point, keep_out=box)
            if rest_on and s_ + 1 >= grown:
                vm = float(k["vmax"](st["v"]))
                calm = calm + 1 if vm < params.rest_vmax else 0
                if calm >= params.rest_substeps:
                    trace.append(round(vm, 5))
                    ran, rest_stop = s_ + 1, True
                    break
            if s_ % VMAX_EVERY == VMAX_EVERY - 1 or s_ == N - 1:
                trace.append(round(float(k["vmax"](st["v"])), 5))
        ti.sync()
        t_run = time.time() - t0
        Xd = st["x"].to_numpy().astype(np.float64)[:n_orig]
    Xd[pinned_in] = X0[pinned_in]
    report = {"n": int(n), "n_orig": int(n_orig), "constraints": int(len(pairs)), "colours": len(seg),
              "stretch": int((kind == 0).sum()) - int(len(G)), "bend": int((kind == 1).sum()), "glue": int(len(G)),
              "lra": int(len(li)), "pinned": int(pin.sum()), "rest_scale_c": round(c, 6),
              "t_jit_s": round(t_jit, 3), "t_run_s": round(t_run, 3), "vmax_tail": trace[-VMAX_TAIL:],
              "substeps_run": int(ran), "rest_stop": bool(rest_stop)}
    return DrapeResult(X=Xd, report=report)
