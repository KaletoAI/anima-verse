"""A238: the ring — a band round one finger, sized from the SKELETON (user ruling 2026-11-20); the mesh gives only
the body's height, which scales the clamp range, and the hand's skin box of the gate.

Why not from the mesh (A234, two rounds): in the bind pose the fingers are fused by webbing, so a section across a
finger runs into its neighbours (11–37 cm round) and the sparse finger skin (~40 points per span) cannot say which
surface is the finger's own. The ring is therefore a FIXED size per body, computed from two bone measures:

- the hand width ``w`` — the distance between the Index1 and Pinky1 bone heads (the index and little knuckles);
- the finger's proximal bone length ``L`` — ``<Side>Hand<Finger>1 -> 2`` (the thumb: ``Thumb2 -> 3``, its Thumb1
  is the metacarpal).

The ratio is taken from a reference hand: the inner radius of the median adult ring per finger (ring-size tables:
inner diameters thumb 20.5, index 18.0, middle 18.5, ring 17.5, little 15.5 mm -> ``RADIUS_REF_MM``) on the median
rigged hand of this pipeline (14 plain bodies measured 2026-11-20: ``w`` median 59.65 mm -> ``HAND_WIDTH_REF_MM``
60; ``L`` medians thumb 32.05, index 34.0, middle 34.6, ring 31.5, little 26.0 mm, rounded to 0.5 mm ->
``BONE_REF_MM`` thumb 32.0, middle 34.5 — under 0.2 % on a radius). A body's
inner radius scales the reference by the geometric mean of its two ratios::

    r = RADIUS_REF_MM[finger] * sqrt((w / HAND_WIDTH_REF_MM) * (L / BONE_REF_MM[finger]))

clamped to ``RADIUS_RANGE_MM`` (7–11 mm) times ``height / HEIGHT_REF_M`` (the body's height — the vertical extent
of the mesh, not a bone measure — so a small figure gets small rings and a tall one large). Worked example — a body exactly at the references (w 60, L of the ring finger
31.5, height 1.70 m): r = 8.75 · sqrt(1 · 1) = 8.75 mm, inside 7–11 → 8.75 mm (inner diameter 17.5 mm).

The ring is centred on the proximal bone at ``ring.along`` of the way from its head (the knuckle), its plane across
the bone, and moves rigidly with that bone (weight 1.0). It is NOT tested against the skin: the webbing would refuse
every ring (A234). The only gate (``check``): the centre lies in the box of that hand's skin and the radius is finite
and inside its range. Pure numpy; no I/O.
"""
from typing import Any, Dict, Tuple

import numpy as np

#: Inner radius (mm) of the median adult ring per finger (module docstring).
RADIUS_REF_MM: Dict[str, float] = {"thumb": 10.25, "index": 9.0, "middle": 9.25, "ring": 8.75, "little": 7.75}
#: The median rigged hand (module docstring): knuckle-to-knuckle width and proximal bone length per finger (mm).
HAND_WIDTH_REF_MM = 60.0
BONE_REF_MM: Dict[str, float] = {"thumb": 32.0, "index": 34.0, "middle": 34.5, "ring": 31.5, "little": 26.0}
#: The plausible inner radius at ``HEIGHT_REF_M`` (mm), scaled by the body's height.
RADIUS_RANGE_MM: Tuple[float, float] = (7.0, 11.0)
HEIGHT_REF_M = 1.70
#: The rig's finger names (``accessory_spec.FINGERS`` -> bone stem) and the proximal bone's (start, end) number.
FINGER_BONES: Dict[str, str] = {"thumb": "thumb", "index": "index", "middle": "middle", "ring": "ring",
                                "little": "pinky"}
PROXIMAL: Dict[str, Tuple[int, int]] = {"thumb": (2, 3)}
#: Angles round the band.
SEGMENTS = 48
#: The hand-skin box of the gate is grown by this much (metres).
BOX_MARGIN_M = 0.002
#: A proximal bone shorter than this is no finger (metres).
MIN_BONE_M = 0.008


def _bones(bones: Dict[str, Any]) -> Dict[str, np.ndarray]:
    return {str(k).split(":")[-1].lower(): np.asarray(v, np.float64) for k, v in bones.items()}


def _bone(norm: Dict[str, np.ndarray], key: str) -> np.ndarray:
    if key not in norm:
        raise KeyError(key)
    return norm[key]


def bone_names(finger: str, side: str) -> Tuple[str, str]:
    """The normalised names of the proximal bone's head and tail joints of ``finger`` on ``side``."""
    stem = FINGER_BONES[finger]
    a, b = PROXIMAL.get(finger, (1, 2))
    return f"{side}hand{stem}{a}", f"{side}hand{stem}{b}"


def size(bones: Dict[str, Any], finger: str, side: str, height_m: float) -> Dict[str, Any]:
    """The inner radius of a ring on ``finger`` of the ``side`` hand (module docstring): ``{radius_m, estimate_mm,
    range_mm, clamped, hand_width_mm, bone_length_mm}``. ``KeyError`` naming a missing bone; ``ValueError`` when the
    bones give no finger."""
    norm = _bones(bones)
    head, tail = bone_names(finger, side)
    length = float(np.linalg.norm(_bone(norm, tail) - _bone(norm, head)))
    width = float(np.linalg.norm(_bone(norm, f"{side}handindex1") - _bone(norm, f"{side}handpinky1")))
    if not (length >= MIN_BONE_M and width >= MIN_BONE_M and height_m > 0.3):
        raise ValueError(f"the {finger} finger's bones are too short to size a ring "
                         f"({length * 1000:.1f} mm long, hand {width * 1000:.1f} mm wide)")
    est = RADIUS_REF_MM[finger] * float(np.sqrt((width * 1000.0 / HAND_WIDTH_REF_MM)
                                                * (length * 1000.0 / BONE_REF_MM[finger])))
    scale = float(height_m) / HEIGHT_REF_M
    lo, hi = RADIUS_RANGE_MM[0] * scale, RADIUS_RANGE_MM[1] * scale
    radius = min(max(est, lo), hi)
    return {"radius_m": radius / 1000.0, "estimate_mm": round(est, 3), "range_mm": [lo, hi],
            "clamped": bool(est < lo or est > hi), "hand_width_mm": round(width * 1000.0, 2),
            "bone_length_mm": round(length * 1000.0, 2)}


def frame(bones: Dict[str, Any], finger: str, side: str, along: float) -> Dict[str, Any]:
    """``{centre, axis, front, bone}``: the ring's centre ``along`` of the way down the proximal bone, its axis the
    bone's direction (toward the finger tip), ``front`` the back of the hand (+Y in the T-pose) made square to it."""
    norm = _bones(bones)
    head, tail = bone_names(finger, side)
    a, b = _bone(norm, head), _bone(norm, tail)
    axis = (b - a) / max(float(np.linalg.norm(b - a)), 1e-12)
    front = np.array([0.0, 1.0, 0.0]) - axis[1] * axis
    if np.linalg.norm(front) < 1e-6:
        front = np.cross(axis, [1.0, 0.0, 0.0])
    return {"centre": a + float(along) * (b - a), "axis": axis, "front": front / np.linalg.norm(front),
            "bone": head}


def directions(fr: Dict[str, Any], n: int = SEGMENTS) -> np.ndarray:
    """``(n, 3)`` unit directions round the axis, angle 0 = ``front``."""
    side = np.cross(fr["axis"], fr["front"])
    phi = 2 * np.pi * np.arange(n) / n
    return np.cos(phi)[:, None] * fr["front"][None] + np.sin(phi)[:, None] * side[None]


def band(fr: Dict[str, Any], radius_m: float, width_m: float, thickness_m: float
         ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The closed band (``accessory_band.band_mesh``): inner wall at ``radius_m`` from the axis, ``width_m`` along
    it, ``thickness_m`` deep. ``(V (n·4, 3), F (n·8, 3), N)``."""
    from app.core.accessory_band import band_mesh
    dirs = directions(fr)
    offsets = np.array([-width_m / 2, width_m / 2])
    return band_mesh(fr, offsets, np.full((2, len(dirs)), float(radius_m)), dirs, float(thickness_m))


def centre_line(fr: Dict[str, Any], radius_m: float, thickness_m: float, n: int = SEGMENTS) -> np.ndarray:
    """The band's middle circle (the dialog's preview dots)."""
    return fr["centre"][None] + (float(radius_m) + float(thickness_m) / 2) * directions(fr, n)


def check(centre: np.ndarray, hand_points: np.ndarray, sized: Dict[str, Any]) -> None:
    """The ring's gate (module docstring): ``ValueError`` when the centre lies outside the box of the hand's skin
    (``hand_points``, grown by ``BOX_MARGIN_M``) or the radius is not finite / outside its range."""
    why = []
    r_mm = float(sized["radius_m"]) * 1000.0
    lo, hi = sized["range_mm"]
    if not np.isfinite(r_mm) or not lo - 1e-6 <= r_mm <= hi + 1e-6:
        why.append(f"inner radius {r_mm:.1f} mm, expected {lo:.1f}–{hi:.1f} mm")
    if not len(hand_points):
        why.append("the hand has no skin")
    else:
        box_lo = hand_points.min(0) - BOX_MARGIN_M
        box_hi = hand_points.max(0) + BOX_MARGIN_M
        if not bool(np.all((centre >= box_lo) & (centre <= box_hi))):
            why.append("its centre lies outside the hand")
    if why:
        raise ValueError("The ring does not fit this body (" + "; ".join(why) + ")")
