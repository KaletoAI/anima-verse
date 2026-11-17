"""Body faces hidden under own-mesh clothing (Ruling A133; the rule is A192's).

The assembled figure (``garment_assembly._build``) grafts each own-mesh clothing piece over the body. In a bent
pose (sit, kneel) the body can poke through the piece near a crease. The body skin under a piece is never seen, so
the assembly drops the body faces a piece fully covers from the DELIVERED body — the bare file stays whole, so the
step is reversible: another worn set builds another assembly from the same bare file.

Rule (A192 — "covered" means it cannot be SEEN, not "a piece vertex is near"). The pieces are voxelised
(``VOXEL_M``, one voxel thick either way, so a crack of a generated mesh is closed); per body vertex ``v`` (bind
pose, normal ``n_v``) ``len(CONE)`` rays leave in a cone of ``CONE_DEG`` round ``n_v``, each from ``INSIDE_TOL_M``
behind the vertex (a piece lying that far under the skin still covers it) to ``RAY_REACH_M`` in front:

* covered — EVERY ray meets a piece. A ray that leaves through a neckline, a cuff, an open front or under a hem
  keeps the vertex, whether the piece has a border edge there or is a closed thick shell (a generated jacket has
  no border edge at its collar or cuffs: the old nearest-vertex rule hid the chest, the neck and the wrists there,
  and the holes showed through the opening).
* kept anyway — within ``SEEN_BAND_M`` of an EXPOSED body vertex (not covered, and one of its rays runs
  ``FREE_REACH_M`` without meeting a piece or the body itself, taken as a solid: a base body is a hollow, partly
  doubled shell, and a vertex of its inner wall looks along the inside of the trunk for more than that), and within ``HEM_BAND_M`` of a piece's open border (a boundary edge): the band a moving hem or
  collar uncovers in a pose stays skin.

A body face is dropped only when all three of its vertices are covered.

Garment under garment (Ruling A144, ``covered_under``): a piece worn under another loses the faces the upper piece
covers, by the same rays with the outward direction taken from the body (the nearest body vertex to the point: a
cloth shell's own normals point both ways); the band at what stays visible of it stays (the top shows in a
jacket's V and at its cuffs). Footwear has its own cut, hair and painted pieces never hide anything. Numpy +
pykdtree + scipy on the CPU, no hub job. ``VERSION`` enters the assembly state, so a changed rule makes every
assembly due once.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

VERSION = 3
#: A body vertex further than this from every piece vertex is never tested (nothing covers it).
REACH_M = 0.12
#: A piece lying up to this far UNDER the skin still covers it (the skin poking through a tight piece).
INSIDE_TOL_M = 0.02
HEM_BAND_M = 0.02
#: The band kept round every exposed body vertex.
SEEN_BAND_M = 0.02
#: Edge of the occupancy voxels; a piece is one voxel thick either way (cracks under ~8 mm are closed).
VOXEL_M = 0.004
#: How far a covering ray looks for a piece: a piece further off (a wide skirt over the legs) covers nothing.
RAY_REACH_M = 0.12
#: How far an exposing ray must run free of every piece and of the body.
FREE_REACH_M = 0.5
#: An exposing ray ignores the body this close to its own start (the surface it leaves).
FREE_SKIP_M = 0.02
CONE_DEG = 65.0


def _cone(half_deg: float = CONE_DEG) -> np.ndarray:
    """Unit directions in the local frame (z = the normal): the normal, 6 at half the cone angle, 10 on its rim."""
    out = [(0.0, 0.0, 1.0)]
    for deg, count, phase in ((half_deg / 2.0, 6, 0.0), (half_deg, 10, 0.5)):
        t = np.radians(deg)
        for i in range(count):
            p = 2.0 * np.pi * (i + phase) / count
            out.append((np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)))
    return np.asarray(out, np.float64)


CONE = _cone()


def surface_points(positions: np.ndarray, faces: np.ndarray, spacing: float) -> np.ndarray:
    """Points on the triangles no further apart than ``spacing``: per triangle a barycentric lattice of
    ``n = ceil(longest edge / spacing)`` steps (at most 256) — its corners for a triangle under ``spacing``."""
    tri = np.asarray(positions, np.float64)[np.asarray(faces, np.int64).reshape(-1, 3)]
    if not len(tri):
        return np.zeros((0, 3))
    edge = np.linalg.norm(tri - np.roll(tri, -1, axis=1), axis=2).max(axis=1)
    steps = np.clip(np.ceil(edge / spacing), 1, 256).astype(np.int64)
    out = []
    for n in np.unique(steps):
        t = tri[steps == n]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = i + j <= n
        w = np.stack([i[keep], j[keep], n - i[keep] - j[keep]], axis=1) / float(n)
        out.append(np.einsum("lk,tkj->tlj", w, t).reshape(-1, 3))
    return np.concatenate(out)


class Occupancy:
    """A boolean voxel grid of surfaces: ``hit(X)`` = the point lies in an occupied voxel."""

    def __init__(self, meshes: Sequence[Tuple[np.ndarray, np.ndarray]], *, voxel: float = VOXEL_M, thicken: int = 1):
        pts = [surface_points(p, f, voxel) for p, f in meshes]
        pts = [p for p in pts if len(p)]
        self.voxel = float(voxel)
        if not pts:
            self.origin = np.zeros(3)
            self.grid = np.zeros((1, 1, 1), bool)
            return
        P = np.concatenate(pts)
        pad = thicken + 1
        self.origin = P.min(axis=0) - pad * self.voxel
        shape = np.ceil((P.max(axis=0) - self.origin) / self.voxel).astype(np.int64) + pad + 1
        grid = np.zeros(tuple(int(v) for v in shape), bool)
        ijk = np.floor((P - self.origin) / self.voxel).astype(np.int64)
        grid[ijk[:, 0], ijk[:, 1], ijk[:, 2]] = True
        if thicken:
            from scipy import ndimage
            grid = ndimage.binary_dilation(grid, structure=np.ones((3, 3, 3), bool), iterations=int(thicken))
        self.grid = grid

    def fill(self) -> "Occupancy":
        """The same grid with every enclosed cavity filled (the body as a solid: its hollow inside is not outside)."""
        from scipy import ndimage
        self.grid = ndimage.binary_fill_holes(self.grid)
        return self

    def hit(self, X: np.ndarray) -> np.ndarray:
        ijk = np.floor((np.asarray(X, np.float64) - self.origin) / self.voxel).astype(np.int64)
        shape = np.asarray(self.grid.shape)
        inside = ((ijk >= 0) & (ijk < shape)).all(axis=1)
        out = np.zeros(len(ijk), bool)
        j = ijk[inside]
        out[inside] = self.grid[j[:, 0], j[:, 1], j[:, 2]]
        return out


def _frames(normals: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    n = np.asarray(normals, np.float64)
    helper = np.where(np.abs(n[:, [0]]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]]))
    t = np.cross(n, helper)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    return t, np.cross(n, t)


def _directions(normals: np.ndarray) -> np.ndarray:
    """(n, len(CONE), 3): the cone directions round each normal."""
    t, b = _frames(normals)
    n = np.asarray(normals, np.float64)
    return CONE[None, :, [0]] * t[:, None, :] + CONE[None, :, [1]] * b[:, None, :] + CONE[None, :, [2]] * n[:, None, :]


def rays_blocked(points: np.ndarray, normals: np.ndarray, occ: Occupancy, *, start: float = -INSIDE_TOL_M,
                 reach: float = RAY_REACH_M) -> np.ndarray:
    """(n, len(CONE)) bool: the ray from ``point + start * d`` to ``point + reach * d`` meets ``occ``."""
    P = np.asarray(points, np.float64)
    D = _directions(normals)
    hit = np.zeros(D.shape[:2], bool)
    rows, cols = np.nonzero(~hit)
    for t in np.arange(start, reach + occ.voxel / 2, occ.voxel):
        if not len(rows):
            break
        h = occ.hit(P[rows] + t * D[rows, cols])
        hit[rows[h], cols[h]] = True
        rows, cols = rows[~h], cols[~h]
    return hit


def rays_free(points: np.ndarray, normals: np.ndarray, pieces: Occupancy, body: Optional[Occupancy], *,
              reach: float = FREE_REACH_M) -> np.ndarray:
    """(n,) bool: one cone ray runs ``reach`` without meeting a piece (from ``-INSIDE_TOL_M``) or the body (from
    ``FREE_SKIP_M`` on)."""
    P = np.asarray(points, np.float64)
    D = _directions(normals)
    alive = np.ones(D.shape[:2], bool)
    rows, cols = np.nonzero(alive)
    step = pieces.voxel
    for t in np.arange(-INSIDE_TOL_M, reach + step / 2, step):
        if not len(rows):
            break
        X = P[rows] + t * D[rows, cols]
        h = pieces.hit(X)
        if body is not None and t >= FREE_SKIP_M:
            h |= body.hit(X)
        alive[rows[h], cols[h]] = False
        rows, cols = rows[~h], cols[~h]
    return alive.any(axis=1)


def vertex_normals(positions: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Area-weighted unit vertex normals (a vertex on no face gets zero)."""
    P = np.asarray(positions, np.float64)
    F = np.asarray(faces, np.int64)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n = np.zeros_like(P)
    for k in range(3):
        np.add.at(n, F[:, k], fn)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, length, out=np.zeros_like(n), where=length > 0)


def weld(positions: np.ndarray, faces: np.ndarray, *, grid_m: float = 1e-4) -> np.ndarray:
    """``faces`` re-indexed onto one vertex per position (``grid_m`` grid): UV and normal seams split a vertex in
    the file, and a split edge would read as an open border."""
    key = np.round(np.asarray(positions, np.float64) / grid_m).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return first[inverse.reshape(-1)][np.asarray(faces, np.int64)]


def boundary_vertices(faces: np.ndarray) -> np.ndarray:
    """Indices of the vertices on an edge used by exactly one face (the open borders); pass welded faces."""
    F = np.asarray(faces, np.int64)
    edges = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    return np.unique(uniq[counts == 1])


def _rims(pieces: Sequence[Tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    rim = [np.asarray(pos, np.float64)[boundary_vertices(weld(pos, faces))] for pos, faces in pieces]
    return np.concatenate(rim) if rim else np.zeros((0, 3))


def _keep_bands(points: np.ndarray, covered: np.ndarray, exposed: np.ndarray, rim: np.ndarray,
                stats: Dict[str, Any]) -> None:
    """Uncover (in place) the covered points within ``SEEN_BAND_M`` of an exposed one and within ``HEM_BAND_M`` of
    a border vertex."""
    from pykdtree.kdtree import KDTree
    for key, seeds, band in (("seen_kept", points[exposed], SEEN_BAND_M), ("hem_kept", rim, HEM_BAND_M)):
        stats[key] = 0
        cand = np.flatnonzero(covered)
        if not len(seeds) or not len(cand):
            continue
        d, _ = KDTree(np.ascontiguousarray(seeds)).query(np.ascontiguousarray(points[cand]), k=1)
        keep = cand[d < band]
        covered[keep] = False
        stats[key] = int(len(keep))


def covered_vertices(body_pos: np.ndarray, body_faces: np.ndarray,
                     pieces: Sequence[Tuple[np.ndarray, np.ndarray]]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """(bool mask over the body vertices, stats) — see the module rule. ``pieces`` = (positions, faces) of each
    clothing piece in the body's space."""
    from pykdtree.kdtree import KDTree
    B = np.ascontiguousarray(np.asarray(body_pos, np.float64))
    covered = np.zeros(len(B), bool)
    stats: Dict[str, Any] = {"pieces": len(pieces), "near": 0, "hem_kept": 0, "seen_kept": 0, "covered": 0}
    pieces = [(np.asarray(p, np.float64), np.asarray(f, np.int64).reshape(-1, 3)) for p, f in pieces if len(p)]
    if not pieces or not len(B):
        return covered, stats
    nb = vertex_normals(B, body_faces)
    G = np.ascontiguousarray(np.concatenate([p for p, _f in pieces]))
    dist, _ = KDTree(G).query(B, k=1, distance_upper_bound=REACH_M)
    near = np.flatnonzero(np.isfinite(dist) & (np.linalg.norm(nb, axis=1) > 0))
    stats["near"] = int(len(near))
    if not len(near):
        return covered, stats
    occ = Occupancy(pieces)
    covered[near] = rays_blocked(B[near], nb[near], occ).all(axis=1)
    # Exposed: the uncovered vertices next to a covered one that can really be seen (not the body's inner wall).
    exposed = np.zeros(len(B), bool)
    cand = np.flatnonzero(~covered & (np.linalg.norm(nb, axis=1) > 0))
    if covered.any() and len(cand):
        d, _ = KDTree(np.ascontiguousarray(B[covered])).query(np.ascontiguousarray(B[cand]), k=1,
                                                              distance_upper_bound=SEEN_BAND_M)
        cand = cand[np.isfinite(d)]
        if len(cand):
            body_occ = Occupancy([(B, np.asarray(body_faces, np.int64).reshape(-1, 3))]).fill()
            exposed[cand] = rays_free(B[cand], nb[cand], occ, body_occ)
    _keep_bands(B, covered, exposed, _rims(pieces), stats)
    stats["covered"] = int(covered.sum())
    return covered, stats


def covered_under(lower_pos: np.ndarray, body_pos: np.ndarray,
                  pieces: Sequence[Tuple[np.ndarray, np.ndarray]]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """(bool mask over the lower piece's vertices, stats): covered by the upper ``pieces`` — see the module rule."""
    from pykdtree.kdtree import KDTree
    L = np.ascontiguousarray(np.asarray(lower_pos, np.float64))
    covered = np.zeros(len(L), bool)
    stats: Dict[str, Any] = {"pieces": len(pieces), "hem_kept": 0, "seen_kept": 0, "covered": 0}
    pieces = [(np.asarray(p, np.float64), np.asarray(f, np.int64).reshape(-1, 3)) for p, f in pieces if len(p)]
    if not pieces or not len(L) or not len(body_pos):
        return covered, stats
    B = np.ascontiguousarray(np.asarray(body_pos, np.float64))
    _d, bi = KDTree(B).query(L, k=1)
    out = L - B[bi]
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    n = np.divide(out, ln, out=np.zeros_like(out), where=ln > 1e-9)
    G = np.ascontiguousarray(np.concatenate([p for p, _f in pieces]))
    dist, _ = KDTree(G).query(L, k=1, distance_upper_bound=REACH_M)
    near = np.flatnonzero(np.isfinite(dist) & (ln[:, 0] > 1e-9))
    if not len(near):
        return covered, stats
    occ = Occupancy(pieces)
    # from the point itself: an upper piece UNDER the lower one covers nothing of it
    covered[near] = rays_blocked(L[near], n[near], occ, start=0.0).all(axis=1)
    # Exposed: a ray really leaves past the upper pieces (not merely further than ``RAY_REACH_M`` to the next wall)
    exposed = np.zeros(len(L), bool)
    cand = near[~covered[near]]
    if len(cand) and covered.any():
        exposed[cand] = rays_free(L[cand], n[cand], occ, None)
    _keep_bands(L, covered, exposed, _rims(pieces), stats)
    stats["covered"] = int(covered.sum())
    return covered, stats


def hidden_faces(faces: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """Bool mask over ``faces``: all three vertices covered."""
    F = np.asarray(faces, np.int64)
    return covered[F].all(axis=1) if len(F) else np.zeros(0, bool)


def hide_under(prims: Sequence[Any], pieces: Sequence[Tuple[np.ndarray, np.ndarray]]
               ) -> Tuple[Dict[int, Any], Dict[str, Any]]:
    """The body primitives (``glb_mesh.Prim``) with the covered faces dropped — only the changed ones, keyed by
    primitive index for ``glb_mesh.rewrite_body_primitives`` — and stats ``{hidden_faces, faces, covered, ...}``.
    Vertices stay (the vertex arrays are untouched, only the index list shrinks)."""
    from dataclasses import replace
    sizes = [len(p.positions) for p in prims]
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
    B = np.concatenate([p.positions for p in prims]) if prims else np.zeros((0, 3))
    F = np.concatenate([np.asarray(p.faces, np.int64) + offs[i] for i, p in enumerate(prims)]) if prims \
        else np.zeros((0, 3), np.int64)
    covered, stats = covered_vertices(B, F, pieces)
    out: Dict[int, Any] = {}
    total = 0
    for i, p in enumerate(prims):
        cov = covered[offs[i]:offs[i + 1]]
        drop = hidden_faces(p.faces, cov)
        if drop.any():
            out[i] = replace(p, faces=np.asarray(p.faces)[~drop])
            total += int(drop.sum())
    stats.update({"version": VERSION, "hidden_faces": total, "faces": int(len(F))})
    return out, stats
