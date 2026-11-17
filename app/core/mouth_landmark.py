"""The MOUTH OPENING measured on a rigged humanoid body (collision version 9, Ruling A193).

The renderers build the mouth channel (``@anima/scene-render`` ``contactTarget.ts`` ``mouthChannel``) on the head
bone. Before A193 its opening was a fixed offset from the head joint (0.5 L forward, 0.15 L up) and its axis the
face normal straight back. Measured on two mesher-built bodies the mouth lay 30-58 mm BELOW that point and 10-25 mm
in front of it, and the axis ran horizontally into the back of the head instead of toward the throat. This module
measures both in bind space; the collision record carries the result (``mouth``) bound to the head joint, so the
channel follows every head turn and tilt.

Method (bind space, the body frame of ``collision_channels.body_frame``: side / up / front):

1. PROFILE: the body vertices within ``BAND_M`` of the head joint's mid-plane (side), binned along ``up`` relative to
   the head joint in ``BIN_M`` bins over ``[V_MIN, V_MAX]``; per bin the front-most offset along ``front`` (the face's
   outline seen from the side), then a running max over ``DILATE`` bins either way (a thin band leaves holes where
   only the back of the head is hit).
2. NOSE TIP v_n: the profile's maximum over ``NOSE_WINDOW`` (above the chin, below the brow).
3. CHIN EDGE v_c: going down from v_n, the first bin whose profile lies more than ``CHIN_DROP_M`` behind the nose
   tip — the underside of the chin, where the outline falls back to the neck.
4. MOUTH: v_m = v_c + ``MOUTH_FRACTION`` · (v_n − v_c); the opening centre O = the head joint's side position, v_m
   up, and the profile's front at v_m (the lips' surface).
5. AXIS: from O toward the throat — the Neck joint (the oral cavity runs back, the pharynx down; the straight line
   from the lips to the top of the neck lies between both).

``locate_mouth`` returns ``{"a": <head joint name>, "a_pos", "b_pos"}`` with ``b_pos`` = O + axis · ``AXIS_LENGTH_M``
(only the direction is read), or a reason string when the head, the neck or the profile does not allow it — the
renderers then keep the head-bone formula.
"""
from __future__ import annotations

from typing import Any, Dict, Union

import numpy as np

BAND_M = 0.008
BIN_M = 0.003
V_MIN, V_MAX = -0.15, 0.15
DILATE = 2
NOSE_WINDOW = (-0.05, 0.08)
CHIN_DROP_M = 0.05
MOUTH_FRACTION = 0.5
AXIS_LENGTH_M = 0.1
MIN_BAND_VERTICES = 40


def locate_mouth(names, index_of: Dict[str, int], positions: np.ndarray, body_positions: np.ndarray,
                 unit: float = 1.0) -> Union[Dict[str, Any], str]:
    """The mouth record of a body (module docstring) or the reason there is none. ``positions`` the bind joint
    positions, ``body_positions`` the body vertices (bind space), ``unit`` metres per bind unit."""
    from app.core.collision_channels import FRAME_JOINTS, body_frame
    from app.core.rig_contract import norm_bone_name
    head, neck = index_of.get(norm_bone_name("Head")), index_of.get(norm_bone_name("Neck"))
    if head is None or neck is None:
        return "joint Head or Neck missing"
    try:
        frame = body_frame({n: positions[index_of[norm_bone_name(n)]] for n in FRAME_JOINTS
                            if norm_bone_name(n) in index_of})
    except ValueError as exc:
        return f"No body frame: {exc}"
    scale = 1.0 / unit if unit > 0 else 1.0
    H = positions[head]
    rel = np.asarray(body_positions, np.float64) - H
    s, v, w = rel @ frame["side"], rel @ frame["up"], rel @ frame["front"]
    band = (np.abs(s) < BAND_M * scale) & (v >= V_MIN * scale) & (v < V_MAX * scale)
    if int(band.sum()) < MIN_BAND_VERTICES:
        return "too few face vertices on the mid-plane"
    edges = np.arange(V_MIN, V_MAX + 1e-9, BIN_M) * scale
    bins = np.clip(np.searchsorted(edges, v[band], side="right") - 1, 0, len(edges) - 2)
    raw = np.full(len(edges) - 1, -np.inf)
    np.maximum.at(raw, bins, w[band])
    profile = np.array([raw[max(0, i - DILATE):i + DILATE + 1].max() for i in range(len(raw))])
    centres = (edges[:-1] + edges[1:]) / 2
    window = (centres >= NOSE_WINDOW[0] * scale) & (centres <= NOSE_WINDOW[1] * scale) & np.isfinite(profile)
    if not window.any():
        return "no face outline in front of the head joint"
    nose = int(np.flatnonzero(window)[np.argmax(profile[window])])
    chin = None
    for i in range(nose, -1, -1):
        if profile[i] < profile[nose] - CHIN_DROP_M * scale:
            chin = i
            break
    if chin is None:
        return "no chin edge below the nose"
    v_m = centres[chin] + MOUTH_FRACTION * (centres[nose] - centres[chin])
    m = int(np.clip(np.searchsorted(edges, v_m, side="right") - 1, 0, len(raw) - 1))
    if not np.isfinite(profile[m]):
        return "no lips on the mid-plane"
    O = H + frame["up"] * v_m + frame["front"] * profile[m]
    toward = positions[neck] - O
    length = float(np.linalg.norm(toward))
    if length < 1e-6:
        return "degenerate mouth axis"
    B = O + toward / length * AXIS_LENGTH_M * scale
    return {"a": str(names[head]), "a_pos": [round(float(x), 4) for x in O],
            "b_pos": [round(float(x), 4) for x in B]}
