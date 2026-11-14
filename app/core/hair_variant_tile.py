"""The tile of one HAAR variant (strand-hair spec 2026-11-13 § 6.3.4): a small CPU picture of the fitted hair cards
on the grey bald head, front and back side by side, for the Hairstyles tab's "HAAR variants" sub-tab.

An orthographic numpy z-buffer: no GPU, no Blender, no file read. The hair (cards and scalp layer) is flat-shaded
in its vertex colour (linear RGB, written as sRGB), the body in ``BODY_GREY``; a face's brightness is
``SHADE_FLOOR + (1 - SHADE_FLOOR) * |n . view|`` (its unit normal against the viewing axis), so the hair's layers read
as layers and the head as a head. The background is transparent.

The frame is the head box: the body points within ``HEAD_DEPTH_M`` of the body's top (the head; the shoulders of a
standing body are lower), their x/y bounding-box centre ``(cx, cy)``, framed ``FRAME_HALF_M`` round it — x and y
``[c - 0.25, c + 0.25]`` m. A ``size`` x ``size`` view: pixel (row r, column c) samples the centre
``x = cx - 0.25 + (c + 0.5) * 0.5 / size``, ``y = cy + 0.25 - (r + 0.5) * 0.5 / size``. Front (left half): seen from
+z, the nearest point has the largest z. Back (right half): seen from -z, x mirrored (column c samples
``x = cx + 0.25 - (c + 0.5) * 0.5 / size``), the nearest point has the smallest z.
"""
from __future__ import annotations

import io
from typing import Tuple

import numpy as np

#: The head box (module docstring): the body points within this of the top, framed this far round their centre.
HEAD_DEPTH_M = 0.22
FRAME_HALF_M = 0.25
#: The body's flat colour (linear) and the floor of the face shading.
BODY_GREY = 0.42
SHADE_FLOOR = 0.35
#: How many candidate pixels one rasterisation batch tests at most (memory, not output).
_BATCH_CANDIDATES = 2_000_000


def head_centre(body_P: np.ndarray) -> Tuple[float, float]:
    """``(cx, cy)``: the x/y bounding-box centre of the body points within ``HEAD_DEPTH_M`` of the top."""
    P = np.asarray(body_P, np.float64).reshape(-1, 3)
    if not len(P):
        raise ValueError("hair_variant_tile: an empty body")
    top = float(P[:, 1].max())
    head = P[P[:, 1] >= top - HEAD_DEPTH_M]
    return (float(head[:, 0].min() + head[:, 0].max()) / 2, float(head[:, 1].min() + head[:, 1].max()) / 2)


def _lin2srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _view(P: np.ndarray, T: np.ndarray, rgb: np.ndarray, centre: Tuple[float, float], size: int,
          back: bool) -> np.ndarray:
    """One orthographic view (``size`` x ``size`` RGBA uint8) of triangles ``T`` (M, 3) over points ``P`` with the
    face colours ``rgb`` (M, 3, linear, shading applied here)."""
    cx, cy = centre
    scale = size / (2 * FRAME_HALF_M)
    u = ((cx + FRAME_HALF_M - P[:, 0]) if back else (P[:, 0] - (cx - FRAME_HALF_M))) * scale
    v = (cy + FRAME_HALF_M - P[:, 1]) * scale
    depth = P[:, 2] if back else -P[:, 2]
    U, Vv, D = u[T], v[T], depth[T]                                   # (M, 3) each
    # pixel centres inside each triangle's box: column c covers u in [c, c + 1), its centre at c + 0.5
    c0 = np.clip(np.ceil(U.min(1) - 0.5), 0, size).astype(np.int64)
    c1 = np.clip(np.floor(U.max(1) - 0.5), -1, size - 1).astype(np.int64)
    r0 = np.clip(np.ceil(Vv.min(1) - 0.5), 0, size).astype(np.int64)
    r1 = np.clip(np.floor(Vv.max(1) - 0.5), -1, size - 1).astype(np.int64)
    area = (U[:, 1] - U[:, 0]) * (Vv[:, 2] - Vv[:, 0]) - (U[:, 2] - U[:, 0]) * (Vv[:, 1] - Vv[:, 0])
    live = (c1 >= c0) & (r1 >= r0) & (np.abs(area) > 1e-12)
    idx = np.flatnonzero(live)
    w = (c1 - c0 + 1)[idx]
    h = (r1 - r0 + 1)[idx]
    side = np.maximum(w, h)
    pix_all, dep_all, tri_all = [], [], []
    # bucket by the box side (powers of two), so a big body triangle never inflates the small cards' grids
    bucket = np.ceil(np.log2(np.maximum(side, 1))).astype(np.int64)
    for b in np.unique(bucket):
        sel = idx[bucket == b]
        B = int(2 ** b)
        oy, ox = np.divmod(np.arange(B * B), B)
        step = max(1, _BATCH_CANDIDATES // (B * B))
        for s in range(0, len(sel), step):
            t = sel[s:s + step]
            cc = c0[t][:, None] + ox[None, :]
            rr = r0[t][:, None] + oy[None, :]
            ok = (cc <= c1[t][:, None]) & (rr <= r1[t][:, None])
            px, py = cc + 0.5, rr + 0.5
            ut, vt = U[t], Vv[t]
            # edge functions; inside when all three share the triangle's orientation
            e0 = (ut[:, 1, None] - ut[:, 0, None]) * (py - vt[:, 0, None]) - (vt[:, 1, None] - vt[:, 0, None]) * (px - ut[:, 0, None])
            e1 = (ut[:, 2, None] - ut[:, 1, None]) * (py - vt[:, 1, None]) - (vt[:, 2, None] - vt[:, 1, None]) * (px - ut[:, 1, None])
            e2 = (ut[:, 0, None] - ut[:, 2, None]) * (py - vt[:, 2, None]) - (vt[:, 0, None] - vt[:, 2, None]) * (px - ut[:, 2, None])
            sgn = np.sign(area[t])[:, None]
            ok &= (e0 * sgn >= 0) & (e1 * sgn >= 0) & (e2 * sgn >= 0)
            a = area[t][:, None]
            # barycentric weights: e1 / area belongs to vertex 0, e2 to vertex 1, e0 to vertex 2
            d = (e1 * D[t][:, 0, None] + e2 * D[t][:, 1, None] + e0 * D[t][:, 2, None]) / a
            hit = np.nonzero(ok)
            pix_all.append(rr[hit] * size + cc[hit])
            dep_all.append(d[hit])
            tri_all.append(t[hit[0]])
    out = np.zeros((size * size, 4), np.uint8)
    if not pix_all or not sum(len(p) for p in pix_all):
        return out.reshape(size, size, 4)
    pix = np.concatenate(pix_all)
    dep = np.concatenate(dep_all)
    tri = np.concatenate(tri_all)
    order = np.lexsort((dep, pix))
    pix, tri = pix[order], tri[order]
    first = np.r_[True, pix[1:] != pix[:-1]]
    pix, tri = pix[first], tri[first]
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    nz = np.abs(n[:, 2]) / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    shade = SHADE_FLOOR + (1 - SHADE_FLOOR) * nz
    lit = _lin2srgb(rgb[tri] * shade[tri, None])
    out[pix, :3] = np.round(lit * 255).astype(np.uint8)
    out[pix, 3] = 255
    return out.reshape(size, size, 4)


def tile_png(V: np.ndarray, F: np.ndarray, colours: np.ndarray, body_P: np.ndarray, body_F: np.ndarray, *,
             size: int = 256) -> bytes:
    """The PNG (``2 size`` x ``size``, RGBA) of the hair ``V`` / ``F`` (triangles) with the vertex ``colours``
    (linear RGB(A), 0..1) on the body ``body_P`` / ``body_F``: the front left, the back right (module docstring)."""
    from PIL import Image
    V = np.asarray(V, np.float64).reshape(-1, 3)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    C = np.asarray(colours, np.float64).reshape(len(V), -1)[:, :3]
    BP = np.asarray(body_P, np.float64).reshape(-1, 3)
    BF = np.asarray(body_F, np.int64).reshape(-1, 3)
    centre = head_centre(BP)
    P = np.vstack([V, BP])
    T = np.vstack([F, BF + len(V)])
    rgb = np.vstack([C[F].mean(1), np.full((len(BF), 3), BODY_GREY)])
    img = np.concatenate([_view(P, T, rgb, centre, int(size), back=False),
                          _view(P, T, rgb, centre, int(size), back=True)], axis=1)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


__all__ = ["HEAD_DEPTH_M", "FRAME_HALF_M", "BODY_GREY", "SHADE_FLOOR", "head_centre", "tile_png"]
