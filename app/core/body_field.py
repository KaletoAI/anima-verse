"""One body field per body: the filled solid of a body mesh, cached per body content on a lattice anchored to the
body, and the signed distance field of a crop taken from it (plan 2026-11-12 fit-sdf-speed-drape, Task 5).

``garment_fit.body_sdf`` is ``field(body_solid(P, F, vox=vox), bounds, ...)``; every fit (clothing, footwear,
HairDeck hair, layers, the limb source's trunk check) goes through it.

The solid (``body_solid``):
- Surface voxelisation at the 5 x 5 barycentric samples of every triangle (``garment_fit._surface_samples``) — a
  triangle with an edge longer than ``SAMPLE_STEPS`` voxels also at a grid of at most one voxel spacing
  (``_dense_samples``; a coarse body's fills used to leak through the sample gaps and read its inside as OUTSIDE) —,
  one dilation, hole fill (``fit_kernels.fill_holes``), the seal of cavities (``_seal_cavities``) and the 2-D hole fill
  of every slice along x, y AND z (``fit_kernels.fill_slices``; Task 1):
  - A hollow body is sealed: an outfit body meshed from its dressed views can be a SHELL — an outer and an inner
    wall, the inner one facing into a cavity — whose cavity is reached from outside through a slit or an opening of
    1 - 3 cm (Kira's outfit bodies 22354b972aef / 3b3a0adaf672 / 62aad0dac21c 2026-11-10: the trunk axis read as
    OUTSIDE, 4 - 7 cm from the "surface"). The hole fill then keeps only the wall, and a garment vertex placed
    under the skin is pushed AWAY from the inner wall, deeper into the body — the skin shows through the piece
    wherever that happened.
  - A limb meshed as a shell — an outer and an inner wall of either winding, open to the outside somewhere along
    the limb — escapes both the 3D fill and the seal (whose region must be ``2 · SDF_SEAL_THICK_VOX + 1`` voxels,
    7 cm, thick); its cross-section is a ring the 2D fill closes. A leg is vertical, so its y-slices are rings (the
    footwear shaft push, boots plan Task 9 fix 4: the clone's bases rebuilt 2026-11-12, Kira ``base20d5701a``, Kai
    ``base634402e5``, read the calf's cavity as OUTSIDE); a T-pose arm is a horizontal tube whose y-slice is a strip
    open at the cuff and towards the torso, so only its x-slices close it (the arm's core read as outside,
    -2..+11 mm along a line through Kai's upper arm). A gap between two shells opened by a hole elsewhere is closed
    by the slices that miss the hole. A concavity open along at least one direction in every slice through it (the
    gap between the legs) stays outside.
- It is decided on a grid over the WHOLE body (± 2 voxels), never on a crop alone: a fill on the crop leaks
  wherever the crop cuts the body (the cut cross-section is open), and the neck would read as outside.
- The grid lies on the body's lattice: its first cell is ``L = floor((P.min(0) - 2 vox) / vox) * vox``, a multiple
  of ``vox``. Every crop of the body snaps to it, so the field of a world point no longer depends on the crop's
  sub-voxel position (before, the grid started at the crop's ``lo``; a retry or a layer with other bounds saw
  another lattice).
- Cached per process, keyed by CONTENT: ``sha1(P bytes + F bytes + repr(vox))`` (float64 / int64), never by a path —
  a body GLB rewritten in place under the same path is another key. ``BODY_CACHE_SIZE`` solids, least recently used
  dropped first (a body at ``VOX_M`` holds about 80 MB). A cached solid is shared: never mutate it.

The field of a crop (``field``):
- The crop ``(lo, hi)`` snaps OUTWARD to the lattice; cells beyond the cached grid are outside.
- Each EDT is taken half a voxel back (it measures to the nearest voxel CENTRE of the other set), so the field is
  continuous across the boundary instead of jumping by two voxels within one cell. The EDT is the ``edt`` package
  (``edt.edtsq``, threaded): integer squared distances, exact in float32, and their float64 ``sqrt`` gives the same
  bits as ``scipy.ndimage.distance_transform_edt``.
- The zero level is put ON the surface: the dilation and the voxel rounding put it ``SDF_ZERO_OFFSET_VOX`` (1.3)
  voxels outside (measured on spheres of 10 to 75 voxels radius: 1.25..1.39, spread +- 0.15), so that much is
  added and a clearance means distance from the real surface. A median over the surface samples would be pulled
  inward by the inner wall of a double-walled body. ``zero_offset_vox=0`` keeps the raw level.
- Outside the body, within ``exact_band_vox`` voxels, the field is the EXACT distance to the surface (nearest of
  the triangles of the 8 nearest surface samples, ``pykdtree``; ``fit_kernels.band_distance``). The voxel EDT is up
  to 0.6 voxel short along diagonal directions, and the clearance is decided exactly in this band. Inside, the
  corrected EDT stays (it only sets how far the first push goes; the iterations converge outside). The nearest
  outside triangles are the outer wall, so a double wall does not disturb the band. Among equally near samples
  pykdtree may pick others than scipy's cKDTree did (up to 2 mm in single band cells, the profile).
- Inside distances near the crop faces may be overestimated (the nearest outside voxel can lie beyond the crop);
  the crop margin keeps that away from the garment.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from app.core import fit_kernels
from app.core.garment_fit import SDF_EXACT_BAND_VOX, SDF_SEAL_THICK_VOX, SDF_ZERO_OFFSET_VOX, Sdf, _surface_samples

#: Solids kept per process (a worker holds about 80 MB per body at ``garment_fit.VOX_M``).
BODY_CACHE_SIZE = 4
#: The 5 x 5 barycentric samples space a triangle edge in 4 steps: a triangle whose longest edge is longer than 4
#: voxels gets a denser grid (``_dense_samples``).
SAMPLE_STEPS = 4

_CACHE: "OrderedDict[str, BodySolid]" = OrderedDict()
_LOCK = threading.Lock()
_INFO = {"builds": 0, "hits": 0}


@dataclass
class BodySolid:
    """The filled solid of one body on its lattice: ``inside[i, j, k]`` is the cell at ``lo + (i, j, k) * vox``.
    ``P`` / ``F`` are the body (float64 / int64 copies), ``pts`` / ``tri_of`` its surface samples and the
    triangle of each."""
    key: str
    inside: np.ndarray
    lo: np.ndarray
    vox: float
    P: np.ndarray
    F: np.ndarray
    pts: np.ndarray
    tri_of: np.ndarray


def cache_info() -> Dict[str, int]:
    """``builds`` (solids built) and ``hits`` (calls served from the cache) since the process started."""
    with _LOCK:
        return dict(_INFO)


def clear_cache() -> None:
    """Drop every cached solid (the counters stay)."""
    with _LOCK:
        _CACHE.clear()


def body_solid(P, F, *, vox: float) -> BodySolid:
    """The body's solid, from the cache when the same body (same vertex and face bytes, same ``vox``) was built
    before in this process (module docstring)."""
    P = np.ascontiguousarray(P, np.float64)
    F = np.ascontiguousarray(np.asarray(F, np.int64).reshape(-1, 3))
    vox = float(vox)
    h = hashlib.sha1()
    h.update(P.tobytes())
    h.update(F.tobytes())
    h.update(repr(vox).encode())
    key = h.hexdigest()
    with _LOCK:
        solid = _CACHE.get(key)
        if solid is not None:
            _CACHE.move_to_end(key)
            _INFO["hits"] += 1
            return solid
    solid = _build(P.copy(), F.copy(), vox, key)
    with _LOCK:
        _INFO["builds"] += 1
        _CACHE[key] = solid
        _CACHE.move_to_end(key)
        while len(_CACHE) > max(1, int(BODY_CACHE_SIZE)):
            _CACHE.popitem(last=False)
    return solid


def _build(P: np.ndarray, F: np.ndarray, vox: float, key: str) -> BodySolid:
    from scipy import ndimage
    if len(F) == 0:
        raise ValueError("The body has no triangles")
    lo = np.floor((P.min(0) - 2 * vox) / vox) * vox
    shape = np.ceil(((P.max(0) + 2 * vox) - lo) / vox).astype(np.int64) + 1
    pts, tri_of = _dense_samples(P, F, vox)
    idx = np.clip(np.round((pts - lo) / vox).astype(np.int64), 0, shape - 1)
    surf = np.zeros(tuple(shape), bool)
    surf[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    surf = ndimage.binary_dilation(surf, iterations=1)
    inside = _seal_cavities(surf, fit_kernels.fill_holes(surf))
    for axis in range(3):
        # every slice of the grid along x, y and z filled in 2D as well (module docstring)
        inside |= fit_kernels.fill_slices(surf, axis)
    del surf
    for a in (inside, F, pts, tri_of):                         # shared by every crop; P stays writeable for numba
        a.flags.writeable = False
    return BodySolid(key=key, inside=inside, lo=lo, vox=vox, P=P, F=F, pts=pts, tri_of=tri_of)


def _dense_samples(P: np.ndarray, F: np.ndarray, vox: float) -> tuple:
    """``_surface_samples`` (5 x 5 per triangle) plus, for every triangle whose longest edge is longer than
    ``SAMPLE_STEPS`` voxels, a barycentric grid of ``n = ceil(longest edge / vox)`` steps per edge — sample spacing at
    most one voxel, so the dilated surface stays closed and the fills cannot leak (a 4 cm triangle edge at 3.4 mm left
    gaps of 10 mm). A body whose triangles are all finer gets exactly the 5 x 5 samples, in the same order."""
    pts, tri_of = _surface_samples(P, F)
    tri = P[F]
    longest = np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2).max(axis=1)
    steps = np.ceil(longest / vox).astype(np.int64)
    coarse = steps > SAMPLE_STEPS
    if not coarse.any():
        return pts, tri_of
    extra_pts, extra_tri = [pts], [tri_of]
    for n in np.unique(steps[coarse]):
        which = np.flatnonzero(coarse & (steps == n))
        uv = np.array([(i / n, j / n) for i in range(n + 1) for j in range(n + 1 - i)])
        t = tri[which]                                                       # (k, 3, 3)
        grid = (t[:, None, 0] * (1 - uv[:, 0] - uv[:, 1])[None, :, None] + t[:, None, 1] * uv[None, :, 0, None]
                + t[:, None, 2] * uv[None, :, 1, None])                      # (k, m, 3)
        extra_pts.append(grid.reshape(-1, 3))
        extra_tri.append(np.repeat(which, len(uv)))
    return np.concatenate(extra_pts), np.concatenate(extra_tri)


def field(solid: BodySolid, bounds, *, zero_offset_vox: Optional[float] = None,
          exact_band_vox: float = SDF_EXACT_BAND_VOX) -> Sdf:
    """Signed distance field (metres, negative inside) of ``solid`` on the crop ``bounds = (lo, hi)`` snapped
    outward to the body's lattice (module docstring)."""
    lo, hi = (np.asarray(b, np.float64) for b in bounds)
    vox = solid.vox
    if (np.ceil((hi - lo) / vox) + 1 < 3).any():
        raise ValueError("SDF bounds are too small")
    first = np.floor((lo - solid.lo) / vox).astype(np.int64)
    last = np.ceil((hi - solid.lo) / vox).astype(np.int64)
    shape = last - first + 1
    inside = np.zeros(tuple(shape), bool)
    a = np.maximum(first, 0)
    b = np.minimum(last, np.array(solid.inside.shape) - 1)
    if (a <= b).all():
        inside[tuple(slice(int(x - f), int(y - f + 1)) for x, y, f in zip(a, b, first))] = \
            solid.inside[tuple(slice(int(x), int(y + 1)) for x, y in zip(a, b))]
    offset = SDF_ZERO_OFFSET_VOX if zero_offset_vox is None else zero_offset_vox
    # each EDT measures to the nearest voxel CENTRE of the other set; half a voxel off each side makes the field
    # continuous with slope ~1 across the boundary (the plain difference jumps by 2 voxels within one cell)
    out = np.where(inside, 0.5 - _edt(inside), _edt(~inside) - 0.5)
    out = (out + offset) * vox
    if exact_band_vox > 0:
        _exact_outside_band(out, solid, first, exact_band_vox)
    return Sdf(field=out, lo=solid.lo + first * vox, vox=vox)


def _edt(mask: np.ndarray) -> np.ndarray:
    """Distance (voxels, float64) of every ``True`` cell to the nearest ``False`` cell of the crop — the bits of
    ``ndimage.distance_transform_edt``. A crop with no ``False`` cell reads as far as the crop is long: the body is
    all inside it (or all outside, for the outside EDT) and no cell of it has a nearer counterpart."""
    import edt
    if mask.all():
        return np.full(mask.shape, float(sum(mask.shape)))
    sq = edt.edtsq(np.ascontiguousarray(mask), black_border=False, parallel=fit_kernels.threads())
    return np.sqrt(sq.astype(np.float64))


def _seal_cavities(surf: np.ndarray, inside: np.ndarray, thick_vox: int = SDF_SEAL_THICK_VOX) -> np.ndarray:
    """``inside`` plus the cavities the hole fill left open (module docstring): voxels that are not inside but have
    a surface voxel before AND after them along each of the three axes (enclosed by the body in all six directions —
    an opening of a few centimetres only leaves the voxels in line with it), kept where they belong to a region at
    least ``2 * thick_vox + 1`` voxels thick (eroded by ``thick_vox``, grown back within the candidates). Kira's
    base bodies, the bodies whose fill holds and every unrigged body but one: nothing added."""
    from scipy import ndimage
    enclosed = ~inside
    for axis in range(3):
        before = np.cumsum(surf, axis=axis, dtype=np.int16)
        total = np.take(before, [-1], axis=axis)
        enclosed &= (before - surf) > 0
        enclosed &= (total - before) > 0
        del before
    core = ndimage.binary_erosion(enclosed, iterations=thick_vox)
    if not core.any():
        return inside
    return inside | ndimage.binary_dilation(core, iterations=thick_vox + 1, mask=enclosed)


def _exact_outside_band(out: np.ndarray, solid: BodySolid, first: np.ndarray, band_vox: float, k: int = 8) -> None:
    """Replace the outside band ``0 < out <= band_vox`` voxels by the exact distance to the nearest of the
    triangles of their ``k`` nearest surface samples (in place; ``fit_kernels.band_distance``). A cell's point is
    ``L + (first + cell) * vox`` — counted on the body lattice, so the same cell of two crops is the same point."""
    from pykdtree.kdtree import KDTree
    vox = solid.vox
    band = (out > 0) & (out <= band_vox * vox)
    cells = np.argwhere(band)
    if len(cells) == 0:
        return
    X = solid.lo + (cells + first) * vox
    reach = (band_vox + 2) * vox
    pts = solid.pts
    near = ((pts >= X.min(0) - reach) & (pts <= X.max(0) + reach)).all(1)
    n_near = int(near.sum())
    if n_near == 0:
        return
    _, nn = KDTree(np.ascontiguousarray(pts[near])).query(np.ascontiguousarray(X), k=min(k, n_near))
    nn = np.asarray(nn, np.int64).reshape(len(X), -1)
    tris = solid.F[solid.tri_of[near][nn]]                      # (n, k, 3)
    out[tuple(cells.T)] = fit_kernels.band_distance(X, solid.P, np.ascontiguousarray(tris))
