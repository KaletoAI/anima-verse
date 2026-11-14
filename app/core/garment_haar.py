"""HAAR hair fit: strands from text onto the wearer — register, drape, clear the face, alpha cards, skin, gate
(strand-hair spec 2026-11-13 § 6.3.1 steps 1-6 and § 6.3.2). Pure numpy / scipy / Taichi on GLB bytes; reads no
file and no profile.

A port of the HAAR spike 2 (``~/claude-out/haar-spike2/src``: ``register.py``, ``drape.py`` round 3, ``cards.py``),
which the user approved after the drape ("ALLE Haare, auch die Fail sehen so gut aus"):

1. **Register** (``strand_register.register``): the template head onto the wearer's skin, the strands with it, the
   hairline on, each root snapped onto the scalp, the head part pushed out of the skull.
2. **Drape** (``drape.run`` strand mode, ``HAAR_DRAPE`` = the spike's ``drape.drape`` defaults: 1500 substeps of
   1 ms, bend compliance 1e-6, clearance ``DRAPE_CLEAR_M``, friction 0.3, damping 0.02, the push capped at 1 mm per
   substep; the early stop at rest of the HairDeck drape): stretch / bend along each strand, the long-range
   tether from the last pin, the pins of the spike's round-2 rule ``pin=scalp`` without the ear rule for face
   strands (``front_ear=0``: the root and every point within ``PIN_ARC_M`` of arc, then the leading run within
   ``PIN_BODY_M`` of the body up to ``PIN_BODY_ARC_M``), the face box as a keep-out during the drape (``eyebox=2``),
   the body grown per point from inside for the points that start inside it (HAAR's generator has no body: long
   hair runs through the shoulders), each escaping on its strand's side (``escape``: horizontal, from the head
   centre toward the root, a little backward). Then the strands' own waves (shorter than ``DETAIL_WIN_M``) are put
   back on the draped curves (``detail_transfer``, the spike's ``detail=1``).
3. **Clear the face** once more on the free points (``clear_face``: the box rule, then the body clearance, then the
   box rule again). Then the over-stretched strands are settled (``settle_stretched``, ruling H-R13): a strand with
   any segment longer than ``STRETCH_LIMIT`` x its rest length is re-sampled along its draped curve at its rest
   arc lengths (then the face box and the body clearance once more), or dropped when the draped curve is shorter
   than its rest length or that clearing stretches it again.
4. **Cards** (``hair_cards.haar_cards``): ``N_CARDS`` k-means cards of ``N_SEG`` segments on the strip atlas, the
   card colour the hairstyle's (``colour_linear``, else white), and a scalp layer under the root zone
   (``scalp_layer``, ruling H-R12: the head's skin round the registered roots, offset out, opaque, in the hair
   colour darkened by ``SCALP_SHADE``) so a parting reads as hair, not skin.
5. **Skin**: ``garment_fit.hair_weights`` (Head -> Neck -> Spine2 by height); the layer all Head; no chain joints.
6. **Gate** (``gate``, spec § 6.3.2), judged on what stays visible after the drape and the face clearing: no
   draped strand point above the chin deeper than ``INSIDE_HEAD_MM`` in the body, no card centreline across the
   eye box, the tips not clearly too short for the length class (``CLEARLY_SHORT_CM``). Everything else is
   reported in the metrics, never gated.

Calibration (``scripts/smoke_haar_gate.py`` docstring): the spike's round-3 hairs the user saw, and the live
alias's sample job, on Kira and Lirien.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core import drape, hair_cards, strand_register
from app.core.garment_fit import VOX_M, FitResult, body_sdf, hair_weights, vertex_normals
from app.core.glb_mesh import GarmentMesh, body_arrays

#: Bumped when the HAAR fit's output changes for the same inputs (the boot refit sweep refits on the CPU).
HAAR_FIT_VERSION = 2
#: Gate (spec § 6.3.2): a draped strand point above the chin deeper than this (mm) in the body refuses the seed.
INSIDE_HEAD_MM = 3.0
#: Gate: the tip p50 relative to the shoulder top (cm, + = above) above this refuses the seed as clearly too short —
#: the spike's class limits (medium <= +8, long <= -6, very long <= -20) plus a 5 cm slack; very short / short and
#: an unknown class are never refused, and hair that is too long never is.
CLEARLY_SHORT_CM: Dict[str, float] = {"medium": 13.0, "long": -1.0, "very long": -15.0}
#: The tip p50 each class aims for (cm relative to the shoulder top), for ranking passing seeds (Task 13).
CLASS_TARGET_CM: Dict[str, float] = {"very short": 20, "short": 14, "medium": 4, "long": -12, "very long": -30}

#: The drape (module docstring, step 2).
HAAR_DRAPE = drape.DrapeParams(substeps=1500, dt=1e-3, gravity=9.81, a_stretch=0.0, a_bend=1e-6, damp=0.02, mu=0.3,
                               grow=0.0, max_push=0.001, lmax=0.0, rest_vmax=0.003, rest_substeps=100)
DRAPE_CLEAR_M = 0.004
#: A point that starts inside the body starts its growth this far below its own depth.
GROW_SLACK_M = 0.001
#: The escape direction: from the head centre toward the root, horizontal, biased this far backward (m) so a crown
#: root escapes to the back.
ESCAPE_BACK_M = 0.01
#: Pins (the spike's ``pin=scalp``).
PIN_ARC_M = 0.02
PIN_BODY_M = 0.005
PIN_BODY_ARC_M = 0.04
#: The drape's body field: the registered hair's bounds ± ``FIELD_MARGIN_M``, reaching ``FIELD_DROP_M`` below the
#: lowest a tip can hang (its root's height minus its length).
FIELD_MARGIN_M = 0.06
FIELD_DROP_M = 0.02
#: Detail transfer: the waves shorter than ``DETAIL_WIN_M`` (moving average), blended in over ``DETAIL_BLEND_M``
#: after the last pin; then the body clearance (``CLEAR_ITERATIONS`` passes).
DETAIL_WIN_M = 0.08
DETAIL_BLEND_M = 0.03
CLEAR_ITERATIONS = 8
#: The face clearing: a free point leaves the box by this much beyond its face.
BOX_EXIT_M = 1e-4
#: Cards.
N_CARDS = 700
N_SEG = 16
CARD_CLEAR_M = 0.004
#: Reported cues: a tip farther than ``FLYAWAY_M`` from the body is a flyaway; a scalp-target point without a root
#: within ``BALD_M`` is uncovered; frizz is the RMS round a ``FRIZZ_WIN_M`` moving average below the ear line.
FLYAWAY_M = 0.06
BALD_M = 0.01
FRIZZ_WIN_M = 0.01
#: Card centrelines are tested against the boxes at these fractions of each segment (and at the tip).
CROSS_STEPS = (0.0, 0.25, 0.5, 0.75)
#: Settling (H-R13): a draped segment longer than this many times its rest length marks its strand as stretched.
STRETCH_LIMIT = 3.0
#: ... against its rest length floored at this (m): the registration's push out of the skull leaves rest segments of
#: a few micrometres, which any draped length would count as stretched (the ``seg_stretch_*`` metrics skip rest
#: segments under the same 1 mm).
STRETCH_REST_FLOOR_M = 0.001
#: The scalp layer (H-R12): Head triangles (all three vertices Head weight > 0.5) whose centroid has a registered
#: root within ``SCALP_REACH_M`` and whose three vertices lie no lower than ``SCALP_BELOW_M`` under the lowest of
#: those roots (so the layer bridges a parting but never paints the forehead or the nape below the hairline), minus
#: the inner wall (centroid deeper than ``VOX_M``); moved ``SCALP_OFFSET_M`` out; COLOR_0 = the hair colour x
#: ``SCALP_SHADE`` on the atlas's opaque patch, so it reads like the shaded hair round it instead of lit skin.
SCALP_REACH_M = 0.012
SCALP_BELOW_M = 0.002
SCALP_OFFSET_M = 0.0015
SCALP_SHADE = 0.6


# --- The gate ----------------------------------------------------------------------------------------------------

def _number(m: Dict[str, Any], key: str) -> Optional[float]:
    v = m.get(key)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def gate(m: Dict[str, Any], length_class: Optional[str]) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` of the HAAR gate (spec § 6.3.2) on the fit's metrics: ``inside_head_3mm`` (strands with a
    point above the chin deeper than ``INSIDE_HEAD_MM`` in the body), ``eye_cards`` (card centrelines across the eye
    box) and ``tip_p50_rel_shoulder_cm`` against ``CLEARLY_SHORT_CM[length_class]``. A missing or non-finite number
    refuses; reasons are plain English."""
    reasons: List[str] = []
    inside = _number(m, "inside_head_3mm")
    if inside is None:
        reasons.append("the depth of the hair in the head was not measured")
    elif inside > 0:
        n = int(inside)
        reasons.append(f"{n} strand{'s' if n != 1 else ''} sink{'' if n != 1 else 's'} more than "
                       f"{INSIDE_HEAD_MM:g} mm into the head")
    eye = _number(m, "eye_cards")
    if eye is None:
        reasons.append("the hair over the eyes was not measured")
    elif eye > 0:
        n = int(eye)
        reasons.append(f"{n} card{'s' if n != 1 else ''} hang{'' if n != 1 else 's'} over the eyes")
    cls = " ".join(str(length_class or "").lower().split())
    bound = CLEARLY_SHORT_CM.get(cls)
    if bound is not None:
        tip = _number(m, "tip_p50_rel_shoulder_cm")
        if tip is None:
            reasons.append("the hair length was not measured")
        elif tip > bound:
            where = f"{tip:.1f} cm above" if tip >= 0 else f"{-tip:.1f} cm below"
            limit = f"at most {bound:.1f}" if bound >= 0 else f"at least {-bound:.1f} cm below"
            reasons.append(f"too short for {cls} hair (tip {where} the shoulder, {limit})")
    return not reasons, reasons


# --- The drape ---------------------------------------------------------------------------------------------------

def _arc(X: np.ndarray) -> np.ndarray:
    return np.concatenate([np.zeros((len(X), 1)), np.cumsum(np.linalg.norm(np.diff(X, axis=1), axis=2), 1)], 1)


def pins(X0: np.ndarray, field) -> np.ndarray:
    """(S, K) bool: the spike's ``pin=scalp`` rule without the ear rule (module docstring)."""
    arc = _arc(X0)
    d = np.asarray(field.sample(X0.reshape(-1, 3))).reshape(X0.shape[:2])
    contact = np.cumprod(d <= PIN_BODY_M, axis=1).astype(bool)
    pinned = (arc <= PIN_ARC_M + 1e-9) | (contact & (arc <= PIN_BODY_ARC_M + 1e-9))
    pinned[:, 0] = True
    return np.cumprod(pinned, axis=1).astype(bool)


def drape_field(X: np.ndarray, body):
    """The body field the drape, the face clearing, the cards and the metrics read (``FIELD_MARGIN_M``,
    ``FIELD_DROP_M``)."""
    L = _arc(X)[:, -1]
    lo, hi = X.reshape(-1, 3).min(0) - FIELD_MARGIN_M, X.reshape(-1, 3).max(0) + FIELD_MARGIN_M
    lo[1] = min(lo[1], float((X[:, 0, 1] - L).min()) - FIELD_DROP_M)
    return body_sdf(np.asarray(body.positions, np.float64), np.asarray(body.faces, np.int64).reshape(-1, 3),
                    vox=VOX_M, bounds=(lo, hi))


def drape_strands(X0: np.ndarray, field, pinned: np.ndarray, hc: np.ndarray, face_box) -> Tuple[np.ndarray, Dict]:
    """The registered strands ``X0`` (S, K, 3) draped (module docstring, step 2) -> ``(X, report)``."""
    S, K, _ = X0.shape
    con = drape.strand_constraints(S, K, X0)
    d0 = np.asarray(field.sample(X0.reshape(-1, 3)))
    thr0 = np.where(d0 >= DRAPE_CLEAR_M, DRAPE_CLEAR_M, np.minimum(d0 - GROW_SLACK_M, DRAPE_CLEAR_M))
    pr = X0[:, 0] - hc
    pr[:, 1] = 0.0
    pr[:, 2] -= ESCAPE_BACK_M
    pr /= np.maximum(np.linalg.norm(pr, axis=1, keepdims=True), 1e-9)
    escape = np.repeat(pr, K, axis=0)
    res = drape.run(X0.reshape(-1, 3), np.zeros((0, 3), np.int64), X0.reshape(-1, 3), pinned.ravel(), field,
                    HAAR_DRAPE, clear=DRAPE_CLEAR_M, lra=True, con=con, components=np.repeat(np.arange(S), K),
                    keep_out=face_box, grow_from=thr0, escape=escape)
    report = dict(res.report, started_inside=int((d0 < 0).sum()))
    return res.X.reshape(S, K, 3), report


def _smooth(X: np.ndarray, win_m: float = DETAIL_WIN_M) -> np.ndarray:
    """Moving average along each strand over ~``win_m`` of arc (edge-padded)."""
    S, K, _ = X.shape
    seg = np.linalg.norm(np.diff(X, axis=1), axis=2).mean(1)
    out = np.empty_like(X)
    for i in range(S):
        w = max(3, int(round(win_m / max(seg[i], 1e-5))) | 1)
        w = min(w, (K // 2) * 2 - 1)
        h = w // 2
        P = np.concatenate([np.repeat(X[i, :1], h, 0), X[i], np.repeat(X[i, -1:], h, 0)])
        c = np.cumsum(np.concatenate([np.zeros((1, 3)), P]), 0)
        out[i] = (c[w:] - c[:-w]) / w
    return out


def _frames(C: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parallel-transport frames (T, N, B) along curves ``C`` (S, K, 3); N0 horizontal (T0 x up)."""
    T = np.gradient(C, axis=1)
    T /= np.maximum(np.linalg.norm(T, axis=2, keepdims=True), 1e-12)
    N = np.empty_like(T)
    n0 = np.cross(T[:, 0], np.array([0.0, 1.0, 0.0]))
    bad = np.linalg.norm(n0, axis=1) < 1e-6
    n0[bad] = np.cross(T[bad, 0], np.array([1.0, 0.0, 0.0]))
    n0 /= np.linalg.norm(n0, axis=1, keepdims=True)
    N[:, 0] = n0
    for k in range(1, C.shape[1]):
        n = N[:, k - 1] - (N[:, k - 1] * T[:, k]).sum(1, keepdims=True) * T[:, k]
        N[:, k] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return T, N, np.cross(T, N)


def _clearance(X: np.ndarray, movable: np.ndarray, field, clear: float) -> int:
    """Push the ``movable`` points of ``X`` (in place) to ``clear`` outside ``field`` -> how many were closer."""
    from app.core.garment_fit import _unit
    first = 0
    for it in range(CLEAR_ITERATIONS):
        d = np.asarray(field.sample(X.reshape(-1, 3))).reshape(X.shape[:2])
        m = movable & (d < clear - 1e-4)
        if it == 0:
            first = int(m.sum())
        if not m.any():
            break
        X[m] += (clear - d[m])[:, None] * _unit(np.asarray(field.grad(X[m])))
    return first


def detail_transfer(X0: np.ndarray, Xd: np.ndarray, pinned: np.ndarray, field) -> np.ndarray:
    """The registered strand's waves (its residual round a ``DETAIL_WIN_M`` moving average, in parallel-transport
    frames) put back on the draped strand, blended in over ``DETAIL_BLEND_M`` after the last pin, then the body
    clearance (the spike's ``detail_transfer``)."""
    S0, Sd = _smooth(X0), _smooth(Xd)
    T0, N0, B0 = _frames(S0)
    Td, Nd, Bd = _frames(Sd)
    r = X0 - S0
    a, b, c = (r * T0).sum(2), (r * N0).sum(2), (r * B0).sum(2)
    Xn = Sd + a[..., None] * Td + b[..., None] * Nd + c[..., None] * Bd
    arc = _arc(X0)
    last_pin = np.where(pinned, arc, 0).max(1)
    w = np.clip((arc - last_pin[:, None]) / DETAIL_BLEND_M, 0, 1)
    w = w * w * (3 - 2 * w)
    w[pinned] = 0.0
    Xo = Xd + w[..., None] * (Xn - Xd)
    _clearance(Xo, ~pinned, field, DRAPE_CLEAR_M)
    return Xo


def _box_out(X: np.ndarray, movable: np.ndarray, box) -> int:
    """The box rule on the ``movable`` points of ``X`` (in place): each inside leaves by -x, +x or +y ->
    how many moved."""
    flat = X.reshape(-1, 3)
    depth, exit_ = drape.box_depth(box, flat)
    m = movable.ravel() & (exit_ >= 0)
    idx = np.flatnonzero(m)
    for e, axis, sign in ((0, 0, -1.0), (1, 0, 1.0), (2, 1, 1.0)):
        sel = idx[exit_[idx] == e]
        flat[sel, axis] += sign * (depth[sel] + BOX_EXIT_M)
    X[...] = flat.reshape(X.shape)
    return int(m.sum())


def clear_face(X: np.ndarray, pinned: np.ndarray, field, face_box) -> Tuple[np.ndarray, Dict[str, int]]:
    """Step 3: the free points out of the face box, the body clearance, the box once more."""
    X = X.copy()
    free = ~pinned
    first = _box_out(X, free, face_box)
    pushed = _clearance(X, free, field, DRAPE_CLEAR_M)
    second = _box_out(X, free, face_box)
    return X, {"box_points": first, "clearance_points": pushed, "box_points_again": second}


def _over_limit(X: np.ndarray, seg0: np.ndarray, limit: float) -> np.ndarray:
    """(S,) bool: a segment of ``X`` longer than ``limit`` x its rest length ``seg0`` (floored at
    ``STRETCH_REST_FLOOR_M``)."""
    seg = np.linalg.norm(np.diff(X, axis=1), axis=2)
    return (seg > limit * np.maximum(seg0, STRETCH_REST_FLOOR_M)).any(1)


def settle_stretched(Xd: np.ndarray, Xrest: np.ndarray, limit: float = STRETCH_LIMIT, *,
                     pinned: Optional[np.ndarray] = None, field=None, face_box=None
                     ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Ruling H-R13 on the draped strands ``Xd`` (S, K, 3) with their rest shape ``Xrest`` -> ``(X, keep, info)``.

    A strand with any segment longer than ``limit`` x its rest length (rest floored at ``STRETCH_REST_FLOOR_M``)
    is re-sampled: its K
    points are put along its draped polyline at the rest arc lengths (root at 0), so no chord is longer than its rest
    segment and the excess length leaves at the tip. When the draped polyline is shorter than the rest length that
    is not possible, and the strand is dropped. With ``field`` and ``face_box`` (and ``pinned`` (S, K)), a re-sampled
    point slid along its strand, so those strands get ``clear_face`` once more; one that is stretched beyond
    ``limit`` again by it could not be re-sampled and is dropped too — no kept strand is stretched beyond ``limit``.
    ``X`` = the kept strands (``keep`` (S,) bool); ``info`` = ``{stretched, resampled, dropped[, face]}``."""
    X = np.array(Xd, np.float64, copy=True)
    seg0 = np.linalg.norm(np.diff(np.asarray(Xrest, np.float64), axis=1), axis=2)
    seg = np.linalg.norm(np.diff(X, axis=1), axis=2)
    over = np.flatnonzero(_over_limit(X, seg0, limit))
    keep = np.ones(len(X), bool)
    moved = np.zeros(len(X), bool)
    for s in over:
        a0 = np.r_[0.0, np.cumsum(seg0[s])]
        ad = np.r_[0.0, np.cumsum(seg[s])]
        if ad[-1] < a0[-1] - 1e-9:
            keep[s] = False
            continue
        X[s] = np.stack([np.interp(a0, ad, X[s, :, a]) for a in range(3)], 1)
        moved[s] = True
    info: Dict[str, Any] = {"stretched": int(len(over))}
    if moved.any() and field is not None and face_box is not None:
        idx = np.flatnonzero(moved)
        pin = np.zeros(X.shape[:2], bool) if pinned is None else np.asarray(pinned, bool)
        X[idx], info["face"] = clear_face(X[idx], pin[idx], field, face_box)
        again = idx[_over_limit(X[idx], seg0[idx], limit)]
        keep[again] = False
    dropped = int((~keep).sum())
    info.update(resampled=int(len(over)) - dropped, dropped=dropped)
    return X[keep], keep, info


def scalp_layer(body, head_w: np.ndarray, roots: np.ndarray, sdf
                ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
    """``(positions, faces, normals, info)`` of the scalp layer under the root zone (module constants
    ``SCALP_*``; faces index the returned positions)."""
    from scipy.spatial import cKDTree
    from app.core.garment_hairdeck import offset_patch
    P = np.asarray(body.positions, np.float64)
    F = np.asarray(body.faces, np.int64).reshape(-1, 3)
    empty = (np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros((0, 3)))
    roots = np.asarray(roots, np.float64).reshape(-1, 3)
    head = np.flatnonzero((np.asarray(head_w) > 0.5)[F].all(1))
    if not len(roots) or not len(head):
        return (*empty, {"faces": 0, "note": "no roots or no head skin"})
    cen = P[F[head]].mean(1)
    near = cKDTree(roots).query_ball_point(cen, SCALP_REACH_M)
    low = np.array([roots[n, 1].min() if n else np.inf for n in near])
    sel = P[F[head], 1].min(1) >= low - SCALP_BELOW_M
    reached = int(sel.sum())
    sel[sel] = np.asarray(sdf.sample(cen[sel])) > -VOX_M
    if not sel.any():
        return (*empty, {"faces": 0, "note": "no head skin round the roots"})
    V, Fl, N, flipped = offset_patch(P, F[head[sel]], sdf, SCALP_OFFSET_M)
    return V, Fl, N, {"faces": int(len(Fl)), "vertices": int(len(V)), "flipped_faces": flipped,
                      "inner_wall_dropped": reached - int(sel.sum()), "reach_m": SCALP_REACH_M}


# --- Metrics -----------------------------------------------------------------------------------------------------

def card_centrelines(V: np.ndarray, n_cards: int, rows: int = N_SEG + 1) -> np.ndarray:
    """(n_cards, rows, 3) centre of each card row (the mean of its two vertices)."""
    return np.asarray(V[:n_cards * rows * 2], np.float64).reshape(n_cards, rows, 2, 3).mean(2)


def cards_crossing(C: np.ndarray, box) -> int:
    """How many card centrelines ``C`` (n, rows, 3) cross ``box`` (sampled at ``CROSS_STEPS`` of each segment and
    at the tip)."""
    if not len(C):
        return 0
    pts = [C[:, :-1] + f * (C[:, 1:] - C[:, :-1]) for f in CROSS_STEPS] + [C[:, -1:]]
    P = np.concatenate(pts, 1)
    _, e = drape.box_depth(box, P.reshape(-1, 3))
    return int((e.reshape(P.shape[:2]) >= 0).any(1).sum())


def _frizz_mm(X: np.ndarray, ear: float) -> float:
    """The spike's frizz cue: per strand (200 points by arc) the RMS round its ``FRIZZ_WIN_M`` moving average below
    the ear line; the median, mm."""
    U, _ = strand_register.resample(X, 200)
    seg = np.linalg.norm(np.diff(U, axis=1), axis=2).mean(1)
    res = []
    for i in range(len(U)):
        win = max(3, int(round(FRIZZ_WIN_M / max(seg[i], 1e-4))) | 1)
        if win >= U.shape[1] // 2:
            continue
        ker = np.ones(win) / win
        sm = np.stack([np.convolve(U[i, :, a], ker, mode="valid") for a in range(3)], 1)
        h = win // 2
        r = np.linalg.norm(U[i, h:U.shape[1] - h] - sm, axis=1)
        m = U[i, h:U.shape[1] - h, 1] < ear
        if m.sum() > 5:
            res.append(np.sqrt((r[m] ** 2).mean()))
    return round(float(np.median(res)) * 1000, 3) if res else 0.0


def metrics(Xd: np.ndarray, Xreg: np.ndarray, C: np.ndarray, field, B: Dict[str, Any], frame: Dict[str, Any]
            ) -> Dict[str, Any]:
    """The gate's three numbers and the reported cues of the draped strands ``Xd`` and card centrelines ``C``."""
    from scipy.spatial import cKDTree
    d = np.asarray(field.sample(Xd.reshape(-1, 3))).reshape(Xd.shape[:2])
    above = Xd[:, :, 1] > B["chin"]
    L = _arc(Xd)[:, -1]
    L0 = _arc(Xreg)[:, -1]
    kept = L / np.maximum(L0, 1e-9)
    seg = np.linalg.norm(np.diff(Xd, axis=1), axis=2)
    seg0 = np.linalg.norm(np.diff(Xreg, axis=1), axis=2)
    stretch = (seg / np.maximum(seg0, 1e-9))[seg0 > 0.001]
    tips = Xd[:, -1]
    d_tip = np.asarray(field.sample(tips))
    rad = np.hypot(tips[:, 0] - B["cx"], tips[:, 2] - B["cz"])
    _, e_face = drape.box_depth(frame["face_box"], Xd[:, 1:].reshape(-1, 3))
    _, e_eye = drape.box_depth(frame["eye_box"], Xd[:, 1:].reshape(-1, 3))
    cover = cKDTree(Xd[:, 0]).query(strand_register.scalp_target(B))[0]
    return {
        "inside_head_3mm": int(((d < -INSIDE_HEAD_MM / 1000.0) & above).any(1).sum()),
        "eye_cards": cards_crossing(C, frame["eye_box"]),
        "tip_p50_rel_shoulder_cm": round(float(np.median(tips[:, 1]) - B["shoulder"]) * 100, 1),
        "face_cards": cards_crossing(C, frame["face_box"]),
        "cards": int(len(C)),
        "strands": int(len(Xd)),
        "inside_head_0mm": int(((d < 0) & above).any(1).sum()),
        "inside_body_3mm": int((d[:, 1:] < -INSIDE_HEAD_MM / 1000.0).any(1).sum()),
        "min_sdf_mm": round(float(d[:, 1:].min()) * 1000, 2),
        "face_strands": int((e_face.reshape(len(Xd), -1) >= 0).any(1).sum()),
        "eye_strands": int((e_eye.reshape(len(Xd), -1) >= 0).any(1).sum()),
        "seg_stretch_p99": round(float(np.percentile(stretch, 99)), 3) if len(stretch) else 1.0,
        "seg_stretch_max": round(float(stretch.max()), 3) if len(stretch) else 1.0,
        "len_kept_p5": round(float(np.percentile(kept, 5)), 4),
        "len_kept_p50": round(float(np.median(kept)), 4),
        "length_cm_p50": round(float(np.median(L)) * 100, 1),
        "flyaway_tip_share": round(float((d_tip > FLYAWAY_M).mean()), 4),
        "tip_radius_p90_over_headw": round(float(np.percentile(rad, 90) / B["head_w"]), 3),
        "scalp_uncovered_share": round(float((cover > BALD_M).mean()), 4),
        "frizz_rms_mm": _frizz_mm(Xreg, B["ear"]),
        "x_range_m": [round(float(v), 4) for v in (Xd[:, :, 0].min() - B["cx"], Xd[:, :, 0].max() - B["cx"])],
        "stretched_resampled": 0,
        "stretched_dropped": 0,
    }


# --- The fit -----------------------------------------------------------------------------------------------------

def fit_haar(strands: np.ndarray, template_head: np.ndarray, rigged_base_glb: bytes, *,
             colour_linear: Optional[Tuple[float, float, float]], length_class: Optional[str],
             template_faces: Optional[np.ndarray] = None) -> FitResult:
    """Fit HAAR ``strands`` (N, P, 3, the template head's space) onto the rigged base body (module docstring) ->
    ``FitResult``.

    ``template_head`` / ``template_faces``: the job's ``_head.obj`` (the faces drop FLAME's eyeballs);
    ``colour_linear``: the hairstyle colour (linear RGB 0..1; None = the atlas white); ``length_class``: the
    hairstyle's (``garment_hair.hair_length_class``) for the gate. The garment is the cards plus the scalp layer as
    ONE primitive in the rigged bind space: the strip atlas as base colour (``hair_cards.strip_atlas``), each card's
    UVs in its variant's column and the scalp layer (``scalp_layer``) on the opaque patch, ``COLOR_0`` = the colour
    on the cards and the colour x ``SCALP_SHADE`` on the layer (alpha 1), Head -> Neck -> Spine2 weights
    (``hair_weights``; the layer all Head), double-sided, no chain joints. ``report.vertices`` =
    ``{hair, cap}`` (the cards first, ``hair_strands.haar_layout``), ``report.layout`` = ``"haar"``. ValueError for a
    base without a skin or strands that make no card."""
    from app.core import hair_strands
    t_all = time.time()
    body = body_arrays(rigged_base_glb)
    if not body.joint_names:
        raise ValueError("The rigged base has no skin")
    B = strand_register.body_frame(body)
    frame = hair_strands.head_frame(body)
    Xreg, reg = strand_register.register(strands, template_head, body, hairline=True, template_faces=template_faces,
                                         frame=B)
    t0 = time.time()
    field = drape_field(Xreg, body)
    pinned = pins(Xreg, field)
    t_field = time.time() - t0
    t0 = time.time()
    Xd, drape_report = drape_strands(Xreg, field, pinned, B["hc"], frame["face_box"])
    Xd = detail_transfer(Xreg, Xd, pinned, field)
    Xd, face = clear_face(Xd, pinned, field, frame["face_box"])
    Xd, keep, settle = settle_stretched(Xd, Xreg, pinned=pinned, field=field, face_box=frame["face_box"])
    if not keep.any():
        raise ValueError("Every HAAR strand was stretched beyond repair by the drape")
    t_drape = time.time() - t0
    t0 = time.time()
    V, Fh, UV, card = hair_cards.haar_cards(Xd, field, n_cards=N_CARDS, n_seg=N_SEG, clear=CARD_CLEAR_M, seed=0,
                                            centre=B["hc"])
    n_cards = int(card.max()) + 1
    C = card_centrelines(V, n_cards)
    t_cards = time.time() - t0
    m = metrics(Xd, Xreg[keep], C, field, B, frame)
    m.update({"stretched_resampled": settle["resampled"], "stretched_dropped": settle["dropped"],
              "icp_scale": reg["scale"], "icp_resid_p95_m": reg["icp_resid_p95_m"],
              "root_resid_p95_m": reg["root_resid_p95_m"], "hairline_tilt_deg": reg["hairline_tilt_deg"]})
    ok, reasons = gate(m, length_class)

    # the scalp layer under the root zone (every registered root, a dropped strand's too)
    Vc, Fc, Nc, cap_info = scalp_layer(body, B["head_w_col"], Xreg[:, 0], B["sdf"])
    nc = len(Vc)
    names, J, W = hair_weights(V, body)
    Jc = np.zeros((nc, 4), np.int64)
    Jc[:, 1] = 1
    Wc = np.zeros((nc, 4))
    Wc[:, 0] = 1.0
    rgb = np.clip(np.asarray(colour_linear if colour_linear is not None else (1.0, 1.0, 1.0), np.float64), 0, 1)
    colour = np.r_[rgb, 1.0]
    shade = np.r_[rgb * SCALP_SHADE, 1.0]
    n_hair = len(V)
    garment = GarmentMesh(positions=np.vstack([V, Vc]), normals=np.vstack([vertex_normals(V, Fh), Nc]),
                          uvs=np.vstack([UV, np.tile(hair_cards.SOLID_UV, (nc, 1))]),
                          indices=np.vstack([Fh, np.asarray(Fc, np.int64) + n_hair]), joints=np.vstack([J, Jc]),
                          weights=np.vstack([W, Wc]), joint_names=list(names), image=hair_cards.strip_atlas(),
                          mime="image/png", material={"name": "hair", "doubleSided": True},
                          colors=np.vstack([np.tile(colour, (n_hair, 1)), np.tile(shade, (nc, 1))]))
    report = {
        "layout": "haar",
        "fit_version": HAAR_FIT_VERSION,
        "vertices": {"hair": int(n_hair), "cap": int(nc)},
        "length_class": length_class,
        "colour_linear": [round(float(v), 4) for v in rgb] if colour_linear is not None else None,
        "frame": {"chin_y": round(B["chin"], 5), "top_y": round(B["top"], 5), "ear_y": round(B["ear"], 5),
                  "shoulder_y": round(B["shoulder"], 5), "landmarks": B["landmark_source"],
                  "face_box": [round(float(v), 5) for v in frame["face_box"]],
                  "eye_box": [round(float(v), 5) for v in frame["eye_box"]]},
        "register": reg,
        "drape": dict(drape_report, pinned_points=int(pinned.sum()), field_dims=list(np.asarray(field.field).shape),
                      substeps=HAAR_DRAPE.substeps),
        "face": face,
        "settle": settle,
        "cards": {"cards": n_cards, "segments": N_SEG, "vertices": int(n_hair), "faces": int(len(Fh))},
        "cap": cap_info,
        "weights": {"joints": list(names), "all_head": int((W[:, 0] == 1).sum()),
                    "blended": int(((W[:, 0] < 1) & (W[:, 0] > 0)).sum())},
        "timing_s": {"register": reg["t_s"], "field": round(t_field, 2), "drape": round(t_drape, 2),
                     "cards": round(t_cards, 2), "total": round(time.time() - t_all, 2)},
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)


__all__ = ["HAAR_FIT_VERSION", "INSIDE_HEAD_MM", "CLEARLY_SHORT_CM", "CLASS_TARGET_CM", "STRETCH_LIMIT", "SCALP_SHADE",
           "gate", "settle_stretched", "scalp_layer", "fit_haar"]
