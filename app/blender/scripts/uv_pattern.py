"""Sewing-pattern UV islands for garment templates: numpy only, no bpy, no scipy.

``garment_template_build.run()`` imports this module inside Blender; ``scripts/smoke_uv_pattern.py`` checks it by hand
without Blender (plan ``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md``, Task 1).

The part of every face comes from the CONSTRUCTION (``build_bodice`` labels a face when it creates it); this module
never assigns or relabels a part. It only:

* ``split_islands`` — cuts the mesh into islands along part borders and marked seam edges. A part that falls into
  several connected components becomes ``name``, ``name_2``, ... (ordered by the mean x of their rest coordinates,
  +X first). A vertex on a cut gets one copy per side; a seam that does not separate an island (the underarm of a
  sleeve tube) still duplicates its vertices.
* ``lscm`` / ``arap`` — flatten a PANEL island from its built rest geometry: least-squares conformal start, then the
  local/global as-rigid-as-possible solve with cotangent weights and a hand-written conjugate gradient.
* ``orient`` — mirror the island so it is seen from OUTSIDE (a per-part axis gives the outward direction), then
  rotate it so the grain (``up``) points to +v.
* ``strip_uv`` — the construction-strip UV of a BAND island (u = arc length of the mid line, v = across).
* ``distortion`` — area ratio and the 95th percentile stretch of a flattening.

Units: metres in, metres out (the UV is in metres until packing). Faces may be quads or n-gons; they are
fan-triangulated (``fan``) for the solves only, the UV stays per island vertex (= per face corner).
"""
from dataclasses import dataclass, field

import numpy as np

#: Pattern parts by the int ``uv_part`` face attribute. 6..9 are reserved (step 3) and never emitted in step 1.
PARTS = {1: "front", 2: "back", 3: "sleeve_l", 4: "sleeve_r", 5: "band", 6: "collar", 7: "placket", 8: "cuff_l",
         9: "cuff_r"}
#: Parts that get the construction-strip UV (``strip_uv``) instead of a flattening.
STRIP_PARTS = frozenset({5, 6, 8, 9})

#: A cotangent weight is clamped to this magnitude (a needle triangle must not dominate the solve).
COT_MAX = 1e4
#: Twice a triangle's area below this (m^2) counts as degenerate and is left out of the solves.
DEGENERATE_2A = 1e-14


@dataclass
class Island:
    """One UV island. ``faces`` = indices into the input face list; ``vmap`` = local vertex -> input vertex id;
    ``corner_vid`` = per face (same order as ``faces``) the local vertex id of each corner, in the face's winding."""
    name: str
    part: int
    faces: list = field(default_factory=list)
    vmap: np.ndarray = None
    corner_vid: list = field(default_factory=list)


def fan(poly):
    """Fan triangles of one face (a tuple of vertex ids)."""
    return [(poly[0], poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def split_islands(n_verts, faces, part, seam_edges, xyz=None):
    """Split the mesh into islands along part borders, ``seam_edges`` (pairs of vertex ids, either order) and open
    or non-manifold edges. ``xyz`` (rest coordinates) orders the components of one part by their mean x, +X first;
    without it they keep the order of their first face. Returns the islands ordered by part, then component."""
    faces = [tuple(int(v) for v in f) for f in faces]
    part = np.asarray(part, dtype=np.int64)
    seams = {(min(a, b), max(a, b)) for a, b in seam_edges}
    offs = np.zeros(len(faces) + 1, dtype=np.int64)
    for i, f in enumerate(faces):
        offs[i + 1] = offs[i] + len(f)
    edges = {}
    for fi, f in enumerate(faces):
        for c in range(len(f)):
            a, b = f[c], f[(c + 1) % len(f)]
            edges.setdefault((min(a, b), max(a, b)), []).append((fi, c, (c + 1) % len(f)))
    fuf = _UF(len(faces))
    cuf = _UF(int(offs[-1]))
    for key, uses in edges.items():
        if len(uses) != 2 or key in seams:
            continue
        (f, ca, cb), (g, ga, gb) = uses
        if part[f] != part[g]:
            continue
        fuf.union(f, g)
        # the corner of the edge's vertex a in f joins the corner of a in g (and the same for b)
        fa, fb = faces[f][ca], faces[f][cb]
        ga_v = faces[g][ga]
        if ga_v == fa:
            cuf.union(int(offs[f] + ca), int(offs[g] + ga))
            cuf.union(int(offs[f] + cb), int(offs[g] + gb))
        else:
            cuf.union(int(offs[f] + ca), int(offs[g] + gb))
            cuf.union(int(offs[f] + cb), int(offs[g] + ga))
    comps = {}
    for fi in range(len(faces)):
        comps.setdefault(fuf.find(fi), []).append(fi)
    by_part = {}
    for fl in comps.values():
        by_part.setdefault(int(part[fl[0]]), []).append(fl)
    out = []
    for p in sorted(by_part):
        built = []
        for fl in by_part[p]:
            classes = {}  # corner root -> (global vid, min face)
            for fi in fl:
                for c, v in enumerate(faces[fi]):
                    r = cuf.find(int(offs[fi] + c))
                    if r not in classes or fi < classes[r][1]:
                        classes[r] = (v, fi)
            order = sorted(classes, key=lambda r: classes[r])
            local = {r: i for i, r in enumerate(order)}
            vmap = np.array([classes[r][0] for r in order], dtype=np.int64)
            corner = [tuple(local[cuf.find(int(offs[fi] + c))] for c in range(len(faces[fi]))) for fi in fl]
            mx = float(np.asarray(xyz, float)[vmap, 0].mean()) if xyz is not None else 0.0
            built.append((-mx, fl[0], fl, vmap, corner))
        built.sort(key=lambda b: (b[0], b[1]))
        base = PARTS.get(p, f"part{p}")
        for n, (_, _, fl, vmap, corner) in enumerate(built):
            out.append(Island(name=base if n == 0 else f"{base}_{n + 1}", part=p, faces=list(fl), vmap=vmap,
                              corner_vid=corner))
    return out


def _local_frames(xyz, tris):
    """Per triangle: its corners in an isometric 2D frame (T, 3, 2) and twice its area (T,)."""
    p = xyz[tris]
    e1 = p[:, 1] - p[:, 0]
    e2 = p[:, 2] - p[:, 0]
    n = np.cross(e1, e2)
    a2 = np.linalg.norm(n, axis=1)
    l1 = np.linalg.norm(e1, axis=1)
    ex = e1 / np.maximum(l1, 1e-30)[:, None]
    ey = np.cross(n / np.maximum(a2, 1e-30)[:, None], ex)
    loc = np.zeros((len(tris), 3, 2))
    loc[:, 1, 0] = l1
    loc[:, 2, 0] = np.einsum("ij,ij->i", e2, ex)
    loc[:, 2, 1] = np.einsum("ij,ij->i", e2, ey)
    return loc, a2


def _cg(matvec, b, x0, tol, maxit):
    """Conjugate gradient for an SPD operator, column-wise on an (n, k) right-hand side."""
    x = x0.copy()
    r = b - matvec(x)
    p = r.copy()
    rs = np.sum(r * r, axis=0)
    stop = (tol * np.maximum(np.sqrt(np.sum(b * b, axis=0)), 1e-30)) ** 2
    for _ in range(maxit):
        if np.all(rs <= stop):
            break
        ap = matvec(p)
        pap = np.sum(p * ap, axis=0)
        alpha = np.where(pap > 0, rs / np.where(pap > 0, pap, 1.0), 0.0)
        x += alpha * p
        r -= alpha * ap
        rs_new = np.sum(r * r, axis=0)
        beta = np.where(rs > 0, rs_new / np.where(rs > 0, rs, 1.0), 0.0)
        p = r + beta * p
        rs = rs_new
    return x


def _boundary(tris, n):
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    keys, cnt = np.unique(e[:, 0] * n + e[:, 1], return_counts=True)
    b = keys[cnt == 1]
    return np.unique(np.concatenate([b // n, b % n]))


def lscm(xyz, tris):
    """Least-squares conformal map of one island; pins the two boundary vertices farthest apart (3D) at (0, 0) and
    (d, 0). Returns (n, 2) UV in metres (a similarity of the conformal map — ``arap`` fixes the scale)."""
    xyz = np.asarray(xyz, float)
    tris = np.asarray(tris, dtype=np.int64)
    n = len(xyz)
    loc, a2 = _local_frames(xyz, tris)
    ok = a2 > DEGENERATE_2A
    t, loc, a2 = tris[ok], loc[ok], a2[ok]
    bnd = _boundary(t, n)
    if len(bnd) < 2:
        bnd = np.arange(n)
    pb = xyz[bnd]
    d2 = np.sum((pb[:, None, :] - pb[None, :, :]) ** 2, axis=2)
    i, j = np.unravel_index(int(np.argmax(d2)), d2.shape)
    p0, p1 = int(bnd[min(i, j)]), int(bnd[max(i, j)])
    dist = float(np.sqrt(d2[i, j]))
    # complex coefficients W_k = (x_{k+2} - x_{k+1}) + i (y_{k+2} - y_{k+1}), over sqrt(2 A)
    s = 1.0 / np.sqrt(a2)
    rows, cols, vals = [], [], []
    tid = np.arange(len(t))
    for k in range(3):
        k1, k2 = (k + 1) % 3, (k + 2) % 3
        a = (loc[:, k2, 0] - loc[:, k1, 0]) * s
        b = (loc[:, k2, 1] - loc[:, k1, 1]) * s
        vid = t[:, k]
        # Re: a u - b v ; Im: b u + a v
        rows += [2 * tid, 2 * tid, 2 * tid + 1, 2 * tid + 1]
        cols += [vid, n + vid, vid, n + vid]
        vals += [a, -b, b, a]
    rows = np.concatenate(rows)
    cols = np.concatenate(cols)
    vals = np.concatenate(vals)
    m_rows = 2 * len(t)
    pinned = np.array([p0, p1, n + p0, n + p1])
    xp = np.zeros(2 * n)
    xp[p0], xp[p1] = 0.0, dist
    free = np.setdiff1d(np.arange(2 * n), pinned)

    def mtm(x_full):
        y = np.bincount(rows, vals * x_full[cols], minlength=m_rows)
        return np.bincount(cols, vals * y[rows], minlength=2 * n)

    def matvec(xf):
        full = np.zeros(2 * n)
        full[free] = xf[:, 0]
        return mtm(full)[free][:, None]

    rhs = -mtm(xp)[free][:, None]
    xf = _cg(matvec, rhs, np.zeros_like(rhs), 1e-12, 20 * len(free) + 100)
    full = xp.copy()
    full[free] = xf[:, 0]
    return np.stack([full[:n], full[n:]], axis=1)


def _signed_uv_area2(uv, tris):
    q = uv[tris]
    d1 = q[:, 1] - q[:, 0]
    d2 = q[:, 2] - q[:, 0]
    return d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]


def arap(xyz, tris, uv0, iters=40, cg_tol=1e-9):
    """As-rigid-as-possible flattening (local/global, cotangent weights) from ``uv0``. A start whose orientation
    disagrees with the triangles' own frames (an anti-conformal LSCM) is mirrored first, since the local step only
    fits rotations. One vertex is held at its start position."""
    xyz = np.asarray(xyz, float)
    tris = np.asarray(tris, dtype=np.int64)
    uv = np.asarray(uv0, float).copy()
    n = len(xyz)
    loc, a2 = _local_frames(xyz, tris)
    ok = a2 > DEGENERATE_2A
    t, loc, a2 = tris[ok], loc[ok], a2[ok]
    if np.sum(_signed_uv_area2(uv, t)) < 0:
        uv[:, 0] = -uv[:, 0]
    # half-edges (i, j) opposite corner k, weight cot(angle at k) / 2
    he_t, he_i, he_j, he_w, he_dx = [], [], [], [], []
    tid = np.arange(len(t))
    for k in range(3):
        i, j = (k + 1) % 3, (k + 2) % 3
        a = loc[:, i] - loc[:, k]
        b = loc[:, j] - loc[:, k]
        cot = (a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1]) / np.maximum(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]), 1e-30)
        he_t.append(tid)
        he_i.append(t[:, i])
        he_j.append(t[:, j])
        he_w.append(0.5 * np.clip(cot, -COT_MAX, COT_MAX))
        he_dx.append(loc[:, i] - loc[:, j])
    he_t = np.concatenate(he_t)
    he_i = np.concatenate(he_i)
    he_j = np.concatenate(he_j)
    he_w = np.concatenate(he_w)
    he_dx = np.concatenate(he_dx)
    pin = int(t[0, 0]) if len(t) else 0
    keep = np.ones(n, bool)
    keep[pin] = False

    def lap(x):  # (n, 2) -> (n, 2), the pinned row zeroed
        d = he_w[:, None] * (x[he_i] - x[he_j])
        out = np.zeros_like(x)
        np.add.at(out, he_i, d)
        np.add.at(out, he_j, -d)
        out[~keep] = 0.0
        return out

    def matvec(x):
        y = x.copy()
        y[~keep] = 0.0
        return lap(y)

    for _ in range(iters):
        du = uv[he_i] - uv[he_j]
        s = np.zeros((len(t), 2, 2))
        np.add.at(s, he_t, he_w[:, None, None] * du[:, :, None] * he_dx[:, None, :])
        u_, _, vt = np.linalg.svd(s)
        r = u_ @ vt
        neg = np.linalg.det(r) < 0
        if np.any(neg):
            u_[neg, :, 1] *= -1
            r[neg] = u_[neg] @ vt[neg]
        rdx = np.einsum("hab,hb->ha", r[he_t], he_dx) * he_w[:, None]
        b = np.zeros((n, 2))
        np.add.at(b, he_i, rdx)
        np.add.at(b, he_j, -rdx)
        # move the pinned vertex's known value to the right-hand side
        fixed = np.zeros((n, 2))
        fixed[pin] = uv[pin]
        b = b - lap(fixed)
        b[pin] = 0.0
        x0 = uv.copy()
        x0[pin] = 0.0
        x = _cg(matvec, b, x0, cg_tol, 10 * n + 100)
        x[pin] = uv[pin]
        uv = x
    return uv


def orient(uv, xyz, tris, up, axis_p, axis_d):
    """Mirror and rotate a flattened island so it is seen from outside with the grain up, then move its bbox to
    the origin.

    1. Outward of triangle t = the component of (centroid - ``axis_p``) orthogonal to ``axis_d`` (``None`` = the
       vertical +Z line: the horizontal radial). u is mirrored when the area-weighted
       sum of sign(n_t . out_t) * sign(uv area_t) is negative — both signs flip with the winding, so the test reads
       geometry, not winding.
    2. The area-weighted mean of J_t . up (J_t = the triangle's 3D -> UV map) is rotated onto +v.
    """
    xyz = np.asarray(xyz, float)
    tris = np.asarray(tris, dtype=np.int64)
    uv = np.asarray(uv, float).copy()
    up = np.asarray(up, float)
    axis_p = np.asarray(axis_p, float)
    axis_d = np.array([0.0, 0.0, 1.0]) if axis_d is None else np.asarray(axis_d, float)
    axis_d = axis_d / np.linalg.norm(axis_d)
    p = xyz[tris]
    e1 = p[:, 1] - p[:, 0]
    e2 = p[:, 2] - p[:, 0]
    nrm = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    rel = p.mean(axis=1) - axis_p
    out = rel - np.outer(rel @ axis_d, axis_d)
    s = np.sum(area * np.sign(np.einsum("ij,ij->i", nrm, out)) * np.sign(_signed_uv_area2(uv, tris)))
    if s < 0:
        uv[:, 0] = -uv[:, 0]
    q = uv[tris]
    f = np.stack([q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]], axis=2)  # (T, 2, 2) uv edge columns
    e = np.stack([e1, e2], axis=2)  # (T, 3, 2)
    ete = np.einsum("tai,taj->tij", e, e)
    det = ete[:, 0, 0] * ete[:, 1, 1] - ete[:, 0, 1] ** 2
    ok = det > DEGENERATE_2A ** 2
    inv = np.zeros_like(ete)
    inv[ok, 0, 0] = ete[ok, 1, 1] / det[ok]
    inv[ok, 1, 1] = ete[ok, 0, 0] / det[ok]
    inv[ok, 0, 1] = inv[ok, 1, 0] = -ete[ok, 0, 1] / det[ok]
    jac = f @ inv @ np.transpose(e, (0, 2, 1))  # (T, 2, 3)
    g = np.sum(area[:, None] * (jac @ up), axis=0)
    if np.linalg.norm(g) > 0:
        ang = np.pi / 2 - np.arctan2(g[1], g[0])
        c, sn = np.cos(ang), np.sin(ang)
        uv = uv @ np.array([[c, sn], [-sn, c]])
    return uv - uv.min(axis=0)


def strip_uv(rows, xyz):
    """Construction-strip UV of a band: ``rows`` = [outer edge vertex ids, inner (up) edge vertex ids], both in u
    order and of equal length. u = cumulative arc length of the mid line, v = 0 on the outer edge and the edge's
    local width on the inner edge (metres). Returns {vertex id: (u, v)}."""
    xyz = np.asarray(xyz, float)
    outer, inner = [int(v) for v in rows[0]], [int(v) for v in rows[1]]
    if len(outer) != len(inner):
        raise ValueError(f"strip rows differ in length: {len(outer)} != {len(inner)}")
    po, pi = xyz[outer], xyz[inner]
    mid = 0.5 * (po + pi)
    u = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(mid, axis=0), axis=1))])
    w = np.linalg.norm(pi - po, axis=1)
    out = {}
    for k in range(len(outer)):
        out[outer[k]] = (float(u[k]), 0.0)
        out[inner[k]] = (float(u[k]), float(w[k]))
    return out


def distortion(uv, xyz, tris):
    """{"area_ratio": UV area / 3D area, "stretch_p95": the 95th percentile over triangles of
    max(sigma_1, 1 / sigma_2) of the per-triangle 3D -> UV map}."""
    xyz = np.asarray(xyz, float)
    tris = np.asarray(tris, dtype=np.int64)
    uv = np.asarray(uv, float)
    loc, a2 = _local_frames(xyz, tris)
    ok = a2 > DEGENERATE_2A
    loc, a2, t = loc[ok], a2[ok], tris[ok]
    uva2 = _signed_uv_area2(uv, t)
    q = uv[t]
    f = np.stack([q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]], axis=2)
    x = np.stack([loc[:, 1] - loc[:, 0], loc[:, 2] - loc[:, 0]], axis=2)
    jac = f @ np.linalg.inv(x)
    sv = np.linalg.svd(jac, compute_uv=False)
    stretch = np.maximum(sv[:, 0], 1.0 / np.maximum(sv[:, 1], 1e-12))
    return {"area_ratio": float(np.sum(np.abs(uva2)) / np.sum(a2)),
            "stretch_p95": float(np.percentile(stretch, 95)) if len(stretch) else 1.0}
