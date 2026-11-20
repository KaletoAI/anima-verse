"""Glasses — a frame with two lenses, built on the CPU (0 hub jobs) and rigid on the Head bone (bug round 2026-11-20;
design ``diag1120.json`` key ``glasses``, decisions E1–E7 approved by the user).

The rig has no eye and no ear bones, and the eye paint (``face_cleanup._locate_eyes``) fails on most rigged bodies, so
the glasses are anchored to what the SHAPE of the face says (``face_landmarks``): a front depth map of the head
(``CELL_M`` cells, every triangle sampled, ``WINDOW_X_M`` to each side of the Head bone head, ``WINDOW_Y_M`` in height),

- the nose tip — the row whose midline stands farthest in front of the strip ``SIDE_BAND_M`` beside it, among the rows
  at most ``NOSE_BEHIND_FRONT_MM`` behind the face's front-most midline row (that keeps the chin out); a domed
  forehead never wins, it has no prominence over its sides;
- the mid-plane — the x of the front-most cell within ``MID_SEARCH_M`` of the head's x in the nose row;
- the nasion (the root of the nose) — the deepest midline cell ``NASION_ABOVE_M`` above the tip; it must lie
  ``NASION_GATE_MM`` above it, else the face was not found;
- the eye line ``y_e`` = nasion − ``EYE_BELOW_NASION_M``; the pad height ``y_b`` = nasion − ``PAD_BELOW_NASION_M``;
- the nose's half width at ``y_b`` — the farthest cell from the mid-plane, contiguous with it, at most
  ``NOSE_WIDTH_BACK_M`` behind the ridge there.

Layout (``layout``; bind space, +Y up, +Z front, +X the body's left):

- bridge: half inner width ``b`` = nose half width + ``BRIDGE_ADD_M``;
- frame half width ``W`` = the larger side of the head at ``y_e`` + ``TEMPLE_ABOVE_EYE_M`` and ``FRAME_DEPTH_M`` behind
  the face's lens plane (the minimum below, before any brow push — the width is a head measure, the same for every
  shape), + ``FRAME_ADD_M`` + the size step (``SIZE_ADD_M``: narrow −3, regular 0, wide +6 mm);
- lens width ``w`` = ``W − b − ENDPIECE_M`` (a round lens at most ``ROUND_MAX_M``), lens height ``w × SHAPE_RATIO``;
  lens centre ``y_e`` (aviator ``AVIATOR_DOWN_M`` lower), ``b + w / 2`` from the mid-plane;
- the lens plane leans ``TILT_DEG`` (its bottom nearer the face) and wraps ``WRAP_DEG`` per side from the bridge;
  its back is ``GAP_M`` in front of the front-most skin inside the lens outline, and at least ``PAD_DIST_M`` in front
  of the nose ridge at ``y_b``. Standing farther forward than that minimum is the brow pushing it: up to
  ``MAX_PUSH_M`` is allowed, more refuses the build (``REFUSE_BROW``);
- nose pads: small ellipsoids on the nose flanks at ``y_b``, ``PAD_GAP_M`` off the skin, each held by an arm to the
  nearest inner rim point;
- temples: from the outer rim at ``y_e + TEMPLE_ABOVE_EYE_M`` back to the ear, each side measured for itself: the
  lateral offset at a depth is the running maximum of the head's side up to that depth + ``GAP_M`` + half the temple
  (never bent inwards). The ear (``accessory_band.ear_anchor``: its top and front) is used when its top lies
  ``EAR_TOP_RANGE_M`` around the eye line: the temple then rises over the last ``EAR_RISE_M`` to clear the ear top
  and ends ``STRAIGHT_PAST_EAR_M`` behind the ear's front (``straight``), or bends down ``HOOK_DROP_M`` behind the
  ear (``hook``). An ear top outside that range (a pointed ear, horns or hair in the search box) is not used: the
  temple runs straight back at its height to the ear's front + ``STRAIGHT_PAST_EAR_M`` — never a hook — and the
  metrics say ``ear_used: false``. The temples run under hair; nothing checks the hair.

Gate (``make``): every vertex of the rims, lenses, bridge and temples at least ``GAP_MIN_M`` off the body (nose,
brows, cheeks and ears included), the pads and their arms at least ``PAD_MIN_M``. The front is moved forward (up to
``MAX_PUSH_M`` in all) until it clears; temples and arms are pushed off the skin along its normal. Rigid on the Head
(weight 1.0): the only morph target (``mouth_open``) moves nothing above the nose tip, so no pose check is needed.

Pure numpy/scipy; no I/O.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# --- face landmarks ------------------------------------------------------------------------------------------------
#: The depth map's cell (metres) and the triangle sampling (points per edge).
CELL_M = 0.001
TRI_SUBDIV = 12
#: The depth map's window round the Head bone head: half width, and (below, above) in height.
WINDOW_X_M = 0.09
WINDOW_Y_M = (-0.07, 0.14)
#: The midline strip and the strip beside it whose difference is the nose's prominence (|x| from the mid-plane).
MID_HALF_M = 0.004
SIDE_BAND_M = (0.025, 0.035)
#: Rows searched for the nose tip (height over the Head bone head) and how far behind the front-most midline row a
#: row may lie (keeps the chin out).
NOSE_ROW_Y_M = (-0.06, 0.09)
NOSE_BEHIND_FRONT_MM = 25.0
#: How far to the side of the head's x the nose row's front-most cell (the mid-plane) is looked for.
MID_SEARCH_M = 0.015
#: Where the nasion is looked for (above the nose tip) and where it must lie (mm above the tip).
NASION_ABOVE_M = (0.015, 0.07)
NASION_GATE_MM = (25.0, 70.0)
EYE_BELOW_NASION_M = 0.004
PAD_BELOW_NASION_M = 0.008
#: The nose's width is read this far behind its ridge.
NOSE_WIDTH_BACK_M = 0.004

# --- layout ---------------------------------------------------------------------------------------------------------
BRIDGE_ADD_M = 0.002
#: The head's side that sets the frame width is read this far behind the face's lens plane (E2; before the
#: brow push).
FRAME_DEPTH_M = 0.035
FRAME_ADD_M = 0.003
SIZE_ADD_M = {"narrow": -0.003, "regular": 0.0, "wide": 0.006}
ENDPIECE_M = 0.005
ROUND_MAX_M = 0.046
#: Lens height per lens width.
SHAPE_RATIO = {"round": 1.0, "rectangular": 0.65, "cat_eye": 0.6, "aviator": 0.85}
AVIATOR_DOWN_M = 0.004
#: A lens narrower / wider than this is no plausible lens on this face.
LENS_W_RANGE_M = (0.022, 0.07)
TILT_DEG = 8.0
WRAP_DEG = 5.0
OUTLINE_POINTS = 64
#: Air: the frame and temples (``GAP_M``, gate ``GAP_MIN_M``); the nose pads (``PAD_GAP_M``, gate ``PAD_MIN_M``).
GAP_M = 0.002
GAP_MIN_M = 0.0019
PAD_GAP_M = 0.001
PAD_MIN_M = 0.0007
#: The lens back stands at least this far in front of the nose ridge at the pad height.
PAD_DIST_M = 0.004
#: How far the brow may push the lenses forward beyond that.
MAX_PUSH_M = 0.008
#: The depth of an acetate front (metal: the rim is round).
ACETATE_DEPTH_M = 0.004
#: The temple: height over the eye line; a metal temple's diameter at least ``TEMPLE_MIN_M``; an acetate temple is
#: flat, ``ACETATE_TEMPLE_H_M`` tall.
TEMPLE_ABOVE_EYE_M = 0.005
TEMPLE_MIN_M = 0.0012
ACETATE_TEMPLE_H_M = 0.004
#: The endpiece: from the outer rim this far back before the temple proper starts.
ENDPIECE_BACK_M = 0.006
#: The ear is used when its top lies between these offsets from the eye line (E4).
EAR_TOP_RANGE_M = (-0.005, 0.030)
EAR_RISE_M = 0.030
STRAIGHT_PAST_EAR_M = 0.010
HOOK_PAST_EAR_M = 0.020
HOOK_DROP_M = 0.020
#: Without an ear: the temple's length behind the lens plane at 1.70 m (scaled by the body's height).
NO_EAR_LENGTH_M = 0.10
TEMPLE_STEP_M = 0.004
#: The temple's lateral offset is read from the head's side in this window round its centre line (height, depth).
SIDE_WINDOW_M = (0.004, 0.003)
#: Nose pads: semi-axes (along the skin's normal, up the nose, across); the arm's radius per frame.
PAD_AXES_M = (0.0009, 0.0045, 0.0025)
ARM_RADIUS_M = {"metal": 0.00045, "acetate": 0.001}
#: Cross-section sides of the rims / temples.
SECTION_SIDES = 8

FACE_MISSING = "The face was not found on this body ({reason})"
REFUSE_BROW = ("The brow stands {mm:.0f} mm in front of the nose bridge — the lenses would float; choose a smaller "
               "or lower frame")
IMPLAUSIBLE = "The glasses do not fit this body ({why})"


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _bone(bones: Dict[str, Any], key: str) -> np.ndarray:
    norm = {str(k).split(":")[-1].lower(): v for k, v in bones.items()}
    if key not in norm:
        raise KeyError(key)
    return np.asarray(norm[key], np.float64)


def sample_triangles(P: np.ndarray, F: np.ndarray, n: int) -> np.ndarray:
    """Points on every triangle of ``(P, F)``: the barycentric grid of ``n`` steps per edge (corners included)."""
    a, b = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
    keep = a + b <= n
    a, b = a[keep] / n, b[keep] / n
    T = P[F]
    return (T[:, None, 0] * (1 - a - b)[None, :, None] + T[:, None, 1] * a[None, :, None]
            + T[:, None, 2] * b[None, :, None]).reshape(-1, 3)


def depth_map(P: np.ndarray, F: np.ndarray, head: np.ndarray) -> Dict[str, Any]:
    """The front depth map of the face: ``{Z (ny, nx) — the front-most z per cell, NaN where empty, x0, y0}`` over the
    window round ``head`` (``WINDOW_X_M``, ``WINDOW_Y_M``), only triangles reaching in front of the head bone."""
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64)
    x0, x1 = head[0] - WINDOW_X_M, head[0] + WINDOW_X_M
    y0, y1 = head[1] + WINDOW_Y_M[0], head[1] + WINDOW_Y_M[1]
    T = P[F]
    keep = (T[:, :, 0].max(1) > x0) & (T[:, :, 0].min(1) < x1) & (T[:, :, 1].max(1) > y0) \
        & (T[:, :, 1].min(1) < y1) & (T[:, :, 2].max(1) > head[2])
    Q = sample_triangles(P, F[keep], TRI_SUBDIV)
    nx, ny = int(round((x1 - x0) / CELL_M)), int(round((y1 - y0) / CELL_M))
    ok = (Q[:, 0] >= x0) & (Q[:, 0] < x1) & (Q[:, 1] >= y0) & (Q[:, 1] < y1)
    Q = Q[ok]
    ix = ((Q[:, 0] - x0) / CELL_M).astype(np.int64).clip(0, nx - 1)
    iy = ((Q[:, 1] - y0) / CELL_M).astype(np.int64).clip(0, ny - 1)
    Z = np.full((ny, nx), -np.inf)
    np.maximum.at(Z, (iy, ix), Q[:, 2])
    Z[~np.isfinite(Z)] = np.nan
    return {"Z": Z, "x0": x0, "y0": y0}


def _cells(dm: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """The x of every column and the y of every row of a depth map (cell centres)."""
    Z = dm["Z"]
    return (dm["x0"] + (np.arange(Z.shape[1]) + 0.5) * CELL_M, dm["y0"] + (np.arange(Z.shape[0]) + 0.5) * CELL_M)


def _strip_max(Z: np.ndarray, xs: np.ndarray, centre: float, lo: float, hi: float) -> np.ndarray:
    """Per row the front-most z over the columns ``lo <= |x − centre| < hi`` (NaN where none)."""
    c = (np.abs(xs - centre) >= lo) & (np.abs(xs - centre) < hi)
    sub = Z[:, c]
    out = np.full(len(Z), np.nan)
    has = np.isfinite(sub).any(1)
    out[has] = np.nanmax(sub[has], axis=1)
    return out


def face_landmarks(P: np.ndarray, F: np.ndarray, bones: Dict[str, Any]) -> Dict[str, Any]:
    """The face of the body ``(P, F)`` (module docstring): ``{mid_x, nose_tip, nasion, eye_y, pad_y, ridge_z,
    nose_half_m, depth}`` (``depth``: ``depth_map``). ``ValueError`` (``FACE_MISSING``) when it is not found;
    ``KeyError`` without a Head bone."""
    head = _bone(bones, "head")
    dm = depth_map(P, F, head)
    Z = dm["Z"]
    xs, ys = _cells(dm)
    if not np.isfinite(Z).any():
        raise ValueError(FACE_MISSING.format(reason="no skin in front of the head bone"))
    mid0 = float(head[0])
    midf = _strip_max(Z, xs, mid0, 0.0, MID_HALF_M)
    sidef = _strip_max(Z, xs, mid0, *SIDE_BAND_M)
    prom = midf - sidef
    rows = (ys > head[1] + NOSE_ROW_Y_M[0]) & (ys < head[1] + NOSE_ROW_Y_M[1]) & np.isfinite(prom)
    if not rows.any():
        raise ValueError(FACE_MISSING.format(reason="no nose row"))
    front = float(np.nanmax(midf[rows]))
    rows &= midf >= front - NOSE_BEHIND_FRONT_MM / 1000.0
    k = int(np.flatnonzero(rows)[int(np.nanargmax(prom[rows]))])
    row = Z[k]
    near = np.abs(xs - mid0) < MID_SEARCH_M
    if not np.isfinite(row[near]).any():
        raise ValueError(FACE_MISSING.format(reason="no nose tip"))
    mid = float(xs[near][int(np.nanargmax(np.where(np.isfinite(row[near]), row[near], -np.inf)))])
    nose = np.array([mid, ys[k], midf[k]])
    midline = _strip_max(Z, xs, mid, 0.0, MID_HALF_M)
    win = (ys > nose[1] + NASION_ABOVE_M[0]) & (ys < nose[1] + NASION_ABOVE_M[1]) & np.isfinite(midline)
    if not win.any():
        raise ValueError(FACE_MISSING.format(reason="no nose root"))
    kn = int(np.flatnonzero(win)[int(np.nanargmin(midline[win]))])
    above_mm = (ys[kn] - nose[1]) * 1000.0
    if not NASION_GATE_MM[0] <= above_mm <= NASION_GATE_MM[1]:
        raise ValueError(FACE_MISSING.format(reason=f"the nose root lies {above_mm:.0f} mm above the nose tip, expected "
                                             f"{NASION_GATE_MM[0]:.0f}–{NASION_GATE_MM[1]:.0f} mm"))
    nasion = np.array([mid, ys[kn], midline[kn]])
    eye_y = float(nasion[1] - EYE_BELOW_NASION_M)
    pad_y = float(nasion[1] - PAD_BELOW_NASION_M)
    kb = int(np.argmin(np.abs(ys - pad_y)))
    ridge = midline[kb]
    if not np.isfinite(ridge):
        raise ValueError(FACE_MISSING.format(reason="no nose ridge at the pad height"))
    # the nose's half width: the farthest cell from the mid-plane, contiguous with it, within NOSE_WIDTH_BACK_M of
    # the ridge
    inside = np.nan_to_num(Z[kb], nan=-np.inf) > ridge - NOSE_WIDTH_BACK_M
    c0 = int(np.argmin(np.abs(xs - mid)))
    half = 0.0
    for step in (1, -1):
        j = c0
        while 0 <= j + step < len(xs) and inside[j + step]:
            j += step
        half = max(half, abs(float(xs[j]) - mid))
    return {"mid_x": mid, "nose_tip": nose, "nasion": nasion, "eye_y": eye_y, "pad_y": pad_y,
            "ridge_z": float(ridge), "nose_half_m": half + CELL_M / 2, "depth": dm}


# --- the ear ---------------------------------------------------------------------------------------------------------

def ear_info(Pw: np.ndarray, dense: np.ndarray, joint_names, bones: Dict[str, Any], side: str,
             eye_y: float) -> Dict[str, Any]:
    """The ear of ``side`` for a temple (``accessory_band.ear_anchor``): ``{found, used, top_y, front_z, back_z,
    top_above_eye_mm, why}`` — ``used`` when its top lies ``EAR_TOP_RANGE_M`` round the eye line (module
    docstring)."""
    from app.core import accessory_band as ab
    try:
        anc = ab.ear_anchor(Pw, dense, joint_names, bones, side)
    except ValueError as e:
        return {"found": False, "used": False, "why": str(e)}
    above = float(anc["top_y"]) - eye_y
    used = EAR_TOP_RANGE_M[0] <= above <= EAR_TOP_RANGE_M[1]
    return {"found": True, "used": bool(used), "top_y": float(anc["top_y"]), "front_z": float(anc["front_z"]),
            "back_z": float(anc["back_z"]), "top_above_eye_mm": round(above * 1000.0, 1),
            "why": "" if used else (f"the ear's top lies {above * 1000:.0f} mm from the eye line, expected "
                                    f"{EAR_TOP_RANGE_M[0] * 1000:.0f} to {EAR_TOP_RANGE_M[1] * 1000:.0f} mm")}


# --- outlines --------------------------------------------------------------------------------------------------------

def _superellipse(a: float, c: float, n: float, t: np.ndarray) -> np.ndarray:
    ct, st = np.cos(t), np.sin(t)
    return np.stack([a * np.sign(ct) * np.abs(ct) ** (2 / n), c * np.sign(st) * np.abs(st) ** (2 / n)], 1)


def outline(shape: str, w: float, h: float, n: int = OUTLINE_POINTS) -> np.ndarray:
    """The lens outline ``(n, 2)`` round its centre: ``u`` toward the temple, ``v`` up; counter-clockwise from the
    temporal side. ``round`` a circle of diameter ``w``; ``rectangular`` a superellipse (exponent 4.5); ``cat_eye`` a
    superellipse (3) whose upper outer quarter is raised by up to ``CAT_EYE_LIFT`` of the height (``k · u²``);
    ``aviator`` a superellipse (2.5) drawn down at the lower inner side by up to ``AVIATOR_DROP`` (the teardrop)."""
    t = 2 * np.pi * np.arange(n) / n
    a, c = w / 2, h / 2
    if shape == "round":
        return _superellipse(a, a, 2.0, t)
    if shape == "rectangular":
        return _superellipse(a, c, 4.5, t)
    if shape == "cat_eye":
        Q = _superellipse(a, c, 3.0, t)
        u, v = Q[:, 0], Q[:, 1]
        lift = CAT_EYE_LIFT * h * np.clip(u / a, 0, 1) ** 2 * np.clip(v / c, 0, 1)
        return np.stack([u, v + lift], 1)
    if shape == "aviator":
        Q = _superellipse(a, c, 2.5, t)
        u, v = Q[:, 0], Q[:, 1]
        drop = np.where(v < 0, 1.0 + AVIATOR_DROP * np.clip((a - u) / (2 * a), 0, 1), 1.0)
        return np.stack([u, v * drop], 1)
    raise ValueError(f"unknown frame shape {shape!r}")


#: The cat-eye's raised outer corner and the aviator's lower inner drop (shares of the lens height).
CAT_EYE_LIFT = 0.4
AVIATOR_DROP = 0.55


# --- the layout -------------------------------------------------------------------------------------------------------

def frame_section(spec_g: Dict[str, Any]) -> Tuple[float, float]:
    """``(in-plane half width, half depth)`` of the rim and the bridge: metal round (``rim_mm``), acetate flat
    (``rim_mm`` wide, ``ACETATE_DEPTH_M`` deep)."""
    rim = float(spec_g["rim_mm"]) / 1000.0
    if spec_g["frame"] == "acetate":
        return rim / 2, max(rim, ACETATE_DEPTH_M) / 2
    return rim / 2, rim / 2


def temple_section(spec_g: Dict[str, Any]) -> Tuple[float, float]:
    """``(half thickness to the side, half height)`` of a temple: metal round (at least ``TEMPLE_MIN_M``), acetate
    flat (``ACETATE_TEMPLE_H_M`` tall)."""
    rim = float(spec_g["rim_mm"]) / 1000.0
    if spec_g["frame"] == "acetate":
        return max(rim * 0.8, 0.002) / 2, ACETATE_TEMPLE_H_M / 2
    d = max(rim * 0.7, TEMPLE_MIN_M)
    return d / 2, d / 2


def side_reach(Q: np.ndarray, mid: float, sx: float, y: float, z: float) -> float:
    """How far to the side ``sx`` the skin samples ``Q`` reach (from the mid-plane) in the window ``SIDE_WINDOW_M``
    round height ``y`` and depth ``z``; 0 where there is none."""
    sel = (np.abs(Q[:, 1] - y) < SIDE_WINDOW_M[0]) & (np.abs(Q[:, 2] - z) < SIDE_WINDOW_M[1]) & ((Q[:, 0] - mid) * sx > 0)
    return float(((Q[sel, 0] - mid) * sx).max()) if sel.any() else 0.0


def head_samples(P: np.ndarray, F: np.ndarray, head: np.ndarray, n: int = 6) -> np.ndarray:
    """Skin samples of the head region (within 0.16 m of the Head bone head's height, in front of 0.2 m behind
    it) — the side profile the temples are laid along."""
    T = np.asarray(P, np.float64)[np.asarray(F, np.int64)]
    c = T.mean(1)
    keep = (np.abs(c[:, 1] - head[1] - 0.06) < 0.12) & (c[:, 2] > head[2] - 0.2) & (np.abs(c[:, 0] - head[0]) < 0.14)
    return sample_triangles(np.asarray(P, np.float64), np.asarray(F, np.int64)[keep], n)


def _plane_z(x, y, lm: Dict[str, Any], b: float) -> np.ndarray:
    """The lens surface's offset in z from its value at the bridge on the eye line: the wrap (``WRAP_DEG`` per side
    from the bridge) and the tilt (``TILT_DEG``, the bottom nearer the face)."""
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    wrap = -np.maximum(np.abs(x - lm["mid_x"]) - b, 0.0) * np.tan(np.radians(WRAP_DEG))
    return wrap + (y - lm["eye_y"]) * np.tan(np.radians(TILT_DEG))


def _lens_points(sx: float, uv: np.ndarray, centre_u: float, centre_y: float, z0: float,
                 lm: Dict[str, Any], b: float) -> np.ndarray:
    x = lm["mid_x"] + sx * (centre_u + uv[:, 0])
    y = centre_y + uv[:, 1]
    return np.stack([x, y, z0 + _plane_z(x, y, lm, b)], 1)


def _inside_polygon(px: np.ndarray, py: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Even-odd test of the points against the closed polygon ``poly`` (k, 2)."""
    inside = np.zeros(len(px), bool)
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    for a, b_, c, d in zip(x1, y1, x2, y2):
        cross = ((b_ > py) != (d > py)) & (px < (c - a) * (py - b_) / np.where(d - b_ == 0, 1e-12, d - b_) + a)
        inside ^= cross
    return inside


def layout(lm: Dict[str, Any], Q: np.ndarray, spec_g: Dict[str, Any], ears: Dict[str, Dict[str, Any]],
           height_m: float, push_m: float = 0.0) -> Dict[str, Any]:
    """The centre lines of the glasses for the face ``lm`` (``face_landmarks``), the head samples ``Q``
    (``head_samples``) and the ears (``ear_info`` per side) — no gate (module docstring): ``{b, W, w, h, z0, push_m,
    brow_m, lenses: {side: (n, 3)}, lens_centre: {side: point}, bridges: [(k, 3)…], temples: {side: (k, 3)},
    temple_ends: {side: "straight" | "hook" | "no_ear"}}``. ``push_m``: an extra forward shift of the front (the
    gate's). ``ValueError`` when the lens would be implausible."""
    mid = lm["mid_x"]
    shape = spec_g["shape"]
    rim_a, rim_d = frame_section(spec_g)
    t_half_w, t_half_h = temple_section(spec_g)
    b = lm["nose_half_m"] + BRIDGE_ADD_M
    y_t = lm["eye_y"] + TEMPLE_ABOVE_EYE_M
    # the lens back: at least PAD_DIST in front of the ridge; the brow inside the outline may push it forward
    z_min = lm["ridge_z"] + PAD_DIST_M + rim_d
    dm = lm["depth"]
    xs, ys = _cells(dm)
    XX, YY = np.meshgrid(xs, ys)
    # the head's width is read behind the face's own lens plane (z_min), not behind the brow-pushed one: a frame
    # shape whose outline reaches the brow must not make the whole frame narrower on the same face
    W = max(side_reach(Q, mid, sx, y_t, z_min - FRAME_DEPTH_M) for sx in (1.0, -1.0)) + FRAME_ADD_M \
        + SIZE_ADD_M[spec_g["size"]]
    w = W - b - ENDPIECE_M
    if shape == "round":
        w = min(w, ROUND_MAX_M)
    if not LENS_W_RANGE_M[0] <= w <= LENS_W_RANGE_M[1]:
        raise ValueError(IMPLAUSIBLE.format(why=f"a lens would be {w * 1000:.0f} mm wide"))
    h = w * SHAPE_RATIO[shape]
    uv = outline(shape, w, h)
    cy = lm["eye_y"] - (AVIATOR_DOWN_M if shape == "aviator" else 0.0)
    cu = b + w / 2
    # the front-most skin inside either lens outline (grown by the rim), against the lens surface there
    need = -np.inf
    for sx in (1.0, -1.0):
        grown = uv * (1 + (rim_a + GAP_M) / max(w / 2, 1e-6))
        px = (XX - mid) * sx - cu
        py = YY - cy
        m = _inside_polygon(px.ravel(), py.ravel(), grown) & np.isfinite(dm["Z"].ravel())
        if m.any():
            gx, gy, gz = XX.ravel()[m], YY.ravel()[m], dm["Z"].ravel()[m]
            need = max(need, float((gz - _plane_z(gx, gy, lm, b)).max()) + GAP_M + rim_d)
    z0 = max(z_min, need)
    brow_m = z0 - z_min
    z0 += push_m
    lenses, centres = {}, {}
    for side, sx in (("left", 1.0), ("right", -1.0)):
        lenses[side] = _lens_points(sx, uv, cu, cy, z0, lm, b)
        centres[side] = _lens_points(sx, np.zeros((1, 2)), cu, cy, z0, lm, b)[0]
    # the bridge (aviator: and a top bar) between the inner rims
    bridges = []
    targets = [0.2 * h / 2] if shape != "aviator" else [0.05 * h / 2, 0.8 * h / 2]
    for k, target in enumerate(targets):
        inner = np.flatnonzero(uv[:, 0] < 0)
        i = int(inner[np.argmin(np.abs(uv[inner, 1] - target))])
        L = lenses["left"][i]
        R = lenses["right"][i]
        top = np.array([mid, max(L[1], R[1]) + (0.003 if k == 0 else 0.001), max(L[2], R[2]) + 0.0015])
        s = np.linspace(0, 1, 17)[:, None]
        bridges.append((1 - s) ** 2 * L + 2 * s * (1 - s) * top + s ** 2 * R)
    temples, ends = {}, {}
    for side, sx in (("left", 1.0), ("right", -1.0)):
        temples[side], ends[side] = _temple(lm, Q, uv, lenses[side], sx, y_t, z0, W, t_half_w, t_half_h,
                                            ears.get(side) or {"found": False, "used": False},
                                            spec_g["temple"], height_m)
    return {"b": b, "W": W, "w": w, "h": h, "z0": z0, "push_m": push_m, "brow_m": brow_m, "lenses": lenses,
            "lens_centre": centres, "bridges": bridges, "temples": temples, "temple_ends": ends, "outline": uv,
            "lens_cy": cy, "lens_cu": cu}


def _temple(lm, Q, uv, lens, sx, y_t, z0, W, t_half_w, t_half_h, ear, temple, height_m):
    """One temple's centre line (``layout``) and how it ends."""
    mid = lm["mid_x"]
    outer = np.flatnonzero(uv[:, 0] > 0)
    i = int(outer[np.argmin(np.abs(lens[outer, 1] - y_t))])
    start = lens[i]
    clear = GAP_M + t_half_w
    if ear["found"]:
        d_front = z0 - ear["front_z"]
    else:
        d_front = NO_EAR_LENGTH_M * height_m / 1.70 - STRAIGHT_PAST_EAR_M
    used = ear["used"]
    hook = used and temple == "hook"
    y_ear = max(y_t, ear["top_y"] + t_half_h + GAP_M) if used else y_t
    d_end = d_front + (HOOK_PAST_EAR_M if hook else STRAIGHT_PAST_EAR_M)
    d0 = ENDPIECE_BACK_M
    ds = np.arange(d0, d_end + 1e-9, TEMPLE_STEP_M)
    if ds[-1] < d_end - 1e-6:
        ds = np.append(ds, d_end)
    pts = [start]
    reach = abs(start[0] - mid)
    rise_from = d_front - EAR_RISE_M
    for d in ds:
        if used and d > rise_from:
            s = min((d - rise_from) / EAR_RISE_M, 1.0)
            y = y_t + (y_ear - y_t) * (3 * s * s - 2 * s ** 3)
        else:
            y = y_t
        z = z0 - d
        reach = max(reach, W, side_reach(Q, mid, sx, y, z) + clear)
        pts.append(np.array([mid + sx * reach, y, z]))
    if hook:
        # bends down behind the ear: a quarter ellipse HOOK_DROP_M down and 0.6 of that back, in the temple's own
        # plane (the gate pushes it off the head and the ear)
        last = pts[-1]
        for a in np.linspace(0, np.pi / 2, 8)[1:]:
            pts.append(np.array([last[0], last[1] - HOOK_DROP_M * (1 - np.cos(a)),
                                 last[2] - HOOK_DROP_M * 0.6 * np.sin(a)]))
    end = "hook" if hook else ("straight" if used else "no_ear")
    return np.vstack(pts), end


# --- meshes -----------------------------------------------------------------------------------------------------------

def sweep(curve: np.ndarray, half_a: float, half_b: float, a_dirs: np.ndarray, closed: bool,
          sides: int = SECTION_SIDES) -> Tuple[np.ndarray, np.ndarray]:
    """An elliptical tube along ``curve`` ``(k, 3)``: ``half_a`` along ``a_dirs`` (per point, made square to the
    tangent), ``half_b`` along the third direction. Open curves get flat end caps. ``(V, F)``, outward wound."""
    curve = np.asarray(curve, np.float64)
    k = len(curve)
    if closed:
        T = np.roll(curve, -1, 0) - np.roll(curve, 1, 0)
    else:
        T = np.gradient(curve, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    A = np.asarray(a_dirs, np.float64)
    A = A - np.einsum("ij,ij->i", A, T)[:, None] * T
    A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)
    B = np.cross(T, A)
    ang = 2 * np.pi * (np.arange(sides) + 0.5) / sides
    V = (curve[:, None] + half_a * np.cos(ang)[None, :, None] * A[:, None]
         + half_b * np.sin(ang)[None, :, None] * B[:, None]).reshape(-1, 3)
    rings = k if closed else k - 1
    i = np.arange(rings)[:, None]
    j = np.arange(sides)[None, :]
    a = i * sides + j
    bb = ((i + 1) % k) * sides + j
    c = ((i + 1) % k) * sides + (j + 1) % sides
    d = i * sides + (j + 1) % sides
    F = np.concatenate([np.stack([a, c, bb], -1).reshape(-1, 3), np.stack([a, d, c], -1).reshape(-1, 3)])
    if not closed:
        caps = []
        for r, flip in ((0, True), (k - 1, False)):
            centre = len(V) + len(caps)
            caps.append(curve[r])
            ring = r * sides + np.arange(sides)
            tri = np.stack([np.full(sides, centre), ring, np.roll(ring, -1)], 1)
            F = np.vstack([F, tri[:, [0, 2, 1]] if flip else tri])
        V = np.vstack([V, np.asarray(caps)])
    from app.core.accessory_band import orient_outward
    return V, orient_outward(V, F.astype(np.int64))


def lens_fan(points: np.ndarray, centre: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The lens as a fan of triangles from ``centre`` to the outline ``points`` (shown from both sides)."""
    V = np.vstack([centre[None], points])
    n = len(points)
    i = np.arange(n)
    F = np.stack([np.zeros(n, np.int64), 1 + i, 1 + (i + 1) % n], 1)
    return V, F


def ellipsoid(centre: np.ndarray, axes: np.ndarray, radii: Tuple[float, float, float]) -> Tuple[np.ndarray, np.ndarray]:
    """An ellipsoid (an icosphere scaled by ``radii`` along the rows of ``axes``)."""
    from app.core.accessory_band import icosphere, orient_outward
    V, F = icosphere(1.0, 1)
    V = centre[None] + (V * np.asarray(radii)[None]) @ np.asarray(axes)
    return V, orient_outward(V, F)


# --- the build -------------------------------------------------------------------------------------------------------

def largest_component(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """The faces of the largest vertex-connected part of ``(P, F)`` — the skin; the small loose parts (eyelash and
    eye pieces) are wound any way and would flip the side of a point beside them (a frame 21 mm in front of the
    eye corner read as inside)."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(F, np.int64)
    n = len(P)
    a = np.concatenate([F[:, 0], F[:, 1], F[:, 2]])
    b = np.concatenate([F[:, 1], F[:, 2], F[:, 0]])
    _k, label = connected_components(sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n)), directed=False)
    main = int(np.bincount(label[F[:, 0]]).argmax())
    return F[label[F[:, 0]] == main]


class SkinDistance:
    """Signed distance to the skin of the closed body ``(Pw, Fw)`` near the head (``largest_component``), the faces
    looked at only within ``radius`` of ``centre`` (the face and the ears). The side comes from the angle-weighted
    pseudo-normal of the closest feature (Bærentzen & Aanæs): the face's own normal inside it, the two faces' normals
    on an edge, the angle-weighted normals round a vertex — a closest point on a crumpled vertex (an eyelid crease)
    is shared by faces facing opposite ways, and any one of them can point away from the point (a frame 21 mm in
    front of the eye corner read as inside)."""

    def __init__(self, Pw: np.ndarray, Fw: np.ndarray, centre: np.ndarray, radius: float = 0.25):
        from scipy.spatial import cKDTree
        P = np.asarray(Pw, np.float64)
        F = largest_component(P, Fw)
        vol = np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6
        if vol < 0:
            F = F[:, ::-1]
        Fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        Fn /= np.maximum(np.linalg.norm(Fn, axis=1, keepdims=True), 1e-20)
        # angle-weighted vertex normals
        VN = np.zeros_like(P)
        for c in range(3):
            e1 = P[F[:, (c + 1) % 3]] - P[F[:, c]]
            e2 = P[F[:, (c + 2) % 3]] - P[F[:, c]]
            cos = np.einsum("ij,ij->i", e1, e2) / np.maximum(np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1),
                                                              1e-20)
            np.add.at(VN, F[:, c], Fn * np.arccos(np.clip(cos, -1, 1))[:, None])
        # edge normals: the sum of the faces on the edge; edge k of a face lies opposite its corner k
        E = np.sort(np.stack([F[:, [1, 2]], F[:, [2, 0]], F[:, [0, 1]]], 1).reshape(-1, 2), 1)
        _u, inv = np.unique(E, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        EN = np.zeros((inv.max() + 1, 3))
        np.add.at(EN, inv, np.repeat(Fn, 3, 0))
        keep = np.linalg.norm(P[F].mean(1) - centre[None], axis=1) < radius
        self.P, self.F, self.Fn, self.VN = P, F[keep], Fn[keep], VN
        self.EN = EN
        self.edge = inv.reshape(-1, 3)[keep]
        self.tree = cKDTree(P[self.F].mean(1))

    def __call__(self, X: np.ndarray, kq: int = 32) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(signed distance, closest point, unit outward pseudo-normal there)`` per point of ``X``."""
        from app.core.garment_fit import point_triangle_closest
        X = np.asarray(X, np.float64)
        kq = min(kq, len(self.F))
        _, cand = self.tree.query(X, k=kq)
        cand = cand.reshape(len(X), -1)
        best = np.full(len(X), np.inf)
        cps = np.array(X)
        face = np.zeros(len(X), np.int64)
        for j in range(cand.shape[1]):
            f = self.F[cand[:, j]]
            cp = point_triangle_closest(X, self.P[f[:, 0]], self.P[f[:, 1]], self.P[f[:, 2]])
            d = np.linalg.norm(X - cp, axis=1)
            better = d < best
            best = np.where(better, d, best)
            cps = np.where(better[:, None], cp, cps)
            face = np.where(better, cand[:, j], face)
        tri = self.P[self.F[face]]
        bary = _barycentric(cps, tri)
        nrm = self.Fn[face].copy()
        zero = bary < BARY_EPS
        on_edge = zero.sum(1) == 1
        at_vertex = zero.sum(1) >= 2
        if on_edge.any():
            k = zero[on_edge].argmax(1)
            nrm[on_edge] = self.EN[self.edge[face[on_edge], k]]
        if at_vertex.any():
            k = bary[at_vertex].argmax(1)
            nrm[at_vertex] = self.VN[self.F[face[at_vertex], k]]
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        sgn = np.where(np.einsum("ij,ij->i", X - cps, nrm) < 0, -1.0, 1.0)
        return best * sgn, cps, nrm


#: A closest point whose barycentric coordinate is below this lies on that coordinate's opposite edge.
BARY_EPS = 1e-6


def _barycentric(X: np.ndarray, T: np.ndarray) -> np.ndarray:
    """Barycentric coordinates ``(n, 3)`` of the points ``X`` (on their triangles ``T`` (n, 3, 3))."""
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    v0, v1, v2 = b - a, c - a, X - a
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("ij,ij->i", v2, v0)
    d21 = np.einsum("ij,ij->i", v2, v1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-30, 1e-30, d00 * d11 - d01 * d01)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.stack([1 - v - w, v, w], 1)


class FaceDistance:
    """``SkinDistance`` made safe in front of and beside the face: a point in front of the front-most skin of its
    depth-map cell (``face_landmarks``' ``depth``), or farther to its side than the skin reaches in its side-map cell
    (``SIDE_CELL_M``, from the head samples), is outside whatever the pseudo-normal says. The skin of these bodies has
    open seams and folds round the eyes where the pseudo-normal still points the wrong way (a rim 4 mm in front of the
    brow read 11 mm inside)."""

    def __init__(self, sd: SkinDistance, lm: Dict[str, Any], Q: np.ndarray):
        self.sd = sd
        self.dm = lm["depth"]
        self.mid = lm["mid_x"]
        Q = np.asarray(Q, np.float64)
        self.y0, self.z0 = float(Q[:, 1].min()), float(Q[:, 2].min())
        ny = int((Q[:, 1].max() - self.y0) / SIDE_CELL_M) + 1
        nz = int((Q[:, 2].max() - self.z0) / SIDE_CELL_M) + 1
        iy = ((Q[:, 1] - self.y0) / SIDE_CELL_M).astype(np.int64)
        iz = ((Q[:, 2] - self.z0) / SIDE_CELL_M).astype(np.int64)
        self.side = {}
        for sx in (1.0, -1.0):
            L = np.full((ny, nz), -np.inf)
            np.maximum.at(L, (iy, iz), (Q[:, 0] - self.mid) * sx)
            self.side[sx] = L

    def outside(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, np.float64)
        Z = self.dm["Z"]
        ix = np.floor((X[:, 0] - self.dm["x0"]) / CELL_M).astype(np.int64)
        iy = np.floor((X[:, 1] - self.dm["y0"]) / CELL_M).astype(np.int64)
        ok = (ix >= 0) & (ix < Z.shape[1]) & (iy >= 0) & (iy < Z.shape[0])
        zf = np.full(len(X), np.nan)
        zf[ok] = Z[iy[ok], ix[ok]]
        front = np.isfinite(zf) & (X[:, 2] > zf)
        out = front.copy()
        for sx, L in self.side.items():
            jy = ((X[:, 1] - self.y0) / SIDE_CELL_M).astype(np.int64)
            jz = ((X[:, 2] - self.z0) / SIDE_CELL_M).astype(np.int64)
            inn = (jy >= 0) & (jy < L.shape[0]) & (jz >= 0) & (jz < L.shape[1]) & ((X[:, 0] - self.mid) * sx > 0)
            reach = np.full(len(X), np.inf)
            reach[inn] = L[jy[inn], jz[inn]]
            out |= inn & ((X[:, 0] - self.mid) * sx > reach)
        return out

    def __call__(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(signed distance, closest point, outward direction)``: the direction is the line from the closest point
        through ``X`` (away from the skin outside, toward and through it inside) — the face normal of a folded
        vertex can point anywhere — and the pseudo-normal only where ``X`` lies on the skin."""
        X = np.asarray(X, np.float64)
        d, cp, n = self.sd(X)
        d = np.where(self.outside(X) & (d < 0), -d, d)
        away = X - cp
        length = np.linalg.norm(away, axis=1)
        line = away / np.maximum(length, 1e-12)[:, None] * np.where(d < 0, -1.0, 1.0)[:, None]
        n = np.where((length > 1e-6)[:, None], line, n)
        return d, cp, n


#: The side map's cell (``FaceDistance``).
SIDE_CELL_M = 0.002


def _clear_line(curve: np.ndarray, sd: "FaceDistance", clearance: float, fixed: int = 0, passes: int = 8) -> np.ndarray:
    """``curve`` with every point but the first ``fixed`` moved off the skin along the skin's normal until it is at
    least ``clearance`` away."""
    X = np.array(curve, np.float64)
    for _ in range(passes):
        d, _cp, n = sd(X)
        short = d < clearance - 1e-5
        short[:fixed] = False
        if not short.any():
            break
        X[short] += n[short] * (clearance - d[short] + 1e-4)[:, None]
    return X


def _temple_mesh(curve: np.ndarray, sx: float, t_half_w: float, t_half_h: float) -> Tuple[np.ndarray, np.ndarray]:
    """A temple: its thickness to the side (``t_half_w`` along x), its height up (``t_half_h``)."""
    side = np.tile(np.array([sx, 0.0, 0.0]), (len(curve), 1))
    return sweep(curve, t_half_w, t_half_h, side, closed=False)


def build(body, dense, Pw: np.ndarray, Fw: np.ndarray, first: np.ndarray, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The glasses of ``spec`` (normalized, kind ``glasses``) on the body (``accessory_build._body_context``): ``{V,
    F, N, temple_faces, lens: {V, F, N}, curve, landmarks, metrics, layout}`` — every vertex rigid on the Head (the
    caller skins it). ``ValueError`` naming why it does not fit (module docstring)."""
    from app.core.accessory_curve import vertex_normals
    g = spec["glasses"]
    P = np.asarray(body.positions, np.float64)
    F = np.asarray(body.faces, np.int64)
    height = float(np.ptp(P[:, 1]))
    head = _bone(body.joint_positions, "head")
    lm = face_landmarks(P, F, body.joint_positions)
    Q = head_samples(P, F, head)
    ears = {side: ear_info(Pw, dense[first], body.joint_names, body.joint_positions, side, lm["eye_y"])
            for side in ("left", "right")}
    sd = FaceDistance(SkinDistance(Pw, Fw, lm["nose_tip"]), lm, Q)
    rim_a, rim_d = frame_section(g)
    t_half_w, t_half_h = temple_section(g)
    # the front (rims, bridge, lenses) clears the face: moved forward until it does, at most MAX_PUSH_M in all
    push = 0.0
    for _ in range(8):
        lay = layout(lm, Q, g, ears, height, push_m=push)
        if lay["brow_m"] + push > MAX_PUSH_M + 1e-6:
            raise ValueError(REFUSE_BROW.format(mm=(lay["brow_m"] + push) * 1000.0))
        front = _front_meshes(lay, rim_a, rim_d)
        d = float(sd(np.vstack([v for v, _f in front]))[0].min())
        if d >= GAP_MIN_M:
            break
        push += GAP_M - d + 1e-4
    else:
        raise ValueError(IMPLAUSIBLE.format(why="the frame does not clear the face"))
    lay["push_m"] = push
    parts: List[Tuple[np.ndarray, np.ndarray, bool]] = [(v, f, False) for v, f in front]
    # nose pads and their arms
    pads = _pads(lm, lay, sd, g)
    parts += [(v, f, False) for v, f in pads["meshes"]]
    # the temples
    lengths, temple_gap = {}, []
    for side, sx in (("left", 1.0), ("right", -1.0)):
        curve = _clear_line(lay["temples"][side], sd, GAP_M + t_half_w + 1e-4, fixed=2)
        # never bent inwards again after the push (the running maximum of the side offset)
        off = np.maximum.accumulate((curve[:, 0] - lm["mid_x"]) * sx)
        curve[:, 0] = lm["mid_x"] + sx * off
        for _ in range(6):
            V, Ft = _temple_mesh(curve, sx, t_half_w, t_half_h)
            dv = sd(V)[0]
            if float(dv.min()) >= GAP_MIN_M:
                break
            # the ring (SECTION_SIDES vertices per centre-line point) that comes too close moves out sideways
            sides = SECTION_SIDES
            per = dv[:len(curve) * sides].reshape(len(curve), sides).min(1)
            low = per < GAP_MIN_M
            low[:2] = False
            if not low.any():
                break
            curve[low, 0] += sx * (GAP_M - per[low] + 1e-4)
        lay["temples"][side] = curve
        lengths[side] = round(float(np.linalg.norm(np.diff(curve, axis=0), axis=1).sum()) * 1000.0, 1)
        temple_gap.append(float(sd(V)[0].min()))
        parts.append((V, Ft, True))
    # assemble
    Vs, Fs, mask = [], [], []
    for V, Fp, is_temple in parts:
        Fs.append(Fp + sum(len(v) for v in Vs))
        Vs.append(V)
        mask.append(np.full(len(Fp), is_temple))
    Vf, Ff = np.vstack(Vs), np.vstack(Fs).astype(np.int64)
    temple_faces = np.concatenate(mask)
    lens_V, lens_F = [], []
    for side in ("left", "right"):
        v, f = lens_fan(lay["lenses"][side], lay["lens_centre"][side])
        lens_F.append(f + sum(len(x) for x in lens_V))
        lens_V.append(v)
    LV, LF = np.vstack(lens_V), np.vstack(lens_F).astype(np.int64)
    # the gate: frame and temples GAP_MIN_M off the body, the pads PAD_MIN_M
    pad_n = sum(len(v) for v, _f in pads["meshes"])
    n_front = sum(len(v) for v, _f in front)
    dist = sd(Vf)[0]
    lens_d = sd(LV)[0]
    rest = np.concatenate([dist[:n_front], dist[n_front + pad_n:], lens_d])
    pad_d = dist[n_front:n_front + pad_n]
    why = []
    if float(rest.min()) < GAP_MIN_M - 1e-6:
        why.append(f"the frame comes within {max(float(rest.min()), 0.0) * 1000:.1f} mm of the head")
    if pad_n and float(pad_d.min()) < PAD_MIN_M - 1e-6:
        why.append(f"a nose pad comes within {max(float(pad_d.min()), 0.0) * 1000:.1f} mm of the nose")
    if why:
        raise ValueError(IMPLAUSIBLE.format(why="; ".join(why)))
    curve = np.vstack([lay["lenses"]["left"], lay["lenses"]["right"]])
    metrics = {
        "frame_mm": round(lay["W"] * 2000.0, 1), "lens_mm": [round(lay["w"] * 1000.0, 1), round(lay["h"] * 1000.0, 1)],
        "bridge_mm": round(lay["b"] * 2000.0, 1), "arms_mm": lengths,
        "forward_mm": round((lay["brow_m"] + push) * 1000.0, 1),
        "ear_used": {s: bool(e["used"]) for s, e in ears.items()},
        "ear_note": {s: e.get("why", "") for s, e in ears.items() if not e["used"]},
        # the same reason as numbers, for a translated line in the dialog: the ear's top above the eye line (None =
        # no ear found on that side) and the accepted range
        "ear_above_mm": {s: e.get("top_above_eye_mm") for s, e in ears.items() if not e["used"]},
        "ear_range_mm": [round(EAR_TOP_RANGE_M[0] * 1000.0), round(EAR_TOP_RANGE_M[1] * 1000.0)],
        "temple_ends": dict(lay["temple_ends"]),
        "gap_mm": {"min": round(float(rest.min()) * 1000.0, 2), "p50": round(float(np.median(rest)) * 1000.0, 2)},
        "pad_gap_mm": round(float(pad_d.min()) * 1000.0, 2) if pad_n else None,
        "inside_share": 0.0, "triangles": int(len(Ff) + len(LF)), "vertices": int(len(Vf) + len(LV)),
        "height_m": round(height, 3)}
    landmarks = {"nose_tip": np.round(lm["nose_tip"], 5).tolist(), "nasion": np.round(lm["nasion"], 5).tolist(),
                 "eye_y": round(lm["eye_y"], 5), "pad_y": round(lm["pad_y"], 5), "mid_x": round(lm["mid_x"], 5),
                 "nose_half_mm": round(lm["nose_half_m"] * 1000.0, 1),
                 "ears": {s: {k: (round(v, 5) if isinstance(v, float) else v) for k, v in e.items()}
                          for s, e in ears.items()}}
    return {"V": Vf, "F": Ff, "N": vertex_normals(Vf, Ff), "temple_faces": temple_faces,
            "lens": {"V": LV, "F": LF, "N": vertex_normals(LV, LF)}, "curve": curve, "landmarks": landmarks,
            "metrics": metrics, "layout": lay}


def _front_meshes(lay: Dict[str, Any], rim_a: float, rim_d: float) -> List[Tuple[np.ndarray, np.ndarray]]:
    """The rims (closed, the in-plane half width along the outline's outward side) and the bridge bars."""
    out = []
    for side in ("left", "right"):
        line = lay["lenses"][side]
        out.append(sweep(line, rim_a, rim_d, line - lay["lens_centre"][side][None], closed=True))
    for bar in lay["bridges"]:
        up = np.tile(np.array([0.0, 1.0, 0.0]), (len(bar), 1))
        out.append(sweep(bar, rim_a, rim_d, up, closed=False))
    return out


def _finite_mean(a: np.ndarray) -> float:
    """The mean of the finite entries, NaN when there are none."""
    a = a[np.isfinite(a)]
    return float(a.mean()) if a.size else float("nan")


def _pads(lm: Dict[str, Any], lay: Dict[str, Any], sd: "FaceDistance", g: Dict[str, Any]) -> Dict[str, Any]:
    """The nose pads on the nose flanks at the pad height, ``PAD_GAP_M`` off the skin, each with an arm to the nearest
    point of its inner rim."""
    dm = lm["depth"]
    xs, ys = _cells(dm)
    kb = int(np.argmin(np.abs(ys - lm["pad_y"])))
    r_arm = ARM_RADIUS_M[g["frame"]]
    meshes, centres = [], {}
    Z = dm["Z"]
    for side, sx in (("left", 1.0), ("right", -1.0)):
        # on the nose's front surface (the depth map — the mesh can carry inner sheets behind it), its normal from
        # the map's slope over +-2 cells
        x = lm["mid_x"] + sx * lm["nose_half_m"] * 0.8
        j = int(np.argmin(np.abs(xs - x)))
        z = Z[kb, j]
        if not np.isfinite(z):
            raise ValueError(IMPLAUSIBLE.format(why="no nose surface where a pad sits"))
        win = Z[kb - 2:kb + 3, j - 2:j + 3]
        dzdx = _finite_mean(win[:, 4] - win[:, 0]) / (4 * CELL_M)
        dzdy = _finite_mean(win[4, :] - win[0, :]) / (4 * CELL_M)
        n = _unit([-dzdx if np.isfinite(dzdx) else -sx, -dzdy if np.isfinite(dzdy) else 0.0, 1.0])
        cp = np.array([xs[j], ys[kb], z])
        up = _unit(np.array([0.0, 1.0, 0.0]) - n[1] * n)
        across = np.cross(n, up)
        centre = cp + n * (PAD_GAP_M + PAD_AXES_M[0])
        axes = np.stack([n, up, across])
        for _ in range(6):
            V, F = ellipsoid(centre, axes, PAD_AXES_M)
            d = float(sd(V)[0].min())
            if d >= PAD_GAP_M - 5e-5:
                break
            centre = centre + n * (PAD_GAP_M - d + 5e-5)
        meshes.append((V, F))
        centres[side] = centre
        # the arm: from the pad's outer face to the nearest inner rim point, bowed away from the nose
        rim = lay["lenses"][side]
        inner = np.flatnonzero(lay["outline"][:, 0] < 0)
        k = int(inner[np.argmin(np.linalg.norm(rim[inner] - centre[None], axis=1))])
        a, c = centre + n * PAD_AXES_M[0], rim[k]
        ctrl = (a + c) / 2 + n * 0.003
        s = np.linspace(0, 1, 9)[:, None]
        arm = (1 - s) ** 2 * a + 2 * s * (1 - s) * ctrl + s ** 2 * c
        arm = _clear_line(arm, sd, PAD_GAP_M + r_arm + 1e-4, fixed=0)
        meshes.append(sweep(arm, r_arm, r_arm, np.tile(np.array([0.0, 1.0, 0.0]), (len(arm), 1)), closed=False))
    return {"meshes": meshes, "centres": centres}
