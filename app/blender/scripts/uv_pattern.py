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
* ``pack`` — all islands at ONE px/cm into a square atlas, in rows (``ROW_ORDER``, a fitted kind's ``ROWS``), in
  IMAGE-frame pixels.
* ``ring_strip_uv`` — the cylindrical strip UV of a RING island without construction rows (the fitted kinds' bands).
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
#: 10..36 are the fitted kinds' pieces (step 3a, ``fitted_pattern.parts``); "left" / "right" are the WEARER's.
PARTS = {1: "front", 2: "back", 3: "sleeve_l", 4: "sleeve_r", 5: "band", 6: "collar", 7: "placket", 8: "cuff_l",
         9: "cuff_r",
         10: "front_l", 11: "front_r", 12: "back_l", 13: "back_r", 14: "waistband", 15: "gusset", 16: "leg_l",
         17: "leg_r", 18: "cup_l", 19: "cup_r", 20: "cup_top_l", 21: "cup_top_r", 22: "gore", 23: "band_l",
         24: "band_r", 25: "strap_l", 26: "strap_r", 27: "glove_back_l", 28: "glove_back_r", 29: "palm_l",
         30: "palm_r", 31: "hip_band_l", 32: "hip_band_r", 33: "top_band_l", 34: "top_band_r", 35: "thumb_l",
         36: "thumb_r",
         # step 3b (plan group B): a skirt's (and a dress's skirt part's) two panels, an open jacket's two fronts
         37: "skirt_front", 38: "skirt_back", 39: "left_front", 40: "right_front"}
#: Parts that get a strip UV instead of a flattening: the construction strip (``strip_uv``) where the builder gives
#: rows, else the cylindrical ring strip (``ring_strip_uv``) — the fitted kinds' rings have no construction rows.
STRIP_PARTS = frozenset({5, 6, 8, 9, 14, 23, 24, 31, 32, 33, 34})

#: Atlas rows of ``pack`` (island names). A name in no row goes to an extra last row, sorted.
ROW_ORDER = (("front", "front_2", "back"), ("sleeve_l", "sleeve_r"), ("band", "collar", "placket", "cuff_l", "cuff_r"))
#: The fitted kinds' rows (``pack(rows=ROWS[kind])``; a top keeps ``ROW_ORDER``). Fronts as seen from the front (the
#: wearer's right at image left), backs as seen from behind.
_TROUSER_ROWS = (("front_r", "front_l", "back_l", "back_r"), ("waistband", "cuff_r", "cuff_l"))
ROWS = {
    "trousers": _TROUSER_ROWS,
    "boxers": _TROUSER_ROWS,
    # the gusset rides in the legs' row (a row of its own under them cost Kira's tights 15.81 -> 13.07 px/cm)
    "tights": (("leg_r", "leg_l", "gusset"), ("waistband", "top_band_r", "top_band_l")),
    "briefs": (("front", "back"), ("gusset", "waistband", "hip_band_r", "hip_band_l")),
    "bra": (("cup_r", "cup_l", "gore"), ("cup_top_r", "cup_top_l"), ("band_r", "band_l"), ("strap_r", "strap_l")),
    "bandeau": (("front", "back"), ("band_r", "band_l"), ("strap_r", "strap_l")),
    "gloves": (("glove_back_r", "glove_back_l", "palm_l", "palm_r"), ("thumb_r", "thumb_l", "cuff_r", "cuff_l")),
    # step 3b (plan group B): the panel kinds cut by ``wrap`` — a skirt, a strapless top, a strapless dress
    "skirt": (("skirt_front", "skirt_back"), ("waistband",)),
    "strapless": (("front", "back"),),
    "dress": (("front", "back"), ("skirt_front", "skirt_back"), ("sleeve_r", "sleeve_l", "collar", "band")),
}
#: Step 3b (B5): a second layout ``pack`` tries beside ``ROWS[kind]`` — the larger px/cm wins, a tie keeps ``ROWS``.
#: A wide skirt's panels side by side make a flat, wide atlas (Gelina 10.51 px/cm); stacked they fill the square
#: (12.29); a short one gains as well (Kira 19.98 -> 26.63).
ROWS_ALT = {
    "skirt": (("skirt_front",), ("skirt_back",), ("waistband",)),
    "dress": (("front", "back", "sleeve_r", "sleeve_l"), ("skirt_front", "skirt_back"), ("collar", "band")),
}
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


#: the fitted kinds' solves (``pattern_uv`` with a ``tol``): a direct block-banded Cholesky (``_Banded``) for the
#: LSCM system and the ARAP Laplacian (factored once per island), Jacobi-preconditioned CG where it does not apply.
#: Plain CG took 520 s on Kira's tights (2 x 12 k vertex leg pieces) and 51-53 s on Lirien's / Kai's trousers.
FAST_LSCM = {"tol": 1e-8, "precond": True}
FAST_ARAP = {"cg_tol": 1e-7, "precond": True}
#: ``ring_strip_uv``: the angular window (each side) over which the ring's radius at an angle is averaged — under the
#: 5.625 deg of a 64-segment test ring, so its own vertex columns stay exact.
RING_SMOOTH_RAD = math.radians(5.0)
#: ``_Banded`` gives up (-> PCG) past this bandwidth after the reverse Cuthill-McKee ordering (a block costs bw^3).
BAND_MAX = 1500
#: ``_Banded`` flushes factor entries below this to zero: the fill-in decays geometrically into subnormal floats, and
#: LAPACK on subnormals ran 100x slower (a 256-block inverse 0.5 s instead of 2 ms).
TINY = 1e-150


def _rcm(n, rows, cols):
    """Reverse Cuthill-McKee order of the symmetric pattern (rows, cols) over n unknowns: breadth-first from a
    lowest-degree vertex per component, neighbours by rising degree, reversed. Returns perm (new -> old)."""
    m = rows != cols
    r, c = np.concatenate([rows[m], cols[m]]), np.concatenate([cols[m], rows[m]])
    o = np.lexsort((c, r))
    r, c = r[o], c[o]
    start = np.searchsorted(r, np.arange(n + 1))
    deg = np.diff(start)
    seen = np.zeros(n, bool)

    def bfs(root):
        seen[root] = True
        q = [int(root)]
        h = 0
        while h < len(q):
            v = q[h]
            h += 1
            nb = c[start[v]:start[v + 1]]
            nb = np.unique(nb[~seen[nb]])
            if len(nb):
                nb = nb[np.argsort(deg[nb], kind="stable")]
                seen[nb] = True
                q.extend(nb.tolist())
        return q

    order = []
    for root in np.argsort(deg, kind="stable"):
        if seen[root]:
            continue
        # a pseudo-peripheral root: the last vertex a breadth-first search from ``root`` reaches (from a vertex in
        # the middle of a long piece the levels are twice as wide — Kira's tights leg: bandwidth > BAND_MAX)
        comp = bfs(root)
        seen[comp] = False
        order.extend(bfs(comp[-1]))
    return np.array(order[::-1], dtype=np.int64)


class _Banded:
    """Direct solver for a sparse SPD matrix given as COO triplets (duplicates summed; both triangles present):
    reverse Cuthill-McKee order, then the matrix is block tridiagonal with blocks of its bandwidth, factored by block
    Cholesky (numpy only — Blender's Python has no scipy). ``ok`` is False when the bandwidth passes ``BAND_MAX`` or
    the matrix is not positive definite (a clipped negative cotangent); the caller then keeps its CG."""

    def __init__(self, n, rows, cols, vals):
        self.ok = False
        rows, cols, vals = np.asarray(rows, np.int64), np.asarray(cols, np.int64), np.asarray(vals, float)
        if n == 0:
            return
        # an unknown no valid triangle touches (a vertex only of degenerate ones) has an empty row: it keeps its
        # start value (``solve``'s x0), as in the CG, and gets a unit diagonal so the rest factors
        used = np.zeros(n, bool)
        used[rows[np.abs(vals) > 0]] = True
        self.iso = np.flatnonzero(~used)
        if len(self.iso):
            rows, cols = np.concatenate([rows, self.iso]), np.concatenate([cols, self.iso])
            vals = np.concatenate([vals, np.ones(len(self.iso))])
        perm = _rcm(n, rows, cols)
        ip = np.empty(n, np.int64)
        ip[perm] = np.arange(n)
        pr, pc = ip[rows], ip[cols]
        b = int(max(np.max(np.abs(pr - pc)) + 1, 8))
        self.b = b
        if b > BAND_MAX:
            return
        nb = -(-n // b)
        d = np.zeros((nb, b, b))
        sub = np.zeros((max(nb - 1, 0), b, b))
        br, bc = pr // b, pc // b
        on = br == bc
        np.add.at(d, (br[on], pr[on] % b, pc[on] % b), vals[on])
        lo = br == bc + 1
        np.add.at(sub, (bc[lo], pr[lo] % b, pc[lo] % b), vals[lo])
        pad = nb * b - n
        if pad:
            d[-1, b - pad:, b - pad:] += np.eye(pad)
        linv = np.empty_like(d)
        off = np.empty_like(sub)
        try:
            for k in range(nb):
                lk = np.linalg.cholesky(d[k])
                linv[k] = np.linalg.inv(lk)
                linv[k][np.abs(linv[k]) < TINY] = 0.0
                if k < nb - 1:
                    off[k] = sub[k] @ linv[k].T           # L_{k+1,k} = A_{k+1,k} L_k^-T
                    off[k][np.abs(off[k]) < TINY] = 0.0
                    d[k + 1] -= off[k] @ off[k].T
        except np.linalg.LinAlgError:
            return
        self.n, self.b, self.nb, self.perm, self.linv, self.off = n, b, nb, perm, linv, off
        self.ok = bool(np.all(np.isfinite(linv)))

    def solve(self, rhs, x0=None):
        rhs = np.asarray(rhs, float)
        k_ = rhs.shape[1]
        y = np.zeros((self.nb * self.b, k_))
        y[:self.n] = rhs[self.perm]
        y = y.reshape(self.nb, self.b, k_)
        for k in range(self.nb):
            t = y[k] if k == 0 else y[k] - self.off[k - 1] @ y[k - 1]
            y[k] = self.linv[k] @ t
        for k in range(self.nb - 1, -1, -1):
            t = y[k] if k == self.nb - 1 else y[k] - self.off[k].T @ y[k + 1]
            y[k] = self.linv[k].T @ t
        out = np.empty((self.n, k_))
        out[self.perm] = y.reshape(-1, k_)[:self.n]
        out[self.iso] = 0.0 if x0 is None else np.asarray(x0, float)[self.iso]
        return out


def _cg(matvec, b, x0, tol, maxit, diag=None):
    """Conjugate gradient for an SPD operator, column-wise on an (n, k) right-hand side. ``diag`` (the operator's
    diagonal, (n,)) = Jacobi-preconditioned CG (the fitted kinds' 24 k vertex leg pieces: unpreconditioned, the LSCM
    and ARAP solves of Kira's tights took 520 s); None = plain CG, the top's path unchanged. The stop is the plain
    residual against ``tol`` |b| either way."""
    x = x0.copy()
    r = b - matvec(x)
    inv = None if diag is None else (1.0 / np.where(np.abs(diag) > 1e-30, diag, 1.0))[:, None]
    z = r if inv is None else r * inv
    p = z.copy()
    rz = np.sum(r * z, axis=0)
    rr = np.sum(r * r, axis=0)
    stop = (tol * np.maximum(np.sqrt(np.sum(b * b, axis=0)), 1e-30)) ** 2
    for _ in range(maxit):
        if np.all(rr <= stop):
            break
        ap = matvec(p)
        pap = np.sum(p * ap, axis=0)
        alpha = np.where(pap > 0, rz / np.where(pap > 0, pap, 1.0), 0.0)
        x += alpha * p
        r -= alpha * ap
        z = r if inv is None else r * inv
        rz_new = np.sum(r * z, axis=0)
        rr = rz_new if inv is None else np.sum(r * r, axis=0)
        beta = np.where(rz > 0, rz_new / np.where(rz > 0, rz, 1.0), 0.0)
        p = z + beta * p
        rz = rz_new
    return x


def _boundary(tris, n):
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    keys, cnt = np.unique(e[:, 0] * n + e[:, 1], return_counts=True)
    b = keys[cnt == 1]
    return np.unique(np.concatenate([b // n, b % n]))


def lscm(xyz, tris, tol=1e-12, precond=False):
    """Least-squares conformal map of one island; pins the two boundary vertices farthest apart (3D) at (0, 0) and
    (d, 0). Returns (n, 2) UV in metres (a similarity of the conformal map — ``arap`` fixes the scale). ``tol`` /
    ``precond``: the CG's relative residual and its Jacobi preconditioner (``_cg``; the fitted kinds: 1e-8, on)."""
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
    xf = None
    if precond:
        # M^T M over the free unknowns: per row of M (2 per triangle, 6 entries each) every pair of its entries
        r6 = np.argsort(rows, kind="stable")
        cr, vr = cols[r6].reshape(-1, 6), vals[r6].reshape(-1, 6)
        idx = -np.ones(2 * n, np.int64)
        idx[free] = np.arange(len(free))
        fi = idx[cr]
        pi, pj = np.repeat(fi, 6, axis=1), np.tile(fi, (1, 6))
        pv = np.repeat(vr, 6, axis=1) * np.tile(vr, (1, 6))
        keep = (pi >= 0) & (pj >= 0)
        solver = _Banded(len(free), pi[keep], pj[keep], pv[keep])
        if solver.ok:
            xf = solver.solve(rhs)
    if xf is None:
        diag = np.bincount(cols, vals * vals, minlength=2 * n)[free] if precond else None
        xf = _cg(matvec, rhs, np.zeros_like(rhs), tol, 20 * len(free) + 100, diag=diag)
    full = xp.copy()
    full[free] = xf[:, 0]
    return np.stack([full[:n], full[n:]], axis=1)


def _align_to(uv, ref):
    """``uv`` turned (a rotation, no mirror) and moved onto ``ref`` (same vertices) in the least-squares sense — the
    2D Procrustes angle atan2(sum a x b, sum a . b) over the centred points."""
    a = uv - uv.mean(axis=0)
    b = ref - ref.mean(axis=0)
    ang = math.atan2(float(np.sum(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])), float(np.sum(a * b)))
    c, s_ = math.cos(ang), math.sin(ang)
    return a @ np.array([[c, s_], [-s_, c]]) + ref.mean(axis=0)


def _signed_uv_area2(uv, tris):
    q = uv[tris]
    d1 = q[:, 1] - q[:, 0]
    d2 = q[:, 2] - q[:, 0]
    return d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]


def arap(xyz, tris, uv0, iters=40, cg_tol=1e-9, tol=None, stats=None, precond=False):
    """As-rigid-as-possible flattening (local/global, cotangent weights) from ``uv0``. A start whose orientation
    disagrees with the triangles' own frames (an anti-conformal LSCM) is mirrored first, since the local step only
    fits rotations. One vertex is held at its start position.

    ``tol`` (step 3a, the fitted kinds' 4-41 k vertex pieces): stop after an iteration whose ARAP energy
    sum w |(u_i - u_j) - R dx_ij|^2 (with that iteration's rotations, at its solved UV) changed by less than ``tol`` of
    the previous iteration's; ``iters`` stays the cap. None = always ``iters``. ``stats`` (a dict) gets "iters".
    ``precond``: the global step's CG with the Laplacian's diagonal as Jacobi preconditioner (``_cg``)."""
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

    ldiag = None
    band = None
    if precond:
        ldiag = np.bincount(l_row[l_row == l_col], l_val[l_row == l_col], minlength=n)
        ldiag[~keep] = 1.0
        kk = keep[l_row] & keep[l_col]
        band = _Banded(n, np.concatenate([l_row[kk], [pin]]), np.concatenate([l_col[kk], [pin]]),
                       np.concatenate([l_val[kk], [1.0]]))
        if not band.ok:
            band = None
    done = 0
    e_prev = None
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
        x = band.solve(b, x0) if band is not None else _cg(matvec, b, x0, cg_tol, 10 * n + 100, diag=ldiag)
        x[pin] = uv[pin]
        uv = x
        done += 1
        if tol is not None:
            res = (uv[he_i] - uv[he_j]) - np.einsum("hab,hb->ha", r[he_t], he_dx)
            e = float(np.sum(he_w * np.sum(res * res, axis=1)))
            if e_prev is not None and abs(e_prev - e) <= tol * max(abs(e_prev), 1e-30):
                break
            e_prev = e
    if stats is not None:
        stats["iters"] = done
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


def _layout(ext, order, size_px, margin_cm):
    """The rows of ``order`` (names in no row: one extra last row, sorted), their widths / heights in cm and the
    density ``s`` of that layout (``pack``)."""
    known = [n for row in order for n in row]
    rows = [[n for n in row if n in ext] for row in order]
    rows.append(sorted(n for n in ext if n not in known))
    rows = [r for r in rows if r]
    row_w = [margin_cm + sum(ext[n][2][0] + margin_cm for n in r) for r in rows]
    row_h = [max(ext[n][2][1] for n in r) for r in rows]
    width = max(row_w) if rows else 0.0
    height = margin_cm + sum(h + margin_cm for h in row_h)
    return rows, row_w, row_h, width, _floor2(size_px / max(width, height, 1e-9))


def pack(islands_uv_m, size_px=2048, margin_cm=1.5, rows=None, rows_alt=None):
    """Pack islands (name -> (n, 2) UV in metres, v up) at ONE density into a ``size_px`` square atlas.

    Rows follow ``rows`` (None = ``ROW_ORDER``, a top's; names in no row: one extra last row, sorted). A row is ``margin`` + (island width +
    ``margin``) per island wide and as high as its tallest island; rows stack from the top margin with ``margin``
    between them, each row centred horizontally within the widest row, islands TOP-aligned inside their row.
    ``s`` = floor_0.01(size / max(W, H)) px/cm with W, H the layout extent in cm. ``rows_alt`` (step 3b,
    ``ROWS_ALT[kind]``): a second layout tried the same way — the one with the larger ``s`` is packed, a tie keeps
    ``rows``.

    Returns ({name: (n, 2) IMAGE-frame pixels, x right, y down}, s). Blender UV of a pixel = (x / size,
    1 - y / size)."""
    ext = {}
    for name, uv in islands_uv_m.items():
        uv = np.asarray(uv, float)
        lo, hi = uv.min(axis=0), uv.max(axis=0)
        ext[name] = (lo, hi, (hi - lo) * 100.0)
    rows, row_w, row_h, width, s = _layout(ext, ROW_ORDER if rows is None else rows, size_px, margin_cm)
    if rows_alt is not None:
        alt = _layout(ext, rows_alt, size_px, margin_cm)
        if alt[4] > s:
            rows, row_w, row_h, width, s = alt
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


def shoulder_seam(xyz, shared, centre_xy, neck_ids=None, side_band_m=0.01):
    """Where the shoulder seams lie, per side ("l" = +X of ``centre_xy``, "r" = -X), in cm.

    ``shared`` = the yoke vertices front and back share (the seam), ``neck_ids`` = the ring the seam ends on (the band's
    outer row; ids < 0 are skipped). On a side: the seam's shoulder end is its vertex farthest from the centre in x,
    its neck end the nearest. The side of a neck ring is nearly straight front to back (on a real top 8 cm within 1 cm
    of its widest x), so its widest vertex is no defined point: the ring's SIDE POINT is the middle in y of the ring
    vertices within ``side_band_m`` of the widest x on that side.

    - ``shoulder_dy_cm`` = |y(shoulder end) - centre y| (the seam leaves the shoulder on top of it);
    - ``neck_dy_cm`` = |y(neck end) - y(the ring's side point)| (it reaches the neck at the side, not in front of or
      behind it; None without a ring);
    - ``neck_fwd_cm`` = centre y - y(the ring's side point): how far the neck stands in front of the torso centre
      (a seam from the shoulder point to the side of the neck runs that far forward; None without a ring);
    - ``max_dy_cm`` = max |y - centre y| over the whole seam."""
    P = np.asarray(xyz, float)
    cx, cy = float(centre_xy[0]), float(centre_xy[1])
    ring = [int(v) for v in (neck_ids or []) if int(v) >= 0]
    out = {}
    for side, sgn in (("l", 1.0), ("r", -1.0)):
        ids = [int(v) for v in shared if (P[int(v), 0] - cx) * sgn > 0]
        if not ids:
            continue
        dx = (P[ids, 0] - cx) * sgn
        sh, ne = ids[int(np.argmax(dx))], ids[int(np.argmin(dx))]
        rx = np.array([(P[v, 0] - cx) * sgn for v in ring])
        side_y = None
        if len(ring) and rx.max() > 0:
            ys = P[[v for v, x in zip(ring, rx) if x >= rx.max() - side_band_m], 1]
            side_y = 0.5 * float(ys.min() + ys.max())
        out[side] = {"shoulder_dy_cm": round(float(abs(P[sh, 1] - cy)) * 100, 2),
                     "neck_dy_cm": None if side_y is None else round(abs(float(P[ne, 1]) - side_y) * 100, 2),
                     "neck_fwd_cm": None if side_y is None else round((cy - side_y) * 100, 2),
                     "max_dy_cm": round(float(np.abs(P[ids, 1] - cy).max()) * 100, 2)}
    return out


def _r(x, nd=3):
    return [round(float(v), nd) for v in x]


def islands_payload(islands, islands_uv_m, xyz, size_px=2048, margin_cm=1.5, cap_heights=None, step_cm=1.0,
                    rows=None, rows_alt=None):
    """The ``islands.json`` dict of a piece.

    ``islands`` = the ``split_islands`` list, ``islands_uv_m`` = {name: (n, 2) oriented UV in metres},
    ``xyz`` = the global rest coordinates, ``cap_heights`` = {name: signed cm} for the sleeves, ``rows`` = the row
    layout (``ROWS[kind]``; None = ``ROW_ORDER``; ``rows_alt`` = ``ROWS_ALT[kind]``, ``pack``). Packs the islands (``pack``) and returns {"version", "atlas_px", "px_per_cm", "margin_cm", "islands": [{"name", "part",
    "bbox_px" [x0, y0, x1, y1], "loops_px" [[[x, y], ...], ...], "verts_px", "tris" (the fan triangles, local ids
    into verts_px), "area_cm2" (UV area), "distortion", "cap_height_cm"?}], "seams": ``seam_samples``}. Pixels are
    image-frame (row = (1 - v) * size), rounded to 1/1000 px; no timing or run data, so equal geometry gives a
    byte-equal payload."""
    xyz = np.asarray(xyz, float)
    px, s = pack(islands_uv_m, size_px, margin_cm, rows=rows, rows_alt=rows_alt)
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


def rows_strip_uv(island, rows, xyz):
    """Step 3b (plan group B): the construction strip UV of a band of SEVERAL vertex rows (a skirt's waistband,
    ``wrap_parts``): (n, 2) metres per local vertex.

    ``rows`` = the band's vertex rows top to bottom, each a list of global vertex ids in u order (equal lengths; the
    ring is cut at its first column, which the list repeats at its end). Per column k: v = the slant length up the
    column from the bottom row (the sum of its row-to-row edges), u = the arc length of the column means (the band's
    mid line) up to k. A vertex of the cut column has two local copies: each takes the end (u 0 or the full length)
    nearer the mean u of its face neighbours (``strip_island_uv``'s rule). A band on a flaring hip is a cone: its top
    edge is shorter than its mid line, its bottom edge longer — measured in ``distortion``."""
    xyz = np.asarray(xyz, float)
    grid = np.asarray(rows, dtype=np.int64)                   # (R, K)
    if grid.ndim != 2 or grid.shape[0] < 2 or grid.shape[1] < 2:
        raise ValueError(f"rows_strip_uv: a band needs 2+ rows of 2+ columns, got {grid.shape}")
    pts = xyz[grid]                                           # (R, K, 3)
    slant = np.linalg.norm(np.diff(pts, axis=0), axis=2)      # (R-1, K)
    v_of = np.concatenate([np.cumsum(slant[::-1], axis=0)[::-1], np.zeros((1, grid.shape[1]))], axis=0)
    mid = pts.mean(axis=0)
    u_of = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(mid, axis=0), axis=1))])
    cols = {}
    for r in range(grid.shape[0]):
        for k in range(grid.shape[1]):
            uv = (float(u_of[k]), float(v_of[r, k]))
            if uv not in cols.setdefault(int(grid[r, k]), []):
                cols[int(grid[r, k])].append(uv)
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


def ring_strip_uv(island, xyz, axis_p, axis_d, cut_dir):
    """The strip UV of a RING island without construction rows (the fitted kinds' waistband, cuffs, grip bands, hip
    bands, bra band; decision D6): (n, 2) metres per local vertex.

    Frame: ``e1`` = ``cut_dir`` made orthogonal to ``axis_d``, ``e2`` = ``axis_d`` x ``e1``; the angle
    theta = atan2(rel . e2, rel . e1) in [0, 2 pi) of every vertex about the axis through ``axis_p`` increases to the
    RIGHT as seen from outside with ``axis_d`` up (the tangent of increasing theta at r is ``axis_d`` x r). The ring
    is cut (``fitted_pattern.ring_cut``), so a vertex there has two local copies: theta = 0 is turned to the cut's
    direction, and the copy whose faces lie at the far end takes 2 pi + its angle. An island without copies (opened
    by ``open_islands``): theta from ``cut_dir``, and every corner under pi of a face that spans more than pi takes
    theta + 2 pi. u = the chord sum
    over the sorted distinct angles up to the vertex's, each angle at the ring's radius there (the mean radius of the
    vertices within ``RING_SMOOTH_RAD``: a polygon ring of n segments is n chords long, not 2 pi r; a waist is no
    circle), v = the height (rel . ``axis_d``) less the lowest. A ring whose radius changes with height (a waistband
    over the hip flare) is stretched by r / r_mean along u at its edges — recorded in ``strip_stretch_p95``, not
    gated."""
    xyz = np.asarray(xyz, float)
    ad = np.asarray(axis_d, float)
    ad = ad / np.linalg.norm(ad)
    e1 = np.asarray(cut_dir, float)
    e1 = e1 - (e1 @ ad) * ad
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(ad, e1)
    rel = xyz[island.vmap] - np.asarray(axis_p, float)
    h = rel @ ad
    radial = rel - np.outer(h, ad)
    rad = np.linalg.norm(radial, axis=1)
    th = np.arctan2(radial @ e2, radial @ e1)
    vm = np.asarray(island.vmap)
    gid, cnt = np.unique(vm, return_counts=True)
    dup = np.isin(vm, gid[cnt > 1])
    if dup.any() and (~dup).any():
        # the cut is where the island holds two copies of a vertex: theta = 0 there (its vertices' mean direction
        # — ``axis_p`` from the geometry need not lie in the cut's plane, and a cut a few degrees off theta = 0
        # wrapped the faces between them across the whole strip: Kai's waistband, area ratio 1.93); every other
        # vertex takes [0, 2 pi), a cut copy 2 pi + its angle when its own faces lie at the far end of the strip
        th0 = math.atan2(float(np.sum(np.sin(th[dup]))), float(np.sum(np.cos(th[dup]))))
        th = np.angle(np.exp(1j * (th - th0)))
        far = np.zeros(len(th))
        cnt_n = np.zeros(len(th))
        for poly in island.corner_vid:
            poly = list(poly)
            ref = [c for c in poly if not dup[c]]
            if not ref:
                continue
            m = float(np.mean(np.mod(th[ref], 2 * np.pi)))
            for c in poly:
                if dup[c]:
                    far[c] += m
                    cnt_n[c] += 1
        late = dup & (cnt_n > 0) & (far > np.pi * np.maximum(cnt_n, 1))
        th = np.where(dup, np.where(late, 2 * np.pi + th, th), np.mod(th, 2 * np.pi))
        th = th - min(float(th.min()), 0.0)
    else:
        th = np.mod(th, 2 * np.pi)
        th = np.where(th > 2 * np.pi - 1e-9, 0.0, th)
        bump = np.zeros(len(th), bool)
        for poly in island.corner_vid:
            t = th[list(poly)]
            if t.max() - t.min() > np.pi:
                for c, tv in zip(poly, t):
                    if tv < np.pi:
                        bump[c] = True
        th = th + 2 * np.pi * bump
    ang = np.unique(np.round(th, 12))
    # the ring's own radius at each distinct angle: the mean radius of the vertices within RING_SMOOTH_RAD (on the
    # circle) — a waist is no circle (Lirien's waistband at its mean radius: area ratio 0.83, stretch p95 1.88)
    tm = np.mod(th, 2 * np.pi)
    o = np.argsort(tm)
    ts, rs_ = tm[o], rad[o]
    ext_t = np.concatenate([ts - 2 * np.pi, ts, ts + 2 * np.pi])
    csum = np.concatenate([[0.0], np.cumsum(np.tile(rs_, 3))])
    am = np.mod(ang, 2 * np.pi)
    lo = np.searchsorted(ext_t, am - RING_SMOOTH_RAD, side="left")
    hi = np.searchsorted(ext_t, am + RING_SMOOTH_RAD, side="right")
    r_a = (csum[hi] - csum[lo]) / np.maximum(hi - lo, 1)
    pts = np.stack([r_a * np.cos(ang), r_a * np.sin(ang)], axis=1)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    u = np.interp(th, ang, cum) if len(ang) > 1 else np.zeros(len(th))
    return np.stack([u, h - (h.min() if len(h) else 0.0)], axis=1)


def pattern_uv(faces, part, seam_edges, xyz, axes=None, strips=None, caps=None, size_px=2048, margin_cm=1.5,
               iters=40, rows=None, rings=None, tol=None, rows_alt=None, bands=None):
    """The pattern UV of one garment mesh.

    ``faces`` = vertex-id tuples (the mesh's polygons, in their loop order), ``part`` = their ``uv_part``,
    ``seam_edges`` = marked cut edges (vertex-id pairs), ``xyz`` = the rest coordinates (metres).
    ``axes`` = {part: (up, axis_p, axis_d)} for ``orient`` (a panel part missing there: +Z up round the vertical line
    through its own centroid); ``strips`` = {part: rows} (``strip_island_uv``) for the parts in ``STRIP_PARTS``;
    ``caps`` = {part: (armhole loop ids, shoulder id, underarm id)} — the underarm vertex lies on the seam, so the
    island holds two copies of it, the cap is measured against both (``cap_height``); a cap whose vertices did not
    survive is left out. Step 3a (the fitted kinds): ``rings`` = {part: (axis_p, axis_d, cut_dir)} for the
    ``STRIP_PARTS`` without construction rows (``ring_strip_uv``), ``rows`` = the atlas row layout (``ROWS[kind]``,
    None = a top's ``ROW_ORDER``; ``rows_alt`` = ``ROWS_ALT[kind]``, step 3b), ``tol`` = ``arap``'s adaptive stop
    (None = always ``iters``). Step 3b: ``bands`` = {part: vertex rows top to bottom} for a ``STRIP_PARTS`` band of
    several rows (``rows_strip_uv``).

    Returns {"payload": ``islands_payload``, "corner_uv": per input face the Blender UV of each corner (x / size,
    1 - y / size of the payload's pixels), "islands": names, "faces_per_part": {name: faces}, "area_ratio_min",
    "area_ratio_max", "stretch_p95_max" (panels), "strip_stretch_p95": {name: value} (bands: recorded, not gated),
    "cap_height_cm": {name: cm}, "arap_iters": {name: iterations} (panels)}."""
    xyz = np.asarray(xyz, float)
    part = np.asarray(part, dtype=np.int64)
    axes, strips, caps, rings, bands = axes or {}, strips or {}, caps or {}, rings or {}, bands or {}
    islands = split_islands(len(xyz), faces, part, seam_edges, xyz=xyz)
    uv_m, cap_cm, its = {}, {}, {}
    for isl in islands:
        lx = xyz[isl.vmap]
        tris = np.array([t for poly in isl.corner_vid for t in fan(poly)], dtype=np.int64).reshape(-1, 3)
        if isl.part in STRIP_PARTS and isl.part in bands:
            # the construction strip, then relaxed by ``arap`` from it (A5 review: a low waist's band is a cone —
            # the bare strip stretched 1.2-1.5 at its edges; relaxed 1.03-1.06, the band bowing ~1-2 cm)
            # (``arap`` mirrors a start it reads as anti-conformal: u is mirrored back, so the band keeps the strip's
            # direction — u growing to the right as seen from outside, v up — and ``_align_to`` turns it back onto
            # the strip: ``arap`` holds one vertex only, a twisted band came out tilted 17 degrees)
            uv = rows_strip_uv(isl, bands[isl.part], xyz)
            if len(tris):
                flip = np.sum(_signed_uv_area2(uv, tris)) < 0
                relaxed = arap(lx, tris, uv, iters=iters, tol=tol)
                if flip:
                    relaxed[:, 0] = -relaxed[:, 0]
                uv = _align_to(relaxed, uv)
            uv = uv - uv.min(axis=0)
        elif isl.part in STRIP_PARTS and isl.part in strips:
            uv = strip_island_uv(isl, strips[isl.part], xyz)
            uv = uv - uv.min(axis=0)
        elif isl.part in STRIP_PARTS and isl.part in rings and len(isl.vmap) >= 3:
            uv = ring_strip_uv(isl, xyz, *rings[isl.part])
        elif len(tris) == 0 or len(isl.vmap) < 3:
            uv = np.zeros((len(isl.vmap), 2))
        else:
            up_, ap, ad = axes.get(isl.part, ((0.0, 0.0, 1.0), lx.mean(axis=0), None))
            st = {}
            fast = tol is not None      # the fitted kinds (step 3a): preconditioned, looser CG; a top as before
            uv = arap(lx, tris, lscm(lx, tris, **(FAST_LSCM if fast else {})), iters=iters, tol=tol, stats=st,
                      **(FAST_ARAP if fast else {}))
            its[isl.name] = st.get("iters", iters)
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
    payload = islands_payload(islands, uv_m, xyz, size_px=size_px, margin_cm=margin_cm, cap_heights=cap_cm,
                              rows=rows, rows_alt=rows_alt)
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
            "cap_height_cm": {k: round(float(v), 3) for k, v in cap_cm.items()}, "arap_iters": its}


def wrap_parts(rows, cols, row_y, kind, waistband_m=0.0, waist_y=None):
    """Step 3b (plan group B, A2): the pattern part of every face of ``garment_template_build.wrap`` and its marked cuts —
    the construction labels the faces, never this module's flattening.

    ``wrap`` builds two panels (front = panel 0, back = panel 1), each ``rows`` x ``cols`` vertices (vertex
    ``p * rows * cols + r * cols + c``; column c at the angle (pi or 0) + pi * c / (cols - 1), row 0 the pinned top at
    ``row_y[0]``) and the quads ``(r, c)`` panel by panel, row by row. Parts:

    - ``kind`` "skirt": front 37 (``skirt_front``), back 38 (``skirt_back``); with ``waistband_m`` > 0 the top
      ``nb = max(1, round(waistband_m / step))`` face rows (step = ``row_y[0] - row_y[1]``) of both panels are the
      waistband (14), a ring opened at the BACK CENTRE: the vertical edges of the back panel's column
      ``(cols - 1) // 2`` (pi / 2 for 41 columns) from row 0 to row ``nb``;
    - "dress" (strapless): faces whose upper row lies at or under the row nearest ``waist_y`` are the skirt part
      (37 / 38), the ones above it the bodice (front 1, back 2);
    - every other (a strapless top): front 1, back 2.

    Returns ``(face_part, seam_edges, info)``: one part per face in ``wrap``'s order, the cut edges as vertex-id pairs
    (before the side seams are merged), ``info`` = {"waistband_rows", "waist_row", "band": the waistband's vertex rows
    top to bottom in ``rows_strip_uv``'s order, construction ids}."""
    n_f = rows - 1
    step = float(row_y[0]) - float(row_y[1]) if rows > 1 else 0.0
    nb = max(1, int(round(float(waistband_m) / step))) if kind == "skirt" and waistband_m > 0 and step > 0 else 0
    nb = min(nb, n_f - 1)
    waist_row = None
    if kind == "dress" and waist_y is not None:
        waist_row = int(min(range(rows), key=lambda r: abs(float(row_y[r]) - float(waist_y))))
    parts = []
    for p in (0, 1):
        for r in range(n_f):
            for _c in range(cols - 1):
                if r < nb:
                    parts.append(14)
                elif kind == "skirt":
                    parts.append(37 + p)
                elif waist_row is not None and r >= waist_row:
                    parts.append(37 + p)
                else:
                    parts.append(1 + p)
    seams = []
    band = []
    if nb:
        c = (cols - 1) // 2
        base = rows * cols
        seams = [(base + r * cols + c, base + (r + 1) * cols + c) for r in range(nb)]
        # the band's vertex rows round the ring, cut at the back centre: back c .. cols - 2, front 0 .. cols - 2, back
        # 0 .. c (the back's last column and the front's last are the side seams the builder merges onto the front's
        # first / the back's first); u then grows with the angle — to the right as seen from outside
        for r in range(nb + 1):
            band.append([base + r * cols + k for k in range(c, cols - 1)] + [r * cols + k for k in range(cols - 1)]
                        + [base + r * cols + k for k in range(c + 1)])
    return parts, seams, {"waistband_rows": nb, "waist_row": waist_row, "band": band}
