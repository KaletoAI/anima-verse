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

from app.core.garment_fit import (MOVED_EPS_M, SDF_MARGIN_M, SPREAD_DEPTH_M, VOX_M, FitResult, body_sdf,
                                  chin_height, dense_weights, gate as _gate_against, hair_weights, joint_index,
                                  push_out, vertex_normals, weld)
from app.core.glb_mesh import GarmentMesh, body_arrays, card_arrays

# Clearance of a card from the body surface (the spike's 0.004 m; cards are thin, unlike a generated hair shell).
CARD_CLEAR_M = 0.004
# The push-out's crown spread (garment_fit.push_out: per vertex the LARGEST displacement within SPREAD_M, iterated
# 6 times + smoothing) floods: one card pushed out of the scalp lifts every card on the head with it. Kira
# 2026-11-11 (~/claude-out/kira-hairdeck): sd before the push p50 5.9 / 11.2 / 9.6 mm (front / sides / back), yet
# 100 % of the head moved by p50 9 / 5 / 8 mm -> scalp -> innermost strand p50 7.4 mm front, outer layer 17.9 mm;
# a puffed helmet. On the head the cards are pushed layer-keeping instead (``layer_push``): a monotone map of the
# distance, so a card above CARD_CLEAR_M + LAYER_BAND_M never moves and the ones below keep their order (no poke:
# share 0.0 at POKE_TOL_M); below the head (the curtain deep in the upper back, up to 3.8 cm inside) the smoothed
# push stays — per-vertex there crumples the ends on the shoulders. The two blend over LAYER_BLEND_M in height.
# The smoothed push runs WITHOUT the crown spread (FIT_VERSION hair 7): with it, the flood it was replaced for came
# back through the blend. Rosi 2026-11-11 (~/claude-out/rosi-hair): the spread lifted the whole head p50 36-50 mm,
# (1 - w) of that entered the blend band (1.554 .. 1.584 m) and the mesh smoothing carried it down the cards to
# ~1.51 -> a ring round the head at eye level, push p50 32.5 mm at 1.55 m against 4.6 mm at 1.58 m and 3.7 above,
# at every angle round the head (27-35 mm -> 0-10 mm). Without the spread: p50 <= 5.4 mm through the band.
LAYER_BAND_M = 0.006
LAYER_BLEND_M = 0.03
LAYER_CLAMP_ITERATIONS = 4
# The back curtain is draped BEHIND the nape before the push (``drape_back``, FIT_VERSION hair 8). HairDeck's
# proxy is a head without a neck; its inner back cards hang straight down from the occiput, through where the
# neck is. Rosi 2026-11-12 (~/claude-out/rosi-hair2): below the ear line 7.7k welded vertices of the back curtain
# lay inside the neck / upper back (96-98 % of them on cards rooted behind the head's mid plane), up to 5-7 cm deep,
# some on a sheet through the middle of the neck (y 1.40: z 0.10 against the neck's 0.04 .. 0.15). The push moves
# each to its NEAREST surface — for a vertex 1 cm from the neck's side and 6 cm from its back that is the side, so
# the curtain wrapped round the neck as a collar (push p50 35-44 mm in the back sectors, 40-70 % of it upward).
# Draped, a back card's vertex below the ear line that lies closer than the clearance goes backward (-z) out of
# the body (stepping DRAPE_STEP_M up to DRAPE_MAX_M; beyond that the push decides), and along its card the shift
# is carried down (a strand once behind the nape stays behind) and faded in over DRAPE_RAMP_M above.
DRAPE_STEP_M = 0.002
DRAPE_MAX_M = 0.10
DRAPE_RAMP_M = 0.03
# The face stays clear (``_clear_face``, after the push), Kira 2026-11-11 (~/claude-out/kira-hairdeck,
# face_back.py): 100 hair vertices hung in the face box (brow .. chin, the inner FACE_CLEAR_SHARE of the face width
# at that height, in front of the head's mid plane), p50 54 mm in front of that plane — HairDeck's side strands fall
# where its own head had no face, over the cheeks and the outer eyes. They move sideways out of the box; the move
# spreads along the card (FACE_FALLOFF per ring, FACE_FALLOFF_RINGS rings) so the strand bends instead of tearing,
# and a clamp keeps the clearance to the cheek. Kira: 100 -> 0 in the box, max move 21.6 mm. A front hairline at or
# below the brows is a fringe from the image and is kept.
FACE_CLEAR_SHARE = 0.8
FACE_FALLOFF = 0.85
FACE_FALLOFF_RINGS = 12
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
# The scalp cap takes the hair's median colour: the 20th percentile (until 2026-11-11) showed as a darker cap at the
# parting and the crown (Kira's HairDeck renders).
CAP_COLOUR_PERCENTILE = 50

# Swing on (Ruling H11): a chain bone's ``anchor_blend`` row is the least-squares row that reproduces today's skin
# over the chain's vertices, pulled towards the row at the bone's segment middle with this ridge (relative to the
# mean diagonal of the normal matrix) so a bone with few vertices stays near that row.
ANCHOR_BLEND_RIDGE = 0.05
#: Weight of each row's "shares sum to 1" equation in that bounded (0..1) least-squares solve.
ANCHOR_BLEND_SUM_WEIGHT = 100.0

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
#: Hair width (``narrow_sides``, per character, profile ``hair_width_scale``; None = 1, HairDeck's own width): the
#: hair's lateral reach beyond the head scaled about the head's mid plane. Rosi 2026-11-12 (~/claude-out/rosi-hair2):
#: the sides stand off the head by HairDeck's own volume — proxy -> hair at 1.52-1.56 m p50 11 / p90 29-34 mm in
#: HairDeck's space (x the ICP scale 1.50, whose proxy is no wider than her head: half width 77.5 mm against
#: 86.5 mm), placed 8-10 / 28-32 mm, final 12-15 / 28-33 mm; the push leaves the outer reach as it was (|x| p90
#: 101 / 107 mm placed, 102 / 108 final). Nothing in the fit adds it, so it is a per-character taste, not a default.
WIDTH_SCALE_LIMITS = (0.5, 1.5)
#: The head's half width per height (``_side_profile``): Head- or Neck-weighted body vertices, the
#: WIDTH_PROFILE_PERCENTILE of |x - cx| per WIDTH_PROFILE_BIN_M bin (an ear is no head width), smoothed over
#: WIDTH_PROFILE_SMOOTH bins; above / below the measured bins the outermost value holds.
WIDTH_PROFILE_BIN_M = 0.005
WIDTH_PROFILE_PERCENTILE = 95
WIDTH_PROFILE_SMOOTH = 5
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
    "max_push_m": ("max", 0.12, "largest push-out after the drape"),
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


def _check_manual(forward_m: Optional[float], tilt_deg: Optional[float], width_scale: Optional[float] = None) -> None:
    for value, limit, name in ((forward_m, FORWARD_LIMIT_M, "forward_m"), (tilt_deg, TILT_LIMIT_DEG, "tilt_deg")):
        if value is not None and not (isinstance(value, (int, float)) and math.isfinite(value)
                                      and abs(value) <= limit):
            raise ValueError(f"The hair {name} must be a number within +-{limit:g}, got {value!r}")
    lo, hi = WIDTH_SCALE_LIMITS
    if width_scale is not None and not (isinstance(width_scale, (int, float)) and math.isfinite(width_scale)
                                        and lo <= width_scale <= hi):
        raise ValueError(f"The hair width_scale must be a number within {lo:g}..{hi:g}, got {width_scale!r}")


def _side_profile(P: np.ndarray, side_v: np.ndarray, cx: float) -> Tuple[np.ndarray, np.ndarray]:
    """``(heights, half widths)`` of the head and neck (``side_v``: Head- or Neck-weighted body vertices) about
    the mid plane ``cx``: per ``WIDTH_PROFILE_BIN_M`` bin the ``WIDTH_PROFILE_PERCENTILE`` of ``|x - cx|``, a
    moving mean over ``WIDTH_PROFILE_SMOOTH`` filled bins."""
    S = P[side_v]
    y0 = float(S[:, 1].min())
    idx = ((S[:, 1] - y0) / WIDTH_PROFILE_BIN_M).astype(np.int64)
    ys, hs = [], []
    for b in np.unique(idx):
        sel = idx == b
        if sel.sum() >= 3:
            ys.append(y0 + (b + 0.5) * WIDTH_PROFILE_BIN_M)
            hs.append(float(np.percentile(np.abs(S[sel, 0] - cx), WIDTH_PROFILE_PERCENTILE)))
    h = np.asarray(hs)
    k = WIDTH_PROFILE_SMOOTH // 2
    smooth = np.array([h[max(0, i - k):i + k + 1].mean() for i in range(len(h))])
    return np.asarray(ys), smooth


def narrow_sides(Q: np.ndarray, profile: Tuple[np.ndarray, np.ndarray], cx: float, width_scale: float
                 ) -> np.ndarray:
    """The hair ``Q`` with its lateral reach beyond the head scaled by ``width_scale`` about the mid plane ``cx``:
    a vertex ``a = |x - cx|`` beyond the head's half width ``h(y)`` (``_side_profile``, interpolated) goes to
    ``h + (a - h) * width_scale``; within ``h`` it stays. Monotone in ``a`` (no layer passes another), the identity
    at the head's side, so hair lying on the scalp and the front hairline (``HAIRLINE_HALF_WIDTH`` of the width,
    inside ``h``) keep their place; the push-out afterwards clears what moved into the body."""
    Q = np.asarray(Q, np.float64).copy()
    if width_scale == 1.0 or not len(profile[0]):
        return Q
    h = np.interp(Q[:, 1], profile[0], profile[1])
    off = Q[:, 0] - cx
    a = np.abs(off)
    Q[:, 0] = cx + np.sign(off) * np.where(a > h, h + (a - h) * width_scale, a)
    return Q


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

def _clamp(P: np.ndarray, disp: np.ndarray, sdf, clear: float, iterations: int) -> np.ndarray:
    """``disp`` plus plain push-out steps along the SDF gradient until ``P + disp`` lies ``clear`` outside."""
    from app.core.garment_fit import _unit
    for _ in range(iterations):
        X = P + disp
        disp = disp + np.clip(clear - sdf.sample(X), 0, None)[:, None] * _unit(sdf.grad(X))
    return disp


def layer_push(P: np.ndarray, sdf, *, clear: float = CARD_CLEAR_M, band: float = LAYER_BAND_M) -> np.ndarray:
    """Layer-keeping displacement of ``P``: the signed distance ``d`` maps to ``clear + band * exp((d - T) / band)``
    below ``T = clear + band`` (continuous at T, increasing, never under ``clear``) and stays above it; moved along
    the SDF gradient, then clamped exactly (``LAYER_CLAMP_ITERATIONS``)."""
    from app.core.garment_fit import _unit
    P = np.asarray(P, np.float64)
    d0 = sdf.sample(P)
    top = clear + band
    target = np.where(d0 < top, clear + band * np.exp(np.minimum(d0 - top, 0.0) / band), d0)
    disp = (target - d0)[:, None] * _unit(sdf.grad(P))
    return _clamp(P, disp, sdf, clear, LAYER_CLAMP_ITERATIONS)


def _cards(Fw: np.ndarray, n: int) -> np.ndarray:
    """The card (connected component of the welded faces) of each of the ``n`` vertices."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(Fw, np.int64).reshape(-1, 3)
    A = coo_matrix((np.ones(F.size), (F.ravel(), np.roll(F, 1, 1).ravel())), shape=(n, n))
    return connected_components(A, directed=False)[1]


def drape_back(P: np.ndarray, Fw: np.ndarray, sdf, *, below_y: float, back_z: float,
               clear: float = CARD_CLEAR_M) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(displacement along -z, report)`` that hangs the back curtain behind the nape (``DRAPE_STEP_M``).

    A back card is one whose highest vertex lies behind ``back_z`` (the head's mid plane). Each of its vertices
    below ``below_y`` (the ear line) with ``sdf < clear`` needs the smallest backward step (multiples of
    ``DRAPE_STEP_M``, at most ``DRAPE_MAX_M``) that puts it ``clear`` outside; none found = 0 (the push decides).
    Along the card a vertex then takes ``max_u need(u) * ramp(y - y_u)`` — ramp 1 at or below u (carried down the
    strand), falling linearly to 0 at ``DRAPE_RAMP_M`` above u — so the strand bends behind the nape instead of
    each vertex jumping to its own nearest surface."""
    P = np.asarray(P, np.float64)
    n = len(P)
    shift = np.zeros(n)
    if not n or not len(Fw):
        return np.zeros_like(P), {"cards": 0, "vertices": 0, "max_m": 0.0}
    card = _cards(Fw, n)
    top = np.full(card.max() + 1, -np.inf)
    np.maximum.at(top, card, P[:, 1])
    order = np.lexsort((-P[:, 1], card))
    root = order[np.r_[0, np.flatnonzero(np.diff(card[order])) + 1]]
    root_z = np.empty(len(top))
    root_z[card[root]] = P[root, 2]
    cand = np.flatnonzero((root_z[card] < back_z) & (P[:, 1] < below_y))
    need = np.zeros(n)
    if len(cand):
        d = sdf.sample(P[cand])
        todo = cand[d < clear]
        steps = np.arange(1, int(round(DRAPE_MAX_M / DRAPE_STEP_M)) + 1) * DRAPE_STEP_M
        open_ = np.ones(len(todo), bool)
        for s in steps:
            if not open_.any():
                break
            idx = todo[open_]
            X = P[idx].copy()
            X[:, 2] -= s
            ok = sdf.sample(X) >= clear
            need[idx[ok]] = s
            open_[np.flatnonzero(open_)[ok]] = False
    for c in np.unique(card[need > 0]):
        members = np.flatnonzero(card == c)
        src = members[need[members] > 0]
        rise = P[members, 1][:, None] - P[src, 1][None, :]        # > 0: the member lies above the source
        ramp = np.clip(1.0 - rise / DRAPE_RAMP_M, 0.0, 1.0)
        shift[members] = (need[src][None, :] * ramp).max(1)
    disp = np.zeros_like(P)
    disp[:, 2] = -shift
    return disp, {"cards": int(len(np.unique(card[shift > 0]))), "vertices": int((need > 0).sum()),
                  "shifted": int((shift > MOVED_EPS_M).sum()), "max_m": round(float(shift.max()), 4)}


def _drape_frame(body) -> Optional[Tuple[float, float]]:
    """``(ear line y, head mid-plane z)`` of a skinned body for ``drape_back``; None without a skin (a bare
    test mesh: no drape)."""
    if not getattr(body, "joint_names", None):
        return None
    from app.core.garment_fit import ear_line_height
    head_v = dense_weights(body)[:, joint_index(body, "head")] > 0.5
    return ear_line_height(body), _head_box(body.positions, head_v)[1]


def _push(Q: np.ndarray, F: np.ndarray, U, body) -> Dict[str, Any]:
    """The push-out of the placed hair ``Q`` on the rigged body (welded cards, SDF over the hair's bounds): the back
    curtain first draped behind the nape (``drape_back``, below the ear line, behind the Head-weighted vertices'
    mid plane; only on a skinned body), then on the head (the top ``SPREAD_DEPTH_M``) layer-keeping
    (``layer_push``), below it the smoothed ``push_out`` without its crown spread (the spread's flood would enter
    the blend band as a ring, see ``LAYER_BLEND_M``), blended over ``LAYER_BLEND_M`` and clamped once more."""
    Pw, Fw, inv = weld(Q, F, U)
    frame = _drape_frame(body)
    lo = Pw.min(0) - SDF_MARGIN_M
    if frame is not None:
        lo[2] -= DRAPE_MAX_M  # the drape's backward steps stay inside the field
    sdf = body_sdf(body.positions, body.faces, vox=VOX_M, bounds=(lo, Pw.max(0) + SDF_MARGIN_M))
    d0 = sdf.sample(Pw)
    if frame is None:
        drape, drape_info = np.zeros_like(Pw), None
    else:
        drape, drape_info = drape_back(Pw, Fw, sdf, below_y=frame[0], back_z=frame[1])
    Pd = Pw + drape
    _q, smooth = push_out(Pd, Fw, sdf, clear=CARD_CLEAR_M)
    layered = layer_push(Pd, sdf)
    w = np.clip((Pd[:, 1] - (Pd[:, 1].max() - SPREAD_DEPTH_M)) / LAYER_BLEND_M, 0.0, 1.0)[:, None]
    push = _clamp(Pd, w * layered + (1.0 - w) * smooth, sdf, CARD_CLEAR_M, LAYER_CLAMP_ITERATIONS)
    disp = drape + push
    Qp = Pw + disp
    return {"Pw": Pw, "Fw": Fw, "inv": inv, "sdf": sdf, "d0": d0, "Qp": Qp, "disp": disp, "push": push,
            "drape": drape_info}


def _ring_max(values: np.ndarray, adjacency, falloff: float, rings: int) -> np.ndarray:
    """``values`` (>= 0) spread over the mesh: per ring a vertex takes ``falloff`` x its largest neighbour."""
    A = adjacency[0] if isinstance(adjacency, tuple) else adjacency
    A = A.tocsr().copy()
    A.data[:] = 1.0   # an edge shared by two faces is counted twice; the spread needs only "is a neighbour"
    v = np.asarray(values, np.float64).copy()
    for _ in range(rings):
        nb = A.multiply(v[None, :]).max(axis=1).toarray().ravel()
        v = np.maximum(v, falloff * nb)
    return v


def _clear_face(Fw: np.ndarray, Qp: np.ndarray, sdf, body, head_w: np.ndarray,
                landmarks: Optional[Dict[str, float]], chin: float,
                hairline_y: Optional[float]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The pushed hair ``Qp`` (welded, faces ``Fw``) with the face kept clear (``FACE_CLEAR_SHARE``) ->
    ``(Q, report)``. A front hairline at or below the brows (``hairline_y``) is a fringe the image shows: kept."""
    from app.core.garment_fit import _adjacency
    Q = np.asarray(Qp, np.float64).copy()
    P = body.positions
    head_v = head_w > 0.5
    if landmarks is None:
        return Q, {"skipped": "no_landmarks"}
    brow = float(landmarks["brow_y"])
    if hairline_y is not None and hairline_y <= brow:
        return Q, {"skipped": "fringe", "hairline_y": round(float(hairline_y), 5)}
    band = head_v & (P[:, 1] < brow) & (P[:, 1] > chin)
    if not band.any():
        return Q, {"skipped": "no_face_band"}
    cx = float(np.median(P[head_v, 0]))
    half = 0.5 * float(np.percentile(P[band, 0], 98) - np.percentile(P[band, 0], 2))
    mid_z = float(np.median(P[band, 2]))
    reach = FACE_CLEAR_SHARE * half
    off = Q[:, 0] - cx
    inside = (Q[:, 1] < brow) & (Q[:, 1] > chin) & (Q[:, 2] > mid_z) & (np.abs(off) < reach)
    need = np.where(inside, reach - np.abs(off), 0.0)
    adjacency = _adjacency(Fw, len(Q))
    dx = (_ring_max(np.where(off >= 0, need, 0.0), adjacency, FACE_FALLOFF, FACE_FALLOFF_RINGS)
          - _ring_max(np.where(off < 0, need, 0.0), adjacency, FACE_FALLOFF, FACE_FALLOFF_RINGS))
    Q[:, 0] += dx
    if inside.any():
        # a strand moved aside may now cut the cheek: out to the clearance again
        Q = Q + _clamp(Q, np.zeros_like(Q), sdf, CARD_CLEAR_M, LAYER_CLAMP_ITERATIONS)
    return Q, {"in_box": int(inside.sum()), "moved": int((np.abs(dx) > MOVED_EPS_M).sum()),
               "max_m": round(float(np.abs(dx).max()), 4) if len(dx) else 0.0,
               "half_width_m": round(half, 4), "mid_z": round(mid_z, 5),
               "in_box_after": int(((Q[:, 1] < brow) & (Q[:, 1] > chin) & (Q[:, 2] > mid_z)
                                    & (np.abs(Q[:, 0] - cx) < reach)).sum())}


def _place_and_push(Q0: np.ndarray, pivot: np.ndarray, F: np.ndarray, U, body, head_v: np.ndarray, chin: float,
                    top: float, forward_m: Optional[float], tilt_deg: Optional[float],
                    gates: Optional[Dict[str, Tuple[str, float, str]]] = None,
                    width_scale: Optional[float] = None,
                    chain_points: Optional[np.ndarray] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
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
    A manual tilt is never searched: it is fitted as set, and the gate decides.

    ``width_scale`` (None = 1) narrows or widens the placed hair's sides (``narrow_sides``) after the forward /
    tilt and before the push; the hairline the tilt aims with lies inside the head's width, so it is not moved.

    ``chain_points`` (HairDeck's spring-chain joints, already mapped with the hair's ``s, t`` like ``Q0``) get the
    same correction with the FINAL forward / tilt / width (gate search included): returned as
    ``push["chain_points"]``. They take no part in the push or in any decision here."""
    gates = GATES if gates is None else gates
    box = _head_box(body.positions, head_v)
    width = 1.0 if width_scale is None else float(width_scale)
    side_profile: Tuple[np.ndarray, np.ndarray] = (np.zeros(0), np.zeros(0))
    if width != 1.0:
        side_v = head_v.copy()
        try:
            side_v |= dense_weights(body)[:, joint_index(body, "neck")] > 0.5
        except KeyError:
            pass
        side_profile = _side_profile(body.positions, side_v, box[0])

    def placed_points(X: np.ndarray, tilt: float) -> np.ndarray:
        Q = adjust_placement(X, pivot, forward, tilt) if (forward or tilt) else X
        return narrow_sides(Q, side_profile, box[0], width) if width != 1.0 else Q

    def placed(tilt: float) -> np.ndarray:
        return placed_points(Q0, tilt)

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
        Q = placed(tilt)
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
            Qc = placed(cand)
            pc = _push(Qc, F, U, body)
            tried.append([cand, _push_max(pc)])
            if _push_passes(pc, gates):
                picked, tilt, Q, pushed, how = cand, cand, Qc, pc, how + "+push_gate"
                pushed_hl = front_hairline(pushed["Qp"], box, floor)
                break
        gate_search = {"tried": tried, "picked": picked}

    if chain_points is not None:
        cp = np.asarray(chain_points, np.float64).reshape(-1, 3)
        pushed = dict(pushed, chain_points=np.array(placed_points(cp, tilt) if len(cp) else cp, np.float64))

    def r5(v: Optional[float]) -> Optional[float]:
        return None if v is None else round(float(v), 5)

    return pushed, {
        "forward_m": round(forward, 5), "forward_source": "default" if forward_m is None else "manual",
        "tilt_deg": round(tilt, 3), "tilt_source": "manual" if tilt_deg is not None else "auto",
        "width_scale": round(width, 3), "width_source": "manual" if width_scale is not None else "default",
        "tilt_solve": how, "rounds": rounds, "pivot": [round(float(v), 5) for v in pivot], "landmarks": landmarks,
        "landmark_source": landmark_source, "landmarks_rejected": rejected,
        "hairline_ratio": HAIRLINE_BROW_RATIO, "hairline_target_y": r5(target),
        "hairline_aim_y": r5(aim) if auto else None,
        "hairline_floor_y": floor, "hairline_unadjusted_y": r5(front_hairline(Q0, box, floor)),
        "hairline_placed_y": r5(front_hairline(Q, box, floor)), "hairline_pushed_y": r5(pushed_hl),
        "gate_search": gate_search}


def _push_max(pushed: Dict[str, Any]) -> float:
    """The largest push-out after the drape (``drape_back`` is a deliberate move, bounded by ``DRAPE_MAX_M``)."""
    disp = pushed.get("push", pushed["disp"])
    return round(float(np.linalg.norm(disp, axis=1).max()), 4) if len(disp) else 0.0


def _push_passes(pushed: Dict[str, Any], gates: Optional[Dict[str, Tuple[str, float, str]]] = None) -> bool:
    """Whether a push-out passes the push gates (``max_push_m``, ``moved_share`` of ``gates``, default ``GATES``)
    as ``fit_hairdeck`` reports them."""
    gates = GATES if gates is None else gates
    mag = np.linalg.norm(pushed["disp"], axis=1)
    if not len(mag):
        return True
    return (_push_max(pushed) <= gates["max_push_m"][1]
            and round(float((mag > MOVED_EPS_M).mean()), 4) <= gates["moved_share"][1])


def _bind_chains(P: np.ndarray, F: np.ndarray, chains_json: Optional[bytes], cards_json: Optional[bytes]
                 ) -> Tuple[Any, List[Any], Dict[str, Any]]:
    """``(binding, chains, report.chains)`` of the hair ``P`` / ``F`` (HairDeck's space) on the seed's spring
    chains (``hair_chains``): ``(None, [], …)`` — today's fit — without both files, for a card file that does not
    match the mesh (``match`` ``"count"`` / ``"offset"`` / ``"invalid"``), a malformed chains file or no chain that
    binds a card. ``chains``: the loaded chains (``hair_chains.load_chains``), which ``binding.chain`` and
    ``binding.kept`` index."""
    from app.core.hair_chains import SETTLE_TOL_M
    info: Dict[str, Any] = {"count": 0, "dropped": 0, "cards_bound": 0, "cards_rigid": 0, "match": None,
                            "chains": [], "joint_depth_max_m": 0.0, "joint_depth_before_max_m": 0.0,
                            "repair": {"tol_m": SETTLE_TOL_M, "moved_joints": 0, "unbound_chains": [],
                                       "truncated_chains": []}}
    if chains_json is None or cards_json is None:
        return None, [], info
    from app.core import hair_chains
    try:
        loaded = hair_chains.load_chains(chains_json)
        given = hair_chains.chain_count(chains_json)
    except ValueError as e:
        info.update(match="invalid", error=str(e)[:200])
        return None, [], info
    centrelines, match = hair_chains.card_centrelines(cards_json, P, F)
    info["match"] = match["match"]
    if match.get("centroid_max") is not None:
        info["centroid_max"] = match["centroid_max"]
    info["dropped"] = given
    if centrelines is None:
        return None, [], info
    binding = hair_chains.bind(P, F, centrelines, loaded)
    bound, rigid = hair_chains.card_counts(binding)
    info.update(count=len(binding.kept), dropped=given - len(binding.kept), cards_bound=bound, cards_rigid=rigid,
                cards_mismatch=binding.mismatch)
    if not binding.kept:
        return None, [], info
    return binding, loaded, info


def _repair_report(kept: List[Any], unbound: List[int], depth: Dict[str, Any]) -> Dict[str, Any]:
    """``report.chains.repair`` of ``hair_chains.repair_depth`` over the ``kept`` chains: the tolerance, the joints
    moved onto their card-centroid line, the chains unbound (HairDeck index, reason, depth before) and the chains
    truncated (Ruling H9: HairDeck index, the first dropped joint, the joints kept — 0 or 1 for a chain that was
    unbound for it — why, its depth and how far its repair would have moved it)."""
    from app.core.hair_chains import SETTLE_TOL_M
    chains = depth["chains"]
    truncated = []
    for i, d in enumerate(chains):
        at = d.get("truncated_at")
        if at is None:
            continue
        truncated.append({"index": int(kept[i].index), "at": int(at), "kept_joints": int(at),
                          "dropped_joints": int(len(d["depth_before"]) - at), "why": d.get("truncate"),
                          "depth_m": round(float(d["depth_before"][at]), 5),
                          "move_m": round(float(d["move_m"][at]), 5)})
    return {"tol_m": SETTLE_TOL_M, "moved_joints": int(depth["moved_joints"]),
            "unbound_chains": [{"index": int(kept[i].index), "reason": chains[i]["reason"],
                                "depth_before_max_m": round(float(chains[i]["depth_before"].max()), 5)}
                               for i in unbound],
            "truncated_chains": truncated}


def _anchor_blend(chain: Any, body: Any, today: Tuple[List[str], np.ndarray, np.ndarray], binding: Any,
                  position: int) -> Dict[str, Dict[str, float]]:
    """Today's skin at one chain's bones (Ruling H11): per bone (``{bone: {body joint: share}}``, joint names as in
    the body, shares > 0 rounded to 3 decimals) the row R_j that makes the chain skin reproduce ``today`` (=
    ``hair_weights``' ``names, J, W``) when every bone rides its row: a bound vertex is skinned ``(1 - w)`` Head +
    ``w * alpha`` seg + ``w * (1 - alpha)`` seg2 (``hair_chains.chain_weights``), so its rows must satisfy
    ``w * (alpha R_seg + (1 - alpha) R_seg2) = today_v - (1 - w) Head``. Least squares over the chain's bound
    vertices (``position`` = its index in ``binding``) with every share in [0, 1] and each row summing to 1
    (``ANCHOR_BLEND_SUM_WEIGHT``), pulled with ``ANCHOR_BLEND_RIDGE`` towards the row at the bone's segment middle
    (also the row of a bone without vertices), then normalised."""
    from app.core import hair_chains
    from app.core.rig_contract import norm_bone_name
    J = np.asarray(chain.joints, np.float64)
    bones = hair_chains.joint_names(chain)
    if len(J) < 2:
        return {}
    names, tJ, tW = today
    k = len(names)
    head = [i for i, nm in enumerate(names) if norm_bone_name(str(nm)) == "head"]
    mnames, mJ, mW = hair_weights((J[:-1] + J[1:]) / 2, body)
    R0 = np.zeros((len(bones), k))
    for b in range(len(J) - 1):
        for jj, ww in zip(mJ[b], mW[b]):
            R0[b, names.index(mnames[int(jj)])] += ww
    R0[-1] = R0[-2]
    on = np.flatnonzero(np.asarray(binding.chain) == position)
    R = R0
    if len(on) and head:
        T = np.zeros((len(on), k))
        np.add.at(T, (np.repeat(np.arange(len(on)), tJ.shape[1]), np.asarray(tJ)[on].ravel()), np.asarray(tW)[on].ravel())
        w, al = np.asarray(binding.w)[on], np.asarray(binding.alpha)[on]
        T[:, head[0]] -= 1.0 - w
        A = np.zeros((len(on), len(bones)))
        np.add.at(A, (np.arange(len(on)), np.asarray(binding.seg)[on]), w * al)
        np.add.at(A, (np.arange(len(on)), np.asarray(binding.seg2)[on]), w * (1.0 - al))
        from scipy.optimize import lsq_linear
        nb = len(bones)
        lam = ANCHOR_BLEND_RIDGE * max(1.0, float(np.trace(A.T @ A)) / nb)
        # x = vec(R) (row-major); rows: the vertices per joint column, the ridge, each row's sum (weighted hard)
        M = np.vstack([np.kron(A, np.eye(k)), np.sqrt(lam) * np.eye(nb * k),
                       ANCHOR_BLEND_SUM_WEIGHT * np.kron(np.eye(nb), np.ones((1, k)))])
        y = np.concatenate([T.ravel(), np.sqrt(lam) * R0.ravel(), ANCHOR_BLEND_SUM_WEIGHT * np.ones(nb)])
        R = lsq_linear(M, y, bounds=(0.0, 1.0)).x.reshape(nb, k)
        sums = R.sum(axis=1, keepdims=True)
        R = np.where(sums > 1e-9, R / np.where(sums > 1e-9, sums, 1.0), R0)
    out: Dict[str, Dict[str, float]] = {}
    for bone, row in zip(bones[:-1], R[:-1]):
        shares = {str(n): round(float(v), 3) for n, v in zip(names, row) if round(float(v), 3) > 0}
        if shares:
            out[bone] = shares
    return out


def fit_hairdeck(nohead_glb: bytes, proxy_glb: bytes, rigged_base_glb: bytes, *,
                 colour_target: Optional[Tuple[float, float, float]],
                 forward_m: Optional[float] = None, tilt_deg: Optional[float] = None,
                 colour_profile: Optional[Tuple[float, float, float]] = None,
                 length_class: Optional[str] = None, width_scale: Optional[float] = None,
                 chains_json: Optional[bytes] = None, cards_json: Optional[bytes] = None,
                 swing: bool = False) -> FitResult:
    """Fit HairDeck hair onto the rigged base body.

    ``nohead_glb``: the hair (node ``hair_cards``, ``COLOR_0``); ``proxy_glb``: the result file with the
    ``head_proxy`` node (same space); ``colour_target``: sRGB 0..1 the hair's median colour is mapped to, None =
    keep HairDeck's colours — or, with ``colour_profile`` (sRGB 0..1 of the profile's named hair colour), the
    CIELAB transfer onto it (``_transfer_colours``; ``colour_target`` wins). ``length_class`` (the profile's hair
    length class, e.g. ``"short"``) picks the gates (``gates_for``). ``forward_m`` / ``tilt_deg``: the placement correction after ``place_proxy`` (move
    along +z; forward pitch about x through the placed proxy centre), None = automatic (``DEFAULT_FORWARD_M``; the
    tilt that brings the front hairline to the brow line, ``_placement``). ``width_scale``: the sides' reach beyond
    the head scaled (``narrow_sides``), None = 1. ValueError for a manual value beyond ``FORWARD_LIMIT_M`` /
    ``TILT_LIMIT_DEG`` / ``WIDTH_SCALE_LIMITS``. Returns the hair plus scalp cap as ONE garment (rigged bind space,
    Head -> Spine2 weights, cap all Head, ``COLOR_0``, double-sided), the metrics and the gates' verdict.

    ``chains_json`` / ``cards_json``: the seed's ``chains_seed<s>.json`` / ``cards_seed<s>.json`` (both or none).
    With both, the cards are bound to HairDeck's spring chains (``hair_chains.bind``, in HairDeck's space before the
    placement), the joints get the hair's placement (``_place_and_push(chain_points=…)``) and follow their cards
    through the push and the face clearing (``hair_chains.follow``); the chain-bound vertices are skinned to Head
    and their chain bones (``hair_chains.chain_weights``), ``garment.joint_parents`` names the chain joints and
    ``report.chains`` summarises them. The positions are those of the fit without chains (Ruling H8: no settle).
    The followed joints get a rest depth check against the body SDF (``hair_chains.repair_depth``): a joint more
    than ``SETTLE_TOL_M`` inside moves onto its card-centroid line at the nearest point outside the body, a chain
    without one is unbound and its cards keep today's rigid weights; a repair that would move a joint too far or
    shrink a segment at it too much truncates the chain there instead (Ruling H9, ``hair_chains.truncate``; fewer
    than two joints left = unbound) — reported in ``report.chains`` (``joint_depth_before_max_m`` /
    ``joint_depth_max_m`` over the chains in the figure, ``repair``, per chain ``depth_before_max_m`` /
    ``depth_max_m`` / ``moved`` / ``truncated_at``), never gated. ``garment.joint_binds`` carries the bind frame of
    every chain joint (``hair_chains.joint_frames`` of the repaired chains), so ``glb_mesh.graft`` appends them as
    real joints. Without the files, a card file that does not match the mesh, no chain that binds a card or every
    chain unbound: today's fit, ``report.chains.count`` 0, no joint binds.

    ``swing`` (Ruling H11, the profile's ``hair_motion.swing_on``): only with Swing on are the chain-bound vertices
    skinned to their chains and the joints written (``joint_parents`` / ``joint_binds``). With Swing off the
    binding is still computed and reported (``report.chains``, ``swing`` False, every chain's ``weighted`` empty —
    no motion group), but the garment is today's: ``hair_weights``' rows byte for byte, no chain joint. With Swing
    on each chain records ``anchor_blend`` = per bone the Head / Neck / Spine2 row that reproduces today's skin
    (``_anchor_blend``): the client puts each bone's swing on top of that blend (secondaryMotion.ts, HAIR CHAINS),
    so the hair at rest is where today's skin puts it and only the swing is added.
    """
    from scipy.spatial import cKDTree
    _check_manual(forward_m, tilt_deg, width_scale)
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
    # spring chains (HairDeck's space, before the placement)
    binding, chains, chain_info = _bind_chains(P, F, chains_json, cards_json)
    kept = [chains[i] for i in binding.kept] if binding is not None else []
    chain_points = None
    if kept:
        chain_points = s * np.concatenate([c.joints for c in kept]) + t
    # placement correction + push-out on the rigged body
    pushed, placement = _place_and_push(s * np.asarray(P, np.float64) + t, pivot, F, U, body, head_v, chin, top,
                                        forward_m, tilt_deg, gates, width_scale, chain_points=chain_points)
    Pw, inv, sdf, d0, Qp, disp = (pushed[k] for k in ("Pw", "inv", "sdf", "d0", "Qp", "disp"))
    push_mag = np.linalg.norm(pushed["push"], axis=1)
    Qp, face = _clear_face(pushed["Fw"], Qp, sdf, body, head_w, placement["landmarks"], chin,
                           placement["hairline_pushed_y"])
    d1 = sdf.sample(Qp)
    mag = np.linalg.norm(disp, axis=1)
    X = Qp[inv]
    names, J, W = hair_weights(X, body)
    joint_parents: Dict[str, str] = {}
    joint_binds: Dict[str, np.ndarray] = {}
    if kept:
        # the joints follow their own cards from the placed (welded ``Pw``) to the fitted hair (``Qp``)
        from app.core import hair_chains
        sizes = np.cumsum([len(c.joints) for c in kept])[:-1]
        placed_joints = np.split(pushed["chain_points"], sizes)
        bound = hair_chains.bound_vertices(binding, inv)
        fitted = hair_chains.follow(placed_joints, Pw, Qp, bound)
        # rest depth check against the body surface: a deep joint moves onto its card-centroid line, a chain
        # without an outside point there is unbound (Ruling H8 — a repair, never a refusal; the cards stay)
        fitted, unbound, depth = hair_chains.repair_depth(fitted, Qp, bound, sdf)
        chain_info["repair"] = _repair_report(kept, unbound, depth)
        kept_pos = list(binding.kept)
        chain_info["joint_depth_before_max_m"] = round(float(max(d["depth_before"].max() for d in depth["chains"])),
                                                       5)
        if unbound:
            binding = hair_chains.unbind(binding, [binding.kept[i] for i in unbound])
            bound_n, rigid_n = hair_chains.card_counts(binding)
            chain_info.update(count=len(binding.kept), cards_bound=bound_n, cards_rigid=rigid_n)
        gone = set(unbound)
        keep = [i for i in range(len(kept)) if i not in gone]
        # Ruling H9: a chain truncated by its repair keeps its upper joints; its dropped part's vertices ride the
        # last kept segment bone
        cut = {kept_pos[i]: len(fitted[i]) for i in keep if depth["chains"][i].get("truncated_at") is not None}
        if cut:
            binding = hair_chains.truncate(binding, cut)
        kept = [kept[i] for i in keep]
        placed_chains = [hair_chains.Chain(index=c.index, joints=fitted[i], stiffness=c.stiffness)
                         for c, i in zip(kept, keep)]
        after = [depth["chains"][i] for i in keep]
        chain_info["joint_depth_max_m"] = round(float(max((d["depth_after"].max() for d in after), default=0.0)), 5)
        if kept:
            # the binding's chain positions index ``chains``: the repaired (and truncated) joints replace them
            placed = list(chains)
            for i, c in zip(keep, placed_chains):
                placed[kept_pos[i]] = c
            today = (list(names), np.asarray(J), np.asarray(W))
            if swing:
                names, J, W = hair_chains.chain_weights(names, J, W, binding, placed)
                joint_parents = hair_chains.joint_parents(placed_chains)
                joint_binds = hair_chains.joint_frames(placed_chains)
        chain_info["swing"] = bool(swing)
        chain_info["chains"] = [{"index": c.index, "bones": hair_chains.joint_names(c),
                                 "weighted": hair_chains.weighted_bones(names, J, W, c),
                                 "anchor_blend": _anchor_blend(c, body, today, binding, kept_pos[i])
                                 if swing else None,
                                 "stiffness": round(float(c.stiffness), 4), "rigid": [],
                                 "depth_before_max_m": round(float(d["depth_before"].max()), 5),
                                 "depth_max_m": round(float(d["depth_after"].max()), 5),
                                 "moved": list(d["moved"]), "truncated_at": d.get("truncated_at")}
                                for c, d, i in zip(placed_chains, after, keep)]
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
                          colors=np.vstack([colours, np.tile(cap_colour, (nc, 1))]), joint_parents=joint_parents,
                          joint_binds=joint_binds)

    m = {
        # the push-out after the drape (``_push_max``); the drape is reported in ``report.push.drape``
        "max_push_m": round(float(push_mag.max()) if len(push_mag) else 0.0, 4),
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
        "width_scale": placement["width_scale"],
    }
    ok, reasons = _gate_against(m, gates)
    near_hair, _ = cKDTree(Qp).query(cranium)
    report = {
        "cranium": {"chin_y": round(chin, 5), "top_y": round(top, 5), "threshold_y": round(threshold, 5),
                    "points": int(len(cranium))},
        "icp": icp,
        "placement": placement,
        "length_class": length_class,
        "push": {"clear_m": CARD_CLEAR_M, "welded_vertices": int(len(Pw)), "drape": pushed.get("drape"),
                 "inside_before": int((d0 < 0).sum()),
                 "closer_than_clear_before": int((d0 < CARD_CLEAR_M).sum()), "inside_after": int((d1 < 0).sum()),
                 "min_clear_after_m": round(float(d1.min()), 5) if len(d1) else None,
                 "p95_push_m": round(float(np.percentile(mag[mag > MOVED_EPS_M], 95)), 4)
                 if (mag > MOVED_EPS_M).any() else 0.0},
        "face": face,
        "weights": {"joints": names, "all_head": int((W[:, 0] == 1).sum()),
                    "blended": int(((W[:, 0] < 1) & (W[:, 0] > 0)).sum()), "all_spine2": int((W[:, 0] == 0).sum())},
        "colour": colour_info,
        "cap": dict(cap_info, hairline_y=None if hairline is None else round(hairline, 5),
                    offset_m=CAP_OFFSET_M, colour_linear=[round(float(v), 4) for v in cap_colour[:3]],
                    cranium_without_hair_within_2cm=round(float((near_hair > 0.02).mean()), 4)
                    if len(near_hair) else None),
        "vertices": {"hair": int(len(X)), "cap": int(nc)},
        "chains": chain_info,
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)
