"""The cut of HAAR hair cards (Ruling A71): clean strand ends by default, and the user's own cut.

Why (A71 diagnosis, Anima Divide's six HAAR fits, ``.superpowers/sdd/2026-11-13-strand-hair/a71-report.md``): the
"very fine threads at the ends" were the strip atlas's tail and a wrapped texel row, not the geometry —

- every card mapped the WHOLE strip (``hair_cards._atlas_rgba``: v 1 at the root .. 0 at the tip), whose strand
  lines end staggered at 80-100 % of its length, thinning to a quarter width over their last quarter: past
  ``S_BODY`` the strip's cover falls from 0.41 (0.56 on its body) to 0 at ``S_END`` (cutoff 0.15), so the last
  ~20 % of every card (6-12 cm on a 57 cm card) showed a comb of a few lines 0.04-0.1 mm wide;
- the tip row sampled v = 0 under the glTF default REPEAT wrap: half of every tip texel came from the strip's ROOT
  row, so 51-79 % of the tip row's width passed the cutoff (worse with each mip level) — a thin horizontal dash at
  every card's end, below the visible hair.

The cards' own width stays 4.2 mm and more at the tip, and the card lengths have no outliers in the long styles
(max / p90 1.15-1.21); a short style had three stray cards up to 2.03 x its p90.

THE RULE (``cut_cards``; ONE port for the Hairstyles tab's live preview: ``frontend/src/tabs/characters/hairCut.ts``,
held together by ``scripts/smoke_hair_cut_parity.py``). Per card of ``R`` rows of two rail vertices (left, right),
root first, the centreline the mean of the two (``hair_strands.haar_layout``), its arc ``a`` and length ``L``:

1. ``keep = min(L, CLAMP_P90 x p90(L of all cards), max_cm / 100, a(at))`` — the outlier clamp, the user's length,
   the user's height (``a(at)``: the arc where the centreline first drops below the landmark's height, linear in
   its segment; 0 when the root lies below it); then at least ``min(L, MIN_KEEP_M)``.
2. ``E = min(ends_cm / 100 (Auto: ENDS_AUTO_M), ENDS_MAX_FRAC x keep)`` — the soft tip.
3. Rows ``0 .. R-2`` sit at arc ``(keep - E) r / (R - 2)``, the last at ``keep``; each rail vertex is its rail's
   linear interpolation at that arc of the centreline (a zero-length segment takes its first row).
4. ``v = 1 - S_BODY r / (R - 2)`` on rows ``0 .. R-2`` and ``1 - S_END`` on the last: the strip's dense body runs
   over the card up to its soft tip, the strip's thinning tail (``S_BODY`` .. ``S_END``) is squeezed into the last
   ``E`` (3 cm by default: 1.5 cm read as a blunt block edge, 4 cm began to show single threads again — renders in
   the A71 report), and nothing past ``S_END`` (where no line passes any cutoff in ``hair_cards.CUTOFF_LIMITS`` above 0.05) and
   never v = 0 (the wrap) reaches a card.

Pure numpy, float64 on the float32-rounded rails (what the GLB stores and what the preview gets), so the server and
the preview compute the same numbers. No push-out afterwards: every vertex lies on its rail between two rows the
cards' push already put outside the body.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

#: Bumped when the rule's output changes for the same inputs (``garment_haar.HAAR_FIT_VERSION`` follows it).
CUT_VERSION = 1
#: The strip (``hair_cards`` atlas, s 0 at the root .. 1 at the tip) mapped onto the card body / its last row.
S_BODY = 0.75
S_END = 0.95
#: The soft tip by default (m) and its share of the kept length at most.
ENDS_AUTO_M = 0.03
ENDS_MAX_FRAC = 0.25
#: A card longer than this x the p90 of the style's card lengths is cut to it.
CLAMP_P90 = 1.5
#: No cut leaves a card shorter than this (m) — or its own length when it is shorter.
MIN_KEEP_M = 0.03
#: The user's setting (the hairstyle's ``hair_cut``): its keys and limits.
MAX_CM_LIMITS: Tuple[float, float] = (3.0, 150.0)
ENDS_CM_LIMITS: Tuple[float, float] = (0.5, 12.0)
#: The heights "Ends at" offers, top down (``landmarks``).
LANDMARKS: Tuple[str, ...] = ("chin", "shoulder", "shoulder_blades", "mid_back", "waist")
#: ``landmarks``: the joint whose bind height a landmark is (``glb_mesh.BodyMesh.joint_positions`` keys).
LANDMARK_JOINTS: Dict[str, str] = {"shoulder_blades": "spine2", "mid_back": "spine1", "waist": "spine"}


def normalise(value: Any) -> Dict[str, Any]:
    """The hairstyle's ``hair_cut`` setting as stored: ``{max_cm?, at?, ends_cm?}`` with only the keys that are set
    (``{}`` = everything automatic: the whole length, Auto ends). ``max_cm`` and ``at`` exclude each other; numbers
    rounded to 0.1 cm. ValueError for anything else (an unknown key, a value beyond its limits, both lengths)."""
    if value is None or value == "":
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("hair_cut must be an object")
    unknown = sorted(set(value) - {"max_cm", "at", "ends_cm"})
    if unknown:
        raise ValueError(f"no hair_cut key: {', '.join(unknown)}")
    out: Dict[str, Any] = {}
    for key, limits in (("max_cm", MAX_CM_LIMITS), ("ends_cm", ENDS_CM_LIMITS)):
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, bool):
            raise ValueError(f"{key} must be a number")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number") from None
        if not math.isfinite(number) or not limits[0] <= number <= limits[1]:
            raise ValueError(f"{key} must lie between {limits[0]:g} and {limits[1]:g} cm")
        out[key] = round(number, 1)
    at = value.get("at")
    if at not in (None, ""):
        if at not in LANDMARKS:
            raise ValueError(f"at must be one of {', '.join(LANDMARKS)}")
        out["at"] = str(at)
    if "max_cm" in out and "at" in out:
        raise ValueError("hair_cut takes a length (max_cm) or a height (at), not both")
    return {k: out[k] for k in ("max_cm", "at", "ends_cm") if k in out}


def landmarks(body, frame: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """The heights (m, bind space) of ``LANDMARKS`` on a rigged body (``glb_mesh.BodyMesh``): chin and shoulder top
    (``garment_fit.chin_height`` / ``shoulder_top_height``, or ``frame`` = ``strand_register.body_frame``'s), the
    rest the bind heights of ``LANDMARK_JOINTS``; a joint the skin lacks leaves its landmark out."""
    from app.core import garment_fit as gf
    out: Dict[str, float] = {}
    out["chin"] = float(frame["chin"]) if frame else float(gf.chin_height(body))
    out["shoulder"] = float(frame["shoulder"]) if frame else float(gf.shoulder_top_height(body))
    joints = getattr(body, "joint_positions", None) or {}
    for name, joint in LANDMARK_JOINTS.items():
        if joint in joints:
            out[name] = float(np.asarray(joints[joint], np.float64)[1])
    return {k: round(out[k], 6) for k in LANDMARKS if k in out}


def percentile90(values: np.ndarray) -> float:
    """numpy's linear percentile 90 (``h = 0.9 (n - 1)``, between the two sorted values round it), spelled out so
    the preview's port computes the same."""
    x = np.sort(np.asarray(values, np.float64))
    if not len(x):
        return 0.0
    h = 0.9 * (len(x) - 1)
    lo = int(math.floor(h))
    hi = min(lo + 1, len(x) - 1)
    return float(x[lo] + (h - lo) * (x[hi] - x[lo]))


def _arc(C: np.ndarray) -> np.ndarray:
    """(R,) arc from the root along the centreline ``C`` (R, 3), summed row by row."""
    a = np.zeros(len(C))
    for i in range(1, len(C)):
        d = C[i] - C[i - 1]
        a[i] = a[i - 1] + math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    return a


def _height_arc(C: np.ndarray, a: np.ndarray, y: float) -> float:
    """The arc where the centreline first drops below height ``y`` (0 when its root does), +inf when it never does."""
    if C[0, 1] < y:
        return 0.0
    for i in range(1, len(C)):
        if C[i, 1] < y:
            dy = C[i - 1, 1] - C[i, 1]
            t = (C[i - 1, 1] - y) / dy if dy > 0 else 0.0
            return float(a[i - 1] + t * (a[i] - a[i - 1]))
    return math.inf


def _at_arc(V: np.ndarray, a: np.ndarray, t: float) -> np.ndarray:
    """The rail vertices ``V`` (R, 2, 3) interpolated at centreline arc ``t`` (``a`` (R,) the rows' arcs)."""
    R = len(a)
    i = 0
    while i < R - 2 and a[i + 1] < t:
        i += 1
    span = a[i + 1] - a[i]
    f = (t - a[i]) / span if span > 0 else 0.0
    f = min(max(f, 0.0), 1.0)
    return V[i] + f * (V[i + 1] - V[i])


def cut_cards(V: np.ndarray, cut: Optional[Mapping[str, Any]] = None,
              heights: Optional[Mapping[str, float]] = None) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """The rule (module docstring) on the rails ``V`` (K, R, 2, 3) -> ``(V', v, info)``: ``V'`` the cut rails, ``v``
    (K, R) every row's glTF v, ``info`` ``{keep_m (K,), length_m (K,), clamp_m, clamped, shortened, ends_m (K,)}``.
    ``cut`` = ``normalise``d (None = ``{}``); ``heights`` = ``landmarks`` (an ``at`` it lacks cuts nothing)."""
    V = np.asarray(V, np.float64)
    if V.ndim != 4 or V.shape[2:] != (2, 3) or V.shape[1] < 3:
        raise ValueError(f"cut_cards: rails of shape {V.shape}")
    cut = normalise(cut)
    K, R = V.shape[:2]
    C = 0.5 * (V[:, :, 0] + V[:, :, 1])
    arcs = [_arc(C[k]) for k in range(K)]
    L = np.array([a[-1] for a in arcs])
    clamp = CLAMP_P90 * percentile90(L)
    user = cut["max_cm"] / 100.0 if "max_cm" in cut else math.inf
    y_at = (heights or {}).get(cut["at"]) if "at" in cut else None
    ends = cut["ends_cm"] / 100.0 if "ends_cm" in cut else ENDS_AUTO_M
    out = np.empty_like(V)
    v = np.empty((K, R))
    keep = np.empty(K)
    tip = np.empty(K)
    clamped = shortened = 0
    body = R - 2
    for k in range(K):
        a = arcs[k]
        length = float(a[-1])
        at = _height_arc(C[k], a, float(y_at)) if y_at is not None else math.inf
        kk = min(length, clamp, user, at)
        if clamp < length and clamp <= min(user, at):
            clamped += 1
        kk = max(kk, min(length, MIN_KEEP_M))
        if kk < length:
            shortened += 1
        e = min(ends, ENDS_MAX_FRAC * kk)
        for r in range(R):
            t = (kk - e) * r / body if r <= body else kk
            out[k, r] = _at_arc(V[k], a, t)
            v[k, r] = 1.0 - (S_BODY * r / body if r <= body else S_END)
        keep[k], tip[k] = kk, e
    return out, v, {"keep_m": keep, "length_m": L, "clamp_m": clamp, "clamped": clamped, "shortened": shortened,
                    "ends_m": tip}


__all__ = ["CUT_VERSION", "S_BODY", "S_END", "ENDS_AUTO_M", "ENDS_MAX_FRAC", "CLAMP_P90", "MIN_KEEP_M",
           "MAX_CM_LIMITS", "ENDS_CM_LIMITS", "LANDMARKS", "normalise", "landmarks", "percentile90", "cut_cards"]
