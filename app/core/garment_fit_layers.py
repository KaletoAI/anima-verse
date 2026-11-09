"""Garment layering math — an own-mesh piece worn OVER other fitted pieces (plan
``docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md``, Task 2).

A piece is fitted against the body alone (``garment_fit.fit_clothing``: clearance ``CLEAR_M`` from the body
surface). Worn over other own-mesh pieces it is LAYERED afterwards, in the rigged bind space where every fit lives
(metres, the T-pose of the rigged base): each vertex of the outer piece must stand at least ``LAYER_CLEAR_M``
(the body clearance) further from the body than the inner pieces stand at the same place on the body.

"The same place": every inner vertex (and triangle centroid) is projected onto the body along the body's signed
distance field — its FOOT — and keeps its height ``h`` above the body. An outer vertex at height ``d`` with foot
``f`` reads the largest ``h`` of the inner feet within ``LAYER_REACH_M`` of ``f``; it needs ``max(h + clear - d,
0)`` more, pushed along the body's gradient (outward, never through the inner shell sideways). That is
``push_out`` of the body fit with a field ``d - h`` instead of ``d``: the same iterations, the same displacement
smoothing over the (welded) mesh, the last iterations exact. Where no inner foot is within reach the field reads
far outside — the outer piece keeps its body fit there.

An inner shell is open (a dress has a hem and a neckline), so it is never voxelised as a solid: a foot/height
field has no inside to leak and pushes only outward from the body. The result keeps the outer piece's UVs,
joints, weights, image and material — only positions and normals change — so a layered fit is derived from the
accepted body fit without the generator, the images or the fit step (no hub job).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Sequence, Tuple

import numpy as np

from app.core.garment_fit import (CLEAR_M, MOVED_EPS_M, SDF_MARGIN_M, VOX_M, body_sdf, push_out, vertex_normals,
                                  weld)
from app.core.glb_mesh import BodyMesh, GarmentMesh

#: The clearance of an outer piece over an inner one — the body clearance (plan: "clearance like the body
#: clearance"): two layers sit as far apart as the first one sits from the skin.
LAYER_CLEAR_M = CLEAR_M
#: How far (on the body surface) an inner piece lifts an outer one: two to three edges of a decimated garment
#: (measured on the e2e dress: 46k vertices, ~5 mm spacing), so the rim of an inner piece (a hem, a neckline) still
#: lifts the outer vertices just beyond it. The need did not change between 6 and 30 mm on that dress (p50 20 mm for
#: an outer copy 6 mm inside it, ideal 17.9 mm) — the largest height within reach is what a flared or folded inner
#: piece pushes an outer one out to.
LAYER_REACH_M = 0.015
#: Inner feet read per outer foot (the largest height within reach wins).
LAYER_K = 16
#: The field value where no inner piece is within reach: far outside, so nothing is pushed there.
_FAR_M = 1.0


class LayerField:
    """``push_out``'s field for a layer: ``sample(X) = d_body(X) - h_inner(foot(X))`` (far outside where no inner
    foot is within ``reach``), ``grad`` = the body's gradient."""

    def __init__(self, sdf, inner_points: np.ndarray, *, reach: float = LAYER_REACH_M, k: int = LAYER_K):
        from scipy.spatial import cKDTree
        self.sdf, self.reach, self.k = sdf, float(reach), int(k)
        P = np.asarray(inner_points, np.float64).reshape(-1, 3)
        h = sdf.sample(P) if len(P) else np.zeros(0)
        outside = h > 0
        self.h = h[outside]
        self.feet = self._feet(P[outside], self.h)
        self.tree = cKDTree(self.feet) if len(self.feet) else None

    def _feet(self, X: np.ndarray, d: np.ndarray) -> np.ndarray:
        if not len(X):
            return np.zeros((0, 3))
        g = self.sdf.grad(X)
        n = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        return X - d[:, None] * n

    def height(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """``(d_body, h_inner)`` per point; ``h_inner`` is NaN where no inner foot is within reach."""
        X = np.asarray(X, np.float64)
        d = self.sdf.sample(X)
        h = np.full(len(X), np.nan)
        if self.tree is None or not len(X):
            return d, h
        k = min(self.k, len(self.feet))
        dist, idx = self.tree.query(self._feet(X, d), k=k, distance_upper_bound=self.reach)
        dist, idx = dist.reshape(len(X), -1), idx.reshape(len(X), -1)
        found = np.isfinite(dist)
        heights = np.where(found, self.h[np.minimum(idx, len(self.h) - 1)], -np.inf).max(1)
        h[found.any(1)] = heights[found.any(1)]
        return d, h

    def sample(self, X) -> np.ndarray:
        d, h = self.height(X)
        return np.where(np.isnan(h), _FAR_M, d - np.nan_to_num(h))

    def grad(self, X) -> np.ndarray:
        return self.sdf.grad(X)


def _surface_points(g: GarmentMesh) -> np.ndarray:
    """An inner piece's vertices plus its triangle centroids (denser feet on a decimated mesh)."""
    P = np.asarray(g.positions, np.float64)
    F = np.asarray(g.indices, np.int64).reshape(-1, 3)
    return np.concatenate([P, P[F].mean(1)]) if len(F) else P


def layer_sdf(body: BodyMesh, garments: Sequence[GarmentMesh]):
    """The body's signed distance field (``garment_fit.body_sdf`` at ``VOX_M``, metres) over the bounds of
    ``garments`` plus ``SDF_MARGIN_M`` — one field for every tier of a layered fit."""
    pts = [np.asarray(g.positions, np.float64) for g in garments if len(g.positions)]
    if not pts:
        raise ValueError("No garment geometry to bound the field")
    allp = np.concatenate(pts)
    return body_sdf(body.positions, body.faces, vox=VOX_M,
                    bounds=(allp.min(0) - SDF_MARGIN_M, allp.max(0) + SDF_MARGIN_M))


def layer_over(outer: GarmentMesh, body: BodyMesh, inners: Sequence[GarmentMesh], *,
               clear: float = LAYER_CLEAR_M, reach: float = LAYER_REACH_M,
               sdf: Any = None) -> Tuple[GarmentMesh, Dict[str, Any]]:
    """The outer garment (rigged bind space, metres) pushed over the inner garments -> ``(garment, report)``.

    Positions move along the body's gradient until every vertex that has an inner foot within ``reach`` stands
    ``clear`` above the highest such inner vertex; normals are recomputed; UVs, skinning, image and material are
    the outer piece's own. ``sdf``: a field from ``layer_sdf`` covering outer and inners (else built here). The
    report: ``covered_share`` (outer vertices with an inner piece under them),
    ``moved`` / ``max_m`` (the push), ``gap_p1_m`` / ``gap_min_m`` (the layer gap ``d - h`` over the covered
    vertices after the push; ``clear`` when satisfied), ``body_p1_m`` (outer clearance from the body).
    """
    inner_pts = [_surface_points(g) for g in inners if len(g.positions)]
    X0 = np.asarray(outer.positions, np.float64)
    Fo = np.asarray(outer.indices, np.int64).reshape(-1, 3)
    if not inner_pts or not len(X0):
        return outer, {"inner_count": len(inner_pts), "covered_share": 0.0, "moved": 0, "max_m": 0.0}
    inner_all = np.concatenate(inner_pts)
    # Seam duplicates (same position, different UV) move as one vertex: push on welded positions.
    Pw, Fw, inv = weld(X0, Fo)
    if sdf is None:
        sdf = layer_sdf(body, [outer, *inners])
    field = LayerField(sdf, inner_all, reach=reach)
    Qw, disp = push_out(Pw, Fw, field, clear=clear)
    d, h = field.height(Qw)
    covered = ~np.isnan(h)
    gap = (d - h)[covered]
    X = Qw[inv]
    normals = vertex_normals(Qw, Fw)[inv]
    moved = np.linalg.norm(disp, axis=1)
    report = {
        "inner_count": len(inner_pts),
        "covered_share": float(covered.mean()) if len(covered) else 0.0,
        "moved": int((moved > MOVED_EPS_M).sum()),
        "max_m": float(moved.max()) if len(moved) else 0.0,
        "gap_p1_m": float(np.percentile(gap, 1)) if len(gap) else None,
        "gap_min_m": float(gap.min()) if len(gap) else None,
        "body_p1_m": float(np.percentile(d, 1)) if len(d) else None,
        "clear_m": float(clear),
        "reach_m": float(reach),
    }
    return replace(outer, positions=X, normals=normals), report
