"""Body faces hidden under own-mesh clothing (Ruling A133).

The assembled figure (``garment_assembly._build``) grafts each own-mesh clothing piece over the body. In a bent
pose (sit, kneel) the body can poke through the piece near a crease. The body skin under a piece is never seen, so
the assembly drops the body faces a piece fully covers from the DELIVERED body — the bare file stays whole, so the
step is reversible: another worn set builds another assembly from the same bare file.

Rule, per body vertex ``v`` (bind pose, normal ``n_v``) against the union of the clothing pieces:

* covered — one of the ``NEIGHBOURS`` nearest piece vertices ``p`` (normal ``n_p``) lies within ``REACH_M`` of ``v``, faces the same way
  (``n_v · n_p >= FACING_MIN``) and is not more than ``INSIDE_TOL_M`` behind the skin (``(p - v) · n_v``);
  and lies OVER it, not beside it (sideways offset ``<= |(p - v) · n_v| + LATERAL_SLACK_M``); the facing test
  keeps skin that only lies NEXT to a piece (a torso beside a sleeve whose inner wall faces it), the sideways test
  skin past a piece's end.
* kept anyway — within ``HEM_BAND_M`` of a piece's open border (a boundary edge: the hem, a cuff, a collar), so no
  hole can show through an opening.

A body face is dropped only when all three of its vertices are covered. Footwear has its own cut, hair and painted
pieces never hide anything. Numpy + pykdtree on the CPU, no hub job. ``VERSION`` enters the assembly state, so a
changed rule makes every assembly due once.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

VERSION = 1
REACH_M = 0.06
FACING_MIN = 0.3
INSIDE_TOL_M = 0.02
HEM_BAND_M = 0.02
NEIGHBOURS = 8
LATERAL_SLACK_M = 0.005


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


def covered_vertices(body_pos: np.ndarray, body_faces: np.ndarray,
                     pieces: Sequence[Tuple[np.ndarray, np.ndarray]]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """(bool mask over the body vertices, stats) — see the module rule. ``pieces`` = (positions, faces) of each
    clothing piece in the body's space."""
    from pykdtree.kdtree import KDTree
    B = np.asarray(body_pos, np.float64)
    covered = np.zeros(len(B), bool)
    stats: Dict[str, Any] = {"pieces": len(pieces), "near": 0, "hem_kept": 0}
    if not len(pieces) or not len(B):
        return covered, stats
    nb = vertex_normals(B, body_faces)
    gp: List[np.ndarray] = []
    gn: List[np.ndarray] = []
    rim: List[np.ndarray] = []
    for pos, faces in pieces:
        P = np.asarray(pos, np.float64)
        welded = weld(P, faces)
        gp.append(P)
        gn.append(vertex_normals(P, welded))
        rim.append(P[boundary_vertices(welded)])
    G = np.ascontiguousarray(np.concatenate(gp))
    GN = np.concatenate(gn)
    dist, idx = KDTree(G).query(np.ascontiguousarray(B), k=NEIGHBOURS, distance_upper_bound=REACH_M)
    near = np.isfinite(dist) & (idx < len(G))
    j = np.where(near, idx, 0)
    ahead = np.einsum("ikj,ij->ik", G[j] - B[:, None, :], nb)
    facing = np.einsum("ikj,ij->ik", GN[j], nb)
    span = np.linalg.norm(G[j] - B[:, None, :], axis=2)
    lateral = np.sqrt(np.maximum(span ** 2 - ahead ** 2, 0.0))
    over = lateral <= np.abs(ahead) + LATERAL_SLACK_M
    covered = (near & (facing >= FACING_MIN) & (ahead >= -INSIDE_TOL_M) & over).any(axis=1)
    stats["near"] = int(near.any(axis=1).sum())
    R = np.concatenate(rim) if rim else np.zeros((0, 3))
    if len(R) and covered.any():
        cand = np.flatnonzero(covered)
        d_rim, _ = KDTree(np.ascontiguousarray(R)).query(np.ascontiguousarray(B[cand]), k=1)
        hem = cand[d_rim < HEM_BAND_M]
        covered[hem] = False
        stats["hem_kept"] = int(len(hem))
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
