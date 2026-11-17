"""Base mesh repair (Ruling A34): the body surface of a base model is closed; a chest tip the extension part
rebuilds is smoothed first.

Two things live here, both pure numpy (no Blender, no trimesh, no scipy at import — the Blender script
``extension_bones.py`` imports this module from Blender's bundled numpy through ``_common.app_root_on_path``):

**Hole fill** (``repair_glb`` / ``fill_holes``). A base body is one closed skin: it has NO intended boundary loop.
The mesher delivers it closed (Kira ``base20d5701a``: 0 open edges out of the mesher, out of the face cleanup and the
face retexture); every open loop on the rigged body is damage — the rigger dropped faces (that body: 3 one-triangle
holes of at most 1.5 mm after ``mesh-mia``, at the neck, the lower back and the upper arm). No loop is kept open: a
base body has no mouth or eye opening, no cut at a seam (the head, hands and feet are one surface with the trunk),
and garments are not body primitives (``glb_mesh._body_prims``). So every loop is filled, unless it is larger
than the "largest hole to fill" setting (``max_hole_cm``): a hole that size is a lost body part, and a membrane
over it would hide that — it stays open and the status says so.

Loops are found on the WELDED surface (positional copies at UV seams are one point, ``WELD_M``). A loop is filled
in the primitive of the faces around it, with the rim's own vertices (so the fill shares their UVs and weights at
the seam-free side of the rim): a 3-vertex loop gets its one triangle; a larger one an ear-clipped triangulation in
its best-fit plane, refined until no inner fill edge is longer than ``REFINE_FACTOR`` times the rim's mean edge, then
FAIRED — the interior vertices solve the uniform bi-Laplacian with the rim and its outer one-ring fixed, so the patch
continues the surrounding curvature (Liepa 2003, "Filling holes in meshes"). Every other vertex attribute of the
new vertices (UVs, colours, morph-target deltas, tangents) is the harmonic interpolation of the rim's values; skin
weights too, per joint over the rim's joints, then the four largest, renormalised to sum 1; normals are the
filled surface's own. A closed body comes back unchanged, byte for byte.

**Matte floor** (``matte_floor``, Ruling A97). The mesher predicts a metallic-roughness texture for the body
(glTF: G = roughness) and paints hair, a beard or brows it modelled INTO the body far glossier than the skin around
them (Rurik ``basee46edcf9``: those texels at roughness 0.16 .. 0.33, the skin at 0.55; Kai ``base634402e5``: the
darkest texels at 0.01) — they glint like wet plastic under a grazing light. No region of an unclothed body is meant
to be glossier than its skin, so every body material gets a floor: the body's own skin roughness — the median
roughness under the body's vertices (a base body is unclothed, so most of its surface is skin) — less
``MATTE_MARGIN``. Texels at or above the floor keep their value, so the skin keeps the generator's roughness and its
fine variation. A texel below it is MIRRORED about it (``r' = min(1, 2 * floor - r)``): continuous at the floor (a
skin texel just below it barely moves), and the glossier the mesher made a region, the rougher it ends — Rurik's
hair and beard at 0.16 .. 0.33 end at 0.67 .. 0.84, Kai's hair at 0.01 at 0.86: matte like hair. Clamping to the
floor instead was rendered too (Ruling A97, Blender, grazing light): the glints go, but the hair keeps the skin's
broad sheen and reads grey and plastic; mirrored it reads matte. The floor is relative on purpose: the mesher gives
one body skin at 0.38 and another at 0.57, so any fixed number either leaves hair glossy or turns a skin matte. The
image is re-encoded in its own format (JPEG at quality 95 without chroma subsampling, PNG / WebP lossless); a
body whose texels are all at or above the floor, or one without a metallic-roughness texture, comes back
unchanged. It runs whether the hole fill is switched on or off — it is not a hole repair — and its record is
``mesh_repair["matte"]``.

**Orientation** (``orient`` / ``orient_glb``, Ruling A137). Every face of a base body is wound outward and every
vertex normal agrees with its faces. Measured on the stored bodies of the test world (four bodies, prerig, plain
and covered): the mesher's winding is already consistent (0..2 inconsistent manifold edges of ~140 000), no face is
visible from outside on its back (9 rays per side), but the surface is split into thousands of manifold pieces by
non-manifold edges (Kira: ~4 900), most faces lie in tight folds, and the parts the extension script builds carry
vertex normals AGAINST their faces (Glut: 3.2 % of the faces). That is why ray parity and normal-based tests read
"13 % inward" (Ruling A135) — not the winding. The pass therefore never guesses an orientation across a
non-manifold edge: on the welded surface it splits the faces into components over MANIFOLD edges only, makes
each component's winding consistent (a breadth-first walk; where both orientations are possible the one that
reverses less area wins), and reverses a whole component only when it is CLOSED (no open or non-manifold edge),
encloses negative volume and does NOT lie inside the rest of the body (six-ray parity, majority) — a closed shell
inside the body wound inward is a cavity and stays so; an open piece keeps the orientation its own majority has. Then every vertex whose stored NORMAL points against the area-weighted normal of its
faces (dot < 0) gets that face normal; every other vertex keeps its bytes. A body that needs nothing comes back
unchanged, byte for byte. It runs in ``repair_glb`` (record ``mesh_repair["orient"]``) and once more on the
published body after the extension parts (``model3d``, ``mesh_repair["orient_parts"]``).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading as _threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

#: Bump when the repair changes what it produces: every stored base body is then repaired again (on the CPU).
#: 2: the matte floor of the body's roughness (Ruling A97).
#: 3: outward winding + vertex normals (``orient``, Ruling A137).
VERSION = 3
#: Metres: positional copies (UV seams, creases) within this distance are one surface point
#: (``extension_bones.COINCIDENT_EPSILON_M``).
WELD_M = 1e-5
#: The "largest hole to fill" setting, its default and range (cm, the hole's largest rim-to-rim distance).
DEFAULT_MAX_HOLE_CM = 4.0
MAX_HOLE_CM_RANGE = (0.5, 20.0)
#: A fill edge longer than this many mean rim edges is split (the patch gets the rim's own resolution).
REFINE_FACTOR = 1.5
#: The matte floor sits this far below the body's median roughness (``matte_floor``): measured over every stored base
#: body of the test world, the skin's 10th percentile lies within 0.04 of that median (Rosi 0.38 / 0.40, Lirien
#: 0.53 / 0.53, Rurik 0.53 / 0.55, Kai 0.45 / 0.49), so the skin stays as it is while hair at 0.01 .. 0.33 rises.
MATTE_MARGIN = 0.05


# --- Settings --------------------------------------------------------------------------------------------------

def validated_settings(raw: Any) -> Dict[str, Any]:
    """``{"enabled": bool, "max_hole_cm": float}`` from a stored or posted map (missing keys = defaults).
    ValueError for a wrong type or a value out of range."""
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw) - {"enabled", "max_hole_cm"}:
        raise ValueError("mesh_repair accepts enabled and max_hole_cm only")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("mesh_repair.enabled must be a boolean")
    limit = raw.get("max_hole_cm", DEFAULT_MAX_HOLE_CM)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit):
        raise ValueError("mesh_repair.max_hole_cm must be a number")
    if not MAX_HOLE_CM_RANGE[0] <= float(limit) <= MAX_HOLE_CM_RANGE[1]:
        raise ValueError(f"mesh_repair.max_hole_cm must be between {MAX_HOLE_CM_RANGE[0]:g} and "
                         f"{MAX_HOLE_CM_RANGE[1]:g}")
    return {"enabled": enabled, "max_hole_cm": float(limit)}


def settings_fingerprint(settings: Dict[str, Any]) -> str:
    """What a repair record stores and the due check compares (the version included)."""
    payload = json.dumps({"version": VERSION, **validated_settings(settings)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- Topology --------------------------------------------------------------------------------------------------

def weld(positions: np.ndarray, tol: float = WELD_M) -> np.ndarray:
    """Welded id per vertex: copies within ``tol`` (grid-rounded) share one id."""
    if not len(positions):
        return np.zeros(0, np.int64)
    q = np.round(np.asarray(positions, np.float64) / tol).astype(np.int64)
    _, inverse = np.unique(q, axis=0, return_inverse=True)
    return inverse.reshape(-1)


def _proper(faces_w: np.ndarray) -> np.ndarray:
    return ((faces_w[:, 0] != faces_w[:, 1]) & (faces_w[:, 1] != faces_w[:, 2])
            & (faces_w[:, 0] != faces_w[:, 2]))


def boundary_loops(positions: np.ndarray, faces: np.ndarray, *, tol: float = WELD_M
                   ) -> Tuple[List[List[Tuple[int, int, int]]], int]:
    """The open loops of a triangle mesh, on its welded surface.

    Returns ``(loops, open_chains)``: each loop is a list of ``(welded id, raw vertex, face)`` in FILL order (the
    direction a fill triangle uses, so it continues the surrounding winding), ``raw vertex`` the vertex the
    boundary face ``face`` uses there; ``open_chains`` counts boundary chains that do not close (a non-manifold
    tangle, never filled). A chain whose two ends share an edge that still has its faces is closed by that edge
    (a face dropped beside a non-manifold edge leaves two open edges). Degenerate faces (two corners on one
    welded point) are ignored."""
    P = np.asarray(positions, np.float64)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    w = weld(P, tol)
    Fw = w[F]
    keep = np.flatnonzero(_proper(Fw))
    if not len(keep):
        return [], 0
    Fw, Fr = Fw[keep], F[keep]
    # directed half-edges (a -> b) of every face, with the raw corners and the face
    a = np.concatenate([Fw[:, 0], Fw[:, 1], Fw[:, 2]])
    b = np.concatenate([Fw[:, 1], Fw[:, 2], Fw[:, 0]])
    ra = np.concatenate([Fr[:, 0], Fr[:, 1], Fr[:, 2]])
    rb = np.concatenate([Fr[:, 1], Fr[:, 2], Fr[:, 0]])
    fi = np.tile(keep, 3)
    stride = int(w.max()) + 1
    key = np.minimum(a, b) * stride + np.maximum(a, b)
    _, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
    edge_set = set(key.tolist())
    open_ = np.flatnonzero(counts[inv.reshape(-1)] == 1)
    if not len(open_):
        return [], 0
    # The fill runs each open edge backwards: from b to a. Next pointer by start vertex (a list: pinch points).
    out_edges: Dict[int, List[int]] = {}
    for e in open_:
        out_edges.setdefault(int(b[e]), []).append(int(e))
    used = set()
    loops: List[List[Tuple[int, int, int]]] = []
    broken = 0
    for start in open_:
        start = int(start)
        if start in used:
            continue
        chain: List[Tuple[int, int, int]] = []
        e = start
        closed = False
        for _ in range(len(open_) + 1):
            used.add(e)
            # fill order: from b[e] (raw rb) to a[e]
            chain.append((int(b[e]), int(rb[e]), int(fi[e])))
            nxt = [x for x in out_edges.get(int(a[e]), []) if x not in used]
            if int(a[e]) == chain[0][0]:
                closed = True
                break
            if not nxt:
                break
            e = nxt[0]
        if not closed and len(chain) >= 2 and _edge_key(int(a[e]), chain[0][0], stride) in edge_set:
            # A chain whose ends are joined by an edge that is NOT open (it still has its faces — a dropped
            # face beside a non-manifold edge leaves two open edges, not three): the existing edge closes it.
            chain.append((int(a[e]), int(ra[e]), int(fi[e])))
            closed = True
        if closed and len(chain) >= 3:
            loops.append(chain)
        else:
            broken += 1
    return loops, broken


def _edge_key(a: int, b: int, stride: int) -> int:
    return min(a, b) * stride + max(a, b)


def open_edge_count(positions: np.ndarray, faces: np.ndarray, *, tol: float = WELD_M) -> int:
    """Welded edges used by exactly one (proper) face."""
    w = weld(np.asarray(positions, np.float64), tol)
    Fw = w[np.asarray(faces, np.int64).reshape(-1, 3)]
    Fw = Fw[_proper(Fw)]
    if not len(Fw):
        return 0
    e = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]), 1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return int((counts == 1).sum())


def _loop_size(points: np.ndarray) -> Tuple[float, float]:
    """``(largest rim-to-rim distance, perimeter)`` of a closed polyline, metres."""
    d = points[:, None, :] - points[None, :, :]
    diameter = float(np.sqrt((d * d).sum(-1)).max()) if len(points) > 1 else 0.0
    perimeter = float(np.linalg.norm(np.roll(points, -1, 0) - points, axis=1).sum())
    return diameter, perimeter


# --- Fill geometry ---------------------------------------------------------------------------------------------

def _plane(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(centre, u, v)`` of the loop's best-fit plane; ``u x v`` points along the loop's own area vector (the
    side the fill faces)."""
    c = points.mean(0)
    area = np.cross(points - c, np.roll(points, -1, 0) - c).sum(0)
    _, _, vt = np.linalg.svd(points - c)
    n = vt[2]
    if float(np.dot(n, area)) < 0:
        n = -n
    u = vt[0] - n * float(np.dot(vt[0], n))
    u /= max(float(np.linalg.norm(u)), 1e-30)
    return c, u, np.cross(n, u)


def _segments_cross(p1, p2, q1, q2) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _simple(xy: np.ndarray) -> bool:
    n = len(xy)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(xy[i], xy[(i + 1) % n], xy[j], xy[(j + 1) % n]):
                return False
    return True


def _ear_clip(xy: np.ndarray) -> Optional[List[Tuple[int, int, int]]]:
    """Triangles (indices into ``xy``, counter-clockwise like ``xy``) of a simple CCW polygon; None when the
    clipping gets stuck."""
    idx = list(range(len(xy)))
    tris: List[Tuple[int, int, int]] = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 10 * len(xy) ** 2:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = xy[i0], xy[i1], xy[i2]
            if cross(a, b, c) <= 1e-18:
                continue
            inside = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = xy[j]
                if cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0:
                    inside = True
                    break
            if inside:
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            clipped = True
            break
        if not clipped:
            return None
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


def _refine(points: List[np.ndarray], tris: List[List[int]], rim: int, limit: float) -> None:
    """Split fill edges in place until no INNER fill edge is longer than ``limit``: the longest inner edge of a
    triangle at its middle, in both triangles that share it. Rim edges are never split (their other side is the
    body). ``points[:rim]`` are the rim."""
    rim_edges = {(min(i, (i + 1) % rim), max(i, (i + 1) % rim)) for i in range(rim)}
    for _ in range(64):
        changed = False
        edge_faces: Dict[Tuple[int, int], List[int]] = {}
        for t, tri in enumerate(tris):
            for k in range(3):
                e = (min(tri[k], tri[(k + 1) % 3]), max(tri[k], tri[(k + 1) % 3]))
                edge_faces.setdefault(e, []).append(t)
        done = set()
        for t in range(len(tris)):
            if t in done:
                continue
            tri = tris[t]
            inner = [(min(tri[k], tri[(k + 1) % 3]), max(tri[k], tri[(k + 1) % 3])) for k in range(3)]
            inner = [e for e in inner if e not in rim_edges]
            if not inner:
                continue
            e = max(inner, key=lambda e: float(np.linalg.norm(points[e[0]] - points[e[1]])))
            owners = edge_faces.get(e, [])
            if (float(np.linalg.norm(points[e[0]] - points[e[1]])) <= limit or len(owners) != 2
                    or any(o in done for o in owners)):
                continue
            m = len(points)
            points.append((points[e[0]] + points[e[1]]) / 2.0)
            for o in owners:
                tri_o = tris[o]
                j = [q for q in range(3) if {tri_o[q], tri_o[(q + 1) % 3]} == set(e)][0]
                x, y, z = tri_o[j], tri_o[(j + 1) % 3], tri_o[(j + 2) % 3]
                tris[o] = [x, m, z]
                tris.append([m, y, z])
                done.add(o)
            changed = True
        if not changed:
            return


def _neighbours(tris: Iterable[Sequence[int]], count: int) -> List[set]:
    nb: List[set] = [set() for _ in range(count)]
    for tri in tris:
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            if a != b:
                nb[a].add(b)
                nb[b].add(a)
    return nb


def _harmonic(values_known: Dict[int, np.ndarray], unknown: List[int], nb: List[set], width: int) -> np.ndarray:
    """Uniform-Laplacian (harmonic) interpolation: ``x_i = mean(x_j)`` for every ``unknown`` vertex, the
    ``values_known`` fixed. Returns ``(len(unknown), width)``."""
    if not unknown:
        return np.zeros((0, width))
    pos = {v: i for i, v in enumerate(unknown)}
    A = np.zeros((len(unknown), len(unknown)))
    rhs = np.zeros((len(unknown), width))
    for v, i in pos.items():
        ns = nb[v]
        A[i, i] = len(ns)
        for j in ns:
            if j in pos:
                A[i, pos[j]] -= 1.0
            else:
                rhs[i] += values_known[j]
    return np.linalg.lstsq(A, rhs, rcond=None)[0]


def _bilaplacian(positions: Dict[int, np.ndarray], unknown: List[int], nb: List[set]) -> np.ndarray:
    """Positions of the ``unknown`` vertices minimising the uniform bi-Laplacian (thin-plate fairing); every
    other vertex of ``nb`` fixed. The Laplacian is taken at the unknown vertices AND their neighbours, so the
    rim's outer ring (in ``nb``) carries the surrounding curvature into the patch."""
    if not unknown:
        return np.zeros((0, 3))
    rows = sorted({v for u in unknown for v in (u, *nb[u])})
    cols = sorted({v for r in rows for v in (r, *nb[r])})
    rpos = {v: i for i, v in enumerate(rows)}
    cpos = {v: i for i, v in enumerate(cols)}
    L = np.zeros((len(rows), len(cols)))
    for v, i in rpos.items():
        ns = nb[v]
        L[i, cpos[v]] = 1.0
        for j in ns:
            L[i, cpos[j]] -= 1.0 / len(ns)
    # (L^2 x)_u = (Lx)_u - mean_{j in N(u)} (Lx)_j for every unknown u
    B = np.zeros((len(unknown), len(cols)))
    for k, u in enumerate(unknown):
        B[k] += L[rpos[u]]
        for j in nb[u]:
            B[k] -= L[rpos[j]] / len(nb[u])
    upos = [cpos[u] for u in unknown]
    unknown_cols = set(upos)
    fixed = [c for c in range(len(cols)) if c not in unknown_cols]
    X = np.array([positions[cols[c]] for c in fixed]) if fixed else np.zeros((0, 3))
    rhs = -B[:, fixed] @ X if fixed else np.zeros((len(unknown), 3))
    return np.linalg.lstsq(B[:, upos], rhs, rcond=None)[0]


def _skin(joints: np.ndarray, weights: np.ndarray, rim_raw: List[int], unknown_count: int,
          nb_rim_patch: List[set], rim: int) -> Tuple[np.ndarray, np.ndarray]:
    """Skin of the new vertices: per joint over the rim's joints, harmonic; then the four largest, sum 1."""
    jset = sorted({int(j) for r in rim_raw for j, w in zip(joints[r], weights[r]) if w > 0})
    if not jset:
        return np.zeros((unknown_count, 4), np.int64), np.zeros((unknown_count, 4))
    col = {j: i for i, j in enumerate(jset)}
    dense = np.zeros((rim, len(jset)))
    for k, r in enumerate(rim_raw):
        for j, w in zip(joints[r], weights[r]):
            if w > 0:
                dense[k, col[int(j)]] += w
    dense /= np.maximum(dense.sum(1, keepdims=True), 1e-30)
    known = {k: dense[k] for k in range(rim)}
    vals = _harmonic(known, list(range(rim, rim + unknown_count)), nb_rim_patch, len(jset))
    vals = np.clip(vals, 0.0, None)
    order = np.argsort(-vals, axis=1)[:, :4]
    J = np.zeros((unknown_count, 4), np.int64)
    W = np.zeros((unknown_count, 4))
    for i in range(unknown_count):
        for k, c in enumerate(order[i]):
            if c < len(jset):
                J[i, k] = jset[c]
                W[i, k] = vals[i, c]
        s = W[i].sum()
        if s <= 0:
            J[i, 0], W[i] = jset[int(np.argmax(dense.mean(0)))], [1.0, 0.0, 0.0, 0.0]
        else:
            W[i] /= s
    return J, W


def fill_loop(prim, loop: List[Tuple[int, int, int]], positions_w: np.ndarray, body_nb: List[set]
              ) -> Dict[str, Any]:
    """Fill ONE loop of ``prim`` (a ``glb_mesh.Prim``, mutated in place: vertices and faces appended).
    ``positions_w`` / ``body_nb``: the welded surface (positions per welded id, welded neighbours) for the
    fairing's outer ring. Returns the fill's numbers."""
    rim_raw = [raw for _, raw, _ in loop]
    rim_w = [wid for wid, _, _ in loop]
    rim = len(rim_raw)
    P = prim.positions
    pts = [np.asarray(P[r], np.float64) for r in rim_raw]
    if rim == 3:
        tris = [[0, 1, 2]]
    else:
        c, u, v = _plane(np.array(pts))
        xy = np.array([[float(np.dot(p - c, u)), float(np.dot(p - c, v))] for p in pts])
        tris_list = _ear_clip(xy) if _simple(xy) else None
        if tris_list is None:   # a loop that folds over in its plane: a fan around its centroid
            pts.append(np.array(pts).mean(0))
            tris = [[i, (i + 1) % rim, rim] for i in range(rim)]
        else:
            tris = [list(t) for t in tris_list]
        mean_edge = float(np.mean([np.linalg.norm(pts[(i + 1) % rim] - pts[i]) for i in range(rim)]))
        _refine(pts, tris, rim, REFINE_FACTOR * mean_edge)
    count = len(pts)
    interior = list(range(rim, count))
    patch_nb = _neighbours(tris, count)
    if interior:
        # Fairing graph: patch vertices 0..count-1, then the rim's outer welded ring as extra fixed vertices.
        nb = [set(s) for s in patch_nb]
        extra: Dict[int, int] = {}
        known: Dict[int, np.ndarray] = {i: pts[i] for i in range(rim)}
        rim_set = set(rim_w)
        for k, wid in enumerate(rim_w):
            for o in body_nb[wid]:
                if o in rim_set:
                    q = rim_w.index(o)
                    nb[k].add(q)
                    continue
                if o not in extra:
                    extra[o] = len(nb)
                    nb.append(set())
                    known[extra[o]] = positions_w[o]
                nb[k].add(extra[o])
                nb[extra[o]].add(k)
        faired = _bilaplacian({**known, **{i: pts[i] for i in interior}}, interior, nb)
        for k, i in enumerate(interior):
            pts[i] = faired[k]
    new_pos = np.array(pts[rim:]) if interior else np.zeros((0, 3))
    base = len(P)
    raw_of = {i: rim_raw[i] for i in range(rim)}
    raw_of.update({i: base + k for k, i in enumerate(interior)})
    faces = np.array([[raw_of[t[0]], raw_of[t[1]], raw_of[t[2]]] for t in tris], np.int64)
    if interior:
        known_attr = lambda arr: {i: np.atleast_1d(np.asarray(arr[rim_raw[i]], np.float64)) for i in range(rim)}
        for name, arr in list(prim.attributes.items()):
            width = 1 if arr.ndim == 1 else arr.shape[1]
            if name == "NORMAL":
                continue   # the filled surface's own, below
            vals = _harmonic(known_attr(arr), interior, patch_nb, width)
            if name.startswith("TANGENT") and width == 4:
                xyz = vals[:, :3] / np.maximum(np.linalg.norm(vals[:, :3], axis=1, keepdims=True), 1e-30)
                vals = np.concatenate([xyz, np.sign(np.where(vals[:, 3:] == 0, 1, vals[:, 3:]))], 1)
            prim.attributes[name] = np.concatenate([arr, vals.reshape(len(interior), *arr.shape[1:])])
        for target in prim.targets:
            for name, arr in list(target.items()):
                width = 1 if arr.ndim == 1 else arr.shape[1]
                vals = _harmonic(known_attr(arr), interior, patch_nb, width)
                target[name] = np.concatenate([arr, vals.reshape(len(interior), *arr.shape[1:])])
        if len(prim.joints) == len(P):
            J, W = _skin(prim.joints, prim.weights, rim_raw, len(interior), patch_nb, rim)
            prim.joints = np.concatenate([prim.joints, J])
            prim.weights = np.concatenate([prim.weights, W])
        prim.positions = np.concatenate([P, new_pos])
        if "NORMAL" in prim.attributes:
            allp = prim.positions
            fn = np.cross(allp[faces[:, 1]] - allp[faces[:, 0]], allp[faces[:, 2]] - allp[faces[:, 0]])
            acc = np.zeros((len(interior), 3))
            for f, n in zip(faces, fn):
                for r in f:
                    if r >= base:
                        acc[r - base] += n
            acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-30)
            prim.attributes["NORMAL"] = np.concatenate([prim.attributes["NORMAL"], acc])
    prim.faces = np.concatenate([prim.faces, faces])
    return {"vertices_added": len(interior), "faces_added": len(faces)}


def fill_holes(prims: List[Any], *, max_hole_m: float) -> Dict[str, Any]:
    """Fill every open loop of the body primitives ``prims`` (``glb_mesh.Prim``, mutated) up to ``max_hole_m``
    across. Returns the report: ``{holes, filled, largest_cm (of the filled), unfilled: [{size_cm, reason}],
    vertices_added, faces_added, changed: [prim index]}``."""
    sizes: List[int] = [len(p.positions) for p in prims]
    offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
    P = np.concatenate([p.positions for p in prims]) if prims else np.zeros((0, 3))
    F = np.concatenate([p.faces + offsets[i] for i, p in enumerate(prims)]) if prims else np.zeros((0, 3), np.int64)
    report: Dict[str, Any] = {"holes": 0, "filled": 0, "largest_cm": 0.0, "unfilled": [], "vertices_added": 0,
                              "faces_added": 0, "changed": []}
    loops, broken = boundary_loops(P, F)
    report["holes"] = len(loops) + broken
    for _ in range(broken):
        report["unfilled"].append({"size_cm": None, "reason": "open edges that do not close into a loop"})
    if not loops:
        return report
    w = weld(P)
    positions_w = np.zeros((int(w.max()) + 1, 3))
    positions_w[w] = P
    Fw = w[F]
    Fw = Fw[_proper(Fw)]
    body_nb = _neighbours(Fw.tolist(), len(positions_w))
    prim_of = np.searchsorted(offsets, np.arange(len(P)), side="right") - 1
    plans = []
    for loop in loops:
        owners = {int(prim_of[raw]) for _, raw, _ in loop}
        size, _perimeter = _loop_size(positions_w[[wid for wid, _, _ in loop]])
        if len(owners) != 1:
            report["unfilled"].append({"size_cm": round(size * 100, 2), "reason": "the loop spans two primitives"})
            continue
        if size > max_hole_m:
            report["unfilled"].append({"size_cm": round(size * 100, 2),
                                       "reason": "larger than the largest hole to fill"})
            continue
        plans.append((owners.pop(), loop, size))
    for index, loop, size in plans:
        prim = prims[index]
        local = [(wid, raw - int(offsets[index]), face) for wid, raw, face in loop]
        numbers = fill_loop(prim, local, positions_w, body_nb)
        report["filled"] += 1
        report["largest_cm"] = max(report["largest_cm"], round(size * 100, 2))
        report["vertices_added"] += numbers["vertices_added"]
        report["faces_added"] += numbers["faces_added"]
        if index not in report["changed"]:
            report["changed"].append(index)
    return report


# --- Orientation (Ruling A137) ---------------------------------------------------------------------------------


#: The six axis rays of the enclosure test (``_enclosed``), nudged off the axes so no ray runs along an edge.
_RAYS = np.array([[1, 0.013, 0.007], [-1, 0.011, -0.009], [0.008, 1, 0.012], [-0.006, -1, 0.01],
                  [0.009, -0.014, 1], [-0.012, 0.005, -1]], np.float64)


def _enclosed(P: np.ndarray, F: np.ndarray, point: np.ndarray) -> bool:
    """Whether ``point`` lies inside the surface ``P[F]``: an odd number of crossings on most of six rays (a
    majority, because the surface is not watertight everywhere)."""
    if not len(F):
        return False
    v0, v1, v2 = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    e1, e2 = v1 - v0, v2 - v0
    s = point - v0
    q = np.cross(s, e1)
    odd = 0
    for d in _RAYS:
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-14
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        u = np.einsum("ij,ij->i", s, h) * inv
        v = np.einsum("ij,j->i", q, d) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hits = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
        odd += int(hits.sum()) % 2
    return odd >= 4


def orient(prims: List[Any]) -> Dict[str, Any]:
    """Wind the body primitives ``prims`` (``glb_mesh.Prim``, mutated) outward and repair their vertex normals
    (module docstring). Returns ``{components, closed, voids, faces_flipped, conflicts, normals_fixed, changed}``."""
    sizes = [len(p.positions) for p in prims]
    offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
    fcounts = [len(p.faces) for p in prims]
    foff = np.concatenate([[0], np.cumsum(fcounts)]).astype(np.int64)
    report: Dict[str, Any] = {"components": 0, "closed": 0, "voids": 0, "faces_flipped": 0,
                              "conflicts": 0, "normals_fixed": 0, "changed": []}
    if not prims or not sum(fcounts):
        return report
    P = np.concatenate([p.positions for p in prims])
    F = np.concatenate([p.faces + offsets[i] for i, p in enumerate(prims)]).astype(np.int64)
    m = len(F)
    w = weld(P)
    Fw = w[F]
    proper = _proper(Fw)
    # Directed edges of the proper faces; an undirected edge with exactly two faces links them.
    fid = np.tile(np.arange(m), 3)
    a = np.concatenate([Fw[:, 0], Fw[:, 1], Fw[:, 2]])
    b = np.concatenate([Fw[:, 1], Fw[:, 2], Fw[:, 0]])
    keep = np.tile(proper, 3)
    fid, a, b = fid[keep], a[keep], b[keep]
    stride = int(w.max()) + 1
    key = np.minimum(a, b) * stride + np.maximum(a, b)
    forward = a < b
    order = np.argsort(key, kind="stable")
    key, fid, forward = key[order], fid[order], forward[order]
    _, start, count = np.unique(key, return_index=True, return_counts=True)
    two = start[count == 2]
    f1, f2 = fid[two], fid[two + 1]
    # Same traversal direction on both sides: the two faces disagree (one of them must be reversed).
    differ = (forward[two] == forward[two + 1]).astype(np.int8)
    bad_edge_faces = np.zeros(m, bool)          # faces on an open or non-manifold edge
    bad_edge_faces[fid[np.repeat(count != 2, count)]] = True
    adj: List[List[Tuple[int, int]]] = [[] for _ in range(m)]
    for x, y, d in zip(f1.tolist(), f2.tolist(), differ.tolist()):
        if x == y:
            continue
        adj[x].append((y, d))
        adj[y].append((x, d))
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])      # 2 x area, along the winding
    area = 0.5 * np.linalg.norm(fn, axis=1)
    vol6 = np.einsum("ij,ij->i", P[F[:, 0]], fn)                          # 6 x signed volume (origin)
    flip = np.zeros(m, bool)
    seen = np.zeros(m, bool)
    for seed in range(m):
        if seen[seed] or not proper[seed]:
            continue
        report["components"] += 1
        seen[seed] = True
        rel = {seed: 0}
        stack = [seed]
        while stack:
            f = stack.pop()
            for g, d in adj[f]:
                want = rel[f] ^ d
                if g in rel:
                    if rel[g] != want:
                        report["conflicts"] += 1
                    continue
                rel[g] = want
                seen[g] = True
                stack.append(g)
        faces = np.fromiter(rel.keys(), np.int64, len(rel))
        bits = np.fromiter(rel.values(), np.int8, len(rel)).astype(bool)
        # The orientation of the component that reverses less area.
        if area[faces[bits]].sum() > area[faces[~bits]].sum():
            bits = ~bits
        if not bad_edge_faces[faces].any():
            report["closed"] += 1
            sign = np.where(bits, -1.0, 1.0)
            if float((vol6[faces] * sign).sum()) < 0:
                inside = np.ones(m, bool)
                inside[faces] = False
                if _enclosed(P, F[inside & proper], P[F[faces[0]]].mean(0)):
                    report["voids"] += 1     # a cavity in the body: wound into the cavity, as it should be
                else:
                    bits = ~bits
        flip[faces[bits]] = True
    report["conflicts"] //= 2
    report["faces_flipped"] = int(flip.sum())
    changed = set()
    for i, p in enumerate(prims):
        local = flip[foff[i]:foff[i + 1]]
        if local.any():
            p.faces = p.faces.copy()
            p.faces[local] = p.faces[local][:, [0, 2, 1]]
            changed.add(i)
        N = p.attributes.get("NORMAL")
        if N is None or not len(p.faces):
            continue
        Q = p.positions
        n = np.cross(Q[p.faces[:, 1]] - Q[p.faces[:, 0]], Q[p.faces[:, 2]] - Q[p.faces[:, 0]])
        vn = np.zeros_like(Q)
        for k in range(3):
            np.add.at(vn, p.faces[:, k], n)
        length = np.linalg.norm(vn, axis=1)
        wrong = (np.einsum("ij,ij->i", vn, N) < 0) & (length > 0)
        if wrong.any():
            N = N.copy()
            N[wrong] = vn[wrong] / length[wrong, None]
            p.attributes["NORMAL"] = N
            report["normals_fixed"] += int(wrong.sum())
            changed.add(i)
    report["changed"] = sorted(changed)
    return report


def orient_glb(glb: bytes) -> Tuple[bytes, Dict[str, Any]]:
    """``(bytes, record)``: ``glb`` with its body primitives wound outward and their normals repaired
    (``orient``); a body that needs nothing returns ``glb`` itself."""
    from app.core import glb_mesh
    prims = glb_mesh.body_primitive_arrays(glb)
    report = orient(prims)
    changed = report.pop("changed")
    record = {"status": "applied", **report}
    if not changed:
        return glb, record
    return glb_mesh.rewrite_body_primitives(glb, {i: prims[i] for i in changed}), record


# --- Matte floor ----------------------------------------------------------------------------------------------

def _texture_images(gltf: dict, texture_index: int) -> List[int]:
    """Every image a texture names: its core ``source`` and any extension source (``EXT_texture_webp`` …)."""
    texture = gltf["textures"][texture_index]
    found = [texture["source"]] if isinstance(texture.get("source"), int) else []
    for extension in (texture.get("extensions") or {}).values():
        if isinstance(extension, dict) and isinstance(extension.get("source"), int):
            found.append(extension["source"])
    return sorted(set(found))


def _decode(payload: bytes) -> np.ndarray:
    from PIL import Image
    import io
    image = Image.open(io.BytesIO(payload))
    image.load()
    return np.asarray(image.convert("RGBA" if "A" in image.getbands() else "RGB")).copy()


def _encode_like(array: np.ndarray, mime: str) -> bytes:
    """``array`` in the format of ``mime``: JPEG at quality 95 without chroma subsampling (the roughness channel is
    not blurred into its neighbours), WebP / PNG lossless."""
    from PIL import Image
    import io
    out = io.BytesIO()
    image = Image.fromarray(array)
    if mime == "image/jpeg":
        image.convert("RGB").save(out, "JPEG", quality=95, subsampling=0)
    elif mime == "image/webp":
        image.save(out, "WEBP", lossless=True)
    else:
        image.save(out, "PNG")
    return out.getvalue()


def matte_floor(glb: bytes, *, margin: float = MATTE_MARGIN) -> Tuple[bytes, Dict[str, Any]]:
    """``(bytes, record)``: ``glb`` with the roughness (G) of every body material's metallic-roughness texture below
    ``floor = median roughness under the body's vertices - margin`` mirrored about that floor (``min(1, 2 * floor -
    r)``; module docstring, Ruling A97). The record:
    ``status`` ``applied`` | ``unchanged`` | ``skipped`` (no metallic-roughness texture), ``anchor`` (the median),
    ``floor``, ``lifted`` (the share of body vertices whose roughness was below the floor), ``p10_before`` /
    ``p10_after`` (their 10th percentile). Roughness counts with the material's ``roughnessFactor``. Garment
    primitives are no body (``glb_mesh._body_prims``) and keep their map (Ruling A36)."""
    from app.core import glb_mesh
    from app.core.face_cleanup import _replace_image
    parsed = glb_mesh._parse(glb, "Base")
    gltf = parsed["gltf"]
    by_texture: Dict[int, List[Tuple[np.ndarray, float]]] = {}
    for primitive in glb_mesh._body_prims(parsed):
        if "material" not in primitive:
            continue
        pbr = gltf["materials"][primitive["material"]].get("pbrMetallicRoughness") or {}
        info = pbr.get("metallicRoughnessTexture")
        if not isinstance(info, dict):
            continue
        uv_key = f"TEXCOORD_{int(info.get('texCoord', 0))}"
        if uv_key not in primitive.get("attributes", {}):
            continue
        uvs = glb_mesh.accessor_array(parsed, primitive["attributes"][uv_key]).astype(np.float64)
        by_texture.setdefault(int(info["index"]), []).append((uvs, float(pbr.get("roughnessFactor", 1.0))))
    if not by_texture:
        return glb, {"status": "skipped", "reason": "no metallic-roughness texture"}
    binary = bytearray(parsed["bin"])
    record: Dict[str, Any] = {"status": "unchanged", "margin": margin}
    before_all, after_all, below, anchors, floors = [], [], [], [], []
    changed = False
    for texture_index, uses in sorted(by_texture.items()):
        images = _texture_images(gltf, texture_index)
        decoded = {}
        for image_index in images:
            if "bufferView" not in gltf["images"][image_index]:
                raise ValueError("The metallic-roughness image is not embedded")
            view = gltf["bufferViews"][gltf["images"][image_index]["bufferView"]]
            start = int(view.get("byteOffset", 0))
            decoded[image_index] = _decode(bytes(binary[start:start + int(view["byteLength"])]))
        # The values are read from the image the renderers load (the preferred one, ``texture_image_index``).
        from app.core.model_validate import texture_image_index
        main = decoded[texture_image_index(gltf, gltf["textures"][texture_index])]
        height, width = main.shape[:2]
        samples = []
        for uvs, factor in uses:
            u = np.clip((np.mod(uvs[:, 0], 1.0) * width).astype(int), 0, width - 1)
            v = np.clip((np.mod(uvs[:, 1], 1.0) * height).astype(int), 0, height - 1)
            samples.append((main[v, u, 1].astype(np.float64) / 255.0) * factor)
        rough = np.concatenate(samples)
        factor = max(f for _uvs, f in uses)
        anchor = float(np.median(rough))
        floor = anchor - margin
        anchors.append(anchor)
        floors.append(floor)
        before_all.append(rough)
        after_all.append(np.where(rough < floor, np.minimum(1.0, 2.0 * floor - rough), rough))
        below.append(rough < floor)
        if floor <= 0 or factor <= 0 or not (rough < floor).any():
            continue
        level = int(math.ceil(min(1.0, floor / factor) * 255.0))
        for image_index, array in decoded.items():
            if not (array[..., 1] < level).any():
                continue
            g = array[..., 1].astype(np.int32)
            array[..., 1] = np.where(g < level, np.minimum(255, 2 * level - g), g).astype(np.uint8)
            mime = gltf["images"][image_index].get("mimeType") or "image/png"
            binary = _replace_image(parsed, binary, image_index, _encode_like(array, mime))
            changed = True
    before, after = np.concatenate(before_all), np.concatenate(after_all)
    record.update(anchor=round(min(anchors), 3), floor=round(min(floors), 3),
                  lifted=round(float(np.concatenate(below).mean()), 3),
                  p10_before=round(float(np.percentile(before, 10)), 3),
                  p10_after=round(float(np.percentile(after, 10)), 3))
    if not changed:
        return glb, record
    record["status"] = "applied"
    return glb_mesh.pack_glb(gltf, bytes(binary)), record


def repair_glb(glb: bytes, settings: Optional[Dict[str, Any]] = None) -> Tuple[bytes, Dict[str, Any]]:
    """``(bytes, record)``: ``glb`` with the holes of its body primitives filled (``fill_holes``), then its body
    wound outward with its normals repaired (``orient``), its roughness lifted to the matte floor (``matte_floor``;
    both also when the hole fill is switched off), and the record a
    model stores (``mesh_repair``: version, settings fingerprint, status ``applied`` | ``skipped`` of the hole fill,
    the numbers, ``matte``). A closed body without a glossy texel returns ``glb`` itself, unchanged."""
    from app.core import glb_mesh
    settings = validated_settings(settings)
    record: Dict[str, Any] = {"version": VERSION, "settings": settings_fingerprint(settings),
                              "max_hole_cm": settings["max_hole_cm"]}
    out = glb
    if not settings["enabled"]:
        record.update(status="skipped", reason="switched off")
    else:
        prims = glb_mesh.body_primitive_arrays(glb)
        report = fill_holes(prims, max_hole_m=settings["max_hole_cm"] / 100.0)
        changed = report.pop("changed")
        record.update(status="applied", **report)
        if changed:
            out = glb_mesh.rewrite_body_primitives(glb, {i: prims[i] for i in changed})
            record["open_edges_after"] = open_edge_count(*_concat(glb_mesh.body_primitive_arrays(out)))
    try:
        out, record["orient"] = orient_glb(out)
    except Exception as exc:  # noqa: BLE001 — the body keeps the mesher's winding and normals
        record["orient"] = {"status": "failed", "error": f"Orientation failed: {exc}"}
    try:
        out, record["matte"] = matte_floor(out)
    except Exception as exc:  # noqa: BLE001 — the holes stay filled; the body keeps the mesher's roughness
        record["matte"] = {"status": "failed", "error": f"Matte floor failed: {exc}"}
    return out, record


def _concat(prims) -> Tuple[np.ndarray, np.ndarray]:
    P, F, base = [], [], 0
    for p in prims:
        P.append(p.positions)
        F.append(p.faces + base)
        base += len(p.positions)
    return np.concatenate(P), np.concatenate(F)


def summary(record: Optional[Dict[str, Any]]) -> str:
    """The status line of a repair record: "2 holes filled, largest 1.8 cm", "Closed — no hole",
    "1 hole left open (6.2 cm — larger than the largest hole to fill)", "Switched off"."""
    record = record if isinstance(record, dict) else {}
    if record.get("status") == "failed":
        return str(record.get("error") or "Repair failed")
    if record.get("status") == "skipped":
        return "Switched off"
    filled = int(record.get("filled") or 0)
    unfilled = [u for u in (record.get("unfilled") or []) if isinstance(u, dict)]
    parts = []
    if filled:
        parts.append(f"{filled} hole{'s' if filled != 1 else ''} filled, largest {float(record.get('largest_cm') or 0):.1f} cm")
    if unfilled:
        sizes = [f"{u['size_cm']:.1f} cm" for u in unfilled if isinstance(u.get("size_cm"), (int, float))]
        reason = str(unfilled[0].get("reason") or "")
        parts.append(f"{len(unfilled)} hole{'s' if len(unfilled) != 1 else ''} left open"
                     + (f" ({', '.join(sizes)} — {reason})" if sizes else f" ({reason})"))
    return " · ".join(parts) if parts else "Closed — no hole"


# --- "Repair again" (the Base body tab) ---------------------------------------------------------------------------


_lock = _threading.Lock()
_running: Dict[str, str] = {}
_results: Dict[str, Dict[str, Any]] = {}


def run_state(character_name: str) -> Dict[str, Any]:
    """``{running, last}`` of the character's "Repair again" run (``last``: ``{signature, error, at}`` or None)."""
    with _lock:
        return {"running": character_name in _running,
                "last": dict(_results[character_name]) if character_name in _results else None}


def start_repair(character_name: str, signature: str) -> bool:
    """Repair the stored base model ``signature`` again in a worker thread: the forced CPU rebuild of its
    extension rig from the clean prerig source (``model3d.rebuild_extension_rig(repair=True)``) — the repair with
    the saved settings, then the extension parts on the repaired mesh, the covered variant, the capsules; no hub
    job. A changed base then refits what is fitted on it (``model3d.after_base_face_change``). False when a
    repair of the character already runs; ValueError when the model is missing."""
    from app.core.model3d import find_model3d
    if find_model3d(character_name, signature) is None:
        raise ValueError("Stored model not found for signature")
    with _lock:
        if character_name in _running:
            return False
        _running[character_name] = signature
        _results.pop(character_name, None)
    try:
        from app.core import cpu_progress
        _threading.Thread(target=cpu_progress.scoped(f"figure:{character_name}", _apply),  # A194: live line
                          args=(character_name, signature), daemon=True,
                          name=f"mesh-repair-{character_name}").start()
    except BaseException:
        with _lock:
            _running.pop(character_name, None)
        raise
    return True


def _apply(character_name: str, signature: str) -> None:
    import logging
    from app.core.model3d import rebuild_extension_rig
    from app.core.task_queue import get_task_queue
    from app.core.timeutils import utc_now_iso
    logger = logging.getLogger(__name__)
    error, task_id = "", ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"Base mesh repair: {character_name}",
            agent_name=character_name, start_running=True)
    except Exception:  # noqa: BLE001 — tracking is display only
        task_id = ""
    try:
        result = rebuild_extension_rig(character_name, signature, force=True, repair=True)
        if not result.get("ok"):
            error = (result.get("error") or (result.get("extension_rig") or {}).get("reason")
                     or "Base mesh repair failed")
    except Exception as exc:  # noqa: BLE001 — reported to the panel
        logger.exception("Base mesh repair of %s (%s) failed", character_name, signature)
        error = str(exc) or type(exc).__name__
    finally:
        with _lock:
            _running.pop(character_name, None)
            _results[character_name] = {"signature": signature, "error": error, "at": utc_now_iso()}
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:  # noqa: BLE001
                pass
