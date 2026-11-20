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
* ``pack`` — all islands at ONE px/cm into a square atlas, in rows (``ROW_ORDER``), in IMAGE-frame pixels.
* ``seam_samples`` — matched point pairs along every duplicated border (the two sides of a seam), for the seam
  continuity check and the seam letters of the debug pattern sheet.
* ``cap_height`` — the signed sleeve cap height (shoulder point over the underarm seam ends).
* ``islands_payload`` — the ``islands.json`` dict: loops and triangles in atlas pixels, no timing or run data, so
  its sha is a pure function of the geometry.
* ``strip_island_uv`` — a band island's strip UV per island vertex (the closed ring's start vertex has two copies,
  a vertex merged away by ``dissolve_degenerate`` drops its column).
* ``pattern_uv`` — the whole pipeline ``garment_template_build.run()`` calls: split, flatten / strip, orient, cap
  heights, pack, payload, and the per-corner Blender UV of every input face.

Units: metres in, metres out (the UV is in metres until packing). Faces may be quads or n-gons; they are
fan-triangulated (``fan``) for the solves only, the UV stays per island vertex (= per face corner).
"""
import math
from dataclasses import dataclass, field

import numpy as np

#: Pattern parts by the int ``uv_part`` face attribute. 6..9 are reserved (step 3) and never emitted in step 1.
PARTS = {1: "front", 2: "back", 3: "sleeve_l", 4: "sleeve_r", 5: "band", 6: "collar", 7: "placket", 8: "cuff_l",
         9: "cuff_r"}
#: Parts that get the construction-strip UV (``strip_uv``) instead of a flattening.
STRIP_PARTS = frozenset({5, 6, 8, 9})

#: Atlas rows of ``pack`` (island names). A name in no row goes to an extra last row, sorted.
ROW_ORDER = (("front", "front_2", "back"), ("sleeve_l", "sleeve_r"), ("band", "collar", "placket", "cuff_l", "cuff_r"))
#: The payload format of ``islands_payload``.
PAYLOAD_VERSION = 1

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

    # the cotangent Laplacian as COO triplets (each half-edge adds w to (i, i) and (j, j), -w to (i, j) and (j, i));
    # the matvec is one ``bincount`` per column (``np.add.at`` per call made the CG 10x slower on a real top)
    # (duplicate entries summed once)
    l_key, l_inv = np.unique(np.concatenate([he_i * n + he_i, he_j * n + he_j, he_i * n + he_j, he_j * n + he_i]),
                             return_inverse=True)
    l_val = np.bincount(l_inv, np.concatenate([he_w, he_w, -he_w, -he_w]), minlength=len(l_key))
    l_row, l_col = l_key // n, l_key % n
    l_row2 = np.concatenate([l_row, l_row + n])

    def lap(x):  # (n, 2) -> (n, 2), the pinned row zeroed
        out = np.bincount(l_row2, np.concatenate([l_val * x[l_col, 0], l_val * x[l_col, 1]]),
                          minlength=2 * n).reshape(2, n).T.copy()
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


def _floor2(x):
    """Floor to 0.01 (a tiny epsilon keeps an exact quotient such as 17.50 from flooring to 17.49)."""
    return math.floor(x * 100.0 + 1e-6) / 100.0


def pack(islands_uv_m, size_px=2048, margin_cm=1.5):
    """Pack islands (name -> (n, 2) UV in metres, v up) at ONE density into a ``size_px`` square atlas.

    Rows follow ``ROW_ORDER`` (names in no row: one extra last row, sorted). A row is ``margin`` + (island width +
    ``margin``) per island wide and as high as its tallest island; rows stack from the top margin with ``margin``
    between them, each row centred horizontally within the widest row, islands TOP-aligned inside their row.
    ``s`` = floor_0.01(size / max(W, H)) px/cm with W, H the layout extent in cm.

    Returns ({name: (n, 2) IMAGE-frame pixels, x right, y down}, s). Blender UV of a pixel = (x / size,
    1 - y / size)."""
    ext = {}
    for name, uv in islands_uv_m.items():
        uv = np.asarray(uv, float)
        lo, hi = uv.min(axis=0), uv.max(axis=0)
        ext[name] = (lo, hi, (hi - lo) * 100.0)
    known = [n for row in ROW_ORDER for n in row]
    rows = [[n for n in row if n in ext] for row in ROW_ORDER]
    rows.append(sorted(n for n in ext if n not in known))
    rows = [r for r in rows if r]
    row_w = [margin_cm + sum(ext[n][2][0] + margin_cm for n in r) for r in rows]
    row_h = [max(ext[n][2][1] for n in r) for r in rows]
    width = max(row_w) if rows else 0.0
    height = margin_cm + sum(h + margin_cm for h in row_h)
    s = _floor2(size_px / max(width, height, 1e-9))
    out = {}
    y_cm = margin_cm
    for r, rw, rh in zip(rows, row_w, row_h):
        x_cm = margin_cm + 0.5 * (width - rw)
        for n in r:
            lo, hi, size_cm = ext[n]
            uv = np.asarray(islands_uv_m[n], float)
            px = np.empty_like(uv)
            px[:, 0] = (x_cm + (uv[:, 0] - lo[0]) * 100.0) * s
            px[:, 1] = (y_cm + (hi[1] - uv[:, 1]) * 100.0) * s
            out[n] = px
            x_cm += size_cm[0] + margin_cm
        y_cm += rh + margin_cm
    return out, s


def _boundary_halfedges(island):
    """Boundary half-edges (local a, local b) of an island in face winding: a corner edge no other face of the
    island uses."""
    cnt = {}
    for poly in island.corner_vid:
        for c in range(len(poly)):
            a, b = poly[c], poly[(c + 1) % len(poly)]
            k = (min(a, b), max(a, b))
            cnt[k] = cnt.get(k, 0) + 1
    out = []
    for poly in island.corner_vid:
        for c in range(len(poly)):
            a, b = poly[c], poly[(c + 1) % len(poly)]
            if cnt[(min(a, b), max(a, b))] == 1:
                out.append((int(a), int(b)))
    return out


def boundary_loops(island):
    """The island's boundary as closed loops of local vertex ids (face winding), longest first; a loop starts at
    its smallest id. A vertex where two loops touch is followed by the smallest unused successor."""
    nxt = {}
    for a, b in _boundary_halfedges(island):
        nxt.setdefault(a, []).append(b)
    for v in nxt:
        nxt[v].sort()
    loops = []
    while any(nxt.values()):
        start = min(v for v, l in nxt.items() if l)
        loop, v = [start], start
        while True:
            w = nxt[v].pop(0)
            if w == start:
                break
            loop.append(w)
            v = w
            if not nxt.get(v):
                break
        i = loop.index(min(loop))
        loops.append(loop[i:] + loop[:i])
    loops.sort(key=lambda lp: (-len(lp), lp[0]))
    return loops


def seam_samples(islands, px, xyz, step_cm=1.0):
    """Matched point pairs along every duplicated border.

    A seam edge is a mesh edge (global vertex ids) that is a boundary edge of exactly two island sides (two islands,
    or twice the same island when a seam does not separate it). Seam edges are chained through global vertices that
    touch exactly two seam edges and whose two sides continue in the same islands at the same local vertices; any
    other vertex ends a chain. Every chain is sampled every ``step_cm`` of its 3D rest length (``xyz``, global ids),
    from 0 up to and including the last whole step; a sample's pixel on each side is interpolated linearly on the
    same edge at the same fraction.

    ``islands`` = the ``split_islands`` list, ``px`` = {name: (n, 2) image-frame pixels} (``pack``). Returns
    [{"seam", "a", "uv_a_px", "b", "uv_b_px"}] with ``seam`` = the chain index (chains ordered by their island
    names, then their smallest global vertex id), ``a`` <= ``b`` by (name, local vertex) of the chain's first edge."""
    xyz = np.asarray(xyz, float)
    sides = {}  # global edge key -> [(island idx, local a, local b, global a, global b)]
    for ii, isl in enumerate(islands):
        for a, b in _boundary_halfedges(isl):
            ga, gb = int(isl.vmap[a]), int(isl.vmap[b])
            if ga == gb:
                continue
            sides.setdefault((min(ga, gb), max(ga, gb)), []).append((ii, a, b, ga, gb))
    seam = {k: v for k, v in sides.items() if len(v) == 2}
    at = {}
    for k in seam:
        for g in k:
            at.setdefault(g, []).append(k)

    def local_at(side, g):
        ii, a, b, ga, gb = side
        return (ii, a if ga == g else b)

    def continues(k1, k2, g):
        s1 = {local_at(s, g) for s in seam[k1]}
        s2 = {local_at(s, g) for s in seam[k2]}
        return len(s1) == 2 and s1 == s2

    def joint_ok(g):
        ks = at[g]
        return len(ks) == 2 and continues(ks[0], ks[1], g)

    used, chains = set(), []
    for k0 in sorted(seam):
        if k0 in used:
            continue
        # walk back to a chain end (or around a closed loop to its smallest edge)
        k, g = k0, k0[0]
        seen = {k0}
        while joint_ok(g):
            k2 = at[g][0] if at[g][1] == k else at[g][1]
            if k2 in seen:
                break
            seen.add(k2)
            g = k2[0] if k2[1] == g else k2[1]
            k = k2
        edges, verts = [], [g]
        while True:
            used.add(k)
            edges.append(k)
            g = k[0] if k[1] == g else k[1]
            verts.append(g)
            if not joint_ok(g):
                break
            k2 = at[g][0] if at[g][1] == k else at[g][1]
            if k2 in used:
                break
            k = k2
        chains.append((edges, verts))

    built = []
    for edges, verts in chains:
        # side A of the first edge = the smaller (island name, local vertex at the chain start)
        first = sorted(seam[edges[0]], key=lambda s: (islands[s[0]].name, local_at(s, verts[0])[1]))
        cur = [local_at(first[0], verts[0]), local_at(first[1], verts[0])]
        track = [cur]
        for e, g0, g1 in zip(edges, verts, verts[1:]):
            # ``continues`` guaranteed that both sides of e meet the current sides at g0
            cur = [local_at(next(sd for sd in seam[e] if local_at(sd, g0) == key), g1) for key in cur]
            track.append(cur)
        names = tuple(islands[t[0]].name for t in track[0])
        built.append((names, min(verts), verts, track))
    built.sort(key=lambda b: (b[0], b[1]))

    out = []
    for si, (names, _, verts, track) in enumerate(built):
        p3 = xyz[verts]
        seg = np.linalg.norm(np.diff(p3, axis=0), axis=1) * 100.0
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(cum[-1])
        for k in range(int(math.floor(total / step_cm + 1e-6)) + 1):
            t = min(k * step_cm, total)
            j = int(min(np.searchsorted(cum, t, side="right") - 1, len(seg) - 1))
            f = 0.0 if seg[j] <= 0 else (t - cum[j]) / seg[j]
            pts = []
            for side in (0, 1):
                ii0, l0 = track[j][side]
                _, l1 = track[j + 1][side]
                q = px[islands[ii0].name]
                pts.append([round(float(v), 3) for v in (1 - f) * q[l0] + f * q[l1]])
            out.append({"seam": si, "a": names[0], "uv_a_px": pts[0], "b": names[1], "uv_b_px": pts[1]})
    return out


def cap_height(island_uv_cm, loop_ids, shoulder_id, underarm_ids):
    """Signed sleeve cap height in cm: v(shoulder point of the armhole loop) - mean v(the underarm seam ends), with
    ``island_uv_cm`` = the island's (n, 2) UV in cm, v up (negative = an inverted cap). All ids are local vertex ids
    and must lie on ``loop_ids``."""
    loop = {int(v) for v in loop_ids}
    ids = [int(shoulder_id)] + [int(v) for v in underarm_ids]
    if not underarm_ids or any(v not in loop for v in ids):
        raise ValueError("cap_height: the shoulder point and the underarm ends must lie on the armhole loop")
    uv = np.asarray(island_uv_cm, float)
    return float(uv[int(shoulder_id), 1] - np.mean(uv[[int(v) for v in underarm_ids], 1]))


def _r(x, nd=3):
    return [round(float(v), nd) for v in x]


def islands_payload(islands, islands_uv_m, xyz, size_px=2048, margin_cm=1.5, cap_heights=None, step_cm=1.0):
    """The ``islands.json`` dict of a piece.

    ``islands`` = the ``split_islands`` list, ``islands_uv_m`` = {name: (n, 2) oriented UV in metres},
    ``xyz`` = the global rest coordinates, ``cap_heights`` = {name: signed cm} for the sleeves. Packs the islands
    (``pack``) and returns {"version", "atlas_px", "px_per_cm", "margin_cm", "islands": [{"name", "part",
    "bbox_px" [x0, y0, x1, y1], "loops_px" [[[x, y], ...], ...], "verts_px", "tris" (the fan triangles, local ids
    into verts_px), "area_cm2" (UV area), "distortion", "cap_height_cm"?}], "seams": ``seam_samples``}. Pixels are
    image-frame (row = (1 - v) * size), rounded to 1/1000 px; no timing or run data, so equal geometry gives a
    byte-equal payload."""
    xyz = np.asarray(xyz, float)
    px, s = pack(islands_uv_m, size_px, margin_cm)
    caps = cap_heights or {}
    items = []
    for isl in islands:
        q = px[isl.name]
        uv = np.asarray(islands_uv_m[isl.name], float)
        tris = np.array([t for poly in isl.corner_vid for t in fan(poly)], dtype=np.int64).reshape(-1, 3)
        lx = xyz[isl.vmap]
        area = float(np.sum(np.abs(_signed_uv_area2(uv, tris))) * 0.5 * 1e4) if len(tris) else 0.0
        dist = distortion(uv, lx, tris) if len(tris) else {"area_ratio": 0.0, "stretch_p95": 1.0}
        item = {
            "name": isl.name,
            "part": int(isl.part),
            "bbox_px": _r(np.concatenate([q.min(axis=0), q.max(axis=0)])),
            "loops_px": [[_r(q[v]) for v in loop] for loop in boundary_loops(isl)],
            "verts_px": [_r(p) for p in q],
            "tris": [[int(v) for v in t] for t in tris],
            "area_cm2": round(area, 4),
            "distortion": {k: round(float(v), 6) for k, v in dist.items()},
        }
        if isl.name in caps:
            item["cap_height_cm"] = round(float(caps[isl.name]), 3)
        items.append(item)
    return {"version": PAYLOAD_VERSION, "atlas_px": int(size_px), "px_per_cm": s, "margin_cm": float(margin_cm),
            "islands": items, "seams": seam_samples(islands, px, xyz, step_cm)}


def strip_island_uv(island, rows, xyz):
    """``strip_uv`` of a band ``island``: (n, 2) UV in metres per local vertex.

    ``rows`` = [outer ids, inner ids] (global vertex ids, u order, equal length; a CLOSED ring repeats its first column
    at the end). A column whose outer or inner vertex is not in the island (merged away by ``dissolve_degenerate``)
    is dropped from the strip; its surviving vertex is placed at the u interpolated by column index between the kept
    columns, on its own edge (v 0 outer, the mean width inner). A vertex on no row (merged into the band from
    elsewhere) takes the UV of the 3D-nearest placed island vertex. The start vertex of a closed ring has two local
    copies (the cut): each takes the end (u 0 or the full length) nearer the mean u of its face neighbours."""
    xyz = np.asarray(xyz, float)
    outer, inner = [int(v) for v in rows[0]], [int(v) for v in rows[1]]
    have = {int(g) for g in island.vmap}
    kept = [k for k in range(len(outer)) if outer[k] in have and inner[k] in have]
    if len(kept) < 2:
        raise ValueError(f"strip_island_uv: {len(kept)} usable columns in {island.name}")
    # ``strip_uv``'s rule per COLUMN (its dict is keyed by vertex id, and a closed ring's start vertex is both the
    # first and the last column)
    po, pi = xyz[[outer[k] for k in kept]], xyz[[inner[k] for k in kept]]
    mid = 0.5 * (po + pi)
    ku = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(mid, axis=0), axis=1))])
    kw = np.linalg.norm(pi - po, axis=1)
    width = float(np.mean(kw))
    cols = {}  # global id -> [(u, v)]
    for k in range(len(outer)):
        for g, on_inner in ((outer[k], False), (inner[k], True)):
            if g not in have:
                continue
            if k in kept:
                j = kept.index(k)
                uv = (float(ku[j]), float(kw[j]) if on_inner else 0.0)
            else:
                uv = (float(np.interp(k, kept, ku)), width if on_inner else 0.0)
            if uv not in cols.setdefault(g, []):
                cols[g].append(uv)
    n = len(island.vmap)
    uv = np.full((n, 2), np.nan)
    multi = []
    for l in range(n):
        c = cols.get(int(island.vmap[l]))
        if c and len(c) == 1:
            uv[l] = c[0]
        elif c:
            multi.append((l, c))
    nb = {}
    for poly in island.corner_vid:
        for a in poly:
            nb.setdefault(a, set()).update(b for b in poly if b != a)
    for l, c in multi:
        us = [uv[b, 0] for b in nb.get(l, ()) if np.isfinite(uv[b, 0])]
        m = float(np.mean(us)) if us else 0.0
        uv[l] = min(c, key=lambda t: abs(t[0] - m))
    placed = np.where(np.isfinite(uv[:, 0]))[0]
    for l in np.where(~np.isfinite(uv[:, 0]))[0]:
        d = np.linalg.norm(xyz[island.vmap[placed]] - xyz[island.vmap[l]], axis=1)
        uv[l] = uv[placed[int(np.argmin(d))]]
    return uv


def pattern_uv(faces, part, seam_edges, xyz, axes=None, strips=None, caps=None, size_px=2048, margin_cm=1.5,
               iters=40):
    """The pattern UV of one garment mesh.

    ``faces`` = vertex-id tuples (the mesh's polygons, in their loop order), ``part`` = their ``uv_part``,
    ``seam_edges`` = marked cut edges (vertex-id pairs), ``xyz`` = the rest coordinates (metres).
    ``axes`` = {part: (up, axis_p, axis_d)} for ``orient`` (a panel part missing there: +Z up round the vertical line
    through its own centroid); ``strips`` = {part: rows} (``strip_island_uv``) for the parts in ``STRIP_PARTS``;
    ``caps`` = {part: (armhole loop ids, shoulder id, underarm id)} — the underarm vertex lies on the seam, so the
    island holds two copies of it, the cap is measured against both (``cap_height``); a cap whose vertices did not
    survive is left out.

    Returns {"payload": ``islands_payload``, "corner_uv": per input face the Blender UV of each corner (x / size,
    1 - y / size of the payload's pixels), "islands": names, "faces_per_part": {name: faces}, "area_ratio_min",
    "area_ratio_max", "stretch_p95_max" (panels), "strip_stretch_p95": {name: value} (bands: recorded, not gated),
    "cap_height_cm": {name: cm}}."""
    xyz = np.asarray(xyz, float)
    part = np.asarray(part, dtype=np.int64)
    axes, strips, caps = axes or {}, strips or {}, caps or {}
    islands = split_islands(len(xyz), faces, part, seam_edges, xyz=xyz)
    uv_m, cap_cm = {}, {}
    for isl in islands:
        lx = xyz[isl.vmap]
        tris = np.array([t for poly in isl.corner_vid for t in fan(poly)], dtype=np.int64).reshape(-1, 3)
        if isl.part in STRIP_PARTS and isl.part in strips:
            uv = strip_island_uv(isl, strips[isl.part], xyz)
            uv = uv - uv.min(axis=0)
        elif len(tris) == 0 or len(isl.vmap) < 3:
            uv = np.zeros((len(isl.vmap), 2))
        else:
            up_, ap, ad = axes.get(isl.part, ((0.0, 0.0, 1.0), lx.mean(axis=0), None))
            uv = arap(lx, tris, lscm(lx, tris), iters=iters)
            uv = orient(uv, lx, tris, np.asarray(up_, float), np.asarray(ap, float),
                        None if ad is None else np.asarray(ad, float))
        uv_m[isl.name] = uv
        if isl.part in caps:
            loop, sh, ua = caps[isl.part]
            loop_g = {int(g) for g in loop}
            loc_loop = [l for l in range(len(isl.vmap)) if int(isl.vmap[l]) in loop_g]
            loc_sh = [l for l in range(len(isl.vmap)) if int(isl.vmap[l]) == int(sh)]
            loc_ua = [l for l in range(len(isl.vmap)) if int(isl.vmap[l]) == int(ua)]
            if loc_sh and loc_ua and int(sh) in loop_g and int(ua) in loop_g:
                cap_cm[isl.name] = cap_height(uv * 100.0, loc_loop, loc_sh[0], loc_ua)
    payload = islands_payload(islands, uv_m, xyz, size_px=size_px, margin_cm=margin_cm, cap_heights=cap_cm)
    corner_uv = [None] * len(faces)
    by_name = {i["name"]: i for i in payload["islands"]}
    for isl in islands:
        vp = by_name[isl.name]["verts_px"]
        for fi, corner in zip(isl.faces, isl.corner_vid):
            corner_uv[fi] = [(vp[l][0] / size_px, 1.0 - vp[l][1] / size_px) for l in corner]
    panels = [i for i in payload["islands"] if i["part"] not in STRIP_PARTS]
    fpp = {}
    for isl in islands:
        fpp[isl.name] = len(isl.faces)
    return {"payload": payload, "corner_uv": corner_uv, "islands": [i.name for i in islands], "faces_per_part": fpp,
            "area_ratio_min": min((i["distortion"]["area_ratio"] for i in panels), default=None),
            "area_ratio_max": max((i["distortion"]["area_ratio"] for i in panels), default=None),
            "stretch_p95_max": max((i["distortion"]["stretch_p95"] for i in panels), default=None),
            "strip_stretch_p95": {i["name"]: i["distortion"]["stretch_p95"] for i in payload["islands"]
                                  if i["part"] in STRIP_PARTS},
            "cap_height_cm": {k: round(float(v), 3) for k, v in cap_cm.items()}}
