"""A228 — a shaping bodice lifts and gathers the chest under it (push-up / corset).

A template top or dress whose ``outfit_piece.lift`` (the "Lift" slider, 0..1) is above zero shapes the BODY under it
before it is draped: the chest tissue slides up along the chest wall by ``LIFT_SHARE`` x lift of its own vertical
extent and gathers a little toward the middle, keeping its volume and its round shape. The cloth then drapes over the
shaped body (``garment_template._build_drape`` drapes on a shaped copy of the plain body), and the assembly of a worn
set that holds the piece moves the shown body the same way (``garment_assembly``), so the figure under the piece, the
skin the piece leaves open and the drape agree. Only positions move: faces, UVs, skin weights and morph targets stay,
so the skinning is the plain body's. The bare body file is never changed — the shaping exists only in a drape's
scratch copy and in an assembled worn set.

Version 4 (review of v3, 2026-11-22): v3 lifted the whole chest as one block and let the skin over its root take
the compression up to 15 cm over the root — past the shoulder line, so the shoulders and the collarbone moved (up to
75 mm) and faces turned over there; its depth fade of 4 cm sheared the overhanging underside at the outer edge
(32 faces turned over at lift 0.7). Version 4 keeps every vertex above the shoulder line where it is: the motion
runs out on a straight ramp (rounded ends) from ``UPPER_START_M`` above the apex up to the shoulder line, so the
upper part of the chest takes the compression and fills, the way a corset gathers it upward. A compressed column
grows forward by at most ``FILL_CAP_M`` x the compression (``g_c``), never in proportion to its depth: an exactly
volume-keeping fill pushed the upper part out into a forward wedge (render 2026-11-22). The volume stays within a few
per cent (``scripts/smoke_bust_shaping.py`` gates >= 0.95), and the lift is what the user asked for: the apex rises
by ``share`` x ``extent_m``, share = min(lift x ``LIFT_SHARE``, ``ROOM_SHARE`` x (cap_y - apex_y) / extent_m) — the
slider's 0..1 is 0..50 % of the chest's own height, capped by the room up to the shoulder line (past it the upper
part turned into a flat shelf). ``D`` is solved so that the flow carries the apex up by exactly that.

The ``landmarks`` are measured once on the plain body (glTF Y-up metres, front = +Z; ``_column_landmarks``): per side
the apex (the most forward chest point), the fold under it (``_fold_below``, as ``garment_template_fitted._fold``)
and the root above it (where the protrusion in front of the chest wall falls under ``ROOT_P_M``); ``fold_y`` /
``apex_y`` / ``root_y`` are the means of both sides, ``extent_m`` = root_y - fold_y, ``cap_y`` the shoulder line.
The chest wall ``wall_z`` is the most forward point of the slice at the fold per ``WALL_STEP_M`` of distance from the
middle. The field is a pure function of a vertex's position and the landmarks, so the full and the low tier
(different vertices) shape alike.

In the coordinates X = x - centre_x, y, p = z - wall(x) (a shear of x, y, z):

    D      = solved: the flow lifts the apex by share * extent_m * min(1, depth_m / FULL_DEPTH_M)
    G      = lift * GATHER * min(1, depth_m / FULL_DEPTH_M)                       (the gathering rate)
    m(y)   = S(y; fold_y - BELOW_M, fold_y + RISE_M) * (1 - R(y; up0, cap_y)),   up0 = apex_y + UPPER_START_M
    R      = a straight ramp 0 -> 1 from up0 to cap_y whose ends are rounded over ``RAMP_ROUND_M``
    k(X)   = 1 - S(|X|; off + SIDE_PAST_M),  off = mean |apex_x - centre_x| of both sides
    g'(p)  = S(p; -BACK_M, FRONT_M),  g(p) = integral of g' from -BACK_M,  g_c = FILL_CAP_M * tanh(g / FILL_CAP_M)
    s(X)   = X * (1 - S(|X|; GATHER_SIDE_M))
    v_x    = -G * s(X) * m(y) * g'(p)
    v_y    =  D * m(y) * k(X) * g'(p)
    v_p    = -D * m'(y) * k(X) * g_c(p)  +  G * s'(X) * m(y) * g(p)

(S = smoothstep). Where g < FILL_CAP_M (the skin near the wall) div v = 0; deeper in the compressed upper part it
keeps less than all of its volume. The positions are the flow of v over unit time (``STEPS`` classic Runge-Kutta
steps). Behind the wall by more than ``BACK_M`` (the back, the arms' undersides), farther than
``off + SIDE_PAST_M[1]`` from the middle and above ``cap_y`` nothing moves.
``scripts/smoke_bust_shaping.py`` derives the numbers by hand.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

import numpy as np

#: Bump when the field changes: it is part of every shaped drape's key.
VERSION = 4
#: The lift at lift 1 as a share of the chest's own vertical extent (fold -> root): the slider's 0..1 is 0..50 %.
LIFT_SHARE = 0.5
#: The gathering rate toward the middle at lift 1: the chest's distance from the middle shrinks by e^-GATHER (10 %).
GATHER = 0.1
#: The chest depth (``landmarks`` ``depth_m``: the largest protrusion in front of the chest wall between the fold
#: and the root) from which the shaping is full; a shallower chest takes the share it has.
FULL_DEPTH_M = 0.08
#: The ramp of m under the fold (from fold - BELOW_M up to fold + RISE_M): the rib cage skin there stretches.
BELOW_M = 0.06
RISE_M = 0.01
#: Where the motion starts running out above the apex (metres): the ramp of m runs from apex_y + this up to the
#: shoulder line (``cap_y``), so the upper part of the chest takes the compression.
UPPER_START_M = 0.06
#: The rounded ends of that ramp (metres).
RAMP_ROUND_M = 0.05
#: The apex rises at most this share of its distance to the shoulder line (past ~0.4 the compressed upper part
#: turned into a flat shelf on a full chest, render 2026-11-22).
ROOM_SHARE = 0.4
#: The forward fill of a compressed column is capped at this (metres, ``g_c``).
FILL_CAP_M = 0.04
#: The sideways fade of the lift, measured past the apex's distance from the body's middle (metres): full inside the
#: first, none beyond the second (scales with the chest's width; a narrower fade sheared the tissue's outer side into
#: a crease, render 2026-11-22).
SIDE_PAST_M = (0.06, 0.15)
#: ``landmarks``: the chest's depth is measured within this distance of the body's middle (metres).
DEPTH_HALF_M = 0.15
#: The sideways fade of the gathering (metres).
GATHER_SIDE_M = (0.12, 0.24)
#: The depth behind the chest wall over which the motion fades out (metres): the underside of the chest and the
#: cleavage lie at or just behind the wall and move with the tissue; the flanks and the back lie far behind it.
BACK_M = 0.06
#: ... and reaches full in front of the wall by this much (metres): a fade over 6 cm into the tissue keeps the
#: overhanging underside at the outer edge from shearing over (v3 had 4 cm and none: 32 faces turned at lift 0.7).
FRONT_M = 0.02
#: Runge-Kutta steps of the flow.
STEPS = 32
#: Bisection steps that solve ``D`` for the asked apex rise.
SOLVE_STEPS = 32
#: The root: the first height over the apex where the protrusion in front of the wall falls under this (metres).
ROOT_P_M = 0.005
#: The landmark columns: vertices within this half width of the apex's x, sampled every COLUMN_STEP_M in height
#: (each sample the most forward vertex within COLUMN_SLICE_M of the height).
COLUMN_HALF_M = 0.008
COLUMN_STEP_M = 0.004
COLUMN_SLICE_M = 0.005
#: The fold is looked for this far under the apex (``_fold_below``).
FOLD_SCAN_M = 0.16
#: The apex is looked for this far from the middle (metres) and from the waist + APEX_ABOVE_WAIST_M up to the
#: shoulder line - APEX_BELOW_SHOULDER_M.
APEX_X_M = (0.03, 0.16)
APEX_ABOVE_WAIST_M = 0.02
APEX_BELOW_SHOULDER_M = 0.04
#: The kinds of template piece that shape the chest.
SHAPING_KINDS = ("top", "dress")
#: The chest-wall bins (``landmarks``): this wide, this many from the middle out.
WALL_STEP_M = 0.02
WALL_BINS = 11
WALL_SLICE_M = 0.005
#: How far the chest wall may fall back from one bin to the next outward (metres; slope 0.6).
WALL_MAX_DROP_M = 0.012


def _smoothstep(v, a: float, b: float):
    t = np.clip((np.asarray(v, np.float64) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _smoothstep_d(v, a: float, b: float):
    """d/dv of ``_smoothstep``."""
    t = (np.asarray(v, np.float64) - a) / (b - a)
    return np.where((t > 0.0) & (t < 1.0), 6.0 * t * (1.0 - t) / (b - a), 0.0)


def _smoothstep_i(v, a: float, b: float):
    """The integral of ``_smoothstep`` from ``a`` to ``v`` (0 under ``a``; (b - a) / 2 + (v - b) over ``b``)."""
    v = np.asarray(v, np.float64)
    t = np.clip((v - a) / (b - a), 0.0, 1.0)
    return (b - a) * (t ** 3 - t ** 4 / 2.0) + np.maximum(v - b, 0.0)


def lift_of(item: Optional[Dict[str, Any]]) -> float:
    """The piece's ``outfit_piece.lift`` (0 when absent or invalid)."""
    try:
        value = float(((item or {}).get("outfit_piece") or {}).get("lift") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, value)) if np.isfinite(value) else 0.0


def applies(params: Optional[Dict[str, Any]], lift: float) -> bool:
    """Whether a template piece with ``params`` and ``lift`` shapes the chest under it."""
    return bool(params) and params.get("kind") in SHAPING_KINDS and lift > 0.0


def _column(P, x: float, y0: float, y1: float):
    """The front of the body along the vertical line at ``x``: ``(heights, z)`` every ``COLUMN_STEP_M`` from ``y0``
    toward ``y1`` (either direction), each the most forward vertex within ``COLUMN_HALF_M`` / ``COLUMN_SLICE_M``;
    heights without a vertex are left out."""
    near = P[(np.abs(P[:, 0] - x) < COLUMN_HALF_M) & (P[:, 1] > min(y0, y1) - COLUMN_SLICE_M)
             & (P[:, 1] < max(y0, y1) + COLUMN_SLICE_M)]
    step = COLUMN_STEP_M if y1 >= y0 else -COLUMN_STEP_M
    ys, zs = [], []
    for y in np.arange(y0, y1 + 0.5 * step, step):
        sl = near[np.abs(near[:, 1] - y) < COLUMN_SLICE_M]
        if len(sl):
            ys.append(float(y))
            zs.append(float(sl[:, 2].max()))
    return np.array(ys), np.array(zs)


def _fold_below(P, apex) -> Optional[float]:
    """The height of the fold under ``apex`` (as ``garment_template_fitted._fold``): going down the front from the
    apex, the first height after the steepest recession where the front recedes less than a fifth as fast; None
    without a recession of 4 mm per step."""
    ys, zs = _column(P, float(apex[0]), float(apex[1]), float(apex[1]) - FOLD_SCAN_M)
    if len(zs) < 5:
        return None
    dz = -np.diff(zs)                        # > 0: the front recedes going down
    k = int(np.argmax(dz))
    if dz[k] < 0.004:
        return None
    for i in range(k + 1, len(dz)):
        if dz[i] < 0.2 * dz[k]:
            return float(ys[i])
    return None


def _wall(P, centre_x: float, fold_y: float) -> list:
    """``wall_z``: per ``WALL_STEP_M`` of distance from the middle the most forward point of the slice at the fold
    (+- half a bin, both sides, ``WALL_SLICE_M`` thick) — at the fold the slice is the rib cage. A bin past the rib
    cage's side holds the last one; the wall falls back at most ``WALL_MAX_DROP_M`` per bin outward."""
    sl = P[(np.abs(P[:, 1] - fold_y) < WALL_SLICE_M) & (np.abs(P[:, 0] - centre_x) < WALL_BINS * WALL_STEP_M)]
    wall: list = []
    for k in range(WALL_BINS):
        d = np.abs(sl[:, 0] - centre_x)
        near = sl[(d >= k * WALL_STEP_M) & (d < (k + 1) * WALL_STEP_M)]
        wall.append(float(near[:, 2].max()) if len(near) else None)
    known = [k for k, w in enumerate(wall) if w is not None]
    if not known:
        raise ValueError("the body has no chest wall at the fold")
    for k in range(WALL_BINS):
        if wall[k] is None:
            wall[k] = wall[known[0]] if k < known[0] else wall[known[-1]]
    for k in range(1, WALL_BINS):
        wall[k] = max(wall[k], wall[k - 1] - WALL_MAX_DROP_M)
    return [round(float(w), 4) for w in wall]


def _apex_band(meas: Dict[str, Any]):
    """The heights the apex is looked for between (``APEX_ABOVE_WAIST_M`` / ``APEX_BELOW_SHOULDER_M``)."""
    return (float(meas["waist_y"]) + APEX_ABOVE_WAIST_M,
            float(meas.get("shoulder_y", float(meas["band_y"]) + 0.09)) - APEX_BELOW_SHOULDER_M)


def chest_apex(positions, meas: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """``{l, r: [x, y, z]}`` — per side the most forward vertex ``APEX_X_M`` from the middle (the spine's x) within
    ``_apex_band``. ValueError when a side has none. Also read by ``garment_template.measure_body`` (a strapless top's
    cup line, on whatever body it drapes on)."""
    P = np.asarray(positions, np.float64)
    centre_x = float(((meas.get("joints") or {}).get("spine2") or [0.0])[0])
    y_lo, y_hi = _apex_band(meas)
    d = P[:, 0] - centre_x
    region = (np.abs(d) > APEX_X_M[0]) & (np.abs(d) < APEX_X_M[1]) & (P[:, 1] > y_lo) & (P[:, 1] < y_hi)
    out = {}
    for name, sign in (("l", 1.0), ("r", -1.0)):
        R = P[region & (np.sign(d) == sign)]
        if not len(R):
            raise ValueError("the body has no chest region")
        out[name] = R[int(np.argmax(R[:, 2]))]
    return out


def landmarks(positions, meas: Dict[str, Any]) -> Dict[str, Any]:
    """The plain body's chest landmarks (module docstring): ``centre_x`` (the spine's x), ``apex`` {l, r: [x, y, z]},
    ``fold_y`` / ``apex_y`` / ``root_y`` (means of both sides), ``extent_m``, ``cap_y`` (the shoulder line, nothing
    above it moves), ``wall_z`` and ``depth_m`` (the largest
    protrusion in front of the wall between the fold and the root within ``DEPTH_HALF_M`` of the middle). A side whose
    fold cannot be found takes the other's; neither = the band less 15 cm. ValueError without a chest region."""
    P = np.asarray(positions, np.float64)
    centre_x = float(((meas.get("joints") or {}).get("spine2") or [0.0])[0])
    y_hi = _apex_band(meas)[1]
    d = P[:, 0] - centre_x
    apex = chest_apex(P, meas)
    folds = {name: _fold_below(P, a) for name, a in apex.items()}
    found = [f for f in folds.values() if f is not None]
    fold_y = float(np.mean(found)) if found else float(meas["band_y"]) - 0.15
    wall = _wall(P, centre_x, fold_y)
    lm: Dict[str, Any] = {"centre_x": round(centre_x, 4), "wall_z": wall}
    roots = []
    for a in apex.values():
        ys, zs = _column(P, float(a[0]), float(a[1]), y_hi)
        prot = zs - wall_at(np.full(len(zs), float(a[0])), lm)
        low = np.where(prot < ROOT_P_M)[0]
        roots.append(float(ys[low[0]]) if len(low) else y_hi)
    apex_y = float(np.mean([a[1] for a in apex.values()]))
    root_y = max(float(np.mean(roots)), apex_y)
    fold_y = min(fold_y, apex_y)
    inside = (P[:, 1] > fold_y) & (P[:, 1] < root_y) & (np.abs(d) < DEPTH_HALF_M)
    depth = float((P[inside, 2] - wall_at(P[inside, 0], lm)).max()) if inside.any() else 0.0
    return {"centre_x": round(centre_x, 4), "wall_z": wall,
            "apex": {k: [round(float(v), 4) for v in a] for k, a in apex.items()},
            "fold_y": round(fold_y, 4), "apex_y": round(apex_y, 4), "root_y": round(root_y, 4),
            "extent_m": round(root_y - fold_y, 4), "depth_m": round(max(0.0, depth), 4),
            "cap_y": round(float(meas.get("shoulder_y", float(meas["band_y"]) + 0.09)), 4)}


def wall_at(x, lm: Dict[str, Any]) -> np.ndarray:
    """The chest wall's front ``z`` at ``x``: ``wall_z`` (one value per ``WALL_STEP_M`` of distance from the middle,
    bin centres) interpolated, the last bin held beyond."""
    wall = lm["wall_z"]
    if not isinstance(wall, (list, tuple)):
        return np.full(np.shape(x), float(wall))
    centres = (np.arange(len(wall)) + 0.5) * WALL_STEP_M
    return np.interp(np.abs(np.asarray(x, np.float64) - lm["centre_x"]), centres, np.asarray(wall, np.float64))


def _ramp(y, a: float, b: float, e: float):
    """0 under ``a``, 1 over ``b``, a straight line between whose ends are rounded over ``e`` (slope 1 / (b - a - e))."""
    return (_smoothstep_i(y, a, a + e) - _smoothstep_i(y, b - e, b)) / ((b - a) - e)


def _ramp_d(y, a: float, b: float, e: float):
    """d/dy of ``_ramp``."""
    return (_smoothstep(y, a, a + e) - _smoothstep(y, b - e, b)) / ((b - a) - e)


def share_of(lm: Dict[str, Any], lift: float) -> float:
    """The apex's rise as a share of ``extent_m`` (module docstring): lift x ``LIFT_SHARE`` x the depth factor,
    capped by ``ROOM_SHARE`` of the room up to the shoulder line."""
    depth = min(1.0, float(lm.get("depth_m", FULL_DEPTH_M)) / FULL_DEPTH_M)
    room = ROOM_SHARE * max(0.0, float(lm["cap_y"]) - float(lm["apex_y"])) / max(float(lm["extent_m"]), 1e-6)
    return max(0.0, min(float(lift) * LIFT_SHARE * depth, room))


def amounts(lm: Dict[str, Any], lift: float) -> Dict[str, float]:
    """The field's numbers for ``lift`` (module docstring): ``D`` (solved, metres), ``G`` (the gathering rate), the
    ramps of m (``lo0`` / ``lo1`` / ``up0`` / ``cap``), the sideways fade of k (``side0`` / ``side1``) and the asked
    apex rise ``rise`` (metres)."""
    depth = min(1.0, float(lm.get("depth_m", FULL_DEPTH_M)) / FULL_DEPTH_M)
    off = float(np.mean([abs(float(v[0]) - float(lm["centre_x"])) for v in lm["apex"].values()]))
    cap = float(lm["cap_y"])
    a = {"D": 0.0, "side0": off + SIDE_PAST_M[0], "side1": off + SIDE_PAST_M[1], "G": float(lift) * GATHER * depth,
         "lo0": float(lm["fold_y"]) - BELOW_M, "lo1": float(lm["fold_y"]) + RISE_M,
         "up0": min(float(lm["apex_y"]) + UPPER_START_M, cap - 2.0 * RAMP_ROUND_M), "cap": cap,
         "rise": share_of(lm, lift) * float(lm["extent_m"])}
    if a["rise"] <= 0.0:
        return a
    apex = np.array([v for v in lm["apex"].values()], np.float64)
    p0 = apex[:, 2] - wall_at(apex[:, 0], lm)
    lo, hi = 0.0, 4.0 * a["rise"] + 0.05
    for _ in range(SOLVE_STEPS):
        a["D"] = 0.5 * (lo + hi)
        _x, y, _p = _flow(apex[:, 0] - float(lm["centre_x"]), apex[:, 1].copy(), p0, a)
        if float(np.mean(y - apex[:, 1])) < a["rise"]:
            lo = a["D"]
        else:
            hi = a["D"]
    a["D"] = 0.5 * (lo + hi)
    return a


def velocity(X, y, p, a: Dict[str, float]):
    """``(v_x, v_y, v_p)`` of the module docstring at ``X`` (x - centre_x), ``y``, ``p`` (z - wall) for the
    ``amounts`` ``a``."""
    gp = _smoothstep(p, -BACK_M, FRONT_M)
    g = _smoothstep_i(p, -BACK_M, FRONT_M)
    gc = FILL_CAP_M * np.tanh(g / FILL_CAP_M)
    rise, fall = _smoothstep(y, a["lo0"], a["lo1"]), 1.0 - _ramp(y, a["up0"], a["cap"], RAMP_ROUND_M)
    m = rise * fall
    dm = _smoothstep_d(y, a["lo0"], a["lo1"]) * fall - rise * _ramp_d(y, a["up0"], a["cap"], RAMP_ROUND_M)
    ax = np.abs(X)
    k = 1.0 - _smoothstep(ax, a["side0"], a["side1"])
    side = _smoothstep(ax, *GATHER_SIDE_M)
    s = X * (1.0 - side)
    ds = (1.0 - side) - ax * _smoothstep_d(ax, *GATHER_SIDE_M)
    return (-a["G"] * s * m * gp,
            a["D"] * m * k * gp,
            -a["D"] * dm * k * gc + a["G"] * ds * m * g)


def _flow(X, y, p, a: Dict[str, float]):
    """``(X, y, p)`` carried by ``velocity`` over unit time (``STEPS`` classic Runge-Kutta steps)."""
    h = 1.0 / STEPS
    for _ in range(STEPS):
        k1 = velocity(X, y, p, a)
        k2 = velocity(X + h / 2 * k1[0], y + h / 2 * k1[1], p + h / 2 * k1[2], a)
        k3 = velocity(X + h / 2 * k2[0], y + h / 2 * k2[1], p + h / 2 * k2[2], a)
        k4 = velocity(X + h * k3[0], y + h * k3[1], p + h * k3[2], a)
        X = X + h / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        y = y + h / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
        p = p + h / 6 * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2])
    return X, y, p


def displace(positions, lm: Dict[str, Any], lift: float, a: Optional[Dict[str, float]] = None) -> np.ndarray:
    """The shaped positions: the flow of ``velocity`` over unit time; vertices the field does not reach come back
    unchanged. ``a``: the ``amounts`` when already solved."""
    P = np.array(positions, np.float64, copy=True).reshape(-1, 3)
    a = a or amounts(lm, lift)
    if a["D"] <= 0.0 and a["G"] <= 0.0:
        return P
    cx = float(lm["centre_x"])
    p0 = P[:, 2] - wall_at(P[:, 0], lm)
    # only what the field can reach is integrated: in front of the wall - BACK_M, inside the side fades, between the
    # ramps of m (the rest has v = 0 everywhere along its path, which never leaves where it is)
    live = (p0 > -BACK_M) & (np.abs(P[:, 0] - cx) < max(a["side1"], GATHER_SIDE_M[1])) \
        & (P[:, 1] > a["lo0"]) & (P[:, 1] < a["cap"])
    X, y, p = _flow(P[live, 0] - cx, P[live, 1].copy(), p0[live], a)
    P[live, 0] = X + cx
    P[live, 1] = y
    P[live, 2] = p + wall_at(X + cx, lm)
    return P


def record(lm: Dict[str, Any], lift: float) -> Dict[str, Any]:
    """What a drape record keeps (``shaping``) and the assembly re-applies."""
    return {"version": VERSION, "lift": round(float(lift), 4), "landmarks": dict(lm)}


def shape_glb(blob: bytes, rec: Dict[str, Any]) -> bytes:
    """``blob`` (a body GLB, or an assembled one) with every skinned non-garment primitive — the body and its
    extension parts alike, a part that stayed where it was would stand through the piece — shaped by ``rec``
    (``record``). The POSITION (and NORMAL, recomputed for the faces touching a moved vertex) bytes are overwritten
    in place, so the buffer layout, skin, UVs and morph targets stay byte-identical; the accessors' min/max follow.
    The skin joints whose bind position lies in the shaped region move with the tissue (``_shape_joints``): a chest
    bone left at its old place would stand outside the shaped surface, and the extension motion would swing the
    tissue round a point in front of it.
    Returns ``blob`` unchanged when nothing moves."""
    import struct
    from app.core import glb_mesh
    if len(blob) < 20 or blob[:4] != b"glTF":
        raise ValueError("not a GLB")
    jlen = struct.unpack_from("<I", blob, 12)[0]
    gltf = json.loads(blob[20:20 + jlen].decode("utf-8"))
    bin_at = 20 + jlen + 8
    bin_len = struct.unpack_from("<I", blob, 20 + jlen)[0]
    data = bytearray(blob[bin_at:bin_at + bin_len])
    lm, lift = rec["landmarks"], float(rec["lift"])
    views, accessors = gltf.get("bufferViews") or [], gltf.get("accessors") or []

    def locate(index: int):
        acc = accessors[index]
        if acc.get("componentType") != 5126 or acc.get("type") != "VEC3" or "bufferView" not in acc \
                or "sparse" in acc:
            raise ValueError("a body POSITION / NORMAL accessor must be a dense float VEC3")
        view = views[acc["bufferView"]]
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        stride = int(view.get("byteStride") or 12)
        return start, stride, int(acc["count"])

    def read(index: int) -> np.ndarray:
        start, stride, n = locate(index)
        raw = np.frombuffer(bytes(data), np.uint8, count=stride * (n - 1) + 12, offset=start)
        return np.lib.stride_tricks.as_strided(raw.view(np.uint8), (n, 12), (stride, 1)).copy().view("<f4") \
            .reshape(n, 3).astype(np.float64)

    def write(index: int, values: np.ndarray) -> None:
        start, stride, n = locate(index)
        rows = np.asarray(values, "<f4").reshape(n, 3)
        for k in range(n):
            data[start + k * stride:start + k * stride + 12] = rows[k].tobytes()

    def faces_of(prim: dict, n: int) -> np.ndarray:
        if "indices" not in prim:
            return np.arange(n - n % 3, dtype=np.int64).reshape(-1, 3)
        acc = accessors[prim["indices"]]
        view = views[acc["bufferView"]]
        dt = {5121: "u1", 5123: "<u2", 5125: "<u4"}[acc["componentType"]]
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        return np.frombuffer(bytes(data), dt, count=int(acc["count"]), offset=start).astype(np.int64).reshape(-1, 3)

    skinned = {node["mesh"] for node in gltf.get("nodes") or []
               if "mesh" in node and "skin" in node and not glb_mesh._is_garment_node(node)}
    done: set = set()
    changed = False
    for mi, mesh in enumerate(gltf.get("meshes") or []):
        if mi not in skinned:
            continue
        for prim in mesh.get("primitives") or []:
            pi = prim.get("attributes", {}).get("POSITION")
            if pi is None or pi in done:
                continue
            done.add(pi)
            P = read(pi)
            Q = displace(P, lm, lift)
            mask = np.any(np.abs(Q - P) > 1e-7, axis=1)
            if not mask.any():
                continue
            changed = True
            write(pi, Q)
            accessors[pi]["min"] = [float(v) for v in Q.min(axis=0).astype(np.float32)]
            accessors[pi]["max"] = [float(v) for v in Q.max(axis=0).astype(np.float32)]
            ni = prim.get("attributes", {}).get("NORMAL")
            if ni is not None:
                write(ni, _normals(Q, faces_of(prim, len(Q)), read(ni), mask))
    moved_joints = _shape_joints(gltf, data, views, accessors, lm, lift)
    if not changed and not moved_joints:
        return blob
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * ((4 - len(text) % 4) % 4)
    rest = blob[bin_at + bin_len + ((4 - bin_len % 4) % 4):]
    body = (struct.pack("<I", len(text)) + b"JSON" + text + struct.pack("<I", bin_len) + b"BIN\0" + bytes(data)
            + b"\0" * ((4 - bin_len % 4) % 4) + rest)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def _normals(P, faces, old, moved_mask) -> np.ndarray:
    """Area-weighted vertex normals of ``P``; only the moved vertices take them."""
    F = np.asarray(faces, np.int64)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    acc = np.zeros_like(P)
    for k in range(3):
        np.add.at(acc, F[:, k], fn)
    length = np.linalg.norm(acc, axis=1, keepdims=True)
    new = np.where(length > 1e-12, acc / np.maximum(length, 1e-12), old)
    touched = np.asarray(moved_mask, bool)          # review L8: an unmoved vertex keeps its stored normal
    out = np.array(old, np.float64, copy=True)
    out[touched] = new[touched]
    return out


def _shape_joints(gltf: dict, data: bytearray, views: list, accessors: list, lm: Dict[str, float],
                  lift: float) -> int:
    """Move the bind position of every joint of skin 0 that the field displaces (in place: the inverse bind matrix
    in ``data`` and the node's ``translation`` in ``gltf``), keeping each joint's skin matrix at rest (node world x
    inverse bind) unchanged, so the rest pose still shows the shaped bind positions. A child joint keeps its world
    place (its local translation is re-derived). Returns how many joints moved."""
    from app.core.glb_mesh import _local_matrix
    skins = gltf.get("skins") or []
    if not skins or "inverseBindMatrices" not in skins[0]:
        return 0
    nodes = gltf.get("nodes") or []
    joints = list(skins[0].get("joints") or [])
    acc = accessors[skins[0]["inverseBindMatrices"]]
    if acc.get("componentType") != 5126 or acc.get("type") != "MAT4" or "bufferView" not in acc:
        return 0
    view = views[acc["bufferView"]]
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride") or 64)
    ibm = [np.frombuffer(bytes(data[start + k * stride:start + k * stride + 64]), "<f4").astype(np.float64)
           .reshape(4, 4).T for k in range(len(joints))]
    bind = np.array([np.linalg.inv(m)[:3, 3] for m in ibm])
    target = displace(bind, lm, lift)
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}
    # a chain that ends in the shaped tissue moves as a unit: an unmoved joint whose ONLY child moved takes the
    # child's displacement, up the chain (a chest chain's root sits behind the wall; left there, its segment to the
    # moved end turned and its end reached out of the shaped surface — the drape's poke rays start on that segment)
    slot = {j: k for k, j in enumerate(joints)}
    moved_by = {k: target[k] - bind[k] for k in range(len(joints)) if np.linalg.norm(target[k] - bind[k]) > 1e-7}
    for k in list(moved_by):
        j, delta = joints[k], moved_by[k]
        while j in parent and parent[j] in slot and len(nodes[parent[j]].get("children") or []) == 1:
            j = parent[j]
            if slot[j] in moved_by:
                break
            moved_by[slot[j]] = delta
            target[slot[j]] = bind[slot[j]] + delta
    move = sorted(moved_by)
    if not move:
        return 0

    def world(i: int, cache: dict) -> np.ndarray:
        if i not in cache:
            local = _local_matrix(nodes[i])
            cache[i] = local if i not in parent else world(parent[i], cache) @ local
        return cache[i]
    before: dict = {}
    for i in range(len(nodes)):
        world(i, before)
    after = dict(before)
    for k in move:
        j = joints[k]
        skin = before[j] @ ibm[k]                     # the joint's skin matrix at rest — kept
        b2 = np.linalg.inv(ibm[k])
        b2[:3, 3] = target[k]
        after[j] = skin @ b2
        ibm[k] = np.linalg.inv(b2)
        data[start + k * stride:start + k * stride + 64] = np.asarray(ibm[k].T, "<f4").tobytes()
    touched = {joints[k] for k in move}
    touched |= {c for j in list(touched) for c in nodes[j].get("children") or []}
    for i in sorted(touched):
        local = (np.linalg.inv(after[parent[i]]) @ after[i]) if i in parent else after[i]
        node = nodes[i]
        if "matrix" in node:
            node["matrix"] = [float(v) for v in local.T.ravel()]
        else:
            node["translation"] = [float(v) for v in local[:3, 3]]
    return len(move)


# --- the worn set ---------------------------------------------------------------------------------------------

#: The template kinds whose drape reaches the chest: they drape on the shaped body when the worn set shapes it.
CHEST_KINDS = ("top", "dress", "jacket", "bra")


def _template_params(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    op = (item or {}).get("outfit_piece") or {}
    if op.get("mesh_mode") != "template":
        return None
    params = (op.get("template") or {}).get("params")
    return params if isinstance(params, dict) else None


def effective_lift(item: Optional[Dict[str, Any]]) -> float:
    """A piece's lift as the motion reads it (``extension_rig.piece_lift`` against the slot defaults the packages
    declare, ``clothing_lift_slots``): its own ``outfit_piece.lift``, else the slot default; a partial cover half.
    0 when no slot of it carries a lift (and so the item form offers none)."""
    from app.core.extension_rig import clothing_lift_slots, piece_lift
    op = (item or {}).get("outfit_piece") or {}
    own = op.get("lift")
    if own is not None:
        own = lift_of(item)
    full = set(op.get("slots") or []) | set(op.get("covers") or [])
    value = piece_lift(own, full, set(op.get("partially_covers") or []), clothing_lift_slots())
    return min(1.0, max(0.0, float(value))) if value is not None else 0.0


def shapes_chest(item: Optional[Dict[str, Any]]) -> bool:
    """Whether ``item`` is a template top / dress whose effective lift shapes the chest under it — of the PIECE; a
    character the shaping does not apply to (``character_shaped``) is gated by the caller / ``set_lift``."""
    params = _template_params(item)
    return bool(params) and applies(params, effective_lift(item))


def character_shaped(character_name: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    """User ruling 2026-11-23: a male character never gets the chest shaping — whatever his pieces say, an explicit
    lift included (``base_skin.is_male`` on the profile's ``gender``). Any other or an unset gender keeps it (a small
    chest is lifted too). ``profile``: the one the caller already holds, else read here."""
    from app.core.base_skin import is_male
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    return not is_male(profile)


def set_lift(item_ids, items: Optional[Dict[str, Dict[str, Any]]] = None, *, character_name: str,
             profile: Optional[Dict[str, Any]] = None) -> float:
    """Review M2: the shaping is a property of the WORN SET — the strongest effective lift among its shaping
    template pieces (``shapes_chest``); 0 when none shapes. ``items``: already loaded items by id. THE one place
    the wearer decides: 0 for a character the shaping does not apply to (``character_shaped``) — every drape, cut,
    assembly and accessory fit reads its shaping from here (``key_tokens`` / ``prepare`` -> the drape records)."""
    from app.models.inventory import get_item
    best = 0.0
    for iid in sorted(set(item_ids or ())):
        item = (items or {}).get(iid) or get_item(iid)
        if shapes_chest(item):
            best = max(best, effective_lift(item))
    if best > 0 and not character_shaped(character_name, profile):
        return 0.0
    return best


def key_tokens(item_id: str, item: Optional[Dict[str, Any]], lower, *, character_name: str) -> list:
    """What ``garment_template.key_for`` folds into the drape key of ``item_id`` worn with ``lower`` (the other
    worn mesh pieces) by ``character_name``: [] when the set does not shape for that character (``set_lift``) or
    the piece does not reach the chest (its key stays what it was before A228), else the one ``signature`` token
    of the set's lift."""
    params = _template_params(item)
    if not params or params.get("kind") not in CHEST_KINDS:
        return []
    lift = set_lift(list(lower or []) + [item_id], {item_id: item} if item else None, character_name=character_name)
    if lift <= 0:
        return []
    raw = json.dumps({"v": VERSION, "lift": round(float(lift), 4)}, sort_keys=True)
    return ["shape:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]]


def prepare(body_glb, item_id: str, item: Optional[Dict[str, Any]], lower, scratch, *, character_name: str):
    """``(body path, shaping record or None, note)`` for a drape of ``character_name``'s piece: a chest piece of a
    shaping set (``key_tokens``)
    drapes on a shaped copy of the plain body written into ``scratch``; every other piece on ``body_glb`` itself.
    A body whose chest cannot be measured (review L9) drapes unshaped with ``note`` saying so."""
    from pathlib import Path
    from app.core import glb_mesh
    from app.core.garment_template import measure_body
    if not key_tokens(item_id, item, lower, character_name=character_name):
        return Path(body_glb), None, ""
    lift = set_lift(list(lower or []) + [item_id], {item_id: item} if item else None, character_name=character_name)
    blob = Path(body_glb).read_bytes()
    try:
        lm = landmarks(glb_mesh.body_arrays(blob).positions, measure_body(blob))
    except (ValueError, KeyError) as exc:
        return Path(body_glb), None, f"chest not shaped: {exc}"
    rec = record(lm, lift)
    target = Path(scratch) / "shaped_body.glb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(shape_glb(blob, rec))
    return target, rec, ""


def worn_record(garments) -> Optional[Dict[str, Any]]:
    """The shaping an assembly applies to the shown body: of the worn template drapes whose record carries one
    (``garment_template`` writes ``shaping``), the one with the strongest lift — never two added up. A worn set
    drapes all its chest pieces with the same record (``set_lift``), so they agree."""
    best = None
    for g in garments or []:
        rec = (g.get("record") or {}).get("shaping") if g.get("template") else None
        if isinstance(rec, dict) and rec.get("version") == VERSION and float(rec.get("lift") or 0) > 0:
            if best is None or float(rec["lift"]) > float(best["lift"]):
                best = rec
    return best


def shape_collision(collision: Optional[Dict[str, Any]], rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Review M3: the collision record of the shown body with its capsules shaped like the body — every bind-space
    endpoint (``a_pos`` / ``b_pos``) displaced; the radius stays (v4 keeps the volume in front of the wall within 5 %
    — ``FILL_CAP_M`` — and turns no face over, so a capsule's girth stays a fair stand-in). Other entries stay. None
    in, None out."""
    if not isinstance(collision, dict):
        return collision
    import copy
    out = copy.deepcopy(collision)
    lm, lift = rec["landmarks"], float(rec["lift"])
    for cap in out.get("capsules") or []:
        ends = [k for k in ("a_pos", "b_pos") if isinstance(cap.get(k), list) and len(cap[k]) == 3]
        if not ends:
            continue
        pts = np.array([cap[k] for k in ends], np.float64)
        moved = displace(pts, lm, lift)
        if not np.any(np.abs(moved - pts) > 1e-7):
            continue
        for k, v in zip(ends, moved):
            cap[k] = [round(float(c), 4) for c in v]
    out["shaping"] = {"version": rec.get("version"), "lift": rec.get("lift")}
    return out


def previous_drape(character_name: str, item_id: str, item: Optional[Dict[str, Any]], *, base_sha: str,
                   params: Dict[str, Any], lower) -> Optional[Dict[str, Any]]:
    """Review M5: while the drape of a changed SHAPING key is not built yet, the newest accepted drape of the piece
    on the same base, with the same parameters and the same other worn pieces, is served instead (its own record
    carries its own shaping, so the assembly shows the body it was draped on) — the piece never drops off the
    figure in between. Only a drape whose shaping differs from the set's now (its lift, or none) stands in — any
    other change of the key leaves the piece off as before. ``{tsig, path, record}`` or None."""
    from app.core.garment_store import read_record
    from app.core.garment_template import templates_dir
    folder = templates_dir(character_name)
    if not folder.is_dir():
        return None
    lift_now = round(set_lift(list(lower or []) + [item_id], {item_id: item} if item else None,
                              character_name=character_name), 4) \
        if key_tokens(item_id, item, lower, character_name=character_name) else 0.0
    best = None
    for meta in folder.glob(f"{item_id}_*.json"):
        rec = read_record(meta)
        glb = meta.with_suffix(".glb")
        if (rec.get("accepted") is not True or not glb.is_file() or rec.get("base_model_sha256") != base_sha
                or rec.get("params") != params or sorted(rec.get("lower") or []) != sorted(lower or [])
                or round(float((rec.get("shaping") or {}).get("lift") or 0.0), 4) == lift_now):
            continue
        stamp = str(rec.get("created_at") or "")
        if best is None or stamp > best[0]:
            best = (stamp, {"tsig": rec.get("tsig"), "path": glb, "record": rec})
    return best[1] if best else None
