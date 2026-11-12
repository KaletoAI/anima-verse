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
