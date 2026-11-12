"""HairDeck spring chains on our rig: load the chains, bind every hair card to its chain, place the joints with the
cards and merge the chain weights into the hair's skin — pure numpy/scipy (plan 2026-11-12-hairdeck-spring-chains,
Task 2).

HairDeck delivers per seed, besides the hair cards, ``chains_seed<s>.json`` (per chain ``joints`` (n, 3) in
HairDeck's head frame, ``stiffness``) and ``cards_seed<s>.json`` (per card ``seq`` (m, 8), root first). The k-th
unwelded connected component of the ``hair_cards`` mesh, in order of its first vertex, IS card k of
``cards_seed`` (same centroid; ``card_centrelines`` checks it, ``CARD_MATCH_TOL``).

Binding (``bind``): a card follows the chain nearest to the lower 60 % of its 16-point centreline when that mean
distance is below ``ASSIGN`` face widths, else it stays rigid with the head. Its vertices then bind to the nearest
segment of that chain, blended with the neighbouring segment around each joint, with a weight that ramps from 0 at
the chain root to 1 over ``RAMP`` face widths of arc length. A card whose vertex rows fail the lower-60 % test on
their own (the vertex-level test disagrees with the centreline) stays rigid.

Placement (Ruling H8, 2026-11-12): the chains are bound to TODAY's fitted rest — the joints get exactly the cards'
similarity and placement correction (``garment_hairdeck._place_and_push(chain_points=…)``) and then follow the
per-vertex push / face-clearing field of their own cards (``follow``, IDW over the ``FOLLOW_K`` nearest bound
vertices). There is no rest-pose settle; the static fit stays as it was, the chains only add motion.

Rest depth (``repair_depth``, Task 3 in its Ruling H8 form): the followed joints are checked against the body
surface (the fit's body SDF). A joint more than ``SETTLE_TOL_M`` inside the body is moved onto its chain's
card-centroid line (``card_centroid_line``: per joint the centroid of the ``FOLLOW_K`` fitted bound vertices
nearest to it) at the nearest point of that line outside the body (``nearest_outside``). A chain with a deep joint
that has no such point — or whose repair would collapse a segment — is unbound (``unbind``): its cards keep today's
rigid Head -> Neck -> Spine2 weights. A repair, never a refusal; the cards themselves are never moved.

Skin (``chain_weights``): a chain-bound vertex rides Head with ``1 - w`` and its two segment bones with ``w * alpha``
and ``w * (1 - alpha)``; a rigid card keeps ``garment_fit.hair_weights``' Head -> Neck -> Spine2 row. Joint names:
``HairGen_c<CC>_<KK>`` (``CC`` = HairDeck's chain index in the file, ``KK`` = segment) plus a leaf
``HairGen_c<CC>_end``; ``_00``'s parent is ``mixamorig:Head``, every other joint's the previous one.

Ported from HairDeck (hyz317/HairDeck, revision cb20f707, hairdeck/spring/sim.py — ``clean``, ``project``,
``skin``, ``skin_blend``, ``centreline`` — and hairdeck/vrm/prep.py's per-card binding), Copyright the HairDeck
authors, Apache License 2.0 (http://www.apache.org/licenses/LICENSE-2.0); changed: the cards are the unwelded
components of the GLB mesh in first-vertex order, matched to ``cards_seed`` by centroid; each card is assigned on
its ``cards_seed`` centreline and its mesh vertices are bound against the assigned chain only (prep.py's rule,
vertex-level disagreement = rigid); ``RAMP`` is 0.15 face widths instead of 0.05 (spike Ruling H1a: 0.05 tears the
card roots by 22-26 mm under a 25 deg swing); ``project`` also returns the segment parameter; the binding is
expressed as glTF skin columns (``chain_weights``) and the joints are placed and moved with the fitted cards
(``follow``) instead of being simulated here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

#: HairDeck's face width in its head frame (``hairdeck/vis/turn_preview.py:43``): the unit of ``ASSIGN`` / ``RAMP``.
W_HEAD = 0.12759823777166274
#: A card binds to a chain whose mean distance to its lower 60 % is below ASSIGN face widths (HairDeck's value).
ASSIGN = 0.4
#: Binding weight ramp from the chain root, in face widths of arc length (spike Ruling H1a: 0.15 W = 2.9-3.1 cm).
RAMP = 0.15
#: Points per card centreline (HairDeck's ``sim.NPT``).
NPT = 16
#: A joint follows the IDW mean displacement of its FOLLOW_K nearest bound vertices (spike Ruling H1a).
FOLLOW_K = 16
#: Largest centroid offset (HairDeck head units) between a mesh card and its ``cards_seed`` entry.
CARD_MATCH_TOL = 0.001
#: The parent of every chain's first joint.
HEAD_PARENT = "mixamorig:Head"
#: Joint name prefix (``HairGen_c<CC>_<KK>`` / ``HairGen_c<CC>_end``).
JOINT_PREFIX = "HairGen_c"
#: The assignment looks at the rows from this fraction of the card on (the lower 60 %).
LOWER_FROM = 0.4
#: A joint closer than this to the previous one is a zero-length segment (HairDeck's ``clean``).
SEGMENT_EPS = 1e-6
#: IDW distance floor of ``follow``.
FOLLOW_EPS = 1e-6
#: A rest joint deeper than this inside the body is repaired (spike Ruling H1a ``SETTLE_TOL_M``; Ruling H8 keeps
#: it as the rest-depth tolerance of ``repair_depth`` — a joint within it stays where ``follow`` put it).
SETTLE_TOL_M = 0.005
#: Sampling step along a card-centroid line when ``nearest_outside`` looks for the body boundary.
REPAIR_STEP_M = 0.001
#: Bisection steps that refine a boundary crossing found by the sampling (0.001 m / 2**30 ~ 1e-12 m).
REPAIR_BISECT = 30


@dataclass
class Chain:
    """One HairDeck spring chain: ``index`` = its position in ``chains_seed``, ``joints`` (n >= 2, 3)."""
    index: int
    joints: np.ndarray
    stiffness: float


@dataclass
class Binding:
    """Per original hair vertex: ``card`` (component in first-vertex order), ``chain`` (position in the ``chains``
    list ``bind`` got, -1 = rigid), ``seg`` / ``seg2`` (segment and its blend neighbour), ``w`` (ramp weight) and
    ``alpha`` (share of ``seg``). ``kept``: the chain positions that bind at least one card, ascending.
    ``mismatch``: cards left rigid because their vertex rows disagree with the centreline assignment."""
    card: np.ndarray
    chain: np.ndarray
    seg: np.ndarray
    w: np.ndarray
    seg2: np.ndarray
    alpha: np.ndarray
    kept: List[int]
    mismatch: int = 0
    cards: int = 0


# --- the HairDeck port -----------------------------------------------------------------------------------------------

def clean(J) -> np.ndarray:
    """Joint polyline with zero-length segments removed (``sim.clean``)."""
    J = np.asarray(J, np.float64)
    keep = np.r_[True, np.linalg.norm(np.diff(J, axis=0), axis=1) > SEGMENT_EPS]
    return J[keep]


def project(P: np.ndarray, J: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Points ``P`` (m, 3) onto the polyline ``J`` (n, 3): ``(distance, segment, arc length from J[0], segment
    parameter u in [0, 1])``; the nearest segment, the first on a tie (``sim.project`` + u)."""
    P = np.asarray(P, np.float64)
    a, ab = J[:-1], np.diff(J, axis=0)
    l2 = (ab ** 2).sum(1)
    u = np.clip(((P[:, None] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
    dist = np.linalg.norm(P[:, None] - (a[None] + u[..., None] * ab[None]), axis=-1)
    k = dist.argmin(1)
    ar = np.arange(len(P))
    cum = np.r_[0, np.cumsum(np.sqrt(l2))]
    return dist[ar, k], k, cum[k] + u[ar, k] * np.sqrt(l2[k]), u[ar, k]


def centreline(seq, n: int = NPT) -> np.ndarray:
    """``n`` arc-length samples of a card's control polyline (``sim.centreline``)."""
    p = np.asarray(seq, np.float64)[:, :3]
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, p[:, k]) for k in range(3)], 1)


def _assign(rows: np.ndarray, chains: List[np.ndarray], face_width: float) -> int:
    """``sim.skin``'s card -> chain rule on ``rows`` (root first): the chain nearest to the lower 60 % when that
    mean distance is below ``ASSIGN * face_width``, else -1."""
    lo = rows[int(LOWER_FROM * len(rows)):]
    best, bd = -1, ASSIGN * face_width
    for ci, J in enumerate(chains):
        dm = project(lo, J)[0].mean()
        if dm < bd:
            best, bd = ci, dm
    return best


def _blend(k: np.ndarray, u: np.ndarray, nseg: int) -> Tuple[np.ndarray, np.ndarray]:
    """``sim.skin_blend``: on segment k at u, alpha = 0.5 + u toward k - 1 (u < 0.5) or 1.5 - u toward k + 1
    (u > 0.5); the first / last segment and u = 0.5 keep alpha 1."""
    k2, al = k.copy(), np.ones(len(k))
    lo = (u < 0.5) & (k > 0)
    hi = (u > 0.5) & (k < nseg - 1)
    k2[lo], al[lo] = k[lo] - 1, 0.5 + u[lo]
    k2[hi], al[hi] = k[hi] + 1, 1.5 - u[hi]
    return k2, al


# --- cards and chains ------------------------------------------------------------------------------------------------

def components(F: np.ndarray, n: int) -> np.ndarray:
    """The card of each of the ``n`` vertices: connected components of the UNWELDED faces ``F``, numbered in
    order of their first vertex. A vertex in no face is a card of its own."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if not n:
        return np.zeros(0, np.int64)
    A = coo_matrix((np.ones(F.size), (F.ravel(), np.roll(F, 1, 1).ravel())), shape=(n, n))
    lab = connected_components(A, directed=False)[1]
    first = np.full(lab.max() + 1, n)
    np.minimum.at(first, lab, np.arange(n))
    rank = np.empty(len(first), np.int64)
    rank[np.argsort(first)] = np.arange(len(first))
    return rank[lab]


def load_chains(chains_json: bytes) -> List[Chain]:
    """The chains of a ``chains_seed<s>.json`` with zero-length segments removed; a chain left with fewer than two
    joints is dropped (its ``index`` stays unused). ValueError for a malformed file."""
    doc = json.loads(chains_json)
    if not isinstance(doc, list):
        raise ValueError("chains file: not a list")
    out: List[Chain] = []
    for i, c in enumerate(doc):
        try:
            J = np.asarray(c["joints"], np.float64)
            stiffness = float(c["stiffness"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"chains file: chain {i} is malformed: {e}") from e
        if J.ndim != 2 or J.shape[1] != 3 or not np.isfinite(J).all() or not np.isfinite(stiffness):
            raise ValueError(f"chains file: chain {i} has no finite (n, 3) joints")
        J = clean(J) if len(J) else J
        if len(J) >= 2:
            out.append(Chain(index=i, joints=J, stiffness=stiffness))
    return out


def chain_count(chains_json: bytes) -> int:
    """The number of chains a ``chains_seed`` file lists (before ``load_chains`` drops degenerate ones)."""
    doc = json.loads(chains_json)
    return len(doc) if isinstance(doc, list) else 0


def card_centrelines(cards_json: bytes, P: np.ndarray, F: np.ndarray
                     ) -> Tuple[Optional[List[np.ndarray]], Dict[str, Any]]:
    """``(centrelines, info)``: the ``NPT``-point centreline of every ``cards_seed`` entry, in the order of the
    mesh's cards (``components``), when card k of the file is component k of the mesh — same count, centroid of
    ``seq[:, :3]`` within ``CARD_MATCH_TOL`` of the component's vertex mean. Otherwise None with ``info["match"]``
    ``"count"`` / ``"offset"`` / ``"invalid"`` (a malformed file); ``"ok"`` on a match."""
    P = np.asarray(P, np.float64)
    card = components(F, len(P))
    nc = int(card.max()) + 1 if len(card) else 0
    info: Dict[str, Any] = {"components": nc}
    try:
        doc = json.loads(cards_json)
        seqs = [np.asarray(c["seq"], np.float64) for c in doc]
    except (KeyError, TypeError, ValueError) as e:
        info.update(match="invalid", error=str(e)[:200])
        return None, info
    info["cards"] = len(seqs)
    if len(seqs) != nc:
        info["match"] = "count"
        return None, info
    if any(s.ndim != 2 or s.shape[0] < 2 or s.shape[1] < 3 or not np.isfinite(s[:, :3]).all() for s in seqs):
        info["match"] = "invalid"
        return None, info
    if not nc:
        info.update(match="ok", centroid_max=0.0)
        return [], info
    count = np.bincount(card, minlength=nc).astype(np.float64)
    cent = np.stack([np.bincount(card, weights=P[:, k], minlength=nc) for k in range(3)], 1) / count[:, None]
    cfile = np.array([s[:, :3].mean(0) for s in seqs])
    off = np.linalg.norm(cent - cfile, axis=1)
    info["centroid_max"] = round(float(off.max()), 6)
    if float(off.max()) > CARD_MATCH_TOL:
        info.update(match="offset", worst_card=int(off.argmax()))
        return None, info
    info["match"] = "ok"
    return [centreline(s) for s in seqs], info


def bind(P: np.ndarray, F: np.ndarray, centrelines: List[np.ndarray], chains: List[Chain], *,
         face_width: float = W_HEAD) -> Binding:
    """Bind every hair vertex (HairDeck head frame) to its card's chain (``sim.skin`` + ``sim.skin_blend`` per card,
    as ``prep.prep`` does it): the card is assigned on its centreline, its vertices (mesh order = root-first rows)
    are projected onto the assigned chain only; a card whose vertex rows fail that chain's lower-60 % test stays
    rigid. ValueError when ``centrelines`` does not hold one entry per card."""
    P = np.asarray(P, np.float64)
    n = len(P)
    card = components(F, n)
    nc = int(card.max()) + 1 if n else 0
    if len(centrelines) != nc:
        raise ValueError(f"bind: {len(centrelines)} centrelines for {nc} cards")
    Js = [c.joints for c in chains]
    ch = np.full(n, -1, np.int64)
    seg = np.zeros(n, np.int64)
    seg2 = np.zeros(n, np.int64)
    w = np.zeros(n)
    alpha = np.ones(n)
    mismatch = 0
    order = np.argsort(card, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(card[order])) + 1, n] if n else np.zeros(1, np.int64)
    for c in range(nc):
        a = _assign(np.asarray(centrelines[c], np.float64), Js, face_width) if Js else -1
        if a < 0:
            continue
        idx = order[starts[c]:starts[c + 1]]      # ascending vertex index: the card's root-first rows
        V = P[idx]
        if _assign(V, [Js[a]], face_width) < 0:
            mismatch += 1
            continue
        _d, k, arc, u = project(V, Js[a])
        k2, al = _blend(k, u, len(Js[a]) - 1)
        ch[idx], seg[idx], seg2[idx], alpha[idx] = a, k, k2, al
        w[idx] = np.clip(arc / (RAMP * face_width), 0.0, 1.0)
    kept = sorted(set(ch[ch >= 0].tolist()))
    return Binding(card=card, chain=ch, seg=seg, w=w, seg2=seg2, alpha=alpha, kept=kept, mismatch=mismatch,
                   cards=nc)


def card_counts(binding: Binding) -> Tuple[int, int]:
    """``(cards bound to a chain, cards rigid)``."""
    bound = int(len(np.unique(binding.card[binding.chain >= 0])))
    return bound, int(binding.cards) - bound


def bound_vertices(binding: Binding, inv: np.ndarray) -> List[np.ndarray]:
    """Per kept chain: the welded vertex indices (``inv`` = original -> welded) of the vertices bound to it."""
    inv = np.asarray(inv, np.int64)
    return [np.unique(inv[binding.chain == ci]) for ci in binding.kept]


# --- placement ---------------------------------------------------------------------------------------------------

def follow(joints: List[np.ndarray], X0: np.ndarray, X1: np.ndarray, bound: List[np.ndarray],
           k: int = FOLLOW_K) -> List[np.ndarray]:
    """Each chain's joints moved with its own cards: ``bound[i]`` = the welded vertex indices bound to chain i,
    ``X0`` -> ``X1`` their placed -> fitted positions; a joint moves by the inverse-distance mean of ``X1 - X0`` over
    its ``k`` nearest bound vertices in ``X0`` (a chain without bound vertices stays)."""
    from scipy.spatial import cKDTree
    X0 = np.asarray(X0, np.float64)
    D = np.asarray(X1, np.float64) - X0
    out = []
    for J, idx in zip(joints, bound):
        J = np.asarray(J, np.float64)
        idx = np.asarray(idx, np.int64)
        if k <= 0 or not len(idx):
            out.append(J.copy())
            continue
        kk = min(int(k), len(idx))
        d, nn = cKDTree(X0[idx]).query(J, k=kk)
        d, nn = np.asarray(d).reshape(len(J), kk), np.asarray(nn).reshape(len(J), kk)
        wt = 1.0 / np.maximum(d, FOLLOW_EPS)
        wt /= wt.sum(1, keepdims=True)
        out.append(J + (wt[..., None] * D[idx][nn]).sum(1))
    return out


# --- rest depth -----------------------------------------------------------------------------------------------------

def joint_depth(joints: List[np.ndarray], sdf) -> List[np.ndarray]:
    """Per chain the depth of each joint inside the body: ``max(0, -sdf)`` (``sdf``: negative inside, ``.sample``)."""
    return [np.maximum(-np.asarray(sdf.sample(np.asarray(J, np.float64).reshape(-1, 3)), np.float64), 0.0)
            for J in joints]


def card_centroid_line(J: np.ndarray, X: np.ndarray, idx: np.ndarray, k: int = FOLLOW_K) -> np.ndarray:
    """The chain's card-centroid line: per joint of ``J`` the mean of the ``k`` vertices ``X[idx]`` (its bound,
    fitted vertices) nearest to it — the same neighbourhood ``follow`` moves the joint with. (n, 3), or an empty
    array without bound vertices."""
    from scipy.spatial import cKDTree
    J = np.asarray(J, np.float64).reshape(-1, 3)
    idx = np.asarray(idx, np.int64)
    if not len(idx) or k <= 0:
        return np.zeros((0, 3))
    V = np.asarray(X, np.float64)[idx]
    kk = min(int(k), len(idx))
    _d, nn = cKDTree(V).query(J, k=kk)
    nn = np.asarray(nn).reshape(len(J), kk)
    return V[nn].mean(1)


def nearest_outside(p: np.ndarray, line: np.ndarray, sdf, *, step: float = REPAIR_STEP_M) -> Optional[np.ndarray]:
    """The point of the polyline ``line`` nearest to ``p`` that lies outside the body (``sdf >= 0``), None when no
    point of it does. Per segment the candidates are the projection of ``p`` (when outside), the outside end
    points and every boundary crossing found by sampling the segment at ``step`` and refining by bisection
    (``REPAIR_BISECT``, keeping the outside end, so the result always samples ``>= 0``) — the distance along a
    segment is unimodal around the projection, so the nearest outside point is one of them."""
    p = np.asarray(p, np.float64)
    L = np.asarray(line, np.float64).reshape(-1, 3)
    if not len(L):
        return None
    cands: List[np.ndarray] = []
    segs = [(L[0], L[0])] if len(L) == 1 else list(zip(L[:-1], L[1:]))
    for a, b in segs:
        ab = b - a
        ln = float(np.linalg.norm(ab))
        if ln <= SEGMENT_EPS:
            if float(sdf.sample(a[None])[0]) >= 0:
                cands.append(a.copy())
            continue
        tp = float(np.clip(np.dot(p - a, ab) / (ln * ln), 0.0, 1.0))
        t = np.unique(np.r_[np.linspace(0.0, 1.0, max(2, int(math.ceil(ln / step)) + 1)), tp])
        out = np.asarray(sdf.sample(a + t[:, None] * ab)) >= 0
        for i in np.flatnonzero(out):
            if t[i] == tp or i == 0 or i == len(t) - 1:
                cands.append(a + t[i] * ab)
        for i in np.flatnonzero(out[:-1] != out[1:]):
            lo, hi = (t[i], t[i + 1]) if out[i + 1] else (t[i + 1], t[i])   # lo inside, hi outside
            for _ in range(REPAIR_BISECT):
                mid = 0.5 * (lo + hi)
                if float(sdf.sample((a + mid * ab)[None])[0]) >= 0:
                    hi = mid
                else:
                    lo = mid
            cands.append(a + hi * ab)
    if not cands:
        return None
    C = np.array(cands)
    return C[int(np.linalg.norm(C - p, axis=1).argmin())].copy()


def repair_depth(joints: List[np.ndarray], X: np.ndarray, bound: List[np.ndarray], sdf, *,
                 tol: float = SETTLE_TOL_M, k: int = FOLLOW_K) -> Tuple[List[np.ndarray], List[int], Dict[str, Any]]:
    """``(joints, unbound, info)``: the rest depth check of the followed joints (Ruling H8). ``bound[i]`` = the
    vertex indices into ``X`` (fitted hair) bound to chain i. A joint deeper than ``tol`` inside the body moves onto
    the chain's ``card_centroid_line`` at its ``nearest_outside`` point; every other joint keeps its exact
    position. A chain is unbound (its position listed in ``unbound``, its joints returned unchanged) when a deep
    joint has no outside point on the line, or when the moved joints would leave a segment shorter than
    ``SEGMENT_EPS``. ``info``: ``moved_joints``, per chain ``depth_before`` / ``depth_after`` / ``moved`` (joint
    positions in the chain) / ``reason`` (``"unreachable"`` / ``"collapsed"`` / None)."""
    before = joint_depth(joints, sdf)
    out: List[np.ndarray] = []
    unbound: List[int] = []
    per: List[Dict[str, Any]] = []
    moved_total = 0
    for i, (J, dep, idx) in enumerate(zip(joints, before, bound)):
        J = np.asarray(J, np.float64)
        deep = np.flatnonzero(dep > tol)
        rec: Dict[str, Any] = {"depth_before": dep, "depth_after": dep, "moved": [], "reason": None}
        if not len(deep):
            out.append(J)
            per.append(rec)
            continue
        line = card_centroid_line(J, X, idx, k)
        J2 = J.copy()
        reason = None
        for j in deep:
            q = nearest_outside(J[j], line, sdf)
            if q is None:
                reason = "unreachable"
                break
            J2[j] = q
        if reason is None and (np.linalg.norm(np.diff(J2, axis=0), axis=1) <= SEGMENT_EPS).any():
            reason = "collapsed"
        if reason is not None:
            unbound.append(i)
            rec["reason"] = reason
            out.append(J)
            per.append(rec)
            continue
        rec["moved"] = deep.tolist()
        rec["depth_after"] = joint_depth([J2], sdf)[0]
        moved_total += len(deep)
        out.append(J2)
        per.append(rec)
    return out, unbound, {"moved_joints": moved_total, "chains": per}


def unbind(binding: Binding, chains: List[int]) -> Binding:
    """``binding`` with the chains at positions ``chains`` (of the list ``bind`` got) taken off: their vertices
    become rigid (chain -1, w 0, alpha 1, seg / seg2 0), ``kept`` recomputed."""
    drop = np.isin(binding.chain, np.asarray(list(chains), np.int64))
    ch, seg, seg2 = binding.chain.copy(), binding.seg.copy(), binding.seg2.copy()
    w, alpha = binding.w.copy(), binding.alpha.copy()
    ch[drop], seg[drop], seg2[drop], w[drop], alpha[drop] = -1, 0, 0, 0.0, 1.0
    kept = sorted(set(ch[ch >= 0].tolist()))
    return Binding(card=binding.card, chain=ch, seg=seg, w=w, seg2=seg2, alpha=alpha, kept=kept,
                   mismatch=binding.mismatch, cards=binding.cards)


# --- joints and skin -----------------------------------------------------------------------------------------------

def joint_names(chain: Chain) -> List[str]:
    """The chain's n - 1 segment bones ``HairGen_c<CC>_<KK>`` (bone KK sits on joint KK) plus the leaf
    ``HairGen_c<CC>_end`` on the last joint."""
    base = f"{JOINT_PREFIX}{chain.index:02d}_"
    return [f"{base}{k:02d}" for k in range(len(chain.joints) - 1)] + [f"{base}end"]


def joint_parents(chains: List[Chain]) -> Dict[str, str]:
    """Joint name -> parent name: the first joint of each chain under ``HEAD_PARENT``, every other under the
    previous joint of its chain."""
    out: Dict[str, str] = {}
    for c in chains:
        names = joint_names(c)
        out[names[0]] = HEAD_PARENT
        for prev, name in zip(names, names[1:]):
            out[name] = prev
    return out


def joint_frames(chains: List[Chain]) -> Dict[str, np.ndarray]:
    """Joint name -> its 4x4 bind world matrix: identity rotation, translation = the joint."""
    out: Dict[str, np.ndarray] = {}
    for c in chains:
        for name, p in zip(joint_names(c), np.asarray(c.joints, np.float64)):
            M = np.eye(4)
            M[:3, 3] = p
            out[name] = M
    return out


def chain_weights(names: List[str], J: np.ndarray, W: np.ndarray, binding: Binding, chains: List[Chain]
                  ) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """``hair_weights``' skin (``names``, ``J`` (n, 4), ``W`` (n, 4)) with the chain binding merged in:
    ``names`` + the joint names of every kept chain (``chains`` = the list ``bind`` got); a chain-bound vertex
    gets Head ``1 - w``, its segment bone ``w * alpha`` and the blend neighbour ``w * (1 - alpha)`` (the neighbour
    is the same bone with weight 0 where alpha is 1); a rigid vertex keeps its row."""
    from app.core.rig_contract import norm_bone_name
    head = [i for i, nm in enumerate(names) if norm_bone_name(str(nm)) == "head"]
    if not head:
        raise ValueError("chain_weights: the hair skin has no Head joint")
    out_names = list(names)
    base: Dict[int, int] = {}
    for ci in binding.kept:
        base[ci] = len(out_names)
        out_names += joint_names(chains[ci])
    J2 = np.asarray(J, np.int64).copy()
    W2 = np.asarray(W, np.float64).copy()
    on = np.flatnonzero(binding.chain >= 0)
    if len(on):
        col = np.array([base[int(c)] for c in binding.chain[on]], np.int64)
        w, al = binding.w[on], binding.alpha[on]
        J2[on] = np.column_stack([np.full(len(on), head[0]), col + binding.seg[on], col + binding.seg2[on],
                                  np.full(len(on), head[0])])
        W2[on] = np.column_stack([1.0 - w, w * al, w * (1.0 - al), np.zeros(len(on))])
    return out_names, J2, W2


def weighted_bones(names: List[str], J: np.ndarray, W: np.ndarray, chain: Chain) -> List[str]:
    """The chain's joint names that carry weight > 0 somewhere in the skin, in chain order."""
    used = {names[i] for i in np.unique(np.asarray(J)[np.asarray(W) > 0]).tolist()}
    return [nm for nm in joint_names(chain) if nm in used]
