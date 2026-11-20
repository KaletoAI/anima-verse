"""The pure half of the template projection bake (``garment_template_drape.project_bake``): numpy only, no bpy — the
Blender script imports it, and ``scripts/smoke_bake_register.py`` checks it by hand without Blender.

Bug round 2026-11-20 ("template textures are random"). The bake used to lay the piece's bounding box onto the view's
alpha bounding box: a strap, a chain or a hanging cord the picture has and the template does not stretched that box,
and the piece's texels sampled transparent pixels (Glut's bra: coverage 0.43, 57 % of the texels push-pull fill).
Now the projected piece is REGISTERED to the view by its silhouette:

* ``mesh_mask`` rasterises the projected triangles on a grid over the piece's own box;
* ``register`` finds the axis-aligned map piece -> picture (a scale and an offset per axis) whose silhouette overlaps
  the picture's alpha best (intersection over union on a grid of ``GRID`` cells), starting from the box fit and a
  scale grid, then a pattern search;
* ``islands`` / ``alpha_parts`` split a paired piece (two gloves) into its parts when both the mesh and the
  picture fall apart into two parts side by side (a gap in x / a near-empty column): each part is registered on its
  own;
* ``sample_bilinear`` reads the picture bilinearly from the opaque, non-opening pixels around a point.

Coordinates: a view is an (h, w) array with row 0 at the BOTTOM (Blender pixels); a picture point is
``(u, v)`` in pixels with pixel ``(i, j)`` covering ``[j, j + 1) x [i, i + 1)`` — its centre is ``(j + 0.5, i + 0.5)``.
A map is ``(sx, ox, sz, oz)``: ``u = sx * x + ox``, ``v = sz * z + oz`` (x already mirrored for the back view).
"""
import numpy as np

#: Cells of the registration grid along the picture region's longer side.
GRID = 128
#: ``mesh_mask``: a triangle that needs a finer barycentric lattice than this is filled by its cell centres instead.
LATTICE_MAX = 16
#: The picture region of the search: the alpha box grown by this share of its size on every side.
REGION_PAD = 0.3
#: Scale factors tried against the box fit before the pattern search (per axis).
SCALES = (0.8, 0.9, 1.0, 1.12, 1.25)
#: A scale may leave the box fit by at most this factor (either way), an offset by at most this share of the box.
SCALE_LIMIT = 1.6
OFFSET_LIMIT = 0.35
#: Pattern search: the first steps (log scale, share of the alpha box) and the smallest ones.
STEP_LOG, STEP_OFF = 0.08, 0.06
MIN_STEP_LOG, MIN_STEP_OFF = 0.004, 0.003
#: A part of a paired piece (``islands`` / ``alpha_parts``) holds at least this share of the whole.
PART_MIN_SHARE = 0.2
#: ``islands``: the gap in x between the two parts, as a share of the piece's x extent.
PART_GAP = 0.05
#: ``alpha_parts``: the middle share of the alpha box searched for the cut, and the most the cut column may hold (as a
#: share of the fullest column).
PART_MIDDLE = 0.4
PART_VALLEY = 0.15


def mesh_mask(p2, tris, cell, origin, shape):
    """Bool grid ``shape`` (rows = z, cols = x) of the projected triangles ``p2[tris]``: cell (r, c) covers
    ``origin + (c, r) * cell .. + cell``. Each triangle is sampled on a barycentric lattice fine enough that no cell
    under it stays empty (step <= half a cell along its longest edge); one bigger than ``LATTICE_MAX`` steps fills the
    cells whose centre it holds."""
    p2 = np.asarray(p2, np.float64)
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    out = np.zeros(shape, bool)
    if not len(tris):
        return out
    a, b, c = p2[tris[:, 0]], p2[tris[:, 1]], p2[tris[:, 2]]
    edge = np.max([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1)], 0)
    k = np.ceil(2.0 * edge / cell).astype(int).clip(1)
    for t in np.nonzero(k > LATTICE_MAX)[0]:
        # a big triangle: the cells whose centre lies in it
        lo = np.floor((np.min([a[t], b[t], c[t]], 0) - origin) / cell).astype(int).clip(0)
        hi = np.minimum(np.ceil((np.max([a[t], b[t], c[t]], 0) - origin) / cell).astype(int), [shape[1], shape[0]])
        if (hi <= lo).any():
            continue
        cx = origin[0] + (np.arange(lo[0], hi[0]) + 0.5) * cell
        cz = origin[1] + (np.arange(lo[1], hi[1]) + 0.5) * cell
        X, Z = np.meshgrid(cx, cz)
        (x1, z1), (x2, z2), (x3, z3) = a[t], b[t], c[t]
        d = (z2 - z3) * (x1 - x3) + (x3 - x2) * (z1 - z3)
        if abs(d) < 1e-18:
            continue
        l1 = ((z2 - z3) * (X - x3) + (x3 - x2) * (Z - z3)) / d
        l2 = ((z3 - z1) * (X - x3) + (x1 - x3) * (Z - z3)) / d
        ins = (l1 >= -1e-9) & (l2 >= -1e-9) & (1 - l1 - l2 >= -1e-9)
        out[lo[1]:hi[1], lo[0]:hi[0]] |= ins
    k = np.where(k > LATTICE_MAX, 0, k)
    for n in np.unique(k[k > 0]):
        sel = k == n
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = i + j <= n
        l1, l2 = (i[keep] / n)[None, :, None], (j[keep] / n)[None, :, None]
        pts = l1 * a[sel][:, None] + l2 * b[sel][:, None] + (1 - l1 - l2) * c[sel][:, None]
        cc = np.floor((pts[..., 0] - origin[0]) / cell).astype(int).ravel()
        rr = np.floor((pts[..., 1] - origin[1]) / cell).astype(int).ravel()
        ok = (cc >= 0) & (cc < shape[1]) & (rr >= 0) & (rr < shape[0])
        out[rr[ok], cc[ok]] = True
    return out


def _box(mask):
    ys, xs = np.nonzero(mask)
    return xs.min(), xs.max() + 1, ys.min(), ys.max() + 1


def box_map(p2, alpha):
    """The bounding-box fit (the bake before this round): the box of the points ``p2`` onto the alpha box, per
    axis."""
    lo, hi = p2.min(0), p2.max(0)
    bx0, bx1, by0, by1 = _box(alpha)
    sx = (bx1 - bx0) / max(1e-9, hi[0] - lo[0])
    sz = (by1 - by0) / max(1e-9, hi[1] - lo[1])
    return (sx, bx0 - lo[0] * sx, sz, by0 - lo[1] * sz)


class _Problem:
    """One registration: the picture's alpha on the search grid and the piece's mask on its own grid."""

    def __init__(self, p2, tris, alpha):
        self.alpha = np.asarray(alpha, bool)
        bx0, bx1, by0, by1 = _box(self.alpha)
        self.bw, self.bh = float(bx1 - bx0), float(by1 - by0)
        pad = REGION_PAD * max(self.bw, self.bh)
        self.step = (max(self.bw, self.bh) + 2 * pad) / GRID
        ncol = int(np.ceil((self.bw + 2 * pad) / self.step))
        nrow = int(np.ceil((self.bh + 2 * pad) / self.step))
        self.u = bx0 - pad + (np.arange(ncol) + 0.5) * self.step
        self.v = by0 - pad + (np.arange(nrow) + 0.5) * self.step
        h, w = self.alpha.shape
        ju, iv = np.floor(self.u).astype(int), np.floor(self.v).astype(int)
        inside = (iv[:, None] >= 0) & (iv[:, None] < h) & (ju[None, :] >= 0) & (ju[None, :] < w)
        self.want = np.zeros((nrow, ncol), bool)
        self.want[inside] = self.alpha[np.clip(iv, 0, h - 1)[:, None].repeat(ncol, 1)[inside],
                                       np.clip(ju, 0, w - 1)[None, :].repeat(nrow, 0)[inside]]
        used = p2[np.unique(np.asarray(tris, np.int64))]
        self.lo, self.hi = used.min(0), used.max(0)
        ext = float(max(self.hi - self.lo))
        self.cell = ext / GRID
        self.origin = self.lo - self.cell
        self.shape = (int(np.ceil((self.hi[1] - self.lo[1]) / self.cell)) + 3,
                      int(np.ceil((self.hi[0] - self.lo[0]) / self.cell)) + 3)
        self.mask = mesh_mask(p2, tris, self.cell, self.origin, self.shape)

    def iou(self, m):
        sx, ox, sz, oz = m
        x = (self.u - ox) / sx
        z = (self.v - oz) / sz
        c = np.floor((x - self.origin[0]) / self.cell).astype(int)
        r = np.floor((z - self.origin[1]) / self.cell).astype(int)
        okc = (c >= 0) & (c < self.shape[1])
        okr = (r >= 0) & (r < self.shape[0])
        got = np.zeros(self.want.shape, bool)
        sub = self.mask[np.clip(r, 0, self.shape[0] - 1)][:, np.clip(c, 0, self.shape[1] - 1)]
        got[np.ix_(okr, okc)] = sub[np.ix_(okr, okc)]
        union = (got | self.want).sum()
        return float((got & self.want).sum() / union) if union else 0.0

    def centred(self, sx, sz):
        """The map of scales (sx, sz) that puts the piece's mask centroid onto the alpha centroid."""
        rr, cc = np.nonzero(self.mask)
        mx = self.origin[0] + (cc.mean() + 0.5) * self.cell
        mz = self.origin[1] + (rr.mean() + 0.5) * self.cell
        ys, xs = np.nonzero(self.alpha)
        return (sx, xs.mean() + 0.5 - sx * mx, sz, ys.mean() + 0.5 - sz * mz)


def register(p2, tris, alpha):
    """``(map, iou, box_iou)``: the map piece -> picture (module docstring) that maximises the silhouette IoU of the
    projected triangles ``p2[tris]`` against ``alpha`` (bool, row 0 = bottom), and the IoU of the box fit it started
    from. Scales stay within ``SCALE_LIMIT`` of the box fit, offsets within ``OFFSET_LIMIT`` of the alpha box."""
    p2 = np.asarray(p2, np.float64)
    pr = _Problem(p2, tris, alpha)
    box = box_map(p2[np.unique(np.asarray(tris, np.int64))], pr.alpha)
    box_iou = pr.iou(box)
    best, best_iou = box, box_iou
    for ks in SCALES:
        for kz in SCALES:
            m = pr.centred(box[0] * ks, box[2] * kz)
            i = pr.iou(m)
            if i > best_iou:
                best, best_iou = m, i
    # searched as (log sx, log sz, picture u, picture v of the piece's box centre): the centre is bounded by the
    # alpha box, whatever the scale
    cx, cz = (pr.lo + pr.hi) / 2
    lim_s = np.log(SCALE_LIMIT)
    ref = (np.log(box[0]), np.log(box[2]), box[0] * cx + box[1], box[2] * cz + box[3])

    def make(v):
        sx, sz = float(np.exp(v[0])), float(np.exp(v[1]))
        return (sx, float(v[2] - sx * cx), sz, float(v[3] - sz * cz))

    def allowed(v):
        return (abs(v[0] - ref[0]) <= lim_s and abs(v[1] - ref[1]) <= lim_s
                and abs(v[2] - ref[2]) <= OFFSET_LIMIT * pr.bw and abs(v[3] - ref[3]) <= OFFSET_LIMIT * pr.bh)
    cur = [np.log(best[0]), np.log(best[2]), best[0] * cx + best[1], best[2] * cz + best[3]]
    if not allowed(cur):
        cur, best_iou = list(ref), box_iou
    step = [STEP_LOG, STEP_LOG, STEP_OFF * pr.bw, STEP_OFF * pr.bh]
    floor = [MIN_STEP_LOG, MIN_STEP_LOG, MIN_STEP_OFF * pr.bw, MIN_STEP_OFF * pr.bh]
    for _ in range(400):
        moved = False
        for d in range(4):
            for sgn in (1, -1):
                v = list(cur)
                v[d] += sgn * step[d]
                if not allowed(v):
                    continue
                i = pr.iou(make(v))
                if i > best_iou + 1e-9:
                    cur, best_iou, moved = v, i, True
        if not moved:
            step = [s / 2 for s in step]
            if all(s < f for s, f in zip(step, floor)):
                break
    return make(cur), round(best_iou, 4), round(box_iou, 4)


def islands(tris, p2):
    """The two parts of a paired piece (two gloves): ``[faces of the left part, faces of the right part]`` (bool masks
    over ``tris``, left = smaller projected x) when the triangles' x spans leave a gap of at least ``PART_GAP`` of the
    piece's x extent and each side holds at least ``PART_MIN_SHARE`` of the faces; else None (the widest gap between
    the merged spans decides). By position, not by mesh connectivity: a UV seam or an overlay splits a glove into
    several connected pieces, two gloves never overlap in x."""
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    if len(tris) < 2:
        return None
    tx = np.asarray(p2, np.float64)[tris, 0]
    lo, hi = tx.min(1), tx.max(1)
    order = np.argsort(lo)
    reach = np.maximum.accumulate(hi[order])            # the right end of everything left of each span
    gaps = lo[order][1:] - reach[:-1]
    if not len(gaps):
        return None
    k = int(np.argmax(gaps))
    if gaps[k] < PART_GAP * (hi.max() - lo.min()):
        return None
    left = np.zeros(len(tris), bool)
    left[order[:k + 1]] = True
    if min(left.sum(), (~left).sum()) < PART_MIN_SHARE * len(tris):
        return None
    return [left, ~left]


def alpha_parts(alpha):
    """The two parts of a picture of a pair: ``[left alpha, right alpha]``, cut at the column between them — the
    column with the fewest opaque pixels in the middle ``PART_MIDDLE`` of the alpha box, when it holds at most
    ``PART_VALLEY`` of the fullest column (two gloves may touch at the thumbs) and each side holds at least
    ``PART_MIN_SHARE`` of the opaque pixels; else None."""
    alpha = np.asarray(alpha, bool)
    cols = alpha.sum(0).astype(np.float64)
    nz = np.nonzero(cols)[0]
    if len(nz) < 4:
        return None
    x0, x1 = nz[0], nz[-1] + 1
    a = x0 + int((x1 - x0) * (0.5 - PART_MIDDLE / 2))
    b = x0 + int(np.ceil((x1 - x0) * (0.5 + PART_MIDDLE / 2)))
    cut = a + int(np.argmin(cols[a:b]))
    if cols[cut] > PART_VALLEY * cols.max():
        return None
    left = np.zeros_like(alpha)
    left[:, :cut] = alpha[:, :cut]
    right = alpha & ~left
    right[:, cut] = False
    total = alpha.sum()
    if min(left.sum(), right.sum()) < PART_MIN_SHARE * total:
        return None
    return [left, right]


def sample_bilinear(rgb, usable, u, v):
    """``(colour (n, 3), valid (n,))`` of picture points ``(u, v)``: the bilinear blend of the four pixels round each
    point, over those that are ``usable`` (opaque and no opening) and renormalised; a point is valid when the pixel
    it lies in is usable (the coverage the nearest lookup had)."""
    h, w = usable.shape
    u = np.asarray(u, np.float64)
    v = np.asarray(v, np.float64)
    ju, iv = np.floor(u).astype(int), np.floor(v).astype(int)
    inb = (ju >= 0) & (ju < w) & (iv >= 0) & (iv < h)
    valid = inb & usable[np.clip(iv, 0, h - 1), np.clip(ju, 0, w - 1)]
    x, y = u - 0.5, v - 0.5
    j0, i0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - j0, y - i0
    col = np.zeros((len(u), 3))
    wsum = np.zeros(len(u))
    for di, dj, wt in ((0, 0, (1 - fx) * (1 - fy)), (0, 1, fx * (1 - fy)), (1, 0, (1 - fx) * fy), (1, 1, fx * fy)):
        ii, jj = i0 + di, j0 + dj
        ok = (ii >= 0) & (ii < h) & (jj >= 0) & (jj < w)
        ok &= usable[np.clip(ii, 0, h - 1), np.clip(jj, 0, w - 1)]
        wt = np.where(ok, wt, 0.0)
        col += wt[:, None] * rgb[np.clip(ii, 0, h - 1), np.clip(jj, 0, w - 1), :3]
        wsum += wt
    col = col / np.maximum(wsum, 1e-12)[:, None]
    near = rgb[np.clip(iv, 0, h - 1), np.clip(ju, 0, w - 1), :3]
    col = np.where((wsum > 1e-9)[:, None], col, near)
    return col, valid


def anisotropy(p3, p2px):
    """Area-weighted median, over triangles, of how unevenly the projection maps the surface onto the picture: per
    triangle the ratio of the larger to the smaller singular value of the map from its 3D plane to picture pixels
    (``p3`` (t, 3, 3) corners in metres, ``p2px`` (t, 3, 2) the same corners in pixels). 1 = no stretch. The caller
    passes the triangles that face the camera (a surface seen edge-on is stretched by any projection). None when no
    triangle is left."""
    p3 = np.asarray(p3, np.float64)
    p2px = np.asarray(p2px, np.float64)
    e1, e2 = p3[:, 1] - p3[:, 0], p3[:, 2] - p3[:, 0]
    n1 = np.linalg.norm(e1, axis=1)
    t1 = e1 / np.maximum(n1, 1e-12)[:, None]
    nrm = np.cross(e1, e2)
    area = np.linalg.norm(nrm, axis=1) / 2
    t2 = np.cross(nrm / np.maximum(2 * area, 1e-12)[:, None], t1)
    a = np.stack([np.einsum("ij,ij->i", e1, t1), np.einsum("ij,ij->i", e1, t2)], 1)   # (t, 2) local coords of e1
    b = np.stack([np.einsum("ij,ij->i", e2, t1), np.einsum("ij,ij->i", e2, t2)], 1)
    q1, q2 = p2px[:, 1] - p2px[:, 0], p2px[:, 2] - p2px[:, 0]
    L = np.stack([a, b], 2)                          # (t, 2, 2): columns = local edges
    Q = np.stack([q1, q2], 2)                        # (t, 2, 2): columns = picture edges
    det = L[:, 0, 0] * L[:, 1, 1] - L[:, 0, 1] * L[:, 1, 0]
    ok = (area > 1e-12) & (np.abs(det) > 1e-14)
    if not ok.any():
        return None
    Li = np.zeros_like(L)
    Li[:, 0, 0], Li[:, 1, 1] = L[:, 1, 1], L[:, 0, 0]
    Li[:, 0, 1], Li[:, 1, 0] = -L[:, 0, 1], -L[:, 1, 0]
    Li /= np.where(ok, det, 1.0)[:, None, None]
    J = Q @ Li
    s = np.linalg.svd(J[ok], compute_uv=False)
    keep = s[:, 1] > 1e-9
    ratio = s[keep, 0] / s[keep, 1]
    wts = area[ok][keep]
    if not len(ratio):
        return None
    order = np.argsort(ratio)
    cum = np.cumsum(wts[order])
    return float(ratio[order][min(len(ratio) - 1, int(np.searchsorted(cum, cum[-1] / 2)))])
