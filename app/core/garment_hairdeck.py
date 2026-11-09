"""HairDeck hair fit: place a HairDeck hair-card mesh on the rigged base body, push it out of the body, correct its
vertex colours and add a scalp cap — pure numpy/scipy on GLB bytes (plan 2026-11-09-hairdeck-hair, Task 3).

A port of the HairDeck fit spike (``~/claude-out/hairdeck/fit/src/fit.py``, user-approved). HairDeck delivers one
character image as hair cards (node ``hair_cards``, ``COLOR_0`` linear, double-sided) plus a ``head_proxy`` sphere
in the same space (the "with head" result file). Facts the code relies on:

- Proxy and body face the same way (+z, yaw 0) and HairDeck's space is uniform: placement is scale + translation.
- The proxy is matched to the CRANIUM, the part of the head the hair rests on: rigged vertices with Head weight
  > 0.5 above ``chin + 0.6 * (top - chin)``. A skin-weight criterion, so an unskinned stray mesh in the body GLB
  (all weights 0) never enters it.
- Cards are separate pieces: no component is dropped and there is no largest-component gate.
- Everything is in the rigged body's metres (k = 1); the push-out uses the garment-fit SDF and spread constants.
- The head match alone leaves the hair too far back (user test 2026-11-09): a placement correction follows it —
  a forward shift and a forward tilt, per character or automatic ("hairline to the brow line", ``_place_and_push``).

Colour: HairDeck samples its vertex colours from the character image itself. A manual override (``colour_target``,
sRGB) maps their median there by a per-channel gain; without one, the profile's NAMED hair colour
(``colour_profile``, e.g. "brunette") is transferred in CIELAB (``_transfer_colours``: the median moves onto the
named colour, every vertex keeps its offset from the median, so the strand shading stays) when HairDeck's median is
more than ``AUTO_RECOLOUR_MIN_DE`` away from it (Kai 2026-11-09: HairDeck's near-black cards, ΔE 17 from
"brunette"). Both are decided by the caller — ``fit_hairdeck`` reads no file and no profile. (A plan-time sampler of
the hair colour from the profile picture was dropped after the spike renders: its skin reference landed on the
shadowed neck in HairDeck's long-hair box and it turned blond hair pink.)

Length class: short hair lies on the scalp, so nearly all of it is pushed out — the ``moved_share`` gate depends on
the hair's length class (``gates_for``).
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.garment_fit import (MOVED_EPS_M, SDF_MARGIN_M, SPREAD_DEPTH_M, SPREAD_M, VOX_M, FitResult, body_sdf,
                                  chin_height, dense_weights, gate as _gate_against, hair_weights, joint_index,
                                  push_out, vertex_normals, weld)
from app.core.glb_mesh import GarmentMesh, body_arrays, card_arrays

# Clearance of a card from the body surface (the spike's 0.004 m; cards are thin, unlike a generated hair shell).
CARD_CLEAR_M = 0.004
# Cranium = Head-weighted vertices above chin + CRANIUM_FROM * (top - chin).
CRANIUM_FROM = 0.6
ICP_ITERATIONS = 30
# Neighbours of the PCA normals the point-to-plane ICP measures along.
PCA_NORMAL_K = 12
# Scalp cap: body triangles within CAP_REACH_M of a hair vertex, offset CAP_OFFSET_M along the outward normal.
CAP_OFFSET_M = 0.0015
CAP_REACH_M = 0.03
# A cap triangle whose centroid lies deeper than this inside the body solid belongs to an inner wall (the generator
# body is double-walled: on the spike's head 43 % of the candidate triangles sat ~4.5 mm inside) and is dropped.
CAP_INNER_DEPTH_M = VOX_M
# Front hairline region: z > head centre z + 0.25 * head depth and |x - head cx| < 0.15 * head width. The plan said
# 0.3 * width (+-5.1 cm on the spike's head): that strip reaches the face-framing strands, whose tips hang at eye
# level (x +-4.5..5.6 cm, y 1.572), and the cap then covered forehead and temples (seen in the render, and 52 cap
# triangles below that hairline). The centre strip (+-2.5 cm) finds the forehead hairline at the parting (1.645).
HAIRLINE_FRONT_DEPTH = 0.25
HAIRLINE_HALF_WIDTH = 0.15
CAP_COLOUR_PERCENTILE = 20

# Placement correction (user test 2026-11-09, finding 5). The proxy is a near-sphere, the cranium is longer (Kira:
# depth 0.20 m, width 0.17 m) and its back dominates the ICP point set, so the placed proxy sits ~1.2 cm to the back
# and its front lands ~6 mm behind the forehead: the hairline rides 3.5 cm above the brow ridge (a long forehead).
# After ``place_proxy`` the hair is pitched forward about the x axis through the placed proxy centre and moved
# forward along +z; both are per-character inputs (profile ``hair_forward_m`` / ``hair_tilt_deg``, None = auto).
#: Forward shift when the character sets none: the measured gap between the proxy front and the forehead.
DEFAULT_FORWARD_M = 0.006
#: Auto tilt: the front hairline goes to brow + HAIRLINE_BROW_RATIO * (crown - brow) (Kira today: 0.39).
HAIRLINE_BROW_RATIO = 0.25
#: The auto tilt is searched in [0, AUTO_TILT_MAX_DEG]: it only LOWERS a hairline that sits too high (the
#: systematic error above). A hairline already at or below the target (bangs) keeps tilt 0 — tilting it back
#: would lift the bangs off the brows.
AUTO_TILT_MAX_DEG = 15.0
AUTO_TILT_TOL_DEG = 0.01
#: The auto tilt aims at the PUSHED hairline: at most this many push-outs, done within HAIRLINE_TOL_M.
PLACEMENT_ROUNDS = 4
HAIRLINE_TOL_M = 0.001
#: Step of the auto tilts tried when the hairline tilt fails the push gate (``_place_and_push``).
GATE_TILT_STEP_DEG = 1.5
#: Bounds of the manual values (the Hair tab's inputs; ``garment_hair.set_hair_placement``).
TILT_LIMIT_DEG = 15.0
FORWARD_LIMIT_M = 0.03
#: Head centre profile for the landmarks: Head-weighted body vertices with |x - head cx| below this, in y bins.
PROFILE_HALF_WIDTH_M = 0.02
PROFILE_BIN_M = 0.005
#: A nose tip stands out of the nasion below the brow, and the brow out of the nasion, by at least this much.
LANDMARK_MIN_DIP_M = 0.003
#: A nose tip lies in the front of the head: front z >= cz + LANDMARK_NOSE_FRONT * depth (the front 20 %). Keeps a
#: chin/neck junction from passing for a face (on the smoke's sphere head the neck ring at z 0.04 dips into the
#: sphere's south pole).
LANDMARK_NOSE_FRONT = 0.3
#: Plausible landmarks on a base head (the rigged body's metres): the brow lies BROW_CROWN_MIN_M..BROW_CROWN_MAX_M
#: below the crown and above the eye line, the nose tip below it; eye line = chin + EYE_LINE_RATIO * (crown - chin)
#: (canon: the eyes halve the head). Kira (bases base233fdd2a / base20d5701a): brow 9.3-9.4 cm below the crown,
#: brow at 0.61-0.63 and nose at 0.21-0.25 of chin..crown. Kai (base634402e5, beard modelled: chin 1.581, crown
#: 1.860) reads as nose 1.613 (lower lip), brow 1.684 (the nose tip): 17.6 cm below the crown, under the eye line
#: 1.720 — the auto tilt then pulled the hairline 2-3 cm below his real brow (~1.743).
BROW_CROWN_MIN_M = 0.08
BROW_CROWN_MAX_M = 0.13
EYE_LINE_RATIO = 0.5
#: Fallback of an implausible profile reading ("proportions"): brow at chin + FALLBACK_BROW_RATIO * (crown - chin)
#: (Kira's profile 0.61-0.63, Kai's real brow ~0.58), the hairline floor (the nasion's role) at
#: chin + FALLBACK_FLOOR_RATIO * (crown - chin) (Kira's nasion 0.33-0.37).
FALLBACK_BROW_RATIO = 0.6
FALLBACK_FLOOR_RATIO = 0.4

GATES = {
    "max_push_m": ("max", 0.12, "largest push-out"),
    "moved_share": ("max", 0.90, "share of vertices moved by the push-out"),
    "icp_resid_p95_m": ("max", 0.012, "95th percentile of the proxy-to-cranium distance"),
}
#: ``moved_share`` limit per hair length class (``garment_hair.hair_length_class``); other classes and an unknown
#: one keep ``GATES``' 0.90. Hair that hangs free of the head is mostly not pushed (Kira, medium: 0.65-0.69 over
#: five fits). Short hair lies on the scalp, so nearly all of it is pushed — the share measures no defect there
#: (Kai, short: 0.870 / 0.912 / 0.930, ICP residual p95 7 mm — good placements, two refused at 0.90): 0.97 keeps
#: a margin above Kai and still refuses hair that was pushed out entirely (a sunk shell, 1.0). Very short hair is
#: all scalp: not gated (1.0).
MOVED_SHARE_BY_CLASS = {"very short": 1.0, "short": 0.97}


def gates_for(length_class: Optional[str] = None) -> Dict[str, Tuple[str, float, str]]:
    """The HairDeck gates for a hair length class: ``GATES`` with the class's ``moved_share`` limit."""
    limit = MOVED_SHARE_BY_CLASS.get(str(length_class or "").strip().lower())
    if limit is None:
        return GATES
    kind, _limit, label = GATES["moved_share"]
    return {**GATES, "moved_share": (kind, limit, f"{label}, {length_class} hair")}


def gate(m: Dict[str, Any], length_class: Optional[str] = None) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` against the HairDeck gates of ``length_class`` (``gates_for``); a missing or non-finite
    number refuses."""
    return _gate_against(m, gates_for(length_class))


# --- colour --------------------------------------------------------------------------------------------------------

def srgb_to_linear(c) -> np.ndarray:
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _correct_colours(C: np.ndarray, colour_target) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Per-channel linear gain mapping the median of ``C`` to the sRGB ``colour_target``, clamped to 1."""
    C = np.asarray(C, np.float64).copy()
    median = np.median(C[:, :3], 0)
    info: Dict[str, Any] = {"median_before_linear": [round(float(v), 4) for v in median]}
    if colour_target is None:
        return C, info
    target = np.asarray(colour_target, np.float64).ravel()
    if target.shape != (3,) or not np.isfinite(target).all() or (target < 0).any() or (target > 1).any():
        raise ValueError(f"The hair colour target must be three sRGB values in 0..1, got {colour_target!r}")
    lin = srgb_to_linear(target)
    gain = lin / np.maximum(median, 1e-6)
    C[:, :3] = np.minimum(C[:, :3] * gain, 1.0)
    target_lab = linear_to_lab(lin)
    info.update({"method": "gain", "target_linear": [round(float(v), 4) for v in lin],
                 "gain": [round(float(v), 4) for v in gain],
                 "median_after_linear": [round(float(v), 4) for v in np.median(C[:, :3], 0)],
                 "delta_e_before": round(delta_e(linear_to_lab(median), target_lab), 2),
                 "delta_e_after": round(delta_e(linear_to_lab(np.median(C[:, :3], 0)), target_lab), 2)})
    return C, info


#: sRGB (D65) linear -> XYZ, and the D65 white the Lab conversion divides by.
_RGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])
_D65 = np.array([0.95047, 1.0, 1.08883])
_LAB_EPS = (6 / 29) ** 3
#: The profile colour is transferred only when HairDeck's median is further than this (CIE76 ΔE) from it: within
#: it the image-sampled colour already reads as the named one and keeps its own nuance.
AUTO_RECOLOUR_MIN_DE = 5.0


def linear_to_lab(lin) -> np.ndarray:
    """Linear sRGB (..., 3) -> CIELAB (D65)."""
    xyz = np.asarray(lin, np.float64) @ _RGB_TO_XYZ.T / _D65
    f = np.where(xyz > _LAB_EPS, np.cbrt(np.maximum(xyz, 0.0)), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_linear(lab) -> np.ndarray:
    """CIELAB (D65) (..., 3) -> linear sRGB, clipped to 0..1 (the gamut)."""
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _D65
    return np.clip(xyz @ np.linalg.inv(_RGB_TO_XYZ).T, 0.0, 1.0)


def delta_e(lab_a, lab_b) -> float:
    """CIE76 colour difference."""
    return float(np.linalg.norm(np.asarray(lab_a, np.float64) - np.asarray(lab_b, np.float64)))


def _transfer_colours(C: np.ndarray, colour_profile) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Recolour the hair to the profile's named colour ``colour_profile`` (sRGB 0..1) in CIELAB: every vertex
    colour moves by (target - median), so the median lands on the named colour and each vertex keeps its offset
    from it — the lightness detail (strand shading, darker roots) and the relative hue spread stay. Skipped
    (``applied`` False) when HairDeck's median lies within ``AUTO_RECOLOUR_MIN_DE`` of it. Reports the CIE76 ΔE
    of the median to the target before and after (after > 0 only where the gamut clips)."""
    C = np.asarray(C, np.float64).copy()
    target = np.asarray(colour_profile, np.float64).ravel()
    if target.shape != (3,) or not np.isfinite(target).all() or (target < 0).any() or (target > 1).any():
        raise ValueError(f"The profile hair colour must be three sRGB values in 0..1, got {colour_profile!r}")
    target_lab = linear_to_lab(srgb_to_linear(target))
    lab = linear_to_lab(C[:, :3])
    median = np.median(lab, 0)
    before = delta_e(median, target_lab)
    info: Dict[str, Any] = {"method": "lab_transfer", "target_lab": [round(float(v), 2) for v in target_lab],
                            "median_lab_before": [round(float(v), 2) for v in median],
                            "delta_e_before": round(before, 2), "min_delta_e": AUTO_RECOLOUR_MIN_DE}
    if before <= AUTO_RECOLOUR_MIN_DE:
        return C, {**info, "applied": False, "delta_e_after": round(before, 2)}
    C[:, :3] = lab_to_linear(lab - median + target_lab)
    after_median = np.median(linear_to_lab(C[:, :3]), 0)
    return C, {**info, "applied": True, "median_lab_after": [round(float(v), 2) for v in after_median],
               "delta_e_after": round(delta_e(after_median, target_lab), 2)}


# --- placement -----------------------------------------------------------------------------------------------------

def _pca_normals(X: np.ndarray, k: int = PCA_NORMAL_K) -> np.ndarray:
    """Unsigned surface normals of a point set: the least-variance axis of each point's ``k`` nearest neighbours.
    No winding is read (the generator body's is not trusted); point-to-plane residuals are squared, so the sign
    does not matter."""
    from scipy.spatial import cKDTree
    _, nn = cKDTree(X).query(X, k=min(k, len(X)))
    Y = X[nn] - X[nn].mean(1, keepdims=True)
    _, vectors = np.linalg.eigh(np.einsum("nki,nkj->nij", Y, Y))
    return vectors[:, :, 0]


def place_proxy(proxy: np.ndarray, cranium: np.ndarray, *, iterations: int = ICP_ITERATIONS
                ) -> Tuple[float, np.ndarray, Dict[str, Any]]:
    """Scale + translation ``(s, t)`` with ``s * proxy + t`` on the cranium (yaw 0).

    Start: the bounding-box match of the proxy's upper half (vertices above the proxy's bbox centre y) and the
    cranium (s = mean of the three extent ratios, bbox centres aligned). Each ICP iteration pairs every upper-half
    point with its nearest cranium point and every cranium point with its nearest point of the WHOLE proxy (the
    spike's symmetric pairing: the cranium's lower rim may find the proxy's equator), then solves s and t in closed
    form, POINT-TO-PLANE (residual along the partner's normal). Point-to-point, as in the spike, is biased by how
    the two surfaces are sampled: on a sphere sampled 60 x 128 against 61 x 120 it settled 1.8 % large; point-to-
    plane lands within 0.1 % for every sampling tried, and on the spike's real files within 0.2 % of the spike.
    Residual = distance of each mapped upper-half point to its nearest cranium point (the spike's measure).
    """
    from scipy.spatial import cKDTree
    centre = (proxy.min(0) + proxy.max(0)) / 2
    upper = proxy[proxy[:, 1] > centre[1]]
    if len(upper) < PCA_NORMAL_K or len(cranium) < PCA_NORMAL_K:
        raise ValueError("Too few proxy or cranium points to place the hair")
    ext_u, ext_c = np.ptp(upper, 0), np.ptp(cranium, 0)
    if (ext_u <= 0).any():
        raise ValueError("The head proxy is flat")
    s = float(np.mean(ext_c / ext_u))
    t = (cranium.min(0) + cranium.max(0)) / 2 - s * (upper.min(0) + upper.max(0)) / 2
    s0, t0 = s, t.copy()
    n_cranium, n_proxy = _pca_normals(cranium), _pca_normals(proxy)
    tree_c = cKDTree(cranium)
    for _ in range(iterations):
        _, j = tree_c.query(s * upper + t)
        _, k = cKDTree(s * proxy + t).query(cranium)
        A = np.concatenate([upper, proxy[k]])
        B = np.concatenate([cranium[j], cranium])
        N = np.concatenate([n_cranium[j], n_proxy[k]])
        # residual n . (s A + t - B), linear in (s, tx, ty, tz)
        x = np.linalg.lstsq(np.column_stack([(N * A).sum(1), N]), (N * B).sum(1), rcond=None)[0]
        s, t = float(x[0]), x[1:]
    if not (s > 0 and math.isfinite(s)):
        raise ValueError("Could not place the hair on the head (degenerate scale)")
    resid, _ = tree_c.query(s * upper + t)
    info = {"scale_init": round(s0, 4), "translation_init": [round(float(v), 5) for v in t0],
            "scale": round(s, 5), "translation": [float(v) for v in t], "iterations": iterations,
            "proxy_centre": [round(float(v), 5) for v in centre],
            "proxy_size": [round(float(v), 5) for v in np.ptp(proxy, 0)],
            "upper_points": int(len(upper)), "cranium_points": int(len(cranium)), "resid": resid}
    return s, t, info


# --- placement correction: hairline to the brow line ---------------------------------------------------------------

def _head_box(P: np.ndarray, head_v: np.ndarray) -> Tuple[float, float, float, float]:
    """``(cx, cz, width, depth)`` of the Head-weighted vertices' bounding box."""
    H = P[head_v]
    lo, hi = H.min(0), H.max(0)
    return float((lo[0] + hi[0]) / 2), float((lo[2] + hi[2]) / 2), float(hi[0] - lo[0]), float(hi[2] - lo[2])


def _front_strip(hair_X: np.ndarray, box: Tuple[float, float, float, float],
                 floor_y: Optional[float] = None) -> np.ndarray:
    cx, cz, width, depth = box
    front = ((hair_X[:, 2] > cz + HAIRLINE_FRONT_DEPTH * depth)
             & (np.abs(hair_X[:, 0] - cx) < HAIRLINE_HALF_WIDTH * width))
    return front if floor_y is None else front & (hair_X[:, 1] >= floor_y)


def front_hairline(hair_X: np.ndarray, box: Tuple[float, float, float, float],
                   floor_y: Optional[float] = None) -> Optional[float]:
    """The front hairline: the lowest hair vertex with ``z > cz + HAIRLINE_FRONT_DEPTH * depth`` and
    ``|x - cx| < HAIRLINE_HALF_WIDTH * width`` (``box`` = ``_head_box``) and, with ``floor_y`` (the nasion of
    ``head_landmarks``), at or above it: a strand hanging in front of the face below eye level is no hairline (Kira's
    HairDeck seed 43 has one down to the chin, y 1.445 — the scalp cap then covered the whole face). None without
    hair in that strip."""
    front = _front_strip(hair_X, box, floor_y)
    return float(hair_X[front, 1].min()) if front.any() else None


def head_landmarks(P: np.ndarray, head_v: np.ndarray, chin: float, top: float) -> Optional[Dict[str, float]]:
    """Nose tip, nasion and brow of the head's centre profile, or None when the profile shows no face.

    Profile = the Head-weighted vertices within ``PROFILE_HALF_WIDTH_M`` of the head's centre x and in front of its
    centre z (a bin holding only back-of-head vertices must not read as a dip), front z = the largest z per
    ``PROFILE_BIN_M`` bin of y (bins from the chin up). Every bin of the lower half of the head (centre <= chin +
    0.5 * (top - chin)) is a nose-tip candidate; its nasion = the bin of SMALLEST front z between it and halfway from
    it to the crown, its brow = the profile vertex of largest z above that nasion bin (the brow ridge / forehead).
    The nose tip is the candidate with the deepest dip to its nasion, counting only candidates whose dip is at least
    ``LANDMARK_MIN_DIP_M``, whose brow stands out of the nasion by as much and which lies in the front of the head
    (``LANDMARK_NOSE_FRONT``). Not "the largest z of the lower half":
    on a head pitched back (chin up; Kira's base ``base20d5701a``: the nose 1.8 cm BEHIND the forehead) that is the
    top of the band, and no face was found. None for a profile without that dip (a sphere)."""
    cx, cz, _, depth = _head_box(P, head_v)
    S = P[head_v & (np.abs(P[:, 0] - cx) < PROFILE_HALF_WIDTH_M) & (P[:, 2] > cz)]
    if len(S) < 3 or not top > chin:
        return None
    n_bins = int(math.ceil((top - chin) / PROFILE_BIN_M))
    idx = np.clip(((S[:, 1] - chin) / PROFILE_BIN_M).astype(np.int64), 0, n_bins - 1)
    zmax = np.full(n_bins, -np.inf)
    np.maximum.at(zmax, idx, S[:, 2])
    centre_y = chin + (np.arange(n_bins) + 0.5) * PROFILE_BIN_M
    filled = np.isfinite(zmax)
    best: Optional[Tuple[float, int, int, np.ndarray]] = None
    nose_band = filled & (centre_y <= chin + 0.5 * (top - chin)) & (zmax >= cz + LANDMARK_NOSE_FRONT * depth)
    for nose in np.flatnonzero(nose_band):
        band = filled & (centre_y > centre_y[nose]) & (centre_y <= centre_y[nose] + 0.5 * (top - centre_y[nose]))
        if not band.any():
            continue
        nasion = int(np.flatnonzero(band)[np.argmin(zmax[band])])
        dip = float(zmax[nose] - zmax[nasion])
        above = S[S[:, 1] >= chin + (nasion + 1) * PROFILE_BIN_M]
        if dip < LANDMARK_MIN_DIP_M or not len(above):
            continue
        brow = above[int(np.argmax(above[:, 2]))]
        if brow[2] - zmax[nasion] < LANDMARK_MIN_DIP_M:
            continue
        if best is None or dip > best[0]:
            best = (dip, int(nose), nasion, brow)
    if best is None:
        return None
    _, nose, nasion, brow = best
    return {"nose_tip_y": round(float(centre_y[nose]), 5), "nose_tip_z": round(float(zmax[nose]), 5),
            "nasion_y": round(float(centre_y[nasion]), 5), "nasion_z": round(float(zmax[nasion]), 5),
            "brow_y": round(float(brow[1]), 5), "brow_z": round(float(brow[2]), 5),
            "crown_y": round(float(top), 5)}


def landmark_doubts(landmarks: Dict[str, float], chin: float, top: float) -> List[str]:
    """Why a ``head_landmarks`` reading is implausible on a base head ([] = plausible): the brow must lie
    ``BROW_CROWN_MIN_M``..``BROW_CROWN_MAX_M`` below the crown and above the eye line (chin + ``EYE_LINE_RATIO``
    * (crown - chin)), the nose tip below the eye line."""
    eye = chin + EYE_LINE_RATIO * (top - chin)
    gap = top - landmarks["brow_y"]
    doubts = []
    if not BROW_CROWN_MIN_M <= gap <= BROW_CROWN_MAX_M:
        doubts.append(f"brow {gap * 100:.1f} cm below the crown (plausible {BROW_CROWN_MIN_M * 100:g}-"
                      f"{BROW_CROWN_MAX_M * 100:g} cm)")
    if landmarks["brow_y"] <= eye:
        doubts.append(f"brow {landmarks['brow_y']:.3f} not above the eye line {eye:.3f}")
    if landmarks["nose_tip_y"] >= eye:
        doubts.append(f"nose tip {landmarks['nose_tip_y']:.3f} not below the eye line {eye:.3f}")
    return doubts


def placement_landmarks(P: np.ndarray, head_v: np.ndarray, chin: float, top: float
                        ) -> Tuple[Optional[Dict[str, float]], str, Optional[Dict[str, Any]]]:
    """``(landmarks, source, rejected)`` the auto tilt aims with. ``source``: ``"profile"`` (``head_landmarks``,
    plausible), ``"proportions"`` (the profile reading failed ``landmark_doubts`` — a beard modelled into the base
    mesh shifts every dip of the profile down by one feature: brow ``FALLBACK_BROW_RATIO`` and floor
    ``FALLBACK_FLOOR_RATIO`` of chin..crown instead, ``rejected`` = ``{landmarks, doubts}`` of the reading) or
    ``"none"`` (the profile shows no face — a sphere; landmarks None, tilt 0)."""
    landmarks = head_landmarks(P, head_v, chin, top)
    if landmarks is None:
        return None, "none", None
    doubts = landmark_doubts(landmarks, chin, top)
    if not doubts:
        return landmarks, "profile", None
    span = top - chin
    fallback = {"brow_y": round(chin + FALLBACK_BROW_RATIO * span, 5),
                "nasion_y": round(chin + FALLBACK_FLOOR_RATIO * span, 5), "crown_y": round(float(top), 5)}
    return fallback, "proportions", {"landmarks": landmarks, "doubts": doubts}


def hairline_target(brow_y: float, crown_y: float, ratio: float = HAIRLINE_BROW_RATIO) -> float:
    """Where the front hairline belongs: ``brow + ratio * (crown - brow)``."""
    return brow_y + ratio * (crown_y - brow_y)


def adjust_placement(Q: np.ndarray, pivot: np.ndarray, forward_m: float, tilt_deg: float) -> np.ndarray:
    """The placed hair pitched forward by ``tilt_deg`` about the x axis through ``pivot`` (positive = the front,
    +z, goes down: (0, 0, r) -> (0, -r sin a, r cos a)), then moved ``forward_m`` along +z."""
    a = math.radians(tilt_deg)
    c, s = math.cos(a), math.sin(a)
    D = np.asarray(Q, np.float64) - pivot
    out = np.empty_like(D)
    out[:, 0] = D[:, 0]
    out[:, 1] = c * D[:, 1] - s * D[:, 2]
    out[:, 2] = s * D[:, 1] + c * D[:, 2]
    out += pivot
    out[:, 2] += forward_m
    return out


def solve_tilt(Q: np.ndarray, pivot: np.ndarray, forward_m: float, box: Tuple[float, float, float, float],
               target_y: float, floor_y: Optional[float] = None) -> Tuple[float, str]:
    """``(tilt_deg, how)``: the forward tilt in [0, AUTO_TILT_MAX_DEG] whose ``front_hairline`` (placed hair,
    before the push-out) reaches ``target_y``, by bisection to ``AUTO_TILT_TOL_DEG``. ``how``: ``"solved"``,
    ``"at_or_below_target"`` (0: the hairline is already low enough), ``"clamped"`` (the largest tilt still leaves
    it above) or ``"no_hairline"`` (0: no hair in the front strip). ``floor_y``: as in ``front_hairline``."""
    def hairline(deg: float) -> Optional[float]:
        return front_hairline(adjust_placement(Q, pivot, forward_m, deg), box, floor_y)

    h0 = hairline(0.0)
    if h0 is None:
        return 0.0, "no_hairline"
    if h0 <= target_y:
        return 0.0, "at_or_below_target"
    h1 = hairline(AUTO_TILT_MAX_DEG)
    if h1 is not None and h1 > target_y:
        return AUTO_TILT_MAX_DEG, "clamped"
    lo, hi = 0.0, AUTO_TILT_MAX_DEG
    while hi - lo > AUTO_TILT_TOL_DEG:
        mid = (lo + hi) / 2
        h = hairline(mid)
        if h is not None and h > target_y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, "solved"


def _check_manual(forward_m: Optional[float], tilt_deg: Optional[float]) -> None:
    for value, limit, name in ((forward_m, FORWARD_LIMIT_M, "forward_m"), (tilt_deg, TILT_LIMIT_DEG, "tilt_deg")):
        if value is not None and not (isinstance(value, (int, float)) and math.isfinite(value)
                                      and abs(value) <= limit):
            raise ValueError(f"The hair {name} must be a number within +-{limit:g}, got {value!r}")


# --- scalp cap -----------------------------------------------------------------------------------------------------

def _scalp_cap(body, head_w: np.ndarray, hair_X: np.ndarray, sdf, floor_y: Optional[float] = None
               ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Optional[float], Dict[str, Any]]:
    """``(positions, faces, normals, hairline_y, info)`` of the scalp cap (faces index the returned positions).

    Rigged body triangles whose three vertices carry Head weight > 0.5, whose centroid lies above the front hairline
    and whose nearest hair vertex is within ``CAP_REACH_M``, minus the inner-wall ones (centroid deeper than
    ``CAP_INNER_DEPTH_M`` inside the body SDF); offset ``CAP_OFFSET_M`` along the outward vertex normals.
    The front hairline is the lowest hair vertex with ``z > head cz + 0.25 depth`` and ``|x - head cx| < 0.15 width``
    (head bbox = the Head-weighted vertices). Face normals are oriented by the SDF gradient at the centroid before
    they are accumulated into vertex normals — the generator body's winding is never trusted — and the winding is
    flipped to match, so a cap face looks outward.
    """
    from scipy.spatial import cKDTree
    P, F = body.positions, body.faces
    head_v = head_w > 0.5
    box = _head_box(P, head_v)
    cx, cz, width, depth = box
    front = _front_strip(hair_X, box, floor_y)
    empty = (np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros((0, 3)))
    hairline = front_hairline(hair_X, box, floor_y)
    if hairline is None:
        return (*empty, None, {"note": "no hair in front of the head: no hairline, no cap"})
    centroid = P[F].mean(1)
    near, _ = cKDTree(hair_X).query(centroid, distance_upper_bound=CAP_REACH_M * 1.0001)
    sel = head_v[F].all(1) & (centroid[:, 1] > hairline) & (near <= CAP_REACH_M)
    candidates = int(sel.sum())
    sel[sel] = sdf.sample(centroid[sel]) > -CAP_INNER_DEPTH_M
    if not sel.any():
        return (*empty, hairline, {"note": "no scalp triangle above the hairline near the hair"})
    Fc = F[sel]
    used, Fl = np.unique(Fc, return_inverse=True)
    Fl = Fl.reshape(-1, 3)
    V = P[used]
    fn = np.cross(V[Fl[:, 1]] - V[Fl[:, 0]], V[Fl[:, 2]] - V[Fl[:, 0]])
    flip = (fn * sdf.grad(centroid[sel])).sum(1) < 0
    fn[flip] *= -1
    Fl[flip] = Fl[flip][:, [0, 2, 1]]
    N = np.zeros_like(V)
    for i in range(3):
        np.add.at(N, Fl[:, i], fn)
    length = np.linalg.norm(N, axis=1, keepdims=True)
    grad = sdf.grad(V)
    fallback = grad / np.maximum(np.linalg.norm(grad, axis=1, keepdims=True), 1e-12)
    N = np.where(length > 1e-12, N / np.maximum(length, 1e-12), fallback)
    V = V + CAP_OFFSET_M * N
    info = {"head_centre_xz": [round(float(cx), 5), round(float(cz), 5)],
            "head_width_m": round(float(width), 5), "head_depth_m": round(float(depth), 5),
            "front_hair_vertices": int(front.sum()), "flipped_faces": int(flip.sum()),
            "inner_wall_dropped": candidates - int(sel.sum())}
    return V, Fl, N, hairline, info


# --- the fit -------------------------------------------------------------------------------------------------------

def _push(Q: np.ndarray, F: np.ndarray, U, body) -> Dict[str, Any]:
    """The push-out of the placed hair ``Q`` on the rigged body (welded cards, SDF over the hair's bounds)."""
    Pw, Fw, inv = weld(Q, F, U)
    sdf = body_sdf(body.positions, body.faces, vox=VOX_M,
                   bounds=(Pw.min(0) - SDF_MARGIN_M, Pw.max(0) + SDF_MARGIN_M))
    d0 = sdf.sample(Pw)
    Qp, disp = push_out(Pw, Fw, sdf, clear=CARD_CLEAR_M, spread=SPREAD_M, spread_depth=SPREAD_DEPTH_M)
    return {"Pw": Pw, "inv": inv, "sdf": sdf, "d0": d0, "Qp": Qp, "disp": disp}


def _place_and_push(Q0: np.ndarray, pivot: np.ndarray, F: np.ndarray, U, body, head_v: np.ndarray, chin: float,
                    top: float, forward_m: Optional[float], tilt_deg: Optional[float],
                    gates: Optional[Dict[str, Tuple[str, float, str]]] = None
                    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Apply the placement correction to the placed hair ``Q0`` and push it out: ``(push, placement report)``.

    ``forward_m`` None = ``DEFAULT_FORWARD_M``. ``tilt_deg`` None = auto: the hairline target comes from
    ``placement_landmarks`` (the profile's, or the head proportions when that reading is implausible; none = tilt
    0, report ``landmark_source``) and ``solve_tilt`` aims the PLACED hair at it. The push-out then lifts the
    front cards that sat inside the forehead (Kira: by 6-9 mm), so the pushed hairline — the one the scalp cap
    uses — is measured and the aim lowered by the miss, up to ``PLACEMENT_ROUNDS`` push-outs, until it lands
    within ``HAIRLINE_TOL_M`` of the target or the tilt is at a bound of its search range. The hairline only counts
    hair at or above the nasion (``front_hairline``'s floor) when the landmarks are found.

    The push gate comes first: when the automatic tilt leaves a push-out ``gates`` (default ``GATES``) refuse (``max_push_m`` /
    ``moved_share``), the other tilts of [0, AUTO_TILT_MAX_DEG] in ``GATE_TILT_STEP_DEG`` steps are tried, nearest
    first, and the first that passes is taken (``tilt_solve`` gets ``+push_gate``; report ``gate_search``). Kira's
    base ``base20d5701a`` (head ~5 cm further forward over the upper back, pitched back) puts the back curtain 8-9.5
    cm deep into the upper back at tilt 0 (push 0.12-0.15); a forward tilt swings that curtain back out of it.
    A manual tilt is never searched: it is fitted as set, and the gate decides."""
    gates = GATES if gates is None else gates
    box = _head_box(body.positions, head_v)
    forward = DEFAULT_FORWARD_M if forward_m is None else float(forward_m)
    landmarks, landmark_source, rejected = placement_landmarks(body.positions, head_v, chin, top)
    target = hairline_target(landmarks["brow_y"], landmarks["crown_y"]) if landmarks else None
    floor = landmarks["nasion_y"] if landmarks else None
    auto = tilt_deg is None and target is not None
    aim, rounds = target, 0
    while True:
        rounds += 1
        if tilt_deg is not None:
            tilt, how = float(tilt_deg), "manual"
        elif target is None:
            tilt, how = 0.0, "no_landmarks"
        else:
            tilt, how = solve_tilt(Q0, pivot, forward, box, aim, floor)
        Q = adjust_placement(Q0, pivot, forward, tilt) if (forward or tilt) else Q0
        pushed = _push(Q, F, U, body)
        pushed_hl = front_hairline(pushed["Qp"], box, floor)
        if not auto or pushed_hl is None or how == "no_hairline" or rounds >= PLACEMENT_ROUNDS:
            break
        miss = pushed_hl - target
        if abs(miss) <= HAIRLINE_TOL_M or (miss > 0 and tilt >= AUTO_TILT_MAX_DEG) or (miss < 0 and tilt <= 0):
            break
        aim -= miss

    gate_search = None
    if tilt_deg is None and not _push_passes(pushed, gates):
        tried = [[round(tilt, 3), _push_max(pushed)]]
        grid = np.round(np.arange(0.0, AUTO_TILT_MAX_DEG + 1e-9, GATE_TILT_STEP_DEG), 3)
        picked = None
        for cand in sorted((float(c) for c in grid if abs(c - tilt) > 1e-6), key=lambda c: (abs(c - tilt), c)):
            Qc = adjust_placement(Q0, pivot, forward, cand)
            pc = _push(Qc, F, U, body)
            tried.append([cand, _push_max(pc)])
            if _push_passes(pc, gates):
                picked, tilt, Q, pushed, how = cand, cand, Qc, pc, how + "+push_gate"
                pushed_hl = front_hairline(pushed["Qp"], box, floor)
                break
        gate_search = {"tried": tried, "picked": picked}

    def r5(v: Optional[float]) -> Optional[float]:
        return None if v is None else round(float(v), 5)

    return pushed, {
        "forward_m": round(forward, 5), "forward_source": "default" if forward_m is None else "manual",
        "tilt_deg": round(tilt, 3), "tilt_source": "manual" if tilt_deg is not None else "auto",
        "tilt_solve": how, "rounds": rounds, "pivot": [round(float(v), 5) for v in pivot], "landmarks": landmarks,
        "landmark_source": landmark_source, "landmarks_rejected": rejected,
        "hairline_ratio": HAIRLINE_BROW_RATIO, "hairline_target_y": r5(target),
        "hairline_aim_y": r5(aim) if auto else None,
        "hairline_floor_y": floor, "hairline_unadjusted_y": r5(front_hairline(Q0, box, floor)),
        "hairline_placed_y": r5(front_hairline(Q, box, floor)), "hairline_pushed_y": r5(pushed_hl),
        "gate_search": gate_search}


def _push_max(pushed: Dict[str, Any]) -> float:
    disp = pushed["disp"]
    return round(float(np.linalg.norm(disp, axis=1).max()), 4) if len(disp) else 0.0


def _push_passes(pushed: Dict[str, Any], gates: Optional[Dict[str, Tuple[str, float, str]]] = None) -> bool:
    """Whether a push-out passes the push gates (``max_push_m``, ``moved_share`` of ``gates``, default ``GATES``)
    as ``fit_hairdeck`` reports them."""
    gates = GATES if gates is None else gates
    mag = np.linalg.norm(pushed["disp"], axis=1)
    if not len(mag):
        return True
    return (round(float(mag.max()), 4) <= gates["max_push_m"][1]
            and round(float((mag > MOVED_EPS_M).mean()), 4) <= gates["moved_share"][1])


def fit_hairdeck(nohead_glb: bytes, proxy_glb: bytes, rigged_base_glb: bytes, *,
                 colour_target: Optional[Tuple[float, float, float]],
                 forward_m: Optional[float] = None, tilt_deg: Optional[float] = None,
                 colour_profile: Optional[Tuple[float, float, float]] = None,
                 length_class: Optional[str] = None) -> FitResult:
    """Fit HairDeck hair onto the rigged base body.

    ``nohead_glb``: the hair (node ``hair_cards``, ``COLOR_0``); ``proxy_glb``: the result file with the
    ``head_proxy`` node (same space); ``colour_target``: sRGB 0..1 the hair's median colour is mapped to, None =
    keep HairDeck's colours — or, with ``colour_profile`` (sRGB 0..1 of the profile's named hair colour), the
    CIELAB transfer onto it (``_transfer_colours``; ``colour_target`` wins). ``length_class`` (the profile's hair
    length class, e.g. ``"short"``) picks the gates (``gates_for``). ``forward_m`` / ``tilt_deg``: the placement correction after ``place_proxy`` (move
    along +z; forward pitch about x through the placed proxy centre), None = automatic (``DEFAULT_FORWARD_M``; the
    tilt that brings the front hairline to the brow line, ``_placement``). ValueError for a manual value beyond
    ``FORWARD_LIMIT_M`` / ``TILT_LIMIT_DEG``. Returns the hair plus scalp cap as ONE garment (rigged bind space,
    Head -> Spine2 weights, cap all Head, ``COLOR_0``, double-sided), the metrics and the gates' verdict.
    """
    from scipy.spatial import cKDTree
    _check_manual(forward_m, tilt_deg)
    gates = gates_for(length_class)
    P, F, U, C, material = card_arrays(nohead_glb, node="hair_cards")
    if C is None:
        raise ValueError("The HairDeck hair has no vertex colours (COLOR_0)")
    proxy, _, _, _, _ = card_arrays(proxy_glb, node="head_proxy")
    body = body_arrays(rigged_base_glb)
    if not body.joint_names:
        raise ValueError("The rigged base has no skin")
    F = np.asarray(F, np.int64).reshape(-1, 3)

    # cranium
    head_w = dense_weights(body)[:, joint_index(body, "head")]
    head_v = head_w > 0.5
    chin = chin_height(body)
    top = float(body.positions[head_v, 1].max())
    threshold = chin + CRANIUM_FROM * (top - chin)
    cranium = body.positions[head_v & (body.positions[:, 1] > threshold)]

    s, t, icp = place_proxy(proxy, cranium)
    resid = icp.pop("resid")
    pivot = s * (proxy.min(0) + proxy.max(0)) / 2 + t
    # placement correction + push-out on the rigged body
    pushed, placement = _place_and_push(s * np.asarray(P, np.float64) + t, pivot, F, U, body, head_v, chin, top,
                                        forward_m, tilt_deg, gates)
    Pw, inv, sdf, d0, Qp, disp = (pushed[k] for k in ("Pw", "inv", "sdf", "d0", "Qp", "disp"))
    d1 = sdf.sample(Qp)
    mag = np.linalg.norm(disp, axis=1)
    X = Qp[inv]
    names, J, W = hair_weights(X, body)
    normals = vertex_normals(X, F)

    if colour_target is None and colour_profile is not None:
        colours, colour_info = _transfer_colours(C, colour_profile)
    else:
        colours, colour_info = _correct_colours(C, colour_target)

    # scalp cap
    Vc, Fc, Nc, hairline, cap_info = _scalp_cap(body, head_w, Qp, sdf, placement["hairline_floor_y"])
    nc = len(Vc)
    cap_colour = np.r_[np.percentile(colours[:, :3], CAP_COLOUR_PERCENTILE, axis=0), 1.0]
    below = int((Vc[Fc].mean(1)[:, 1] < hairline).sum()) if len(Fc) else 0
    Jc = np.zeros((nc, 4), np.int64)
    Jc[:, 1] = 1
    Wc = np.zeros((nc, 4))
    Wc[:, 0] = 1.0

    material = copy.deepcopy(material or {})
    material["doubleSided"] = True
    garment = GarmentMesh(positions=np.vstack([X, Vc]), normals=np.vstack([normals, Nc]),
                          uvs=np.vstack([np.asarray(U, np.float64), np.zeros((nc, 2))]),
                          indices=np.vstack([F, Fc + len(X)]), joints=np.vstack([J, Jc]),
                          weights=np.vstack([W, Wc]), joint_names=names, image=b"", mime="", material=material,
                          colors=np.vstack([colours, np.tile(cap_colour, (nc, 1))]))

    m = {
        "max_push_m": round(float(mag.max()) if len(mag) else 0.0, 4),
        "moved_share": round(float((mag > MOVED_EPS_M).mean()) if len(mag) else 0.0, 4),
        "icp_scale": round(s, 4),
        "icp_resid_median_m": round(float(np.median(resid)), 5),
        "icp_resid_p95_m": round(float(np.percentile(resid, 95)), 5),
        "cap_tris": int(len(Fc)),
        "cap_tris_below_hairline": below,
        "colour_target": [float(v) for v in colour_target] if colour_target is not None else None,
        # Reported, not gated: the CIE76 distance of the hair's median colour to the target after the recolour
        # (the manual or profile colour; None when HairDeck's own colours are kept without a profile colour).
        "colour_delta_e": colour_info.get("delta_e_after"),
        # Reported, not gated: the placement correction actually applied.
        "forward_m": placement["forward_m"],
        "tilt_deg": placement["tilt_deg"],
    }
    ok, reasons = _gate_against(m, gates)
    near_hair, _ = cKDTree(Qp).query(cranium)
    report = {
        "cranium": {"chin_y": round(chin, 5), "top_y": round(top, 5), "threshold_y": round(threshold, 5),
                    "points": int(len(cranium))},
        "icp": icp,
        "placement": placement,
        "length_class": length_class,
        "push": {"clear_m": CARD_CLEAR_M, "welded_vertices": int(len(Pw)), "inside_before": int((d0 < 0).sum()),
                 "closer_than_clear_before": int((d0 < CARD_CLEAR_M).sum()), "inside_after": int((d1 < 0).sum()),
                 "min_clear_after_m": round(float(d1.min()), 5) if len(d1) else None,
                 "p95_push_m": round(float(np.percentile(mag[mag > MOVED_EPS_M], 95)), 4)
                 if (mag > MOVED_EPS_M).any() else 0.0},
        "weights": {"joints": names, "all_head": int((W[:, 0] == 1).sum()),
                    "blended": int(((W[:, 0] < 1) & (W[:, 0] > 0)).sum()), "all_spine2": int((W[:, 0] == 0).sum())},
        "colour": colour_info,
        "cap": dict(cap_info, hairline_y=None if hairline is None else round(hairline, 5),
                    offset_m=CAP_OFFSET_M, colour_linear=[round(float(v), 4) for v in cap_colour[:3]],
                    cranium_without_hair_within_2cm=round(float((near_hair > 0.02).mean()), 4)
                    if len(near_hair) else None),
        "vertices": {"hair": int(len(X)), "cap": int(nc)},
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)
